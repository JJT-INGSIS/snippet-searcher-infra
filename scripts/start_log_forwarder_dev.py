import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "observability/logs"
ENVIRONMENTS = ("dev", "prod")
PRIVATE = "/etc/snippet-observability/{environment}"
RUNTIME = "/opt/snippet-observability/{environment}/logs-v1"
RUNTIME_FILES = ("fluent-bit.conf", "parsers-ingress.conf", "forwarder.compose.yaml")
AGENT_CONFIGURATION_NAME = "agent.json"
LICENSE_INCLUDE_NAME = "logs-license.conf"
LICENSE_INCLUDE_TARGET = "/fluent-bit/etc/license.conf"
LICENSE_VARIABLE = "NR_LICENSE_KEY"
LICENSE_PATTERN = re.compile(r"[a-zA-Z0-9_-]{20,100}")
OWNER_ONLY = 0o600
SHARED_READ = 0o644
SHARED_DIRECTORY = 0o755
COMPOSE_SECONDS = 180
JOURNAL_SECONDS = 30
JOURNAL_MATCHES = ("CONTAINER_TAG=snippet-ingress", "_TRANSPORT=kernel", "_SYSTEMD_UNIT=docker.service")
DESCRIPTION = "Start or remove the log forwarder outside Swarm, reusing the agent license"


def agent_configuration(environment):
    return Path(PRIVATE.format(environment=environment)) / AGENT_CONFIGURATION_NAME


def license_file(environment):
    return Path(PRIVATE.format(environment=environment)) / LICENSE_INCLUDE_NAME


def runtime_directory(environment):
    return Path(RUNTIME.format(environment=environment))


def license_include(raw):
    try:
        key = json.loads(raw).get("license_key")
    except (ValueError, AttributeError):
        raise ValueError("Agent configuration is not valid JSON") from None
    if not isinstance(key, str) or not LICENSE_PATTERN.fullmatch(key):
        raise ValueError("Agent configuration has no valid ingest license")
    return "@SET " + LICENSE_VARIABLE + "=" + key + "\n"


def write_private(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_ONLY)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)


def install_runtime(environment):
    target = runtime_directory(environment)
    if target.exists():
        if not all(filecmp.cmp(SOURCE / name, target / name, shallow=False) for name in RUNTIME_FILES):
            raise ValueError("The installed forwarder revision differs; install a new logs revision instead")
        return target
    target.mkdir(parents=True, mode=SHARED_DIRECTORY)
    for name in RUNTIME_FILES:
        shutil.copy2(SOURCE / name, target / name)
        (target / name).chmod(SHARED_READ)
    return target


def compose(environment, *arguments, capture=False):
    command = ["docker", "compose", "-f", str(runtime_directory(environment) / "forwarder.compose.yaml"), *arguments]
    result = subprocess.run(command, env={**os.environ, "SNIPPET_ENVIRONMENT": environment}, check=True,
                            timeout=COMPOSE_SECONDS, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def journal_has(match):
    result = subprocess.run(["journalctl", "--quiet", "--no-pager", "--lines", "1", "--output", "cat", match],
                            check=True, timeout=JOURNAL_SECONDS, capture_output=True, text=True)
    return bool(result.stdout.strip())


def missing_journal_sources():
    return [match for match in JOURNAL_MATCHES if not journal_has(match)]


def start(environment):
    source = agent_configuration(environment)
    if not source.is_file():
        raise ValueError("The agent license is missing; no new license is created here")
    if license_file(environment).exists():
        raise ValueError("A forwarder license include already exists; remove the forwarder first")
    missing = missing_journal_sources()
    if missing:
        raise ValueError("The journal has no entries yet for " + ", ".join(missing)
                         + "; deploy NGINX with the journald driver first")
    install_runtime(environment)
    write_private(license_file(environment), license_include(source.read_text()))
    compose(environment, "up", "-d")
    if not compose(environment, "ps", "--status", "running", "-q", capture=True):
        raise RuntimeError("The forwarder is not running; inspect its own logs")
    print("PASS log forwarder running for " + environment)


def remove(environment):
    if runtime_directory(environment).exists():
        compose(environment, "down")
    license_file(environment).unlink(missing_ok=True)
    print("PASS log forwarder removed for " + environment + "; state volume and runtime files kept")


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("action", choices=("start", "remove"))
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="dev")
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: the agent license is readable only by root")
    try:
        if arguments.action == "start":
            start(arguments.environment)
        else:
            remove(arguments.environment)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL log forwarder: " + type(error).__name__ + ": " + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
