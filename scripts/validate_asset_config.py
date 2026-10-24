"""Render and check SNI-33 Compose/Swarm candidates without secrets or VM access.

Does not extend the operational release contract: that belongs to SNI-43.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from stack_release import validate_manifest

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = {"asset-service", "azurite"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_runtime(services):
    for name, package in (("asset-service", "ghcr.io/austral-ingsis/snippet-asset-service"),
                          ("azurite", "mcr.microsoft.com/azure-storage/azurite:3.35.0")):
        service = services[name]
        require(re.fullmatch(re.escape(package) + r"@sha256:[a-f0-9]{64}", service["image"]),
                f"{name}: reviewed immutable image required")
        require(not service.get("ports"), f"{name}: public ports are forbidden")
        require(not service.get("secrets"), f"{name}: no Packages/database secrets")
        require(bool(service.get("healthcheck", {}).get("test")), f"{name}: healthcheck required")
    blobs = services["azurite"]
    require(blobs["command"] == ["azurite-blob", "--blobHost", "0.0.0.0", "--location", "/data", "--skipApiVersionCheck"],
            "Azurite must explicitly persist blob data under /data")
    require(any(mount.get("source") == "asset_blobs" and mount.get("target") == "/data"
                and mount.get("type") == "volume" for mount in blobs.get("volumes", [])),
            "Azurite requires the dedicated persistent volume")
    require(services["asset-service"]["environment"] == {"AZURE_HOST": "http://azurite", "NEW_RELIC_AGENT_ENABLED": "false"},
            "Asset must use the internal emulator, without unrelated credentials")


def validate_candidate(base, expanded, provider):
    require(set(expanded["services"]) == set(base["services"]) | RUNTIME, "Unexpected Swarm services")
    for name, service in base["services"].items():
        if name == "snippets-service":
            original = {key: value for key, value in service.items() if key != "environment"}
            changed = {key: value for key, value in expanded["services"][name].items() if key != "environment"}
            require(original == changed, "Asset must not alter Snippets image, mounts, deployment or ports")
            settings = expanded["services"][name]["environment"]
            require(all(settings.get(key) == value for key, value in service["environment"].items()),
                    "Asset must preserve original Snippets settings")
            require(settings["STORAGE_PROVIDER"] == provider, "Provider selection changed")
            require(settings["STORAGE_ASSET_BASE_URL"] == "http://asset-service:8080", "Wrong internal Asset URL")
        else:
            require(service == expanded["services"][name], f"Unrelated service changed: {name}")
    require(expanded.get("secrets") == base.get("secrets"), "Database secrets changed")
    for name, volume in base["volumes"].items():
        require(expanded["volumes"].get(name) == volume, f"Existing volume changed: {name}")
    validate_runtime(expanded["services"])
    constraints = expanded["services"]["azurite"]["deploy"]["placement"]["constraints"]
    require(constraints == ["node.labels.asset_storage == true"], "Blob placement must be controlled")


def render(files, environment, profiles=()):
    command = ["docker", "compose", "--env-file", os.devnull, "--project-name", "sni33-validation"]
    for profile in profiles:
        command += ["--profile", profile]
    for file in files:
        command += ["-f", str(ROOT / file)]
    return json.loads(subprocess.check_output([*command, "config", "--format", "json"],
                                            env=environment, text=True, timeout=30))


def main():
    environment = {**os.environ, "SNIPPETS_DB_PASSWORD": "unused-validation",
                   "PERMISSIONS_DB_PASSWORD": "unused-validation", "GITHUB_ACTOR": "unused-validation",
                   "GITHUB_TOKEN": "unused-validation", "STORAGE_PROVIDER": "local"}
    compose = render(["compose.yaml"], environment, ("assets", "verification"))
    validate_runtime(compose["services"])
    require(compose["services"]["snippets-service"]["environment"]["STORAGE_PROVIDER"] == "local",
            "Compose must not silently activate Asset")
    require(not RUNTIME & set(render(["compose.yaml"], environment)["services"]), "Runtime must be opt-in")
    for target in ("dev", "prod"):
        record = json.loads((ROOT / f"swarm/{target}-release.json").read_text())
        settings = {**environment, **validate_manifest(record)}
        base = render(["swarm/stack.yaml"], settings)
        for provider in ("local", "asset"):
            selected = {**settings, "STORAGE_PROVIDER": provider}
            files = ["swarm/stack.yaml", "swarm/stack.asset.yaml"]
            expanded = render(files, selected)
            validate_candidate(base, expanded, provider)
            for name in RUNTIME:
                require(expanded["services"][name]["image"] == compose["services"][name]["image"],
                        "Compose and Swarm runtime images must match")
            subprocess.run(["docker", "stack", "config", "-c", str(ROOT / files[0]), "-c", str(ROOT / files[1])],
                           env=selected, check=True, stdout=subprocess.DEVNULL, timeout=30)
            print(f"PASS Asset candidate {target}; provider={provider}; existing services/secrets/volumes preserved")


if __name__ == "__main__":
    main()
