import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from deploy_service import CHECKS, deploy_locked, expected_images, reconcile
from stack_release import write_record


def release(environment='dev'):
    root = Path(__file__).resolve().parent.parent
    return {**json.loads((root / f'swarm/{environment}-release.json').read_text()), 'checks': CHECKS}


def request(environment='dev', run=10):
    return {'repository': 'JJT-INGSIS/snippets-service', 'service': 'snippets-service',
            'environment': environment, 'image-ref': 'ghcr.io/jjt-ingsis/snippets-service@sha256:' + 'a' * 64,
            'source-sha': 'b' * 40, 'source-tree': 'c' * 40, 'target-sha': 'b' * 40,
            'run-id': run, 'run-attempt': 1, 'build-run-id': run, 'build-run-attempt': 1}


class FakeSwarm:
    def __init__(self, previous):
        self.current = expected_images(previous)
        self.updates = []
        self.bad = set()
        self.interruption = None
        self.pull_failure = False
        self.auto_rollback = False

    def check_manager(self):
        pass

    def images(self):
        return dict(self.current)

    def pull(self, image):
        if self.pull_failure:
            raise subprocess.CalledProcessError(1, 'docker pull')

    def update(self, service, image):
        self.updates.append((service, image))
        if self.interruption == 'before':
            self.interruption = None
            raise KeyboardInterrupt()
        self.current[service] = image
        if self.auto_rollback:
            self.current[service] = self.previous_image
            self.auto_rollback = False
        if self.interruption == 'after':
            self.interruption = None
            raise KeyboardInterrupt()

    def verify(self, manifest):
        if self.current != expected_images(manifest) or any(image in self.bad for image in self.current.values()):
            raise RuntimeError('Convergencia o salud fallida')


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.previous = release()
        write_record(self.state / 'release.json', self.previous)
        self.swarm = FakeSwarm(self.previous)
        self.authorize = lambda value: None
        self.verify_evidence = lambda value: None

    def run_deploy(self, value=None):
        return deploy_locked(self.state, value or request(), self.swarm, self.authorize, self.verify_evidence)

    def test_updates_one_app_preserves_others_database_and_source_record(self):
        old = copy.deepcopy(self.previous)
        receipt = self.run_deploy()
        current = json.loads((self.state / 'release.json').read_text())
        self.assertEqual(receipt['outcome'], 'verified')
        self.assertEqual(current['images']['snippets-service'], request()['image-ref'])
        for name in ('permissions-service', 'printscript-service'):
            self.assertEqual(current['images'][name], old['images'][name])
        self.assertEqual(current['database_image'], old['database_image'])
        self.assertEqual(self.previous, old)
        self.assertFalse((self.state / 'pending.json').exists())

    def test_prod_does_not_require_other_images_to_match_dev(self):
        previous = release('prod')
        previous['images']['permissions-service'] = 'ghcr.io/jjt-ingsis/permissions-service@sha256:' + 'f' * 64
        write_record(self.state / 'release.json', previous)
        self.swarm = FakeSwarm(previous)
        self.run_deploy(request('prod'))
        self.assertEqual(self.swarm.current['permissions-service'], previous['images']['permissions-service'])

    def test_rejected_authorization_or_failed_pull_does_not_modify_services_or_record(self):
        before = (self.state / 'release.json').read_bytes()
        for failure in ('authorization', 'pull'):
            with self.subTest(failure=failure):
                self.authorize = lambda value: None
                self.swarm.pull_failure = failure == 'pull'
                if failure == 'authorization':
                    self.authorize = lambda value: (_ for _ in ()).throw(ValueError('obsolete'))
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    self.run_deploy()
                self.assertEqual(self.swarm.updates, [])
                self.assertEqual((self.state / 'release.json').read_bytes(), before)

    def test_drift_or_unverified_baseline_is_rejected(self):
        self.swarm.current['permissions-service'] = 'unexpected'
        with self.assertRaises(ValueError):
            self.run_deploy()
        self.assertEqual(self.swarm.updates, [])
        write_record(self.state / 'release.json', {**self.previous, 'checks': {'recovery': 'failed'}})
        with self.assertRaises(ValueError):
            self.run_deploy()

    def test_unhealthy_update_recovers_verified_digest_and_returns_failure_receipt(self):
        self.swarm.bad.add(request()['image-ref'])
        receipt = self.run_deploy()
        self.assertEqual(receipt['outcome'], 'recovered')
        self.assertEqual(self.swarm.current, expected_images(self.previous))
        current = json.loads((self.state / 'release.json').read_text())
        self.assertEqual(current['images'], self.previous['images'])
        self.assertEqual(current['checks'], CHECKS)

    def test_swarm_automatic_rollback_is_detected_without_resubmission(self):
        self.swarm.previous_image = self.previous['images']['snippets-service']
        self.swarm.auto_rollback = True
        receipt = self.run_deploy()
        self.assertEqual(receipt['outcome'], 'recovered')
        self.assertEqual(len(self.swarm.updates), 1)

    def test_failed_recovery_keeps_pending_and_does_not_claim_healthy_release(self):
        def unhealthy_after_update(service, image):
            self.swarm.current[service] = image
            self.swarm.bad.add(image)
        self.swarm.update = unhealthy_after_update
        with self.assertRaises(RuntimeError):
            self.run_deploy()
        self.assertTrue((self.state / 'pending.json').exists())
        self.assertEqual(json.loads((self.state / 'release.json').read_text())['checks'], {'recovery': 'failed'})
        self.swarm.bad.clear()
        receipt = reconcile(self.state, self.swarm)
        self.assertEqual(receipt['outcome'], 'recovered')

    def test_interrupt_after_acceptance_reconciles_success_without_second_update(self):
        self.swarm.interruption = 'after'
        with self.assertRaises(KeyboardInterrupt):
            self.run_deploy()
        self.assertTrue((self.state / 'pending.json').exists())
        self.assertEqual(json.loads((self.state / 'release.json').read_text())['images'], self.previous['images'])
        receipt = self.run_deploy()
        self.assertEqual(receipt['outcome'], 'verified')
        self.assertEqual(len(self.swarm.updates), 1)

    def test_interrupt_before_acceptance_reconciles_unchanged_state_as_failure(self):
        self.swarm.interruption = 'before'
        with self.assertRaises(KeyboardInterrupt):
            self.run_deploy()
        receipt = self.run_deploy()
        self.assertEqual(receipt['outcome'], 'recovered')
        self.assertEqual(self.swarm.current, expected_images(self.previous))
        self.assertEqual(len(self.swarm.updates), 1)

    def test_interrupt_between_journal_and_release_write_completes_atomically(self):
        from deploy_service import write_record as original
        failed = False
        def interrupted(path, value):
            nonlocal failed
            if path.name == 'release.json' and not failed:
                failed = True
                raise KeyboardInterrupt()
            original(path, value)
        with patch('deploy_service.write_record', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.run_deploy()
        receipt = self.run_deploy()
        self.assertEqual(receipt['outcome'], 'verified')
        self.assertFalse((self.state / 'pending.json').exists())
        self.assertEqual(len(self.swarm.updates), 1)

    def test_changed_retry_payload_and_out_of_order_runs_are_rejected(self):
        self.swarm.interruption = 'after'
        with self.assertRaises(KeyboardInterrupt):
            self.run_deploy()
        changed = {**request(), 'image-ref': 'ghcr.io/jjt-ingsis/snippets-service@sha256:' + 'e' * 64}
        with self.assertRaises(ValueError):
            self.run_deploy(changed)
        self.run_deploy()
        with self.assertRaises(ValueError):
            self.run_deploy(request(run=9))
        self.assertEqual(len(self.swarm.updates), 1)

    def test_old_completed_retry_cannot_overwrite_new_deployment(self):
        self.run_deploy()
        newer = {**request(run=11), 'image-ref': 'ghcr.io/jjt-ingsis/snippets-service@sha256:' + 'e' * 64}
        self.run_deploy(newer)
        with self.assertRaises(ValueError):
            self.run_deploy()
        self.assertEqual(self.swarm.current['snippets-service'], newer['image-ref'])

    def test_pending_unexpected_image_requires_intervention(self):
        self.swarm.interruption = 'after'
        with self.assertRaises(KeyboardInterrupt):
            self.run_deploy()
        self.swarm.current['snippets-service'] = 'unexpected-external-update'
        with self.assertRaises(ValueError):
            reconcile(self.state, self.swarm)
        self.assertEqual(len(self.swarm.updates), 1)

    def test_authorization_rechecked_inside_operation_before_submission(self):
        calls = []
        def authorization(value):
            calls.append(value)
            if len(calls) == 2:
                raise ValueError('Branch advanced during pull')
        self.authorize = authorization
        with self.assertRaises(ValueError):
            self.run_deploy()
        self.assertEqual(self.swarm.updates, [])
        self.assertFalse((self.state / 'pending.json').exists())

    def test_missing_prod_evidence_rejects_update_under_lock(self):
        previous = release('prod')
        write_record(self.state / 'release.json', previous)
        self.swarm = FakeSwarm(previous)
        self.verify_evidence = lambda value: (_ for _ in ()).throw(ValueError('No verified dev image'))
        before = (self.state / 'release.json').read_bytes()
        with self.assertRaises(ValueError):
            self.run_deploy(request('prod'))
        self.assertEqual(self.swarm.updates, [])
        self.assertEqual((self.state / 'release.json').read_bytes(), before)

    def test_new_attempt_verifies_same_digest_without_resubmitting_update(self):
        self.run_deploy()
        retry = {**request(), 'run-attempt': 2}
        receipt = self.run_deploy(retry)
        self.assertEqual(receipt['run-attempt'], 2)
        self.assertEqual(receipt['build-run-attempt'], 1)
        self.assertEqual(len(self.swarm.updates), 1)

    @unittest.skipUnless(os.name == 'posix', 'fcntl requires Linux (CI or disposable Docker runner)')
    def test_cd_waits_for_existing_bootstrap_flock_on_same_file(self):
        import fcntl
        import select
        import sys
        code = ('from pathlib import Path; from deploy_service import deployment_lock; '
                'import sys\nprint("ready", flush=True)\n'
                'with deployment_lock(Path(sys.argv[1])): print("acquired", flush=True)')
        with (self.state / 'deploy.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            process = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.state)],
                                       cwd=Path(__file__).resolve().parent,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                self.assertEqual(select.select([process.stdout], [], [], 0.15)[0], [])
                fcntl.flock(lock, fcntl.LOCK_UN)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout.strip(), 'acquired')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == '__main__':
    unittest.main()
