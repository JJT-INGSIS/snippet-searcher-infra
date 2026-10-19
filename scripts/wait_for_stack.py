"""Wait for the desired service versions, not just a successful stack submission."""
import json
import os
import subprocess
import sys
import time

from stack_release import STACK_SERVICES as SERVICES, DATABASE_SERVICES, VARIABLES



def docker_json(*arguments):
    return json.loads(subprocess.check_output(["docker", *arguments], text=True, timeout=30))


def converged(stack):
    expected = dict(zip(SERVICES[:3], (os.environ[name] for name in VARIABLES)))
    expected.update({name: os.environ['POSTGRES_IMAGE'] for name in DATABASE_SERVICES})
    for name in SERVICES:
        service = docker_json("service", "inspect", f"{stack}_{name}")[0]
        state = service.get("UpdateStatus", {}).get("State", "")
        # A rollback toward the expected digest is still converging. The digest
        # check below continues to reject a rollback while verifying a candidate.
        if state in {"paused", "rollback_paused"}:
            raise RuntimeError(f"{name}: actualización fallida ({state})")
        desired = service["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"]
        if name in expected and desired != expected[name]:
            raise RuntimeError(f"{name}: Swarm no mantiene el digest solicitado (posible rollback)")
        if "@sha256:" not in desired:
            raise RuntimeError(f"{name}: el manager no pudo resolver la imagen a un digest")
        task_ids = subprocess.check_output([
            "docker", "service", "ps", "--filter", "desired-state=running",
            "--no-trunc", "--quiet", f"{stack}_{name}",
        ], text=True, timeout=30).split()
        if not task_ids:
            return False
        tasks = docker_json("inspect", *task_ids)
        replicas = service["Spec"]["Mode"]["Replicated"]["Replicas"]
        running = [task for task in tasks if task["Status"]["State"] == "running"
                   and task["Spec"]["ContainerSpec"]["Image"] == desired]
        if len(running) != replicas or state not in {"", "completed", "rollback_completed"}:
            return False
    return True


def main():
    deadline = time.monotonic() + 600
    stable_since = None
    while time.monotonic() < deadline:
        if converged(sys.argv[1]):
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= 60:
                print("Las cinco instancias ejecutan las imágenes esperadas y permanecieron estables 60s.")
                return
        else:
            stable_since = None
        time.sleep(5)
    raise RuntimeError("El stack no convergió en 10 minutos")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
