"""Execute one approved probe inside the private, unprivileged Swarm collector."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/probes")
import observability_config  # noqa: E402


def collect(service, config_path=Path("/opt/runtime/config.json")):
    config = json.loads(config_path.read_text())
    observability_config.validate(config)
    targets = [*config["postgres"], *([config["redis"]] if config["redis"] else [])]
    target = next((entry for entry in targets if entry["service"] == service), None)
    if target is None:
        if service not in {entry["service"] for entry in config["storage"]}:
            raise ValueError("Unknown probe")
        return subprocess.run(
            [
                sys.executable,
                "/opt/probes/storage_health.py",
                "--config",
                str(config_path),
                "--service",
                service,
            ],
            capture_output=True,
            timeout=28,
            check=True,
        ).stdout
    definition = next(
        entry
        for entry in observability_config.render(
            config, config_path, Path("/opt/probes")
        )["integrations"]
        if entry["labels"]["service"] == service
    )
    password = Path(target["passwordFile"]).read_text()
    if len(password) != 64 or any(c not in "0123456789abcdef" for c in password):
        raise ValueError("Invalid monitoring credential")
    result = subprocess.run(
        ["/opt/bin/" + definition["name"]],
        env={**os.environ, **definition["env"], "PASSWORD": password},
        capture_output=True,
        timeout=20,
        check=True,
    )
    # Native integrations can exit zero with metrics=[] on outage. Preserve that
    # output verbatim; never fabricate a healthy sample or replay an old result.
    json.loads(result.stdout)
    return result.stdout


if __name__ == "__main__":
    try:
        sys.stdout.buffer.write(collect(sys.argv[1]))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ):
        raise SystemExit("Private collector unavailable; no sample emitted") from None
