import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import run_dev_drill


class DevDrillTests(unittest.TestCase):
    def test_prod_and_other_hosts_cannot_run_authenticated_mutations(self):
        for host in ('vm-snippet-prod', 'localhost'):
            with self.subTest(host=host), patch('run_dev_drill.socket.gethostname', return_value=host), \
                    patch('run_dev_drill.subprocess.run') as command, self.assertRaises(ValueError):
                run_dev_drill.run('healthy-create')
            command.assert_not_called()

    def test_unknown_scenario_never_starts_docker(self):
        with patch('run_dev_drill.subprocess.run') as command, self.assertRaises(ValueError):
            run_dev_drill.run('anything')
        command.assert_not_called()

    def test_job_uuid_is_required_before_starting_browser(self):
        with patch('run_dev_drill.socket.gethostname', return_value='vm-snippet-dev'), \
                patch.object(Path, 'is_file', return_value=True), \
                patch('run_dev_drill.subprocess.run') as command, self.assertRaises(ValueError):
            run_dev_drill.run('job-status', 'invalid')
        command.assert_not_called()

    def test_injection_must_be_explicit_and_only_for_the_negative_creation(self):
        for scenario, inject in [('printscript-unavailable', False), ('healthy-create', True)]:
            with self.subTest(scenario=scenario), patch('run_dev_drill.socket.gethostname', return_value='vm-snippet-dev'), \
                    patch.object(Path, 'is_file', return_value=True), \
                    patch('run_dev_drill.subprocess.run') as command, self.assertRaises(ValueError):
                run_dev_drill.run(scenario, inject_printscript=inject)
            command.assert_not_called()

    def test_printscript_is_not_interrupted_if_browser_never_authenticates(self):
        browser = Mock()
        browser.poll.return_value = 1
        with tempfile.TemporaryDirectory() as directory, \
                patch('run_dev_drill.subprocess.Popen', return_value=browser), \
                patch('run_dev_drill.subprocess.run') as command, self.assertRaises(ValueError):
            run_dev_drill.authenticated_injection(['docker', 'run'], directory)
        command.assert_not_called()

    def test_cut_requires_authenticated_handshake_and_preserves_exact_replica_target(self):
        browser = Mock()
        browser.poll.side_effect = [None, 0]
        browser.wait.return_value = 0
        specification = json.dumps([{'Spec': {'Mode': {'Replicated': {'Replicas': 1}}}}])
        with tempfile.TemporaryDirectory() as directory, \
                patch('run_dev_drill.subprocess.Popen', return_value=browser), \
                patch('run_dev_drill.subprocess.check_output', side_effect=[specification, '']), \
                patch('run_dev_drill.subprocess.run') as command, patch('builtins.print'):
            (Path(directory) / 'cut-requested').touch()
            result = run_dev_drill.authenticated_injection(['docker', 'run'], directory)
            self.assertEqual(result.returncode, 0)
            self.assertTrue((Path(directory) / 'cut-complete').is_file())
        self.assertEqual(command.call_args.args[0], [
            'docker', 'service', 'scale', '--detach=true', 'snippet-searcher-dev_printscript-service=0'])


if __name__ == '__main__':
    unittest.main()
