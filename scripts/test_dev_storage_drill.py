import unittest
from unittest.mock import patch

import run_dev_storage_drill as drill


class StorageDrillSafety(unittest.TestCase):
    def test_does_not_mutate_prod_or_a_local_docker_context(self):
        for host in ('vm-snippet-prod', 'localhost'):
            with self.subTest(host=host), patch.object(drill.socket, 'gethostname', return_value=host), \
                    patch.object(drill.subprocess, 'run') as command, self.assertRaises(ValueError):
                drill.run()
            command.assert_not_called()

    def test_never_replaces_an_already_readonly_or_another_volume(self):
        mount = {'Type': 'volume', 'Source': drill.SOURCE, 'Target': drill.TARGET, 'ReadOnly': False}
        def specification(row):
            return {'Spec': {'TaskTemplate': {'ContainerSpec': {'Mounts': [row]}}}}
        drill.require_original_mount(specification(mount))
        for change in ({'ReadOnly': True}, {'Source': 'user-data'}, {'Type': 'bind'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                drill.require_original_mount(specification(mount | change))

    def test_mount_order_and_empty_defaults_do_not_hide_real_configuration_drift(self):
        original = {'ContainerSpec': {'Image': 'fixed', 'Mounts': [
            {'Target': '/b', 'Source': 'second', 'VolumeOptions': {}, 'ReadOnly': False},
            {'Target': '/a', 'Source': 'first', 'ReadOnly': True}]}}
        equivalent = {'ContainerSpec': {'Image': 'fixed', 'DNSConfig': {}, 'StopGracePeriod': 10_000_000_000, 'Mounts': [
            {'Target': '/a', 'Source': 'first', 'ReadOnly': True},
            {'Target': '/b', 'Source': 'second'}]}}
        self.assertEqual(drill.equivalent_template_hash(original), drill.equivalent_template_hash(equivalent))
        import copy
        for update in ({'ReadOnly': True}, {'Source': 'another-volume'}):
            changed = copy.deepcopy(equivalent)
            changed['ContainerSpec']['Mounts'][1].update(update)
            self.assertNotEqual(drill.equivalent_template_hash(original), drill.equivalent_template_hash(changed))
        for key, value in (('DNSConfig', {'Nameservers': ['1.1.1.1']}), ('StopGracePeriod', 30_000_000_000)):
            changed = copy.deepcopy(equivalent)
            changed['ContainerSpec'][key] = value
            self.assertNotEqual(drill.equivalent_template_hash(original), drill.equivalent_template_hash(changed))
        changed = copy.deepcopy(equivalent)
        changed['ContainerSpec']['Image'] = 'another-image'
        self.assertNotEqual(drill.equivalent_template_hash(original), drill.equivalent_template_hash(changed))

    def test_only_the_collector_mount_changes_and_inverse_is_writable(self):
        with patch.object(drill.subprocess, 'run') as command:
            drill.change(True)
            drill.change(False)
        for call, suffix in zip(command.call_args_list, ('true', 'false')):
            args = call.args[0]
            self.assertEqual(args[-1], 'snippet-observability-dev_collector')
            self.assertEqual(args[-2], 'type=volume,source=snippet-searcher-dev_snippets_content,target=/observed/snippets-content,readonly=' + suffix)
            self.assertNotIn('snippet-searcher-dev_snippets-service', args)


if __name__ == '__main__':
    unittest.main()
