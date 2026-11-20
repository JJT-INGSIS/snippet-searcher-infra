"""Explicit PROD stages. No DEV credential copying or application service updates."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import sys

import install_observability_integrations as packages
from production_observability_candidate import bundle, ROOT, REPO
from stack_release import expected_images, validate_manifest
from start_log_forwarder_dev import agent_license, write_private

RUNTIME = Path(ROOT)
PRIVATE = Path('/etc/snippet-observability/prod')
STATE = Path('/home/azureuser/.local/state/snippet-searcher/prod')
STACK = 'snippet-searcher-prod_'
DATABASES = ('snippets', 'permissions')
VERSION = 'sni88-prod-v1'


def docker(*args, data=None):
    return subprocess.run(['docker', *args], input=data, capture_output=True, text=True,
                          check=True, timeout=180).stdout.strip()


def healthy_container(service):
    ids = docker('ps', '--filter', 'label=com.docker.swarm.service.name=' + STACK + service,
                 '--filter', 'status=running', '--format', '{{.ID}}').splitlines()
    if len(ids) != 1:
        raise ValueError('Require one running task: ' + service)
    if docker('inspect', ids[0], '--format', '{{.State.Health.Status}}') != 'healthy':
        raise ValueError('Require healthy task: ' + service)
    return ids[0]


def require_host():
    if os.geteuid() != 0 or socket.gethostname() != 'vm-snippet-prod' or platform.machine() != 'x86_64':
        raise ValueError('Requires root on the inventoried PROD x86-64 manager')
    swarm = json.loads(docker('info', '--format', '{{json .Swarm}}'))
    if swarm.get('LocalNodeState') != 'active' or not swarm.get('ControlAvailable'):
        raise ValueError('Requires active Swarm manager')
    if (STATE / 'pending.json').exists():
        raise ValueError('Resolve pending deployment before monitoring changes')
    release = json.loads((STATE / 'release.json').read_text())
    validate_manifest(release)
    if release['environment'] != 'prod' or release.get('storage_provider', 'local') != 'local' \
            or set(release.get('infrastructure', {})) != {'nginx'}:
        raise ValueError('PROD topology changed; review the candidate')
    for service in expected_images(release):
        healthy_container(service)
    volume = json.loads(docker('volume', 'inspect', STACK + 'snippets_content'))[0]
    owner = Path(volume['Mountpoint']).stat()
    if (owner.st_uid, owner.st_gid) != (10001, 10001):
        raise ValueError('Content owner differs; never chmod/chown application data')
    return release


def write_shared(path, value):
    path.write_text(value)
    path.chmod(0o644)


def stage():
    require_host()
    if RUNTIME.exists():
        raise ValueError('Runtime already exists; inspect partial state, never overwrite')
    config = json.loads((REPO / 'observability/config.prod-local.example.json').read_text())
    config['version'] = VERSION
    candidate = bundle(config)
    RUNTIME.mkdir(parents=True, mode=0o755)
    for name in ('collect.py', 'docker-config.yml', 'swarm_sample.py', 'images.lock.json'):
        shutil.copy2(REPO / 'observability/runtime' / name, RUNTIME / name)
        (RUNTIME / name).chmod(0o644)
    shutil.copy2(REPO / 'scripts/stack_release.py', RUNTIME / 'stack_release.py')
    (RUNTIME / 'stack_release.py').chmod(0o644)
    (RUNTIME / 'probes').mkdir()
    for name in ('asset_probe.py', 'storage_health.py', 'observability_config.py'):
        shutil.copy2(REPO / 'scripts' / name, RUNTIME / 'probes' / name)
        (RUNTIME / 'probes' / name).chmod(0o644)
    for name, value in [('config.json', config), ('integrations.json', candidate['integrations']),
                        ('agent.compose.json', candidate['agentCompose']),
                        ('collector.stack.json', candidate['collectorStack'])]:
        write_shared(RUNTIME / name, json.dumps(value, indent=2) + '\n')
    write_shared(RUNTIME / 'dispatch.sh', candidate['dispatch'])
    packages.install(RUNTIME / 'packages', 'amd64')
    shutil.copytree(RUNTIME / 'packages/var/db/newrelic-infra/newrelic-integrations/bin', RUNTIME / 'bin')
    locks = json.loads((RUNTIME / 'images.lock.json').read_text())
    for image in locks.values():
        docker('pull', image)
    cid = docker('create', locks['dockerCli'])
    try:
        docker('cp', cid + ':/usr/local/bin/docker', str(RUNTIME / 'docker'))
    finally:
        docker('rm', cid)
    (RUNTIME / 'docker').chmod(0o755)
    write_shared(RUNTIME / 'staged', VERSION + '\n')
    print('PASS staged PROD files; no database role, agent, license or telemetry activated')


def query(cid, database, sql):
    return docker('exec', cid, 'psql', '-U', database, '-d', database, '-Atc', sql)


def provision(expected_release):
    require_host()
    if hashlib.sha256((STATE / 'release.json').read_bytes()).hexdigest() != expected_release:
        raise ValueError('Confirmed release changed since operator review')
    if not (RUNTIME / 'staged').is_file() or PRIVATE.exists():
        raise ValueError('Require staged runtime and absent private directory; inspect partial changes')
    names = ['obs_' + db + '_db_password' for db in DATABASES]
    if set(names).intersection(docker('secret', 'ls', '--format', '{{.Name}}').splitlines()):
        raise ValueError('Monitoring secrets already exist; never rotate implicitly')
    tasks = {db: healthy_container(db + '-db') for db in DATABASES}
    for db, cid in tasks.items():
        if query(cid, db, "SELECT 1 FROM pg_roles WHERE rolname='nri_monitor'"):
            raise ValueError('Monitoring role collision; review existing grants')
    PRIVATE.mkdir(parents=True, mode=0o700)
    write_private(PRIVATE / 'provisioning', VERSION + '\n')
    # No aliases, application service edits, table grants or database restarts.
    for db, name in zip(DATABASES, names):
        password = secrets.token_hex(32)
        write_private(PRIVATE / name, password)
        docker('secret', 'create', name, '-', data=password)
        docker('exec', '-i', tasks[db], 'sh', '-c',
               'IFS= read -r OBS_MONITOR_PASSWORD; export OBS_MONITOR_PASSWORD; exec psql -U "$1" -d "$1" -v database="$1"',
               'monitor-setup', db, data=password + '\n' +
               'BEGIN;\n' + (REPO / 'observability/sql/postgresql-monitor.sql').read_text() + '\nCOMMIT;\n')
    docker('stack', 'deploy', '--resolve-image', 'always', '-c', str(RUNTIME / 'collector.stack.json'),
           'snippet-observability-prod')
    write_private(PRIVATE / 'provisioned', VERSION + '\n')
    print('PASS PROD read-only statistics roles and private collector provisioned; verify samples before agent start')


def metrics(value):
    return value.get('metrics', []) + [m for row in value.get('data', []) for m in row.get('metrics', [])]


def verify():
    require_host()
    ids = docker('ps', '--filter', 'label=com.docker.swarm.service.name=snippet-observability-prod_collector',
                 '--filter', 'status=running', '--format', '{{.ID}}').splitlines()
    if len(ids) != 1:
        raise ValueError('Require exactly one private PROD collector')
    results = {}
    for name in ('snippets-db', 'permissions-db', 'storage-local', 'snippets-db-disk', 'permissions-db-disk'):
        value = json.loads(docker('exec', ids[0], 'python3', '/opt/runtime/collect.py', name))
        if name in ('snippets-db', 'permissions-db'):
            if not metrics(value):
                raise ValueError('Native integration emitted no metrics: ' + name)
            results[name] = {'metricCount': len(metrics(value))}
        else:
            rows = value if isinstance(value, list) else [value]
            if not rows or any(row.get('up') != 1 for row in rows):
                raise ValueError('Storage fixture/capacity failed: ' + name)
            results[name] = rows
    print(json.dumps({'environment': 'prod', 'collector': results, 'ingestionVerified': False}))


def start():
    require_host()
    if not (PRIVATE / 'provisioned').is_file() or (PRIVATE / 'agent.json').exists():
        raise ValueError('Require provisioned PROD; never overwrite an existing agent license')
    if subprocess.run(['pgrep', '-x', 'newrelic-infra'], capture_output=True).returncode == 0:
        raise ValueError('Host already has an agent; avoid duplicate ingestion')
    verify()
    key = sys.stdin.read(200).strip()
    agent_license(json.dumps({'license_key': key}))
    config = {'license_key': key, 'display_name': 'vm-snippet-prod', 'docker_api_version': '1.44',
              'enable_process_metrics': False, 'metrics_process_sample_rate': -1,
              'metrics_system_sample_rate': 60, 'metrics_storage_sample_rate': 60,
              'metrics_network_sample_rate': 60, 'disable_inventory': True,
              'custom_attributes': {'environment': 'prod', 'service': 'infrastructure-agent', 'version': VERSION}}
    write_private(PRIVATE / 'agent.json', json.dumps(config))
    docker('compose', '-p', 'snippet-observability-prod', '-f', str(RUNTIME / 'agent.compose.json'), 'up', '-d')
    print('PASS PROD agent started; actual New Relic reception still requires verification')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('stage', 'provision', 'verify', 'start'))
    parser.add_argument('--expected-release', help='SHA-256 of the operator-reviewed confirmed release')
    args = parser.parse_args()
    if args.phase == 'provision' and (not args.expected_release or len(args.expected_release) != 64):
        parser.error('Provision requires --expected-release SHA-256')
    # Same application lock; fail promptly instead of racing a CD deployment.
    require_host()
    with (STATE / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.phase == 'provision':
            provision(args.expected_release)
        else:
            {'stage': stage, 'verify': verify, 'start': start}[args.phase]()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise SystemExit('PROD operation failed; inspect protected partial state before retrying; no credentials printed') from None
