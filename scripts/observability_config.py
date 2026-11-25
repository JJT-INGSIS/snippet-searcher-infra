"""Render the approved SNI-82 integrations; no license, credential values or deploys."""

import argparse
import json
import re
import shlex
from pathlib import Path
from urllib.parse import urlsplit


BLOCKED = "SELECT 'blocked_sessions' AS metric_name, 'gauge' AS metric_type, count(*) AS metric_value FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"


def absolute(value):
    return (
        isinstance(value, str)
        and value.startswith("/")
        and value != "/"
        and not any(c in value for c in ("\n", "\r", "\x00"))
        and ".." not in Path(value).parts
    )


def validate(config):
    if set(config) != {
        "environment",
        "version",
        "intervalSeconds",
        "postgres",
        "redis",
        "storage",
    }:
        raise ValueError("Unknown/missing configuration fields")
    if config["environment"] not in ("dev", "prod") or not re.fullmatch(
        r"[a-zA-Z0-9_.:@-]{1,128}", config["version"]
    ):
        raise ValueError("Invalid identity")
    if (
        type(config["intervalSeconds"]) is not int
        or not 30 <= config["intervalSeconds"] <= 300
    ):
        raise ValueError("Interval must be between 30 and 300 seconds")
    if (
        not isinstance(config["postgres"], list)
        or len(config["postgres"]) != 2
        or not isinstance(config["storage"], list)
        or not config["storage"]
    ):
        raise ValueError("Two databases and active storage are required")
    services = []
    for entry in [
        *config["postgres"],
        *([config["redis"]] if config["redis"] is not None else []),
    ]:
        fields = (
            {"service", "host", "port", "database", "username", "passwordFile"}
            if entry in config["postgres"]
            else {"service", "host", "port", "username", "passwordFile"}
        )
        if set(entry) != fields or not absolute(entry["passwordFile"]):
            raise ValueError("Only password file references are accepted")
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,100}", entry["host"])
            or type(entry["port"]) is not int
            or not 1 <= entry["port"] <= 65535
        ):
            raise ValueError("Invalid target")
        if entry["username"] != "nri_monitor":
            raise ValueError("Invalid monitoring user")
        if "database" in entry and not re.fullmatch(
            r"[a-z_][a-z0-9_]{0,62}", entry["database"]
        ):
            raise ValueError("Invalid database")
        services.append(entry["service"])
    native = [
        *config["postgres"],
        *([config["redis"]] if config["redis"] is not None else []),
    ]
    if len({t["passwordFile"] for t in native}) != len(native):
        raise ValueError("Each target requires its own monitoring credential")
    if len({(t["host"], t["port"], t["database"]) for t in config["postgres"]}) != 2:
        raise ValueError("Database targets must be distinct")
    for storage in config["storage"]:
        kind = storage.get("kind")
        if kind not in ("local", "asset", "filesystem"):
            raise ValueError("Invalid storage kind")
        fields = (
            {"kind", "service", "baseUrl"}
            if kind == "asset"
            else {"kind", "service", "path"}
        )
        if set(storage) != fields:
            raise ValueError("Unexpected storage settings")
        if kind == "asset":
            url = urlsplit(storage["baseUrl"])
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or url.path not in ("", "/")
                or url.query
                or url.fragment
            ):
                raise ValueError("Invalid Asset URL")
        elif not absolute(storage["path"]):
            raise ValueError("Invalid volume path")
        services.append(storage["service"])
    if len(set(services)) != len(services) or not all(
        re.fullmatch(r"[a-z][a-z0-9-]{0,63}", s) for s in services
    ):
        raise ValueError("Service identities must be unique")
    return config


def render(config, config_path, scripts_path):
    config = validate(config)
    variables = {}
    integrations = []
    for index, target in enumerate(
        [
            *config["postgres"],
            *([config["redis"]] if config["redis"] is not None else []),
        ]
    ):
        name = "secret" + str(index)
        variables[name] = {
            "command": {
                "path": "/bin/cat",
                "args": [target["passwordFile"]],
                "ttl": "1m",
            }
        }
        env = {
            "HOSTNAME": target["host"],
            "PORT": str(target["port"]),
            "USERNAME": target["username"],
            "PASSWORD": "${" + name + "}",
            "METRICS": "true",
            "INVENTORY": "false",
        }
        postgres = "database" in target
        if postgres:
            env.update(
                DATABASE=target["database"],
                COLLECTION_LIST=json.dumps({target["database"]: {}}),
                COLLECT_BLOAT_METRICS="false",
                COLLECT_DB_LOCK_METRICS="false",
                ENABLE_QUERY_MONITORING="false",
                CUSTOM_METRICS_QUERY=BLOCKED,
                TIMEOUT="5",
            )
        else:
            env.update(REMOTE_MONITORING="true", CONFIG_INVENTORY="false", KEYS="{}")
        integrations.append(
            {
                "name": "nri-postgresql" if postgres else "nri-redis",
                "env": env,
                "interval": str(config["intervalSeconds"]) + "s",
                "timeout": "20s",
                "labels": {
                    **{k: config[k] for k in ("environment", "version")},
                    "service": target["service"],
                },
            }
        )
    if not absolute(str(config_path)) or not absolute(str(scripts_path)):
        raise ValueError("Runtime paths must be absolute")
    apis = [
        {
            "event_type": "SnippetStorageSample",
            "commands": [
                {
                    "run": shlex.join(
                        [
                            "/usr/bin/python3",
                            str(Path(scripts_path) / "storage_health.py"),
                            "--config",
                            str(config_path),
                            "--service",
                            storage["service"],
                        ]
                    )
                }
            ],
        }
        for storage in config["storage"]
    ]
    for storage, api in zip(config["storage"], apis):
        integrations.append(
            {
                "name": "nri-flex",
                "interval": str(config["intervalSeconds"]) + "s",
                "timeout": "30s",
                "labels": {
                    **{k: config[k] for k in ("environment", "version")},
                    "service": storage["service"],
                },
                "config": {"name": "snippet-" + storage["service"], "apis": [api]},
            }
        )
    return {"variables": variables, "integrations": integrations}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--scripts-path", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                render(
                    json.loads(args.config.read_text()),
                    args.runtime_config,
                    args.scripts_path,
                ),
                indent=2,
            )
        )
    except (ValueError, OSError, KeyError, TypeError):
        raise SystemExit("Invalid observability configuration") from None
