import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observability/runtime"))

import swarm_sample

NOW = datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)
NAMESPACE = "snippet-searcher-dev"
NGINX_IMAGE = "nginx:1.30.6-alpine@sha256:" + "a" * 64
SNIPPETS_IMAGE = "ghcr.io/jjt-ingsis/snippets-service@sha256:" + "b" * 64
OLDER_SNIPPETS_IMAGE = "ghcr.io/jjt-ingsis/snippets-service@sha256:" + "c" * 64
OOM_EXIT = 137
LONG_ERROR = "task: non-zero exit (1) " + "x" * 500
FIELDS = {"environment", "service", "image", "expectedImage", "imageState", "running", "desired",
          "failedTasks", "lastError", "lastExitCode", "oomKilled"}


def stamp(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def service(identifier, name, image, replicas=1):
    return {"ID": identifier, "Spec": {"Name": NAMESPACE + "_" + name, "Mode": {"Replicated": {"Replicas": replicas}},
                                      "TaskTemplate": {"ContainerSpec": {"Image": image}}}}


def task(service_id, state, minutes_ago, exit_code=None, error="", desired="running"):
    status = {"State": state, "Timestamp": stamp(minutes_ago), "Err": error}
    if exit_code is not None:
        status["ContainerStatus"] = {"ExitCode": exit_code}
    return {"ID": service_id + "-" + state + str(minutes_ago), "ServiceID": service_id,
            "DesiredState": desired, "Status": status}


class FakeDocker:
    def __init__(self, services, tasks):
        self.services = services
        self.tasks = tasks
        self.calls = []

    def __call__(self, arguments):
        self.calls.append(arguments)
        if arguments[:2] == ["service", "ls"]:
            return "\n".join(item["ID"] for item in self.services)
        if arguments[:2] == ["service", "inspect"]:
            return json.dumps(self.services)
        if arguments[:2] == ["service", "ps"]:
            return "\n".join(item["ID"] for item in self.tasks)
        if arguments[:1] == ["inspect"]:
            return json.dumps(self.tasks)
        raise AssertionError(arguments)


def release(snippets=SNIPPETS_IMAGE):
    return {"images": {"snippets-service": snippets}, "database_image": "postgres@sha256:" + "d" * 64,
            "infrastructure": {"nginx": {"image": NGINX_IMAGE}}}


def collect(docker, known_release):
    rows = swarm_sample.collect(docker, known_release, "dev", NOW)
    return {row["service"]: row for row in rows}


class SwarmSampleTests(unittest.TestCase):
    def healthy(self):
        return FakeDocker([service("s1", "snippets-service", SNIPPETS_IMAGE), service("s2", "nginx", NGINX_IMAGE)],
                          [task("s1", "running", 30), task("s2", "running", 30)])

    def test_reports_replicas_and_matching_images_without_other_fields(self):
        rows = collect(self.healthy(), release())
        self.assertEqual(set(rows), {"snippets-service", "nginx"})
        for row in rows.values():
            self.assertEqual(set(row), FIELDS)
            self.assertEqual((row["running"], row["desired"]), (1, 1))
            self.assertEqual(row["imageState"], "match")
            self.assertEqual((row["failedTasks"], row["lastError"], row["lastExitCode"], row["oomKilled"]),
                             (0, "", 0, 0))

    def test_running_image_different_from_the_confirmed_release_is_a_mismatch(self):
        row = collect(self.healthy(), release(OLDER_SNIPPETS_IMAGE))["snippets-service"]
        self.assertEqual(row["imageState"], "mismatch")
        self.assertEqual(row["expectedImage"], OLDER_SNIPPETS_IMAGE)
        self.assertEqual(row["image"], SNIPPETS_IMAGE)

    def test_unknown_release_or_service_outside_it_is_unknown_not_a_match(self):
        self.assertEqual(collect(self.healthy(), None)["nginx"]["imageState"], "unknown")
        docker = FakeDocker([service("s3", "certbot", "certbot/certbot@sha256:" + "e" * 64, replicas=0)], [])
        row = collect(docker, release())["certbot"]
        self.assertEqual((row["imageState"], row["expectedImage"]), ("unknown", ""))

    def test_recent_oom_failure_reports_exit_code_and_last_error(self):
        docker = FakeDocker([service("s1", "snippets-service", SNIPPETS_IMAGE)],
                            [task("s1", "running", 1),
                             task("s1", "failed", 2, OOM_EXIT, "task: non-zero exit (137)", "shutdown"),
                             task("s1", "failed", 6, 1, "task: non-zero exit (1)", "shutdown")])
        row = collect(docker, release())["snippets-service"]
        self.assertEqual((row["failedTasks"], row["lastExitCode"], row["oomKilled"]), (2, OOM_EXIT, 1))
        self.assertEqual(row["lastError"], "task: non-zero exit (137)")
        self.assertEqual(row["running"], 1)

    def test_failures_outside_the_window_are_ignored(self):
        old = swarm_sample.FAILURE_WINDOW_MINUTES + 1
        docker = FakeDocker([service("s1", "snippets-service", SNIPPETS_IMAGE)],
                            [task("s1", "running", old), task("s1", "failed", old, OOM_EXIT, "x", "shutdown")])
        row = collect(docker, release())["snippets-service"]
        self.assertEqual((row["failedTasks"], row["oomKilled"]), (0, 0))

    def test_rejected_task_without_container_counts_and_error_is_bounded(self):
        docker = FakeDocker([service("s1", "snippets-service", SNIPPETS_IMAGE)],
                            [task("s1", "rejected", 1, error=LONG_ERROR, desired="shutdown")])
        row = collect(docker, release())["snippets-service"]
        self.assertEqual((row["failedTasks"], row["lastExitCode"], row["running"]), (1, 0, 0))
        self.assertEqual(len(row["lastError"]), swarm_sample.ERROR_LIMIT)

    def test_only_the_environment_stack_is_listed(self):
        docker = self.healthy()
        collect(docker, release())
        self.assertIn("label=com.docker.stack.namespace=" + NAMESPACE, docker.calls[0])

    def test_unexpected_names_fail_instead_of_emitting(self):
        docker = FakeDocker([service("s1", 'snippets"service', SNIPPETS_IMAGE)], [])
        with self.assertRaises(ValueError):
            swarm_sample.collect(docker, release(), "dev", NOW)

    def test_unsupported_environment_fails(self):
        with self.assertRaises(ValueError):
            swarm_sample.collect(self.healthy(), release(), "staging", NOW)

    def test_unreadable_or_invalid_release_file_is_unknown(self):
        self.assertIsNone(swarm_sample.read_release(Path("/nonexistent/release.json")))


if __name__ == "__main__":
    unittest.main()
