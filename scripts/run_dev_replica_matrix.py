"""Bounded SNI-87 replica faults on DEV, one component at a time, with durable receipts."""

import argparse
import fcntl
import hashlib
import json
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

COMPONENTS = ('nginx', 'ui', 'snippets-service', 'permissions-service', 'snippets-db', 'redis')
STATE = Path('/home/azureuser/.local/state/snippet-searcher/dev')
RUNNER = Path(__file__).with_name('run_dev_drill.py')


def now():
    return datetime.now(timezone.utc).isoformat()


def output(*arguments):
    return subprocess.check_output(arguments, text=True, timeout=30).strip()


def original_replicas(specification):
    replicas = specification['Spec'].get('Mode', {}).get('Replicated', {}).get('Replicas')
    if type(replicas) is not int or replicas != 1:
        raise ValueError('Require the original single replica; never guess a restoration target')
    return replicas


def validate_baseline(host, release, pending):
    if host != 'vm-snippet-dev' or release.get('environment') != 'dev':
        raise ValueError('Only the DEV VM is allowed')
    if pending or release.get('background') != {'publisher': True, 'consumer': True}:
        raise ValueError('Finish deployment/consumer acceptance before starting another fault')


def require_idle():
    database = output('docker', 'ps', '--filter',
                      'label=com.docker.swarm.service.name=snippet-searcher-dev_snippets-db', '--format', '{{.ID}}')
    if not database or '\n' in database:
        raise ValueError('Require one healthy Snippets database')
    query = ("SELECT (SELECT count(*) FROM event_outbox WHERE published_at IS NULL) + "
             "(SELECT count(*) FROM background_jobs WHERE finished_at IS NULL) + "
             "(SELECT count(*) FROM execution_permits WHERE state <> 'RELEASED')")
    count = output('docker', 'exec', database, 'sh', '-c',
                   'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"', 'sh', query)
    if count != '0':
        raise ValueError('Existing jobs/outbox/permits need review; do not interrupt them')


def wait_healthy(service):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if output('docker', 'ps', '--filter', 'label=com.docker.swarm.service.name=' + service,
                  '--filter', 'health=healthy', '--format', '{{.ID}}'):
            return
        time.sleep(2)
    raise ValueError('Service did not recover health: ' + service)


def scale(service, replicas):
    subprocess.run(['docker', 'service', 'scale', '--detach=true', f'{service}={replicas}'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)


def exercise(component, seconds, directory):
    if component not in COMPONENTS or not 300 <= seconds <= 600:
        raise ValueError('Use an approved component and a bounded five-to-ten-minute window')
    with (STATE / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = json.loads((STATE / 'release.json').read_text())
        validate_baseline(socket.gethostname(), release, (STATE / 'pending.json').exists())
        if output('docker', 'info', '--format', '{{.Name}}') != 'vm-snippet-dev':
            raise ValueError('Docker context is not the DEV VM')
        available = output('docker', 'service', 'ls', '--filter',
                           'label=com.docker.stack.namespace=snippet-searcher-dev', '--format', '{{.Replicas}}').splitlines()
        if len(available) < 8 or any(value != '1/1' for value in available):
            raise ValueError('All application services must have their original running replica')
        subprocess.run(['python3', '-B', str(RUNNER), 'healthy-create'], check=True, timeout=210)
        require_idle()
        service = 'snippet-searcher-dev_' + component
        application_services = output('docker', 'service', 'ls', '--filter',
                                      'label=com.docker.stack.namespace=snippet-searcher-dev', '--format', '{{.Name}}').splitlines()
        specification = json.loads(output('docker', 'service', 'inspect', service))[0]
        replicas = original_replicas(specification)
        wait_healthy(service)
        template_hash = hashlib.sha256(json.dumps(specification['Spec']['TaskTemplate'], sort_keys=True).encode()).hexdigest()
        unit = 'sni87-matrix-' + component + '-' + uuid4().hex[:8]
        receipt = {'component': component, 'environment': 'dev', 'status': 'PREPARED', 'preparedAt': now(),
                   'originalImage': specification['Spec']['TaskTemplate']['ContainerSpec']['Image'],
                   'templateSha256': template_hash, 'restoreReplicas': replicas, 'holdSeconds': seconds,
                   'timerUnit': unit, 'incidentId': None, 'deviceReceivedAt': None}
        path = directory / (component + '.json')
        with path.open('x') as target:
            path.chmod(0o600)
            json.dump(receipt, target)

        def save():
            temporary = path.with_suffix('.tmp')
            temporary.touch(mode=0o600, exist_ok=True)
            temporary.write_text(json.dumps(receipt, indent=2) + '\n')
            temporary.replace(path)

        subprocess.run(['systemd-run', '--unit=' + unit, '--on-active=' + str(seconds + 90) + 's',
                        '/usr/bin/docker', 'service', 'scale', '--detach=true', f'{service}={replicas}'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20)
        try:
            scale(service, 0)
            receipt.update(status='FAULT_ACTIVE', faultAt=now())
            save()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                time.sleep(max(0, min(1, deadline - time.monotonic())))
        finally:
            receipt.update(status='RESTORING', restoreStartedAt=now())
            save()
            scale(service, replicas)
            wait_healthy(service)
            for application_service in application_services:
                wait_healthy(application_service)
            receipt['healthRecoveredAt'] = now()
            current = json.loads(output('docker', 'service', 'inspect', service))[0]
            current_hash = hashlib.sha256(json.dumps(current['Spec']['TaskTemplate'], sort_keys=True).encode()).hexdigest()
            if current_hash != template_hash:
                raise ValueError('Service template changed during the drill; review before continuing')
            subprocess.run(['python3', '-B', str(RUNNER), 'healthy-create'], check=True, timeout=210)
            receipt.update(status='RESTORED_AWAITING_ALERT_EVIDENCE', functionalRecoveryAt=now(),
                           originalTemplatePreserved=True)
            save()
            subprocess.run(['systemctl', 'stop', unit + '.timer'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, timeout=20)
        print(json.dumps(receipt, separators=(',', ':')), flush=True)


def terminate(signum, frame):
    raise SystemExit('Matrix interrupted; restoring the active component')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', nargs='+', choices=COMPONENTS, required=True)
    parser.add_argument('--hold-seconds', type=int, default=420)
    parser.add_argument('--execute', action='store_true')
    arguments = parser.parse_args()
    if not arguments.execute:
        raise SystemExit('Read the runbook and use --execute only in the authorized DEV window')
    if not 300 <= arguments.hold_seconds <= 600 or len(set(arguments.components)) != len(arguments.components):
        raise SystemExit('Require unique components and a bounded hold duration')
    signal.signal(signal.SIGTERM, terminate)
    directory = Path('/var/tmp') / ('sni87-matrix-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    directory.mkdir(mode=0o700, exist_ok=False)
    print(json.dumps({'directory': str(directory), 'startedAt': now()}), flush=True)
    for name in arguments.components:
        exercise(name, arguments.hold_seconds, directory)
