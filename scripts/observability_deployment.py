"""Read-only compatibility with the explicitly provisioned DEV monitor."""

import base64
import hashlib
from pathlib import Path

MARKER = Path('/etc/snippet-observability/dev/provisioned')
ENTRYPOINT = Path(__file__).resolve().parent.parent / 'redis/entrypoint.sh'


def installed(environment):
    if environment != 'dev' or not MARKER.exists():
        return False
    if MARKER.read_text() != 'sni82-runtime-v1\n':
        raise ValueError('Runtime de observabilidad desconocido; reconciliar antes de desplegar')
    return True


def redis_configs(expected, container, docker_json):
    """Allow only the reviewed entrypoint substitution, never arbitrary drift."""
    digest = hashlib.sha256(ENTRYPOINT.read_bytes()).hexdigest()
    name = 'snippet-observability-dev-redis-entrypoint-' + digest[:12]
    entries = container.get('Configs', [])
    replaced = [item for item in entries if item.get('ConfigName') == name]
    if len(replaced) != 1 or replaced[0].get('File', {}).get('Name') != '/etc/redis/entrypoint.sh':
        raise ValueError('Redis no conserva el entrypoint de monitoreo revisado')
    actual = docker_json('config', 'inspect', name)[0]
    content = base64.b64decode(actual['Spec']['Data'], validate=True)
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('Contenido del entrypoint de monitoreo distinto del revisado')
    return {**expected, 'redis_entrypoint': {'name': name, 'sha256': digest}}


def require_aliases(stack, docker_json):
    for service, suffix in (('snippets-db', 'default'), ('permissions-db', 'default'), ('redis', 'redis_internal')):
        network = docker_json('network', 'inspect', stack + '_' + suffix)[0]['Id']
        current = docker_json('service', 'inspect', stack + '_' + service)[0]
        attachments = current['Spec']['TaskTemplate'].get('Networks', [])
        if not any(item['Target'] == network and 'dev-' + service in item.get('Aliases', []) for item in attachments):
            raise ValueError('Alias privado de monitoreo ausente: ' + service)


def require_reconciled_stack(environment):
    if installed(environment):
        raise ValueError('Monitoreo DEV instalado: reconciliar el manifiesto antes de reaplicar el stack; no se modificó ningún servicio')
