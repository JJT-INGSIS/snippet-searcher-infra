"""Local isolated Compose acceptance for SNI-33. Never deploys Swarm or migrates data.

Starts only Asset/Azurite and a temporary probe. Recreates both containers and
compares actual content. Removes only its own containers/network, preserving the
generated volume (printed on completion) even on failure. No credentials needed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent


def local_engine():
    # Docker gives an explicitly selected context priority over DOCKER_HOST.
    if os.environ.get("DOCKER_CONTEXT"):
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", os.environ["DOCKER_CONTEXT"], "--format", "{{.Endpoints.docker.Host}}"],
            text=True, timeout=15).strip()
    elif os.environ.get("DOCKER_HOST"):
        endpoint = os.environ["DOCKER_HOST"]
    else:
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True, timeout=15).strip()
    if not endpoint.startswith("unix://"):
        raise RuntimeError("This acceptance runner requires a local Unix Docker engine, never a remote VM")


def verify():
    local_engine()
    project = "sni33-check-" + uuid4().hex[:12]
    # --env-file disables the project's real .env. These values only satisfy
    # interpolation; none is passed to Asset, Azurite or the probe.
    environment = {**os.environ, "SNIPPETS_DB_PASSWORD": "unused-isolated-validation",
                   "PERMISSIONS_DB_PASSWORD": "unused-isolated-validation",
                   "GITHUB_ACTOR": "unused-isolated-validation", "GITHUB_TOKEN": "unused-isolated-validation"}
    command = ["docker", "compose", "--env-file", os.devnull, "--profile", "assets",
               "--profile", "verification", "-p", project,
               "-f", str(ROOT / "compose.yaml")]

    def compose(*args, **kwargs):
        return subprocess.run([*command, *args], env=environment, check=True, timeout=240, **kwargs)

    def probe(mode, manifest=None):
        result = compose("run", "--rm", "--no-deps", "-T", "asset-tests", "python", "-B",
                         "/verification/asset_probe.py", mode, input=manifest, text=True,
                         stdout=subprocess.PIPE)
        return result.stdout

    print(f"SNI-33 isolated project: {project}", flush=True)
    print(f"Volume retained: {project}_asset_blobs", flush=True)
    try:
        compose("up", "-d", "--wait", "--wait-timeout", "180", "asset-service", "azurite")
        before = compose("ps", "-q", "asset-service", "azurite", text=True, stdout=subprocess.PIPE).stdout.split()
        if len(before) != 2:
            raise RuntimeError("Expected exactly two running runtime containers")
        manifest = probe("prepare")
        # Read it now too: do not recreate if a failed probe emitted bad evidence.
        json.loads(manifest)
        compose("up", "-d", "--force-recreate", "--no-deps", "--wait", "--wait-timeout", "180",
                "asset-service", "azurite")
        after = compose("ps", "-q", "asset-service", "azurite", text=True, stdout=subprocess.PIPE).stdout.split()
        if len(after) != 2 or set(before) & set(after):
            raise RuntimeError("Both runtime containers must actually be replaced")
        probe("verify", manifest)
        compose("stop", "--timeout", "10", "azurite")
        probe("unavailable", manifest)
        compose("up", "-d", "--wait", "--wait-timeout", "180", "azurite")
        probe("verify", manifest)
        probe("cleanup", manifest)
        print("PASS Asset/Azurite: new containers, identical content, outage/recovery, idempotent deletion; internal network only", flush=True)
    finally:
        # No -v, no prune, no existing project. Preserve blobs for investigation.
        compose("down", "--timeout", "20")


if __name__ == "__main__":
    try:
        verify()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"FAIL isolated Asset persistence: {error}", file=sys.stderr)
        sys.exit(1)
