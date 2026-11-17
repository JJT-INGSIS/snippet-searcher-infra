"""Regression: independent CD accepts reviewed monitoring, never arbitrary drift."""

import base64
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import observability_deployment as monitor
from redis_runtime import verify_effective
from stack_runtime import apply_release
from test_redis_runtime import candidate


def fixture():
    release = candidate()
    configs = release['infrastructure']['redis']['configs']
    name = 'snippet-observability-dev-redis-entrypoint-' + hashlib.sha256(monitor.ENTRYPOINT.read_bytes()).hexdigest()[:12]
    services = {
        service: {'Spec': {'Mode': {'Replicated': {'Replicas': 1}},
            'UpdateConfig': {'Order': 'stop-first'}, 'RollbackConfig': {'Order': 'stop-first'},
            'TaskTemplate': {'ContainerSpec': {}, 'Networks': []}}}
        for service in ('snippets-db', 'permissions-db', 'redis', 'snippets-service', 'printscript-service')
    }
    for service in ('snippets-db', 'permissions-db', 'redis'):
        network = 'private' if service == 'redis' else 'default'
        services[service]['Spec']['TaskTemplate']['Networks'] = [{'Target': network, 'Aliases': ['dev-' + service]}]
    redis = services['redis']['Spec']['TaskTemplate']
    redis['ContainerSpec'] = {
        'Command': ['sh', '/etc/redis/entrypoint.sh'],
        'Configs': [{'ConfigName': value['name']} for key, value in configs.items() if key != 'redis_entrypoint'] +
            [{'ConfigName': name, 'File': {'Name': '/etc/redis/entrypoint.sh'}}],
        'Secrets': [{'SecretName': key, 'File': {'Name': key}} for key in ('redis_password', 'obs_redis_password')],
        'Healthcheck': {'Test': ['CMD', 'sh', '/etc/redis/healthcheck.sh']}}
    redis['Resources'] = {'Limits': {'MemoryBytes': 384 * 1024 * 1024, 'NanoCPUs': 500000000}}
    snippets = services['snippets-service']['Spec']['TaskTemplate']
    snippets['Networks'] = [{'Target': 'private'}]
    snippets['ContainerSpec'] = {
        'Env': ['SPRING_DATA_REDIS_HOST=redis', 'SPRING_DATA_REDIS_PORT=6379'],
        'Secrets': [{'SecretName': 'redis_password', 'File': {'Name': 'spring.data.redis.password'}}]}
    config = {'Spec': {'Data': base64.b64encode(monitor.ENTRYPOINT.read_bytes()).decode()}}

    def docker(*args):
        if args[0] == 'network':
            return [{'Id': 'private' if args[-1].endswith('redis_internal') or args[-1] == 'private' else 'default', 'Internal': True}]
        if args[0] == 'config':
            return [config]
        return [services[args[-1].removeprefix('snippet-searcher-dev_')]]
    return release, services, config, docker


class MonitoringDeploymentTests(unittest.TestCase):
    def test_marker_is_explicit_dev_only_and_unknown_revision_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'provisioned'
            with patch.object(monitor, 'MARKER', marker):
                self.assertFalse(monitor.installed('dev'))
                marker.write_text('sni82-runtime-v1\n')
                self.assertTrue(monitor.installed('dev'))
                self.assertFalse(monitor.installed('prod'))
                marker.write_text('unknown\n')
                with self.assertRaises(ValueError):
                    monitor.installed('dev')

    @patch.object(monitor, 'installed', return_value=True)
    def test_reviewed_runtime_passes_for_each_independent_app_without_mutating_record(self, installed):
        release, _services, _config, docker = fixture()
        before = copy.deepcopy(release)
        for app in ('ui', 'snippets-service', 'permissions-service', 'printscript-service'):
            verify_effective(release, docker, app)
        self.assertEqual(release, before)

    @patch.object(monitor, 'installed', return_value=True)
    def test_unknown_config_secret_or_lost_alias_is_rejected(self, installed):
        for change in ('config-content', 'config-name', 'config-target', 'secret', 'alias'):
            with self.subTest(change=change):
                release, services, config, docker = fixture()
                container = services['redis']['Spec']['TaskTemplate']['ContainerSpec']
                if change == 'config-content':
                    config['Spec']['Data'] = base64.b64encode(b'changed').decode()
                elif change == 'config-name':
                    container['Configs'][-1]['ConfigName'] = 'unreviewed'
                elif change == 'config-target':
                    container['Configs'][-1]['File']['Name'] = '/wrong-target'
                elif change == 'secret':
                    container['Secrets'].append({'SecretName': 'unexpected', 'File': {'Name': 'unexpected'}})
                else:
                    services['permissions-db']['Spec']['TaskTemplate']['Networks'][0]['Aliases'] = []
                with self.assertRaises(ValueError):
                    verify_effective(release, docker)

    @patch.object(monitor, 'installed', return_value=False)
    def test_without_explicit_provisioning_extra_monitor_secret_remains_drift(self, installed):
        release, services, _config, docker = fixture()
        services['redis']['Spec']['TaskTemplate']['ContainerSpec']['Configs'] = [
            {'ConfigName': value['name']}
            for value in release['infrastructure']['redis']['configs'].values()
        ]
        with self.assertRaises(ValueError):
            verify_effective(release, docker)

    @patch.object(monitor, 'installed', return_value=True)
    @patch('stack_runtime.subprocess.run')
    @patch('stack_runtime.render_release')
    def test_full_stack_reapply_is_refused_before_render_or_mutation(self, render, run, installed):
        with self.assertRaisesRegex(ValueError, 'reconciliar'):
            apply_release(candidate(), lambda *args: [])
        render.assert_not_called()
        run.assert_not_called()

    def test_transport_bundle_includes_monitor_compatibility_module(self):
        from ssh_deploy import BUNDLE_SCRIPTS
        self.assertIn('observability_deployment.py', BUNDLE_SCRIPTS)
