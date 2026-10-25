"""Strict SSH transport; token travels on stdin and is never uploaded to disk."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

from github_cd import operation_id, validate_request

BUNDLE_SCRIPTS = ('deploy_service.py', 'github_cd.py', 'stack_release.py', 'wait_for_stack.py',
                  'verify_stack.py', 'internal_http.py', 'smoke_tests.py', 'bootstrap_swarm.py',
                  'stack_runtime.py', 'rollout_checks.py', 'validate_asset_config.py', 'asset_probe.py')
BUNDLE_FILES = ('swarm/stack.yaml', 'swarm/stack.ingress.yaml', 'swarm/stack.asset.yaml',
                'swarm/stack.ui.yaml', 'nginx/nginx.conf', 'nginx/templates/ingress.conf.template', 'nginx/validate-env.sh')


def connection_options(host, user, port, directory):
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
        raise ValueError('Host o usuario SSH inválido')
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('Puerto SSH inválido')
    private = directory / 'key'
    hosts = directory / 'known_hosts'
    private.write_text(os.environ['SSH_PRIVATE_KEY'] + '\n')
    hosts.write_text(os.environ['SSH_KNOWN_HOSTS'] + '\n')
    private.chmod(0o600)
    hosts.chmod(0o600)
    if not os.environ['SSH_PRIVATE_KEY'].strip() or not os.environ['SSH_KNOWN_HOSTS'].strip():
        raise ValueError('Secrets SSH ausentes en el environment ejecutor')
    common = ['-i', str(private), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
              '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={hosts}',
              '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=15',
              '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4']
    return ['ssh', '-p', port, *common], ['scp', '-P', port, *common], f'{user}@{host}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    request = validate_request(json.loads(args.request.read_text()))
    revision = os.environ['INFRA_REVISION']
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('Fijar INFRA_REVISION al commit integrado de SNI-25 antes de habilitar CD')
    user = os.environ['SSH_USER']
    with tempfile.TemporaryDirectory(prefix='sni25-ssh-') as temporary:
        directory = Path(temporary)
        ssh, scp, destination = connection_options(os.environ['SSH_HOST'], user,
                                                 os.environ['SSH_PORT'], directory)
        remote = f'/home/{user}/.local/share/snippet-searcher/cd/{revision}'
        subprocess.run([*ssh, destination, f'umask 077; mkdir -p {remote}'], check=True, timeout=30)
        bundle = directory / 'scripts.tar'
        with tarfile.open(bundle, 'w') as archive:
            for name in BUNDLE_SCRIPTS:
                path = Path(__file__).resolve().parent / name
                if path.is_symlink():
                    raise ValueError('No se permiten enlaces en el bundle de scripts')
                archive.add(path, arcname=f'scripts/{path.name}', recursive=False)
            for relative in BUNDLE_FILES:
                path = Path(__file__).resolve().parent.parent / relative
                if path.is_symlink():
                    raise ValueError('No se permiten enlaces en recursos del bundle')
                archive.add(path, arcname=relative, recursive=False)
        # Serialize bundle installation too: another service can use this revision.
        identity = operation_id(request)
        uploaded = f'{remote}/{identity}.tar'
        subprocess.run([*scp, str(bundle), f'{destination}:{uploaded}'], check=True, timeout=60)
        subprocess.run([*ssh, destination,
                        f'flock {remote}/install.lock tar -xf {uploaded} -C {remote} && rm -f {uploaded}'],
                       check=True, timeout=60)
        envelope = json.dumps({'request': request, 'token': os.environ.get('GH_TOKEN', '')})
        command = [*ssh, destination,
                   f'sudo -n python3 -B {remote}/scripts/deploy_service.py']
        # Retry the same identity after transport loss. The VM journal, not the
        # SSH exit code, determines whether to verify, recover, or submit an update.
        for attempt in range(2):
            try:
                result = subprocess.run(command, input=envelope, text=True, timeout=3600)
            except subprocess.TimeoutExpired:
                result = subprocess.CompletedProcess(command, 255)
            if result.returncode != 255 or attempt == 1:
                break
        state = f'/home/{user}/.local/state/snippet-searcher/{request["environment"]}'
        operation_file = directory / 'operation.json'
        subprocess.run([*scp, f'{destination}:{state}/operations/{identity}.json', str(operation_file)],
                       check=True, timeout=30)
        operation = json.loads(operation_file.read_text())
        if operation['request'] != request:
            raise ValueError('El recibo remoto no corresponde a esta ejecución')
        receipt = operation.get('receipt')
        if receipt:
            args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
        if not receipt or operation.get('state') != 'verified' or result.returncode != 0:
            raise RuntimeError('Despliegue no confirmado; revisar el diario y la recuperación en la VM')
        print(f'Despliegue verificado: {request["service"]} en {request["environment"]}, {request["image-ref"]}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f'FAIL SSH deploy: {error}', file=sys.stderr)
        sys.exit(1)
