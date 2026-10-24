"""HTTP transport fixture, not an implementation of Snippets or the UI."""
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROLE = sys.argv[1]
WRITES = {}
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle_request(self):
        path = urlsplit(self.path).path
        data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.command in ("POST", "PUT", "DELETE"):
            with LOCK:
                WRITES[path] = WRITES.get(path, 0) + 1
        if path == "/slow":
            time.sleep(65)
        if path == "/disconnect-write":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if path == "/problem":
            body = {"type": "urn:fixture:invalid", "status": 422, "title": "Invalid", "detail": "fixture", "instance": path}
            self.reply(422, json.dumps(body).encode(), "application/problem+json")
        elif path == "/missing":
            self.reply(404, b'{"status":404,"type":"urn:fixture:missing"}', "application/problem+json")
        elif path == "/fail-write":
            self.reply(503, b'{"status":503}', "application/problem+json")
        elif path == "/__test/stats":
            with LOCK:
                self.reply(200, json.dumps(WRITES).encode(), "application/json")
        elif ROLE == "ui":
            self.reply(200, b"<!doctype html><title>UI transport fixture</title>", "text/html")
        else:
            self.reply(200, json.dumps({"role": ROLE, "method": self.command, "path": self.path,
                                       "body": data.decode("utf-8"), "headers": dict(self.headers)}).encode(), "application/json")

    def reply(self, status, body, media):
        try:
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request
    do_OPTIONS = handle_request

    def log_message(self, *args):
        # Fixtures receive fake Authorization values. Never log requests/headers.
        pass


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
