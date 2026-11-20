"""Bounded readonly-view fault for the active DEV storage probe, not application data."""

import argparse
import fcntl
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

from run_dev_replica_matrix import STATE, RUNNER, now, output, require_idle, validate_baseline

SERVICE = 'snippet-observability-dev_collector'
SOURCE = 'snippet-searcher-dev_snippets_content'
TARGET = '/observed/snippets-content'
UNIT = 'sni87-storage-view-restore-20261120'
RECEIPT = Path('/var/tmp/sni87-storage-view-20261120.json')


def mount_argument(readonly):
    return 'type=volume,source=' + SOURCE + ',target=' + TARGET + ',readonly=' + str(readonly).lower()


def require_original_mount(spec):
    entries = [x for x in spec['Spec']['TaskTemplate']['ContainerSpec']['Mounts'] if x['Target'] == TARGET]
    if len(entries) != 1 or entries[0]['Type'] != 'volume' or entries[0]['Source'] != SOURCE or entries[0].get('ReadOnly', False):
        raise ValueError('Require the original writable view of the known DEV content volume')


def change(readonly):
    subprocess.run(['docker', 'service', 'update', '--detach=true', '--mount-add', mount_argument(readonly), SERVICE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)


def wait_view(readonly):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        ids = output('docker', 'ps', '--filter', 'label=com.docker.swarm.service.name=' + SERVICE,
                     '--filter', 'status=running', '--format', '{{.ID}}').splitlines()
        if len(ids) == 1:
            mounts = json.loads(output('docker', 'inspect', ids[0], '--format', '{{json .Mounts}}'))
            if any(x['Destination'] == TARGET and x['RW'] is (not readonly) for x in mounts):
                return ids[0]
        time.sleep(2)
    raise ValueError('Private collector view did not converge')


def probe(cid):
    result = json.loads(output('docker', 'exec', cid, 'python3', '/opt/runtime/collect.py', 'storage-local'))
    return result[0] if isinstance(result, list) else result


def equivalent_template_hash(template):
    container = template['ContainerSpec']
    mounts = [{key: value for key, value in mount.items()
               if not (key == 'VolumeOptions' and value == {})
               and not (key == 'ReadOnly' and value is False)}
              for mount in container['Mounts']]
    normalized_container = {key: value for key, value in container.items()
                            if not (key == 'DNSConfig' and value == {})
                            and not (key == 'StopGracePeriod' and value == 10_000_000_000)}
    normalized = {**template, 'ContainerSpec': {**normalized_container, 'Mounts': sorted(mounts, key=lambda x: x['Target'])}}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


def template_hash():
    spec = json.loads(output('docker', 'service', 'inspect', SERVICE))[0]
    return equivalent_template_hash(spec['Spec']['TaskTemplate'])


def run():
    if os.geteuid() != 0 or socket.gethostname() != 'vm-snippet-dev':
        raise ValueError('Only root on the reviewed DEV manager is allowed')
    with (STATE / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = json.loads((STATE / 'release.json').read_text())
        validate_baseline(socket.gethostname(), release, (STATE / 'pending.json').exists())
        if release.get('storage_provider', 'local') != 'local':
            raise ValueError('Only the active local provider is covered')
        require_idle()
        spec = json.loads(output('docker', 'service', 'inspect', SERVICE))[0]
        require_original_mount(spec)
        before = template_hash()
        baseline = probe(wait_view(False))
        if baseline['up'] != 1:
            raise ValueError('Storage baseline must be healthy')
        subprocess.run(['python3', '-B', str(RUNNER), 'healthy-create'], check=True, timeout=210)
        receipt = {'environment': 'dev', 'scope': 'Active volume, collector readonly view only; application mount unchanged',
                   'preparedAt': now(), 'status': 'PREPARED', 'baseline': baseline, 'deviceReceivedAt': None,
                   'beforeTemplateEquivalentSha256': before}
        descriptor = os.open(RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as target:
            json.dump(receipt, target)

        def save():
            RECEIPT.write_text(json.dumps(receipt, indent=2) + '\n')

        subprocess.run(['systemd-run', '--unit=' + UNIT, '--on-active=510s', '/usr/bin/docker',
                        'service', 'update', '--detach=true', '--mount-add', mount_argument(False), SERVICE],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20)
        try:
            change(True)
            failed = probe(wait_view(True))
            if failed['up'] != 0:
                raise ValueError('Expected a real readonly-view probe failure')
            receipt.update(status='FAULT_ACTIVE', faultAt=now(), failed=failed)
            save()
            deadline = time.monotonic() + 420
            while time.monotonic() < deadline:
                time.sleep(max(0, min(1, deadline - time.monotonic())))
        finally:
            receipt.update(status='RESTORING', restoreStartedAt=now())
            save()
            change(False)
            recovered = probe(wait_view(False))
            if recovered['up'] != 1 or recovered.get('contentOk') != 1:
                raise ValueError('Real storage write/read recovery not verified')
            receipt['afterTemplateEquivalentSha256'] = template_hash()
            receipt['restoredTemplateEquivalent'] = receipt['afterTemplateEquivalentSha256'] == before
            if not receipt['restoredTemplateEquivalent']:
                receipt.update(status='RESTORE_CONFIGURATION_DRIFT')
                save()
                raise ValueError('Collector configuration changed beyond mount ordering/defaults; inspect before continuing')
            receipt['recovered'] = recovered
            subprocess.run(['python3', '-B', str(RUNNER), 'healthy-create'], check=True, timeout=210)
            receipt.update(status='RESTORED_AWAITING_ALERT_EVIDENCE', functionalRecoveryAt=now())
            save()
            subprocess.run(['systemctl', 'stop', UNIT + '.timer'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, timeout=20)
        print(json.dumps(receipt), flush=True)


def interrupted(signum, frame):
    raise SystemExit('Storage-view drill interrupted; restoring the original collector view')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    if not parser.parse_args().execute:
        raise SystemExit('Read the runbook and use --execute only in the authorized DEV window')
    signal.signal(signal.SIGTERM, interrupted)
    run()
