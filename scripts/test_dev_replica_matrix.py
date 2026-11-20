import unittest

from run_dev_replica_matrix import original_replicas, validate_baseline


class ReplicaMatrixSafetyTests(unittest.TestCase):
    def test_prod_is_rejected_even_when_flags_are_healthy(self):
        with self.assertRaises(ValueError):
            validate_baseline('vm-snippet-prod', {'environment': 'prod', 'background': {
                'publisher': True, 'consumer': True}}, False)

    def test_pending_deploy_and_paused_consumer_cannot_overlap_with_a_fault(self):
        healthy = {'environment': 'dev', 'background': {'publisher': True, 'consumer': True}}
        validate_baseline('vm-snippet-dev', healthy, False)
        with self.assertRaises(ValueError):
            validate_baseline('vm-snippet-dev', healthy, True)
        with self.assertRaises(ValueError):
            validate_baseline('vm-snippet-dev', healthy | {'background': {
                'publisher': True, 'consumer': False}}, False)

    def test_a_preexisting_zero_replica_state_is_never_overwritten(self):
        for replicas in (0, 2, None):
            with self.subTest(replicas=replicas), self.assertRaises(ValueError):
                original_replicas({'Spec': {'Mode': {'Replicated': {'Replicas': replicas}}}})
        self.assertEqual(original_replicas({'Spec': {'Mode': {'Replicated': {'Replicas': 1}}}}), 1)


if __name__ == '__main__':
    unittest.main()
