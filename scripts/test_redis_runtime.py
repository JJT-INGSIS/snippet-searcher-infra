"""SNI-56 cutover contracts, isolation and failure preflight."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bootstrap_swarm import plan_release
from deploy_service import deploy_locked
from redis_preflight import require_capacity
from redis_runtime import REDIS_IMAGE, specification
from rollout_checks import require_updated_callers
from stack_release import expected_images, permanent_services, select_release, update_service, validate_manifest, write_record
from stack_runtime import ROOT, apply_release, render_release
from test_deploy_service import FakeSwarm, release, request
import test_expanded_release


def candidate(environment='dev'):
    return plan_release(release(environment), install_redis=True)


class RedisRuntimeTests(unittest.TestCase):
    def test_opt_in_preserves_legacy_and_registers_only_reviewed_metadata(self):
        previous = release()
        before = copy.deepcopy(previous)
        result = candidate()
        validate_manifest(result)
        self.assertEqual(previous, before)
        self.assertNotIn('redis', expected_images(previous))
        self.assertEqual(expected_images(result)['redis'], REDIS_IMAGE)
        self.assertIn('redis', permanent_services(result, 'snippets-service'))
        self.assertEqual(result['images'], previous['images'])
        bad = copy.deepcopy(result)
        bad['infrastructure']['redis']['password'] = 'must-not-be-in-release'
        with self.assertRaises(ValueError): validate_manifest(bad)

    def test_actual_v062_reader_rejects_redis_before_deployment(self):
        raw = (ROOT / 'tests/legacy/v0.6.2-stack_release.txt').read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        self.assertEqual(blob, '306ed0228181b9167e9c05c6ed39f91463d859ef')
        namespace = {'__name__': 'legacy_release'}
        exec(compile(raw, 'v0.6.2-stack_release', 'exec'), namespace)
        namespace['validate_manifest'](release())
        with self.assertRaisesRegex(ValueError, 'desconocido'):
            namespace['validate_manifest'](candidate())

    @patch('redis_cd.require_redis_cd', return_value='a' * 40)
    def test_redis_cutover_rejects_v062_callers_and_active_runs(self, central):
        factory = test_expanded_release.RolloutGateTests().api
        with self.assertRaisesRegex(ValueError, 'antiguo'):
            require_updated_callers('dev', factory('v0.6.2'), redis=True)
        with self.assertRaisesRegex(ValueError, 'antiguo'):
            require_updated_callers('dev', factory('v0.6.3'), redis=True)
        require_updated_callers('dev', factory('v0.6.4'), redis=True)
        with self.assertRaisesRegex(ValueError, 'activas'):
            require_updated_callers('dev', factory('v0.6.4', active=True), redis=True)

    def test_central_tag_must_pin_redis_aware_tools_not_the_legacy_sha(self):
        from redis_cd import require_redis_cd, LEGACY_REVISION
        def reader(repository, path, revision):
            if repository == 'github-workflows':
                return '  INFRA_REVISION: ' + 'a' * 40 + '\r\n'
            self.assertEqual(revision, 'a' * 40)
            return (ROOT / path).read_text()
        self.assertEqual(require_redis_cd(reader), 'a' * 40)
        with self.assertRaisesRegex(ValueError, 'SHA nuevo'):
            require_redis_cd(lambda *args: '  INFRA_REVISION: ' + LEGACY_REVISION + '\n')
        with self.assertRaisesRegex(ValueError, 'contrato Redis'):
            require_redis_cd(lambda repo, *args: '  INFRA_REVISION: ' + 'a' * 40 + '\n' if repo == 'github-workflows' else '')

    def test_memory_and_disk_reserves_fail_before_installing(self):
        with tempfile.TemporaryDirectory() as folder:
            mem = Path(folder) / 'meminfo'
            mem.write_text('MemAvailable: 500000 kB\n')
            require_capacity(folder, lambda _: SimpleNamespace(free=1024**3), mem)
            with self.assertRaisesRegex(ValueError, '512'):
                require_capacity(folder, lambda _: SimpleNamespace(free=1), mem)
            mem.write_text('MemAvailable: 1000 kB\n')
            with self.assertRaisesRegex(ValueError, '384'):
                require_capacity(folder, lambda _: SimpleNamespace(free=1024**3), mem)

    def test_redis_transition_submits_no_unrelated_service_and_never_prunes(self):
        # Test submission boundary independently of Compose; renders are tested with the real CLI separately.
        rendered = {'services': {name: {'image': image} for name, image in expected_images(candidate()).items()}}
        with patch('stack_runtime.render_release', return_value=rendered), \
                patch('stack_runtime.validate_rendered', side_effect=json.dumps), \
                patch('stack_runtime.require_configs'), patch('stack_runtime.subprocess.run') as call:
            apply_release(candidate(), lambda *args: [], redis_transition=True)
        submitted = json.loads(call.call_args.kwargs['input'])
        self.assertEqual(set(submitted['services']), {'redis', 'snippets-service', 'printscript-service'})
        self.assertNotIn('--prune', call.call_args.args[0])

    def test_independent_cd_preserves_redis_and_every_other_image(self):
        for service in ('snippets-service', 'permissions-service', 'printscript-service'):
            previous = candidate()
            previous['checks'] = {'convergence': 'passed', 'sql_and_internal_http': 'passed'}
            target = request()
            target.update(service=service, repository='JJT-INGSIS/' + service,
                          **{'image-ref': 'ghcr.io/jjt-ingsis/' + service + '@sha256:' + 'e' * 64})
            with tempfile.TemporaryDirectory() as folder:
                state = Path(folder)
                write_record(state / 'release.json', previous)
                swarm = FakeSwarm(previous)
                deploy_locked(state, target, swarm, lambda _: None, lambda _: None)
                current = json.loads((state / 'release.json').read_text())
                self.assertEqual(current['infrastructure'], previous['infrastructure'])
                for name, image in expected_images(previous).items():
                    if name != service: self.assertEqual(swarm.current[name], image)

    def test_reapply_keeps_redis_data_identity_and_rejects_removal(self):
        previous = candidate()
        requested = copy.deepcopy(previous)
        requested['images']['permissions-service'] = 'ghcr.io/jjt-ingsis/permissions-service@sha256:' + 'f' * 64
        selected = select_release(requested, previous, change_infrastructure=True)
        self.assertEqual(selected['images'], previous['images'])
        self.assertEqual(selected['infrastructure']['redis'], previous['infrastructure']['redis'])
        requested['infrastructure'].pop('redis')
        with self.assertRaises(ValueError): select_release(requested, previous, change_infrastructure=True)

    def test_effective_spec_rejects_exposure_or_changed_coordination(self):
        from redis_runtime import verify_effective
        target = candidate()
        redis = {'Spec': {'Mode': {'Replicated': {'Replicas': 1}},
            'UpdateConfig': {'Order': 'stop-first'}, 'RollbackConfig': {'Order': 'stop-first'},
            'TaskTemplate': {'ContainerSpec': {'Command': ['sh', '/etc/redis/entrypoint.sh'],
                'Configs': [{'ConfigName': item['name']} for item in target['infrastructure']['redis']['configs'].values()],
                'Secrets': [{'SecretName': 'redis_password', 'File': {'Name': 'redis_password'}}],
                'Healthcheck': {'Test': ['CMD', 'sh', '/etc/redis/healthcheck.sh']}},
                'Networks': [{'Target': 'private'}],
                'Resources': {'Limits': {'MemoryBytes': 384 * 1024 * 1024, 'NanoCPUs': 500000000}}}}}
        coordinator = {'Spec': {'Mode': {'Replicated': {'Replicas': 1}},
            'UpdateConfig': {'Order': 'stop-first'}, 'RollbackConfig': {'Order': 'stop-first'},
            'TaskTemplate': {'ContainerSpec': {}, 'Networks': [{'Target': 'private'}]}}}
        snippets = copy.deepcopy(coordinator)
        snippets['Spec']['TaskTemplate']['ContainerSpec'] = {
            'Env': ['SPRING_DATA_REDIS_HOST=redis', 'SPRING_DATA_REDIS_PORT=6379'],
            'Secrets': [{'SecretName': 'redis_password', 'File': {'Name': 'spring.data.redis.password'}}]}
        services = {'redis': redis, 'snippets-service': snippets, 'printscript-service': coordinator}
        network = {'Internal': True}
        def docker(*args):
            return [network if args[0] == 'network' else services[args[-1].removeprefix('snippet-searcher-dev_')]]
        verify_effective(target, docker)
        cases = [
            (redis['Spec'], 'EndpointSpec', {'Ports': [{'PublishedPort': 6379}]}),
            (redis['Spec']['TaskTemplate']['ContainerSpec'], 'Env', ['REDIS_PASSWORD=forbidden']),
            (redis['Spec']['TaskTemplate']['Resources']['Limits'], 'NanoCPUs', 1000000000),
            (coordinator['Spec'], 'UpdateConfig', {'Order': 'start-first'}),
            (network, 'Internal', False)]
        for mapping, key, value in cases:
            previous = copy.deepcopy(mapping.get(key))
            mapping[key] = value
            with self.assertRaises(ValueError): verify_effective(target, docker)
            if previous is None: mapping.pop(key)
            else: mapping[key] = previous


if __name__ == '__main__':
    unittest.main()
