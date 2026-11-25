import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from verify_asset_persistence import local_engine
from verify_nginx import ACCESS_FIELDS, request, require

ROOT = Path(__file__).resolve().parent.parent
FORWARDER_CONFIG = ROOT / "observability/logs/fluent-bit.conf"
TRUSTED_FILTERS = {"Systemd_Filter _TRANSPORT=kernel": "Systemd_Filter SYSLOG_IDENTIFIER=fixture-kernel",
                   "Systemd_Filter _SYSTEMD_UNIT=docker.service": "Systemd_Filter SYSLOG_IDENTIFIER=fixture-docker"}
STDOUT_OUTPUT = "[OUTPUT]\n    Name   stdout\n    Match  *\n    Format json_lines\n"
FAKE_LICENSE = "@SET NR_LICENSE_KEY=fixture-license-0123456789abcdef\n"
ADDED_FIELDS = {"logtype", "environment", "service"}
OUTPUT_FIELDS = {"date"}
HOST_FIELDS = {"MESSAGE", "PRIORITY"}
SECRET_QUERY = "token=fixture-secret"
REQUESTS = ("/api/snippets?" + SECRET_QUERY, "/api/missing", "/", "/editor/1",
            "/api/executions/550e8400-e29b-41d4-a716-446655440000")
OOM_LINE = "Out of memory: Killed process 4242 (java) total-vm:1024kB"
KERNEL_NOISE = "eth0: link becomes ready"
DOCKER_WARNING = "fixture: task failed with exit 137"
DOCKER_INFO = "fixture: routine info"
WARNING_PRIORITY = 3
INFO_PRIORITY = 6
DOCKER_DRIVER_FIELDS = {"CONTAINER_ID": "0123456789ab", "CONTAINER_NAME": "snippet-searcher-dev_nginx.1.x",
                        "IMAGE_NAME": "nginx:1.30.6-alpine", "SYSLOG_IDENTIFIER": "snippet-ingress"}
SEED_REQUEST_ID = "0" * 32
SEED_ENTRIES = ({"MESSAGE": json.dumps({"request_id": SEED_REQUEST_ID}), "CONTAINER_TAG": "snippet-ingress"},
                {"MESSAGE": "Out of memory: seed before start", "SYSLOG_IDENTIFIER": "fixture-kernel", "PRIORITY": "3"},
                {"MESSAGE": "fixture: seed before start", "SYSLOG_IDENTIFIER": "fixture-docker", "PRIORITY": "3"})
WAIT_SECONDS = 40
POLL_SECONDS = 1
COMPOSE_SECONDS = 300


def fixture_config():
    text = FORWARDER_CONFIG.read_text()
    for production, fixture in TRUSTED_FILTERS.items():
        require(text.count(production) == 1, "Production journald filter changed: " + production)
        text = text.replace(production, fixture)
    require(text.count("[OUTPUT]") == 1, "Forwarder must have exactly one output")
    return text[:text.index("[OUTPUT]")] + STDOUT_OUTPUT


def journal_entry(fields):
    return "".join(name + "=" + value + "\n" for name, value in fields.items())


class Project:
    def __init__(self, file, environment):
        self.name = "sni80-check-" + uuid4().hex[:12]
        self.file = file
        self.environment = environment

    def run(self, *arguments, text_input=None):
        command = ["docker", "compose", "--env-file", os.devnull, "-p", self.name, "-f", str(self.file), *arguments]
        return subprocess.run(command, env=self.environment, check=True, timeout=COMPOSE_SECONDS, text=True,
                              input=text_input, stdout=subprocess.PIPE).stdout.strip()


def nginx_lines():
    environment = {**os.environ, "SNIPPETS_DB_PASSWORD": "unused-validation", "PERMISSIONS_DB_PASSWORD": "unused-validation",
                   "GITHUB_ACTOR": "unused-validation", "GITHUB_TOKEN": "unused-validation", "PROXY_HTTP_PORT": "0",
                   "FIXTURE_PROXY_HOSTNAME": "snippet.test"}
    project = Project(ROOT / "tests/nginx/compose.yaml", environment)
    try:
        project.run("--profile", "ingress", "up", "-d", "--wait", "nginx", "snippets-service", "ui")
        port = int(project.run("--profile", "ingress", "port", "nginx", "8080").rsplit(":", 1)[1])
        for path in REQUESTS:
            request(port, path)
        logs = project.run("--profile", "ingress", "logs", "--no-color", "--no-log-prefix", "nginx")
    finally:
        project.run("--profile", "ingress", "down", "--timeout", "5")
    lines = [line for line in logs.splitlines() if line.startswith("{")]
    require(len(lines) == len(REQUESTS), "NGINX did not write one JSON line per request")
    return lines


def inject(project, entries):
    for fields in entries:
        project.run("exec", "-T", "journal", "logger", "--journald", text_input=journal_entry(fields))


def forwarded(project, expected):
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        logs = project.run("logs", "--no-color", "--no-log-prefix", "forwarder")
        records = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
        if len(records) >= expected or time.monotonic() >= deadline:
            return records, logs
        time.sleep(POLL_SECONDS)


def check(records, logs, lines):
    by_type = {}
    for record in records:
        by_type.setdefault(record.get("logtype"), []).append(record)
    ingress = by_type.get("nginx-ingress", [])
    require(len(ingress) == len(lines), "Every NGINX line must arrive once and the malformed one must be dropped; got "
            + str({kind: len(items) for kind, items in by_type.items()}))
    require(all(set(record) == ACCESS_FIELDS | ADDED_FIELDS | OUTPUT_FIELDS for record in ingress),
            "Ingress records must keep only the allowlisted fields")
    require({record["route"] for record in ingress} == {"api", "executions", "ui"}, "Routes lost on the way")
    require({record["request_id"] for record in ingress} == {json.loads(line)["request_id"] for line in lines},
            "Request IDs changed on the way")
    require(all(record["environment"] == "dev" and record["service"] == "nginx" for record in ingress),
            "Ingress identity attributes missing")
    kernel = by_type.get("host-kernel", [])
    require([record["MESSAGE"] for record in kernel] == [OOM_LINE], "Only kernel OOM lines may pass")
    docker = by_type.get("host-docker", [])
    require([record["MESSAGE"] for record in docker] == [DOCKER_WARNING], "Only Docker warnings or worse may pass")
    require(all(set(record) == HOST_FIELDS | ADDED_FIELDS | OUTPUT_FIELDS for record in kernel + docker),
            "Host records must keep only the allowlisted fields")
    require(set(by_type) == {"nginx-ingress", "host-kernel", "host-docker"}, "Unexpected records forwarded")
    for leaked in ("fixture-secret", "CONTAINER_", "_HOSTNAME", "fixture-license", SEED_REQUEST_ID, "seed before start"):
        require(leaked not in logs, "Forwarder output leaked " + leaked)


def verify():
    local_engine()
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        (fixture / "machine-id").write_text(uuid4().hex + "\n")
        (fixture / "license.conf").write_text(FAKE_LICENSE)
        (fixture / "fluent-bit.conf").write_text(fixture_config())
        lines = nginx_lines()
        print("PASS real NGINX wrote " + str(len(lines)) + " JSON access lines", flush=True)
        environment = {**os.environ, "SNIPPET_ENVIRONMENT": "dev", "FIXTURE_DIRECTORY": directory}
        project = Project(ROOT / "tests/logs/compose.yaml", environment)
        project.environment["FIXTURE_FORWARDER"] = project.name + "-forwarder"
        print("SNI-80 isolated project: " + project.name, flush=True)
        try:
            project.run("up", "-d", "--build", "--wait", "journal")
            project.run("exec", "-T", "journal", "journalctl", "--flush")
            inject(project, SEED_ENTRIES)
            project.run("up", "-d", "forwarder")
            time.sleep(POLL_SECONDS * 3)
            ingress = [{"MESSAGE": line, "CONTAINER_TAG": "snippet-ingress", "PRIORITY": str(INFO_PRIORITY),
                        **DOCKER_DRIVER_FIELDS} for line in lines]
            malformed = {"MESSAGE": "not json " + SECRET_QUERY, "CONTAINER_TAG": "snippet-ingress"}
            host = [{"MESSAGE": OOM_LINE, "SYSLOG_IDENTIFIER": "fixture-kernel", "PRIORITY": str(WARNING_PRIORITY)},
                    {"MESSAGE": KERNEL_NOISE, "SYSLOG_IDENTIFIER": "fixture-kernel", "PRIORITY": str(INFO_PRIORITY)},
                    {"MESSAGE": DOCKER_WARNING, "SYSLOG_IDENTIFIER": "fixture-docker", "PRIORITY": str(WARNING_PRIORITY)},
                    {"MESSAGE": DOCKER_INFO, "SYSLOG_IDENTIFIER": "fixture-docker", "PRIORITY": str(INFO_PRIORITY)}]
            inject(project, [*ingress, malformed, *host])
            records, logs = forwarded(project, len(lines) + 2)
            check(records, logs, lines)
            print("PASS journald -> Fluent Bit: allowlisted ingress fields, routes and request IDs; "
                  "malformed line dropped; only kernel OOM and Docker warnings; no history, query, driver fields or license",
                  flush=True)
        finally:
            project.run("down", "-v", "--timeout", "5")


if __name__ == "__main__":
    verify()
