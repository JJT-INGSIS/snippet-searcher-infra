"""Explicit one-time DEV monitoring provisioning, after staging and operator review."""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path("/opt/snippet-observability/dev/runtime-v1")
PRIVATE = Path("/etc/snippet-observability/dev")
SOURCE = Path(__file__).resolve().parent.parent
STACK = "snippet-searcher-dev_"


def docker(*args, data=None):
    return subprocess.run(
        ["docker", *args], input=data, capture_output=True, text=True, check=True
    ).stdout.strip()


def container(service):
    ids = docker(
        "ps",
        "--filter",
        "label=com.docker.swarm.service.name=" + STACK + service,
        "--filter",
        "status=running",
        "--format",
        "{{.ID}}",
    ).splitlines()
    if len(ids) != 1:
        raise ValueError("Expected exactly one application task")
    return ids[0]


def healthy(service):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            cid = container(service)
            if (
                docker("inspect", cid, "--format", "{{.State.Health.Status}}")
                == "healthy"
            ):
                return cid
        except (ValueError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    raise ValueError("Application task did not recover; inspect before proceeding")


def alias_options(service, network, alias):
    spec = json.loads(docker("service", "inspect", STACK + service))[0]
    network_id = json.loads(docker("network", "inspect", network))[0]["Id"]
    entry = next(
        n for n in spec["Spec"]["TaskTemplate"]["Networks"] if n["Target"] == network_id
    )
    if alias in entry.get("Aliases", []):
        return []
    aliases = [*entry.get("Aliases", []), alias]
    return [
        "--network-rm",
        network,
        "--network-add",
        "name=" + network + "," + ",".join("alias=" + a for a in aliases),
    ]


def provision():
    if (
        os.geteuid() != 0
        or socket.gethostname() != "vm-snippet-dev"
        or not (ROOT / "integrations.json").is_file()
    ):
        raise ValueError("Requires staged runtime on the reviewed DEV manager")
    if PRIVATE.exists():
        raise ValueError(
            "Monitoring private directory exists; do not overwrite credentials"
        )
    # Finish all collision/health checks before creating anything.
    for service in ("snippets-db", "permissions-db", "redis"):
        healthy(service)
    for service, db in (("snippets-db", "snippets"), ("permissions-db", "permissions")):
        exists = docker(
            "exec",
            container(service),
            "psql",
            "-U",
            db,
            "-d",
            db,
            "-Atc",
            "SELECT 1 FROM pg_roles WHERE rolname='nri_monitor'",
        )
        if exists:
            raise ValueError(
                "Monitoring role already exists; review its ownership and grants"
            )
    names = (
        "obs_snippets_db_password",
        "obs_permissions_db_password",
        "obs_redis_password",
    )
    existing = set(docker("secret", "ls", "--format", "{{.Name}}").splitlines())
    if existing.intersection(names):
        raise ValueError("Monitoring secrets already exist; will not replace them")
    PRIVATE.mkdir(parents=True, mode=0o700)
    for name in names:
        value = secrets.token_hex(32)
        path = PRIVATE / name
        path.write_text(value)
        path.chmod(0o600)
        docker("secret", "create", name, "-", data=value)
    for service, db, secret in (
        ("snippets-db", "snippets", names[0]),
        ("permissions-db", "permissions", names[1]),
    ):
        sql = (SOURCE / "observability/sql/postgresql-monitor.sql").read_text()
        # Read the password through stdin, not docker exec arguments, labels or service environment.
        docker(
            "exec",
            "-i",
            container(service),
            "sh",
            "-c",
            'IFS= read -r OBS_MONITOR_PASSWORD; export OBS_MONITOR_PASSWORD; exec psql -U "$1" -d "$1" -v database="$1"',
            "monitor-setup",
            db,
            data=(PRIVATE / secret).read_text() + "\n" + sql,
        )
        options = alias_options(
            service, "snippet-searcher-dev_default", "dev-" + service
        )
        if options:
            docker(
                "service",
                "update",
                "--update-order",
                "stop-first",
                *options,
                STACK + service,
            )
            healthy(service)
    entrypoint = (SOURCE / "redis/entrypoint.sh").read_text()
    cfg = (
        "snippet-observability-dev-redis-entrypoint-"
        + hashlib.sha256(entrypoint.encode()).hexdigest()[:12]
    )
    docker("config", "create", cfg, "-", data=entrypoint)
    redis = json.loads(docker("service", "inspect", STACK + "redis"))[0]
    old = next(
        c["ConfigName"]
        for c in redis["Spec"]["TaskTemplate"]["ContainerSpec"]["Configs"]
        if c["File"]["Name"] == "/etc/redis/entrypoint.sh"
    )
    (PRIVATE / "redis-previous-config").write_text(old)
    docker(
        "service",
        "update",
        "--update-order",
        "stop-first",
        *alias_options("redis", "snippet-searcher-dev_redis_internal", "dev-redis"),
        "--config-rm",
        old,
        "--config-add",
        "source=" + cfg + ",target=/etc/redis/entrypoint.sh,mode=0444",
        "--secret-add",
        "source=obs_redis_password,target=obs_redis_password,mode=0400",
        STACK + "redis",
    )
    healthy("redis")
    docker(
        "stack",
        "deploy",
        "--resolve-image",
        "never",
        "-c",
        str(ROOT / "collector.stack.yaml"),
        "snippet-observability-dev",
    )
    (PRIVATE / "provisioned").write_text("sni82-runtime-v1\n")
    print(
        "Dedicated DEV monitor provisioned. Application images/data and CD unchanged. Agent not started."
    )


if __name__ == "__main__":
    try:
        provision()
    except (
        OSError,
        ValueError,
        KeyError,
        StopIteration,
        subprocess.SubprocessError,
    ) as error:
        # Never print psql/Redis stderr or CompletedProcess: credentials may occur there.
        print(
            type(error).__name__
            + ": provisioning stopped; inspect current state and protected files before retrying"
        )
        raise SystemExit(1) from None
