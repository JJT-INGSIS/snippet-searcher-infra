"""Controlled database task replacement; compare actual table and content fingerprints."""
import fcntl
import json
import os
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path
from verify_stack import container, sql
from stack_release import DATABASE_SERVICES


def database_snapshot(stack, service):
    names = sql(stack, service, "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name;").splitlines()
    if not names:
        raise RuntimeError('No application tables found')
    if any(not re.fullmatch('[a-z_][a-z_0-9]*', name) for name in names):
        raise RuntimeError('Unexpected table name')
    return {name: sql(stack, service, f'''SELECT count(*) || ':' || md5(COALESCE(string_agg(row_to_json(t)::text, '' ORDER BY row_to_json(t)::text), '')) FROM "{name}" t;''') for name in names}


def content_snapshot(stack):
    return subprocess.check_output(['docker','exec',container(stack,'snippets-service'),'sh','-ec',
        'find "$STORAGE_LOCAL_DIRECTORY" -type f -exec sha256sum {} \\; | sort'],text=True,timeout=30)


def wait_database(stack, service):
    for attempt in range(90):
        try:
            inspected=json.loads(subprocess.check_output(['docker','inspect',container(stack,service)],text=True,timeout=30))[0]
            if inspected['State'].get('Health',{}).get('Status')=='healthy':
                return
        except (RuntimeError, subprocess.CalledProcessError):
            pass
        time.sleep(2)
    raise RuntimeError(f'{service}: not healthy after recreation')


def verify(stack):
    if stack not in ('snippet-searcher-dev','snippet-searcher-prod'):
        raise ValueError('Unexpected stack')
    environment=stack.removeprefix('snippet-searcher-')
    owner=pwd.getpwnam(os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    state=Path(owner.pw_dir)/f'.local/state/snippet-searcher/{environment}'
    with (state/'deploy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        content_before=content_snapshot(stack)
        for service in DATABASE_SERVICES:
            before=database_snapshot(stack,service)
            old_id=container(stack,service)
            subprocess.run(['docker','service','update','--detach','--force',f'{stack}_{service}'],check=True,timeout=30)
            # Docker may still show the previous healthy task briefly.
            for attempt in range(90):
                try:
                    if container(stack,service)!=old_id: break
                except RuntimeError: pass
                time.sleep(2)
            wait_database(stack,service)
            if container(stack,service)==old_id or database_snapshot(stack,service)!=before:
                raise RuntimeError(f'{service}: task not replaced or stored data changed')
            print(f'PASS persistence {service}: new task, identical {len(before)} table snapshots',flush=True)
        if content_snapshot(stack)!=content_before:
            raise RuntimeError('Snippet content changed during database recreation')
        print('PASS snippet content fingerprints preserved',flush=True)


if __name__=='__main__':
    verify(sys.argv[1])
