"""Real NGINX, controlled HTTP upstreams, local isolated Docker project. No Azure.

Transport acceptance only: fixtures are never a deployed UI or business backend.
"""
import http.client
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from verify_asset_persistence import local_engine

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_HOST = "snippet.test:8088"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    body: bytes


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def request(port, path, method="GET", body=None, headers=None, timeout=8):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers={"Host": PUBLIC_HOST, **(headers or {})})
        incoming = connection.getresponse()
        raw = incoming.read(10 * 1024 * 1024 + 1)
        require(len(raw) <= 10 * 1024 * 1024, "Test response exceeded limit")
        return Response(incoming.status, dict(incoming.getheaders()), raw)
    finally:
        connection.close()


def eventually(port, path, status):
    deadline = time.monotonic() + 25
    while True:
        try:
            result = request(port, path)
            if result.status == status:
                return result
        except (OSError, http.client.HTTPException):
            pass
        require(time.monotonic() < deadline, f"{path}: expected HTTP {status} after DNS recovery")
        time.sleep(1)


def check_transport(port):
    for method in ("GET", "POST", "PUT", "DELETE", "OPTIONS"):
        path = "/api/snippets?name=a%2Fb&tag=x&tag=y&empty=&space=a+b"
        body = None if method == "GET" else '  {"code":"¡Hola 🌎!\\n","description":null}  '.encode("utf-8")
        sent = {"Content-Type": "application/json", "Authorization": "Bearer fixture-not-a-real-token",
                "Idempotency-Key": "550e8400-e29b-41d4-a716-446655440000",
                "Forwarded": "for=203.0.113.123;proto=https;host=attacker.test",
                "X-Forwarded-For": "203.0.113.123", "X-Forwarded-Host": "attacker.test",
                "X-Forwarded-Proto": "https", "X-Forwarded-Port": "443", "X-Forwarded-Prefix": "/fake",
                "X-Forwarded-Ssl": "on", "X-Request-ID": "attacker-value", "Host": "SNIPPET.TEST:9999"}
        sent["Origin"] = "http://fixture-ui.test"
        result = request(port, path, method, body, sent)
        require(result.status == 200, f"{method}: transport failed")
        echoed = json.loads(result.body)
        require(echoed["path"] == path.removeprefix("/api"), "Prefix/query changed incorrectly")
        require(echoed["method"] == method and echoed["body"] == (body or b"").decode("utf-8"), "Method/body changed")
        received = {key.lower(): value for key, value in echoed["headers"].items()}
        require(received.get("authorization") == sent["Authorization"]
                and received.get("idempotency-key") == sent["Idempotency-Key"], "Identity/idempotence header lost")
        require(received.get("content-type") == "application/json", "Request Content-Type changed")
        require(received.get("origin") == sent["Origin"] and "Access-Control-Allow-Origin" not in result.headers,
                "Proxy must preserve Origin without implementing Spring CORS")
        require("forwarded" not in received and "x-forwarded-ssl" not in received, "Untrusted forwarding header leaked")
        require(received.get("x-forwarded-host") == PUBLIC_HOST and received.get("host") == PUBLIC_HOST
                and received.get("x-forwarded-proto") == "http" and received.get("x-forwarded-port") == "8088"
                and received.get("x-forwarded-prefix") == "/api", "Canonical forwarding headers incorrect")
        require(received.get("x-forwarded-for") != "203.0.113.123" and "," not in received.get("x-forwarded-for", ""),
                "Client-controlled forwarding chain trusted")
        require(re.fullmatch(r"[a-f0-9]{32}", received.get("x-request-id", "")), "Request ID was not replaced")
    nested = request(port, "/api/api/snippets")
    require(json.loads(nested.body)["path"] == "/api/snippets", "Prefix must be removed exactly once")
    for route in ("/languages", "/users"):
        require(json.loads(request(port, "/api" + route).body)["path"] == route, "Public route mapping failed")
    print("PASS method/query/UTF-8 body, Authorization/idempotence, canonical Host and forwarding headers", flush=True)


def check_routes_and_failures(port):
    redirect = request(port, "/api?q=a%2Fb&empty=", "POST", b"payload")
    require(redirect.status == 308 and redirect.headers.get("Location") == "/api/?q=a%2Fb&empty=", "Noncanonical API redirect changed")
    followed = request(port, redirect.headers["Location"], "POST", b"payload")
    echoed = json.loads(followed.body)
    require(echoed["method"] == "POST" and echoed["body"] == "payload", "308 follow lost method/body")
    for path in ("/", "/editor/123", "/api-other"):
        require(request(port, path).headers.get("Content-Type") == "text/html", "UI routing failed")
    for path, expected in (("/api/problem", 422), ("/api/missing", 404)):
        result = request(port, path)
        require(result.status == expected and result.headers.get("Content-Type") == "application/problem+json", "API error became SPA HTML")
        require(json.loads(result.body)["status"] == expected, "Problem Details changed")
    require(request(port, "/api/snippets", headers={"Host": "attacker.test"}).status == 404, "Unknown Host reached a backend")
    require(request(port, "/.well-known/acme-challenge/probe-token").body.strip() == b"test-challenge-not-a-certificate", "ACME webroot incorrect")
    require(request(port, "/.well-known/acme-challenge/missing").status == 404, "Missing challenge fell through to UI")
    require(request(port, "/.well-known/acme-challenge/probe-token", "POST", b"x").status == 403, "ACME webroot accepts writes")
    # Send only an oversized Content-Length: reject before sending/storing 8 MiB.
    require(request(port, "/api/snippets", "POST", headers={"Content-Length": str(8 * 1024 * 1024 + 1)}).status == 413,
            "Oversized body was not rejected")
    large = b"x" * (1024 * 1024)
    require(json.loads(request(port, "/api/snippets", "POST", large).body)["body"].encode() == large, "A 1 MiB body was truncated")
    require(request(port, "/api/fail-write", "POST", b"x").status == 503, "Upstream 503 changed")
    require(request(port, "/api/disconnect-write", "POST", b"x").status == 502, "Disconnected write not reported as gateway failure")
    stats = json.loads(request(port, "/api/__test/stats").body)
    require(stats.get("/fail-write") == 1 and stats.get("/disconnect-write") == 1, "Proxy replayed a write")
    print("PASS 308, UI/API separation, Problem Details, ACME, 8 MiB limit and no write replay", flush=True)


def verify():
    local_engine()
    project = "sni38-check-" + uuid4().hex[:12]
    environment = {**os.environ, "SNIPPETS_DB_PASSWORD": "unused-validation", "PERMISSIONS_DB_PASSWORD": "unused-validation",
                   "GITHUB_ACTOR": "unused-validation", "GITHUB_TOKEN": "unused-validation", "PROXY_HTTP_PORT": "0"}
    command = ["docker", "compose", "--env-file", os.devnull, "--profile", "ingress", "-p", project,
               "-f", str(ROOT / "tests/nginx/compose.yaml")]

    def compose(*args, **kwargs):
        return subprocess.run([*command, *args], env=environment, check=True, timeout=180, **kwargs)

    def capture(*args):
        return compose(*args, stdout=subprocess.PIPE, text=True).stdout.strip()

    def identity(service):
        cid = capture("ps", "-q", service)
        require(bool(cid), f"Missing fixture {service}")
        return json.loads(subprocess.check_output(["docker", "inspect", cid], text=True, timeout=15))[0]

    print(f"SNI-38 isolated project: {project}", flush=True)
    try:
        # Start with NO upstreams: runtime DNS must not prevent proxy startup.
        compose("up", "-d", "--wait", "--wait-timeout", "30", "nginx")
        compose("exec", "-T", "nginx", "nginx", "-t")
        port = int(capture("port", "nginx", "8080").rsplit(":", 1)[1])
        proxy_id = identity("nginx")["Id"]
        require(request(port, "/healthz").status == 200, "NGINX health failed")
        require(request(port, "/api/snippets").status == 502, "Missing API must produce gateway failure")
        compose("up", "-d", "ui")
        eventually(port, "/", 200)
        require(request(port, "/api/snippets").status == 502, "Missing API was hidden by the UI")
        compose("up", "-d", "snippets-service")
        eventually(port, "/api/snippets", 200)
        check_transport(port)
        check_routes_and_failures(port)
        print("CHECK bounded read timeout: waiting for the configured 60 seconds", flush=True)
        started = time.monotonic()
        require(request(port, "/api/slow", timeout=70).status == 504, "Slow API did not time out")
        require(55 <= time.monotonic() - started < 70, "Read timeout does not match 60s configuration")
        print("PASS real 60s read timeout", flush=True)
        # A timed-out upstream may be excluded briefly by NGINX passive failure
        # accounting. Wait for its bounded recovery before testing a UI outage.
        eventually(port, "/api/snippets", 200)
        compose("stop", "--timeout", "2", "ui")
        require(request(port, "/").status in (502, 504), "UI outage did not produce a gateway error")
        require(request(port, "/api/snippets").status == 200, "UI outage broke the API")
        require(request(port, "/healthz").status == 200, "Upstream outage changed proxy health")
        compose("up", "-d", "ui")
        eventually(port, "/", 200)
        previous = identity("snippets-service")
        old_ip = next(iter(previous["NetworkSettings"]["Networks"].values()))["IPAddress"]
        compose("stop", "--timeout", "2", "snippets-service")
        compose("rm", "-f", "snippets-service")
        compose("up", "-d", "address-holder")
        compose("up", "-d", "snippets-service")
        current = identity("snippets-service")
        new_ip = next(iter(current["NetworkSettings"]["Networks"].values()))["IPAddress"]
        require(previous["Id"] != current["Id"] and old_ip != new_ip, "Fixture did not actually change its container/IP")
        eventually(port, "/api/snippets", 200)
        require(identity("nginx")["Id"] == proxy_id, "Proxy was recreated to recover DNS")
        logs = capture("logs", "--no-color", "nginx")
        for sensitive in ("fixture-not-a-real-token", "550e8400-e29b-41d4-a716-446655440000", "attacker-value", "name=a%2Fb"):
            require(sensitive not in logs, "Proxy logs included sensitive request data")
        print("PASS independent outages and upstream container/IP replacement without proxy restart; sanitized logs", flush=True)
    finally:
        # This generated project has no database or persistent production content.
        # No volumes, old configs, stack or resources outside this project removed.
        compose("down", "--timeout", "5")


if __name__ == "__main__":
    try:
        verify()
    except (RuntimeError, OSError, ValueError, http.client.HTTPException, subprocess.SubprocessError) as error:
        print(f"FAIL NGINX transport acceptance: {error}", file=sys.stderr)
        sys.exit(1)
