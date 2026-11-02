"""Validate Redis candidates without secrets or deployment."""
import copy
import json
import os

from redis_runtime import REDIS_IMAGE, REDIS_FILES, specification
from stack_release import upgrade_release, validate_manifest, expected_images
from stack_runtime import ROOT, render_release, validate_rendered
from validate_asset_config import render


def check(base, candidate, release):
    services = candidate['services']
    redis = services['redis']
    if redis.get('ports') or set(redis['networks']) != {'redis_internal'}:
        raise ValueError('Redis debe ser privado y no publicar puertos')
    if not candidate['networks']['redis_internal'].get('internal'):
        raise ValueError('Redis requiere red interna')
    if redis['image'] != REDIS_IMAGE or redis['deploy']['replicas'] != 1:
        raise ValueError('Redis requiere imagen revisada y una réplica')
    for name in ('redis', 'snippets-service', 'printscript-service'):
        deploy = services[name]['deploy']
        if deploy['update_config']['order'] != 'stop-first' or deploy['rollback_config']['order'] != 'stop-first':
            raise ValueError('Coordinadores deben reemplazarse sin solapamiento')
    for name in base['services']:
        if name not in ('snippets-service', 'printscript-service') and services[name] != base['services'][name]:
            raise ValueError(f'Redis alteró un servicio ajeno: {name}')
    for name in ('snippets-service', 'printscript-service'):
        original = copy.deepcopy(base['services'][name])
        changed = copy.deepcopy(services[name])
        original['deploy']['update_config']['order'] = 'stop-first'
        if name == 'snippets-service':
            original['environment'].update(SPRING_DATA_REDIS_HOST='redis', SPRING_DATA_REDIS_PORT='6379',
                SNIPPETS_OUTBOX_STREAM=f'snippet-searcher:{release["environment"]}:events')
            original['networks'] = {'default': {}, 'redis_internal': {}}
            original.setdefault('secrets', []).append({'source': 'redis_password',
                                                       'target': 'spring.data.redis.password'})
        if original != changed:
            raise ValueError(f'Redis modificó más que conexión/política del coordinador: {name}')
    for service in services.values():
        if any(('PASSWORD' in key and not key.endswith('_FILE')) or key.endswith('_TOKEN')
               for key in service.get('environment', {})):
            # Existing base secrets are configtree files; Redis must not introduce credential environment.
            raise ValueError('Credencial en environment inspeccionable')


def main():
    settings = {**os.environ, 'SNIPPETS_DB_PASSWORD': 'unused-validation',
                'PERMISSIONS_DB_PASSWORD': 'unused-validation', 'GITHUB_ACTOR': 'unused-validation',
                'GITHUB_TOKEN': 'unused-validation'}
    profiles = ('ui', 'ingress', 'assets', 'verification')
    base_local = render(['compose.yaml'], settings, profiles)
    local = render(['compose.yaml', 'compose.redis.yaml'], settings, profiles)
    if 'redis' in base_local['services'] or local['services']['redis'].get('ports') \
            or not local['networks']['redis_internal']['internal']:
        raise ValueError('Compose Redis debe ser optativo, privado y sin puertos')
    if local['services']['redis']['image'] != REDIS_IMAGE:
        raise ValueError('Compose debe usar la misma imagen revisada de Swarm')
    for name, original in base_local['services'].items():
        changed = copy.deepcopy(local['services'][name])
        expected = copy.deepcopy(original)
        if name == 'snippets-service':
            expected['environment'].update(SPRING_CONFIG_IMPORT='configtree:/run/secrets/',
                SPRING_DATA_REDIS_HOST='redis', SPRING_DATA_REDIS_PORT='6379',
                SNIPPETS_OUTBOX_STREAM='snippet-searcher:local:events')
            expected['networks'] = {'default': None, 'redis_internal': None}
            expected.setdefault('secrets', []).append({'source': 'redis_password',
                                                       'target': 'spring.data.redis.password'})
            expected['depends_on']['redis'] = {'condition': 'service_healthy', 'required': True}
        if expected != changed:
            raise ValueError(f'Compose Redis modificó contratos/build/secrets ajenos: {name}')
    print('PASS Compose Redis: optativo, privado, contratos/build/secrets existentes conservados')
    for environment in ('dev', 'prod'):
        release = upgrade_release(json.loads((ROOT / f'swarm/{environment}-release.json').read_text()))
        base = render_release(release)
        release['infrastructure']['redis'] = specification(environment)
        candidate = render_release(release)
        check(base, candidate, release)
        validate_rendered(candidate)
        assert set(candidate['services']) == set(expected_images(release))
        print(f'PASS Redis render {environment}: privado, secretos por archivo, políticas selectivas')
    for file in REDIS_FILES.values():
        if not (ROOT / file).is_file():
            raise ValueError('Config Redis incompleta')


if __name__ == '__main__':
    main()
