"""Isolated real Redis acceptance; never mounts the Docker socket or touches application volumes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from prepare_redis_secret import create
from redis_runtime import REDIS_IMAGE
from redis_storage import backup, restore

ROOT = Path(__file__).resolve().parent.parent


def command(*args, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError(f'Docker operation failed: {args[0]} (output withheld)')
    return result


def cli(container, *args):
    return command('exec', container, 'sh', '/etc/redis/cli.sh', *args).stdout.strip()


def healthy(container):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        details = json.loads(command('inspect', container).stdout)[0]
        if details['State'].get('Health', {}).get('Status') == 'healthy':
            return details
        if not details['State']['Running']:
            raise RuntimeError('Redis did not start; credential output withheld')
        time.sleep(.25)
    raise RuntimeError('Redis authenticated healthcheck did not pass')


def start_fixture(container, secret, volume=None):
    args = ['run', '-d', '--name', container, '--label', 'com.jjt.sni56=' + container,
            '--network', 'none', '--memory', '384m', '--cpus', '.5',
            '--mount', f'type=bind,source={ROOT / "redis"},target=/etc/redis,readonly',
            '--mount', f'type=bind,source={secret},target=/run/secrets/redis_password,readonly',
            '--tmpfs', '/run/redis:rw,noexec,nosuid,size=1m',
            '--health-cmd', 'sh /etc/redis/healthcheck.sh', '--health-interval', '1s',
            '--health-timeout', '2s', '--health-retries', '3', '--entrypoint', 'sh']
    args += ['--mount', f'type=volume,source={volume},target=/data'] if volume else ['--tmpfs', '/data:rw,size=8m']
    command(*args, REDIS_IMAGE, '/etc/redis/entrypoint.sh')
    return healthy(container)


def disk_full(secret, identity):
    container = identity + '-disk'
    try:
        start_fixture(container, secret)
        assert cli(container, 'XADD', 'events', '*', 'event', 'must-survive')
        cli(container, 'XGROUP', 'CREATE', 'events', 'workers', '0-0')
        cli(container, 'XREADGROUP', 'GROUP', 'workers', 'consumer', 'STREAMS', 'events', '>')
        assert command('exec', container, 'sh', '-ec',
                       'test "$(stat -f -c %T /data)" = tmpfs; test "$(stat -f -c %b /data)" -le 2048').returncode == 0
        command('exec', container, 'sh', '-c',
                'dd if=/dev/zero of=/data/fault-fill bs=1024 count=16384 2>/dev/null || true')
        cli(container, 'SET', 'fault-trigger', 'x' * 16384)
        from redis_storage import wait_for
        wait_for(container, lambda state: state['aof_last_write_status'] == 'err')
        assert 'MISCONF' in cli(container, 'XADD', 'events', '*', 'event', 'not-durable')
        assert command('exec', container, 'sh', '/etc/redis/healthcheck.sh', check=False).returncode != 0
        assert cli(container, 'XLEN', 'events') == '1'
        assert cli(container, 'XPENDING', 'events', 'workers').splitlines()[0] == '1'
        command('exec', container, 'rm', '-f', '/data/fault-fill')
        wait_for(container, lambda state: state['aof_last_write_status'] == 'ok')
        healthy(container)
        assert cli(container, 'XPENDING', 'events', 'workers').splitlines()[0] == '1'
        print('PASS bounded full-AOF filesystem: writes rejected, unhealthy, pending retained, recovery verified')
    finally:
        command('rm', '-f', container, check=False)


def run():
    from verify_asset_persistence import local_engine
    local_engine()
    identity = 'sni56-' + uuid4().hex
    folder = ROOT / '.sni56' / identity
    folder.mkdir(parents=True)
    secret = folder / 'redis_password'
    create(secret)
    password = secret.read_text()
    digest = hashlib.sha256(password.encode()).hexdigest()
    volume = identity + '-data'
    container = identity
    command('volume', 'create', '--label', 'com.jjt.sni56=' + identity, volume)
    try:
        command('run', '-d', '--name', container, '--label', 'com.jjt.sni56=' + identity,
            '--network', 'none', '--memory', '384m', '--cpus', '.5',
            '--mount', f'type=bind,source={ROOT / "redis"},target=/etc/redis,readonly',
            '--mount', f'type=bind,source={secret},target=/run/secrets/redis_password,readonly',
            '--mount', f'type=volume,source={volume},target=/data',
            '--tmpfs', '/run/redis:rw,noexec,nosuid,size=1m',
            '--health-cmd', 'sh /etc/redis/healthcheck.sh', '--health-interval', '1s',
            '--health-timeout', '2s', '--health-retries', '3',
            '--entrypoint', 'sh', REDIS_IMAGE, '/etc/redis/entrypoint.sh')
        details = healthy(container)
        inspected = json.dumps(details)
        assert password not in inspected and digest not in inspected
        assert not details['NetworkSettings']['Ports']
        assert details['HostConfig']['Memory'] == 384 * 1024 * 1024
        assert 'NOAUTH' in command('exec', container, 'redis-cli', '--raw', 'PING').stdout
        assert cli(container, 'CONFIG', 'GET', 'maxmemory-policy').splitlines()[-1] == 'noeviction'
        assert int(cli(container, 'CONFIG', 'GET', 'maxmemory').splitlines()[-1]) == 128 * 1024 * 1024
        first = cli(container, 'XADD', 'events', '*', 'event', 'confirmed-one')
        cli(container, 'XADD', 'events', '*', 'event', 'confirmed-two')
        assert cli(container, 'XGROUP', 'CREATE', 'events', 'workers', '0-0') == 'OK'
        cli(container, 'XREADGROUP', 'GROUP', 'workers', 'first-worker', 'COUNT', '2', 'STREAMS', 'events', '>')
        assert cli(container, 'XACK', 'events', 'workers', first) == '1'
        pending = cli(container, 'XPENDING', 'events', 'workers')
        assert pending.splitlines()[0] == '1'
        command('stop', '--time', '10', container)
        command('start', container)
        healthy(container)
        assert cli(container, 'XLEN', 'events') == '2'
        assert cli(container, 'XPENDING', 'events', 'workers') == pending
        assert cli(container, 'CONFIG', 'SET', 'maxmemory', '1') == 'OK'
        assert 'OOM' in cli(container, 'XADD', 'events', '*', 'event', 'not-admitted')
        assert cli(container, 'XLEN', 'events') == '2'
        assert cli(container, 'XPENDING', 'events', 'workers') == pending
        assert cli(container, 'CONFIG', 'SET', 'maxmemory', str(128 * 1024 * 1024)) == 'OK'
        snapshot = folder / 'snapshot.rdb'
        backup(container, snapshot)
        restored_volume = identity + '-restored'
        restore(snapshot, restored_volume, secret)
        restored_container = identity + '-restored'
        try:
            start_fixture(restored_container, secret, restored_volume)
            assert cli(restored_container, 'XLEN', 'events') == '2'
            assert cli(restored_container, 'XPENDING', 'events', 'workers') == pending
        finally:
            command('rm', '-f', restored_container, check=False)
            command('volume', 'rm', restored_volume, check=False)
        print('PASS RDB backup and fresh-volume restore to AOF: messages and pending group recovered')
        logs = command('logs', container).stdout + command('logs', container).stderr
        assert password not in logs and digest not in logs
        print('PASS real Redis: secret-free inspect/logs, private, authenticated, AOF restart, pending group and OOM retained')
        disk_full(secret, identity)
    finally:
        command('rm', '-f', container, check=False)
        command('volume', 'rm', volume, check=False)
        secret.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
