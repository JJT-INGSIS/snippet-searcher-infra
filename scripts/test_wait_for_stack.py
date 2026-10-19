import os
import unittest
from unittest.mock import patch

from wait_for_stack import converged, VARIABLES


class RollbackConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.image = 'ghcr.io/jjt-ingsis/example@sha256:' + 'a' * 64
        self.environment = {name: self.image for name in (*VARIABLES, 'POSTGRES_IMAGE')}
        self.status = 'rollback_started'
        self.actual_image = self.image

    def docker(self, *arguments):
        if arguments[:2] == ('service', 'inspect'):
            return [{'UpdateStatus': {'State': self.status},
                     'Spec': {'TaskTemplate': {'ContainerSpec': {'Image': self.actual_image}},
                              'Mode': {'Replicated': {'Replicas': 1}}}}]
        return [{'Status': {'State': 'running'},
                 'Spec': {'ContainerSpec': {'Image': self.actual_image}}}]

    def converged(self):
        with patch.dict(os.environ, self.environment), \
                patch('wait_for_stack.docker_json', side_effect=self.docker), \
                patch('wait_for_stack.subprocess.check_output', return_value='task-id\n'):
            return converged('snippet-searcher-dev')

    def test_recovery_waits_while_swarm_rolls_back_to_expected_digest(self):
        self.assertFalse(self.converged())

    def test_candidate_rejected_when_swarm_rolls_back_to_another_digest(self):
        self.actual_image = self.image.replace('a' * 64, 'b' * 64)
        with self.assertRaisesRegex(RuntimeError, 'no mantiene el digest solicitado'):
            self.converged()

    def test_paused_rollback_remains_a_failure(self):
        self.status = 'rollback_paused'
        with self.assertRaisesRegex(RuntimeError, 'rollback_paused'):
            self.converged()

    def test_completed_rollback_can_converge_with_expected_running_tasks(self):
        self.status = 'rollback_completed'
        self.assertTrue(self.converged())


if __name__ == '__main__':
    unittest.main()
