"""HTTP transport fixture, not an implementation of Snippets or the UI."""
import json
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROLE = sys.argv[1]
WRITES = {}
LOCK = threading.Lock()
STREAMS = {}
INPUT_REQUEST = "660e8400-e29b-41d4-a716-446655440000"


def event(execution, sequence, kind, data):
    return json.dumps({"executionId": execution, "seq": sequence, "type": kind, "data": data},
                      ensure_ascii=False).encode() + b"\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle_request(self):
        path = urlsplit(self.path).path
        data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.command in ("POST", "PUT", "DELETE"):
            with LOCK:
                WRITES[path] = WRITES.get(path, 0) + 1
        execution = re.fullmatch(r"/executions/([a-f0-9-]{36})(?:/(events|inputs|cancel))?", path)
        if ROLE == "api" and execution:
            self.execution_request(execution[1], execution[2], data)
            return
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

    def execution_request(self, identity, operation, data):
        # Transport fixture only: no interpreter, permissions or durable sessions.
        with LOCK:
            stream = STREAMS.setdefault(identity, {"gate": threading.Event(), "finished": False, "action": None})
        if operation is None:
            self.reply(200, json.dumps({"finished": stream["finished"], "action": stream["action"],
                                       "body": stream.get("body"), "actionHeaders": stream.get("headers"), "path": self.path,
                                       "headers": dict(self.headers)}).encode(), "application/json")
        elif operation in ("inputs", "cancel"):
            if identity.endswith("000003"):
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if identity.endswith("000004"):
                self.reply(503, b'{"status":503}', "application/problem+json")
                return
            stream["action"] = operation
            stream["body"] = data.decode()
            stream["headers"] = dict(self.headers)
            body = {"requestId": INPUT_REQUEST, "accepted": True} if operation == "inputs" else {"state": "CANCELLING"}
            self.reply(200 if operation == "inputs" else 202, json.dumps(body).encode(), "application/json")
            stream["gate"].set()
        elif operation == "events":
            after = int(parse_qs(urlsplit(self.path).query).get("after", ["0"])[0])
            if after == 999:
                self.reply(409, b'{"status":409,"type":"urn:snippets:problem:event-history-unavailable"}',
                           "application/problem+json")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            # Deliberately unsafe upstream policy: ingress must override it once.
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if identity.endswith("000005"):
                # Longer than the real 60s inactivity timeout, with 10s heartbeats.
                try:
                    self.wfile.write(event(identity, 1, "started", {"mode": "INTERACTIVE"}))
                    self.wfile.flush()
                    for sequence in range(2, 9):
                        time.sleep(10)
                        self.wfile.write(event(identity, sequence, "heartbeat", {}))
                        self.wfile.flush()
                    self.wfile.write(event(identity, 9, "terminal", {"outcome": "COMPLETED", "reason": "fixture"}))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            records = [("started", {"mode": "INTERACTIVE"}), ("output", {"text": "¡Hola 🌎!"}),
                       ("heartbeat", {}), ("input-required", {"requestId": INPUT_REQUEST, "prompt": "Nombre"})]
            try:
                for seq, (kind, content) in enumerate(records, 1):
                    if seq > after:
                        raw = event(identity, seq, kind, content)
                        # A Unicode character may straddle reads; a chunk is not an event.
                        split = raw.find("🌎".encode()) + 1 if kind == "output" else len(raw)
                        self.wfile.write(raw[:split])
                        self.wfile.flush()
                        if split < len(raw):
                            time.sleep(0.02)
                            self.wfile.write(raw[split:])
                            self.wfile.flush()
                if identity.endswith("000002"):
                    return  # Intentional EOF with no terminal, not a successful execution.
                if not stream["gate"].wait(8):
                    outcome = "TECHNICAL_FAILURE"
                else:
                    outcome = "CANCELLED" if stream["action"] == "cancel" else "COMPLETED"
                stream["finished"] = True
                self.wfile.write(event(identity, 5, "terminal", {"outcome": outcome, "reason": "fixture"}))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

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
