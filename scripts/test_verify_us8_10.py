import unittest

from verify_us8_10 import (
    LARGE_LINE,
    LARGE_LINES,
    Received,
    Reply,
    VerificationError,
    actor,
    kinds,
    large_output_code,
    outputs,
    problem,
    terminal_of,
)

MIB = 1024 * 1024


def received(*events: dict) -> list:
    return [Received(float(index), event) for index, event in enumerate(events)]


class VerifyUs810Test(unittest.TestCase):
    def test_problem_keeps_only_the_contract_name(self):
        reply = Reply(409, {"type": "urn:snippets:problem:input-conflict"})
        self.assertEqual(problem(reply), "input-conflict")
        self.assertEqual(problem(Reply(404, None)), "")

    def test_events_are_summarized_in_arrival_order(self):
        stream = received(
            {"type": "started", "data": {"mode": "INTERACTIVE"}},
            {"type": "output", "data": {"text": ""}},
            {"type": "heartbeat", "data": {}},
            {"type": "output", "data": {"text": "ñ"}},
            {"type": "terminal", "data": {"outcome": "COMPLETED", "reason": "program-completed"}},
        )
        self.assertEqual(kinds(stream), ["started", "output", "heartbeat", "output", "terminal"])
        self.assertEqual(outputs(stream), ["", "ñ"])
        self.assertEqual(terminal_of(stream)["outcome"], "COMPLETED")

    def test_a_stream_without_terminal_is_a_failure(self):
        with self.assertRaises(VerificationError):
            terminal_of(received({"type": "started", "data": {"mode": "TEST"}}))
        with self.assertRaises(VerificationError):
            terminal_of([])

    def test_large_output_exceeds_the_limit_with_events_that_fit_the_buffer(self):
        code = large_output_code()
        self.assertLess(len(code.encode()), MIB)
        self.assertGreater(LARGE_LINE * LARGE_LINES, MIB)
        self.assertLess(LARGE_LINE, 256 * 1024)
        self.assertEqual(code.count("println(texto);"), LARGE_LINES)

    def test_generated_actors_are_unique_and_safe_for_queries(self):
        first, second = actor("owner"), actor("owner")
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^sni53-[a-z0-9-]+$")


if __name__ == "__main__":
    unittest.main()