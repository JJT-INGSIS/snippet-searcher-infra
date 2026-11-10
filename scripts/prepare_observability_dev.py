"""Stage the reviewed DEV split on its manager; does not grant roles or start services."""

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

import install_observability_integrations as packages
import observability_runtime

ROOT = Path("/opt/snippet-observability/dev/runtime-v1")
REPO = Path(__file__).resolve().parent.parent


def prepare():
    if (
        os.geteuid() != 0
        or socket.gethostname() != "vm-snippet-dev"
        or platform.machine() != "x86_64"
    ):
        raise ValueError("Requires root on the reviewed DEV x86-64 manager")
    if ROOT.exists():
        raise ValueError("Runtime directory exists; inspect it instead of overwriting")
    swarm = json.loads(
        subprocess.check_output(
            ["docker", "info", "--format", "{{json .Swarm}}"], text=True
        )
    )
    if swarm.get("LocalNodeState") != "active" or not swarm.get("ControlAvailable"):
        raise ValueError("DEV must be an active Swarm manager")
    volume = json.loads(
        subprocess.check_output(
            ["docker", "volume", "inspect", "snippet-searcher-dev_snippets_content"],
            text=True,
        )
    )[0]
    stat = Path(volume["Mountpoint"]).stat()
    if (stat.st_uid, stat.st_gid) != (10001, 10001):
        raise ValueError(
            "Content volume identity changed; review collector user without chmod/chown of application data"
        )
    ROOT.mkdir(parents=True, mode=0o755)
    for name in (
        "collect.py",
        "dispatch.sh",
        "agent.compose.yaml",
        "collector.stack.yaml",
        "docker-config.yml",
        "swarm.sh",
        "images.lock.json",
    ):
        shutil.copy2(REPO / "observability/runtime" / name, ROOT / name)
        (ROOT / name).chmod(0o644)
    (ROOT / "probes").mkdir()
    for name in ("asset_probe.py", "storage_health.py", "observability_config.py"):
        shutil.copy2(REPO / "scripts" / name, ROOT / "probes" / name)
        (ROOT / "probes" / name).chmod(0o644)
    config = json.loads((REPO / "observability/config.example.json").read_text())
    config["version"] = "sni82-runtime-v1"
    (ROOT / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (ROOT / "integrations.json").write_text(
        json.dumps(observability_runtime.integrations(config), indent=2) + "\n"
    )
    packages.install(ROOT / "packages", "amd64")
    shutil.copytree(
        ROOT / "packages/var/db/newrelic-infra/newrelic-integrations/bin", ROOT / "bin"
    )
    locks = json.loads((ROOT / "images.lock.json").read_text())
    for image in locks.values():
        subprocess.run(["docker", "pull", image], check=True, stdout=subprocess.DEVNULL)
    cid = subprocess.check_output(
        ["docker", "create", locks["dockerCli"]], text=True
    ).strip()
    try:
        subprocess.run(
            ["docker", "cp", cid + ":/usr/local/bin/docker", str(ROOT / "docker")],
            check=True,
        )
    finally:
        subprocess.run(["docker", "rm", cid], check=True, stdout=subprocess.DEVNULL)
    (ROOT / "docker").chmod(0o755)
    print("DEV runtime staged. No roles, secrets, service updates or agent started.")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        prepare()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit(
            "DEV staging failed; inspect the staged directory before retrying"
        ) from None
