import unittest
from pathlib import Path
from unittest.mock import patch

from deploy_service import Swarm
from test_expanded_release import expanded
from verify_stack import verify_snippets_jdbc


class SwarmVerificationTests(unittest.TestCase):
    def test_jdbc_startup_evidence_survives_more_than_200_request_logs(self):
        logs = 'Flyway jdbc:postgresql://snippets-db:5432/snippets\n' + 'request completed\n' * 5500
        with patch('verify_stack.container', return_value='current-container') as current, \
                patch('verify_stack.subprocess.check_output', return_value=logs) as read:
            verify_snippets_jdbc('snippet-searcher-prod')
        current.assert_called_once_with('snippet-searcher-prod', 'snippets-service')
        self.assertEqual(read.call_args.args[0], ['docker', 'logs', 'current-container'])

    def test_current_container_without_jdbc_evidence_still_fails(self):
        with patch('verify_stack.container', return_value='current-container'), \
                patch('verify_stack.subprocess.check_output', return_value='request completed\n'), \
                self.assertRaisesRegex(RuntimeError, 'contenedor actual'):
            verify_snippets_jdbc('snippet-searcher-prod')

    def test_configuration_is_checked_again_after_convergence(self):
        order = []
        with patch('stack_runtime.verify_service_configuration', side_effect=lambda *args: order.append('configuration')), \
                patch('deploy_service.subprocess.run', side_effect=lambda command, **options: order.append(Path(command[1]).name)):
            Swarm('dev').verify(expanded())
        self.assertEqual(order, ['configuration', 'wait_for_stack.py', 'configuration', 'verify_stack.py'])

    def test_a_rollback_that_restores_app_ports_after_convergence_fails_verification(self):
        outcomes = iter([None, ValueError('Sólo NGINX puede publicar puertos web en el stack ampliado')])

        def configuration(*args):
            failure = next(outcomes)
            if failure:
                raise failure

        with patch('stack_runtime.verify_service_configuration', side_effect=configuration), \
                patch('deploy_service.subprocess.run') as run, self.assertRaisesRegex(ValueError, 'Sólo NGINX'):
            Swarm('dev').verify(expanded())
        self.assertEqual([Path(call.args[0][1]).name for call in run.call_args_list], ['wait_for_stack.py'])
