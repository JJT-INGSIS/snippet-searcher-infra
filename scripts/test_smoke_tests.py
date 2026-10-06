"""Unit tests for the verification runner; no Docker, credentials or real services needed."""

import contextlib
import io
import unittest
from email.message import Message
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from uuid import UUID

import smoke_tests as smoke

SNIPPET_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
PATH = f"/ownership/{SNIPPET_ID}"


def ok(body, status=200):
    return smoke.Response(status, "application/json", body)


def problem(status, instance, category=None, **extra):
    body = {"status": status, "title": "Problem", "detail": "Detail", "instance": instance, **extra}
    if category:
        body["type"] = f"urn:permissions:problem:{category}"
    return smoke.Response(status, "application/problem+json", body)


def printscript_responses():
    return [
        ok({"valid": True, "diagnostics": []}),
        ok({"valid": True, "diagnostics": []}),
        ok({"valid": False, "diagnostics": [
            {"rule": "UNEXPECTED_TOKEN", "message": "Any wording", "line": 2, "column": 1},
        ]}),
        problem(422, "/validate", supportedVersions=["1.0", "1.1"]),
    ]


def permissions_responses():
    owner = {"snippetId": str(SNIPPET_ID), "ownerId": "infra-smoke-test"}
    return [
        problem(404, PATH, "ownership-not-found"),
        ok(owner, 201), ok(owner), ok(owner),
        ok({"allowed": True}), ok({"allowed": False}),
        problem(409, PATH, "owner-conflict"), ok(owner), ok({"status": "UP"}),
    ]


@patch.dict("os.environ", {
    "PRINTSCRIPT_BASE_URL": "http://printscript-service:8080",
    "PERMISSIONS_BASE_URL": "http://permissions-service:8080",
})
class ContractTest(unittest.TestCase):
    def test_printscript_checks_both_versions_and_http_errors(self):
        with patch.object(smoke, "request", side_effect=printscript_responses()) as request:
            smoke.check_printscript()
        self.assertEqual(request.call_args_list[1].args[3]["version"], "1.1")

    def test_printscript_rejects_http_error_for_invalid_code(self):
        responses = printscript_responses()
        responses[2] = problem(400, "/validate")
        with patch.object(smoke, "request", side_effect=responses):
            with self.assertRaises(smoke.VerificationError):
                smoke.check_printscript()

    def test_printscript_rejects_numeric_valid_field(self):
        with patch.object(smoke, "request", return_value=ok({"valid": 1, "diagnostics": []})):
            with self.assertRaises(smoke.VerificationError):
                smoke.check_printscript()

    def test_printscript_rejects_invalid_diagnostic_coordinates(self):
        responses = printscript_responses()
        responses[2].body["diagnostics"][0]["line"] = 0
        with patch.object(smoke, "request", side_effect=responses):
            with self.assertRaises(smoke.VerificationError):
                smoke.check_printscript()

    def test_permissions_checks_idempotence_denial_and_conflict(self):
        with patch.object(smoke, "uuid4", return_value=SNIPPET_ID):
            with patch.object(smoke, "request", side_effect=permissions_responses()) as request:
                smoke.check_permissions()
        self.assertEqual(request.call_args_list[1].args[3], {"ownerId": "infra-smoke-test"})
        self.assertIn("actorId=infra-smoke-test-other", request.call_args_list[5].args[1])

    def test_permissions_accepts_actuator_vendor_json(self):
        responses = permissions_responses()
        responses[-1] = smoke.Response(200, "application/vnd.spring-boot.actuator.v3+json", {"status": "UP"})
        with patch.object(smoke, "uuid4", return_value=SNIPPET_ID):
            with patch.object(smoke, "request", side_effect=responses):
                smoke.check_permissions()

    def test_permissions_rejects_wrong_health_content_type(self):
        responses = permissions_responses()
        responses[-1] = smoke.Response(200, "text/html", {"status": "UP"})
        with patch.object(smoke, "uuid4", return_value=SNIPPET_ID):
            with patch.object(smoke, "request", side_effect=responses):
                with self.assertRaises(smoke.VerificationError):
                    smoke.check_permissions()

    def test_permissions_rejects_unhealthy_actuator(self):
        responses = permissions_responses()
        responses[-1] = smoke.Response(503, "application/vnd.spring-boot.actuator.v3+json", {"status": "DOWN"})
        with patch.object(smoke, "uuid4", return_value=SNIPPET_ID):
            with patch.object(smoke, "request", side_effect=responses):
                with self.assertRaises(smoke.VerificationError):
                    smoke.check_permissions()

    def test_permissions_detects_owner_replaced_after_conflict(self):
        responses = permissions_responses()
        responses[7] = ok({"snippetId": str(SNIPPET_ID), "ownerId": "other"})
        with patch.object(smoke, "uuid4", return_value=SNIPPET_ID):
            with patch.object(smoke, "request", side_effect=responses):
                with self.assertRaises(smoke.VerificationError):
                    smoke.check_permissions()

    def test_permissions_detects_technical_failure_instead_of_denial(self):
        responses = permissions_responses()
        responses[5] = problem(500, PATH + "/can-modify")
        with patch.object(smoke, "uuid4", return_value=SNIPPET_ID):
            with patch.object(smoke, "request", side_effect=responses):
                with self.assertRaises(smoke.VerificationError):
                    smoke.check_permissions()


class RunnerTest(unittest.TestCase):
    def test_readiness_retries_connection_failure_and_server_error(self):
        probe = MagicMock(side_effect=[smoke.RequestFailure("offline"), problem(503, "/"), ok({})])
        with patch.object(smoke.time, "monotonic", side_effect=[0, 0, 0, 1, 1, 2]):
            with patch.object(smoke.time, "sleep"):
                self.assertEqual(smoke.wait_ready(probe), ok({}))
        self.assertEqual(probe.call_count, 3)

    def test_readiness_returns_client_error_without_retry(self):
        probe = MagicMock(return_value=problem(404, "/ownership/new"))
        self.assertEqual(smoke.wait_ready(probe).status, 404)
        probe.assert_called_once()

    def test_invalid_json_client_response_is_not_retried(self):
        probe = MagicMock(return_value=smoke.RequestFailure("invalid JSON", False))
        with self.assertRaises(smoke.VerificationError):
            smoke.wait_ready(probe)
        probe.assert_called_once()

    def test_readiness_has_a_bounded_deadline(self):
        with patch.object(smoke.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(smoke.VerificationError, "60 seconds"):
                smoke.wait_ready(MagicMock())

    def test_response_rejects_wrong_content_type(self):
        with self.assertRaises(smoke.VerificationError):
            smoke.success(smoke.Response(200, "text/html", {}))

    def test_failure_still_runs_both_suites_and_returns_nonzero(self):
        with patch.object(smoke, "check_printscript", side_effect=smoke.VerificationError("offline")):
            with patch.object(smoke, "check_permissions") as permissions:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(smoke.main(), 1)
                permissions.assert_called_once()

    def test_success_returns_zero(self):
        with patch.object(smoke, "check_printscript"), patch.object(smoke, "check_permissions"):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(smoke.main(), 0)

    def test_missing_url_fails_configuration(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(smoke.VerificationError):
                smoke.base_url("PERMISSIONS_BASE_URL")

    def test_url_credentials_are_rejected(self):
        with patch.dict("os.environ", {"PERMISSIONS_BASE_URL": "http://user:password@host"}):
            with self.assertRaises(smoke.VerificationError):
                smoke.base_url("PERMISSIONS_BASE_URL")


class RequestTest(unittest.TestCase):
    def test_http_error_body_is_read_as_problem_details(self):
        headers = Message()
        headers["Content-Type"] = "application/problem+json"
        error = HTTPError(
            "http://permissions-service:8080/ownership/new", 404, "Not Found", headers,
            io.BytesIO(b'{"status":404,"title":"Not Found","detail":"Missing","instance":"/ownership/new"}'),
        )
        with patch.object(smoke, "urlopen", side_effect=error):
            result = smoke.request("http://permissions-service:8080", "/ownership/new")
        self.assertIsInstance(result, smoke.Response)
        self.assertEqual(result.status, 404)
        self.assertEqual(result.content_type, "application/problem+json")

    def test_network_failure_is_retryable(self):
        with patch.object(smoke, "urlopen", side_effect=URLError("offline")):
            result = smoke.request("http://permissions-service:8080", "/ownership/new")
        self.assertIsInstance(result, smoke.RequestFailure)
        self.assertTrue(result.retryable)


if __name__ == "__main__":
    unittest.main()
