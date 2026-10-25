"""Read-only SNI-38 candidate validation; does not alter the SNI-43 release format."""
import json
import os
import re
import subprocess

from stack_release import validate_manifest
from validate_asset_config import ROOT, render, require, validate_candidate as validate_asset_candidate

NGINX_IMAGE = "nginx:1.30.6-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951"


def validate_candidate(base, candidate):
    require(set(candidate["services"]) == set(base["services"]) | {"nginx"}, "Unexpected ingress services")
    for name, service in base["services"].items():
        expected = {key: value for key, value in service.items() if key != "ports"}
        require(candidate["services"][name] == expected, f"Ingress changed unrelated configuration of {name}")
    for section in ("secrets", "volumes", "networks"):
        for name, value in base.get(section, {}).items():
            require(candidate.get(section, {}).get(name) == value, f"Ingress changed {section}/{name}")
    nginx = candidate["services"]["nginx"]
    require(nginx["image"] == NGINX_IMAGE, "NGINX must use the reviewed immutable image")
    require(not nginx.get("secrets"), "Proxy must not receive database or Packages secrets")
    require(len(nginx.get("ports", [])) == 1 and str(nginx["ports"][0]["published"]) == "80"
            and nginx["ports"][0]["target"] == 8080, "HTTP candidate publishes only NGINX port 80")
    require(len(nginx.get("configs", [])) == 3, "NGINX requires three versioned configs")
    require(any(m.get("target") == "/var/www/acme" and m.get("read_only") is True
                for m in nginx.get("volumes", [])), "Proxy ACME webroot must be read-only")
    for name in ("nginx_main", "nginx_routes", "nginx_env_check"):
        config = candidate["configs"][name]
        suffix = name.removeprefix("nginx_")
        require(re.fullmatch(rf"snippet-searcher-(dev|prod)_nginx_{suffix}_v[1-9][0-9]*", config["name"])
                and bool(config.get("file")), "Swarm configs must be versioned snapshots")


def main():
    environment = {**os.environ, "SNIPPETS_DB_PASSWORD": "unused-validation",
                   "PERMISSIONS_DB_PASSWORD": "unused-validation", "GITHUB_ACTOR": "unused-validation",
                   "GITHUB_TOKEN": "unused-validation", "PROXY_HOSTNAME": "snippet.test", "PROXY_HTTP_PORT": "8088",
                   "PROXY_PUBLIC_PORT": "8088", "STORAGE_PROVIDER": "local"}
    local = render(["compose.yaml"], environment, ("ingress",))
    require(local["services"]["nginx"]["image"] == NGINX_IMAGE, "Compose/Swarm NGINX image mismatch")
    require(local["services"]["nginx"]["ports"][0]["host_ip"] == "127.0.0.1", "Local ingress must bind localhost")
    for target in ("dev", "prod"):
        record = json.loads((ROOT / f"swarm/{target}-release.json").read_text())
        selected = {**environment, **validate_manifest(record)}
        base = render(["swarm/stack.yaml"], selected)
        candidate = render(["swarm/stack.yaml", "swarm/stack.ingress.yaml"], selected)
        for service in base['services']:
            candidate['services'][service].pop('ports', None)
        validate_candidate(base, candidate)
        for assets in (False, True):
            files = ["swarm/stack.yaml", "swarm/stack.ingress.yaml"] + (["swarm/stack.asset.yaml"] if assets else [])
            if assets:
                expanded = render(files, selected)
                for service in base['services']:
                    expanded['services'][service].pop('ports', None)
                validate_asset_candidate(candidate, expanded, "local")
            command = ["docker", "stack", "config"]
            for file in files:
                command += ["-c", str(ROOT / file)]
            subprocess.run(command, env=selected, check=True, stdout=subprocess.DEVNULL, timeout=30)
            print(f"PASS HTTP ingress candidate {target}; assets={assets}; original settings/data preserved")


if __name__ == "__main__":
    main()
