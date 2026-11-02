"""Manual Redis snapshot backup and restore into a NEW volume; never clears a live volume."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

from redis_runtime import REDIS_IMAGE

ROOT = Path(__file__).resolve().parent.parent
AUTH = 'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; exec redis-cli --raw "$@"'


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=90)
    if result.returncode:
        if args[0] == 'cp':
            raise RuntimeError(f'Docker cp falló: {result.stderr.strip()}')
        raise RuntimeError(f'Falló operación Docker {args[0]}; no se imprime salida sensible')
    return result.stdout.strip()


def redis(container, *args):
    return docker('exec', container, 'sh', '-ec', AUTH, 'redis-cli', *args)


def persistence(container):
    return dict(line.split(':', 1) for line in redis(container, 'INFO', 'persistence').splitlines()
                if ':' in line and not line.startswith('#'))


def wait_for(container, predicate):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if predicate(persistence(container)):
            return
        time.sleep(.2)
    raise RuntimeError('Redis no confirmó persistencia en el plazo; conservar datos y revisar')


def backup(container, destination):
    destination = Path(destination).resolve()
    if destination.exists() or destination.with_suffix('.json').exists():
        raise ValueError('El backup no sobrescribe archivos existentes')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    before = int(persistence(container)['rdb_saves'])
    if redis(container, 'BGSAVE') != 'Background saving started':
        raise RuntimeError('Redis no inició un snapshot nuevo; no copiar un RDB anterior')
    wait_for(container, lambda state: int(state['rdb_saves']) > before and
             state['rdb_bgsave_in_progress'] == '0' and state['rdb_last_bgsave_status'] == 'ok')
    partial = destination.with_name(destination.name + '.' + uuid4().hex + '.partial')
    try:
        docker('cp', f'{container}:/data/dump.rdb', str(partial))
        os.chmod(partial, 0o600)
        with partial.open('r+b') as saved:
            os.fsync(saved.fileno())
        digest = hashlib.sha256(partial.read_bytes()).hexdigest()
        # Hard-link creates the final name exclusively, never replacing another backup.
        os.link(partial, destination)
        metadata = {'format': 'redis-rdb-v1', 'sha256': digest, 'image': REDIS_IMAGE}
        with destination.with_suffix('.json').open('x') as output:
            os.chmod(output.name, 0o600)
            json.dump(metadata, output)
            output.flush()
            os.fsync(output.fileno())
        return metadata
    finally:
        partial.unlink(missing_ok=True)


def restore(snapshot, volume, secret):
    snapshot, secret = Path(snapshot).resolve(), Path(secret).resolve()
    meta = json.loads(snapshot.with_suffix('.json').read_text())
    if meta.get('format') != 'redis-rdb-v1' or meta.get('image') != REDIS_IMAGE \
            or hashlib.sha256(snapshot.read_bytes()).hexdigest() != meta.get('sha256'):
        raise ValueError('Backup sin identidad/checksum válido')
    if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}', volume):
        raise ValueError('Nombre de volumen inválido')
    if not re.fullmatch('[a-f0-9]{64}', secret.read_text()):
        raise ValueError('Archivo de secreto inválido')
    if volume in docker('volume', 'ls', '--format', '{{.Name}}').splitlines():
        raise ValueError('Restaurar exige un volumen nuevo, nunca limpiar uno existente')
    identity = uuid4().hex
    docker('volume', 'create', '--label', 'com.jjt.sni56.restore=' + identity, volume)
    actual = json.loads(docker('volume', 'inspect', volume))[0]
    if actual.get('Labels', {}).get('com.jjt.sni56.restore') != identity:
        raise ValueError('El volumen no pertenece a esta restauración')
    folder = ROOT / '.sni56' / identity
    # These files contain only public configuration, never credentials. Redis drops to uid 999.
    folder.mkdir(parents=True, mode=0o755)
    config = folder / 'redis.conf'
    config.write_text((ROOT / 'redis/redis.conf').read_text().replace('appendonly yes', 'appendonly no'))
    config.chmod(0o644)
    for name in ('entrypoint.sh', 'healthcheck.sh', 'cli.sh'):
        (folder / name).write_bytes((ROOT / 'redis' / name).read_bytes())
    container = 'sni56-restore-' + identity
    created = False
    try:
        docker('create', '--name', container, '--network', 'none', '--memory', '384m',
               '--mount', f'type=volume,source={volume},target=/data',
               '--mount', f'type=bind,source={folder},target=/etc/redis,readonly',
               '--mount', f'type=bind,source={secret},target=/run/secrets/redis_password,readonly',
               '--tmpfs', '/run/redis:rw,noexec,nosuid,size=1m',
               '--entrypoint', 'sh', REDIS_IMAGE, '/etc/redis/entrypoint.sh')
        created = True
        docker('cp', str(snapshot), f'{container}:/data/dump.rdb')
        docker('start', container)
        until = time.monotonic() + 30
        while time.monotonic() < until:
            try:
                if redis(container, 'PING') == 'PONG':
                    break
            except RuntimeError:
                pass  # Only bounded startup polling; no restore is declared healthy from an error.
            time.sleep(.2)
        else:
            raise RuntimeError('Redis restaurado no respondió')
        # Load RDB without AOF first; otherwise an AOF may mask/ignore the restored snapshot.
        if redis(container, 'CONFIG', 'SET', 'appendonly', 'yes') != 'OK':
            raise RuntimeError('No se habilitó AOF después de cargar el RDB')
        wait_for(container, lambda state: state['aof_enabled'] == '1' and
                 state['aof_rewrite_in_progress'] == '0' and state['aof_last_bgrewrite_status'] == 'ok'
                 and int(state['aof_base_size']) > 0)
        docker('stop', '--time', '15', container)
        print('Restauración preparada en volumen nuevo; conectar sólo mediante cambio operativo revisado.')
    finally:
        if created:
            docker('rm', '-f', container)
        config.unlink(missing_ok=True)
        for name in ('entrypoint.sh', 'healthcheck.sh', 'cli.sh'):
            (folder / name).unlink(missing_ok=True)
        # Deliberately retain the new volume on success AND failure; no destructive auto-repair.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    save = modes.add_parser('backup')
    save.add_argument('container')
    save.add_argument('destination', type=Path)
    load = modes.add_parser('restore')
    load.add_argument('snapshot', type=Path)
    load.add_argument('new_volume')
    load.add_argument('secret_file', type=Path)
    args = parser.parse_args()
    if args.mode == 'backup':
        backup(args.container, args.destination)
        print('Snapshot exportado y checksum registrado; copiar fuera de la VM para cubrir pérdida del host.')
    else:
        restore(args.snapshot, args.new_volume, args.secret_file)
