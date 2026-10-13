import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cd_evidence import build_request, inspect_image
from ssh_deploy import connection_options, main
from test_deploy_service import request


class RunnerContractTests(unittest.TestCase):
    def test_rerun_uses_original_build_attempt_and_current_verification_attempt(self):
        value = request()
        environment = {
            'GITHUB_REPOSITORY': value['repository'], 'GITHUB_SHA': value['target-sha'],
            'DEPLOY_ENV': 'dev', 'IMAGE_REF': value['image-ref'], 'SOURCE_SHA': value['source-sha'],
            'SOURCE_TREE': value['source-tree'], 'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '2',
            'BUILD_RUN_ID': '10', 'BUILD_RUN_ATTEMPT': '1',
        }
        with patch.dict(os.environ, environment, clear=True):
            result = build_request()
        self.assertEqual(result['run-attempt'], 2)
        self.assertEqual(result['build-run-attempt'], 1)

    def test_image_labels_must_match_original_build_and_exact_source(self):
        value = request()
        labels = {
            'org.opencontainers.image.source': f'https://github.com/{value["repository"]}',
            'org.opencontainers.image.revision': value['source-sha'],
            'io.jjt.source-tree': value['source-tree'],
            'io.jjt.actions-run': f'https://github.com/{value["repository"]}/actions/runs/10',
            'io.jjt.actions-run-attempt': '1',
        }
        image = {'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Labels': labels}}
        with patch('cd_evidence.subprocess.run') as pull, \
                patch('cd_evidence.subprocess.check_output', side_effect=lambda *a, **kw: json.dumps([image])):
            inspect_image(value)
            self.assertIn(value['image-ref'], pull.call_args.args[0])
            labels['io.jjt.actions-run-attempt'] = '2'
            with self.assertRaises(ValueError):
                inspect_image(value)

    def test_ssh_requires_secrets_and_strict_host_identity(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {'SSH_PRIVATE_KEY': 'test-key', 'SSH_KNOWN_HOSTS': 'test-host-key'}):
            ssh, scp, destination = connection_options('host.example', 'azureuser', '22', Path(temporary))
            self.assertEqual(destination, 'azureuser@host.example')
            for command in (ssh, scp):
                self.assertIn('StrictHostKeyChecking=yes', command)
                self.assertIn('BatchMode=yes', command)
            os.environ['SSH_PRIVATE_KEY'] = ''
            with self.assertRaises(ValueError):
                connection_options('host.example', 'azureuser', '22', Path(temporary))
            with self.assertRaises(ValueError):
                connection_options('host; touch /tmp/unwanted', 'azureuser', '22', Path(temporary))

    def exercise_transport(self, outcome):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / 'request.json', root / 'receipt.json'
            source.write_text(json.dumps(request()))
            submitted = []
            commands = []
            def remote(command, **kwargs):
                commands.append(command)
                if command[0] == 'ssh' and 'sudo -n python3' in command[-1]:
                    submitted.append(kwargs['input'])
                    # First connection lost after submission; retry reads the same
                    # operation instead of inventing a different request.
                    return subprocess.CompletedProcess(command, 255 if len(submitted) == 1 else 0)
                if command[0] == 'scp' and '/operations/' in command[-2]:
                    record = {'state': outcome, 'request': request(),
                              'receipt': {**request(), 'outcome': outcome}}
                    Path(command[-1]).write_text(json.dumps(record))
                return subprocess.CompletedProcess(command, 0)
            environment = {'INFRA_REVISION': 'a' * 40, 'SSH_HOST': 'host.example', 'SSH_USER': 'azureuser',
                           'SSH_PORT': '22', 'SSH_PRIVATE_KEY': 'test-key', 'SSH_KNOWN_HOSTS': 'test-host-key',
                           'GH_TOKEN': 'test-token-stdin-only'}
            with patch.dict(os.environ, environment), \
                    patch('ssh_deploy.sys.argv', ['ssh_deploy.py', str(source), str(destination)]), \
                    patch('ssh_deploy.subprocess.run', side_effect=remote):
                if outcome == 'verified':
                    main()
                    self.assertEqual(json.loads(destination.read_text())['outcome'], 'verified')
                else:
                    with self.assertRaises(RuntimeError):
                        main()
                    self.assertFalse(destination.exists())
            self.assertEqual(len(submitted), 2)
            self.assertEqual(submitted[0], submitted[1])
            self.assertEqual(json.loads(submitted[0])['token'], environment['GH_TOKEN'])
            self.assertFalse(any(environment['GH_TOKEN'] in str(command) for command in commands))

    def test_lost_ssh_response_retries_same_request_and_recovers_verified_receipt(self):
        self.exercise_transport('verified')

    def test_recovered_remote_version_keeps_runner_failed(self):
        self.exercise_transport('recovered')


if __name__ == '__main__':
    unittest.main()
