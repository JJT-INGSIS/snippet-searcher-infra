"""Manual bootstrap/reapply for one environment; shared locked release contract for CD."""
import argparse
import fcntl
import json
import os
import pwd
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from stack_release import SERVICES, DATABASE_SERVICES, write_record, validate_manifest, select_release, update_service, validate_promotion

ROOT = Path(__file__).resolve().parent.parent

def docker_json(*arguments):
    return json.loads(subprocess.check_output(["docker", *arguments], text=True, timeout=30))


def preflight(manifest, environment):
    info = docker_json("info", "--format", "{{json .}}")
    if info.get("Name") != f"vm-snippet-{manifest['environment']}" or not info.get("Swarm", {}).get("ControlAvailable"):
        raise ValueError("Conectarse al manager del ambiente correcto; no desplegar desde otro Docker context")
    nodes = subprocess.check_output(["docker", "node", "ls", "-q"], text=True, timeout=30).split()
    if len(nodes) != 1:
        raise ValueError("Se requiere el Swarm independiente de un nodo")
    node = docker_json("node", "inspect", nodes[0])[0]
    if node["Spec"].get("Labels", {}).get("database") != "true" or node["Spec"].get("Availability") != "active":
        raise ValueError("El nodo debe estar active y tener database=true; ejecutar prepare_swarm_vm.sh")
    for secret in ("snippets_db_password", "permissions_db_password"):
        docker_json("secret", "inspect", secret)
    subprocess.run(["docker", "stack", "config", "-c", str(ROOT / "swarm/stack.yaml")],
                   check=True, env=environment, stdout=subprocess.DEVNULL, timeout=30)
    # Pull antes de modificar el stack: detecta falta de permiso, digest ausente
    # o arquitectura incompatible sin reconstruir nada en la VM.
    for image in (*manifest["images"].values(), manifest["database_image"]):
        subprocess.run(["docker", "pull", "--platform", "linux/amd64", image], check=True, timeout=600)
        pulled = docker_json("image", "inspect", image)[0]
        if pulled.get("Architecture") != "amd64" or pulled.get("Os") != "linux":
            raise ValueError(f"Arquitectura incorrecta: {image}")
    print("Preflight correcto: manager, secretos, stack e imágenes linux/amd64.", flush=True)


def verify_database_images(image, stack):
    for service in DATABASE_SERVICES:
        current = docker_json("service", "inspect", f"{stack}_{service}")[0]
        if current["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"] != image:
            raise RuntimeError(f"{service}: no ejecuta la versión de PostgreSQL solicitada")


def execute(manifest, environment, state):
    stack = f"snippet-searcher-{manifest['environment']}"
    preflight(manifest, environment)
    subprocess.run(["docker", "stack", "deploy", "--with-registry-auth", "--resolve-image", "always",
                    "-c", str(ROOT / "swarm/stack.yaml"), stack], check=True, env=environment, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "scripts/wait_for_stack.py"), stack],
                   check=True, env=environment, timeout=700)
    verify_database_images(manifest["database_image"], stack)
    print("Convergencia correcta. Comprobando SQL y HTTP desde la red del stack.", flush=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_stack.py"), stack],
                   check=True, env=environment, timeout=300)
    record = {**manifest, "run": "manual", "deployed_at": datetime.now(timezone.utc).isoformat(),
              "checks": {"convergence": "passed", "sql_and_internal_http": "passed"}}
    history = state / "history"
    history.mkdir(mode=0o700, exist_ok=True)
    write_record(history / f"{uuid4().hex}.json", record)
    write_record(state / "release.json", record)
    print(f"Release confirmado: {state / 'release.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "preflight", "deploy"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument('--service', choices=SERVICES, help='Actualizar sólo esta aplicación; conservar las otras referencias')
    parser.add_argument('--dev-record', type=Path, help='Registro confirmado de dev para promocionar los mismos digests')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    selected = validate_manifest(manifest)
    if args.mode == "check":
        print(json.dumps(selected, indent=2))
        return
    environment = {**os.environ, **selected}
    if args.mode == "preflight":
        preflight(manifest, environment)
        return
    owner = pwd.getpwnam(os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name)
    state = Path(owner.pw_dir) / f".local/state/snippet-searcher/{manifest['environment']}"
    # Crear cada directorio por separado: mkdir(parents=True) bajo sudo dejaría
    # .local/state a nombre de root en una cuenta recién creada.
    for path in (state.parents[2], state.parents[1], state.parent, state):
        if not path.exists():
            path.mkdir(mode=0o700)
            if os.geteuid() == 0:
                os.chown(path, owner.pw_uid, owner.pw_gid)
    # El mismo lock que usa el borrador de CD, para evitar despliegues simultáneos.
    with (state / "deploy.lock").open("a") as lock:
        deadline = time.monotonic() + 1800
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timeout esperando el bloqueo del ambiente")
                time.sleep(1)
        try:
            if (state / 'pending.json').exists():
                raise RuntimeError('CD tiene una operación pendiente; reconciliarla antes de reaplicar infra')
            previous_path = state / "release.json"
            previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
            selected_manifest = select_release(manifest, previous)
            if args.service:
                if previous is None:
                    raise ValueError("Actualizar un servicio requiere bootstrap previo")
                selected_manifest = update_service(selected_manifest, args.service, manifest['images'][args.service])
            if selected_manifest['environment'] == 'prod':
                if args.dev_record is None:
                    raise ValueError('Prod requiere el registro confirmado de dev')
                dev_record = json.loads(args.dev_record.read_text())
                validate_promotion(selected_manifest, dev_record)
            execute(selected_manifest, {**os.environ, **validate_manifest(selected_manifest)}, state)
        finally:
            # sudo no debe dejar el registro inaccesible para azureuser/CD.
            if os.geteuid() == 0:
                for path in (state.parent, state, *state.rglob("*")):
                    os.chown(path, owner.pw_uid, owner.pw_gid)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as error:
        print(f"FAIL: {error}. Release no confirmado; revisar el stack antes de reintentar.", file=sys.stderr)
        sys.exit(1)
