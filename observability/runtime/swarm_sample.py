import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stack_release import expected_images

DOCKER = "/opt/runtime/docker"
ENVIRONMENTS = ("dev", "prod")
FAILURE_WINDOW_MINUTES = 10
ERROR_LIMIT = 200
OOM_EXIT = 137
COMMAND_SECONDS = 8
FAILED_STATES = ("failed", "rejected")
MICROSECOND_DIGITS = 6
NAME = re.compile(r"[a-zA-Z0-9_.-]+")
IMAGE = re.compile(r"[a-zA-Z0-9_./:@-]+")
DIGEST = re.compile(r"@(sha256:[a-f0-9]{64})$")
TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z")


def namespace(environment):
    if environment not in ENVIRONMENTS:
        raise ValueError("Unsupported environment")
    return "snippet-searcher-" + environment


def identifiers(output):
    return [line.strip() for line in output.splitlines() if line.strip()]


def moment(value):
    found = TIMESTAMP.fullmatch(value)
    if found is None:
        raise ValueError("Unexpected task timestamp")
    fraction = (found.group(2) or "0")[:MICROSECOND_DIGITS].ljust(MICROSECOND_DIGITS, "0")
    parsed = datetime.strptime(found.group(1), "%Y-%m-%dT%H:%M:%S")
    return parsed.replace(microsecond=int(fraction), tzinfo=timezone.utc)


def same_image(expected, actual):
    wanted, running = DIGEST.search(expected), DIGEST.search(actual)
    if wanted and running:
        return wanted.group(1) == running.group(1)
    return expected == actual


def image_state(expected, actual):
    if not expected:
        return "unknown"
    return "match" if same_image(expected, actual) else "mismatch"


def exit_code(task):
    return task.get("Status", {}).get("ContainerStatus", {}).get("ExitCode") or 0


def recent_failures(tasks, now):
    since = now - timedelta(minutes=FAILURE_WINDOW_MINUTES)
    failed = [task for task in tasks
              if task["Status"]["State"] in FAILED_STATES and moment(task["Status"]["Timestamp"]) >= since]
    return sorted(failed, key=lambda task: moment(task["Status"]["Timestamp"]), reverse=True)


def running(tasks):
    return len([task for task in tasks if task["Status"]["State"] == "running" and task["DesiredState"] == "running"])


def known_images(release):
    try:
        return expected_images(release) if release else {}
    except (KeyError, TypeError, AttributeError):
        return {}


def row(service, tasks, expected, environment, now):
    prefix = namespace(environment) + "_"
    full_name = service["Spec"]["Name"]
    image = service["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"]
    if not full_name.startswith(prefix) or not NAME.fullmatch(full_name) or not IMAGE.fullmatch(image):
        raise ValueError("Unexpected service name or image")
    name = full_name.removeprefix(prefix)
    own = [task for task in tasks if task["ServiceID"] == service["ID"]]
    failures = recent_failures(own, now)
    last = failures[0] if failures else {}
    wanted = expected.get(name, "")
    return {
        "environment": environment,
        "service": name,
        "image": image,
        "expectedImage": wanted,
        "imageState": image_state(wanted, image),
        "running": running(own),
        "desired": service["Spec"].get("Mode", {}).get("Replicated", {}).get("Replicas", 0),
        "failedTasks": len(failures),
        "lastError": last.get("Status", {}).get("Err", "")[:ERROR_LIMIT],
        "lastExitCode": exit_code(last),
        "oomKilled": int(any(exit_code(task) == OOM_EXIT for task in failures)),
    }


def collect(run, release, environment, now):
    label = "label=com.docker.stack.namespace=" + namespace(environment)
    service_ids = identifiers(run(["service", "ls", "--filter", label, "-q"]))
    if not service_ids:
        raise ValueError("No services in the environment stack")
    services = json.loads(run(["service", "inspect", *service_ids]))
    task_ids = identifiers(run(["service", "ps", "-q", "--no-trunc", *service_ids]))
    tasks = json.loads(run(["inspect", "--type", "task", *task_ids])) if task_ids else []
    expected = known_images(release)
    return [row(service, tasks, expected, environment, now) for service in services]


def read_release(path):
    try:
        release = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return release if isinstance(release, dict) else None


def docker(arguments):
    return subprocess.run([DOCKER, *arguments], check=True, capture_output=True, text=True,
                          timeout=COMMAND_SECONDS).stdout


def main():
    parser = argparse.ArgumentParser(description="Swarm tasks, failures and expected images, without secrets")
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--release", type=Path, required=True)
    arguments = parser.parse_args()
    rows = collect(docker, read_release(arguments.release), arguments.environment, datetime.now(timezone.utc))
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
