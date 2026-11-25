"""Start the reviewed DEV agent; ingest license arrives only through stdin."""

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path("/opt/snippet-observability/dev/runtime-v1")
PRIVATE = Path("/etc/snippet-observability/dev")


def start():
    if (
        os.geteuid() != 0
        or socket.gethostname() != "vm-snippet-dev"
        or not (PRIVATE / "provisioned").is_file()
    ):
        raise ValueError("Requires provisioned DEV manager")
    if (PRIVATE / "agent.json").exists():
        raise ValueError(
            "Agent configuration already exists; never overwrite an existing license"
        )
    if (
        subprocess.run(
            ["pgrep", "-x", "newrelic-infra"], capture_output=True
        ).returncode
        == 0
    ):
        raise ValueError("An infrastructure agent already runs on this host")
    license_key = sys.stdin.read(200).strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{20,100}", license_key):
        raise ValueError("Invalid ingest license")
    config = {
        "license_key": license_key,
        "display_name": "vm-snippet-dev",
        "docker_api_version": "1.44",
        "enable_process_metrics": False,
        "metrics_process_sample_rate": -1,
        "metrics_system_sample_rate": 60,
        "metrics_storage_sample_rate": 60,
        "metrics_network_sample_rate": 60,
        "disable_inventory": True,
        "custom_attributes": {
            "environment": "dev",
            "service": "infrastructure-agent",
            "version": "sni82-runtime-v1",
        },
    }
    fd = os.open(PRIVATE / "agent.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(config, output)
    subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "agent.compose.yaml"), "up", "-d"],
        check=True,
        capture_output=True,
    )
    print(
        "DEV host agent started; verify actual New Relic reception before declaring completion."
    )


if __name__ == "__main__":
    try:
        start()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit(
            "Agent start failed; inspect protected DEV configuration without printing it"
        ) from None
