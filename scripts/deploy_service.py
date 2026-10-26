"""Update one bootstrapped Swarm app; reconcile interrupted operations under its lock."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from github_cd import CHECKS, GitHub, operation_id, require_authorized_head, require_verified_image, validate_request, checks_for
from stack_release import (APPLICATIONS, INFRA_PACKAGES, ONE_SHOT_SERVICES, expected_images,
                           update_service, validate_manifest, write_record)

ROOT = Path(__file__).resolve().parent.parent
FAILURES = (ValueError, RuntimeError, OSError, subprocess.SubprocessError)


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text())


def remote_log(state, identity, owner):
    """Keep child verification output off an SSH pipe that may disappear."""
    logs = state / 'logs'
    logs.mkdir(mode=0o700, exist_ok=True)
    path = logs / f'{identity}.log'
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    if os.geteuid() == 0:
        os.chown(logs, owner.pw_uid, owner.pw_gid)
        os.chown(path, owner.pw_uid, owner.pw_gid)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(descriptor, 1)
    os.dup2(descriptor, 2)
    os.close(descriptor)


@contextmanager
def deployment_lock(state):
    import fcntl
    # Require the bootstrap directories; CD must not silently bootstrap a VM.
    if not (state / 'release.json').is_file():
        raise ValueError('Falta bootstrap y release.json confirmado')
    with (state / 'deploy.lock').open('a') as lock:
        deadline = time.monotonic() + 1800
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Timeout esperando deploy.lock')
                time.sleep(1)
        yield


def docker_json(*arguments):
    return json.loads(subprocess.check_output(['docker', *arguments], text=True, timeout=30))


class Swarm:
    def __init__(self, environment):
        self.environment = environment
        self.stack = f'snippet-searcher-{environment}'

    def check_manager(self):
        info = docker_json('info', '--format', '{{json .}}')
        if info.get('Name') != f'vm-snippet-{self.environment}' or not info.get('Swarm', {}).get('ControlAvailable'):
            raise ValueError('VM o manager incorrecto')

    def images(self):
        rows = subprocess.check_output(['docker', 'service', 'ls', '--filter',
                f'label=com.docker.stack.namespace={self.stack}', '--format', '{{.Name}}'], text=True, timeout=30).split()
        known = set(APPLICATIONS) | set(INFRA_PACKAGES) | {'snippets-db', 'permissions-db'}
        result = {}
        for full_name in rows:
            name = full_name.removeprefix(self.stack + '_')
            if name in ONE_SHOT_SERVICES:
                continue
            if name not in known:
                raise ValueError('Servicio ajeno al inventario del stack')
            result[name] = docker_json('service', 'inspect', full_name)[0]['Spec']['TaskTemplate']['ContainerSpec']['Image']
        return result

    def pull(self, image):
        subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', image], check=True, timeout=600)
        built = docker_json('image', 'inspect', image)[0]
        if built.get('Os') != 'linux' or built.get('Architecture') != 'amd64':
            raise ValueError('Imagen incompatible con las VMs x64')

    def update(self, service, image):
        # Public GHCR: no registry credentials or runtime secret modifications.
        subprocess.run(['docker', 'service', 'update', '--detach', '--image', image,
                        f'{self.stack}_{service}'], check=True, timeout=180)

    def verify(self, release, application=None):
        from stack_runtime import verify_service_configuration
        verify_service_configuration(release, docker_json, application)
        environment = {**os.environ, **validate_manifest(release)}
        environment['VERIFY_APPLICATION'] = application or ''
        subprocess.run([sys.executable, str(ROOT / 'scripts/wait_for_stack.py'), self.stack],
                       check=True, env=environment, timeout=700)
        verify_service_configuration(release, docker_json, application)
        subprocess.run([sys.executable, str(ROOT / 'scripts/verify_stack.py'), self.stack],
                       check=True, env=environment, timeout=300)

    def apply_infrastructure(self, release):
        from stack_runtime import apply_release
        apply_release(release, docker_json)

    def remove_components(self, names):
        if not set(names) <= set(INFRA_PACKAGES) | {'ui'}:
            raise ValueError('La recuperación no elimina aplicaciones backend ni bases')
        for name in sorted(names):
            subprocess.run(['docker', 'service', 'rm', f'{self.stack}_{name}'], check=True, timeout=30)

    def require_recoverable_infrastructure(self, previous, candidate):
        from stack_release import infrastructure, ui_environment
        images = self.images()
        if 'ui' in images:
            current = docker_json('service', 'inspect', f'{self.stack}_ui')[0]['Spec']['TaskTemplate']['ContainerSpec']
            values = dict(entry.split('=', 1) for entry in current.get('Env', []))
            if not any(all(values.get(key, '') == value for key, value in ui_environment(release).items())
                       for release in (previous, candidate) if 'ui' in release['images']):
                raise ValueError('Configuración UI ajena a la operación; intervención requerida')
        if 'nginx' not in images:
            return
        current = docker_json('service', 'inspect', f'{self.stack}_nginx')[0]['Spec']['TaskTemplate']['ContainerSpec']
        actual = {entry['ConfigName'] for entry in current.get('Configs', [])}
        possible = set()
        hosts = set()
        for release in (previous, candidate):
            proxy = infrastructure(release).get('nginx')
            if proxy:
                possible.update(spec['name'] for spec in proxy['configs'].values())
                hosts.add(proxy['hostname'])
        values = dict(entry.split('=', 1) for entry in current.get('Env', []))
        if not actual or not actual <= possible or values.get('PROXY_HOSTNAME') not in hosts:
            raise ValueError('Configuración NGINX ajena a la operación; intervención requerida')


def require_images(swarm, release):
    if swarm.images() != expected_images(release):
        raise ValueError('Swarm y registro no coinciden; reconciliar antes de desplegar')


def save_operation(state, operation):
    operations = state / 'operations'
    operations.mkdir(mode=0o700, exist_ok=True)
    write_record(operations / f'{operation_id(operation["request"])}.json', operation)


def confirm_release(state, identity, release):
    write_record(state / 'release.json', release)
    history = state / 'history'
    history.mkdir(mode=0o700, exist_ok=True)
    write_record(history / f'sni25-{identity}.json', release)
    (state / 'pending.json').unlink(missing_ok=True)


def finish(state, operation, release, outcome):
    receipt = {**operation['request'], 'outcome': outcome, 'verified-at': now(),
               'checks': checks_for(operation['request']['service']) if outcome in ('verified', 'recovered') else {},
               'previous-image': operation['previous']['images'][operation['request']['service']],
               'actual-image': release['images'][operation['request']['service']]}
    changed = {**release, 'deployed_at': receipt['verified-at'],
               'checks': CHECKS if receipt['checks'] else {'recovery': 'failed'},
               'deployments': {**release.get('deployments', {}), operation['request']['service']: receipt}}
    # Journal first: if the process stops between files, reconciliation can finish
    # the release write without resubmitting the Docker update.
    final = {**operation, 'receipt': receipt, 'state': outcome, 'confirmed-release': changed}
    save_operation(state, final)
    confirm_release(state, operation_id(operation['request']), changed)
    return receipt


def settle(state, operation, swarm):
    """Resolve actual state, including automatic rollback, after lost SSH/process."""
    previous, candidate = operation['previous'], operation['candidate']
    service = operation['request']['service']
    actual = swarm.images()
    for name, image in expected_images(previous).items():
        if name != service and actual[name] != image:
            raise ValueError('Otro servicio cambió durante una operación pendiente; intervención necesaria')
    if actual[service] == candidate['images'][service]:
        try:
            swarm.verify(candidate, service)
        except FAILURES:
            pass
        else:
            return finish(state, operation, candidate, 'verified')
    if actual[service] not in (previous['images'][service], candidate['images'][service]):
        raise ValueError('Referencia inesperada del servicio; no sobrescribir cambios externos')
    try:
        if swarm.images()[service] != previous['images'][service]:
            swarm.update(service, previous['images'][service])
        swarm.verify(previous, service)
        return finish(state, operation, previous, 'recovered')
    except FAILURES:
        # Do not label the old release healthy or clear the pending recovery.
        observed = swarm.images()
        failed = {**previous, 'images': {name: observed[name] for name in previous['images']},
                  'checks': {'recovery': 'failed'}}
        write_record(state / 'release.json', failed)
        save_operation(state, {**operation, 'state': 'recovery_failed'})
        raise RuntimeError('Falló la recuperación; pendiente conservado para reconciliación') from None


def reconcile(state, swarm):
    pending = state / 'pending.json'
    if not pending.exists():
        return None
    identity = read_json(pending)['operation']
    if isinstance(identity, str) and re.fullmatch(r'infra-[a-f0-9]{32}', identity):
        from bootstrap_swarm import reconcile_infrastructure
        return reconcile_infrastructure(state, swarm)
    if not isinstance(identity, str) or not re.fullmatch(
            r'(snippets-service|permissions-service|printscript-service|ui)-[0-9]+-[0-9]+', identity):
        raise ValueError('Identificador de operación pendiente inválido')
    operation = read_json(state / 'operations' / f'{identity}.json')
    if operation.get('state') in ('verified', 'recovered'):
        # Still check actual convergence; a finalized journal is not proof of
        # current state after an interruption between journal and release writes.
        release = operation['confirmed-release']
        require_images(swarm, release)
        swarm.verify(release, operation['request']['service'])
        confirm_release(state, identity, release)
        return operation['receipt']
    return settle(state, operation, swarm)


def deploy_locked(state, request, swarm, authorize, verify_evidence):
    validate_request(request)
    swarm.check_manager()
    pending = state / 'pending.json'
    if pending.exists() and read_json(pending)['operation'] == operation_id(request):
        original = read_json(state / 'operations' / f'{operation_id(request)}.json')
        if original['request'] != request:
            raise ValueError('Un reintento no puede cambiar los datos de la operación')
    reconciled = reconcile(state, swarm)
    if reconciled and 'service' in reconciled and operation_id(reconciled) == operation_id(request):
        return reconciled
    completed = state / 'operations' / f'{operation_id(request)}.json'
    if completed.exists():
        operation = read_json(completed)
        if operation['request'] != request:
            raise ValueError('Un reintento no puede cambiar los datos de la operación')
        if operation.get('state') in ('verified', 'recovered'):
            current = read_json(state / 'release.json')
            require_images(swarm, current)
            swarm.verify(current, request['service'])
            if current['images'][request['service']] != operation['receipt']['actual-image']:
                raise ValueError('La operación fue reemplazada por otra versión; no se redespliega')
            return operation['receipt']
    previous = read_json(state / 'release.json')
    validate_manifest(previous)
    if previous['environment'] != request['environment'] or previous.get('checks') != CHECKS:
        raise ValueError('El registro previo no está verificado para este ambiente')
    last = previous.get('deployments', {}).get(request['service'])
    if last and (request['run-id'], request['run-attempt']) < (last['run-id'], last['run-attempt']):
        raise ValueError('Ejecución anterior a la última operación registrada')
    authorize(request)
    verify_evidence(request)  # Historical proof once; current authorization is checked again below.
    require_images(swarm, previous)
    swarm.verify(previous, request['service'])  # Establish the actually working rollback baseline.
    swarm.pull(request['image-ref'])
    # Recheck authorization after slow pulls/checks, still inside deploy.lock.
    authorize(request)
    candidate = update_service(previous, request['service'], request['image-ref'])
    operation = {'request': request, 'previous': previous, 'candidate': candidate,
                 'state': 'updating', 'started-at': now()}
    save_operation(state, operation)
    write_record(state / 'pending.json', {'operation': operation_id(request)})
    try:
        if previous['images'][request['service']] != request['image-ref']:
            swarm.update(request['service'], request['image-ref'])
    except FAILURES:
        # A timeout may have happened after Docker accepted the update.
        pass
    return settle(state, operation, swarm)


def main():
    import pwd
    # Ordinary SSH loss must not abort a submitted operation halfway through.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    envelope = json.load(sys.stdin)
    request = envelope['request']
    validate_request(request)
    api = GitHub(request['repository'], envelope.get('token', ''))
    del envelope
    owner = pwd.getpwnam(os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    state = Path(owner.pw_dir) / f'.local/state/snippet-searcher/{request["environment"]}'
    # Docker/verifier output goes to a VM log, not the SSH pipe: a closed client
    # must not turn healthy verification into a broken-pipe failure and rollback.
    if not state.is_dir():
        raise ValueError('Falta el directorio de estado del bootstrap')
    remote_log(state, operation_id(request), owner)
    with deployment_lock(state):
        try:
            receipt = deploy_locked(state, request, Swarm(request['environment']),
                                    lambda value: require_authorized_head(api, value),
                                    lambda value: require_verified_image(api, value))
        finally:
            if os.geteuid() == 0:
                for path in (state, *state.rglob('*')):
                    os.chown(path, owner.pw_uid, owner.pw_gid)
    # SSH transports only the exit status. The durable journal is the receipt source.
    return 0 if receipt['outcome'] == 'verified' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (*FAILURES, KeyError, TypeError) as error:
        print(f'FAIL deployment: {error}. Revisar estado y operación pendiente.', file=sys.stderr)
        sys.exit(1)
