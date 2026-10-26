import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bootstrap_swarm import plan_release, require_certificate
from stack_release import TLS_CONFIGS, validate_manifest
from stack_runtime import verify_service_configuration
from test_expanded_release import expanded


def secured(environment='dev'):
    return plan_release(expanded(environment, assets=False), f'snippet-{environment}.test', tls=True)


def proxy_service(release, ports):
    proxy = release['infrastructure']['nginx']
    return {'Spec': {'TaskTemplate': {'ContainerSpec': {
        'Configs': [{'ConfigName': spec['name']} for spec in proxy['configs'].values()],
        'Env': [f'PROXY_HOSTNAME={proxy["hostname"]}', 'PROXY_PUBLIC_PORT=443']}},
        'EndpointSpec': {'Ports': [{'TargetPort': target, 'PublishedPort': published} for target, published in ports]}}}


class TlsReleaseTests(unittest.TestCase):
    def test_tls_state_is_explicit_and_owns_exactly_its_configs(self):
        validate_manifest(secured())
        missing = secured()
        del missing['infrastructure']['nginx']['configs']['nginx_tls']
        legacy = expanded(assets=False)
        legacy['infrastructure']['nginx']['port'] = 80
        implicit = expanded(assets=False)
        implicit['infrastructure']['nginx']['tls'] = 'yes'
        plain_with_tls = expanded(assets=False)
        plain_with_tls['infrastructure']['nginx']['configs'].update(
            {key: copy.deepcopy(spec) for key, spec in secured()['infrastructure']['nginx']['configs'].items()
             if key in TLS_CONFIGS})
        for value in (missing, legacy, implicit, plain_with_tls):
            with self.subTest(value=value['infrastructure']['nginx']), self.assertRaises(ValueError):
                validate_manifest(value)

    def test_http_to_https_plan_keeps_unchanged_configs_and_adds_only_tls_ones(self):
        plain = expanded(assets=False)
        plain['infrastructure']['nginx']['configs']['nginx_redirect']['name'] = 'snippet-searcher-dev_nginx_redirect_v3'
        planned = plan_release(plain, 'snippet-dev.test', tls=True)
        configs = planned['infrastructure']['nginx']['configs']
        self.assertTrue(planned['infrastructure']['nginx']['tls'])
        self.assertEqual(configs['nginx_redirect'], plain['infrastructure']['nginx']['configs']['nginx_redirect'])
        self.assertEqual({configs[key]['name'] for key in TLS_CONFIGS},
                         {'snippet-searcher-dev_nginx_tls_v1', 'snippet-searcher-dev_nginx_routes_v1'})
        self.assertEqual(planned['images'], plain['images'])

    def test_tls_plan_requires_an_explicit_hostname(self):
        with self.assertRaisesRegex(ValueError, 'nginx-host'):
            plan_release(expanded(assets=False), tls=True)

    def test_tls_is_refused_until_the_certificate_files_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '{environment}'
            with patch('bootstrap_swarm.CERTIFICATES', str(root)):
                require_certificate(expanded(assets=False))
                with self.assertRaisesRegex(ValueError, 'certificado'):
                    require_certificate(secured())
                live = Path(directory) / 'dev' / 'live' / 'snippet-dev.test'
                live.mkdir(parents=True)
                (live / 'fullchain.pem').write_text('chain')
                with self.assertRaisesRegex(ValueError, 'certificado'):
                    require_certificate(secured())
                (live / 'privkey.pem').write_text('key')
                require_certificate(secured())

    def test_proxy_must_publish_the_ports_of_its_tls_state(self):
        for release, ports, valid in ((secured(), ((8080, 80), (8443, 443)), True),
                                      (secured(), ((8080, 80),), False),
                                      (expanded(assets=False), ((8080, 80), (8443, 443)), False),
                                      (expanded(assets=False), ((8080, 80),), True)):
            service = proxy_service(release, ports)
            with self.subTest(tls=release['infrastructure']['nginx']['tls'], ports=ports), \
                    patch('stack_runtime.require_configs'):
                inspect = lambda *args: [service] if args[-1].endswith('_nginx') else [{'Spec': {
                    'TaskTemplate': {'ContainerSpec': {'Env': []}}}}]
                if valid:
                    verify_service_configuration(release, inspect)
                else:
                    with self.assertRaisesRegex(ValueError, 'puertos'):
                        verify_service_configuration(release, inspect)


if __name__ == '__main__':
    unittest.main()
