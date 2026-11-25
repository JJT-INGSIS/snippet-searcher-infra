import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

BASE_URL = os.environ.get("SNI53_BASE_URL", "http://localhost:8088/api")
INFRA = Path(__file__).resolve().parent.parent
REQUEST_SECONDS = 15.0
STREAM_SECONDS = 150.0
RECOVERY_SECONDS = 90.0
LARGE_LINE = 200_000
LARGE_LINES = 6
REPOSITORIES = (
    "snippets-service",
    "permissions-service",
    "printscript-service",
    "snippet-searcher-ui",
    "snippet-searcher-infra",
)
ASKS_NAME = 'println("Antes"); let nombre: string = readInput("Nombre?"); println("Hola, " + nombre);'
TWO_INPUTS = 'let a: string = readInput("a?"); println(a); let b: string = readInput("b?"); println(b);'


class VerificationError(Exception):
    pass


@dataclass(frozen=True)
class Reply:
    status: int
    body: object


@dataclass(frozen=True)
class Received:
    seconds: float
    event: dict


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def problem(reply: Reply) -> str:
    body = reply.body if isinstance(reply.body, dict) else {}
    return str(body.get("type", "")).rsplit(":", 1)[-1]


def kinds(received: list) -> list:
    return [item.event["type"] for item in received]


def outputs(received: list) -> list:
    return [item.event["data"]["text"] for item in received if item.event["type"] == "output"]


def terminal_of(received: list) -> dict:
    last = received[-1].event if received else {}
    require(last.get("type") == "terminal", f"el stream terminó sin terminal: {kinds(received)}")
    return last["data"]


def large_output_code(line: int = LARGE_LINE, lines: int = LARGE_LINES) -> str:
    declaration = 'let texto: string = "' + "x" * line + '";'
    return declaration + " println(texto);" * lines


def actor(role: str) -> str:
    return f"sni53-{role}-{uuid4().hex[:8]}"


def connection(seconds: float):
    target = urlsplit(BASE_URL)
    factory = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    return factory(target.hostname, target.port, timeout=seconds), target.path.rstrip("/")


def call(method: str, path: str, identity: str | None = None, body: object = None, extra: dict | None = None) -> Reply:
    client, prefix = connection(REQUEST_SECONDS)
    headers = {"Content-Type": "application/json", **(extra or {})}
    if identity:
        headers["X-Dev-Actor-Id"] = identity
    try:
        client.request(method, prefix + path, None if body is None else json.dumps(body).encode(), headers)
        response = client.getresponse()
        raw = response.read()
        return Reply(response.status, json.loads(raw) if raw else None)
    finally:
        client.close()


def compose(*arguments: str, seconds: float = 240.0) -> str:
    completed = subprocess.run(
        ["docker", "compose", *arguments], cwd=INFRA, capture_output=True, text=True, timeout=seconds,
    )
    require(completed.returncode == 0, f"docker compose {' '.join(arguments)} falló: {completed.stderr.strip()[-300:]}")
    return completed.stdout


def eventually(attempt, seconds: float, message: str):
    deadline = time.monotonic() + seconds
    while True:
        try:
            result = attempt()
        except (OSError, http.client.HTTPException):
            result = None
        if result:
            return result
        require(time.monotonic() < deadline, message)
        time.sleep(2)


def snippet(owner: str, name: str, code: str, version: str = "1.1") -> str:
    body = {"name": name, "description": None, "language": "printscript", "version": version, "code": code}
    reply = call("POST", "/snippets", owner, body, {"Idempotency-Key": str(uuid4())})
    require(reply.status == 201, f"crear {name}: {reply.status} {problem(reply)}")
    return reply.body["id"]


def test_case(owner: str, snippet_id: str, inputs: list, expected: list) -> str:
    reply = call("POST", f"/snippets/{snippet_id}/tests", owner, {"inputs": inputs, "expectedOutputs": expected})
    require(reply.status == 201, f"crear test: {reply.status} {problem(reply)}")
    return reply.body["id"]


def start(identity: str, snippet_id: str, test_id: str | None = None) -> Reply:
    path = f"/snippets/{snippet_id}" + (f"/tests/{test_id}" if test_id else "") + "/executions"
    return call("POST", path, identity, {})


def created(reply: Reply) -> str | None:
    return reply.body["executionId"] if reply.status == 201 else None


def started(identity: str, snippet_id: str, test_id: str | None = None) -> str:
    reply = start(identity, snippet_id, test_id)
    require(reply.status == 201, f"iniciar ejecución: {reply.status} {problem(reply)}")
    return reply.body["executionId"]


def send(identity: str, execution: str, request_id: str, value: str) -> Reply:
    return call("POST", f"/executions/{execution}/inputs", identity, {"requestId": request_id, "value": value})


class Stream:
    def __init__(self, identity: str, execution: str):
        self.client, prefix = connection(STREAM_SECONDS)
        self.client.request("GET", f"{prefix}/executions/{execution}/events?after=0", headers={"X-Dev-Actor-Id": identity})
        self.response = self.client.getresponse()
        require(self.response.status == 200, f"abrir eventos: {self.response.status}")
        self.opened = time.monotonic()
        self.received = []

    def next(self) -> Received | None:
        try:
            line = self.response.readline()
        except (OSError, http.client.HTTPException):
            return None
        if not line.strip():
            return None
        item = Received(round(time.monotonic() - self.opened, 3), json.loads(line))
        self.received.append(item)
        return item

    def until(self, kind: str) -> dict:
        while True:
            item = self.next()
            require(item is not None, f"el stream terminó antes de {kind}: {kinds(self.received)}")
            if item.event["type"] == kind:
                return item.event

    def rest(self) -> list:
        while True:
            item = self.next()
            if item is None or item.event["type"] == "terminal":
                self.client.close()
                return self.received


def run_to_end(identity: str, execution: str) -> list:
    return Stream(identity, execution).rest()


def finish(identity: str, execution: str) -> dict:
    return terminal_of(run_to_end(identity, execution))


def cancel(identity: str, execution: str) -> dict:
    reply = call("POST", f"/executions/{execution}/cancel", identity, {})
    require(reply.status == 202, f"cancelar: {reply.status} {problem(reply)}")
    return finish(identity, execution)


def audit(execution: str) -> dict:
    UUID(execution)
    query = (
        "SELECT mode, test_id IS NULL, COALESCE(result->'terminal'->>'outcome', ''), "
        "COALESCE(jsonb_array_length(result->'outputs'), -1), reserved, COALESCE(failure, '') "
        f"FROM snippet_execution_audit WHERE id = '{execution}'"
    )
    row = compose("exec", "-T", "snippets-db", "psql", "-U", "snippets", "-d", "snippets", "-At", "-F", "|", "-c", query)
    require(row.strip() != "", f"sin fila de auditoría para {execution}")
    mode, without_test, outcome, kept, reserved, failure = row.strip().split("|")
    return {
        "mode": mode, "withoutTest": without_test == "t", "outcome": outcome,
        "outputsKept": int(kept), "reserved": reserved == "t", "failure": failure,
    }


def startable(identity: str, snippet_id: str) -> str | None:
    reply = start(identity, snippet_id)
    if reply.status != 201:
        return None
    execution = reply.body["executionId"]
    cancel(identity, execution)
    return execution


def released(identity: str, snippet_id: str) -> str:
    return eventually(
        lambda: startable(identity, snippet_id), RECOVERY_SECONDS, f"{identity} sigue sin poder ejecutar",
    )


def definitions(state: dict) -> dict:
    owner = actor("owner")
    main = snippet(owner, "SNI-53 tests", TWO_INPUTS)
    cases = {
        "pass": (["Ana", "Ana"], ["Ana", "Ana"]),
        "fail": (["Ana", "Bea"], ["Ana", "Otra"]),
        "edge": (["", "ñ 🌎"], ["", "ñ 🌎"]),
        "exhausted": (["Ana"], ["Ana"]),
    }
    tests = {name: test_case(owner, main, inputs, expected) for name, (inputs, expected) in cases.items()}
    listed = call("GET", f"/snippets/{main}/tests", owner)
    require(listed.status == 200, f"listar tests: {listed.status}")
    saved = [(item["id"], item["inputs"], item["expectedOutputs"]) for item in listed.body["items"]]
    require(saved == [(tests[name], *cases[name]) for name in cases], "los tests no se guardaron exactos")
    state.update(owner=owner, snippet=main, tests=tests, listed=listed.body, executions=[])
    return {"tests": len(saved), "exact": True}


def sharing(state: dict) -> dict:
    owner, main, tests = state["owner"], state["snippet"], state["tests"]
    shared = call("PUT", f"/snippets/{main}/shares/dev-ana", owner)
    require(shared.status in (200, 201), f"compartir: {shared.status}")
    reader_list = call("GET", f"/snippets/{main}/tests", "dev-ana")
    require(reader_list.status == 200 and reader_list.body == state["listed"], "B no ve los mismos tests")
    reader_create = call("POST", f"/snippets/{main}/tests", "dev-ana", {"inputs": [], "expectedOutputs": []})
    require(reader_create.status == 403, f"B creó un test: {reader_create.status}")
    reader_run = eventually(lambda: created(start("dev-ana", main, tests["pass"])), RECOVERY_SECONDS, "B no pudo ejecutar")
    reader_terminal = finish("dev-ana", reader_run)
    require(reader_terminal.get("comparison") == "PASSED", f"B: {reader_terminal}")
    stranger = actor("stranger")
    denied = {
        "listTests": call("GET", f"/snippets/{main}/tests", stranger).status,
        "detail": call("GET", f"/snippets/{main}", stranger).status,
        "runTest": start(stranger, main, tests["pass"]).status,
        "runInteractive": start(stranger, main).status,
    }
    require(set(denied.values()) == {404}, f"C obtuvo acceso: {denied}")
    other = snippet(owner, "SNI-53 otro", 'println("otro");')
    foreign = test_case(owner, other, [], ["otro"])
    crossed = start(owner, main, foreign)
    require(crossed.status == 404, f"test de otro snippet: {crossed.status}")
    return {"readerCreate": 403, "readerRun": "PASSED", "stranger": denied, "foreignTest": 404}


def test_runs(state: dict) -> dict:
    owner, main, tests = state["owner"], state["snippet"], state["tests"]
    expected = {
        "pass": ("COMPLETED", "PASSED"), "fail": ("COMPLETED", "FAILED"),
        "edge": ("COMPLETED", "PASSED"), "exhausted": ("INPUT_EXHAUSTED", None),
    }
    results = {}
    for name, (outcome, comparison) in expected.items():
        execution = started(owner, main, tests[name])
        received = run_to_end(owner, execution)
        terminal = terminal_of(received)
        require(terminal["outcome"] == outcome and terminal.get("comparison") == comparison, f"{name}: {terminal}")
        state["executions"].append(execution)
        results[name] = {"events": kinds(received), "outputs": outputs(received), "comparison": comparison}
    broken = snippet(owner, "SNI-53 error", "println(1 / 0);")
    failing = test_case(owner, broken, [], [])
    terminal = finish(owner, started(owner, broken, failing))
    require(terminal["outcome"] == "PROGRAM_ERROR" and "comparison" not in terminal, f"error de programa: {terminal}")
    results["programError"] = {"outcome": terminal["outcome"], "reason": terminal["reason"]}
    return results


def interactive(state: dict) -> dict:
    owner = actor("interactive")
    program = snippet(owner, "SNI-53 interactivo", ASKS_NAME)
    execution = started(owner, program)
    stream = Stream(owner, execution)
    prompt = stream.until("input-required")
    before = outputs(stream.received)
    require(before == ["Antes"], f"no llegó el output antes del pedido: {before}")
    intruder = actor("intruder")
    attempts = {
        "describe": call("GET", f"/executions/{execution}", intruder).status,
        "events": call("GET", f"/executions/{execution}/events?after=0", intruder).status,
        "input": send(intruder, execution, prompt["data"]["requestId"], "X").status,
        "cancel": call("POST", f"/executions/{execution}/cancel", intruder, {}).status,
    }
    require(set(attempts.values()) == {403}, f"otro actor operó la sesión: {attempts}")
    time.sleep(2)
    request_id = prompt["data"]["requestId"]
    accepted = send(owner, execution, request_id, "Ana")
    require(accepted.status == 200 and accepted.body == {"requestId": request_id, "accepted": True}, "input rechazado")
    repeated = send(owner, execution, request_id, "Ana")
    require(repeated.status == 200, f"repetir el input: {repeated.status}")
    conflicting = send(owner, execution, request_id, "Otra")
    require(conflicting.status == 409 and problem(conflicting) == "input-conflict", f"otro valor: {conflicting.status}")
    received = stream.rest()
    terminal = terminal_of(received)
    require(outputs(received) == ["Antes", "Hola, Ana"], f"outputs: {outputs(received)}")
    require(terminal["outcome"] == "COMPLETED" and "comparison" not in terminal, f"terminal: {terminal}")
    saved = audit(execution)
    require(saved["mode"] == "INTERACTIVE" and saved["withoutTest"] and saved["outputsKept"] == 0, f"auditoría: {saved}")
    require(not saved["reserved"], "la reserva quedó tomada")
    state["executions"].append(execution)
    first_output = next(item.seconds for item in received if item.event["type"] == "output")
    return {
        "events": kinds(received), "intruder": attempts, "repeatedInput": 200, "conflictingInput": 409,
        "secondsBetweenFirstOutputAndTerminal": round(received[-1].seconds - first_output, 3), "audit": saved,
    }


def update_during_run(state: dict) -> dict:
    owner = actor("editor")
    code = 'println("v1"); let n: string = readInput("?"); println("v1 " + n);'
    program = snippet(owner, "SNI-53 edición", code)
    reply = start(owner, program)
    require(reply.status == 201, f"iniciar: {reply.status}")
    execution, code_hash = reply.body["executionId"], reply.body["snapshot"]["codeHash"]
    stream = Stream(owner, execution)
    prompt = stream.until("input-required")
    body = {"name": "SNI-53 edición", "description": None, "language": "printscript", "version": "1.1", "code": 'println("v2");'}
    edited = call("PUT", f"/snippets/{program}", owner, body)
    require(edited.status == 200, f"editar: {edited.status}")
    send(owner, execution, prompt["data"]["requestId"], "Ana")
    received = stream.rest()
    require(outputs(received) == ["v1", "v1 Ana"], f"no usó la foto vieja: {outputs(received)}")
    described = call("GET", f"/executions/{execution}", owner)
    require(described.body["snapshot"]["codeHash"] == code_hash, "cambió el hash del snapshot")
    current = call("GET", f"/snippets/{program}", owner)
    require(current.body.get("code") == 'println("v2");', "el snippet no quedó editado")
    return {"outputs": outputs(received), "snapshotKept": True, "snippetNow": "v2"}


def actor_quota(state: dict) -> dict:
    owner = actor("quota")
    program = snippet(owner, "SNI-53 cupo", ASKS_NAME)
    first = started(owner, program)
    second = start(owner, program)
    require(second.status == 409 and problem(second) == "execution-already-active", f"segunda: {second.status}")
    stopped = cancel(owner, first)
    require(stopped["outcome"] == "CANCELLED", f"Stop: {stopped}")
    require(not audit(first)["reserved"], "Stop no liberó la reserva")
    again = startable(owner, program)
    require(again is not None, "no pudo volver a ejecutar después de Stop")
    return {"secondStart": 409, "stop": stopped["outcome"], "restartAfterStop": True}


def global_limit(state: dict) -> dict:
    owners = [actor(f"global{index}") for index in range(5)]
    programs = [snippet(owner, f"SNI-53 global {index}", ASKS_NAME) for index, owner in enumerate(owners)]
    running = [started(owner, program) for owner, program in zip(owners[:4], programs[:4])]
    fifth = start(owners[4], programs[4])
    outcomes = [cancel(owner, execution)["outcome"] for owner, execution in zip(owners, running)]
    require(fifth.status == 429 and problem(fifth) == "execution-capacity-exhausted", f"quinta: {fifth.status}")
    require(set(outcomes) == {"CANCELLED"}, f"cancelaciones: {outcomes}")
    require(startable(owners[4], programs[4]) is not None, "la quinta no pudo ejecutar después")
    return {"fifthStart": 429, "cancelled": len(outcomes), "fifthAfterRelease": True}


def environment(state: dict) -> dict:
    owner = actor("env")
    secret = env_value("SNIPPETS_DB_PASSWORD")
    results = {}
    for name in ("PATH", "SNIPPETS_DB_PASSWORD"):
        program = snippet(owner, f"SNI-53 readEnv {name}", f'println(readEnv("{name}"));')
        received = run_to_end(owner, started(owner, program))
        terminal = terminal_of(received)
        rules = [item.get("rule") for item in terminal.get("diagnostics", [])]
        require(terminal["outcome"] == "PROGRAM_ERROR" and outputs(received) == [], f"readEnv {name}: {terminal}")
        require(not secret or secret not in json.dumps(terminal), "el secreto apareció en el terminal")
        results[name] = {"outcome": terminal["outcome"], "rules": rules}
    return results


def env_value(name: str) -> str:
    path = INFRA / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    return next((line.split("=", 1)[1] for line in lines if line.startswith(name + "=")), "")


def large_output(state: dict) -> dict:
    owner = actor("output")
    program = snippet(owner, "SNI-53 salida", large_output_code())
    received = run_to_end(owner, started(owner, program))
    terminal = terminal_of(received)
    require(terminal["outcome"] == "LIMIT_EXCEEDED", f"salida excesiva: {terminal}")
    return {"outcome": terminal["outcome"], "reason": terminal["reason"], "outputsBeforeLimit": len(outputs(received))}


def input_wait(state: dict) -> dict:
    owner = actor("wait")
    program = snippet(owner, "SNI-53 espera", ASKS_NAME)
    execution = started(owner, program)
    stream = Stream(owner, execution)
    stream.until("input-required")
    terminal = terminal_of(stream.rest())
    require(terminal["outcome"] == "LIMIT_EXCEEDED", f"espera vencida: {terminal}")
    require(not audit(execution)["reserved"], "la espera vencida no liberó la reserva")
    return {"outcome": terminal["outcome"], "reason": terminal["reason"], "seconds": stream.received[-1].seconds}


def no_consumer(state: dict) -> dict:
    owner = actor("noconsumer")
    program = snippet(owner, "SNI-53 sin navegador", ASKS_NAME)
    execution = started(owner, program)
    released(owner, program)
    saved = audit(execution)
    require(saved["outcome"] != "COMPLETED" and not saved["reserved"], f"sin navegador: {saved}")
    return {"audit": saved}


def interpreter_down(state: dict) -> dict:
    owner = actor("down")
    program = snippet(owner, "SNI-53 caído", 'println("ok");')
    check = test_case(owner, program, [], ["ok"])
    compose("stop", "printscript-service")
    try:
        refused = start(owner, program, check)
    finally:
        interpreter_ready()
    require(refused.status == 503 and problem(refused) == "dependency-unavailable", f"PrintScript caído: {refused.status}")
    attempts = []
    terminal = eventually(lambda: fresh_run(attempts), RECOVERY_SECONDS, f"ningún actor nuevo pudo ejecutar: {attempts}")
    require(terminal.get("comparison") == "PASSED", f"actor nuevo después de volver: {terminal}")
    blocked = [item["actor"] for item in attempts if item["status"] != 201] + [owner]
    stuck = [name for name in blocked if not eventually_free(name)]
    require(not stuck, f"actores con un inicio fallido quedaron bloqueados: {len(stuck)} de {len(blocked)}; intentos {attempts}")
    return {"whileDown": 503, "attemptsAfterRestart": attempts, "blockedReleased": True}


def fresh_run(attempts: list) -> dict | None:
    owner = actor("after-down")
    program = snippet(owner, "SNI-53 después", 'println("ok");')
    check = test_case(owner, program, [], ["ok"])
    reply = start(owner, program, check)
    attempts.append({"actor": owner, "status": reply.status, "problem": problem(reply)})
    return finish(owner, reply.body["executionId"]) if reply.status == 201 else None


def eventually_free(owner: str) -> bool:
    try:
        return bool(eventually(lambda: reservations(owner) == 0, RECOVERY_SECONDS, "reserva tomada"))
    except VerificationError:
        return False


def reservations(owner: str) -> int:
    require(re.fullmatch(r"sni53-[a-z0-9-]+", owner) is not None, f"actor inesperado: {owner}")
    query = f"SELECT count(*) FROM snippet_execution_audit WHERE reserved AND actor_id = '{owner}'"
    return int(compose("exec", "-T", "snippets-db", "psql", "-U", "snippets", "-d", "snippets", "-At", "-c", query))


def interpreter_ready() -> None:
    compose("up", "-d", "--no-build", "--wait", "printscript-service")
    probe = actor("probe")
    eventually(lambda: validated(probe), RECOVERY_SECONDS, "PrintScript no volvió a validar código")


def validated(probe: str) -> bool:
    body = {"name": "SNI-53 probe", "description": None, "language": "printscript", "version": "1.1", "code": "println(1);"}
    return call("POST", "/snippets", probe, body, {"Idempotency-Key": str(uuid4())}).status == 201


def interpreter_restart(state: dict) -> dict:
    return interrupted("restart", ("restart", "printscript-service"))


def interpreter_kill(state: dict) -> dict:
    return interrupted("kill", ("kill", "printscript-service"))


def interrupted(role: str, *commands: tuple) -> dict:
    owner = actor(role)
    program = snippet(owner, f"SNI-53 {role}", ASKS_NAME)
    execution = started(owner, program)
    stream = Stream(owner, execution)
    stream.until("input-required")
    for command in commands:
        compose(*command)
    received = stream.rest()
    interpreter_ready()
    last = received[-1].event if received else {}
    seen = last["data"]["outcome"] if last.get("type") == "terminal" else "sin terminal"
    require(seen != "COMPLETED", f"{role}: se presentó como completado")
    released(owner, program)
    saved = audit(execution)
    require(saved["outcome"] != "COMPLETED" and not saved["reserved"], f"{role}: {saved}")
    return {"streamEnd": seen, "audit": saved}


def recreate(state: dict) -> dict:
    owner = actor("recreate")
    program = snippet(owner, "SNI-53 recrear", ASKS_NAME)
    execution = started(owner, program)
    before = {item: audit(item) for item in state["executions"]}
    services = ["snippets-db", "snippets-service", "permissions-db", "permissions-service", "printscript-service"]
    compose("up", "-d", "--no-build", "--force-recreate", "--wait", *services, seconds=400)
    compose("restart", "nginx")
    listed = eventually(lambda: tests_after(state), RECOVERY_SECONDS, "no se pudieron leer los tests")
    require(listed == state["listed"], "los tests cambiaron después de recrear")
    after = {item: audit(item) for item in state["executions"]}
    require(after == before, "cambiaron resultados guardados")
    released(owner, program)
    saved = audit(execution)
    require(saved["outcome"] != "COMPLETED" and not saved["reserved"], f"sesión activa: {saved}")
    return {"testsKept": True, "resultsKept": len(after), "activeSession": saved}


def tests_after(state: dict) -> dict | None:
    reply = call("GET", f"/snippets/{state['snippet']}/tests", state["owner"])
    return reply.body if reply.status == 200 else None


def versions() -> dict:
    commits = {}
    for name in REPOSITORIES:
        folder = INFRA if name == "snippet-searcher-infra" else INFRA.parent / name
        found = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True, text=True)
        commits[name] = found.stdout.strip() if found.returncode == 0 else "no disponible"
    images = [json.loads(line) for line in compose("images", "--format", "json").splitlines() if line.strip()]
    flat = [item for entry in images for item in (entry if isinstance(entry, list) else [entry])]
    return {"commits": commits, "images": {item["ContainerName"]: item["ID"] for item in flat}}


CASES = (
    ("1 definiciones exactas", definitions),
    ("2 compartir y autorización", sharing),
    ("3 ejecutar tests", test_runs),
    ("4 interactivo y dueño de la sesión", interactive),
    ("6 editar durante la ejecución", update_during_run),
    ("5 cupo por actor y Stop", actor_quota),
    ("5 límite global", global_limit),
    ("9 readEnv sin variables del servicio", environment),
    ("5 salida excesiva", large_output),
    ("5 espera de input vencida", input_wait),
    ("5 sin navegador", no_consumer),
    ("3 PrintScript caído", interpreter_down),
    ("5 reinicio ordenado de PrintScript", interpreter_restart),
    ("5 PrintScript muere de golpe", interpreter_kill),
    ("7 recrear componentes", recreate),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="SNI-53: aceptación de US8-10 contra Compose local")
    parser.add_argument("--output", type=Path, help="archivo JSON de evidencia")
    arguments = parser.parse_args()
    state = {}
    results = []
    for name, case in CASES:
        began = time.monotonic()
        try:
            evidence = case(state)
            results.append({"case": name, "result": "PASSED", "evidence": evidence})
        except (VerificationError, OSError, http.client.HTTPException, subprocess.SubprocessError, KeyError, ValueError) as error:
            results.append({"case": name, "result": "FAILED", "error": str(error)})
        seconds = round(time.monotonic() - began, 1)
        results[-1]["seconds"] = seconds
        print(f"{'OK   ' if results[-1]['result'] == 'PASSED' else 'FALLA'} {name} ({seconds} s)", flush=True)
        if results[-1]["result"] == "FAILED":
            print(f"      {results[-1]['error']}", flush=True)
    report = {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseUrl": BASE_URL,
        "versions": versions(),
        "cases": results,
    }
    if arguments.output:
        arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    failed = sum(item["result"] == "FAILED" for item in results)
    print(f"{len(results) - failed}/{len(results)} casos aprobados")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())