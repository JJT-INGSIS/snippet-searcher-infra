"""Render the reviewed stack and immutable configs; no generic resource orchestration."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

from stack_release import (DATABASE_SERVICES, NGINX_FILES, SERVICES, expected_images,
                           infrastructure, storage_provider, ui_environment, validate_manifest)

ROOT = Path(__file__).resolve().parent.parent


def render_release(release):
    from validate_asset_config import render
    settings = {**os.environ, **validate_manifest(release)}
    components = infrastructure(release)
    files = ['swarm/stack.yaml']
    if 'nginx' in components:
        files.append('swarm/stack.ingress.yaml')
        if components['nginx']['tls']:
            files.append('swarm/stack.tls.yaml')
        settings.update(PROXY_HOSTNAME=components['nginx']['hostname'], PROXY_PUBLIC_PORT='443')
    if 'asset-service' in components:
        files.append('swarm/stack.asset.yaml')
    if 'ui' in release['images']:
        files.append('swarm/stack.ui.yaml')
        settings.update(ui_environment(release))
    settings['STORAGE_PROVIDER'] = storage_provider(release)
    asset = release.get('asset', {})
    for name, default in (('container', 'snippets'), ('connect_timeout', '2s'), ('read_timeout', '5s'),
                          ('max_content_bytes', 1048576)):
        settings['STORAGE_ASSET_' + name.upper()] = str(asset.get(name, default))
    data = render(files, settings)
    data.pop('name', None)
    data['version'] = '3.8'
    # Compose supplies project names. Swarm must own these resources per environment.
    for section in ('networks', 'volumes'):
        for resource in data.get(section, {}).values():
            if not resource.get('external'):
                resource.pop('name', None)
    for name, image in expected_images(release).items():
        data['services'][name]['image'] = image
    if 'nginx' in components:
        for name in SERVICES:
            data['services'][name].pop('ports', None)
        data['configs'] = {key: {'external': True, 'name': spec['name']}
                           for key, spec in components['nginx']['configs'].items()}
    if set(data['services']) != set(expected_images(release)):
        raise ValueError('El render no coincide con el inventario autorizado')
    # Avoid Compose-only healthcheck/default fields unsupported by stack deploy.
    for service in data['services'].values():
        service.pop('profiles', None)
        for key in ('command', 'entrypoint'):
            if service.get(key) is None:
                service.pop(key, None)
        for name, config in service.get('networks', {}).items():
            if config is None:
                service['networks'][name] = {}
        for port in service.get('ports', []):
            if 'published' in port:
                port['published'] = int(port['published'])
    return data


def stack_document(data):
    # Compose config has already consumed $$ escaping. stack deploy interpolates
    # once more; protect literal shell variables in healthchecks and entrypoints.
    def escaped(value):
        if isinstance(value, str):
            return value.replace('$', '$$')
        if isinstance(value, list):
            return [escaped(entry) for entry in value]
        if isinstance(value, dict):
            return {key: escaped(entry) for key, entry in value.items()}
        return value
    return json.dumps(escaped(data))


def validate_rendered(data):
    document = stack_document(data)
    subprocess.run(['docker', 'stack', 'config', '-c', '-'], input=document, text=True,
                   check=True, stdout=subprocess.DEVNULL, timeout=30)
    return document


def require_configs(release, docker_json, create=False):
    proxy = infrastructure(release).get('nginx')
    if not proxy:
        return
    # Read the index once: an inspect/list failure is not proof of absence.
    found = subprocess.check_output(['docker', 'config', 'ls', '--format', '{{.Name}}'],
                                    text=True, timeout=30).splitlines()
    for key, spec in proxy['configs'].items():
        if spec['name'] in found:
            actual = docker_json('config', 'inspect', spec['name'])[0]
            content = base64.b64decode(actual['Spec']['Data'], validate=True)
        else:
            content = (ROOT / NGINX_FILES[key]).read_bytes()
        if hashlib.sha256(content).hexdigest() != spec['sha256']:
            raise ValueError('La config tiene otro contenido que el registrado')
        if create and spec['name'] not in found:
            subprocess.run(['docker', 'config', 'create', spec['name'], str(ROOT / NGINX_FILES[key])],
                           check=True, timeout=30)


def verify_service_configuration(release, docker_json, application=None):
    stack = f'snippet-searcher-{release["environment"]}'
    if 'ui' in release['images'] and application in (None, 'ui'):
        actual = docker_json('service', 'inspect', f'{stack}_ui')[0]['Spec']['TaskTemplate']['ContainerSpec']
        values = dict(entry.split('=', 1) for entry in actual.get('Env', []))
        if any(values.get(key, '') != value for key, value in ui_environment(release).items()):
            raise ValueError('Configuración efectiva de UI distinta del registro')
    if application != 'ui':
        snippets = docker_json('service', 'inspect', f'{stack}_snippets-service')[0]
        env = dict(entry.split('=', 1) for entry in snippets['Spec']['TaskTemplate']['ContainerSpec'].get('Env', []))
        if env.get('STORAGE_PROVIDER', 'local') != storage_provider(release):
            raise ValueError('Proveedor efectivo distinto del registro')
        if storage_provider(release) == 'asset':
            asset = release.get('asset', {})
            expected = {'STORAGE_ASSET_BASE_URL': 'http://asset-service:8080',
                'STORAGE_ASSET_CONTAINER': asset.get('container', 'snippets'),
                'STORAGE_ASSET_CONNECT_TIMEOUT': asset.get('connect_timeout', '2s'),
                'STORAGE_ASSET_READ_TIMEOUT': asset.get('read_timeout', '5s'),
                'STORAGE_ASSET_MAX_CONTENT_BYTES': str(asset.get('max_content_bytes', 1048576))}
            if any(env.get(key) != value for key, value in expected.items()):
                raise ValueError('Configuración efectiva de Asset distinta del registro')
    proxy = infrastructure(release).get('nginx')
    if proxy and application is None:
        actual = docker_json('service', 'inspect', f'{stack}_nginx')[0]
        spec = actual['Spec']['TaskTemplate']['ContainerSpec']
        names = {entry['ConfigName'] for entry in spec.get('Configs', [])}
        if names != {entry['name'] for entry in proxy['configs'].values()}:
            raise ValueError('NGINX no usa las configs registradas')
        values = dict(entry.split('=', 1) for entry in spec.get('Env', []))
        if values.get('PROXY_HOSTNAME') != proxy['hostname'] or values.get('PROXY_PUBLIC_PORT') != '443':
            raise ValueError('NGINX no usa el origen registrado')
        ports = actual['Spec'].get('EndpointSpec', {}).get('Ports', [])
        expected = {(8080, 80), (8443, 443)} if proxy['tls'] else {(8080, 80)}
        if len(ports) != len(expected) or {(port.get('TargetPort'), port.get('PublishedPort')) for port in ports} != expected:
            raise ValueError('NGINX no publica los puertos de su estado TLS')
        require_configs(release, docker_json)
        for name in (*SERVICES, *DATABASE_SERVICES, 'ui', 'asset-service', 'azurite'):
            if name in expected_images(release):
                current = docker_json('service', 'inspect', f'{stack}_{name}')[0]
                if current.get('Endpoint', {}).get('Ports') or current['Spec'].get('EndpointSpec', {}).get('Ports'):
                    raise ValueError('Sólo NGINX puede publicar puertos web en el stack ampliado')


def apply_release(release, docker_json):
    document = validate_rendered(render_release(release))
    require_configs(release, docker_json, create=True)
    subprocess.run(['docker', 'stack', 'deploy', '--resolve-image', 'always', '-c', '-',
                    f'snippet-searcher-{release["environment"]}'], input=document, text=True, check=True, timeout=180)
