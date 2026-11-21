"""SNI-72: public API configuration is explicit and survives independent CD."""
import copy
import unittest
from unittest.mock import patch

from stack_release import auth_environment, select_release, update_service, validate_manifest
from stack_runtime import render_release, verify_service_configuration
from test_expanded_release import expanded

AUTH = {'mode': 'auth0', 'issuer': 'https://jjt-snippet-searcher.us.auth0.com/',
        'audience': 'https://jjt-snippets-dev.duckdns.org/api'}


class AuthConfigurationTests(unittest.TestCase):
    def test_legacy_defaults_preserve_dev_and_keep_prod_disabled(self):
        self.assertEqual(auth_environment(expanded())['AUTH_MODE'], 'dev')
        self.assertEqual(auth_environment(expanded('prod'))['AUTH_MODE'], 'disabled')

    def test_invalid_configuration_fails_closed(self):
        for auth in (None, [], {'mode': []}, {'mode': 'typo'}, {'mode': 'auth0'},
                     {**AUTH, 'issuer': 'http://issuer/'}, {**AUTH, 'audience': ''},
                     {**AUTH, 'client_secret': 'forbidden'}, {'mode': 'disabled', 'issuer': AUTH['issuer']}):
            with self.subTest(auth=auth), self.assertRaises(ValueError):
                validate_manifest({**expanded(), 'auth': auth})
        with self.assertRaises(ValueError):
            validate_manifest({**expanded('prod'), 'auth': {'mode': 'dev'}})

    def test_independent_deploy_and_reapply_keep_auth_and_existing_images(self):
        previous = {**expanded(), 'auth': copy.deepcopy(AUTH)}
        for service in previous['images']:
            image = 'ghcr.io/jjt-ingsis/' + service + '@sha256:' + 'e' * 64
            selected = update_service(previous, service, image)
            self.assertEqual(selected['auth'], AUTH)
            for other, original in previous['images'].items():
                if other != service:
                    self.assertEqual(selected['images'][other], original)
        requested = expanded()
        self.assertEqual(select_release(requested, previous, change_infrastructure=True)['auth'], AUTH)
        selected = select_release({**requested, 'auth': AUTH}, requested, change_infrastructure=True)
        self.assertEqual(selected['auth'], AUTH)
        self.assertEqual(selected['images'], requested['images'])

    def test_render_uses_record_instead_of_runner_environment(self):
        release = {**expanded(), 'auth': AUTH}
        def render(files, settings):
            self.assertEqual(settings['AUTH_MODE'], 'auth0')
            self.assertEqual(settings['AUTH_AUDIENCE'], AUTH['audience'])
            from stack_release import expected_images
            return {'services': {name: {} for name in expected_images(release)}}
        with patch('validate_asset_config.render', side_effect=render), \
                patch.dict('os.environ', {'AUTH_MODE': 'dev', 'AUTH_AUDIENCE': 'wrong'}):
            render_release(release)

    def test_effective_auth_must_match_record_without_printing_values(self):
        release = {**expanded(assets=False), 'auth': AUTH}
        environment = {**auth_environment(release), 'STORAGE_PROVIDER': 'local'}
        def docker(*args):
            return [{'Spec': {'TaskTemplate': {'ContainerSpec': {
                'Env': [f'{key}={value}' for key, value in environment.items()]}}}}]
        verify_service_configuration(release, docker, 'snippets-service')
        environment['AUTH_MODE'] = 'dev'
        with self.assertRaisesRegex(ValueError, 'autenticación'):
            verify_service_configuration(release, docker, 'snippets-service')


if __name__ == '__main__':
    unittest.main()
