"""Manual bootstrap/reapply for one environment; shared locked release contract for CD."""
import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from stack_release import (APPLICATIONS, CERTIFICATES, DATABASE_SERVICES, database_image, expected_images, infrastructure,
                           nginx_files, upgrade_release, write_record, validate_manifest, select_release, update_service,
                           validate_promotion)

ROOT = Path(__file__).resolve().parent.parent


def plan_release(previous, hostname=None, install_assets=False, config_version=1, ui_image=None, ui_actor=None, tls=False):
    """Read-only candidate, from actual references rather than historical YAML digests."""
    from validate_asset_config import render
    from validate_nginx_config import NGINX_IMAGE
    if tls and not hostname:
        raise ValueError('TLS requiere --nginx-host explícito')
    planned = upgrade_release(previous)
    planned.pop('checks', None)
    if hostname:
        configs = {}
        old = infrastructure(previous).get('nginx', {}).get('configs', {})
        for key, file in nginx_files(tls).items():
            digest = hashlib.sha256((ROOT / file).read_bytes()).hexdigest()
            configs[key] = dict(old[key]) if key in old and old[key]['sha256'] == digest else {
                'name': f'snippet-searcher-{previous["environment"]}_{key}_v{config_version}', 'sha256': digest}
        planned['infrastructure']['nginx'] = {'image': NGINX_IMAGE, 'hostname': hostname, 'tls': tls, 'configs': configs}
    if install_assets:
        data = render(['swarm/stack.yaml', 'swarm/stack.asset.yaml'], {**os.environ, **validate_manifest(previous)})
        for name in ('asset-service', 'azurite'):
            planned['infrastructure'].setdefault(name, {'image': data['services'][name]['image']})
    if ui_image:
        if 'ui' in previous['images'] and previous['images']['ui'] != ui_image:
            raise ValueError('UI ya instalada: actualizar su imagen mediante CD independiente')
        planned['images']['ui'] = ui_image
    if ui_actor is not None:
        planned['ui'] = {'dev_actor': ui_actor}
    validate_manifest(planned)
    return planned

def require_certificate(manifest):
    proxy = infrastructure(manifest).get('nginx')
    if not proxy or not proxy['tls']:
        return
    live = Path(CERTIFICATES.format(environment=manifest['environment'])) / 'live' / proxy['hostname']
    if not all((live / name).is_file() for name in ('fullchain.pem', 'privkey.pem')):
        raise ValueError('TLS requiere el certificado emitido para el hostname; emitirlo antes de publicar 443')


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
    if 'azurite' in infrastructure(manifest) and node['Spec'].get('Labels', {}).get('asset_storage') != 'true':
        raise ValueError('Azurite requiere el nodo con volumen original y asset_storage=true; no etiquetar automáticamente')
    for secret in ("snippets_db_password", "permissions_db_password"):
        docker_json("secret", "inspect", secret)
    require_certificate(manifest)
    if manifest.get('schema_version') == 2:
        from stack_runtime import render_release, require_configs, validate_rendered
        validate_rendered(render_release(manifest))
        require_configs(manifest, docker_json)
    else:
        subprocess.run(["docker", "stack", "config", "-c", str(ROOT / "swarm/stack.yaml")],
                       check=True, env=environment, stdout=subprocess.DEVNULL, timeout=30)
    # Pull antes de modificar el stack: detecta falta de permiso, digest ausente
    # o arquitectura incompatible sin reconstruir nada en la VM.
    for image in set(expected_images(manifest).values()):
        subprocess.run(["docker", "pull", "--platform", "linux/amd64", image], check=True, timeout=600)
        pulled = docker_json("image", "inspect", image)[0]
        if pulled.get("Architecture") != "amd64" or pulled.get("Os") != "linux":
            raise ValueError(f"Arquitectura incorrecta: {image}")
    print("Preflight correcto: manager, secretos, stack e imágenes linux/amd64.", flush=True)


def finish_infrastructure(state, identity, operation, release, outcome):
    confirmed = {**upgrade_release(release), 'deployed_at': datetime.now(timezone.utc).isoformat(),
                 'checks': {'convergence': 'passed', 'sql_and_internal_http': 'passed'}}
    receipt = {'kind': 'infrastructure', 'operation': identity, 'outcome': outcome,
               'verified_at': confirmed['deployed_at']}
    operation = {**operation, 'state': outcome, 'receipt': receipt, 'confirmed-release': confirmed}
    write_record(state / 'operations' / f'{identity}.json', operation)
    history = state / 'history'
    history.mkdir(mode=0o700, exist_ok=True)
    write_record(history / f'{identity}.json', confirmed)
    write_record(state / 'release.json', confirmed)
    (state / 'pending.json').unlink(missing_ok=True)
    return receipt


def reconcile_infrastructure(state, swarm):
    identity = json.loads((state / 'pending.json').read_text())['operation']
    if not isinstance(identity, str) or not re.fullmatch(r'infra-[a-f0-9]{32}', identity):
        raise ValueError('Identidad de operación de infraestructura inválida')
    operation = json.loads((state / 'operations' / f'{identity}.json').read_text())
    previous, candidate = operation['previous'], operation['candidate']
    validate_manifest(previous)
    validate_manifest(candidate)
    swarm.check_manager()
    if operation.get('kind') != 'infrastructure' or previous['environment'] != candidate['environment'] \
            or candidate['environment'] != swarm.environment:
        raise ValueError('Operación de infraestructura de otro ambiente o tipo')
    actual = swarm.images()
    stable = {**previous['images'], **{name: database_image(previous) for name in DATABASE_SERVICES}}
    for name, image in stable.items():
        if actual.get(name) != image:
            raise ValueError('Una aplicación/base cambió durante infra; no sobrescribirla')
    allowed = set(expected_images(previous)) | set(expected_images(candidate))
    if set(actual) - allowed or any(actual[name] not in {expected_images(previous).get(name),
            expected_images(candidate).get(name)} for name in actual):
        raise ValueError('Referencia de infraestructura inesperada; intervención requerida')
    if operation['state'] in ('verified', 'recovered'):
        confirmed = operation['confirmed-release']
        if actual != expected_images(confirmed):
            raise ValueError('El diario final no coincide con Swarm')
        swarm.verify(confirmed)
        return finish_infrastructure(state, identity, operation, confirmed, operation['state'])
    if actual == expected_images(candidate):
        try:
            swarm.verify(candidate)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
            pass
        else:
            return finish_infrastructure(state, identity, operation, candidate, 'verified')
    if actual == expected_images(previous):
        try:
            swarm.verify(previous)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
            pass
        else:
            return finish_infrastructure(state, identity, operation, previous, 'recovered')
    # Recover only known infra changes, never downgrade an application or database.
    swarm.require_recoverable_infrastructure(previous, candidate)
    try:
        swarm.apply_infrastructure(previous)
        extras = set(expected_images(candidate)) - set(expected_images(previous))
        swarm.remove_components(extras & set(swarm.images()))
        if swarm.images() != expected_images(previous):
            raise ValueError('La recuperación dejó referencias inesperadas')
        swarm.verify(previous)
        return finish_infrastructure(state, identity, operation, previous, 'recovered')
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        write_record(state / 'release.json', {**previous, 'checks': {'recovery': 'failed'}})
        write_record(state / 'operations' / f'{identity}.json', {**operation, 'state': 'recovery_failed'})
        raise RuntimeError('Recuperación de infraestructura fallida; diario pendiente conservado') from None


def deploy_infrastructure(state, requested, swarm, gate):
    from deploy_service import reconcile, require_images
    recovered_operation = reconcile(state, swarm)
    if recovered_operation and recovered_operation['outcome'] != 'verified':
        raise RuntimeError('La operación interrumpida fue recuperada; revisar antes de solicitar otro cambio')
    previous = json.loads((state / 'release.json').read_text())
    validate_manifest(previous)
    if previous.get('checks') != {'convergence': 'passed', 'sql_and_internal_http': 'passed'}:
        raise ValueError('La base anterior no está confirmada; reconciliar antes del corte')
    candidate = select_release(requested, previous, change_infrastructure=True)
    if recovered_operation and candidate == previous:
        return recovered_operation  # Reconciliation already verified this exact state.
    require_images(swarm, previous)
    swarm.verify(previous)
    preflight(candidate, {**os.environ, **validate_manifest(candidate)})
    if candidate['environment'] == 'prod':
        from github_cd import GitHub, select_evidence, require_authorized_head
        for name in set(candidate['images']) - set(previous['images']):
            image = candidate['images'][name]
            labels = docker_json('image', 'inspect', image)[0]['Config'].get('Labels', {})
            tree = labels.get('io.jjt.source-tree', '')
            if not re.fullmatch(r'[a-f0-9]{40}', tree):
                raise ValueError('Nueva aplicación prod sin Git tree de origen')
            api = GitHub(APPLICATIONS[name]['repository'], os.environ.get('GH_TOKEN', ''))
            evidence = select_evidence(api, name, tree, image)
            target = api.request('/branches/main')['commit']['sha']
            require_authorized_head(api, {**evidence, 'environment': 'prod', 'target-sha': target})
    gate(candidate['environment'])  # Latest callers and active runs, under the shared lock.
    identity = 'infra-' + uuid4().hex
    operation = {'kind': 'infrastructure', 'state': 'updating', 'previous': upgrade_release(previous),
                 'candidate': candidate, 'started_at': datetime.now(timezone.utc).isoformat()}
    (state / 'operations').mkdir(mode=0o700, exist_ok=True)
    write_record(state / 'operations' / f'{identity}.json', operation)
    write_record(state / 'pending.json', {'operation': identity})
    # Fence old Actions BEFORE applying any expanded resource; never restore v1 on rollback.
    write_record(state / 'release.json', upgrade_release(previous))
    try:
        swarm.apply_infrastructure(candidate)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        pass  # Docker may have accepted the request before a transport timeout.
    receipt = reconcile_infrastructure(state, swarm)
    if receipt['outcome'] != 'verified':
        raise RuntimeError('Cambio de infraestructura falló y fue recuperado; operación en rojo')
    return receipt


def verify_database_images(image, stack):
    for service in DATABASE_SERVICES:
        current = docker_json("service", "inspect", f"{stack}_{service}")[0]
        if current["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"] != image:
            raise RuntimeError(f"{service}: no ejecuta la versión de PostgreSQL solicitada")


def execute(manifest, environment, state):
    stack = f"snippet-searcher-{manifest['environment']}"
    preflight(manifest, environment)
    if manifest.get('schema_version') == 2:
        from stack_runtime import apply_release
        apply_release(manifest, docker_json)
    else:
        subprocess.run(["docker", "stack", "deploy", "--with-registry-auth", "--resolve-image", "always",
                        "-c", str(ROOT / "swarm/stack.yaml"), stack], check=True, env=environment, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "scripts/wait_for_stack.py"), stack],
                   check=True, env=environment, timeout=700)
    verify_database_images(database_image(manifest), stack)
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
    parser.add_argument("mode", choices=("plan", "check", "preflight", "deploy"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument('--service', choices=APPLICATIONS, help='Prueba manual de actualización dev; producción usa CD')
    parser.add_argument('--infrastructure', action='store_true', help='Cambio explícito de infraestructura, con recuperación')
    parser.add_argument('--nginx-host', help='Sólo plan: hostname explícito del proxy')
    parser.add_argument('--tls', action='store_true', help='Sólo plan: publicar 443 con el certificado ya emitido')
    parser.add_argument('--install-assets', action='store_true', help='Sólo plan: instalar runtime sin activar proveedor')
    parser.add_argument('--config-version', type=int, default=1, help='Sólo plan: revisión para configs cuyo contenido cambió')
    parser.add_argument('--ui-image', help='Sólo plan: incorporar UI por su digest real; no actualiza una UI instalada')
    parser.add_argument('--ui-dev-actor', help='Sólo plan: actor público explícito de dev; vacío deshabilita identidad')
    parser.add_argument('--dev-record', type=Path, help='Registro confirmado de dev para promocionar los mismos digests')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    selected = validate_manifest(manifest)
    if args.mode == 'plan':
        if args.config_version < 1:
            raise ValueError('La revisión de config debe ser positiva')
        print(json.dumps(plan_release(manifest, args.nginx_host, args.install_assets, args.config_version,
                                      args.ui_image, args.ui_dev_actor, args.tls), indent=2))
        return
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
            from deploy_service import Swarm, reconcile, remote_log
            from rollout_checks import require_updated_callers
            swarm = Swarm(manifest['environment'])
            if args.infrastructure:
                signal.signal(signal.SIGHUP, signal.SIG_IGN)
                print(f'Operación con diario persistente. Log: {state / "logs/infrastructure.log"}', flush=True)
                remote_log(state, 'infrastructure', owner)
            if (state / 'pending.json').exists():
                if not (state / 'release.json').exists():
                    raise RuntimeError('Operación pendiente sin release confirmado; intervención requerida')
                if not args.infrastructure:
                    reconcile(state, swarm)
            previous_path = state / "release.json"
            previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
            if previous is None and manifest.get('schema_version') == 2:
                raise ValueError('Primero bootstrap base; ampliar sólo mediante --infrastructure con registro confirmado')
            if args.infrastructure:
                if previous is None or args.service:
                    raise ValueError('Infra requiere bootstrap confirmado y no combina --service')
                deploy_infrastructure(state, manifest, swarm,
                    lambda target: require_updated_callers(target, include_ui='ui' in manifest['images']))
                return
            selected_manifest = select_release(manifest, previous)
            if args.service:
                if previous is None:
                    raise ValueError("Actualizar un servicio requiere bootstrap previo")
                if selected_manifest['environment'] == 'prod':
                    raise ValueError('La actualización de aplicación prod requiere CD y evidencia por servicio')
                selected_manifest = update_service(selected_manifest, args.service, manifest['images'][args.service])
            if previous is None and selected_manifest['environment'] == 'prod':
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
