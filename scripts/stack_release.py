"""Pure selection of exact release references; atomic record I/O at the boundary."""
import json
import os
import re
from copy import deepcopy
from uuid import uuid4

SERVICES = ('snippets-service', 'permissions-service', 'printscript-service')
DATABASE_SERVICES = ('snippets-db', 'permissions-db')
STACK_SERVICES = (*SERVICES, *DATABASE_SERVICES)
VARIABLES = ('SNIPPETS_IMAGE', 'PERMISSIONS_IMAGE', 'PRINTSCRIPT_IMAGE')
DIGEST = r'sha256:[a-f0-9]{64}'
APPLICATIONS = {name: {'repository': f'JJT-INGSIS/{name}', 'package': f'ghcr.io/jjt-ingsis/{name}', 'variable': variable}
                for name, variable in zip(SERVICES, VARIABLES)}
APPLICATIONS['ui'] = {'repository': 'JJT-INGSIS/snippet-searcher-ui',
                      'package': 'ghcr.io/jjt-ingsis/snippet-searcher-ui', 'variable': 'UI_IMAGE'}
INFRA_PACKAGES = {'nginx': 'nginx:1.30.6-alpine',
                  'asset-service': 'ghcr.io/austral-ingsis/snippet-asset-service',
                  'azurite': 'mcr.microsoft.com/azure-storage/azurite:3.35.0'}
NGINX_FILES = {'nginx_main': 'nginx/nginx.conf', 'nginx_routes': 'nginx/templates/ingress.conf.template',
               'nginx_env_check': 'nginx/validate-env.sh'}
ONE_SHOT_SERVICES = ('certbot',)


def database_image(manifest):
    return manifest['database']['image'] if manifest.get('schema_version') == 2 else manifest['database_image']


def infrastructure(manifest):
    return manifest.get('infrastructure', {})


def storage_provider(manifest):
    return manifest.get('storage_provider', 'local')


def ui_configuration(manifest):
    actor = manifest.get('ui', {}).get('dev_actor', '')
    return {'environment': manifest['environment'],
            'identity': {'mode': 'dev', 'actorId': actor} if actor else {'mode': 'disabled'}}


def ui_environment(manifest):
    return {'APP_ENV': manifest['environment'], 'UI_DEV_ACTOR': manifest.get('ui', {}).get('dev_actor', '')}


def expected_images(manifest):
    return {**manifest['images'], **{name: database_image(manifest) for name in DATABASE_SERVICES},
            **{name: spec['image'] for name, spec in infrastructure(manifest).items()}}


def permanent_services(manifest, application=None):
    names = expected_images(manifest)
    if application is None:
        return names
    if application == 'ui':
        return {'ui': names['ui']}
    selected = set(STACK_SERVICES)
    if storage_provider(manifest) == 'asset':
        selected.update(('asset-service', 'azurite'))
    return {name: image for name, image in names.items() if name in selected}


def upgrade_release(previous):
    """New readers accept v1; v2 deliberately omits the v1 database_image field.

    Old pinned bootstrap/CD validate that field before submitting any Docker change.
    A schema number alone would be ignored by those readers and is NOT a fence.
    """
    validate_manifest(previous)
    result = deepcopy(previous)
    result['schema_version'] = 2
    result['database'] = {'image': database_image(previous)}
    result.pop('database_image', None)
    result.setdefault('infrastructure', {})
    result.setdefault('storage_provider', 'local')
    return result


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('environment') not in {'dev', 'prod'}:
        raise ValueError('El ambiente debe ser dev o prod')
    images = manifest.get('images')
    version = manifest.get('schema_version', 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Versión de registro no soportada')
    allowed = set(SERVICES) if version == 1 else set(APPLICATIONS)
    if not isinstance(images, dict) or not set(SERVICES) <= set(images) <= allowed:
        raise ValueError('Aplicaciones incompletas o fuera de la lista autorizada')
    for service in images:
        if not isinstance(images[service], str) or not re.fullmatch(
            re.escape(APPLICATIONS[service]['package']) + rf'@{DIGEST}', images[service]
        ):
            raise ValueError(f'{service}: se requiere su paquete exacto por digest')
    if version == 2 and (not isinstance(manifest.get('database'), dict) or set(manifest['database']) != {'image'}):
        raise ValueError('v2 requiere database.image explícita')
    database = manifest['database']['image'] if version == 2 else manifest.get('database_image')
    if not isinstance(database, str) or not re.fullmatch(rf'postgres:18\.6-bookworm@{DIGEST}', database):
        raise ValueError('PostgreSQL 18.6-bookworm requiere digest exacto')
    if version == 1 and any(key in manifest for key in ('infrastructure', 'storage_provider', 'database', 'ui')):
        raise ValueError('Ampliar el inventario requiere schema_version=2')
    if version == 2:
        if 'database_image' in manifest:
            raise ValueError('v2 no conserva database_image: impedir ejecución de herramientas antiguas')
        validate_components(manifest)
    settings = {APPLICATIONS[name]['variable']: image for name, image in images.items()}
    settings.update(POSTGRES_IMAGE=database, DEPLOY_ENV=manifest['environment'],
                    SNIPPET_RELEASE=json.dumps(manifest, separators=(',', ':')))
    return settings


def validate_components(manifest):
    components = infrastructure(manifest)
    if not isinstance(components, dict) or not set(components) <= set(INFRA_PACKAGES):
        raise ValueError('Componente de infraestructura desconocido')
    for name, spec in components.items():
        if not isinstance(spec, dict) or not isinstance(spec.get('image'), str) or not re.fullmatch(
                re.escape(INFRA_PACKAGES[name]) + rf'@{DIGEST}', spec['image']):
            raise ValueError(f'{name}: paquete exacto por digest requerido')
        fields = {'image', 'hostname', 'port', 'configs'} if name == 'nginx' else {'image'}
        if set(spec) != fields:
            raise ValueError(f'{name}: campos de configuración desconocidos o incompletos')
    if ('asset-service' in components) != ('azurite' in components):
        raise ValueError('Asset y Azurite se incorporan juntos')
    if storage_provider(manifest) not in ('local', 'asset'):
        raise ValueError('Proveedor de storage desconocido')
    if storage_provider(manifest) == 'asset' and 'asset-service' not in components:
        raise ValueError('Asset activo requiere runtime instalado')
    if 'ui' in manifest['images'] and 'nginx' not in components:
        raise ValueError('UI requiere entrada NGINX explícita')
    ui = manifest.get('ui', {})
    if not isinstance(ui, dict) or set(ui) - {'dev_actor'} or (ui and 'ui' not in manifest['images']):
        raise ValueError('Configuración UI desconocida o sin aplicación instalada')
    actor = ui.get('dev_actor', '')
    if not isinstance(actor, str) or (actor and (manifest['environment'] != 'dev' or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:@|/-]{0,127}', actor))):
        raise ValueError('Identidad UI de desarrollo inválida o habilitada en prod')
    if 'nginx' in components:
        proxy = components['nginx']
        host = proxy.get('hostname', '')
        if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(
                r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*', host):
            raise ValueError('Hostname de NGINX inválido')
        if type(proxy.get('port')) is not int or proxy['port'] != 80:
            raise ValueError('Ingreso HTTP usa puerto 80; TLS se incorpora en SNI-40')
        if not isinstance(proxy.get('configs'), dict) or set(proxy['configs']) != set(NGINX_FILES):
            raise ValueError('NGINX requiere las tres configs versionadas')
        for key, spec in proxy['configs'].items():
            if not isinstance(spec, dict) or set(spec) != {'name', 'sha256'} or not isinstance(spec.get('name'), str) \
                    or not isinstance(spec.get('sha256'), str) or not re.fullmatch(
                    rf'snippet-searcher-{manifest["environment"]}_{key}_v[1-9][0-9]*', spec.get('name', '')) \
                    or not re.fullmatch(r'[a-f0-9]{64}', spec.get('sha256', '')):
                raise ValueError('Config NGINX sin nombre/hash válido')
    asset = manifest.get('asset', {})
    if not isinstance(asset, dict) or set(asset) - {'container', 'connect_timeout', 'read_timeout', 'max_content_bytes', 'probe'}:
        raise ValueError('Configuración Asset desconocida')
    if not isinstance(asset.get('container', 'snippets'), str) or not re.fullmatch(
            r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', asset.get('container', 'snippets')) or '--' in asset.get('container', ''):
        raise ValueError('Container de Asset inválido')
    for key in ('connect_timeout', 'read_timeout'):
        if not isinstance(asset.get(key, '2s'), str) or not re.fullmatch(r'[1-9][0-9]*(ms|s)', asset.get(key, '2s')):
            raise ValueError('Timeout Asset inválido')
    size = asset.get('max_content_bytes', 1048576)
    if type(size) is not int or not 1 <= size <= 1048576:
        raise ValueError('Límite Asset inválido')
    if 'probe' in asset:
        from asset_probe import validate_manifest as validate_probe, ProbeFailure
        try:
            validate_probe(asset['probe'])
        except ProbeFailure as error:
            raise ValueError('Manifiesto de probe Asset inválido') from error


def select_release(requested, previous, change_infrastructure=False):
    validate_manifest(requested)
    if previous is None:
        return {**requested}
    validate_manifest(previous)
    if previous['environment'] != requested['environment']:
        raise ValueError('El registro pertenece a otro ambiente')
    # Reapplying infrastructure takes current app AND database references.
    if not change_infrastructure:
        return deepcopy(previous)
    selected = upgrade_release(previous)
    if not set(infrastructure(previous)) <= set(infrastructure(requested)):
        raise ValueError('Retirar infraestructura persistente requiere un procedimiento específico')
    # Configuration changes preserve app/database versions, receipts and unknown metadata.
    selected.update(infrastructure=deepcopy(infrastructure(requested)))
    if storage_provider(requested) != storage_provider(previous):
        raise ValueError('Cambiar proveedor requiere una transición de datos independiente (SNI-19/36)')
    if requested.get('asset', {}) != previous.get('asset', {}):
        raise ValueError('Cambiar configuración de storage requiere transición explícita')
    new_apps = set(requested['images']) - set(previous['images'])
    for name in new_apps:
        selected['images'][name] = requested['images'][name]
    if 'ui' in requested:
        selected['ui'] = deepcopy(requested['ui'])
    validate_manifest(selected)
    return selected


def update_service(previous, service, image):
    if service not in APPLICATIONS or service not in previous['images']:
        raise ValueError('Servicio desconocido')
    changed = {**previous, 'images': {**previous['images'], service: image}}
    validate_manifest(changed)
    return changed


def write_record(path, record):
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        with temporary.open('x') as output:
            os.chmod(temporary, 0o600)
            json.dump(record, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_promotion(prod, dev):
    validate_manifest(prod)
    validate_manifest(dev)
    if prod['environment'] != 'prod' or dev['environment'] != 'dev':
        raise ValueError('La promoción requiere dev a prod')
    if dev.get('checks', {}).get('sql_and_internal_http') != 'passed':
        raise ValueError('Falta evidencia confirmada de dev')
    if prod['images'] != dev['images'] or database_image(prod) != database_image(dev):
        raise ValueError('Prod debe usar exactamente los digests comprobados en dev')
