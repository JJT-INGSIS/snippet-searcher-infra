"""GitHub evidence and authorization for the three SNI-25 service pipelines."""
import json
import re
import urllib.request
from urllib.error import HTTPError

from stack_release import SERVICES, DIGEST

TASK = 'sni25:verified'
SHA = r'[a-f0-9]{40}'
CHECKS = {'convergence': 'passed', 'sql_and_internal_http': 'passed'}
ARTIFACT_FIELDS = ('image-ref', 'source-sha', 'source-tree', 'build-run-id', 'build-run-attempt')


def validate_repository(repository):
    service = repository.split('/')[-1]
    if service not in SERVICES or repository != f'JJT-INGSIS/{service}':
        raise ValueError('Repositorio fuera del alcance de CD')
    return service


def operation_id(request):
    return f'{request["service"]}-{request["run-id"]}-{request["run-attempt"]}'


def validate_request(request):
    service = request['service']
    if service != validate_repository(request['repository']):
        raise ValueError('Servicio y repositorio no coinciden')
    if request['environment'] not in ('dev', 'prod'):
        raise ValueError('Ambiente inválido')
    if not re.fullmatch(rf'ghcr.io/jjt-ingsis/{service}@{DIGEST}', request['image-ref']):
        raise ValueError('Se requiere el paquete del servicio por digest')
    for field in ('source-sha', 'source-tree', 'target-sha'):
        if not re.fullmatch(SHA, request[field]):
            raise ValueError(f'{field}: SHA inválido')
    for field in ('run-id', 'run-attempt', 'build-run-id', 'build-run-attempt'):
        if type(request[field]) is not int or request[field] < 1:
            raise ValueError(f'{field}: identificador inválido')
    return request


class GitHub:
    def __init__(self, repository, token):
        validate_repository(repository)
        self.base = f'https://api.github.com/repos/{repository}'
        self.token = token

    def request(self, path, data=None):
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            # Do not expose the response or authorization headers in diagnostics.
            raise RuntimeError(f'GitHub {error.code} en {path.split("?")[0]}') from None

    def pages(self, path):
        page = 1
        separator = '&' if '?' in path else '?'
        while True:
            items = self.request(f'{path}{separator}per_page=100&page={page}')
            if not isinstance(items, list):
                raise ValueError('Respuesta paginada de GitHub inválida')
            yield from items
            if len(items) < 100:
                return
            page += 1


def require_authorized_head(api, request):
    """Called inside the VM lock, immediately before changing Swarm."""
    branch = 'main' if request['environment'] == 'prod' else 'dev'
    current = api.request(f'/branches/{branch}')
    if current['commit']['sha'] != request['target-sha']:
        raise ValueError('Ejecución obsoleta: la rama avanzó; no se modifica Swarm')
    content = api.request(f'/git/commits/{request["target-sha"]}')
    if content['tree']['sha'] != request['source-tree']:
        raise ValueError('El contenido autorizado no coincide con la imagen')
    if branch == 'dev' and request['source-sha'] != request['target-sha']:
        raise ValueError('Dev debe ejecutar la imagen de su commit exacto')
    if branch == 'main':
        if not current.get('protected'):
            raise ValueError('main no está protegida')
        pulls = api.pages(f'/commits/{request["target-sha"]}/pulls')
        if not any(pr.get('merged_at') and pr.get('merge_commit_sha') == request['target-sha']
                   and pr['base']['ref'] == 'main' and pr['head']['ref'] == 'dev'
                   and pr['head'].get('repo', {}).get('full_name') == request['repository']
                   for pr in pulls):
            raise ValueError('Prod exige el merge de una PR de dev a main del mismo repositorio')


def require_verified_image(api, request):
    if request['environment'] == 'prod':
        select_evidence(api, request['service'], request['source-tree'], request['image-ref'])


def valid_evidence(api, deployment, service, tree):
    """Persistent verified receipt; never infer verification from a generic success."""
    payload = deployment.get('payload')
    if deployment.get('task') != TASK or deployment.get('environment') != 'dev':
        return None
    if deployment.get('creator', {}).get('login') != 'github-actions[bot]':
        return None
    if not isinstance(payload, dict) or payload.get('schema') != 1:
        return None
    if payload.get('service') != service or payload.get('source-tree') != tree:
        return None
    if payload.get('checks') != CHECKS:
        return None
    if payload.get('outcome') != 'verified' or payload.get('actual-image') != payload.get('image-ref'):
        return None
    try:
        validate_request(payload)
    except (ValueError, KeyError, TypeError):
        return None
    if payload['environment'] != 'dev' or deployment.get('sha') != payload['target-sha']:
        return None
    if payload['source-sha'] != payload['target-sha']:
        return None
    run = api.request(f'/actions/runs/{payload["run-id"]}/attempts/{payload["run-attempt"]}')
    if (run.get('conclusion') != 'success' or run.get('status') != 'completed'
            or run.get('event') not in ('push', 'workflow_dispatch')
            or run.get('head_branch') != 'dev' or run.get('head_sha') != payload['target-sha']
            or run.get('path') != '.github/workflows/pipeline.yml'
            or run.get('repository', {}).get('full_name') != payload['repository']):
        return None
    # The caller must actually have executed the central pipeline and CD from
    # one immutable revision. A similarly named local workflow is not proof.
    workflows = run.get('referenced_workflows', [])
    revisions = {}
    for name in ('kotlin-service-pipeline.yml', 'cd.yml'):
        prefix = f'JJT-INGSIS/github-workflows/.github/workflows/{name}@'
        matches = [entry.get('sha') for entry in workflows
                   if entry.get('path', '').startswith(prefix)]
        if len(matches) != 1 or not isinstance(matches[0], str) or not re.fullmatch(SHA, matches[0]):
            return None
        revisions[name] = matches[0]
    if len(set(revisions.values())) != 1:
        return None
    commit = api.request(f'/git/commits/{payload["source-sha"]}')
    if commit['tree']['sha'] != tree:
        return None
    # A later inactive status does not erase the explicit successful receipt.
    # Retention of older statuses/logs is deliberately not part of selection.
    return payload


def select_evidence(api, service, tree, image_ref=None):
    for deployment in api.pages(f'/deployments?environment=dev&task={TASK}'):
        evidence = valid_evidence(api, deployment, service, tree)
        if evidence and (image_ref is None or evidence['image-ref'] == image_ref):
            return evidence
    raise ValueError('No existe evidencia confiable de dev para el Git tree exacto de main')


def record_evidence(api, receipt):
    if receipt.get('outcome') != 'verified' or receipt.get('environment') != 'dev':
        raise ValueError('Sólo un despliegue dev verificado puede emitir evidencia')
    validate_request(receipt)
    if receipt.get('checks') != CHECKS \
            or receipt.get('actual-image') != receipt['image-ref']:
        raise ValueError('El recibo no confirma checks e imagen efectiva')
    payload = {**receipt, 'schema': 1}
    # Idempotent retry after a successful create followed by a lost response.
    for existing in api.pages(f'/deployments?environment=dev&task={TASK}'):
        if existing.get('payload') == payload and existing.get('creator', {}).get('login') == 'github-actions[bot]':
            deployment = existing
            break
    else:
        deployment = api.request('/deployments', {
            'ref': receipt['target-sha'], 'task': TASK, 'environment': 'dev',
            'auto_merge': False, 'required_contexts': [], 'production_environment': False,
            'payload': payload, 'description': 'SNI-25: digest verificado en dev',
        })
    api.request(f'/deployments/{deployment["id"]}/statuses', {
        'state': 'success', 'auto_inactive': False,
        'log_url': f'https://github.com/{receipt["repository"]}/actions/runs/{receipt["run-id"]}',
        'description': 'Convergencia, SQL y HTTP verificados',
    })
    return deployment['id']
