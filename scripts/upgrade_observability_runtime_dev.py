import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import observability_runtime

REPO = Path(__file__).resolve().parent.parent
BASE = "/opt/snippet-observability/dev/"
SOURCE = Path(BASE + "runtime-v1")
TARGET = Path(BASE + "runtime-v2")
PRIVATE = Path("/etc/snippet-observability/dev")
PROJECT = "runtime-v1"
HOST = "vm-snippet-dev"
PREVIOUS_VERSION = "sni82-runtime-v1"
VERSION = "sni80-runtime-v2"
SHARED_READ = 0o644
COMPOSE_SECONDS = 180
ADDED = {"swarm_sample.py": REPO / "observability/runtime/swarm_sample.py",
         "stack_release.py": REPO / "scripts/stack_release.py"}
DESCRIPTION = "Install runtime-v2 with the new Swarm sample and recreate the DEV agent; revert returns to v1"


def agent_compose(text):
    if str(SOURCE) not in text or "version: " + PREVIOUS_VERSION not in text:
        raise ValueError("The installed agent Compose is not the reviewed runtime-v1")
    return text.replace(str(SOURCE), str(TARGET)).replace("version: " + PREVIOUS_VERSION, "version: " + VERSION)


def upgraded_config(config):
    return {**config, "version": VERSION}


def write_shared(path, content):
    path.write_text(content)
    path.chmod(SHARED_READ)


def compose(runtime):
    subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(runtime / "agent.compose.yaml"), "up", "-d"],
                   check=True, timeout=COMPOSE_SECONDS, capture_output=True)


def require_host():
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        raise ValueError("Requires root on the DEV manager")
    if not (PRIVATE / "agent.json").is_file() or not SOURCE.is_dir():
        raise ValueError("Requires the running SNI-82 runtime-v1 agent")


def upgrade():
    require_host()
    if TARGET.exists():
        raise ValueError("runtime-v2 exists; inspect it instead of overwriting")
    shutil.copytree(SOURCE, TARGET, symlinks=True)
    for name, source in ADDED.items():
        shutil.copy2(source, TARGET / name)
        (TARGET / name).chmod(SHARED_READ)
    config = upgraded_config(json.loads((SOURCE / "config.json").read_text()))
    write_shared(TARGET / "config.json", json.dumps(config, indent=2) + "\n")
    write_shared(TARGET / "integrations.json", json.dumps(observability_runtime.integrations(config), indent=2) + "\n")
    write_shared(TARGET / "agent.compose.yaml", agent_compose((SOURCE / "agent.compose.yaml").read_text()))
    compose(TARGET)
    print("PASS DEV agent recreated on runtime-v2; verify SnippetSwarmSample fields in New Relic")


def revert():
    require_host()
    compose(SOURCE)
    print("PASS DEV agent back on runtime-v1; runtime-v2 kept for inspection")


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("action", choices=("upgrade", "revert"))
    arguments = parser.parse_args()
    try:
        if arguments.action == "upgrade":
            upgrade()
        else:
            revert()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("FAIL runtime upgrade: " + type(error).__name__ + ": " + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
