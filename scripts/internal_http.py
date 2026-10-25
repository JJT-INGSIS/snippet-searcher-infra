"""HTTP from the stack network; no privileged credentials or public ports."""
import json
import os
import sys
import urllib.request
from urllib.error import HTTPError
from uuid import uuid4


def request(url, method='GET', body=None, headers=None):
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=payload, method=method, headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, None


def verify(stack):
    release = json.loads(os.environ.get('SNIPPET_RELEASE', '{}'))
    application = os.environ.get('VERIFY_APPLICATION') or None
    if application == 'ui':
        verify_ui(release)
        return
    permissions = os.environ['PERMISSIONS_BASE_URL']
    printscript = os.environ['PRINTSCRIPT_BASE_URL']
    status, health = request(permissions + '/actuator/health')
    assert status == 200 and health['status'] == 'UP'
    print('PASS Permissions datasource HTTP health', flush=True)
    status, result = request(printscript + '/validate', 'POST', {'code': 'println(1);', 'version': '1.0'})
    assert status == 200 and result['valid'] is True
    print('PASS PrintScript internal HTTP validation', flush=True)
    if stack == 'snippet-searcher-dev':
        from smoke_tests import main
        if main() != 0:
            raise RuntimeError("Fallaron contratos HTTP de dev")
        key = str(uuid4())
        status, created = request('http://snippets-service:8080/snippets', 'POST',
            {'name': 'infra-bootstrap-probe', 'description': None, 'language': 'printscript', 'version': '1.0', 'code': 'println(1);'},
            {'Idempotency-Key': key, 'X-Dev-Actor-Id': 'infra-bootstrap-probe'})
        assert status == 201 and created.get('id')
        print(f"PASS Snippets creation/internal clients SQL/storage id={created['id']}", flush=True)
        status, owner = request(permissions + '/ownership/' + created['id'])
        assert status == 200 and owner['ownerId'] == 'infra-bootstrap-probe'
        print('PASS Snippets to Permissions ownership', flush=True)
    else:
        status, _ = request(permissions + '/ownership/' + str(uuid4()))
        assert status == 404
        print('PASS prod ownership query (no write)', flush=True)
    if release.get('storage_provider') == 'asset':
        verify_asset(release, stack)
    if application is None and release.get('infrastructure', {}).get('nginx'):
        verify_ingress(release)


def verify_asset(release, stack):
    from asset_probe import prepare, verify as read_probe, cleanup, wait_ready
    base = 'http://asset-service:8080'
    wait_ready('http://asset-service:9090')
    if stack.endswith('-dev'):
        sample = prepare(base)
        cleanup(base, sample)
    else:
        sample = release.get('asset', {}).get('probe')
        if sample is None:
            raise ValueError('Prod Asset requiere probe previamente preparado; no escribir ni inferir éxito')
        read_probe(base, sample)
    print('PASS Asset con Blob real; sin probar directorio local', flush=True)


def verify_ui(release):
    from stack_release import ui_configuration
    # Read real runtime config as well as HTML; SPA fallback must not fake config health.
    with urllib.request.urlopen('http://ui:8080/', timeout=10) as response:
        assert response.status == 200 and 'text/html' in response.headers.get('Content-Type', '')
        assert response.read(1048576)
    status, config = request('http://ui:8080/app-config.json')
    assert status == 200 and config == ui_configuration(release)
    print('PASS UI HTTP y configuración runtime del ambiente', flush=True)


def verify_ingress(release):
    proxy = release['infrastructure']['nginx']
    headers = {'Host': f'{proxy["hostname"]}:{proxy["port"]}'}
    with urllib.request.urlopen(urllib.request.Request('http://nginx:8080/healthz', headers=headers), timeout=10) as answer:
        assert answer.status == 200 and answer.read(1024) == b'nginx-up\n'
    direct_status, direct = request('http://snippets-service:8080/languages')
    routed_status, routed = request('http://nginx:8080/api/languages', headers=headers)
    assert direct_status == routed_status == 200 and direct and routed == direct
    if 'ui' in release['images']:
        verify_ui(release)
        with urllib.request.urlopen(urllib.request.Request('http://nginx:8080/', headers=headers), timeout=10) as answer:
            assert answer.status == 200 and 'text/html' in answer.headers.get('Content-Type', '')
    print('PASS proxy y rutas internas; DNS/TLS externos NO verificados (SNI-44)', flush=True)


if __name__ == '__main__':
    verify(sys.argv[1])
