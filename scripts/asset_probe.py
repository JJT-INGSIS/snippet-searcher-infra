"""SNI-33 internal HTTP probe. Writes only generated objects in a dedicated test container.

prepare emits a manifest on stdout; verify/cleanup read that manifest from stdin.
No storage credentials, SDK, public ports, redirects or automatic write retries.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

MAX_RESPONSE = 7 * 1024 * 1024
SAMPLES = ("", "let texto: string = \"¡Hola 🌎!\";\nprintln(texto);\n", '{"format":"snippet-content-v1","code":"original"}')


class ProbeFailure(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Response:
    status: int
    media_type: str
    body: bytes


def require(condition, message):
    if not condition:
        raise ProbeFailure(message)


def base_url(variable):
    value = os.environ.get(variable, "").rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ProbeFailure(f"{variable}: invalid base URL") from error
    require(parsed.scheme in ("http", "https") and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
            and (port is None or port > 0), f"{variable}: invalid base URL")
    return value


def request(base, path, method="GET", body=None, timeout=5, accept="application/octet-stream"):
    headers = {"Accept": accept}
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
    outgoing = Request(base + path, data=body, headers=headers, method=method)
    try:
        try:
            # Internal service discovery must not be sent through a host proxy.
            incoming = build_opener(ProxyHandler({}), NoRedirects()).open(outgoing, timeout=timeout)
        except HTTPError as error:
            incoming = error
        with incoming:
            raw = incoming.read(MAX_RESPONSE + 1)
            require(len(raw) <= MAX_RESPONSE, "Asset response exceeded probe limit")
            return Response(incoming.status, incoming.headers.get_content_type(), raw)
    except (URLError, OSError, TimeoutError) as error:
        # Do not print a transport exception that could contain response content.
        raise ProbeFailure(f"{method} {path}: transport failure; write/delete outcome may be uncertain") from error


def wait_ready(base, timeout=120):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "Asset management did not become healthy within the deadline")
        try:
            result = request(base, "/actuator/health", timeout=min(5, remaining), accept="application/json")
        except ProbeFailure:
            result = None
        if result is not None and result.status == 200:
            require(result.media_type in ("application/json", "application/vnd.spring-boot.actuator.v3+json"),
                    "Asset health must return JSON")
            try:
                health = json.loads(result.body)
            except (ValueError, UnicodeDecodeError) as error:
                raise ProbeFailure("Asset health returned invalid JSON") from error
            require(isinstance(health, dict) and health.get("status") == "UP", "Asset health is not UP")
            return
        if result is not None:
            require(result.status >= 500, f"Asset health returned unexpected HTTP {result.status}")
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def envelope(code):
    return json.dumps({"format": "snippet-content-v1", "code": code}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def path_for(manifest, entry):
    return f"/v1/asset/{manifest['container']}/{entry['key']}"


def validate_manifest(value):
    require(isinstance(value, dict) and set(value) == {"format", "container", "objects"}, "Invalid probe manifest")
    require(value["format"] == "infra-asset-probe-v1", "Unknown probe manifest version")
    require(isinstance(value["container"], str)
            and re.fullmatch(r"infra-sni33-[a-f0-9]{32}", value["container"]), "Not a dedicated probe container")
    require(isinstance(value["objects"], list) and len(value["objects"]) == len(SAMPLES), "Invalid probe objects")
    for entry, code in zip(value["objects"], SAMPLES):
        require(isinstance(entry, dict) and set(entry) == {"key", "sha256"}, "Invalid probe object")
        require(isinstance(entry["key"], str) and re.fullmatch(r"[a-f0-9]{32}", entry["key"]), "Invalid probe key")
        require(entry["sha256"] == hashlib.sha256(code.encode("utf-8")).hexdigest(), "Invalid expected fingerprint")
    require(len({entry["key"] for entry in value["objects"]}) == len(SAMPLES), "Duplicate probe key")
    return value


def prepare(base):
    manifest = validate_manifest({
        "format": "infra-asset-probe-v1", "container": "infra-sni33-" + uuid4().hex,
        "objects": [{"key": uuid4().hex, "sha256": hashlib.sha256(code.encode("utf-8")).hexdigest()}
                    for code in SAMPLES],
    })
    for entry, code in zip(manifest["objects"], SAMPLES):
        path = path_for(manifest, entry)
        require(request(base, path).status == 404, "Fresh probe key must not exist")
        result = request(base, path, "PUT", envelope(code))
        require(result.status == 201, f"Asset creation returned HTTP {result.status}")
    verify(base, manifest)
    # Only test identifiers and hashes, never real snippet code or credentials.
    return manifest


def verify(base, manifest):
    validate_manifest(manifest)
    for entry, code in zip(manifest["objects"], SAMPLES):
        result = request(base, path_for(manifest, entry))
        require(result.status == 200, f"Asset read returned HTTP {result.status}")
        require(result.media_type in ("application/octet-stream", "text/plain"), "Unexpected Asset media type")
        require(result.body == envelope(code), "Asset did not preserve exact UTF-8 envelope bytes")
        # Equal bytes already prove empty/Unicode/newlines survived; decode as a
        # second contract check without implementing another production codec.
        decoded = json.loads(result.body)
        require(hashlib.sha256(decoded["code"].encode("utf-8")).hexdigest() == entry["sha256"],
                "Decoded code fingerprint changed")


def cleanup(base, manifest):
    validate_manifest(manifest)
    for entry in manifest["objects"]:
        path = path_for(manifest, entry)
        require(request(base, path, "DELETE").status in (204, 404), "Asset deletion failed")
        require(request(base, path, "DELETE").status in (204, 404), "Asset deletion is not idempotent")
        require(request(base, path).status == 404, "Deleted probe object is still present")


def unavailable(base, manifest):
    validate_manifest(manifest)
    try:
        result = request(base, path_for(manifest, manifest["objects"][0]))
    except ProbeFailure:
        # With the backend deliberately stopped, a timeout is technical failure,
        # not evidence that the referenced object is missing.
        return
    require(result.status >= 500, f"Backend outage must be technical failure, not HTTP {result.status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "cleanup", "unavailable"))
    args = parser.parse_args()
    base = base_url("STORAGE_ASSET_BASE_URL")
    if args.mode != "unavailable":
        wait_ready(base_url("ASSET_MANAGEMENT_BASE_URL"))
    if args.mode == "prepare":
        print(json.dumps(prepare(base)))
    else:
        manifest = validate_manifest(json.load(sys.stdin))
        {"verify": verify, "cleanup": cleanup, "unavailable": unavailable}[args.mode](base, manifest)
    print(f"PASS Asset {args.mode}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ProbeFailure, ValueError, OSError) as error:
        print(f"FAIL Asset: {error}", file=sys.stderr)
        sys.exit(1)
