import argparse
import os
import subprocess
import sys

from apm_runtime import license_secret
from start_log_forwarder_dev import ENVIRONMENTS, agent_configuration, agent_license

DOCKER_SECONDS = 30
DESCRIPTION = "Create the Swarm secret with the APM license, read from the agent configuration"


def secret_exists(name, run=subprocess.run):
    result = run(["docker", "secret", "inspect", name], capture_output=True, text=True, timeout=DOCKER_SECONDS)
    return result.returncode == 0


def create(environment, run=subprocess.run):
    source = agent_configuration(environment)
    if not source.is_file():
        raise ValueError("The agent license is missing; no new license is created here")
    name = license_secret(environment)
    if secret_exists(name, run):
        raise ValueError("The APM license secret already exists; it is never replaced in place")
    license_key = agent_license(source.read_text())
    run(["docker", "secret", "create", name, "-"], input=license_key, text=True, check=True,
        capture_output=True, timeout=DOCKER_SECONDS)
    return name


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="dev")
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: the agent license is readable only by root")
    try:
        print("PASS created secret " + create(arguments.environment))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("FAIL APM secret: " + type(error).__name__ + ": " + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
