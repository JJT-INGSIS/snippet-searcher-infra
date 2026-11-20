"""Check environment isolation and the host/private collector boundary for PROD."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import production_observability_candidate as candidate


class ProductionCandidate(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((candidate.REPO / 'observability/config.prod-local.example.json').read_text())

    def test_candidate_is_offline_and_contains_only_prod_dispatch_destinations(self):
        with patch('subprocess.run', side_effect=AssertionError('No operational commands allowed')):
            result = candidate.bundle(self.config)
        self.assertEqual(result['status'], 'REVIEW_ONLY_NOT_APPLIED')
        self.assertNotIn('/dev/', json.dumps(result))
        self.assertNotIn('snippet-searcher-dev', json.dumps(result))
        self.assertNotIn('snippet-observability-dev', result['dispatch'])
        integrations = result['integrations']['integrations']
        self.assertEqual(len(integrations), 6)
        self.assertEqual({x['labels']['environment'] for x in integrations}, {'prod'})
        self.assertNotIn('variables', result['integrations'])
        self.assertNotIn('PASSWORD', json.dumps(result['integrations']))
        self.assertIn('/snippet-searcher/prod/release.json', json.dumps(integrations[-1]))

    def test_collector_has_no_host_access_license_or_published_ports(self):
        result = candidate.bundle(self.config)
        stack = result['collectorStack']
        collector = stack['services']['collector']
        self.assertTrue(collector['read_only'])
        self.assertEqual(collector['user'], '10001:10001')
        self.assertEqual(collector['cap_drop'], ['ALL'])
        self.assertNotIn('privileged', collector)
        self.assertNotIn('ports', collector)
        self.assertNotIn('environment', collector)
        self.assertEqual(set(stack['networks']), {'application'})
        self.assertEqual(stack['networks']['application']['name'], 'snippet-searcher-prod_default')
        self.assertNotIn('docker.sock', json.dumps(collector))
        self.assertNotIn('agent.json', json.dumps(collector))
        self.assertEqual(set(collector['secrets']), {'obs_snippets_db_password', 'obs_permissions_db_password'})
        mounts = {x['source']: x for x in collector['volumes'] if isinstance(x, dict) and x['type'] == 'volume'}
        self.assertEqual({x for x in mounts if not mounts[x]['read_only']}, {'storage-local'})
        self.assertEqual(len(mounts), 3)
        self.assertEqual(collector['deploy']['placement']['constraints'], ['node.hostname == vm-snippet-prod'])

    def test_host_agent_privilege_is_explicit_and_db_credentials_are_not_mounted(self):
        agent = candidate.bundle(self.config)['agentCompose']['services']['agent']
        self.assertTrue(agent['privileged'])
        self.assertIn('/var/run/docker.sock:/var/run/docker.sock', agent['volumes'])
        self.assertNotIn('obs_snippets_db_password', json.dumps(agent))
        self.assertNotIn('license_key', json.dumps(agent))
        self.assertNotIn('ports', agent)

    def test_topology_drift_is_rejected_instead_of_silently_collecting_another_environment(self):
        mutations = [
            lambda x: x.update(environment='dev'),
            lambda x: x.update(redis=json.loads((candidate.REPO / 'observability/config.example.json').read_text())['redis']),
            lambda x: x['postgres'][0].update(host='dev-snippets-db'),
            lambda x: x['postgres'][0].update(passwordFile='/etc/snippet-observability/dev/password'),
            lambda x: x['postgres'][0].update(database='other'),
            lambda x: x['storage'][0].update(path='/observed/dev'),
            lambda x: x['storage'].pop(),
            lambda x: x.update(license_key='not-a-real-secret'),
        ]
        for mutate in mutations:
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.subTest(config=config), self.assertRaises(ValueError):
                candidate.bundle(config)

    def test_dispatch_rejects_unapproved_service_before_calling_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'dispatch.sh'
            script.write_text(candidate.bundle(self.config)['dispatch'])
            for service in ('redis', 'storage-asset', 'snippets-db;exit 0', ''):
                with self.subTest(service=service):
                    result = subprocess.run(['sh', str(script), service], capture_output=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, b'')
                    self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
