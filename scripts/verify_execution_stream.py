"""HTTP/HTTPS assertions against a gated transport fixture, not an interpreter."""
import json
import time
from uuid import uuid4

from verify_nginx import PUBLIC_HOST, require


def check_execution_stream(connect, call):
    headers = {"Content-Type": "application/json", "X-Dev-Actor-Id": "fixture-actor",
               "Authorization": "Bearer fixture-not-a-real-token"}
    for action in ("inputs", "cancel"):
        identity = str(uuid4())
        path = f"/api/executions/{identity}"
        connection = connect()
        try:
            connection.request("GET", path + "/events?after=1", headers={
                "Host": PUBLIC_HOST, "Accept-Encoding": "gzip", **headers})
            incoming = connection.getresponse()
            require(incoming.status == 200 and incoming.getheader("Content-Type") == "application/x-ndjson",
                    "Event status/media type changed")
            require(incoming.getheader("Content-Encoding") is None, "Stream was compressed")
            require(incoming.getheader("Cache-Control") == "no-store", "Stream lost no-store")
            require(sum(key.lower() == "cache-control" for key, _ in incoming.getheaders()) == 1,
                    "Stream cache policy duplicated")
            records = [json.loads(incoming.readline(4096)) for _ in range(3)]
            require([row["seq"] for row in records] == [2, 3, 4], "Cursor/query or sequence changed")
            require([row["type"] for row in records] == ["output", "heartbeat", "input-required"], "Event types changed")
            require(records[0]["data"]["text"] == "¡Hola 🌎!", "Split UTF-8 changed")
            require(all(row["executionId"] == identity for row in records), "Another stream was reused")
            require(not json.loads(call(path).body)["finished"], "Events were withheld until upstream termination")
            body = json.dumps({"requestId": records[-1]["data"]["requestId"], "value": "ñ\n"}).encode()
            if action == "cancel":
                body = b"{}"
            accepted = call(path + "/" + action, "POST", body, headers)
            require(accepted.status == (200 if action == "inputs" else 202), "Control response changed")
            terminal = json.loads(incoming.readline(4096))
            require(terminal["type"] == "terminal" and terminal["seq"] == 5, "Terminal framing changed")
            require(terminal["data"]["outcome"] == ("COMPLETED" if action == "inputs" else "CANCELLED"),
                    "Control request did not reach waiting fixture")
            require(incoming.readline(4096) == b"", "Data appended after EOF")
            state = json.loads(call(path).body)
            received = {key.lower(): value for key, value in state["actionHeaders"].items()}
            require(state["body"] == body.decode() and received.get("x-dev-actor-id") == "fixture-actor"
                    and received.get("authorization") == headers["Authorization"], "Control body/identity changed")
            require(json.loads(call("/api/__test/stats").body)[f"/executions/{identity}/{action}"] == 1,
                    "Control request replayed")
        finally:
            connection.close()
    base = "/api/executions/550e8400-e29b-41d4-a716-446655"
    problem = call(base + "000001/events?after=999")
    require(problem.status == 409 and problem.headers.get("Content-Type") == "application/problem+json",
            "Pre-stream error changed")
    require(problem.headers.get("Cache-Control") == "no-store", "Error in private session can be cached")
    connection = connect()
    try:
        connection.request("GET", base + "000002/events", headers={"Host": PUBLIC_HOST})
        incoming = connection.getresponse()
        partial = [json.loads(line) for line in incoming if line]
        require([row["seq"] for row in partial] == [1, 2, 3, 4], "Interrupted stream altered")
        require(not any(row["type"] == "terminal" for row in partial), "Terminal invented on EOF")
    finally:
        connection.close()
    for suffix, expected in (("000003", 502), ("000004", 503)):
        for action in ("inputs", "cancel"):
            path = base + suffix + "/" + action
            require(call(path, "POST", b"{}", headers).status == expected, "Control failure hidden")
            require(json.loads(call("/api/__test/stats").body)[path.removeprefix("/api")] == 1,
                    "Failed control replayed")
    print("PASS incremental NDJSON, cursor/UTF-8, input/cancel, errors, EOF and no retries (fixture only)", flush=True)


def check_heartbeat_stream(connect):
    started = time.monotonic()
    connection = connect()
    try:
        connection.request("GET", "/api/executions/550e8400-e29b-41d4-a716-446655000005/events",
                           headers={"Host": PUBLIC_HOST})
        connection.sock.settimeout(20)
        incoming = connection.getresponse()
        records = [json.loads(incoming.readline(4096))]
        require(records[0]["type"] == "started" and time.monotonic() - started < 6,
                "First event was buffered")
        records.extend(json.loads(line) for line in incoming if line)
        require([row["seq"] for row in records] == list(range(1, 10)), "Heartbeat stream interrupted")
        require([row["type"] for row in records[1:-1]] == ["heartbeat"] * 7, "Heartbeats altered")
        require(records[-1]["type"] == "terminal" and time.monotonic() - started >= 65,
                "Transport did not remain open beyond the 60s inactivity timeout")
        print("PASS 70s open stream with 10s heartbeats and unchanged 60s inactivity timeout (fixture only)", flush=True)
    finally:
        connection.close()
