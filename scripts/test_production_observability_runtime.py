import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import production_observability_runtime as runtime


class ProductionRuntimeTests(unittest.TestCase):
    def test_unknown_host_cannot_read_or_modify_docker(self):
        with patch.object(runtime.os, 'geteuid', return_value=0), \
                patch.object(runtime.socket, 'gethostname', return_value='vm-snippet-dev'), \
                patch.object(runtime, 'docker') as docker, self.assertRaises(ValueError):
            runtime.require_host()
        docker.assert_not_called()

    def test_changed_release_fails_before_any_grant_or_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            (state / 'release.json').write_text('{}')
            with patch.object(runtime, 'STATE', state), patch.object(runtime, 'require_host'), \
                    patch.object(runtime, 'docker') as docker, self.assertRaises(ValueError):
                runtime.provision('0' * 64)
            docker.assert_not_called()

    def test_existing_private_state_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'release.json').write_text('{}')
            (root / 'staged').touch()
            digest = hashlib.sha256(b'{}').hexdigest()
            with patch.object(runtime, 'STATE', root), patch.object(runtime, 'RUNTIME', root), \
                    patch.object(runtime, 'PRIVATE', root), patch.object(runtime, 'require_host'), \
                    patch.object(runtime, 'docker') as docker, self.assertRaises(ValueError):
                runtime.provision(digest)
            docker.assert_not_called()

    def test_secret_collision_stops_before_creating_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'release.json').write_text('{}')
            (root / 'staged').touch()
            private = root / 'private'
            with patch.object(runtime, 'STATE', root), patch.object(runtime, 'RUNTIME', root), \
                    patch.object(runtime, 'PRIVATE', private), patch.object(runtime, 'require_host'), \
                    patch.object(runtime, 'docker', return_value='obs_snippets_db_password'), self.assertRaises(ValueError):
                runtime.provision(hashlib.sha256(b'{}').hexdigest())
            self.assertFalse(private.exists())

    def test_native_exit_zero_without_metrics_is_not_success(self):
        def docker(*args, **kwargs):
            return 'collector-id' if args[0] == 'ps' else json.dumps({'metrics': []})
        with patch.object(runtime, 'require_host'), patch.object(runtime, 'docker', side_effect=docker), \
                self.assertRaisesRegex(ValueError, 'no metrics'):
            runtime.verify()

    def test_storage_failure_is_not_replaced_with_a_healthy_sample(self):
        def docker(*args, **kwargs):
            if args[0] == 'ps':
                return 'collector-id'
            return json.dumps({'metrics': [{}]} if args[-1].endswith('-db') else {'up': 0})
        with patch.object(runtime, 'require_host'), patch.object(runtime, 'docker', side_effect=docker), \
                self.assertRaisesRegex(ValueError, 'Storage'):
            runtime.verify()

    def test_provision_uses_stdin_and_does_not_update_application_services(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'release.json').write_text('{}')
            (root / 'staged').touch()
            calls = []
            def docker(*args, **kwargs):
                calls.append((args, kwargs))
                return ''
            with patch.object(runtime, 'STATE', root), patch.object(runtime, 'RUNTIME', root), \
                    patch.object(runtime, 'PRIVATE', root / 'private'), patch.object(runtime, 'require_host'), \
                    patch.object(runtime, 'healthy_container', side_effect=lambda s: s), \
                    patch.object(runtime, 'docker', side_effect=docker), patch.object(runtime, 'query', return_value=''), \
                    patch('builtins.print'):
                runtime.provision(hashlib.sha256(b'{}').hexdigest())
            self.assertFalse(any(args[:2] == ('service', 'update') for args, _ in calls))
            for args, kwargs in calls:
                if args[:2] == ('secret', 'create'):
                    self.assertEqual(args[-1], '-')
                    self.assertEqual(len(kwargs['data']), 64)
                    self.assertNotIn(kwargs['data'], args)
            self.assertEqual(len([1 for args, _ in calls if args[:2] == ('secret', 'create')]), 2)
            self.assertEqual((root / 'private/provisioned').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
