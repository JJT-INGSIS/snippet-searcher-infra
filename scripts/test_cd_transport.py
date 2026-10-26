import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cd_evidence import build_request, inspect_image, main as evidence_main, publication_source, published_artifact, select_artifact, summary
from github_cd import ARTIFACT_FIELDS
from ssh_deploy import connection_options, main
from test_deploy_service import request


class RunnerContractTests(unittest.TestCase):
    def environment(self, **changes):
        value = request()
        return {'GITHUB_REPOSITORY': value['repository'], 'GITHUB_SHA': value['target-sha'],
                'GITHUB_REF': 'refs/heads/dev', 'GITHUB_EVENT_NAME': 'push',
                'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '1',
                'IMAGE_NAME': 'ghcr.io/jjt-ingsis/snippets-service', 'PLATFORMS': 'linux/amd64',
                'SOURCE_TREE': value['source-tree'], 'IMAGE_DIGEST': 'sha256:' + 'a' * 64, **changes}

    def test_publication_descriptor_survives_job_output_and_preserves_build_on_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'output'
            with patch.dict(os.environ, self.environment(GITHUB_OUTPUT=str(output)), clear=True), \
                    patch('cd_evidence.sys.argv', ['cd_evidence.py', 'published']):
                evidence_main()
            exported = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertEqual(set(exported), {'artifact'})
            artifact = json.loads(exported['artifact'])
            self.assertEqual(set(artifact), set(ARTIFACT_FIELDS))
            with patch.dict(os.environ, self.environment(GITHUB_RUN_ATTEMPT='2'), clear=True):
                retry = build_request(artifact)
            self.assertEqual(retry['image-ref'], request()['image-ref'])
            self.assertEqual(retry['source-tree'], request()['source-tree'])
            self.assertEqual(retry['run-attempt'], 2)
            self.assertEqual(retry['build-run-attempt'], 1)

    def test_publication_rejects_foreign_image_bad_platform_or_unverified_checkout(self):
        cases = [{'IMAGE_NAME': 'ghcr.io/another/service'}, {'PLATFORMS': 'linux/other'}, {}]
        for changes in cases:
            with self.subTest(changes=changes), patch.dict(os.environ, self.environment(**changes), clear=True), \
                    patch('cd_evidence.subprocess.check_output', return_value='f' * 40), self.assertRaises(ValueError):
                publication_source()

    def test_metadata_keeps_tree_and_platform_specific_cache_scope(self):
        with patch.dict(os.environ, self.environment(PLATFORMS='linux/amd64,linux/arm64'), clear=True), \
                patch('cd_evidence.subprocess.check_output', side_effect=['b' * 40, 'c' * 40]):
            source = publication_source()
        self.assertEqual(source['tree'], 'c' * 40)
        self.assertEqual(source['image'], 'ghcr.io/jjt-ingsis/snippets-service')
        self.assertEqual(source['cache-scope'], 'snippets-service-linux-amd64-linux-arm64')

    def test_select_uses_target_commit_tree_and_returns_exact_historical_artifact(self):
        from test_github_cd import FakeGitHub
        api = FakeGitHub()
        with patch.dict(os.environ, self.environment(GITHUB_REF='refs/heads/main', GITHUB_SHA='d' * 40,
                                                    PROD_DEPLOY_ENABLED='true'), clear=True):
            artifact = select_artifact(api)
            promoted = build_request(artifact)
        self.assertEqual(artifact['source-sha'], 'b' * 40)
        self.assertEqual(promoted['target-sha'], 'd' * 40)
        self.assertEqual(promoted['image-ref'], request()['image-ref'])
        self.assertIn(('/git/commits/' + 'd' * 40, None), api.calls)

    def test_main_publication_disabled_prod_and_pr_are_rejected_before_selection(self):
        from test_github_cd import FakeGitHub
        for changes in ({'PUBLISH_REQUESTED': 'true', 'PROD_DEPLOY_ENABLED': 'true'},
                        {'PROD_DEPLOY_ENABLED': 'false'},
                        {'GITHUB_EVENT_NAME': 'pull_request', 'PROD_DEPLOY_ENABLED': 'true'}):
            api = FakeGitHub()
            with self.subTest(changes=changes), patch.dict(os.environ,
                    self.environment(GITHUB_REF='refs/heads/main', **changes), clear=True), self.assertRaises(ValueError):
                select_artifact(api)
            self.assertEqual(api.calls, [])

    def test_invalid_build_digest_cannot_be_exported(self):
        with patch.dict(os.environ, self.environment(IMAGE_DIGEST='latest'), clear=True), self.assertRaises(ValueError):
            published_artifact()

    def test_prepare_checks_labels_once_and_writes_only_current_request(self):
        artifact = {key: request()[key] for key in ARTIFACT_FIELDS}
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'request.json'
            with patch.dict(os.environ, self.environment(ARTIFACT=json.dumps(artifact)), clear=True), \
                    patch('cd_evidence.sys.argv', ['cd_evidence.py', 'prepare', str(target)]), \
                    patch('cd_evidence.inspect_image') as inspect:
                evidence_main()
            self.assertEqual(json.loads(target.read_text()), request())
            inspect.assert_called_once_with(request())

    def test_summary_does_not_report_missing_receipt_as_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'summary.md'
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(output)}):
                summary(Path(temporary) / 'missing.json')
            self.assertIn('Despliegue no confirmado', output.read_text())

    def test_rerun_uses_original_build_attempt_and_current_verification_attempt(self):
        value = request()
        environment = {
            'GITHUB_REPOSITORY': value['repository'], 'GITHUB_SHA': value['target-sha'],
            'GITHUB_REF': 'refs/heads/dev', 'GITHUB_EVENT_NAME': 'push',
            'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '2',
        }
        with patch.dict(os.environ, environment, clear=True):
            result = build_request({key: value[key] for key in ARTIFACT_FIELDS})
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
                    self.assertEqual(json.loads(destination.read_text())['outcome'], 'recovered')
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
