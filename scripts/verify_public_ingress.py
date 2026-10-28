"""Opt-in, read-only SNI-44 checks from an authorized external workstation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import re
import socket
import ssl
from datetime import datetime, timezone


HOSTS = {'dev': 'jjt-snippets-dev.duckdns.org', 'prod': 'jjt-snippets-prod.duckdns.org'}
# Explicit project ports, not a general-purpose scanner. SSH is intentionally excluded.
PRIVATE_PORTS = (2375, 2376, 2377, 3000, 5432, 5434, 6379, 7946, 8080, 8081, 8082, 8083, 9000, 10000, 10001, 10002)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def request(host, path, secure=True, headers=None):
    connection = (http.client.HTTPSConnection(host, context=ssl.create_default_context(), timeout=15)
                  if secure else http.client.HTTPConnection(host, timeout=15))
    try:
        connection.request('GET', path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read(2 * 1024 * 1024)
    finally:
        connection.close()


def header(headers, name):
    values = [value for key, value in headers if key.lower() == name.lower()]
    require(len(values) <= 1, f'Header duplicado: {name}')
    return values[0] if values else None


def check_redirect(host, response):
    status, headers, _ = response
    require(status == 308, 'HTTP debe redirigir con 308')
    require(header(headers, 'Location') == f'https://{host}/api/languages?probe=sni44',
            'Redirección debe conservar hostname, ruta y query')


def check_runtime(environment, response):
    status, headers, body = response
    require(status == 200, 'Configuración runtime no disponible')
    require('no-store' in (header(headers, 'Cache-Control') or ''), 'Runtime requiere no-store')
    config = json.loads(body)
    require(config.get('environment') == environment, 'UI de otro ambiente')
    if environment == 'prod':
        require(config.get('identity') == {'mode': 'disabled'}, 'Prod no debe usar identidad dev')
    return config


def check_api(response, expected):
    status, headers, body = response
    require(status == expected, f'API: esperado {expected}, recibido {status}')
    require('json' in (header(headers, 'Content-Type') or ''), 'API no debe devolver fallback HTML')
    for key in ('Access-Control-Allow-Origin', 'Access-Control-Allow-Credentials'):
        header(headers, key)
    json.loads(body)


def port_closed(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return False
    except (TimeoutError, ConnectionRefusedError):
        return True
    # DNS and other OS errors are inconclusive, never a passing firewall test.


def verify(environment):
    host = HOSTS[environment]
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secure:
            cert = secure.getpeercert()
            fingerprint = hashlib.sha256(secure.getpeercert(binary_form=True)).hexdigest()
            protocol = secure.version()
    check_redirect(host, request(host, '/api/languages?probe=sni44', secure=False))
    require(request(host, '/.well-known/acme-challenge/sni44-absent', secure=False)[0] == 404,
            'Challenge inexistente no debe redirigir ni servir UI')
    require(request(host, '/healthz')[0] == 200, 'NGINX no saludable')
    for path in ('/', '/rules'):
        status, headers, body = request(host, path)
        require(status == 200 and 'text/html' in (header(headers, 'Content-Type') or ''), f'SPA inválida: {path}')
        require(b'<div id="root"' in body, 'No se recibió la aplicación UI')
        require(not re.search(rb'(?:src|href)=["\']http://', body), 'HTML carga recursos por HTTP')
    runtime = check_runtime(environment, request(host, '/app-config.json'))
    check_api(request(host, '/api/languages'), 200)
    if environment == 'prod':
        for headers in ({}, {'X-Dev-Actor-Id': 'dev-juanfran'}):
            check_api(request(host, '/api/snippets?page=0&page_size=10', headers=headers), 401)
    for path in ('/api/actuator', '/api/actuator/health', '/api/permissions', '/api/assets'):
        headers = {'X-Dev-Actor-Id': runtime['identity']['actorId']} if environment == 'dev' else {}
        require(request(host, path, headers=headers)[0] in (401, 403, 404), f'Ruta interna expuesta: {path}')
    blocked = request(host, '/api/languages', headers={'Origin': 'https://untrusted.invalid'})
    # Empty policy leaves public responses readable only same-origin; an explicit
    # allowlist may reject the request outright. Neither grants the hostile origin.
    require(blocked[0] in (200, 403), 'Respuesta inesperada al origen no autorizado')
    require(header(blocked[1], 'Access-Control-Allow-Origin') is None, 'Origen no autorizado recibió permiso')
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = dict(zip(PRIVATE_PORTS, pool.map(lambda port: port_closed(host, port), PRIVATE_PORTS)))
    require(all(results.values()), 'Puertos privados accesibles: ' + str([port for port, closed in results.items() if not closed]))
    return {'environment': environment, 'hostname': host, 'resolved_addresses': addresses,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'tls': protocol,
            'certificate_sha256': fingerprint, 'certificate_serial': cert['serialNumber'],
            'certificate_expires': cert['notAfter'], 'external_transport': 'passed',
            'private_ports_closed_from_this_client': list(results),
            'browser_cors_and_recovery': 'separate verification required'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', choices=HOSTS)
    args = parser.parse_args()
    print(json.dumps(verify(args.environment), indent=2))


if __name__ == '__main__':
    main()
