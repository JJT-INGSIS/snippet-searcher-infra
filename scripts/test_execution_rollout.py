"""Render execution coordinator replacements without deploying any service."""
import copy
import unittest

from redis_runtime import specification
from stack_runtime import render_release
from test_deploy_service import release
from test_expanded_release import expanded


class ExecutionRolloutTests(unittest.TestCase):
    def candidates(self):
        for environment in ('dev', 'prod'):
            yield environment, 'legacy', release(environment)
            value = expanded(environment, assets=False, ui=True)
            yield environment, 'expanded', value
            redis = copy.deepcopy(value)
            redis['infrastructure']['redis'] = specification(environment)
            yield environment, 'redis', redis

    def test_coordinators_never_overlap_during_update_or_rollback(self):
        for environment, topology, manifest in self.candidates():
            services = render_release(manifest)['services']
            for name in ('snippets-service', 'printscript-service'):
                with self.subTest(environment=environment, topology=topology, service=name):
                    deploy = services[name]['deploy']
                    self.assertEqual(deploy['replicas'], 1)
                    self.assertEqual(deploy['update_config']['order'], 'stop-first')
                    self.assertEqual(deploy['rollback_config']['order'], 'stop-first')
                    self.assertEqual(deploy['update_config']['parallelism'], 1)
                    self.assertEqual(deploy['update_config']['failure_action'], 'rollback')

    def test_stateless_services_keep_their_update_policy_and_data_mounts(self):
        for environment, topology, manifest in self.candidates():
            services = render_release(manifest)['services']
            with self.subTest(environment=environment, topology=topology):
                self.assertEqual(services['permissions-service']['deploy']['update_config']['order'], 'start-first')
                for name in ('ui', 'nginx'):
                    if name in services:
                        self.assertEqual(services[name]['deploy']['update_config']['order'], 'start-first')
                for name in ('snippets-db', 'permissions-db'):
                    self.assertEqual(services[name]['deploy']['update_config']['order'], 'stop-first')
                    self.assertTrue(services[name]['volumes'])
                self.assertTrue(services['snippets-service']['volumes'])


if __name__ == '__main__':
    unittest.main()
