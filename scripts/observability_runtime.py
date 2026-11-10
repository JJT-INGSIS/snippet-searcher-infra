"""Render the approved DEV host-agent/private-collector split; no deployment/secrets."""

import argparse
import json
from pathlib import Path

import observability_config


def integrations(config):
    observability_config.validate(config)
    if config["environment"] != "dev":
        raise ValueError("This reviewed deployment is DEV only")
    targets = [*config["postgres"], *([config["redis"]] if config["redis"] else [])]
    native = [
        {
            "name": "nri-postgresql" if "database" in target else "nri-redis",
            "exec": ["/bin/sh", "/opt/runtime/dispatch.sh", target["service"]],
            "interval": str(config["intervalSeconds"]) + "s",
            "timeout": "25s",
            "labels": {
                "environment": "dev",
                "version": config["version"],
                "service": target["service"],
            },
        }
        for target in targets
    ]
    storage = [
        {
            "name": "nri-flex",
            "interval": str(config["intervalSeconds"]) + "s",
            "timeout": "35s",
            "labels": {
                "environment": "dev",
                "version": config["version"],
                "service": target["service"],
            },
            "config": {
                "name": "snippet-" + target["service"],
                "apis": [
                    {
                        "event_type": "SnippetStorageSample",
                        "commands": [
                            {
                                "run": "/bin/sh /opt/runtime/dispatch.sh "
                                + target["service"]
                            }
                        ],
                    }
                ],
            },
        }
        for target in config["storage"]
    ]
    swarm = {
        "name": "nri-flex",
        "interval": str(config["intervalSeconds"]) + "s",
        "timeout": "10s",
        "config": {
            "name": "snippet-swarm",
            "apis": [
                {
                    "event_type": "SnippetSwarmSample",
                    "commands": [{"run": "/bin/sh /opt/runtime/swarm.sh"}],
                }
            ],
        },
        "labels": {
            "environment": "dev",
            "version": config["version"],
            "service": "swarm",
        },
    }
    return {"integrations": [*native, *storage, swarm]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(integrations(json.loads(args.config.read_text())), indent=2))
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit("Invalid DEV observability configuration") from None
