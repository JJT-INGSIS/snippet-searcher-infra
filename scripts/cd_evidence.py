"""Runner boundary: publication metadata, artifact selection, requests and evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from github_cd import ARTIFACT_FIELDS, DIGEST, GitHub, record_evidence, select_evidence, validate_repository, validate_request


def deployment_environment():
    if os.environ['GITHUB_EVENT_NAME'] not in ('push', 'workflow_dispatch'):
        raise ValueError('CD sólo admite push o ejecución manual después de CI')
    environments = {'refs/heads/dev': 'dev', 'refs/heads/main': 'prod'}
    environment = environments.get(os.environ['GITHUB_REF'])
    if environment is None:
        raise ValueError('CD sólo admite dev y main')
    if environment == 'prod':
        if os.environ.get('PUBLISH_REQUESTED') == 'true':
            raise ValueError('main no publica ni reconstruye; promover un digest verificado en dev')
        if os.environ.get('PROD_DEPLOY_ENABLED') != 'true':
            raise ValueError('Prod deshabilitada: verificar protección de main antes de habilitarla')
    return environment


def build_request(artifact):
    repository = os.environ['GITHUB_REPOSITORY']
    return validate_request({**{key: artifact[key] for key in ARTIFACT_FIELDS},
        'repository': repository, 'service': validate_repository(repository),
        'environment': deployment_environment(), 'target-sha': os.environ['GITHUB_SHA'],
        'run-id': int(os.environ['GITHUB_RUN_ID']), 'run-attempt': int(os.environ['GITHUB_RUN_ATTEMPT'])})


def publication_source():
    if deployment_environment() != 'dev':
        raise ValueError('Sólo dev construye imágenes')
    validate_repository(os.environ['GITHUB_REPOSITORY'])
    image = os.environ['IMAGE_NAME']
    if image != f'ghcr.io/{os.environ["GITHUB_REPOSITORY"].lower()}':
        raise ValueError('image-name debe ser el paquete exacto del repositorio caller')
    platforms = os.environ['PLATFORMS']
    if not re.fullmatch(r'linux/(amd64|arm64)(,linux/(amd64|arm64))*', platforms):
        raise ValueError('Plataformas Linux inválidas')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if sha != os.environ['GITHUB_SHA']:
        raise ValueError('El checkout no corresponde al commit verificado por CI')
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    return {'image': image, 'tree': tree,
            'cache-scope': f'{os.environ["GITHUB_REPOSITORY"].split("/")[-1]}-{platforms.replace("/", "-").replace(",", "-")}'}


def published_artifact():
    digest = os.environ['IMAGE_DIGEST']
    if not re.fullmatch(DIGEST, digest):
        raise ValueError('El build no devolvió un digest válido')
    request = build_request({'image-ref': f'{os.environ["IMAGE_NAME"]}@{digest}',
        'source-sha': os.environ['GITHUB_SHA'], 'source-tree': os.environ['SOURCE_TREE'],
        'build-run-id': int(os.environ['GITHUB_RUN_ID']),
        'build-run-attempt': int(os.environ['GITHUB_RUN_ATTEMPT'])})
    return {key: request[key] for key in ARTIFACT_FIELDS}


def select_artifact(api):
    if deployment_environment() != 'prod':
        raise ValueError('La selección corresponde únicamente a prod')
    tree = api.request(f'/git/commits/{os.environ["GITHUB_SHA"]}')['tree']['sha']
    evidence = select_evidence(api, validate_repository(os.environ['GITHUB_REPOSITORY']), tree)
    # Authorization against the current branch is checked inside the VM lock.
    return {key: evidence[key] for key in ARTIFACT_FIELDS}


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


def summary(path):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write('## Despliegue SNI-25\n\n')
        if path.exists():
            receipt = json.loads(path.read_text())
            for key in ('environment', 'service', 'image-ref', 'source-sha', 'source-tree', 'outcome'):
                output.write(f'- {key}: `{receipt[key]}`\n')
            output.write('\nLa confirmación de dev requiere también registrar evidencia en GitHub.\n')
        else:
            output.write('Despliegue no confirmado. Consultar el diario remoto antes de reintentar.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('source', 'published', 'select', 'prepare', 'record', 'summary'))
    parser.add_argument('file', type=Path, nargs='?')
    args = parser.parse_args()
    if args.mode in ('prepare', 'record', 'summary') and args.file is None:
        parser.error('Este comando requiere un archivo')
    outputs = {}
    if args.mode == 'source':
        outputs = publication_source()
    elif args.mode == 'published':
        outputs = {'artifact': json.dumps(published_artifact(), separators=(',', ':'))}
    elif args.mode == 'select':
        api = GitHub(os.environ['GITHUB_REPOSITORY'], os.environ.get('GH_TOKEN', ''))
        outputs = {'artifact': json.dumps(select_artifact(api), separators=(',', ':'))}
    elif args.mode == 'prepare':
        request = build_request(json.loads(os.environ['ARTIFACT']))
        inspect_image(request)
        args.file.write_text(json.dumps(request, indent=2) + '\n')
    elif args.mode == 'record':
        api = GitHub(os.environ['GITHUB_REPOSITORY'], os.environ.get('GH_TOKEN', ''))
        deployment = record_evidence(api, json.loads(args.file.read_text()))
        print(f'Evidencia dev registrada: Deployment {deployment}')
    else:
        summary(args.file)
    if outputs:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in outputs.items():
                output.write(f'{key}={value}\n')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f'FAIL CD evidence: {error}', file=sys.stderr)
        sys.exit(1)
