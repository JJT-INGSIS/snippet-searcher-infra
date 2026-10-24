import contextlib
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import asset_probe as probe
import verify_asset_persistence as persistence


class AssetProbeTests(unittest.TestCase):
    def setUp(self):
        self.objects = {}
        self.calls = []
        objects, calls = self.objects, self.calls

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(("GET", self.path))
                if self.path == "/actuator/health":
                    self.reply(200, b'{"status":"UP"}', "application/json")
                else:
                    self.reply(200 if self.path in objects else 404, objects.get(self.path, b""))

            def do_PUT(self):
                calls.append(("PUT", self.path))
                objects[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
                self.reply(201)

            def do_DELETE(self):
                calls.append(("DELETE", self.path))
                existed = self.path in objects
                objects.pop(self.path, None)
                self.reply(204 if existed else 404)

            def reply(self, status, body=b"", media="application/octet-stream"):
                self.send_response(status)
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def test_real_http_preserves_empty_unicode_and_json_looking_code(self):
        probe.wait_ready(self.base)
        manifest = probe.prepare(self.base)
        self.assertEqual(len(self.objects), 3)
        self.assertEqual(json.loads(next(iter(self.objects.values())))["code"], "")
        probe.verify(self.base, manifest)
        probe.cleanup(self.base, manifest)
        self.assertFalse(self.objects)
        self.assertEqual(sum(method == "PUT" for method, _ in self.calls), 3)
        self.assertEqual(sum(method == "DELETE" for method, _ in self.calls), 6)

    def test_corrupt_or_missing_object_is_not_a_success(self):
        manifest = probe.prepare(self.base)
        path = probe.path_for(manifest, manifest["objects"][0])
        for body in (b"wrong", None):
            if body is None:
                self.objects.pop(path)
            else:
                self.objects[path] = body
            with self.assertRaises(probe.ProbeFailure):
                probe.verify(self.base, manifest)

    def test_server_failure_does_not_retry_writes(self):
        with patch.object(probe, "request", side_effect=[probe.Response(404, "", b""), probe.Response(503, "", b"")]) as outgoing:
            with self.assertRaises(probe.ProbeFailure):
                probe.prepare(self.base)
            self.assertEqual(outgoing.call_count, 2)

    def test_timeout_does_not_retry_writes(self):
        with patch.object(probe, "request", side_effect=[probe.Response(404, "", b""), probe.ProbeFailure("uncertain")]) as outgoing:
            with self.assertRaisesRegex(probe.ProbeFailure, "uncertain"):
                probe.prepare(self.base)
            self.assertEqual(outgoing.call_count, 2)

    def test_cleanup_cannot_target_normal_containers_or_traversal(self):
        manifest = probe.prepare(self.base)
        for container in ("snippets", "../snippets", "infra-sni33-" + "a" * 33):
            with self.subTest(container=container), self.assertRaises(probe.ProbeFailure):
                probe.cleanup(self.base, {**manifest, "container": container})
        manifest["objects"][0]["key"] = "../other"
        with self.assertRaises(probe.ProbeFailure):
            probe.cleanup(self.base, manifest)

    def test_wrong_content_type_is_rejected(self):
        manifest = probe.prepare(self.base)
        with patch.object(probe, "request", return_value=probe.Response(200, "text/html", probe.envelope(""))):
            with self.assertRaises(probe.ProbeFailure):
                probe.verify(self.base, manifest)

    def test_outage_cannot_be_reported_as_missing_or_success(self):
        manifest = probe.prepare(self.base)
        for status in (200, 404):
            with self.subTest(status=status), patch.object(probe, "request", return_value=probe.Response(status, "", b"")):
                with self.assertRaises(probe.ProbeFailure):
                    probe.unavailable(self.base, manifest)
        with patch.object(probe, "request", return_value=probe.Response(503, "", b"")):
            probe.unavailable(self.base, manifest)
        with patch.object(probe, "request", side_effect=probe.ProbeFailure("offline")):
            probe.unavailable(self.base, manifest)


class AssetProbeBoundaryTests(unittest.TestCase):
    def test_invalid_urls_are_rejected(self):
        for url in ("", "ftp://host", "http://user:secret@host", "http://host/x", "http://host?token=x",
                    "http://host#part", "http://host:99999", "http://host:0"):
            with self.subTest(url=url), patch.dict("os.environ", {"BASE": url}), self.assertRaises(probe.ProbeFailure):
                probe.base_url("BASE")

    def test_readiness_retries_technical_failures_but_not_client_error(self):
        results = [probe.ProbeFailure("offline"), probe.Response(503, "application/json", b"{}"),
                   probe.Response(200, "application/json", b'{"status":"UP"}')]
        with patch.object(probe, "request", side_effect=results), patch.object(probe.time, "sleep"):
            probe.wait_ready("http://asset")
        with patch.object(probe, "request", return_value=probe.Response(401, "application/json", b"{}")) as outgoing:
            with self.assertRaises(probe.ProbeFailure):
                probe.wait_ready("http://asset")
            outgoing.assert_called_once()

    def test_readiness_has_deadline_and_requires_up_json(self):
        with patch.object(probe.time, "monotonic", side_effect=[0, 121]), self.assertRaises(probe.ProbeFailure):
            probe.wait_ready("http://asset")
        for body in (b"{}", b"not json", b"[]", b'{"status":"DOWN"}'):
            with self.subTest(body=body), patch.object(probe, "request", return_value=probe.Response(200, "application/json", body)):
                with self.assertRaises(probe.ProbeFailure):
                    probe.wait_ready("http://asset")

    def test_response_size_is_bounded(self):
        from email.message import Message
        from unittest.mock import MagicMock
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.read.return_value = b"a" * 11
        reply.headers = Message()
        opener = MagicMock()
        opener.open.return_value = reply
        with patch.object(probe, "MAX_RESPONSE", 10), patch.object(probe, "build_opener", return_value=opener):
            with self.assertRaises(probe.ProbeFailure):
                probe.request("http://asset", "/")
            reply.read.assert_called_once_with(11)

    def test_persistence_runner_refuses_remote_docker(self):
        with patch.dict("os.environ", {"DOCKER_HOST": "ssh://vm-snippet-dev", "DOCKER_CONTEXT": ""}):
            with self.assertRaises(RuntimeError):
                persistence.local_engine()

    def test_selected_context_cannot_bypass_remote_guard_with_local_host(self):
        with patch.dict("os.environ", {"DOCKER_CONTEXT": "prod", "DOCKER_HOST": "unix:///tmp/docker.sock"}), \
                patch.object(persistence.subprocess, "check_output", return_value="ssh://vm-snippet-prod\n"):
            with self.assertRaises(RuntimeError):
                persistence.local_engine()

    def test_runner_cleans_own_containers_even_when_read_fails(self):
        from subprocess import CompletedProcess, CalledProcessError
        replies = ["", "old-a\nold-b\n", "{}", "", "new-a\nnew-b\n"]
        def run(command, **kwargs):
            if command[-1] == "verify":
                raise CalledProcessError(1, command)
            return CompletedProcess(command, 0, stdout=replies.pop(0) if replies else "")
        with patch.object(persistence, "local_engine"), patch.object(persistence.subprocess, "run", side_effect=run) as outgoing:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(CalledProcessError):
                persistence.verify()
        command = outgoing.call_args_list[-1].args[0]
        self.assertIn("down", command)
        self.assertIn("assets", command)
        self.assertNotIn("--volumes", command)

    def test_runner_retains_volume_and_only_targets_generated_project(self):
        from subprocess import CompletedProcess
        replies = ["", "old-asset\nold-blob\n", "{}", "", "new-asset\nnew-blob\n", "", "", "", "", "", "", ""]
        def run(command, **kwargs):
            return CompletedProcess(command, 0, stdout=replies.pop(0))
        with patch.object(persistence, "local_engine"), patch.object(persistence.subprocess, "run", side_effect=run) as outgoing:
            with contextlib.redirect_stdout(io.StringIO()):
                persistence.verify()
        for call in outgoing.call_args_list:
            command = call.args[0]
            self.assertIn("sni33-check-", command[command.index("-p") + 1])
            self.assertNotIn("--volumes", command)
            self.assertNotIn("-v", command)
        self.assertIn("down", outgoing.call_args_list[-1].args[0])


if __name__ == "__main__":
    unittest.main()
