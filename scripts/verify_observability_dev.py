"""Read native metrics and probe only the dedicated fixture on the reviewed DEV VM."""

import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/opt/snippet-observability/dev/runtime-v1")


def execute(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=45)


def native_metrics(value):
    return value.get("metrics", []) + [
        m for entry in value.get("data", []) for m in entry.get("metrics", [])
    ]


def verify():
    if socket.gethostname() != "vm-snippet-dev":
        raise ValueError("Only the reviewed DEV VM is allowed")
    ids = execute(
        "ps",
        "--filter",
        "label=com.docker.swarm.service.name=snippet-observability-dev_collector",
        "--filter",
        "status=running",
        "--format",
        "{{.ID}}",
    ).splitlines()
    if len(ids) != 1:
        raise ValueError("Expected one private collector")
    config = json.loads((ROOT / "config.json").read_text())
    targets = [*config["postgres"], *([config["redis"]] if config["redis"] else [])]
    evidence = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": "dev",
        "version": config["version"],
        "native": {},
        "storage": [],
    }
    for target in targets:
        result = json.loads(
            execute(
                "exec", ids[0], "python3", "/opt/runtime/collect.py", target["service"]
            )
        )
        metrics = native_metrics(result)
        if not metrics:
            raise ValueError("Native integration emitted no metrics")
        evidence["native"][target["service"]] = {
            "metricCount": len(metrics),
            "eventTypes": sorted({m["event_type"] for m in metrics}),
        }
    for target in config["storage"]:
        result = json.loads(
            execute(
                "exec", ids[0], "python3", "/opt/runtime/collect.py", target["service"]
            )
        )
        rows = result if isinstance(result, list) else [result]
        if not rows or any(row["up"] != 1 for row in rows):
            raise ValueError("Storage probe did not succeed")
        evidence["storage"].extend(rows)
    # Test the actual Docker CLI and shell dispatch inside the pinned agent image,
    # without passing an ingest key or starting a second agent.
    image = json.loads((ROOT / "images.lock.json").read_text())["agent"]
    native = json.loads(
        execute(
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            "--mount",
            "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock",
            "--mount",
            "type=bind,src=" + str(ROOT) + ",dst=/opt/runtime,readonly",
            image,
            "/opt/runtime/dispatch.sh",
            "snippets-db",
        )
    )
    if not native_metrics(native):
        raise ValueError("Host-agent dispatch did not collect")
    evidence["agentDispatchVerified"] = True
    flex_results = []
    for entry in json.loads((ROOT / "integrations.json").read_text())["integrations"]:
        if entry["name"] != "nri-flex":
            continue
        fixture = ROOT / "qa-flex.json"
        fixture.write_text(json.dumps(entry["config"]))
        fixture.chmod(0o644)
        try:
            result = json.loads(
                execute(
                    "run",
                    "--rm",
                    "--entrypoint",
                    "/var/db/newrelic-infra/newrelic-integrations/bin/nri-flex",
                    "--mount",
                    "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock",
                    "--mount",
                    "type=bind,src=" + str(ROOT) + ",dst=/opt/runtime,readonly",
                    image,
                    "-config_file",
                    "/opt/runtime/qa-flex.json",
                )
            )
            rows = native_metrics(result)
            event = entry["config"]["apis"][0]["event_type"]
            if not any(row.get("event_type") == event for row in rows):
                raise ValueError("Flex did not emit the expected event")
            flex_results.append(
                {
                    "name": entry["config"]["name"],
                    "eventType": event,
                    "metricCount": len(rows),
                }
            )
        finally:
            fixture.unlink(missing_ok=True)
    evidence["pinnedAgentFlexVerified"] = flex_results
    evidence["newRelicIngestionVerified"] = False
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    try:
        verify()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise SystemExit(
            "DEV probe acceptance failed; do not declare ingestion or health"
        ) from None
