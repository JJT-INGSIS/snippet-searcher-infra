"""Privacy and isolation guarantees of the dedicated PROD browser publisher."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / 'observability/newrelic/prod-functional/run.py'
spec = importlib.util.spec_from_file_location('prod_functional', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ProdFunctionalTest(unittest.TestCase):
    def test_missing_identity_never_launches_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(runner, 'CREDENTIALS', Path(folder) / 'absent.json'):
                with patch.object(runner.subprocess, 'run') as execute:
                    self.assertEqual(runner.execute_check(), ('FAILURE', 'CONFIGURATION'))
                    execute.assert_not_called()

    def test_event_has_only_minimal_prod_result_without_credentials(self):
        class Receipt:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b'{"success":true,"uuid":"receipt"}'

        class Publisher:
            request = None
            def open(self, request, timeout):
                self.request = request
                return Receipt()

        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)
            (config / 'agent.json').write_text(json.dumps({'license_key': 'private-ingest-key'}))
            publisher = Publisher()
            with patch.object(runner, 'CONFIG', config):
                with patch.object(runner.urllib.request, 'build_opener', return_value=publisher):
                    runner.publish('SUCCESS', 'NONE', 123)
            payload = json.loads(publisher.request.data)
            self.assertEqual(payload, [{'eventType': 'SnippetFunctionalCheck', 'environment': 'prod',
                                       'checkName': 'snippet-searcher-prod-functional-listing',
                                       'result': 'SUCCESS', 'durationMs': 123, 'failureCategory': 'NONE'}])
            self.assertNotIn('private-ingest-key', publisher.request.data.decode())

    def test_missing_acknowledgement_is_not_success(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b'{"success":false}'

        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)
            (config / 'agent.json').write_text('{"license_key":"test"}')
            with patch.object(runner, 'CONFIG', config):
                with patch.object(runner.urllib.request, 'build_opener') as opener:
                    opener.return_value.open.return_value = Response()
                    with self.assertRaisesRegex(ValueError, 'event not acknowledged'):
                        runner.publish('SUCCESS', 'NONE', 10)


if __name__ == '__main__':
    unittest.main()
