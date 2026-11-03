"""Read-only verification of the Redis-aware central CD release and its pinned tools."""
import base64
import json
import os
import re
import urllib.request

LEGACY_REVISION = '9fcc49204260566667171cdde320eea8f81c965d'
VERSION = 'v0.6.4'


def read_file(repository, path, revision):
    url = f'https://api.github.com/repos/JJT-INGSIS/{repository}/contents/{path}?ref={revision}'
    headers = {'Accept': 'application/vnd.github+json'}
    if os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            return base64.b64decode(json.load(response)['content']).decode()
    except Exception:
        raise ValueError('No se pudo verificar la release central y su infra fijada; no instalar Redis') from None


def require_redis_cd(reader=read_file):
    workflow = reader('github-workflows', '.github/workflows/cd.yml', VERSION)
    pins = re.findall(r'^  INFRA_REVISION: ([a-f0-9]{40})\r?$', workflow, re.MULTILINE)
    if len(pins) != 1 or pins[0] == LEGACY_REVISION:
        raise ValueError('El CD Redis requiere un SHA nuevo y completo de infraestructura')
    revision = pins[0]
    # Confirm the pinned scripts, rather than trusting a new workflow tag alone.
    for path, marker in (
            ('scripts/redis_runtime.py', 'def verify_effective('),
            ('scripts/stack_runtime.py', 'redis_transition'),
            ('scripts/stack_release.py', "'redis'"),
            ('scripts/ssh_deploy.py', "'redis_runtime.py'"),
            ('swarm/stack.redis.yaml', 'redis_password')):
        if marker not in reader('snippet-searcher-infra', path, revision):
            raise ValueError('El SHA del CD no contiene el contrato Redis requerido')
    return revision
