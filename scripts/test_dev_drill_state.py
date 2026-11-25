import copy
import unittest
from unittest.mock import patch

import dev_drill_state as state


class SnapshotComparison(unittest.TestCase):
    def test_configuration_change_and_incomplete_recovery_are_rejected(self):
        before = {'releaseSha256': 'original', 'services': [{'replicas': '1/1', 'image': 'digest-a'}]}
        state.compare(before, copy.deepcopy(before))
        for change in ({'replicas': '0/1'}, {'image': 'digest-b'}):
            after = copy.deepcopy(before)
            after['services'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                state.compare(before, after)
        with self.assertRaises(ValueError):
            state.compare(before, before | {'releaseSha256': 'another'})

    def test_prod_is_rejected_before_reading_deployment_or_docker(self):
        with patch.object(state.socket, 'gethostname', return_value='vm-snippet-prod'), \
                patch.object(state, 'output') as command, self.assertRaises(ValueError):
            state.snapshot()
        command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
