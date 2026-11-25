import copy
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import observability_config as config
import storage_health as probe


class StorageHealthTests(unittest.TestCase):
    def settings(self, **values):
        return {
            "environment": "dev",
            "version": "test",
            "service": "storage-local",
            "kind": "local",
            **values,
        }

    def test_real_filesystem_roundtrip_leaves_other_files_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            untouched = Path(root) / "application-data"
            untouched.write_bytes(b"private original")
            result = probe.sample(self.settings(path=root))
            self.assertEqual(result["up"], 1)
            self.assertGreater(result["totalBytes"], 0)
            self.assertEqual(result["contentOk"], 1)
            self.assertEqual(list((Path(root) / ".sni82-probe").iterdir()), [])
            self.assertEqual(untouched.read_bytes(), b"private original")

    def test_private_directory_symlink_cannot_redirect_a_write(self):
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as other,
        ):
            (Path(root) / ".sni82-probe").symlink_to(other)
            result = probe.sample(self.settings(path=root))
            self.assertEqual(result["up"], 0)
            self.assertEqual(list(Path(other).iterdir()), [])
            self.assertNotIn(root, json.dumps(result))

    def test_missing_mount_is_failure_not_a_new_empty_directory(self):
        with tempfile.TemporaryDirectory() as root:
            missing = str(Path(root) / "missing")
            result = probe.sample(self.settings(path=missing))
            self.assertEqual(result["up"], 0)
            self.assertFalse(Path(missing).exists())

    def test_asset_checks_exact_bytes_not_only_http_200_and_bounds_leftovers(self):
        objects = {}
        corrupt = [False]

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                objects[self.path] = self.rfile.read(
                    int(self.headers["Content-Length"])
                )
                self.send_response(201)
                self.end_headers()

            def do_GET(self):
                self.send_response(200 if self.path in objects else 404)
                self.end_headers()
                self.wfile.write(
                    b"wrong bytes" if corrupt[0] else objects.get(self.path, b"")
                )

            def do_DELETE(self):
                objects.pop(self.path, None)
                self.send_response(204)
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            settings = self.settings(
                kind="asset", baseUrl=f"http://127.0.0.1:{server.server_port}"
            )
            self.assertEqual(probe.sample(settings)["up"], 1)
            self.assertEqual(objects, {})
            corrupt[0] = True
            for _ in range(2):
                result = probe.sample(settings)
                self.assertEqual(result["up"], 0)
                self.assertEqual(result["reason"], "content-mismatch")
            self.assertEqual(len(objects), 1)
            corrupt[0] = False
            self.assertEqual(probe.sample(settings)["up"], 1)
            self.assertEqual(objects, {})
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


class ObservabilityConfigTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(
            (
                Path(__file__).resolve().parent.parent
                / "observability/config.example.json"
            ).read_text()
        )

    def test_database_selection_does_not_collect_application_tables_or_queries(self):
        value = config.render(self.value, Path("/etc/obs.json"), Path("/opt/obs"))
        database = value["integrations"][0]
        self.assertEqual(
            json.loads(database["env"]["COLLECTION_LIST"]), {"snippets": {}}
        )
        self.assertEqual(database["env"]["ENABLE_QUERY_MONITORING"], "false")
        self.assertEqual(database["env"]["PASSWORD"], "${secret0}")
        self.assertEqual(
            value["variables"]["secret0"]["command"]["args"],
            ["/run/secrets/obs_snippets_db_password"],
        )
        self.assertEqual(value["integrations"][2]["env"]["CONFIG_INVENTORY"], "false")

    def test_plaintext_passwords_invalid_targets_duplicates_and_inactive_redis(self):
        for field, value in [
            ("password", "do-not-leak"),
            ("host", "http://untrusted"),
            ("port", True),
            ("username", "postgres"),
        ]:
            candidate = copy.deepcopy(self.value)
            candidate["postgres"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                config.validate(candidate)
        self.value["redis"] = None
        result = config.render(self.value, Path("/etc/obs.json"), Path("/opt/obs"))
        self.assertFalse(any(i["name"] == "nri-redis" for i in result["integrations"]))
        self.value["storage"][0]["service"] = "snippets-db"
        with self.assertRaises(ValueError):
            config.validate(self.value)

    def test_opt_in_overlays_keep_databases_private_and_separate_native_aliases(self):
        import subprocess
        import shutil

        if not shutil.which("docker"):
            self.skipTest("Docker Compose is required for overlay rendering")
        repo = Path(__file__).resolve().parent.parent
        environment = {
            **__import__("os").environ,
            "SNIPPETS_IMAGE": "example/snippets:qa",
            "PERMISSIONS_IMAGE": "example/permissions:qa",
            "PRINTSCRIPT_IMAGE": "example/printscript:qa",
            "POSTGRES_IMAGE": "postgres:18.6-bookworm",
        }
        command = ["docker", "compose"]
        for file in (
            "swarm/stack.yaml",
            "swarm/stack.redis.yaml",
            "swarm/stack.observability.yaml",
            "swarm/stack.observability-redis.yaml",
        ):
            command += ["-f", str(repo / file)]
        for name in ("dev", "prod"):
            result = subprocess.run(
                [*command, "config", "--format", "json"],
                env={**environment, "DEPLOY_ENV": name},
                capture_output=True,
                text=True,
                check=True,
            )
            value = json.loads(result.stdout)
            for service in ("snippets-db", "permissions-db"):
                self.assertNotIn("ports", value["services"][service])
                self.assertIn(
                    name + "-" + service,
                    value["services"][service]["networks"]["default"]["aliases"],
                )
            self.assertNotIn("ports", value["services"]["redis"])
            self.assertTrue(value["networks"]["redis_internal"]["internal"])


class IntegrationArchiveTests(unittest.TestCase):
    def test_checksum_and_tar_members_cannot_overwrite_outside_the_bundle(self):
        import hashlib
        import io
        import tarfile
        from install_observability_integrations import stage_archive

        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            for name in (
                "../../escape",
                "var/db/newrelic-infra/newrelic-integrations/bin/nri-redis",
                "var/db/newrelic-infra/newrelic-integrations/redis-definition.yml",
            ):
                data = b"test artifact"
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        data = payload.getvalue()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                stage_archive(data, "0" * 64, "nri-redis", Path(root))
            self.assertEqual(list(Path(root).iterdir()), [])
            stage_archive(
                data, hashlib.sha256(data).hexdigest(), "nri-redis", Path(root)
            )
            self.assertTrue(
                (
                    Path(root)
                    / "var/db/newrelic-infra/newrelic-integrations/bin/nri-redis"
                ).exists()
            )
            self.assertEqual(list(Path(root).iterdir())[0].name, "var")


if __name__ == "__main__":
    unittest.main()
