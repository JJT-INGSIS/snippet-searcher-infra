import unittest
from pathlib import Path
from unittest.mock import patch

from deploy_service import Swarm
from test_expanded_release import expanded


class SwarmVerificationTests(unittest.TestCase):
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