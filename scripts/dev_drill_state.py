"""Read-only DEV snapshot/compare around an Azure VM drill; never starts/stops services."""

import argparse
import hashlib
import json
import os
import socket
from pathlib import Path

from run_dev_replica_matrix import STATE, now, output, require_idle, validate_baseline

SNAPSHOT = Path('/var/tmp/sni87-vm-before-20261120.json')


def compare(before, after):
    for key in ('releaseSha256', 'services'):
        if before[key] != after[key]:
            raise ValueError('DEV configuration changed across the VM drill: ' + key)
    if any(x['replicas'] != '1/1' for x in after['services']):
        raise ValueError('DEV replicas have not recovered')


def snapshot():
    if os.geteuid() != 0 or socket.gethostname() != 'vm-snippet-dev':
        raise ValueError('Only root on the DEV manager may collect this receipt')
    release_bytes = (STATE / 'release.json').read_bytes()
    release = json.loads(release_bytes)
    validate_baseline(socket.gethostname(), release, (STATE / 'pending.json').exists())
    if output('docker', 'info', '--format', '{{.Name}}') != 'vm-snippet-dev':
        raise ValueError('Docker is not connected to the DEV host')
    require_idle()
    names = sorted(output('docker', 'service', 'ls', '--format', '{{.Name}}').splitlines())
    names = [name for name in names if name.startswith(('snippet-searcher-dev_', 'snippet-observability-dev_'))]
    rows = []
    for name in names:
        spec = json.loads(output('docker', 'service', 'inspect', name))[0]['Spec']
        replicas = output('docker', 'service', 'ls', '--filter', 'name=' + name, '--format', '{{.Replicas}}')
        rows.append({'service': name, 'image': spec['TaskTemplate']['ContainerSpec']['Image'],
                     'replicas': replicas,
                     'templateSha256': hashlib.sha256(json.dumps(spec['TaskTemplate'], sort_keys=True).encode()).hexdigest()})
    if len(rows) != 9 or any(row['replicas'] != '1/1' for row in rows):
        raise ValueError('Require the eight application services and collector at 1/1')
    return {'at': now(), 'environment': 'dev', 'releaseSha256': hashlib.sha256(release_bytes).hexdigest(),
            'services': rows, 'pendingJournal': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('before', 'after'))
    stage = parser.parse_args().stage
    value = snapshot()
    if stage == 'before':
        fd = os.open(SNAPSHOT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as target:
            json.dump(value, target, indent=2)
        print(json.dumps({'at': value['at'], 'status': 'BASELINE_SAVED', 'services': len(value['services']),
                          'releaseSha256': value['releaseSha256']}))
    else:
        before = json.loads(SNAPSHOT.read_text())
        compare(before, value)
        print(json.dumps({'at': value['at'], 'status': 'CONFIGURATION_PRESERVED',
                          'services': len(value['services']), 'releaseSha256': value['releaseSha256'],
                          'functionalRecoveryVerified': False}))
