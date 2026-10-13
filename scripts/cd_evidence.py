"""Runner commands: select, inspect and register exact verified image references."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from github_cd import api_for, record_evidence, require_authorized_head, select_evidence, validate_request


def build_request(evidence=None):
    repository = os.environ['GITHUB_REPOSITORY']
    service = repository.split('/')[-1]
    source = evidence or {
        'image-ref': os.environ['IMAGE_REF'], 'source-sha': os.environ['SOURCE_SHA'],
        'source-tree': os.environ['SOURCE_TREE'],
        'build-run-id': int(os.environ.get('BUILD_RUN_ID') or os.environ['GITHUB_RUN_ID']),
        'build-run-attempt': int(os.environ.get('BUILD_RUN_ATTEMPT') or os.environ['GITHUB_RUN_ATTEMPT']),
    }
    request = {
        'repository': repository, 'service': service, 'environment': os.environ['DEPLOY_ENV'],
        'image-ref': source['image-ref'], 'source-sha': source['source-sha'],
        'source-tree': source['source-tree'], 'target-sha': os.environ['GITHUB_SHA'],
        'run-id': int(os.environ['GITHUB_RUN_ID']), 'run-attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
        'build-run-id': source['build-run-id'], 'build-run-attempt': source['build-run-attempt'],
    }
    return validate_request(request)


def inspect_image(request):
    subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', request['image-ref']],
                   check=True, timeout=600)
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', request['image-ref']], text=True))[0]
    labels = image['Config'].get('Labels', {})
    expected = {
        'org.opencontainers.image.source': f'https://github.com/{request["repository"]}',
        'org.opencontainers.image.revision': request['source-sha'],
        'io.jjt.source-tree': request['source-tree'],
        'io.jjt.actions-run': f'https://github.com/{request["repository"]}/actions/runs/{request["build-run-id"]}',
        'io.jjt.actions-run-attempt': str(request['build-run-attempt']),
    }
    if image.get('Os') != 'linux' or image.get('Architecture') != 'amd64':
        raise ValueError('La imagen debe soportar linux/amd64')
    if any(labels.get(key) != value for key, value in expected.items()):
        raise ValueError('Las etiquetas no corresponden al digest y origen registrados')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('select', 'prepare', 'record'))
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    api = api_for(os.environ['GITHUB_REPOSITORY'])
    if args.mode == 'record':
        receipt = json.loads(args.file.read_text())
        deployment = record_evidence(api, receipt)
        print(f'Evidencia dev registrada: Deployment {deployment}')
        return
    if args.mode == 'select':
        if os.environ.get('PROD_DEPLOY_ENABLED') != 'true':
            raise ValueError('Prod deshabilitada: verificar protección de main antes de habilitar PROD_DEPLOY_ENABLED')
        tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip()
        source = select_evidence(api, os.environ['GITHUB_REPOSITORY'].split('/')[-1], tree)
        request = build_request(source)
        if request['environment'] != 'prod':
            raise ValueError('La selección corresponde únicamente a prod')
        require_authorized_head(api, request)
    else:
        request = build_request()
        if request['environment'] == 'prod' and os.environ.get('PROD_DEPLOY_ENABLED') != 'true':
            raise ValueError('Prod no está habilitada')
    inspect_image(request)
    args.file.write_text(json.dumps(request, indent=2) + '\n')
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as stream:
            image, digest = request['image-ref'].split('@')
            stream.write(f'image={image}\ndigest={digest}\n')
            for key in ('image-ref', 'source-sha', 'source-tree', 'build-run-id', 'build-run-attempt'):
                stream.write(f'{key}={request[key]}\n')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f'FAIL CD evidence: {error}', file=sys.stderr)
        sys.exit(1)
