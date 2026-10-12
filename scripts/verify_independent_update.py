"""Exercise one app update with a verified alternative digest; prove other tasks stay put."""
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path
from stack_release import validate_manifest
from verify_stack import SERVICES, container


def verify(candidate_path, service):
    candidate=json.loads(candidate_path.read_text())
    validate_manifest(candidate)
    if candidate['environment']!='dev' or service not in SERVICES[:3]:
        raise ValueError('This controlled update test is dev only')
    owner=pwd.getpwnam(os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    record_path=Path(owner.pw_dir)/'.local/state/snippet-searcher/dev/release.json'
    previous=json.loads(record_path.read_text())
    if previous['images'][service]==candidate['images'][service]:
        raise ValueError('Select a distinct, verified digest to demonstrate actual task replacement')
    stack='snippet-searcher-dev'
    before={name:container(stack,name) for name in SERVICES}
    bootstrap=Path(__file__).with_name('bootstrap_swarm.py')
    subprocess.run([sys.executable,str(bootstrap),'deploy',str(candidate_path),'--service',service],check=True)
    after={name:container(stack,name) for name in SERVICES}
    if before[service]==after[service] or any(before[name]!=after[name] for name in SERVICES if name!=service):
        raise RuntimeError('Target did not change or other application/database tasks were recreated')
    current=json.loads(record_path.read_text())
    for name in current['images']:
        if name!=service and current['images'][name]!=previous['images'][name]:
            raise RuntimeError('Other recorded image changed')
    print(f'PASS independent update {service}; four other tasks and references preserved',flush=True)
    # Reapply the original baseline manifest: the record must prevent rollback.
    subprocess.run([sys.executable,str(bootstrap),'deploy',str(bootstrap.parent.parent/'swarm/dev-release.json')],check=True)
    reapplied={name:container(stack,name) for name in SERVICES}
    latest=json.loads(record_path.read_text())
    if reapplied!=after or latest['images']!=current['images']:
        raise RuntimeError('Reapplying infrastructure reset references or recreated tasks')
    print('PASS reapply stale baseline: current references and all five task IDs preserved',flush=True)


if __name__=='__main__':
    verify(Path(sys.argv[1]),sys.argv[2])
