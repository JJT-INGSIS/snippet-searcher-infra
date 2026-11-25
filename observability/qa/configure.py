"""Private fixtures only; all ports remain inside this QA project's network."""

import json
import secrets


def configure(root, repo, image):
    secret_dir = root / "secrets"
    secret_dir.mkdir(mode=0o700)
    names = (
        "db_admin",
        "db1_monitor",
        "db2_monitor",
        "redis_password",
        "obs_redis_password",
    )
    for name in names:
        path = secret_dir / name
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    config = json.loads((repo / "observability/config.example.json").read_text())
    for entry, host, secret in zip(
        config["postgres"], ("db1", "db2"), ("db1_monitor", "db2_monitor")
    ):
        entry.update(host=host, passwordFile="/run/secrets/" + secret)
    config["redis"]["host"] = "redis"
    config["storage"] = [
        {"kind": "local", "service": "storage-local", "path": "/data"},
        {"kind": "asset", "service": "asset-service", "baseUrl": "http://asset:8080"},
    ]
    (root / "config.json").write_text(json.dumps(config))
    services = {}
    for host, database, secret in [
        ("db1", "snippets", "db1_monitor"),
        ("db2", "permissions", "db2_monitor"),
    ]:
        services[host] = {
            "image": json.loads((repo / "swarm/dev-release.json").read_text())[
                "database_image"
            ],
            "environment": {
                "POSTGRES_DB": database,
                "POSTGRES_USER": database,
                "POSTGRES_PASSWORD_FILE": "/run/secrets/db_admin",
            },
            "secrets": ["db_admin", {"source": secret, "target": "monitor_password"}],
            "volumes": [
                host + "_data:/var/lib/postgresql",
                str(repo / "observability/sql/postgresql-monitor.sql")
                + ":/opt/postgresql-monitor.sql:ro",
            ],
        }
    services["redis"] = {
        "image": "redis:7.4.7-alpine@sha256:02f2cc4882f8bf87c79a220ac958f58c700bdec0dfb9b9ea61b62fb0e8f1bfcf",
        "entrypoint": ["sh", "/opt/entrypoint.sh"],
        "secrets": ["redis_password", "obs_redis_password"],
        "volumes": [
            str(repo / "redis/entrypoint.sh") + ":/opt/entrypoint.sh:ro",
            str(repo / "redis/redis.conf") + ":/etc/redis/redis.conf:ro",
        ],
        "tmpfs": ["/data:size=8m", "/run/redis:size=1m"],
    }
    services["asset"] = {
        "image": "ghcr.io/austral-ingsis/snippet-asset-service@sha256:eacad54bf95717c5483619ad1fe45a9b4a0012a37b451c37baf13e6f43200656",
        "environment": {
            "AZURE_HOST": "http://azurite",
            "NEW_RELIC_AGENT_ENABLED": "false",
        },
    }
    services["azurite"] = {
        "image": "mcr.microsoft.com/azure-storage/azurite:3.35.0@sha256:647c63a91102a9d8e8000aab803436e1fc85fbb285e7ce830a82ee5d6661cf37",
        "command": [
            "azurite-blob",
            "--blobHost",
            "0.0.0.0",
            "--location",
            "/data",
            "--skipApiVersionCheck",
        ],
        "volumes": ["asset_data:/data"],
    }
    services["probe"] = {
        "image": image,
        "secrets": list(names),
        "volumes": [
            "content:/data",
            str(root / "config.json") + ":/opt/config.json:ro",
        ],
    }
    value = {
        "services": services,
        "volumes": {
            name: {} for name in ("db1_data", "db2_data", "asset_data", "content")
        },
        "secrets": {name: {"file": str(secret_dir / name)} for name in names},
    }
    (root / "compose.json").write_text(json.dumps(value, indent=2))
