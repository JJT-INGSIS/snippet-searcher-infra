"""Read-only SNI-38/40 candidate validation; does not alter the SNI-43 release format."""
import json
import os
import re
import subprocess

from stack_release import CERTIFICATES, nginx_files, validate_manifest
from validate_asset_config import ROOT, render, require, validate_candidate as validate_asset_candidate

NGINX_IMAGE = "nginx:1.30.6-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951"


def validate_candidate(base, candidate, tls=False):
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
    published = {(str(port["published"]), port["target"]) for port in nginx.get("ports", [])}
    expected_ports = {("80", 8080), ("443", 8443)} if tls else {("80", 8080)}
    require(len(nginx.get("ports", [])) == len(expected_ports) and published == expected_ports,
            "Ingress publishes only NGINX 80, and 443 once TLS is enabled")
    keys = nginx_files(tls)
    require(len(nginx.get("configs", [])) == len(keys), "NGINX requires the versioned configs of its TLS state")
    mounts = {mount.get("target"): mount for mount in nginx.get("volumes", [])}
    require(mounts.get("/var/www/acme", {}).get("read_only") is True, "Proxy ACME webroot must be read-only")
    certificates = {target for target in mounts if target.startswith("/etc/letsencrypt")}
    require(certificates == ({"/etc/letsencrypt/live", "/etc/letsencrypt/archive"} if tls else set()),
            "Proxy mounts only live/archive certificates, never the ACME account")
    for target in certificates:
        location = CERTIFICATES.format(environment="(dev|prod)") + target.removeprefix("/etc/letsencrypt")
        require(mounts[target].get("read_only") is True and re.fullmatch(location, mounts[target].get("source", "")),
                "Certificates must be read-only files of the environment host directory")
    for name in keys:
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
        for tls in (False, True):
            overlays = ["swarm/stack.ingress.yaml"] + (["swarm/stack.tls.yaml"] if tls else [])
            candidate = render(["swarm/stack.yaml", *overlays], selected)
            for service in base['services']:
                candidate['services'][service].pop('ports', None)
            validate_candidate(base, candidate, tls)
            for assets in (False, True):
                files = ["swarm/stack.yaml", *overlays] + (["swarm/stack.asset.yaml"] if assets else [])
                if assets:
                    expanded = render(files, selected)
                    for service in base['services']:
                        expanded['services'][service].pop('ports', None)
                    validate_asset_candidate(candidate, expanded, "local")
                command = ["docker", "stack", "config"]
                for file in files:
                    command += ["-c", str(ROOT / file)]
                subprocess.run(command, env=selected, check=True, stdout=subprocess.DEVNULL, timeout=30)
                print(f"PASS ingress candidate {target}; tls={tls}; assets={assets}; original settings/data preserved")


if __name__ == "__main__":
    main()
