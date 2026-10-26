"""Real NGINX HTTPS ingress with a throwaway CA and controlled upstreams. No Azure, no ACME."""
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from verify_asset_persistence import local_engine
from verify_nginx import ROOT, Response, require
from verify_execution_stream import check_execution_stream

HOST = "snippet.test"


class PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def openssl(*arguments):
    subprocess.run(["openssl", *arguments], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def authority(directory):
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=sni40-test-ca",
            "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", str(directory / "ca.key"), "-out", str(directory / "ca.pem"))
    return directory / "ca.pem"


def issue(directory, generation):
    archive = directory / "archive" / HOST
    live = directory / "live" / HOST
    archive.mkdir(parents=True, exist_ok=True)
    live.mkdir(parents=True, exist_ok=True)
    extensions = directory / "leaf.ext"
    extensions.write_text(f"subjectAltName=DNS:{HOST}\nbasicConstraints=critical,CA:FALSE\n"
                          "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
                          "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n")
    key = archive / f"privkey{generation}.pem"
    request = directory / "leaf.csr"
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={HOST}", "-keyout", str(key), "-out", str(request))
    openssl("x509", "-req", "-in", str(request), "-CA", str(directory / "ca.pem"), "-CAkey", str(directory / "ca.key"),
            "-set_serial", str(1000 + generation), "-days", "2", "-extfile", str(extensions),
            "-out", str(archive / f"fullchain{generation}.pem"))
    for name in ("fullchain", "privkey"):
        pending = live / f".{name}.pem"
        pending.unlink(missing_ok=True)
        pending.symlink_to(f"../../archive/{HOST}/{name}{generation}.pem")
        os.replace(pending, live / f"{name}.pem")
    return 1000 + generation


def plain(port, path, method="GET", body=None, host=HOST):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        connection.request(method, path, body=body, headers={"Host": host})
        incoming = connection.getresponse()
        return Response(incoming.status, dict(incoming.getheaders()), incoming.read())
    finally:
        connection.close()


def context(ca, version=None):
    created = ssl.create_default_context(cafile=str(ca))
    if version:
        created.minimum_version = created.maximum_version = version
    return created


def secure(port, ca, path, method="GET", body=None, version=None, headers=None):
    connection = PinnedHTTPS(HOST, port, context=context(ca, version), timeout=8)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        incoming = connection.getresponse()
        served = connection.sock.getpeercert()
        return Response(incoming.status, dict(incoming.getheaders()), incoming.read()), int(served["serialNumber"], 16)
    finally:
        connection.close()


def eventually(check, message):
    deadline = time.monotonic() + 25
    while True:
        try:
            if check():
                return
        except (OSError, http.client.HTTPException, ssl.SSLError):
            pass
        require(time.monotonic() < deadline, message)
        time.sleep(1)


def check_http(port):
    require(plain(port, "/healthz", host="127.0.0.1").status == 200, "Proxy health failed")
    require(plain(port, "/.well-known/acme-challenge/probe-token").body.strip() == b"test-challenge-not-a-certificate",
            "ACME webroot incorrect")
    require(plain(port, "/.well-known/acme-challenge/missing").status == 404, "Missing challenge was redirected")
    require(plain(port, "/.well-known/acme-challenge/probe-token", "POST", b"x").status == 403, "ACME webroot accepts writes")
    for method, path in (("GET", "/api/snippets?q=a%2Fb&empty=&tag=x&tag=y"), ("POST", "/api/http-write"),
                         ("GET", "/editor/1"), ("GET", "/healthz")):
        result = plain(port, path, method, b"payload" if method == "POST" else None)
        require(result.status == 308 and result.headers.get("Location") == f"https://{HOST}{path}",
                f"HTTP {method} {path} was not redirected to HTTPS keeping URI and query")
    require(plain(port, "/api/snippets", host="attacker.test").status == 404, "Unknown Host was redirected")
    print("PASS HTTP serves only health, ACME webroot and 308 to the fixed HTTPS host", flush=True)


def check_https(port, ca, serial):
    result, served = secure(port, ca, "/api/snippets?q=a%2Fb")
    require(served == serial, "Unexpected certificate served")
    echoed = json.loads(result.body)
    received = {key.lower(): value for key, value in echoed["headers"].items()}
    require(echoed["path"] == "/snippets?q=a%2Fb", "HTTPS API routing changed")
    require(received.get("x-forwarded-proto") == "https" and received.get("x-forwarded-port") == "443"
            and received.get("host") == f"{HOST}:443", "HTTPS forwarding headers incorrect")
    require(secure(port, ca, "/")[0].headers.get("Content-Type") == "text/html", "HTTPS UI routing failed")
    require(secure(port, ca, "/healthz")[0].status == 200, "HTTPS proxy health failed")
    stats = json.loads(secure(port, ca, "/api/__test/stats")[0].body)
    require("/http-write" not in stats, "A plain HTTP write reached the API")
    for version in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
        require(secure(port, ca, "/healthz", version=version)[0].status == 200, f"{version.name} rejected")
    unknown = ssl.create_default_context()
    unknown.check_hostname = False
    unknown.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection(("127.0.0.1", port), 8)
    try:
        unknown.wrap_socket(raw, server_hostname="attacker.test")
        require(False, "Unknown SNI completed a TLS handshake")
    except ssl.SSLError:
        pass
    finally:
        raw.close()
    print("PASS verified chain and hostname, TLS 1.2/1.3, HTTPS routes, unknown SNI rejected, no API over HTTP", flush=True)


def verify():
    local_engine()
    project = "sni40-check-" + uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="sni40-tls-") as temporary:
        directory = Path(temporary)
        ca = authority(directory)
        first = issue(directory, 1)
        environment = {**os.environ, "TLS_FIXTURE_DIR": str(directory)}
        command = ["docker", "compose", "--env-file", os.devnull, "-p", project,
                   "-f", str(ROOT / "tests/nginx/tls-ingress.yaml")]

        def compose(*args, capture=False):
            return subprocess.run([*command, *args], env=environment, check=True, timeout=180,
                                  stdout=subprocess.PIPE if capture else None, text=True)

        def published(target):
            return int(compose("port", "nginx", target, capture=True).stdout.strip().rsplit(":", 1)[1])

        def proxy_id():
            return compose("ps", "-q", "nginx", capture=True).stdout.strip()

        print(f"SNI-40 isolated project: {project}", flush=True)
        try:
            compose("up", "-d", "nginx")
            compose("exec", "-T", "nginx", "nginx", "-t")
            http_port, https_port = published("8080"), published("8443")
            eventually(lambda: plain(http_port, "/healthz", host="127.0.0.1").status == 200, "NGINX did not start")
            check_http(http_port)
            compose("up", "-d", "snippets-service", "ui")
            eventually(lambda: secure(https_port, ca, "/api/snippets")[0].status == 200, "HTTPS API did not recover")
            check_https(https_port, ca, first)
            check_execution_stream(lambda: PinnedHTTPS(HOST, https_port, context=context(ca), timeout=6),
                                   lambda path, method="GET", body=None, headers=None:
                                   secure(https_port, ca, path, method, body, headers=headers)[0])
            before = proxy_id()
            second = issue(directory, 2)
            compose("exec", "-T", "nginx", "nginx", "-t")
            compose("exec", "-T", "nginx", "nginx", "-s", "reload")
            eventually(lambda: secure(https_port, ca, "/healthz")[1] == second, "Reload did not serve the renewed certificate")
            require(proxy_id() == before, "Proxy was recreated to load the renewed certificate")
            print("PASS renewed certificate served after nginx -t and reload, same container", flush=True)
            compose("restart", "nginx")
            https_port = published("8443")
            eventually(lambda: secure(https_port, ca, "/healthz")[1] == second, "Restart lost the renewed certificate")
            print("PASS proxy restart keeps the persisted certificate", flush=True)
        finally:
            compose("down", "--timeout", "5")


if __name__ == "__main__":
    try:
        verify()
    except (RuntimeError, OSError, ValueError, http.client.HTTPException, ssl.SSLError,
            subprocess.SubprocessError) as error:
        print(f"FAIL HTTPS ingress acceptance: {error}", file=sys.stderr)
        sys.exit(1)
