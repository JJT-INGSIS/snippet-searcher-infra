#!/usr/bin/env python3
"""Run the DEV browser check and publish only its result through Event API."""

import fcntl
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
CONFIG = Path('/etc/snippet-observability/dev')
CREDENTIALS = CONFIG / 'functional-auth0.json'
NAME = 'snippet-searcher-dev-functional-listing'
IMAGE = 'cypress/included@sha256:2c4e24645ea2d2de59b001ec09de9817e7e13aca93cda8061b4f044d5321a038'
EVENT_URL = 'https://insights-collector.newrelic.com/v1/accounts/8718557/events'
FAILURE_STAGES = {'AUTH0_LOGIN', 'LISTING_HTTP', 'SNIPPET_MISSING', 'DETAIL_CONTENT'}
FIXTURE_STAGES = {'FIXTURE_MARKER', 'FIXTURE_SAVE', 'FIXTURE_RENAME'}


def provision_credentials():
    """Accept credentials on stdin and replace only this runner's private file."""
    credentials = json.loads(sys.stdin.buffer.read(8192))
    values = {name: credentials[name] for name in ('username', 'password')}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ValueError('invalid credentials')
    with tempfile.NamedTemporaryFile(mode='w', dir=CONFIG, delete=False) as target:
        temporary = Path(target.name)
        try:
            json.dump(values, target)
            target.close()
            temporary.replace(CREDENTIALS)
        finally:
            temporary.unlink(missing_ok=True)


def execute_check(fixture_action=None):
    if not CREDENTIALS.is_file():
        return 'FAILURE', 'CONFIGURATION'
    with tempfile.TemporaryDirectory(prefix='sni85-', dir='/run') as result:
        command = [
            '/usr/bin/docker', 'run', '--rm', '--pull=never', '--name', NAME,
            '--log-driver', 'none', '--network', 'host',
            '--add-host', 'jjt-snippets-dev.duckdns.org:127.0.0.1',
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--cpus', '1', '--memory', '1536m', '--memory-swap', '1536m', '--shm-size', '256m',
            '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=512m',
            '--env', 'HOME=/tmp', '--env', 'XDG_CACHE_HOME=/tmp/cache',
            '--env', 'CYPRESS_CACHE_FOLDER=/tmp/cypress-cache',
            '--env', 'CYPRESS_NO_COMMAND_LOG=1',
            '--mount', f'type=bind,src={PROJECT},dst=/check,readonly',
            '--mount', f'type=bind,src={CREDENTIALS},dst=/run/auth0.json,readonly',
            '--mount', f'type=bind,src={result},dst=/run/result',
        ]
        spec = 'functional.cy.js'
        if fixture_action:
            command.extend(['--env', f'SNI85_FIXTURE_ACTION={fixture_action}'])
            spec = 'fixture.cy.js'
        command.extend([
            '--workdir', '/check', '--entrypoint', '/bin/sh', IMAGE, '-ec',
            'umask 077; mkdir -p /tmp/cypress-cache/13.8.1; '
            'ln -s /root/.cache/Cypress/13.8.1/Cypress /tmp/cypress-cache/13.8.1/Cypress; '
            f'exec cypress run --browser electron --headless --spec {spec}',
        ])
        try:
            execution = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL, timeout=180, check=False)
        except subprocess.TimeoutExpired:
            subprocess.run(['/usr/bin/docker', 'rm', '-f', NAME], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15, check=False)
            return 'FAILURE', 'RUNNER'

        stage_path = Path(result) / 'stage'
        stage = stage_path.read_text() if stage_path.is_file() else ''
        if execution.returncode == 0 and stage == 'COMPLETE':
            return 'SUCCESS', 'NONE'
        permitted = FAILURE_STAGES | FIXTURE_STAGES if fixture_action else FAILURE_STAGES
        return 'FAILURE', stage if stage in permitted else 'RUNNER'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def publish(result, category, duration_ms):
    key = json.loads((CONFIG / 'agent.json').read_text())['license_key']
    event = {
        'eventType': 'SnippetFunctionalCheck',
        'environment': 'dev',
        'checkName': NAME,
        'result': result,
        'durationMs': duration_ms,
        'failureCategory': category,
    }
    request = urllib.request.Request(EVENT_URL, data=json.dumps([event]).encode(), method='POST',
                                     headers={'Api-Key': key, 'Content-Type': 'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
        receipt = json.load(response)
        if response.status != 200 or receipt.get('success') is not True or not receipt.get('uuid'):
            raise ValueError('event not acknowledged')


def run(fixture_action=None):
    with open(f'/run/lock/{NAME}.lock', 'a', encoding='utf8') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('SNI-85 check already running', file=sys.stderr)
            return 3

        started = time.monotonic_ns()
        try:
            result, category = execute_check(fixture_action)
        except (OSError, ValueError, subprocess.SubprocessError):
            result, category = 'FAILURE', 'RUNNER'
        duration_ms = (time.monotonic_ns() - started) // 1_000_000
        if fixture_action:
            print(f'SNI-85 fixture {fixture_action}: {result} {category}')
            return 0 if result == 'SUCCESS' else 1
        try:
            publish(result, category, duration_ms)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            print('SNI-85 Event API submission failed', file=sys.stderr)
            return 2
        print(f'SNI-85 Event API acknowledged: {result} {category} {duration_ms}ms')
        return 0 if result == 'SUCCESS' else 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--provision-credentials']:
        try:
            provision_credentials()
        except (OSError, TypeError, ValueError, KeyError):
            sys.exit('SNI-85 credential setup failed')
    elif not sys.argv[1:]:
        sys.exit(run())
    elif len(sys.argv) == 3 and sys.argv[1] == '--fixture' and sys.argv[2] in {'prepare', 'hide', 'restore'}:
        sys.exit(run(sys.argv[2]))
    else:
        sys.exit('Unsupported SNI-85 command')
