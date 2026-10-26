"""Read-only SQL/health checks in both environments; HTTP contract writes only in dev."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from stack_release import STACK_SERVICES as SERVICES, DATABASE_SERVICES, permanent_services, storage_provider
PROBE_IMAGE = 'python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a'


def container(stack, service):
    ids = subprocess.check_output(['docker', 'ps', '-q', '--filter', f'label=com.docker.swarm.service.name={stack}_{service}', '--filter', 'status=running'], text=True, timeout=30).split()
    if len(ids) != 1:
        raise RuntimeError(f'{service}: se requiere una tarea running')
    return ids[0]


def sql(stack, service, query):
    result = subprocess.check_output(['docker', 'exec', '-i', container(stack, service), 'sh', '-ec',
        'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At'],
        input=query, text=True, timeout=30)
    return result.strip()


def verify(stack):
    if stack not in ('snippet-searcher-dev', 'snippet-searcher-prod'):
        raise ValueError('Stack inesperado')
    release = json.loads(os.environ['SNIPPET_RELEASE']) if os.environ.get('SNIPPET_RELEASE') else None
    application = os.environ.get('VERIFY_APPLICATION') or None
    selected = permanent_services(release, application) if release else SERVICES
    deadline = time.monotonic() + 120
    while True:
        health = {service: json.loads(subprocess.check_output(['docker', 'inspect', container(stack, service)], text=True, timeout=30))[0]['State'].get('Health', {}).get('Status') for service in selected}
        if all(status == 'healthy' for status in health.values()):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f'Healthchecks no saludables: {health}')
        time.sleep(5)
    for service in DATABASE_SERVICES if application != 'ui' else ():
        assert sql(stack, service, 'SELECT current_database();') == service.removesuffix('-db')
        migrations = sql(stack, service, 'SELECT count(*) FROM flyway_schema_history WHERE success;')
        if int(migrations) < 1:
            raise RuntimeError(f'{service}: faltan migraciones de la aplicación')
        print(f'PASS SQL autenticado {service}; migraciones={migrations}', flush=True)
    # Check storage permission as the actual non-root user without writing content.
    if application != 'ui' and (release is None or storage_provider(release) == 'local'):
        subprocess.run(['docker', 'exec', container(stack, 'snippets-service'), 'sh', '-ec',
                        'test "$(id -u)" = 10001 && test -w "$STORAGE_LOCAL_DIRECTORY"'], check=True, timeout=30)
        print('PASS storage local montado y escribible para uid 10001', flush=True)
    # App startup log proves JDBC/Flyway, direct SQL above verifies both actual schemas.
    if application != 'ui':
        logs = subprocess.check_output(['docker', 'service', 'logs', '--tail', '200', f'{stack}_snippets-service'], stderr=subprocess.STDOUT, text=True, timeout=30)
        if 'jdbc:postgresql://snippets-db:5432/snippets' not in logs:
            raise RuntimeError('Falta evidencia JDBC/Flyway de Snippets')
    scripts = Path(__file__).resolve().parent
    probe = f'sni24-http-{uuid4().hex[:12]}'
    command = ['docker', 'service', 'create', '--detach', '--name', probe,
               '--restart-condition', 'none', '--read-only', '--network', f'{stack}_default', '--user', '10001:10001',
               '--mount', f'type=bind,source={scripts},target=/verification,readonly',
               '-e', 'PERMISSIONS_BASE_URL=http://permissions-service:8080',
               '-e', 'PRINTSCRIPT_BASE_URL=http://printscript-service:8080',
               '-e', 'SNIPPET_RELEASE=' + json.dumps(release or {}),
               '-e', 'VERIFY_APPLICATION=' + (application or ''),
               PROBE_IMAGE, 'python', '-B', '/verification/internal_http.py', stack]
    subprocess.run(command, check=True, timeout=30)
    try:
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            tasks = subprocess.check_output(['docker', 'service', 'ps', '-q', '--no-trunc', probe], text=True, timeout=30).split()
            if tasks:
                task = json.loads(subprocess.check_output(['docker', 'inspect', tasks[0]], text=True, timeout=30))[0]
                status = task['Status']['State']
                if status == 'complete':
                    subprocess.run(['docker', 'service', 'logs', probe], check=True, timeout=30)
                    return
                if status in ('failed', 'rejected'):
                    subprocess.run(['docker', 'service', 'logs', probe], timeout=30)
                    raise RuntimeError(f'HTTP probe failed ({status})')
            time.sleep(2)
        raise RuntimeError('HTTP probe timed out')
    finally:
        subprocess.run(['docker', 'service', 'rm', probe], check=True, timeout=30)



if __name__ == '__main__':
    try:
        verify(sys.argv[1])
    except (ValueError, RuntimeError, AssertionError, OSError, KeyError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f'FAIL verification: {error}', file=sys.stderr)
        sys.exit(1)
