import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import start_log_forwarder_dev as forwarder

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "observability/logs"
SECTION = re.compile(r"^\[([A-Z]+)\]$")
IMAGE = "fluent/fluent-bit:5.1.5@sha256:2740f387f6e68fab66d28e4fa6a853387b9cab6ffb4cb78958f69bba4eb0e7b4"
LICENSE_FILE = "/etc/snippet-observability/dev/agent.json"
FAKE_KEY = "fake-license-0123456789abcdef"
INGRESS_KEYS = {"time", "request_id", "method", "path", "route", "status", "bytes_sent", "request_time",
                "upstream", "upstream_status", "upstream_connect_time", "upstream_response_time",
                "logtype", "environment", "service"}
HOST_KEYS = {"MESSAGE", "PRIORITY", "logtype", "environment", "service"}
JOURNAL_FILTERS = {"ingress": "CONTAINER_TAG=snippet-ingress", "kernel": "_TRANSPORT=kernel",
                   "docker": "_SYSTEMD_UNIT=docker.service"}
OWNER_ONLY = 0o600


def sections():
    found, current = [], None
    for raw in (LOGS / "fluent-bit.conf").read_text().splitlines():
        line = raw.strip()
        header = SECTION.match(line)
        if header:
            current = {"section": header.group(1), "entries": []}
            found.append(current)
        elif line and not line.startswith("@") and current is not None:
            key, _, value = line.partition(" ")
            current["entries"].append((key.lower(), value.strip()))
    return found


def of(kind):
    return [section for section in sections() if section["section"] == kind]


def value(section, key):
    return dict(section["entries"]).get(key)


def values(section, key):
    return [item for name, item in section["entries"] if name == key]


def filters_for(tag):
    return [section for section in of("FILTER") if value(section, "match") == tag]


def compose():
    result = subprocess.run(["docker", "compose", "-f", str(LOGS / "forwarder.compose.yaml"), "config",
                             "--format", "json"], capture_output=True, text=True, check=True, timeout=30,
                            env={**os.environ, "SNIPPET_ENVIRONMENT": "dev"})
    return json.loads(result.stdout)["services"]["forwarder"]


class ForwarderConfigTests(unittest.TestCase):
    def test_only_three_journald_inputs_read_from_tail(self):
        inputs = of("INPUT")
        self.assertEqual({value(item, "tag") for item in inputs}, set(JOURNAL_FILTERS))
        for item in inputs:
            with self.subTest(tag=value(item, "tag")):
                self.assertEqual(value(item, "name"), "systemd")
                self.assertEqual(values(item, "systemd_filter"), [JOURNAL_FILTERS[value(item, "tag")]])
                self.assertEqual(value(item, "read_from_tail"), "On")
                self.assertIsNotNone(value(item, "db"))
                self.assertIsNotNone(value(item, "mem_buf_limit"))

    def test_kernel_lines_are_only_oom_and_docker_lines_only_warnings_or_worse(self):
        kernel = [value(item, "regex") for item in filters_for("kernel") if value(item, "name") == "grep"]
        self.assertEqual(len(kernel), 1)
        self.assertIn("Out of memory", kernel[0])
        docker = [value(item, "regex") for item in filters_for("docker") if value(item, "name") == "grep"]
        self.assertEqual(docker, ["PRIORITY ^[0-4]$"])

    def test_ingress_lines_are_parsed_as_json_from_the_message(self):
        parsers = [item for item in filters_for("ingress") if value(item, "name") == "parser"]
        self.assertEqual(len(parsers), 1)
        self.assertEqual(value(parsers[0], "key_name"), "MESSAGE")
        self.assertEqual(value(parsers[0], "reserve_data"), None)

    def test_each_stream_keeps_only_allowlisted_fields(self):
        for tag, keys in (("ingress", INGRESS_KEYS), ("kernel", HOST_KEYS), ("docker", HOST_KEYS)):
            modifiers = [item for item in filters_for(tag) if value(item, "name") == "record_modifier"]
            with self.subTest(tag=tag):
                self.assertEqual(len(modifiers), 1)
                added = {entry.split(" ")[0] for entry in values(modifiers[0], "record")}
                self.assertEqual(added, {"logtype", "environment", "service"})
                self.assertEqual(set(values(modifiers[0], "allowlist_key")), keys)

    def test_single_new_relic_output_with_license_from_the_include(self):
        outputs = of("OUTPUT")
        self.assertEqual(len(outputs), 1)
        self.assertEqual(value(outputs[0], "name"), "nrlogs")
        self.assertEqual(value(outputs[0], "match"), "*")
        self.assertEqual(value(outputs[0], "license_key"), "${" + forwarder.LICENSE_VARIABLE + "}")
        self.assertIsNotNone(value(outputs[0], "retry_limit"))
        self.assertIsNotNone(value(outputs[0], "storage.total_limit_size"))
        text = (LOGS / "fluent-bit.conf").read_text()
        self.assertIn("@INCLUDE " + forwarder.LICENSE_INCLUDE_TARGET, text)


class ForwarderContainerTests(unittest.TestCase):
    def test_pinned_image_outside_swarm_without_privileges_or_docker_socket(self):
        service = compose()
        self.assertEqual(service["image"], IMAGE)
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertNotIn("privileged", service)
        self.assertEqual(service["environment"], {"SNIPPET_ENVIRONMENT": "dev"})
        self.assertIn("mem_limit", service)
        self.assertIn("cpus", service)
        self.assertEqual(service["restart"], "unless-stopped")
        mounts = {item["target"]: item for item in service["volumes"]}
        self.assertNotIn("/var/run/docker.sock", mounts)
        self.assertEqual(mounts[forwarder.LICENSE_INCLUDE_TARGET]["source"],
                         "/etc/snippet-observability/dev/logs-license.conf")
        for target in ("/var/log/journal", "/etc/machine-id",
                       forwarder.LICENSE_INCLUDE_TARGET, "/fluent-bit/etc/fluent-bit.conf"):
            with self.subTest(target=target):
                self.assertTrue(mounts[target].get("read_only"))


class LicenseIncludeTests(unittest.TestCase):
    def test_include_reuses_the_agent_license(self):
        content = forwarder.license_include(json.dumps({"license_key": FAKE_KEY, "display_name": "x"}))
        self.assertEqual(content, "@SET " + forwarder.LICENSE_VARIABLE + "=" + FAKE_KEY + "\n")

    def test_invalid_agent_configuration_fails_without_echoing_the_value(self):
        for raw in ("{}", "not json", json.dumps({"license_key": FAKE_KEY + "\n@SET X=1"}),
                    json.dumps({"license_key": FAKE_KEY + "}"}), json.dumps({"license_key": "short"})):
            with self.subTest(raw=raw), self.assertRaises(ValueError) as error:
                forwarder.license_include(raw)
            self.assertNotIn(FAKE_KEY, str(error.exception))

    def test_private_file_is_owner_only_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "license.conf"
            forwarder.write_private(target, "@SET A=b\n")
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), OWNER_ONLY)
            with self.assertRaises(FileExistsError):
                forwarder.write_private(target, "@SET A=c\n")
            self.assertEqual(target.read_text(), "@SET A=b\n")

    def test_agent_license_path_is_the_one_from_sni82(self):
        self.assertEqual(str(forwarder.agent_configuration("dev")), LICENSE_FILE)


if __name__ == "__main__":
    unittest.main()
