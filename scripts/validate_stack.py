"""CI validation with public immutable references and no real secrets or VM access."""
import json
import os
import subprocess
from pathlib import Path
from stack_release import validate_manifest

ROOT = Path(__file__).resolve().parent.parent
for environment in ('dev', 'prod'):
    manifest = json.loads((ROOT / f'swarm/{environment}-release.json').read_text())
    selected = validate_manifest(manifest)
    subprocess.run(['docker', 'stack', 'config', '-c', str(ROOT / 'swarm/stack.yaml')],
                   env={**os.environ, **selected}, check=True, stdout=subprocess.DEVNULL)
    print(f'PASS stack configuration {environment}')
