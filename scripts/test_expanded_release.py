"""SNI-43 behavior: v1 compatibility, component isolation, journals and cutover fencing."""
import base64
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bootstrap_swarm import deploy_infrastructure, plan_release
from deploy_service import deploy_locked, reconcile
from github_cd import checks_for, validate_repository, validate_request
from rollout_checks import require_updated_callers
from stack_release import (database_image, expected_images, nginx_files, permanent_services, select_release,
                           ui_configuration, update_service, upgrade_release, validate_manifest, write_record)
from stack_runtime import ROOT, apply_release, render_release, stack_document, require_configs
from test_deploy_service import CHECKS, FakeSwarm, release, request


def expanded(environment='dev', assets=True, ui=False):
    result = upgrade_release(release(environment))
    from validate_nginx_config import NGINX_IMAGE
    result['infrastructure']['nginx'] = {'image': NGINX_IMAGE, 'hostname': f'snippet-{environment}.test', 'tls': False,
        'configs': {key: {'name': f'snippet-searcher-{environment}_{key}_v1',
                         'sha256': hashlib.sha256((ROOT / file).read_bytes()).hexdigest()}
                    for key, file in nginx_files(False).items()}}
    if assets:
        result['infrastructure'].update({
            'asset-service': {'image': 'ghcr.io/austral-ingsis/snippet-asset-service@sha256:' + 'a' * 64},
            'azurite': {'image': 'mcr.microsoft.com/azure-storage/azurite:3.35.0@sha256:' + 'b' * 64}})
    if ui:
        result['images']['ui'] = 'ghcr.io/jjt-ingsis/snippet-searcher-ui@sha256:' + 'c' * 64
    return result


class InfrastructureSwarm(FakeSwarm):
    def __init__(self, previous):
        super().__init__(previous)
        self.config = copy.deepcopy(previous.get('infrastructure', {}))
        self.ui = copy.deepcopy(previous.get('ui', {}))
        self.applications = []
        self.removed = []
        self.failure = False

    def apply_infrastructure(self, manifest):
        self.applications.append(copy.deepcopy(manifest))
        self.current.update(expected_images(manifest))
        self.config = copy.deepcopy(manifest.get('infrastructure', {}))
        self.ui = copy.deepcopy(manifest.get('ui', {}))
        if self.interruption:
            self.interruption = None
            raise KeyboardInterrupt()

    def require_recoverable_infrastructure(self, previous, candidate):
        if self.config not in (previous.get('infrastructure', {}), candidate.get('infrastructure', {})):
            raise ValueError('Configuración de un tercero')

    def remove_components(self, names):
        self.removed.extend(names)
        for name in names:
            del self.current[name]

    def verify(self, manifest, application=None):
        super().verify(manifest, application)
        if application is None and self.config != manifest.get('infrastructure', {}):
            raise ValueError('Config efectiva diferente')
        if application in (None, 'ui') and self.ui != manifest.get('ui', {}):
            raise ValueError('Config UI efectiva diferente')
        if self.failure and manifest.get('infrastructure'):
            raise RuntimeError('Proxy no enruta')


class ExpandedReleaseTests(unittest.TestCase):
    def test_ui_runtime_config_is_explicit_preserved_and_forbidden_in_prod(self):
        value = expanded(ui=True)
        value['ui'] = {'dev_actor': 'dev-juanfran'}
        validate_manifest(value)
        self.assertEqual(ui_configuration(value)['identity'], {'mode': 'dev', 'actorId': 'dev-juanfran'})
        self.assertEqual(select_release(release(), value)['ui'], value['ui'])
        self.assertEqual(update_service(value, 'ui', value['images']['ui'])['ui'], value['ui'])
        for actor in ('bad"actor', 'bad\nactor', ' x', 'x' * 129):
            value['ui']['dev_actor'] = actor
            with self.assertRaises(ValueError): validate_manifest(value)
        prod = expanded('prod', ui=True)
        self.assertEqual(ui_configuration(prod)['identity'], {'mode': 'disabled'})
        prod['ui'] = {'dev_actor': 'dev-juanfran'}
        with self.assertRaises(ValueError): validate_manifest(prod)

    def test_initial_ui_plan_keeps_other_digests_and_refuses_manual_app_upgrade(self):
        old = expanded()
        image = expanded(ui=True)['images']['ui']
        candidate = plan_release(old, ui_image=image, ui_actor='dev-juanfran')
        self.assertEqual(candidate['images'], {**old['images'], 'ui': image})
        self.assertEqual(candidate['storage_provider'], 'local')
        with self.assertRaises(ValueError): plan_release(candidate, ui_image=image.replace('c' * 64, 'd' * 64))

    def test_upgrade_preserves_references_receipts_and_unknown_metadata_without_mutation(self):
        old = {**release(), 'deployments': {'snippets-service': {'run-id': 10}}, 'custom': {'keep': True}}
        original = copy.deepcopy(old)
        new = upgrade_release(old)
        self.assertEqual(old, original)
        self.assertEqual(new['images'], old['images'])
        self.assertEqual(database_image(new), old['database_image'])
        self.assertEqual(new['custom'], old['custom'])
        self.assertEqual(new['deployments'], old['deployments'])
        self.assertNotIn('database_image', new)
        validate_manifest(new)

    def test_real_legacy_reader_accepts_v1_and_rejects_v2_before_old_cd_can_update(self):
        raw = (ROOT / 'tests/legacy/v0.5.1-stack_release.txt').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '5b0ba0f7f3db27d012f9aa7ca6240865d3ebccdd67d6afc9fb90bfa3b965d18d')
        source = raw.decode()
        namespace = {'__name__': 'legacy_release'}
        exec(compile(source, 'v0.5.1-stack_release', 'exec'), namespace)
        namespace['validate_manifest'](release())
        for value in (upgrade_release(release()), expanded(), expanded(ui=True)):
            with self.subTest(value=value['infrastructure']), self.assertRaises(ValueError):
                namespace['validate_manifest'](value)

    def test_unknown_schema_component_service_package_or_mutable_ref_is_rejected(self):
        values = []
        value = expanded(); value['schema_version'] = 3; values.append(value)
        value = expanded(); value['infrastructure']['redis'] = {'image': 'redis:latest'}; values.append(value)
        value = expanded(); value['images']['arbitrary'] = value['images']['snippets-service']; values.append(value)
        value = expanded(); value['infrastructure']['nginx']['image'] = 'nginx:latest'; values.append(value)
        value = expanded(); value['database_image'] = database_image(value); values.append(value)
        value = expanded(); value['infrastructure']['nginx']['configs']['nginx_main']['name'] = '../escape'; values.append(value)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_manifest(value)

    def test_reapply_keeps_live_digests_infrastructure_provider_and_receipts(self):
        current = expanded(ui=True)
        current['images']['snippets-service'] = request()['image-ref']
        current['deployments'] = {'snippets-service': {'run-id': 11}}
        before = copy.deepcopy(current)
        self.assertEqual(select_release(release(), current), before)
        candidate = expanded(ui=True)
        candidate['infrastructure']['nginx']['configs']['nginx_redirect']['name'] = 'snippet-searcher-dev_nginx_redirect_v2'
        selected = select_release(candidate, current, change_infrastructure=True)
        self.assertEqual(selected['images'], current['images'])
        self.assertEqual(selected['deployments'], current['deployments'])
        self.assertEqual(current, before)

    def test_installed_asset_does_not_activate_provider_and_transition_is_rejected(self):
        old = release()
        installed = select_release(expanded(), old, change_infrastructure=True)
        self.assertEqual(installed['storage_provider'], 'local')
        candidate = copy.deepcopy(installed); candidate['storage_provider'] = 'asset'
        validate_manifest(candidate)
        with self.assertRaisesRegex(ValueError, 'transición'):
            select_release(candidate, installed, change_infrastructure=True)

    def test_app_update_preserves_infrastructure_and_uses_a_closed_ui_mapping(self):
        previous = expanded(ui=True)
        changed = update_service(previous, 'ui', 'ghcr.io/jjt-ingsis/snippet-searcher-ui@sha256:' + 'd' * 64)
        self.assertEqual(previous['infrastructure'], changed['infrastructure'])
        self.assertEqual(changed['images']['snippets-service'], previous['images']['snippets-service'])
        self.assertEqual(validate_repository('JJT-INGSIS/snippet-searcher-ui'), 'ui')
        value = {**request(), 'repository': 'JJT-INGSIS/snippet-searcher-ui', 'service': 'ui',
                 'image-ref': changed['images']['ui']}
        validate_request(value)
        value['image-ref'] = request()['image-ref']
        with self.assertRaises(ValueError): validate_request(value)
        self.assertNotEqual(checks_for('ui'), CHECKS)

    def test_verification_scope_does_not_roll_back_backend_for_unrelated_proxy_ui_or_dns(self):
        value = expanded(ui=True)
        self.assertEqual(set(permanent_services(value, 'ui')), {'ui'})
        self.assertNotIn('nginx', permanent_services(value, 'snippets-service'))
        self.assertNotIn('asset-service', permanent_services(value, 'snippets-service'))
        value['storage_provider'] = 'asset'
        self.assertIn('asset-service', permanent_services(value, 'snippets-service'))
        self.assertNotIn('certbot', permanent_services(value))


class InfrastructureRecoveryTests(unittest.TestCase):
    def test_initial_prod_ui_requires_approved_main_tree_and_dev_evidence(self):
        from test_github_cd import FakeGitHub
        candidate = expanded('prod', ui=True)
        self.previous = release('prod')
        self.swarm = InfrastructureSwarm(self.previous)
        write_record(self.state / 'release.json', self.previous)
        before = (self.state / 'release.json').read_bytes()
        proof = {**request(), 'service': 'ui', 'repository': 'JJT-INGSIS/snippet-searcher-ui',
                 'image-ref': candidate['images']['ui']}
        for condition in ('tree', 'unprotected', 'direct_push'):
            api = FakeGitHub(proof['repository'])
            if condition == 'tree': api.tree = 'd' * 40
            if condition == 'unprotected': api.protected = False
            if condition == 'direct_push': api.merged_pr = False
            with patch('github_cd.GitHub', return_value=api), \
                    patch('github_cd.select_evidence', return_value=proof), \
                    patch('bootstrap_swarm.docker_json', return_value=[{'Config': {'Labels': {'io.jjt.source-tree': 'c' * 40}}}]), \
                    self.assertRaises(ValueError):
                self.deploy(candidate)
            self.assertEqual(self.swarm.applications, [])
            self.assertEqual((self.state / 'release.json').read_bytes(), before)
        with patch('github_cd.GitHub', return_value=FakeGitHub(proof['repository'])), \
                patch('github_cd.select_evidence', return_value=proof), \
                patch('bootstrap_swarm.docker_json', return_value=[{'Config': {'Labels': {'io.jjt.source-tree': 'c' * 40}}}]):
            self.assertEqual(self.deploy(candidate)['outcome'], 'verified')
        self.assertEqual(json.loads((self.state / 'release.json').read_text())['images'], candidate['images'])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.previous = release()
        write_record(self.state / 'release.json', self.previous)
        self.swarm = InfrastructureSwarm(self.previous)
        self.gates = []

    def deploy(self, candidate=None):
        with patch('bootstrap_swarm.preflight'):
            return deploy_infrastructure(self.state, candidate or expanded(), self.swarm, self.gates.append)

    def test_addition_verifies_and_fences_legacy_preserving_app_and_database_images(self):
        receipt = self.deploy()
        current = json.loads((self.state / 'release.json').read_text())
        self.assertEqual(receipt['outcome'], 'verified')
        self.assertEqual(current['images'], self.previous['images'])
        self.assertEqual(database_image(current), database_image(self.previous))
        self.assertEqual(current['storage_provider'], 'local')
        self.assertEqual(self.gates, ['dev'])
        self.assertFalse((self.state / 'pending.json').exists())
        self.assertEqual(self.swarm.updates, [])

    def test_gate_fails_before_fence_or_mutation(self):
        before = (self.state / 'release.json').read_bytes()
        def reject(environment): raise ValueError('Old caller')
        with patch('bootstrap_swarm.preflight'), self.assertRaises(ValueError):
            deploy_infrastructure(self.state, expanded(), self.swarm, reject)
        self.assertEqual((self.state / 'release.json').read_bytes(), before)
        self.assertFalse((self.state / 'pending.json').exists())
        self.assertEqual(self.swarm.applications, [])

    def test_bad_proxy_recovers_only_infrastructure_and_keeps_v2_fence(self):
        self.swarm.failure = True
        with self.assertRaisesRegex(RuntimeError, 'recuperado'):
            self.deploy()
        current = json.loads((self.state / 'release.json').read_text())
        self.assertEqual(self.swarm.current, expected_images(self.previous))
        self.assertEqual(current['schema_version'], 2)
        self.assertEqual(current['images'], self.previous['images'])
        self.assertEqual(set(self.swarm.removed), {'nginx', 'asset-service', 'azurite'})
        self.assertEqual(self.swarm.updates, [])

    def test_same_image_new_config_can_fail_and_restore_previous_config(self):
        old = expanded()
        self.previous = old
        self.swarm = InfrastructureSwarm(old)
        write_record(self.state / 'release.json', old)
        candidate = copy.deepcopy(old)
        candidate['infrastructure']['nginx']['configs']['nginx_redirect']['name'] = 'snippet-searcher-dev_nginx_redirect_v2'
        verify = self.swarm.verify
        def only_old(manifest, application=None):
            verify(manifest, application)
            if manifest['infrastructure'] != old['infrastructure']: raise RuntimeError('Bad routes')
        self.swarm.verify = only_old
        with self.assertRaises(RuntimeError): self.deploy(candidate)
        self.assertEqual(self.swarm.config, old['infrastructure'])
        self.assertEqual(self.swarm.removed, [])

    def test_interruption_after_apply_reconciles_actual_config_without_second_apply(self):
        self.swarm.interruption = 'after'
        with self.assertRaises(KeyboardInterrupt): self.deploy()
        self.assertTrue((self.state / 'pending.json').exists())
        self.assertEqual(json.loads((self.state / 'release.json').read_text())['schema_version'], 2)
        result = reconcile(self.state, self.swarm)
        self.assertEqual(result['outcome'], 'verified')
        self.assertEqual(len(self.swarm.applications), 1)

    def test_completed_journal_after_interrupted_release_write_is_reverified(self):
        from bootstrap_swarm import write_record as original
        def fail(path, record):
            if path.name == 'release.json' and record.get('infrastructure'): raise KeyboardInterrupt()
            original(path, record)
        with patch('bootstrap_swarm.write_record', side_effect=fail), self.assertRaises(KeyboardInterrupt): self.deploy()
        self.assertEqual(reconcile(self.state, self.swarm)['outcome'], 'verified')
        self.assertEqual(len(self.swarm.applications), 1)

    def test_retry_of_interrupted_infrastructure_confirms_without_resubmitting(self):
        self.swarm.interruption = 'after'
        with self.assertRaises(KeyboardInterrupt): self.deploy()
        self.assertEqual(self.deploy()['outcome'], 'verified')
        self.assertEqual(len(self.swarm.applications), 1)
        self.assertEqual(self.gates, ['dev'])

    def test_retry_after_failed_interrupted_change_recovers_and_stays_red(self):
        self.swarm.interruption = 'after'
        with self.assertRaises(KeyboardInterrupt): self.deploy()
        self.swarm.failure = True
        with self.assertRaisesRegex(RuntimeError, 'interrumpida fue recuperada'): self.deploy()
        self.assertEqual(len(self.swarm.applications), 2)  # Candidate, then restore; no new candidate.
        self.assertEqual(self.swarm.current, expected_images(self.previous))
        self.assertFalse((self.state / 'pending.json').exists())

    def test_failed_recovery_preserves_journal_and_does_not_claim_health(self):
        self.swarm.failure = True
        original = self.swarm.apply_infrastructure
        def fail_old(value):
            if not value.get('infrastructure'): raise RuntimeError('Cannot restore')
            original(value)
        self.swarm.apply_infrastructure = fail_old
        with self.assertRaises(RuntimeError): self.deploy()
        self.assertTrue((self.state / 'pending.json').exists())
        self.assertEqual(json.loads((self.state / 'release.json').read_text())['checks'], {'recovery': 'failed'})
        self.swarm.failure = False
        self.swarm.apply_infrastructure = original
        self.assertEqual(reconcile(self.state, self.swarm)['outcome'], 'verified')

    def test_external_app_drift_is_never_overwritten_during_recovery(self):
        self.swarm.interruption = 'after'
        with self.assertRaises(KeyboardInterrupt): self.deploy()
        self.swarm.current['permissions-service'] = 'external'
        with self.assertRaises(ValueError): reconcile(self.state, self.swarm)
        self.assertEqual(len(self.swarm.applications), 1)

    def test_application_cd_preserves_extended_record_components_and_recovers_independently(self):
        previous = expanded(ui=True)
        write_record(self.state / 'release.json', previous)
        self.swarm = InfrastructureSwarm(previous)
        self.swarm.bad.add(request()['image-ref'])
        result = deploy_locked(self.state, request(), self.swarm, lambda _: None, lambda _: None)
        self.assertEqual(result['outcome'], 'recovered')
        current = json.loads((self.state / 'release.json').read_text())
        self.assertEqual(current['infrastructure'], previous['infrastructure'])
        self.assertEqual(self.swarm.applications, [])

    def test_ui_cd_updates_only_ui_and_records_ui_checks_not_fictitious_sql(self):
        previous = expanded(ui=True)
        write_record(self.state / 'release.json', previous)
        self.swarm = InfrastructureSwarm(previous)
        value = {**request(), 'service': 'ui', 'repository': 'JJT-INGSIS/snippet-searcher-ui',
                 'image-ref': 'ghcr.io/jjt-ingsis/snippet-searcher-ui@sha256:' + 'd' * 64}
        receipt = deploy_locked(self.state, value, self.swarm, lambda _: None, lambda _: None)
        self.assertEqual(receipt['checks'], checks_for('ui'))
        self.assertEqual(self.swarm.updates, [('ui', value['image-ref'])])
        self.assertEqual(self.swarm.current['snippets-service'], previous['images']['snippets-service'])
        self.assertEqual(self.swarm.config, previous['infrastructure'])


class RuntimeBoundaryTests(unittest.TestCase):
    def test_unknown_ui_configuration_is_not_overwritten_during_infra_recovery(self):
        from deploy_service import Swarm
        value = expanded(ui=True)
        actual = {'Spec': {'TaskTemplate': {'ContainerSpec': {'Env': ['APP_ENV=dev', 'UI_DEV_ACTOR=someone-else']}}}}
        with patch.object(Swarm, 'images', return_value=expected_images(value)), \
                patch('deploy_service.docker_json', return_value=[actual]), self.assertRaisesRegex(ValueError, 'UI ajena'):
            Swarm('dev').require_recoverable_infrastructure(value, value)

    def test_deployment_submits_exactly_the_validated_document_without_temporary_files(self):
        data = {'services': {'database': {'healthcheck': {'test': ['CMD-SHELL', 'echo "$POSTGRES_USER"']}}}}
        with patch('stack_runtime.render_release', return_value=data), \
                patch('stack_runtime.require_configs'), patch('stack_runtime.subprocess.run') as docker:
            apply_release(expanded(), lambda *args: None)
        validation, deployment = docker.call_args_list
        self.assertEqual(validation.args[0], ['docker', 'stack', 'config', '-c', '-'])
        self.assertEqual(deployment.args[0][-3:], ['-c', '-', 'snippet-searcher-dev'])
        self.assertEqual(validation.kwargs['input'], deployment.kwargs['input'])
        self.assertIn('$$POSTGRES_USER', deployment.kwargs['input'])

    def test_invalid_manifest_cannot_create_configs_or_submit_deployment(self):
        with patch('stack_runtime.render_release', return_value={}), \
                patch('stack_runtime.require_configs') as configs, \
                patch('stack_runtime.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'docker')) as docker, \
                self.assertRaises(subprocess.CalledProcessError):
            apply_release(expanded(), lambda *args: None)
        configs.assert_not_called()
        self.assertEqual(docker.call_count, 1)

    def test_render_keeps_current_refs_removes_public_ports_and_uses_external_config_snapshots(self):
        value = expanded(ui=True)
        services = {name: {'image': image, 'command': None, 'entrypoint': None,
                    'networks': {'default': None}} for name, image in expected_images(value).items()}
        services['snippets-service']['ports'] = [{'published': '8080', 'target': 8080}]
        services['nginx']['ports'] = [{'published': '80', 'target': 8080}]
        composed = {'name': 'sni33-validation', 'services': services,
                    'networks': {'default': {'name': 'sni33-validation_default'}},
                    'volumes': {'snippets_data': {'name': 'sni33-validation_snippets_data'}}}
        with patch('validate_asset_config.render', return_value=composed):
            data = render_release(value)
        self.assertNotIn('ports', data['services']['snippets-service'])
        self.assertEqual(data['services']['nginx']['ports'][0]['published'], 80)
        self.assertEqual(data['volumes']['snippets_data'], {})
        self.assertTrue(all(spec['external'] for spec in data['configs'].values()))
        self.assertNotIn('command', data['services']['snippets-db'])

    def test_render_protects_shell_variables_from_a_second_interpolation(self):
        original = {'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U "$POSTGRES_USER"']}}
        document = json.loads(stack_document(original))
        self.assertEqual(document['healthcheck']['test'][1], 'pg_isready -U "$$POSTGRES_USER"')
        self.assertIn('$POSTGRES_USER', original['healthcheck']['test'][1])

    def test_config_hash_mismatch_is_rejected_without_overwriting_immutable_resource(self):
        value = expanded(assets=False)
        names = '\n'.join(spec['name'] for spec in value['infrastructure']['nginx']['configs'].values())
        with patch('stack_runtime.subprocess.check_output', return_value=names), \
                patch('stack_runtime.subprocess.run') as mutation, self.assertRaisesRegex(ValueError, 'otro contenido'):
            require_configs(value, lambda *args: [{'Spec': {'Data': base64.b64encode(b'wrong config').decode()}}], create=True)
        mutation.assert_not_called()

    def test_finished_certbot_is_not_inspected_as_a_permanent_application(self):
        from deploy_service import Swarm
        name = 'snippet-searcher-dev_snippets-service'
        with patch('deploy_service.subprocess.check_output', return_value=name + '\nsnippet-searcher-dev_certbot\n'), \
                patch('deploy_service.docker_json', return_value=[{'Spec': {'TaskTemplate': {'ContainerSpec': {'Image': 'image'}}}}]) as inspect:
            self.assertEqual(Swarm('dev').images(), {'snippets-service': 'image'})
        inspect.assert_called_once_with('service', 'inspect', name)

    def test_prod_asset_missing_read_probe_is_failure_without_writing(self):
        import asset_probe
        from internal_http import verify_asset
        with patch.object(asset_probe, 'wait_ready'), patch.object(asset_probe, 'prepare') as write, \
                self.assertRaisesRegex(ValueError, 'previamente preparado'):
            verify_asset(expanded('prod'), 'snippet-searcher-prod')
        write.assert_not_called()


class UIEvidenceTests(unittest.TestCase):
    def test_ui_requires_exact_tree_digest_run_and_trusted_cd_reference(self):
        from github_cd import valid_evidence
        from test_github_cd import deployment
        value = deployment()
        payload = value['payload']
        payload.update(service='ui', repository='JJT-INGSIS/snippet-searcher-ui', checks=checks_for('ui'))
        payload['image-ref'] = payload['actual-image'] = 'ghcr.io/jjt-ingsis/snippet-searcher-ui@sha256:' + 'c' * 64
        class API:
            trusted = True
            ci = 'success'
            mixed_revision = False
            def pages(self, path, key=None):
                return iter([{'name': 'verify / Frontend CI', 'status': 'completed', 'conclusion': self.ci}])
            def request(self, path):
                if path.startswith('/git/commits/'):
                    return {'tree': {'sha': 'c' * 40}}
                return {'conclusion': 'success', 'status': 'completed', 'event': 'push', 'head_branch': 'dev',
                    'head_sha': 'b' * 40, 'path': '.github/workflows/pipeline.yml',
                    'repository': {'full_name': payload['repository']},
                    'referenced_workflows': [{'path': f'JJT-INGSIS/github-workflows/.github/workflows/{name}@v0.6.0',
                                              'sha': ('b' if self.mixed_revision and name == 'frontend-ci.yml' else 'a') * 40}
                                             for name in ('frontend-ci.yml', 'cd.yml')] if self.trusted else []}
        api = API()
        self.assertEqual(valid_evidence(api, value, 'ui', 'c' * 40)['image-ref'], payload['image-ref'])
        self.assertIsNone(valid_evidence(api, value, 'ui', 'd' * 40))
        for conclusion in ('skipped', 'failure', 'cancelled', None):
            api.ci = conclusion
            self.assertIsNone(valid_evidence(api, value, 'ui', 'c' * 40))
        api.ci = 'success'
        api.mixed_revision = True
        self.assertIsNone(valid_evidence(api, value, 'ui', 'c' * 40))
        api.mixed_revision = False
        api.trusted = False
        self.assertIsNone(valid_evidence(api, value, 'ui', 'c' * 40))


class RolloutGateTests(unittest.TestCase):
    def api(self, reference='v0.6.1', active=False):
        class API:
            def __init__(self, repository, token): self.repository = repository
            def request(self, path):
                if '/actions/runs?' in path:
                    return {'workflow_runs': [{'status': 'queued' if active else 'completed', 'event': 'push'}]}
                if '/contents/.github/workflows?' in path:
                    return [{'name': 'pipeline.yml', 'path': '.github/workflows/pipeline.yml'}]
                return {'content': base64.b64encode(('jobs:\n  verify:\n    uses: '
                    'JJT-INGSIS/github-workflows/.github/workflows/kotlin-service-pipeline.yml@' + reference).encode()).decode()}
        return API

    def test_requires_current_version_and_no_active_push_or_manual_runs(self):
        require_updated_callers('dev', self.api())
        require_updated_callers('prod', self.api())
        with self.assertRaisesRegex(ValueError, 'antiguo'): require_updated_callers('dev', self.api('v0.5.1'))
        with self.assertRaisesRegex(ValueError, 'antiguo'): require_updated_callers('dev', self.api('v0.6.0'))
        with self.assertRaisesRegex(ValueError, 'activas'): require_updated_callers('prod', self.api(active=True))


class LocalDesktopGuardTests(unittest.TestCase):
    def test_only_the_local_desktop_linux_pipe_is_accepted_on_windows(self):
        from verify_asset_persistence import local_engine
        with patch.dict('os.environ', {'DOCKER_CONTEXT': '', 'DOCKER_HOST': 'npipe:////./pipe/dockerDesktopLinuxEngine'}), \
                patch('os.name', 'nt'), patch('subprocess.check_output', return_value='linux\n'):
            local_engine()
        for endpoint, engine in (('npipe:////remote/pipe/dockerDesktopLinuxEngine', 'linux'),
                                 ('npipe:////./pipe/dockerDesktopLinuxEngine', 'windows')):
            with patch.dict('os.environ', {'DOCKER_CONTEXT': '', 'DOCKER_HOST': endpoint}), \
                    patch('os.name', 'nt'), patch('subprocess.check_output', return_value=engine), self.assertRaises(RuntimeError):
                local_engine()


if __name__ == '__main__':
    unittest.main()
