"""Verify HTTP contracts from the shared Compose network, using only the standard library."""

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

READY_TIMEOUT = 60.0
REQUEST_TIMEOUT = 5.0


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: dict


@dataclass(frozen=True)
class RequestFailure:
    detail: str
    retryable: bool = True


class VerificationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def base_url(variable: str) -> str:
    value = os.environ.get(variable, "").rstrip("/")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise VerificationError(f"{variable} must be a valid HTTP base URL.") from error
    require(
        parsed.scheme in ("http", "https")
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment,
        f"{variable} must be an HTTP base URL without credentials, query or fragment.",
    )
    return value


def request(
    base: str,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = REQUEST_TIMEOUT,
) -> Response | RequestFailure:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if payload is None else {"Content-Type": "application/json"}
    outgoing = Request(base + path, data=data, headers=headers, method=method)
    try:
        try:
            incoming = urlopen(outgoing, timeout=timeout)
        except HTTPError as error:
            # HTTP errors still have a response body, including Problem Details.
            incoming = error
        with incoming:
            status = incoming.status
            content_type = incoming.headers.get_content_type()
            raw = incoming.read()
    except (URLError, OSError, TimeoutError) as error:
        return RequestFailure(f"{method} {path}: connection failed ({error})")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return RequestFailure(f"{method} {path}: HTTP {status} did not return valid JSON", status >= 500)
    if not isinstance(body, dict):
        return RequestFailure(f"{method} {path}: HTTP {status} did not return a JSON object", status >= 500)
    return Response(status, content_type, body)


def wait_ready(probe: Callable[[float], Response | RequestFailure]) -> Response:
    deadline = time.monotonic() + READY_TIMEOUT
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0, f"Service did not become available within {READY_TIMEOUT:g} seconds.")
        result = probe(min(REQUEST_TIMEOUT, remaining))
        if isinstance(result, RequestFailure) and not result.retryable:
            raise VerificationError(result.detail)
        if isinstance(result, Response) and result.status < 500:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = result.detail if isinstance(result, RequestFailure) else f"HTTP {result.status}"
            raise VerificationError(f"Service did not become available within {READY_TIMEOUT:g} seconds: {detail}")
        time.sleep(min(1.0, remaining))


def response(result: Response | RequestFailure, status: int, content_type: str) -> Response:
    if isinstance(result, RequestFailure):
        raise VerificationError(result.detail)
    require(result.status == status, f"Expected HTTP {status}, received {result.status}.")
    require(
        result.content_type == content_type,
        f"Expected {content_type}, received {result.content_type}.",
    )
    return result


def success(result: Response | RequestFailure, status: int = 200) -> dict:
    return response(result, status, "application/json").body


def problem(
    result: Response | RequestFailure,
    status: int,
    instance: str,
    category: str | None = None,
) -> dict:
    body = response(result, status, "application/problem+json").body
    require(body.get("status") == status, "Problem Details status does not match HTTP status.")
    require(body.get("instance") == instance, "Problem Details instance does not match the request path.")
    for field in ("title", "detail"):
        require(isinstance(body.get(field), str) and bool(body[field].strip()), f"Missing Problem Details {field}.")
    if category is not None:
        require(body.get("type") == f"urn:permissions:problem:{category}", "Unexpected Problem Details type.")
    return body


def check_printscript() -> None:
    base = base_url("PRINTSCRIPT_BASE_URL")
    valid_code = {"code": "println(1);", "version": "1.0"}
    first = wait_ready(lambda timeout: request(base, "/validate", "POST", valid_code, timeout))
    first_body = success(first)
    require(
        first_body.get("valid") is True and first_body == {"valid": True, "diagnostics": []},
        "Valid PrintScript 1.0 was not accepted.",
    )
    second = request(base, "/validate", "POST", {**valid_code, "version": "1.1"})
    second_body = success(second)
    require(
        second_body.get("valid") is True and second_body == {"valid": True, "diagnostics": []},
        "Valid PrintScript 1.1 was not accepted.",
    )
    invalid = success(request(
        base, "/validate", "POST",
        {"code": "let total: number = 5\nprintln(total);", "version": "1.0"},
    ))
    require(invalid.get("valid") is False, "Invalid code must return HTTP 200 with valid=false.")
    diagnostics = invalid.get("diagnostics")
    require(isinstance(diagnostics, list) and bool(diagnostics), "Invalid code must include diagnostics.")
    for diagnostic in diagnostics:
        require(isinstance(diagnostic, dict), "Each diagnostic must be an object.")
        require(diagnostic.get("rule") == "UNEXPECTED_TOKEN", "Unexpected diagnostic rule for a missing semicolon.")
        require(isinstance(diagnostic.get("message"), str), "A diagnostic must contain a human-readable message.")
        for coordinate in ("line", "column"):
            require(
                type(diagnostic.get(coordinate)) is int and diagnostic[coordinate] >= 1,
                f"Diagnostic {coordinate} must be an integer starting at 1.",
            )
    unsupported = problem(
        request(base, "/validate", "POST", {**valid_code, "version": "2.0"}),
        422, "/validate",
    )
    versions = unsupported.get("supportedVersions")
    require(
        isinstance(versions, list) and all(isinstance(version, str) for version in versions)
        and set(versions) == {"1.0", "1.1"},
        "Unsupported version must report supportedVersions 1.0 and 1.1.",
    )


def check_permissions() -> None:
    base = base_url("PERMISSIONS_BASE_URL")
    snippet_id = str(uuid4())
    path = f"/ownership/{snippet_id}"
    owner = "infra-smoke-test"
    other = "infra-smoke-test-other"
    expected = {"snippetId": snippet_id, "ownerId": owner}
    initial = wait_ready(lambda timeout: request(base, path, timeout=timeout))
    problem(initial, 404, path, "ownership-not-found")
    require(
        success(request(base, path, "PUT", {"ownerId": owner}), 201) == expected,
        "Registration must return the UUID and owner that were supplied.",
    )
    print(f"  Test ownership created: {snippet_id} (owner={owner})", flush=True)
    require(
        success(request(base, path, "PUT", {"ownerId": owner})) == expected,
        "Retrying registration must preserve ownership.",
    )
    require(success(request(base, path)) == expected, "Owner lookup returned another relation.")
    for actor, allowed in ((owner, True), (other, False)):
        checked = success(request(base, path + "/can-modify?" + urlencode({"actorId": actor})))
        require(
            type(checked.get("allowed")) is bool and checked == {"allowed": allowed},
            "Modification permission did not match ownership.",
        )
    problem(request(base, path, "PUT", {"ownerId": other}), 409, path, "owner-conflict")
    require(success(request(base, path)) == expected, "Conflicting registration replaced the original owner.")
    health_result = request(base, "/actuator/health")
    if isinstance(health_result, RequestFailure):
        raise VerificationError(health_result.detail)
    require(
        health_result.content_type in ("application/json", "application/vnd.spring-boot.actuator.v3+json"),
        f"Unexpected Actuator health Content-Type: {health_result.content_type}.",
    )
    health = response(health_result, 200, health_result.content_type).body
    require(health.get("status") == "UP", "Permissions health is not UP.")


def run_suite(name: str, check: Callable[[], None]) -> bool:
    print(f"CHECK {name}", flush=True)
    try:
        check()
    except VerificationError as error:
        print(f"FAIL {name}: {error}", flush=True)
        return False
    print(f"PASS {name}", flush=True)
    return True


def main() -> int:
    results = tuple(run_suite(name, check) for name, check in (
        ("PrintScript", check_printscript),
        ("Permissions", check_permissions),
    ))
    print(f"Result: {sum(results)}/{len(results)} services passed.", flush=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
