"""Run an authenticated SNI-87 DEV operation; never print Cypress logs or JWTs."""

import argparse
import fcntl
import json
import os
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

IMAGE = 'cypress/included@sha256:2c4e24645ea2d2de59b001ec09de9817e7e13aca93cda8061b4f044d5321a038'
PROJECT = Path(__file__).resolve().parents[1] / 'observability'
CREDENTIALS = Path('/etc/snippet-observability/dev/functional-auth0.json')
NAME = 'snippet-searcher-dev-sni87-drill'
RULES = Path('/var/tmp/sni87-20261119-rules-before.json')
RECEIPTS = Path('/var/tmp/sni87-20261119-evidence.jsonl')
SCENARIOS = ('healthy-create', 'printscript-unavailable', 'enqueue-format', 'job-status', 'restore-format',
             'business-rejections')


def authenticated_injection(command, result):
    browser = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 110
        ready = Path(result) / 'cut-requested'
        while browser.poll() is None and not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if not ready.exists():
            raise ValueError('Browser did not become ready; PrintScript was not interrupted')
        service = 'snippet-searcher-dev_printscript-service'
        specification = json.loads(subprocess.check_output(['docker', 'service', 'inspect', service], text=True, timeout=15))[0]
        if specification['Spec']['Mode']['Replicated']['Replicas'] != 1:
            raise ValueError('PrintScript must have its original replica before injection')
        subprocess.run(['docker', 'service', 'scale', '--detach=true', service + '=0'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        deadline = time.monotonic() + 20
        while subprocess.check_output(['docker', 'service', 'ps', service, '--filter', 'desired-state=running',
                                       '--format', '{{.ID}}'], text=True, timeout=10).strip():
            if time.monotonic() >= deadline:
                raise ValueError('PrintScript did not converge to zero replicas')
            time.sleep(0.2)
        print(json.dumps({'step': 'printscript-cut', 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}), flush=True)
        (Path(result) / 'cut-complete').touch(mode=0o600)
        return subprocess.CompletedProcess(command, browser.wait(timeout=80))
    finally:
        if browser.poll() is None:
            subprocess.run(['docker', 'rm', '-f', NAME], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15, check=False)
            browser.wait(timeout=15)


def run(scenario, job_id=None, inject_printscript=False):
    if scenario not in SCENARIOS:
        raise ValueError('Unsupported scenario')
    if socket.gethostname() != 'vm-snippet-dev' or not CREDENTIALS.is_file():
        raise ValueError('This runner requires the DEV VM and its dedicated identity')
    if scenario == 'job-status' and (not job_id or str(uuid.UUID(job_id)) != job_id):
        raise ValueError('Canonical job UUID required')
    if scenario == 'enqueue-format' and RULES.exists():
        raise ValueError('Rule snapshot already exists; do not overwrite the original')
    if scenario == 'restore-format' and not RULES.is_file():
        raise ValueError('Rule snapshot missing; cannot invent the original')
    if (scenario == 'printscript-unavailable') != inject_printscript:
        raise ValueError('PrintScript drill requires explicit injection and a restoration timer')
    if inject_printscript:
        subprocess.run(['systemctl', 'is-active', '--quiet', 'sni87-printscript-restore-20261119b.timer'],
                       check=True, timeout=10)
    with open('/run/lock/' + NAME + '.lock', 'a', encoding='utf8') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix='sni87-', dir='/run') as result:
            command = [
                'docker', 'run', '--rm', '--pull=never', '--name', NAME, '--log-driver', 'none',
                '--network', 'host', '--add-host', 'jjt-snippets-dev.duckdns.org:127.0.0.1',
                '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--cpus', '1', '--memory', '1536m', '--memory-swap', '1536m', '--shm-size', '256m',
                '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=512m',
                '--env', 'HOME=/tmp', '--env', 'XDG_CACHE_HOME=/tmp/cache',
                '--env', 'CYPRESS_CACHE_FOLDER=/tmp/cypress-cache', '--env', 'CYPRESS_NO_COMMAND_LOG=1',
                '--env', 'SNI87_SCENARIO=' + scenario, '--env', 'SNI87_JOB_ID=' + (job_id or ''),
                '--mount', f'type=bind,src={PROJECT},dst=/check,readonly',
                '--mount', f'type=bind,src={CREDENTIALS},dst=/run/auth0.json,readonly',
                '--mount', f'type=bind,src={result},dst=/run/result',
                '--workdir', '/check/drills', '--entrypoint', '/bin/sh', IMAGE, '-ec',
                'umask 077; mkdir -p /tmp/cypress-cache/13.8.1; '
                'ln -s /root/.cache/Cypress/13.8.1/Cypress /tmp/cypress-cache/13.8.1/Cypress; '
                'exec cypress run --browser electron --headless',
            ]
            if scenario == 'restore-format':
                command[2:2] = ['--mount', f'type=bind,src={RULES},dst=/run/rules-before.json,readonly']
            try:
                if inject_printscript:
                    execution = authenticated_injection(command, result)
                else:
                    execution = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               stdin=subprocess.DEVNULL, timeout=180, check=False)
            except subprocess.TimeoutExpired:
                subprocess.run(['docker', 'rm', '-f', NAME], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, check=False)
                raise ValueError('Browser drill timed out; no automatic mutation retry') from None
            evidence = Path(result) / 'evidence.jsonl'
            snapshot = Path(result) / 'rules-before.json'
            if snapshot.is_file():
                with RULES.open('x', encoding='utf8') as target:
                    RULES.chmod(0o600)
                    target.write(snapshot.read_text())
            if evidence.is_file():
                for line in evidence.read_text().splitlines():
                    receipt = json.dumps(json.loads(line), separators=(',', ':'))
                    descriptor = os.open(RECEIPTS, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(descriptor, 'a', encoding='utf8') as target:
                        if os.fstat(target.fileno()).st_uid != os.geteuid():
                            raise ValueError('Evidence file has an unexpected owner')
                        target.write(receipt + '\n')
                    print(receipt)
            if execution.returncode:
                stage = Path(result) / 'stage'
                value = stage.read_text() if stage.is_file() else 'START'
                raise ValueError('Browser drill failed at ' + value + '; Cypress logs were discarded')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=SCENARIOS)
    parser.add_argument('--job-id')
    parser.add_argument('--inject-printscript', action='store_true')
    args = parser.parse_args()
    try:
        run(args.scenario, args.job_id, args.inject_printscript)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
