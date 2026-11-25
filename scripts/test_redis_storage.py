"""Non-destructive boundaries for manual Redis recovery."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from redis_runtime import REDIS_IMAGE
from redis_storage import backup, restore


class RedisStorageTests(unittest.TestCase):
    def fixture(self, folder):
        snapshot, secret = Path(folder) / 'snapshot.rdb', Path(folder) / 'password'
        snapshot.write_bytes(b'snapshot-fixture')
        secret.write_text('a' * 64)
        snapshot.with_suffix('.json').write_text(json.dumps({
            'format': 'redis-rdb-v1', 'image': REDIS_IMAGE,
            'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest()}))
        return snapshot, secret

    def test_existing_volume_is_never_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot, secret = self.fixture(folder)
            with patch('redis_storage.docker', return_value='existing\n') as docker:
                with self.assertRaisesRegex(ValueError, 'volumen nuevo'):
                    restore(snapshot, 'existing', secret)
            docker.assert_called_once_with('volume', 'ls', '--format', '{{.Name}}')

    def test_corrupted_backup_is_rejected_before_touching_docker(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot, secret = self.fixture(folder)
            snapshot.write_bytes(b'corrupt')
            with patch('redis_storage.docker') as docker:
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    restore(snapshot, 'fresh', secret)
            docker.assert_not_called()

    def test_existing_backup_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot, _ = self.fixture(folder)
            with patch('redis_storage.docker') as docker:
                with self.assertRaisesRegex(ValueError, 'sobrescribe'):
                    backup('redis', snapshot)
            docker.assert_not_called()

    def test_failed_volume_listing_cannot_be_treated_as_an_empty_host(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot, secret = self.fixture(folder)
            with patch('redis_storage.docker', side_effect=RuntimeError('unavailable')) as docker:
                with self.assertRaises(RuntimeError):
                    restore(snapshot, 'fresh', secret)
            self.assertEqual(docker.call_count, 1)


if __name__ == '__main__':
    unittest.main()
