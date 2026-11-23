"""Auth0 cutover contract: paired runtime config, narrow apply and durable recovery."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bootstrap_swarm import deploy_infrastructure, plan_release
from deploy_service import reconcile
from scoped_deploy import ScopedSwarm, require_auth_only, scoped_document
from stack_release import select_release, ui_configuration, ui_environment, update_service, validate_manifest, write_record
from stack_runtime import render_release
from test_expanded_release import InfrastructureSwarm, expanded
from verify_public_ingress import check_bearer_required

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = json.loads((ROOT / 'auth0/development.public.json').read_text())


def previous_release():
    original = expanded(ui=True, assets=False)
    value = plan_release(original, 'jjt-snippets-dev.duckdns.org', tls=True)
    value['checks'] = original['checks']
    return value


def authenticated(previous):
    value = copy.deepcopy(previous)
    value['auth'] = {'mode': 'auth0', **{k: PUBLIC[k] for k in ('issuer', 'audience')}}
    value['ui'] = {'auth': {k: PUBLIC[k] for k in ('domain', 'client_id', 'audience')}}
    return value


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.previous = previous_release()
        self.previous['ui'] = {'dev_actor': 'dev-test'}
        self.previous['apm'] = {'enabled': True}
        self.candidate = authenticated(self.previous)

    def test_public_ui_config_matches_api_and_survives_image_deploys(self):
        validate_manifest(self.candidate)
        identity = ui_configuration(self.candidate)['identity']
        self.assertEqual(identity, {'mode': 'auth0', 'domain': PUBLIC['domain'],
                                   'clientId': PUBLIC['client_id'], 'audience': PUBLIC['audience']})
        for service in self.candidate['images']:
            changed = update_service(self.candidate, service, self.candidate['images'][service])
            self.assertEqual(ui_configuration(changed), ui_configuration(self.candidate))
            self.assertEqual(changed['apm'], {'enabled': True})
        environment = ui_environment(self.candidate)
        self.assertEqual(environment['UI_DEV_ACTOR'], '')
        self.assertEqual(environment['UI_AUTH_DOMAIN'], PUBLIC['domain'])
        self.assertEqual(environment['UI_AUTH_CLIENT_ID'], PUBLIC['client_id'])
        self.assertEqual(environment['UI_AUTH_AUDIENCE'], PUBLIC['audience'])

    def test_partial_secret_mixed_actor_and_mismatched_parameters_are_rejected(self):
        changes = [lambda c: c['ui']['auth'].pop('client_id'),
                   lambda c: c['ui']['auth'].update(client_secret='forbidden'),
                   lambda c: c['ui'].update(dev_actor='dev-other'),
                   lambda c: c['ui']['auth'].update(domain='other.auth0.com'),
                   lambda c: c['ui']['auth'].update(audience='https://other/api'),
                   lambda c: c['ui']['auth'].update(domain='https://wrong/'),
                   lambda c: c['ui']['auth'].update(client_id='short'),
                   lambda c: c.update(auth={'mode': 'dev'})]
        for change in changes:
            value = copy.deepcopy(self.candidate)
            change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_manifest(value)

    def test_auth_scope_refuses_images_apm_storage_proxy_and_prod(self):
        require_auth_only(self.previous, self.candidate)
        require_auth_only(self.previous, self.previous)
        for change in [lambda c: c.update(apm={'enabled': False}),
                       lambda c: c['images'].update(ui=c['images']['ui'].replace('c' * 64, 'd' * 64)),
                       lambda c: c['infrastructure']['nginx'].update(hostname='other.test'),
                       lambda c: c.update(environment='prod'),
                       lambda c: c.update(storage_provider='asset')]:
            value = copy.deepcopy(self.candidate)
            change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                require_auth_only(self.previous, value)

    def test_real_render_preserves_apm_and_selects_only_snippets_and_ui(self):
        before, after = render_release(self.previous), render_release(self.candidate)
        for service, spec in before['services'].items():
            if service not in ('ui', 'snippets-service'):
                self.assertEqual(after['services'][service], spec)
        old = before['services']['snippets-service']
        new = after['services']['snippets-service']
        self.assertEqual(old['secrets'], new['secrets'])
        for key, value in old['environment'].items():
            if not key.startswith('AUTH_') and key != 'SNIPPETS_CORS_ALLOWED_ORIGINS':
                self.assertEqual(new['environment'][key], value)
        self.assertEqual(new['environment']['NEW_RELIC_ENABLED'], 'true')
        self.assertEqual(new['environment']['SNIPPETS_CORS_ALLOWED_ORIGINS'], 'https://jjt-snippets-dev.duckdns.org')
        with patch('scoped_deploy.render_release', return_value=after), \
                patch('scoped_deploy.validate_rendered', side_effect=json.dumps):
            document = json.loads(scoped_document(self.candidate, {'snippets-service', 'ui'}))
        self.assertEqual(set(document['services']), {'snippets-service', 'ui'})
        self.assertFalse(document['services']['snippets-service'].get('ports'))

    def test_plan_uses_public_metadata_without_touching_source_or_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'release.json'
            path.write_text(json.dumps(self.previous))
            original = path.read_bytes()
            result = subprocess.check_output([sys.executable, '-B', str(ROOT / 'scripts/bootstrap_swarm.py'),
                                              'plan', str(path), '--auth0-dev'], text=True)
            planned = json.loads(result)
            selected = select_release(planned, self.previous, change_infrastructure=True)
            require_auth_only(self.previous, selected)
            self.assertEqual(selected['images'], self.previous['images'])
            self.assertEqual(selected['apm'], self.previous['apm'])
            self.assertEqual(path.read_bytes(), original)


class AuthSwarm(InfrastructureSwarm):
    scope = 'auth'
    rule = staticmethod(require_auth_only)

    def __init__(self, previous):
        super().__init__(previous)
        self.auth = copy.deepcopy(previous.get('auth', {}))
        self.confirmed = copy.deepcopy(previous)

    def apply_infrastructure(self, manifest):
        require_auth_only(self.confirmed, manifest)
        self.auth = copy.deepcopy(manifest.get('auth', {}))
        super().apply_infrastructure(manifest)

    def verify(self, manifest, application=None):
        super().verify(manifest, application)
        if self.auth != manifest.get('auth', {}):
            raise ValueError('API identity differs')


class RecoveryTests(unittest.TestCase):
    def test_recovery_after_interruption_keeps_the_auth_scope_and_restores_mixed_state(self):
        previous = previous_release()
        previous['apm'] = {'enabled': True}
        candidate = authenticated(previous)
        swarm = AuthSwarm(previous)
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            write_record(state / 'release.json', previous)
            swarm.interruption = True
            with patch('bootstrap_swarm.preflight'), self.assertRaises(KeyboardInterrupt):
                deploy_infrastructure(state, candidate, swarm, lambda _: None)
            identity = json.loads((state / 'pending.json').read_text())['operation']
            operation = json.loads((state / 'operations' / (identity + '.json')).read_text())
            self.assertEqual(operation['scope'], 'auth')
            swarm.ui = copy.deepcopy(previous.get('ui', {}))
            with patch('scoped_deploy.ScopedSwarm', return_value=swarm):
                receipt = reconcile(state, InfrastructureSwarm(previous))
            self.assertEqual(receipt['outcome'], 'recovered')
            confirmed = json.loads((state / 'release.json').read_text())
            self.assertEqual(confirmed['images'], previous['images'])
            self.assertEqual(confirmed['apm'], previous['apm'])
            self.assertNotIn('auth', confirmed)
            self.assertFalse((state / 'pending.json').exists())
            self.assertEqual(swarm.auth, {})

    def test_failure_outside_auth_is_rejected_before_preflight_or_mutation(self):
        previous = previous_release()
        candidate = authenticated(previous)
        candidate['apm'] = {'enabled': True}
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            write_record(state / 'release.json', previous)
            swarm = AuthSwarm(previous)
            with patch('bootstrap_swarm.preflight') as preflight, self.assertRaises(ValueError):
                deploy_infrastructure(state, candidate, swarm, lambda _: None)
            preflight.assert_not_called()
            self.assertEqual(swarm.applications, [])
            self.assertFalse((state / 'pending.json').exists())


class PublicContractTests(unittest.TestCase):
    def test_spring_empty_401_is_valid_but_html_and_missing_bearer_challenge_are_not(self):
        check_bearer_required((401, [('WWW-Authenticate', 'Bearer')], b''))
        for response in [(200, [], b''), (401, [], b''),
                         (401, [('WWW-Authenticate', 'Bearer'), ('Content-Type', 'text/html')], b'<html>')]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                check_bearer_required(response)

    def test_recovery_refuses_api_identity_changed_by_another_operator(self):
        previous = previous_release()
        candidate = authenticated(previous)
        swarm = ScopedSwarm('dev', previous, 'auth')
        values = {'AUTH_MODE': 'auth0', 'AUTH_ISSUER': 'https://other.auth0.com/',
                  'AUTH_AUDIENCE': PUBLIC['audience']}
        spec = [{'Spec': {'TaskTemplate': {'ContainerSpec': {
            'Env': [key + '=' + value for key, value in values.items()]}}}}]
        with patch('deploy_service.Swarm.require_recoverable_infrastructure'), \
                patch('deploy_service.docker_json', return_value=spec), self.assertRaisesRegex(ValueError, 'terceros'):
            swarm.require_recoverable_infrastructure(previous, candidate)

    def test_recovery_refuses_to_overwrite_an_apm_change(self):
        previous = previous_release()
        previous['apm'] = {'enabled': True}
        swarm = ScopedSwarm('dev', previous, 'auth')
        spec = [{'Spec': {'TaskTemplate': {'ContainerSpec': {'Env': ['NEW_RELIC_ENABLED=false']}}}}]
        with patch('deploy_service.Swarm.require_recoverable_infrastructure'), \
                patch('deploy_service.docker_json', return_value=spec), self.assertRaisesRegex(ValueError, 'APM'):
            swarm.require_recoverable_infrastructure(previous, authenticated(previous))


if __name__ == '__main__':
    unittest.main()
