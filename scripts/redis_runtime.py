"""Explicit Redis component contract; no credential values in release records."""
import hashlib
import re
from pathlib import Path

REDIS_IMAGE = 'redis:7.4.7-alpine@sha256:02f2cc4882f8bf87c79a220ac958f58c700bdec0dfb9b9ea61b62fb0e8f1bfcf'
REDIS_FILES = {'redis_configuration': 'redis/redis.conf',
               'redis_entrypoint': 'redis/entrypoint.sh', 'redis_healthcheck': 'redis/healthcheck.sh'}


def specification(environment, version=1):
    root = Path(__file__).resolve().parent.parent
    return {'image': REDIS_IMAGE, 'configs': {
        key: {'name': f'snippet-searcher-{environment}_{key}_v{version}',
              'sha256': hashlib.sha256((root / file).read_bytes()).hexdigest()}
        for key, file in REDIS_FILES.items()}}


def validate(spec, environment):
    if set(spec) != {'image', 'configs'} or spec.get('image') != REDIS_IMAGE:
        raise ValueError('Redis requiere imagen/configuración revisada')
    configs = spec.get('configs')
    if not isinstance(configs, dict) or set(configs) != set(REDIS_FILES):
        raise ValueError('Redis requiere todas las configs inmutables')
    for key, item in configs.items():
        if not isinstance(item, dict) or set(item) != {'name', 'sha256'} or not isinstance(item['name'], str) \
                or not re.fullmatch(f'snippet-searcher-{environment}_{key}_v[1-9][0-9]*', item['name']) \
                or not isinstance(item['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['sha256']):
            raise ValueError('Config Redis sin identidad revisada')


def config_files(release):
    from stack_release import infrastructure, NGINX_FILES
    components = infrastructure(release)
    result = {}
    for component, files in (('nginx', NGINX_FILES), ('redis', REDIS_FILES)):
        for key, spec in components.get(component, {}).get('configs', {}).items():
            result[key] = (spec, files[key])
    return result


def verify_effective(release, docker_json, application=None):
    stack = f'snippet-searcher-{release["environment"]}'
    # Independent deploys preserve the installed Redis component, even for UI/Permissions.
    current = docker_json('service', 'inspect', f'{stack}_redis')[0]
    spec = current['Spec']
    container = spec['TaskTemplate']['ContainerSpec']
    if spec.get('Mode', {}).get('Replicated', {}).get('Replicas') != 1:
        raise ValueError('Redis debe conservar una sola réplica')
    if spec.get('UpdateConfig', {}).get('Order') != 'stop-first' \
            or spec.get('RollbackConfig', {}).get('Order') != 'stop-first':
        raise ValueError('Redis no conserva reemplazo seguro')
    if current.get('Endpoint', {}).get('Ports') or spec.get('EndpointSpec', {}).get('Ports'):
        raise ValueError('Redis no puede publicar puertos')
    if container.get('Args') or container.get('Command') != ['sh', '/etc/redis/entrypoint.sh']:
        raise ValueError('Comando Redis no revisado')
    if any(any(word in item.split('=', 1)[0] for word in ('PASSWORD', 'TOKEN', 'AUTH'))
           for item in container.get('Env', [])):
        raise ValueError('Credencial Redis en environment inspeccionable')
    configs = {item['ConfigName'] for item in container.get('Configs', [])}
    expected = {item['name'] for item in release['infrastructure']['redis']['configs'].values()}
    if configs != expected:
        raise ValueError('Redis no conserva configs registradas')
    secrets = {(item['SecretName'], item['File']['Name']) for item in container.get('Secrets', [])}
    if secrets != {('redis_password', 'redis_password')}:
        raise ValueError('Redis no usa el secreto por archivo')
    if spec['TaskTemplate'].get('Resources', {}).get('Limits', {}).get('MemoryBytes') != 384 * 1024 * 1024:
        raise ValueError('Redis no conserva el límite de memoria')
    if spec['TaskTemplate']['Resources']['Limits'].get('NanoCPUs') != 500000000:
        raise ValueError('Redis no conserva el límite de CPU')
    if container.get('Healthcheck', {}).get('Test') != ['CMD', 'sh', '/etc/redis/healthcheck.sh']:
        raise ValueError('Redis no conserva el healthcheck autenticado')
    networks = spec['TaskTemplate'].get('Networks', [])
    if len(networks) != 1:
        raise ValueError('Redis requiere una única red interna')
    network_id = networks[0]['Target']
    if not docker_json('network', 'inspect', network_id)[0].get('Internal'):
        raise ValueError('La red efectiva de Redis no es interna')
    for name in ('snippets-service', 'printscript-service'):
        app = docker_json('service', 'inspect', f'{stack}_{name}')[0]['Spec']
        if app.get('Mode', {}).get('Replicated', {}).get('Replicas') != 1 \
                or app.get('UpdateConfig', {}).get('Order') != 'stop-first' \
                or app.get('RollbackConfig', {}).get('Order') != 'stop-first':
            raise ValueError('Coordinador con réplicas solapadas')
    snippets = docker_json('service', 'inspect', f'{stack}_snippets-service')[0]['Spec']['TaskTemplate']['ContainerSpec']
    snip_networks = docker_json('service', 'inspect', f'{stack}_snippets-service')[0]['Spec']['TaskTemplate']['Networks']
    if network_id not in {item['Target'] for item in snip_networks}:
        raise ValueError('Snippets no está conectado a la red Redis')
    env = dict(item.split('=', 1) for item in snippets.get('Env', []))
    if env.get('SPRING_DATA_REDIS_HOST') != 'redis' or env.get('SPRING_DATA_REDIS_PORT') != '6379' \
            or 'SPRING_DATA_REDIS_PASSWORD' in env:
        raise ValueError('Conexión Redis distinta de la revisada')
    if ('redis_password', 'spring.data.redis.password') not in {
            (item['SecretName'], item['File']['Name']) for item in snippets.get('Secrets', [])}:
        raise ValueError('Snippets no usa el secreto Redis por archivo')
