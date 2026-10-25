"""Real packaged UI + reviewed ingress; controlled API is transport evidence only."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from verify_nginx import ROOT, eventually, local_engine, request, require


def verify(image):
    local_engine()
    if not re.fullmatch(r'[a-z0-9][a-z0-9._:/@-]+', image):
        raise ValueError('Se requiere la referencia local de la UI a probar')
    subprocess.run(['docker', 'image', 'inspect', image], check=True, stdout=subprocess.DEVNULL, timeout=30)
    project = 'sni42-ingress-' + uuid4().hex[:12]
    settings = {**os.environ, 'PROXY_HTTP_PORT': '0', 'SNIPPETS_DB_PASSWORD': 'unused-validation',
                'PERMISSIONS_DB_PASSWORD': 'unused-validation', 'GITHUB_ACTOR': 'unused-validation',
                'GITHUB_TOKEN': 'unused-validation'}
    with tempfile.TemporaryDirectory(prefix='sni42-ui-') as temporary:
        override = Path(temporary) / 'ui.yaml'
        override.write_text('services:\n  ui:\n    image: ' + json.dumps(image) + '''
    command: !reset null
    volumes: !reset []
    user: "101:101"
    tmpfs: [/tmp]
    environment:
      APP_ENV: ${UI_TEST_ENV:?}
      UI_DEV_ACTOR: ${UI_TEST_ACTOR:-}
''')
        command = ['docker', 'compose', '--env-file', os.devnull, '--profile', 'ingress', '-p', project,
                   '-f', str(ROOT / 'tests/nginx/compose.yaml'), '-f', str(override)]
        def compose(*args, capture=False):
            return subprocess.run([*command, *args], env=settings, check=True, timeout=180,
                                  stdout=subprocess.PIPE if capture else None, text=True)
        settings.update(UI_TEST_ENV='dev', UI_TEST_ACTOR='dev-juanfran')
        try:
            for environment, actor in (('dev', 'dev-juanfran'), ('prod', '')):
                settings.update(UI_TEST_ENV=environment, UI_TEST_ACTOR=actor)
                compose('up', '-d', '--wait', 'ui', 'snippets-service', 'nginx')
                port = int(compose('port', 'nginx', '8080', capture=True).stdout.strip().rsplit(':', 1)[1])
                index = eventually(port, '/', 200)
                require(b'type="module"' in index.body, 'Expected the actual built UI, not a fixture HTML')
                require(request(port, '/editor/a-snippet').body == index.body, 'SPA navigation failed')
                config = request(port, '/app-config.json')
                require(config.headers.get('Cache-Control') == 'no-store', 'Runtime configuration cached')
                require(json.loads(config.body) == {'environment': environment,
                    'identity': {'mode': 'dev', 'actorId': actor} if actor else {'mode': 'disabled'}}, 'Wrong runtime config')
                forwarded = json.loads(eventually(port, '/api/languages', 200).body)
                require(forwarded['path'] == '/languages', 'API prefix not removed')
                for path, status in (('/api/missing', 404), ('/api/problem', 422)):
                    response = request(port, path)
                    require(response.status == status and response.headers.get('Content-Type') == 'application/problem+json',
                            'API failure was converted to SPA HTML')
                require(request(port, '/assets/not-found.js').status == 404, 'Missing static became SPA HTML')
                print(f'PASS packaged UI + real NGINX {environment}; controlled API transport, not business acceptance', flush=True)
        finally:
            compose('down', '--remove-orphans')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', help='Existing locally built UI image; never pull/build/deploy a VM here')
    verify(parser.parse_args().image)
