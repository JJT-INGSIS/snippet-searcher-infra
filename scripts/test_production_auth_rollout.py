import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auth_rollout import plan_identity
from bootstrap_swarm import plan_release
from scoped_deploy import require_auth_only, scoped_document
from stack_release import ui_configuration
from stack_runtime import render_release
from test_expanded_release import expanded

ROOT = Path(__file__).resolve().parent.parent


class ProductionAuthTests(unittest.TestCase):
    def setUp(self):
        self.previous = plan_release(expanded('prod', ui=True, assets=False),
                                     'jjt-snippets-prod.duckdns.org', tls=True)
        self.candidate = plan_identity(self.previous, 'prod')

    def test_uses_admin_confirmed_public_client_and_prod_audience(self):
        identity = ui_configuration(self.candidate)['identity']
        self.assertEqual(identity['clientId'], '3WzM34S00lsCGU0p4hYImgs2xCuPgejW')
        self.assertEqual(identity['audience'], 'https://jjt-snippets-prod.duckdns.org/api')
        require_auth_only(self.previous, self.candidate)
        require_auth_only(self.candidate, self.previous)
        self.assertNotIn('auth', self.previous)

    def test_only_two_services_change_and_apm_is_preserved(self):
        self.previous['apm'] = {'enabled': True}
        candidate = plan_identity(self.previous, 'prod')
        before, after = render_release(self.previous), render_release(candidate)
        for service in before['services']:
            if service not in ('ui', 'snippets-service'):
                self.assertEqual(before['services'][service], after['services'][service])
        key = 'auth0_directory_prod'
        before_snippets = before['services']['snippets-service']
        after_snippets = after['services']['snippets-service']
        self.assertEqual(after_snippets['secrets'], before_snippets['secrets'] + [
            {'source': key, 'target': 'snippets.directory.auth0.client-secret'},
        ])
        self.assertNotIn('AUTH0_DIRECTORY_CLIENT_ID', before_snippets['environment'])
        self.assertEqual(after_snippets['environment']['AUTH0_DIRECTORY_CLIENT_ID'],
                         'wa4O5PHWRFY7ekVtsoF3lzHlegDAZ3Tb')
        self.assertEqual(after['secrets'][key],
                         {'external': True, 'name': 'snippet-searcher-prod-auth0-directory-v1'})
        with patch('scoped_deploy.validate_rendered', side_effect=json.dumps):
            scoped = json.loads(scoped_document(candidate, {'ui', 'snippets-service'}))
        self.assertEqual(set(scoped['services']), {'ui', 'snippets-service'})

    def test_rejects_dev_parameters_and_changes_outside_identity(self):
        changes = [lambda c: c['ui']['auth'].update(client_id='BDuvRyQ6ryyye08Bs9ZEfRzw7AsskFs6'),
                   lambda c: c['auth'].update(audience='https://jjt-snippets-dev.duckdns.org/api'),
                   lambda c: c['ui'].update(dev_actor='owner'),
                   lambda c: c.update(apm={'enabled': True}),
                   lambda c: c['images'].update(ui=c['images']['ui'].replace('c' * 64, 'e' * 64))]
        for change in changes:
            candidate = copy.deepcopy(self.candidate)
            change(candidate)
            with self.subTest(change=change), self.assertRaises(ValueError):
                require_auth_only(self.previous, candidate)

    def test_rejects_wrong_environment_hostname_and_plaintext(self):
        for change in [lambda c: c.update(environment='dev'),
                       lambda c: c['infrastructure']['nginx'].update(hostname='jjt-snippets-dev.duckdns.org'),
                       lambda c: c['infrastructure']['nginx'].update(tls=False)]:
            value = copy.deepcopy(self.previous)
            change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan_identity(value, 'prod')

    def test_cli_plans_from_confirmed_record_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'release.json'
            source.write_text(json.dumps(self.previous))
            original = source.read_bytes()
            result = subprocess.check_output([sys.executable, str(ROOT / 'scripts/bootstrap_swarm.py'),
                                              'plan', str(source), '--auth0-prod'], text=True)
            require_auth_only(self.previous, json.loads(result))
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
