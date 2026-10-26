"""Let's Encrypt for the NGINX ingress: one-shot Certbot container, locked reload, real expiry."""
import argparse
import fcntl
import json
import os
import pwd
import socket
import ssl
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from stack_release import CERTIFICATES

CERTBOT_IMAGE = 'certbot/certbot:v5.8.0@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20'
PEM_END = '-----END CERTIFICATE-----'


def state_directory(environment):
    owner = pwd.getpwnam(os.environ.get('SUDO_USER') or 'azureuser')
    return Path(owner.pw_dir) / '.local/state/snippet-searcher' / environment


def registered_proxy(environment):
    release = json.loads((state_directory(environment) / 'release.json').read_text())
    proxy = release.get('infrastructure', {}).get('nginx')
    if release.get('environment') != environment or not proxy:
        raise ValueError('El ambiente no tiene NGINX registrado; instalar el ingreso HTTP antes de emitir')
    return proxy


def certbot(environment, *arguments):
    return ['docker', 'run', '--rm', '--name', f'snippet-searcher-{environment}-certbot',
            '-v', f'{CERTIFICATES.format(environment=environment)}:/etc/letsencrypt',
            '-v', f'snippet-searcher-{environment}_ingress_acme:/var/www/acme',
            CERTBOT_IMAGE, *arguments, '--non-interactive']


def issue_arguments(hostname, staging, replace):
    arguments = ['certonly', '--webroot', '-w', '/var/www/acme', '-d', hostname, '--cert-name', hostname,
                 '--agree-tos', '--register-unsafely-without-email']
    return arguments + (['--staging'] if staging else []) + (['--force-renewal'] if replace else [])


def certificate(environment, hostname):
    chain = Path(CERTIFICATES.format(environment=environment)) / 'live' / hostname / 'fullchain.pem'
    return chain.read_text() if chain.is_file() else None


def leaf(chain):
    return chain[:chain.index(PEM_END) + len(PEM_END)] + '\n'


def describe(chain):
    output = subprocess.run(['openssl', 'x509', '-noout', '-issuer', '-enddate'], input=leaf(chain),
                            capture_output=True, text=True, check=True, timeout=30).stdout
    fields = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    return fields['issuer'].strip(), fields['notAfter'].strip()


def is_staging(chain):
    return '(STAGING)' in describe(chain)[0]


def report(hostname, chain):
    issuer, expiry = describe(chain)
    print(f'Certificado {hostname}: emisor {issuer}; vence {expiry}', flush=True)


def served(hostname):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection(('127.0.0.1', 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=hostname) as secured:
            return secured.getpeercert(binary_form=True)


def reload_proxy(environment, hostname, chain):
    tasks = subprocess.check_output(['docker', 'ps', '-q', '--filter',
                                     f'label=com.docker.swarm.service.name=snippet-searcher-{environment}_nginx'],
                                    text=True, timeout=30).split()
    if len(tasks) != 1:
        raise RuntimeError('Se esperaba exactamente una tarea NGINX en ejecución')
    subprocess.run(['docker', 'exec', tasks[0], 'nginx', '-t'], check=True, timeout=30)
    subprocess.run(['docker', 'exec', tasks[0], 'nginx', '-s', 'reload'], check=True, timeout=30)
    expected = ssl.PEM_cert_to_DER_cert(leaf(chain))
    deadline = time.monotonic() + 30
    while served(hostname) != expected:
        if time.monotonic() >= deadline:
            raise RuntimeError('NGINX recargó pero no sirve el certificado del disco')
        time.sleep(2)
    print('NGINX recargado: sirve el certificado del disco, sin reiniciar tareas', flush=True)


@contextmanager
def locked(environment):
    state = state_directory(environment)
    with (state / 'deploy.lock').open('r') as lock:
        deadline = time.monotonic() + 1800
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Timeout esperando el bloqueo del ambiente') from None
                time.sleep(5)
        if (state / 'pending.json').exists():
            raise RuntimeError('Hay una operación de despliegue pendiente; reconciliarla antes de tocar certificados')
        yield


def issue(environment, staging):
    proxy = registered_proxy(environment)
    hostname = proxy['hostname']
    with locked(environment):
        current = certificate(environment, hostname)
        current_staging = current is not None and is_staging(current)
        if current is not None and not current_staging and not staging:
            raise ValueError('Ya hay un certificado de producción; renovarlo con renew, no repetir la emisión')
        if current is not None and not current_staging and staging:
            raise ValueError('No reemplazar un certificado de producción por uno de staging')
        subprocess.run(certbot(environment, *issue_arguments(hostname, staging, current_staging and not staging)),
                       check=True, timeout=600)
        chain = certificate(environment, hostname)
        report(hostname, chain)
        if proxy['tls']:
            reload_proxy(environment, hostname, chain)


def renew(environment, dry_run):
    proxy = registered_proxy(environment)
    hostname = proxy['hostname']
    with locked(environment):
        before = certificate(environment, hostname)
        if before is None:
            raise ValueError('No hay certificado emitido para el ambiente; emitir con issue')
        arguments = ['renew', '--cert-name', hostname] + (['--dry-run'] if dry_run else [])
        if subprocess.run(certbot(environment, *arguments), timeout=600).returncode != 0:
            raise RuntimeError(f'Renovación fallida; se conserva el certificado vigente, que vence {describe(before)[1]}')
        after = certificate(environment, hostname)
        if after != before and proxy['tls']:
            reload_proxy(environment, hostname, after)
        report(hostname, after)


def reload_only(environment):
    proxy = registered_proxy(environment)
    if not proxy['tls']:
        raise ValueError('NGINX todavía no publica 443; no hay certificado que recargar')
    with locked(environment):
        reload_proxy(environment, proxy['hostname'], certificate(environment, proxy['hostname']))


def status(environment):
    proxy = registered_proxy(environment)
    chain = certificate(environment, proxy['hostname'])
    if chain is None:
        raise ValueError('No hay certificado emitido para el ambiente')
    report(proxy['hostname'], chain)
    if proxy['tls']:
        same = served(proxy['hostname']) == ssl.PEM_cert_to_DER_cert(leaf(chain))
        print('NGINX sirve el certificado del disco' if same else 'NGINX sirve OTRO certificado: recargar', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('issue', 'renew', 'reload', 'status'))
    parser.add_argument('environment', choices=('dev', 'prod'))
    parser.add_argument('--staging', action='store_true', help='issue: autoridad de prueba, no confiable')
    parser.add_argument('--dry-run', action='store_true', help='renew: prueba contra staging sin guardar nada')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Ejecutar con sudo: los certificados y la cuenta ACME son sólo de root')
    if args.command == 'issue':
        issue(args.environment, args.staging)
    elif args.command == 'renew':
        renew(args.environment, args.dry_run)
    elif args.command == 'reload':
        reload_only(args.environment)
    else:
        status(args.environment)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, ssl.SSLError, subprocess.SubprocessError) as error:
        print(f'FAIL certificados: {error}', file=sys.stderr)
        sys.exit(1)
