"""SNI-45 design examples; not an interpreter, HTTP server or production SDK."""

import copy
import hashlib
import json
import unittest
from pathlib import Path
from uuid import UUID

FIXTURE = Path(__file__).resolve().parents[1] / "docs/contracts/execution-v1.json"
OUTCOMES = {
    "COMPLETED", "PROGRAM_ERROR", "INPUT_EXHAUSTED", "LIMIT_EXCEEDED",
    "CANCELLED", "TECHNICAL_FAILURE", "INTERRUPTED",
}


def canonical_uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected canonical UUID")


def validate_example(example):
    """Check fixture invariants only, not authorization or actual interpreter work."""
    mode = example["mode"]
    if mode not in {"TEST", "INTERACTIVE"}:
        raise ValueError("Unknown mode")
    if mode == "TEST":
        definition = example["definition"]
        if set(definition) != {"inputs", "expectedOutputs"}:
            raise ValueError("Unexpected test fields")
        for key in ("inputs", "expectedOutputs"):
            if not isinstance(definition[key], list) or not all(
                isinstance(value, str) for value in definition[key]
            ):
                raise ValueError("Expected ordered arrays of strings")
    events = example["events"]
    if not events or events[0]["type"] != "started":
        raise ValueError("Missing started event")
    execution_id = events[0]["executionId"]
    canonical_uuid(execution_id)
    pending_input = None
    terminal = None
    output = []
    for seq, event in enumerate(events, 1):
        if terminal is not None:
            raise ValueError("Event after terminal")
        if type(event["seq"]) is not int or event["seq"] != seq:
            raise ValueError("Non-contiguous sequence")
        if event["executionId"] != execution_id:
            raise ValueError("Mixed sessions")
        kind, data = event["type"], event["data"]
        if kind == "started":
            if seq != 1 or data != {"mode": mode}:
                raise ValueError("Invalid started event")
        elif kind == "output":
            if not isinstance(data.get("text"), str):
                raise ValueError("Output must be a string")
            output.append(data["text"])
        elif kind == "input-required":
            if mode != "INTERACTIVE" or pending_input is not None:
                raise ValueError("Unexpected input request")
            canonical_uuid(data["requestId"])
            if not isinstance(data.get("prompt"), str):
                raise ValueError("Invalid prompt")
            pending_input = data["requestId"]
        elif kind == "input-accepted":
            if pending_input is None or data != {"requestId": pending_input}:
                raise ValueError("Input does not match pending request")
            pending_input = None
        elif kind == "heartbeat":
            if data != {}:
                raise ValueError("Invalid heartbeat")
        elif kind == "terminal":
            terminal = data
            if data.get("outcome") not in OUTCOMES or not data.get("reason"):
                raise ValueError("Invalid terminal outcome")
            if pending_input is not None and data["outcome"] == "COMPLETED":
                raise ValueError("Completed while awaiting input")
            for diagnostic in data.get("diagnostics", []):
                if not all(isinstance(diagnostic.get(key), str) for key in ("rule", "message")):
                    raise ValueError("Invalid diagnostic text")
                if any(type(diagnostic.get(key)) is not int or diagnostic[key] < 1
                       for key in ("line", "column")):
                    raise ValueError("Invalid diagnostic position")
            if mode == "TEST" and data["outcome"] == "COMPLETED":
                expected = example["definition"]["expectedOutputs"]
                comparison = "PASSED" if output == expected else "FAILED"
                if data.get("comparison") != comparison:
                    raise ValueError("Comparison is not exact")
                if type(data.get("unusedInputs")) is not int or not (
                    0 <= data["unusedInputs"] <= len(example["definition"]["inputs"])
                ):
                    raise ValueError("Invalid unused input count")
            elif "comparison" in data:
                raise ValueError("Comparison without normally completed test")
        else:
            raise ValueError("Unknown event")
    state = terminal["outcome"] if terminal else (
        "UNKNOWN" if example["transportEnded"] else
        "WAITING_INPUT" if pending_input else "RUNNING"
    )
    if state != example["expectedState"]:
        raise ValueError("Unexpected final state")
    return output


def decode_chunks(chunks):
    """Test-only NDJSON decoder, retaining raw bytes across arbitrary boundaries."""
    pending = b""
    events = []
    for chunk in chunks:
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if not line:
                raise ValueError("Empty NDJSON line")
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict):
                raise ValueError("Expected JSON object")
            events.append(event)
    if pending:
        raise ValueError("Truncated NDJSON event")
    return events


class ExecutionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_all_examples_are_consistent(self):
        names = [item["name"] for item in self.contract["examples"]]
        self.assertEqual(len(names), len(set(names)))
        for example in self.contract["examples"]:
            with self.subTest(name=example["name"]):
                validate_example(example)

    def test_ndjson_handles_every_byte_boundary_including_unicode(self):
        for example in self.contract["examples"]:
            encoded = b"".join(
                json.dumps(e, ensure_ascii=False).encode("utf-8") + b"\n"
                for e in example["events"]
            )
            self.assertEqual(decode_chunks([bytes([b]) for b in encoded]), example["events"])

    def test_truncated_or_blank_ndjson_is_not_success(self):
        for chunks in ([b'{"seq":1}'], [b'\n'], [b'[]\n'], [b'\xff\n']):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                decode_chunks(chunks)

    def test_spaces_order_duplicates_and_unicode_are_not_normalized(self):
        expected = ["ñ", "", "ñ"]
        self.assertNotEqual(expected, ["ñ", "ñ", ""])
        self.assertNotEqual(expected, ["ñ", ""])
        self.assertNotEqual(["hola"], ["hola "])
        self.assertNotEqual(["é"], ["e\u0301"])
        self.assertEqual([], [])

    def test_eof_does_not_complete_session(self):
        example = self.contract["examples"][5]
        self.assertEqual(example["expectedState"], "UNKNOWN")
        validate_example(example)

    def test_rejects_reordered_duplicate_and_cross_session_events(self):
        for mutation in ("gap", "boolean", "duplicate", "session", "after-terminal"):
            example = copy.deepcopy(self.contract["examples"][0])
            if mutation == "gap":
                example["events"][1]["seq"] = 3
            elif mutation == "boolean":
                example["events"][0]["seq"] = True
            elif mutation == "duplicate":
                example["events"][1]["seq"] = 1
            elif mutation == "session":
                example["events"][1]["executionId"] = "different-session"
            else:
                example["events"].append(example["events"][-1])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_example(example)

    def test_technical_error_cannot_be_assertion_failure(self):
        example = copy.deepcopy(self.contract["examples"][6])
        example["events"][-1]["data"]["comparison"] = "FAILED"
        with self.assertRaises(ValueError):
            validate_example(example)

    def test_test_mode_cannot_wait_for_browser_input(self):
        example = copy.deepcopy(self.contract["examples"][2])
        example["mode"] = "TEST"
        example["definition"] = {"inputs": [], "expectedOutputs": []}
        example["events"][0]["data"]["mode"] = "TEST"
        with self.assertRaises(ValueError):
            validate_example(example)

    def test_definitions_require_string_arrays_and_no_owner(self):
        for mutation in ("missing", "wrong-type", "null-item", "owner"):
            example = copy.deepcopy(self.contract["examples"][0])
            if mutation == "missing":
                del example["definition"]["inputs"]
            elif mutation == "wrong-type":
                example["definition"]["inputs"] = "not-an-array"
            elif mutation == "null-item":
                example["definition"]["inputs"] = [None]
            else:
                example["definition"]["ownerId"] = "body-actor"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_example(example)

    def test_input_acceptance_must_match_request(self):
        example = copy.deepcopy(self.contract["examples"][2])
        example["events"][3]["data"]["requestId"] = "660e8400-e29b-41d4-a716-446655440099"
        with self.assertRaises(ValueError):
            validate_example(example)

    def test_diagnostic_positions_start_at_one(self):
        for position in (0, -1, True):
            example = copy.deepcopy(self.contract["examples"][7])
            example["events"][-1]["data"]["diagnostics"][0]["line"] = position
            with self.subTest(position=position), self.assertRaises(ValueError):
                validate_example(example)

    def test_problem_examples_have_stable_types_and_no_credentials(self):
        for problem in self.contract["problemExamples"]:
            self.assertTrue(problem["type"].startswith("urn:snippets:problem:"))
            self.assertIn(problem["status"], (403, 409))
            self.assertTrue(problem["instance"].startswith("/executions/"))
            self.assertTrue(all(isinstance(problem[key], str) for key in ("title", "detail")))
            self.assertNotIn("?", problem["instance"])

    def test_snapshot_change_cannot_be_current(self):
        for example in self.contract["snapshotExamples"]:
            self.assertEqual(example["executed"] == example["current"], example["expectedCurrent"])

    def test_approved_limits_match_agreement(self):
        expected = {
            "activePerActor": 1, "activeGlobal": 4, "totalSeconds": 120,
            "inputWaitSeconds": 30, "reconnectSeconds": 15,
            "codeBytes": 1048576, "inputBytes": 8192, "outputBytes": 1048576,
            "bufferEvents": 256, "bufferBytes": 262144,
            "terminalRetentionSeconds": 60,
        }
        self.assertEqual(self.contract["approvedDefaults"], expected)
        self.assertEqual(self.contract["mediaType"], "application/x-ndjson")
        self.assertEqual(self.contract["status"], "approved-by-thiago-for-team-review")

    def test_heartbeat_is_below_transport_inactivity_timeout(self):
        self.assertEqual(self.contract["protocolDefaults"]["heartbeatSeconds"], 10)
        self.assertLess(self.contract["protocolDefaults"]["heartbeatSeconds"], 60)

    def test_http_examples_keep_public_and_internal_requests_separate(self):
        examples = self.contract["httpExamples"]
        self.assertEqual(examples["startInteractive"]["request"], {})
        self.assertEqual(examples["startInteractive"]["status"], 201)
        self.assertEqual(set(examples["internalStartTest"]["request"]), {
            "code", "version", "mode", "inputs",
        })
        self.assertEqual(examples["emptyList"]["response"], {"items": []})
        self.assertEqual(examples["cancel"]["status"], 202)
        self.assertEqual(examples["cancel"]["response"]["state"], "CANCELLING")
        created = examples["createTest"]
        self.assertEqual(created["status"], 201)
        canonical_uuid(created["response"]["id"])
        canonical_uuid(created["response"]["snippetId"])
        self.assertEqual(created["request"]["inputs"], created["response"]["inputs"])
        self.assertEqual(created["request"]["expectedOutputs"], created["response"]["expectedOutputs"])

    def test_public_descriptor_does_not_expose_private_references(self):
        descriptor = self.contract["httpExamples"]["startInteractive"]["response"]
        self.assertEqual(set(descriptor), {
            "executionId", "snippetId", "mode", "state", "lastSeq", "snapshot", "limits",
        })
        canonical_uuid(descriptor["executionId"])
        canonical_uuid(descriptor["snippetId"])
        self.assertEqual(descriptor["limits"], self.contract["approvedDefaults"])
        self.assertEqual(set(descriptor["snapshot"]), {"language", "version", "codeHash"})

    def test_hash_vectors_fix_serialization_and_utf8(self):
        for vector in self.contract["hashVectors"]:
            wire = json.dumps(vector["value"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.assertEqual("sha256-v1:" + hashlib.sha256(wire).hexdigest(), vector["hash"])

    def test_terminal_fixture_coverage_includes_cancellation_and_restart(self):
        outcomes = {
            event["data"]["outcome"]
            for example in self.contract["examples"]
            for event in example["events"] if event["type"] == "terminal"
        }
        self.assertEqual(outcomes, OUTCOMES)

    def test_unused_inputs_are_reported_without_forcing_test_failure(self):
        example = next(e for e in self.contract["examples"] if e["name"] == "unused-inputs-do-not-fail-expectations")
        validate_example(example)
        self.assertEqual(example["events"][-1]["data"]["unusedInputs"], 1)
        self.assertEqual(example["events"][-1]["data"]["comparison"], "PASSED")


if __name__ == "__main__":
    unittest.main()
