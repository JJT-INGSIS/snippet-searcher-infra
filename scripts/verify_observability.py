"""Opt-in SNI-82 local Docker acceptance. No ports, cloud account or live deployments."""

import argparse
import hashlib
import importlib.util
import json
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import install_observability_integrations as packages
import observability_config

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "qa_configure", REPO / "observability/qa/configure.py"
)
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
PYTHON_IMAGE = "python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b"


def wait(check, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError("Acceptance condition not observed before deadline")


def run(evidence_path, architecture):
    root = Path(tempfile.mkdtemp(prefix="sni82-qa-"))
    project = "sni82-qa-" + uuid4().hex[:8]
    image = project + ":local"
    binary_root = root / "packages"
    packages.install(binary_root, architecture)
    image_context = root / "image"
    image_context.mkdir()
    shutil.copytree(
        binary_root / "var/db/newrelic-infra/newrelic-integrations/bin",
        image_context / "bin",
    )
    flex_lock = json.loads((REPO / "observability/qa/flex.lock.json").read_text())
    asset = flex_lock["assets"][architecture]
    archive = packages.download(asset["url"])
    assert hashlib.sha256(archive).hexdigest() == asset["sha256"]
    import io

    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        member = next(
            m
            for m in source.getmembers()
            if m.isfile() and Path(m.name).name == "nri-flex"
        )
        path = image_context / "bin/nri-flex"
        path.write_bytes(source.extractfile(member).read())
        path.chmod(0o755)
    for file in ("asset_probe.py", "storage_health.py", "observability_config.py"):
        shutil.copy2(REPO / "scripts" / file, image_context / file)
    shutil.copy2(REPO / "observability/qa/native.py", image_context / "native.py")
    (image_context / "Dockerfile").write_text(
        f'FROM {PYTHON_IMAGE}\nWORKDIR /opt/probes\nCOPY bin/ /usr/local/bin/\nCOPY *.py ./\nRUN ln -s /usr/local/bin/python3 /usr/bin/python3\nCMD ["sleep", "infinity"]\n'
    )
    subprocess.run(
        [
            "docker",
            "build",
            "--platform",
            "linux/" + architecture,
            "-t",
            image,
            str(image_context),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    qa.configure(root, REPO, image)
    fixture = json.loads((root / "compose.json").read_text())
    fixture["services"]["probe"]["platform"] = "linux/" + architecture
    (root / "compose.json").write_text(json.dumps(fixture))
    config = json.loads((root / "config.json").read_text())
    rendered = observability_config.render(
        config, Path("/opt/config.json"), Path("/opt/probes")
    )
    flex_configs = [
        i["config"] for i in rendered["integrations"] if i["name"] == "nri-flex"
    ]
    command = ["docker", "compose", "-f", str(root / "compose.json"), "-p", project]

    def compose(*args, data=None, check=True):
        return subprocess.run(
            [*command, *args], input=data, capture_output=True, text=True, check=check
        )

    def native(service):
        value = compose(
            "exec",
            "-T",
            "probe",
            "python3",
            "/opt/probes/native.py",
            service,
            check=False,
        )
        if value.returncode != 0:
            return None
        parsed = json.loads(value.stdout)
        expected = "RedisSample" if service == "redis" else "PostgresqlDatabaseSample"
        return (
            parsed
            if any(
                m.get("event_type") == expected
                for d in parsed.get("data", [])
                for m in d["metrics"]
            )
            else None
        )

    def metrics(value):
        return [m for dataset in value["data"] for m in dataset["metrics"]]

    def storage(service):
        value = compose(
            "exec",
            "-T",
            "probe",
            "python3",
            "/opt/probes/storage_health.py",
            "--config",
            "/opt/config.json",
            "--service",
            service,
        )
        return json.loads(value.stdout)

    def redis(field):
        return next(m[field] for m in metrics(native("redis")) if field in m)

    evidence = {
        "result": "RUNNING",
        "at": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "architecture": architecture,
        "packages": json.loads(packages.LOCK.read_text()),
        "flex": flex_lock,
        "cases": {},
    }
    try:
        compose("up", "-d")
        for host, database in [("db1", "snippets"), ("db2", "permissions")]:
            wait(
                lambda: compose(
                    "exec",
                    "-T",
                    host,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    database,
                    "-d",
                    database,
                    check=False,
                ).returncode
                == 0
            )
            compose(
                "exec",
                "-T",
                host,
                "sh",
                "-c",
                'export OBS_MONITOR_PASSWORD="$(cat /run/secrets/monitor_password)"; psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v database="$POSTGRES_DB" -f /opt/postgresql-monitor.sql',
            )
            compose(
                "exec",
                "-T",
                host,
                "psql",
                "-U",
                database,
                "-d",
                database,
                "-c",
                "CREATE TABLE private_fixture (value text);",
            )
            denied = compose(
                "exec",
                "-T",
                host,
                "sh",
                "-c",
                'export PGPASSWORD="$(cat /run/secrets/monitor_password)"; psql -h 127.0.0.1 -U nri_monitor -d "$POSTGRES_DB" -c "SELECT * FROM private_fixture"',
                check=False,
            )
            assert denied.returncode != 0 and "permission denied" in denied.stderr
        healthy = {
            service: wait(lambda service=service: native(service))
            for service in ("snippets-db", "permissions-db", "redis")
        }
        assert all(
            any(
                m.get("event_type") == "PostgresqlDatabaseSample"
                for m in metrics(healthy[s])
            )
            for s in ("snippets-db", "permissions-db")
        )
        assert redis("db.aofLastWriteStatus") == "ok"
        evidence["cases"]["nativeHealthy"] = {
            s: sorted({m["event_type"] for m in metrics(v)}) for s, v in healthy.items()
        }
        evidence["cases"]["noApplicationTableAccess"] = True
        for query in (
            "SET sni82-forbidden value",
            "GET sni82-forbidden",
            "CONFIG GET maxmemory",
        ):
            denied = compose(
                "exec",
                "-T",
                "redis",
                "sh",
                "-c",
                'export REDISCLI_AUTH="$(cat /run/secrets/obs_redis_password)"; redis-cli --user nri_monitor '
                + query,
            )
            assert "NOPERM" in denied.stdout
        evidence["cases"]["redisNoKeyWriteOrConfigAccess"] = True
        # Two real sessions create a lock wait; the custom metric contains no query text.
        first = subprocess.Popen(
            [
                *command,
                "exec",
                "-T",
                "db1",
                "psql",
                "-U",
                "snippets",
                "-d",
                "snippets",
                "-c",
                "BEGIN; LOCK private_fixture IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(20); COMMIT;",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait(
            lambda: compose(
                "exec",
                "-T",
                "db1",
                "psql",
                "-U",
                "snippets",
                "-d",
                "snippets",
                "-At",
                "-c",
                "SELECT count(*) FROM pg_locks WHERE relation='private_fixture'::regclass AND mode='AccessExclusiveLock' AND granted",
            ).stdout.strip()
            == "1"
        )
        second = subprocess.Popen(
            [
                *command,
                "exec",
                "-T",
                "db1",
                "psql",
                "-U",
                "snippets",
                "-d",
                "snippets",
                "-c",
                "SELECT count(*) FROM private_fixture",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            blocked = wait(
                lambda: next(
                    (
                        m["blocked_sessions"]
                        for m in metrics(native("snippets-db"))
                        if m.get("blocked_sessions", 0) > 0
                    ),
                    None,
                ),
                10,
            )
        finally:
            first.wait(timeout=30)
            second.wait(timeout=20)
        assert (
            next(
                m["blocked_sessions"]
                for m in metrics(native("snippets-db"))
                if "blocked_sessions" in m
            )
            == 0
        )
        evidence["cases"]["realBlockedSessionAndRecovery"] = {
            "blocked": blocked,
            "recovered": 0,
        }
        before = storage("storage-local")
        assert before["up"] == 1 and before["contentOk"] == 1
        wait(lambda: storage("asset-service")["up"] == 1)
        rows = []
        for index, flex_config in enumerate(flex_configs):
            path = root / ("flex" + str(index) + ".json")
            path.write_text(json.dumps(flex_config))
            compose("cp", str(path), "probe:/opt/flex.json")
            flex = json.loads(
                compose(
                    "exec", "-T", "probe", "nri-flex", "-config_file", "/opt/flex.json"
                ).stdout
            )
            rows += [
                m for m in metrics(flex) if m["event_type"] == "SnippetStorageSample"
            ]
        assert len(rows) == 2 and all(
            m.get("up") == 1 and not m.get("error") for m in rows
        )
        evidence["cases"]["flexAcceptsActualSamples"] = [m["service"] for m in rows]
        # Read-only is an isolated mount; no application/database filesystem is filled.
        read_only = json.loads(json.dumps(fixture))
        read_only["services"]["probe"]["volumes"][0] = "content:/data:ro"
        (root / "readonly.json").write_text(json.dumps(read_only))
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(root / "readonly.json"),
                "-p",
                project,
                "up",
                "-d",
                "--no-deps",
                "probe",
            ],
            check=True,
            capture_output=True,
        )
        failed = storage("storage-local")
        assert failed["up"] == 0 and "availableBytes" in failed
        compose("up", "-d", "--no-deps", "probe")
        assert storage("storage-local")["up"] == 1
        evidence["cases"]["localReadOnlyFailureAndRecovery"] = {
            "before": before,
            "failed": failed,
            "recovered": True,
        }
        # The real Asset stays running while its real Azurite backend is unavailable.
        compose("stop", "azurite")
        unavailable = storage("asset-service")
        assert unavailable["up"] == 0
        compose("start", "azurite")
        wait(lambda: storage("asset-service")["up"] == 1)
        evidence["cases"]["assetBackendFailureAndRecovery"] = unavailable
        for target, service in [("db1", "snippets-db"), ("redis", "redis")]:
            compose("stop", target)
            assert native(service) is None
            compose("start", target)
            wait(lambda: native(service))
            evidence["cases"][target + "UnavailableAndRecovered"] = True
        # A fixed 8 MiB tmpfs belongs ONLY to this Redis QA instance.
        compose(
            "exec",
            "-T",
            "redis",
            "sh",
            "-c",
            "dd if=/dev/zero of=/data/sni82-ballast bs=1024 count=8192 2>/dev/null",
            check=False,
        )
        compose(
            "exec",
            "-T",
            "redis",
            "sh",
            "-c",
            'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; redis-cli -x SET sni82-fault',
            data="x" * 1048576,
            check=False,
        )
        wait(lambda: redis("db.aofLastWriteStatus") == "err", 20)
        compose("exec", "-T", "redis", "rm", "/data/sni82-ballast")
        wait(lambda: redis("db.aofLastWriteStatus") == "ok", 30)
        evidence["cases"]["aofFullFilesystemErrorAndRecovery"] = True
        # A malformed optional monitoring credential disables only the observer.
        monitor_secret = root / "secrets/obs_redis_password"
        original_secret = monitor_secret.read_text()
        monitor_secret.write_text("invalid")
        try:
            compose("restart", "redis")

            def application_alive():
                return (
                    compose(
                        "exec",
                        "-T",
                        "redis",
                        "sh",
                        "-c",
                        'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; redis-cli PING',
                        check=False,
                    ).stdout.strip()
                    == "PONG"
                )

            wait(application_alive)
            assert native("redis") is None
        finally:
            monitor_secret.write_text(original_secret)
            compose("restart", "redis")
        wait(lambda: native("redis"))
        evidence["cases"]["badMonitoringCredentialKeepsApplicationAvailable"] = True
        evidence["result"] = "PASS"
        evidence["limits"] = [
            "Standalone collectors/Flex; no New Relic ingestion or live VM",
            "Pool/JDBC latency belongs to application instrumentation",
            "Isolated Redis tmpfs is a fault fixture, not a durability certification",
        ]
    except BaseException:
        evidence["result"] = "FAIL"
        raise
    finally:
        evidence["stoppedOwnProject"] = compose("stop", check=False).returncode == 0
        evidence["privateWorkspace"] = str(root)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "result": evidence["result"],
                "project": project,
                "evidence": str(evidence_path),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--architecture",
        choices=["amd64", "arm64"],
        default="arm64" if platform.machine() == "arm64" else "amd64",
    )
    args = parser.parse_args()
    run(args.evidence, args.architecture)
