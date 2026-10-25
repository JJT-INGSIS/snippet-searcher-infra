"""Read-only cutover gates. A v2 record fences historical tools under deploy.lock."""
import base64
import os
import re

from github_cd import GitHub
from stack_release import SERVICES


def require_updated_callers(environment, api_factory=GitHub, include_ui=False):
    branch = 'dev' if environment == 'dev' else 'main'
    central = re.compile(r'JJT-INGSIS/github-workflows/\.github/workflows/[^\s\'"]+')
    for name in (*SERVICES, *(['snippet-searcher-ui'] if include_ui else [])):
        workflows = ('frontend-ci.yml', 'cd.yml') if name == 'snippet-searcher-ui' else ('kotlin-service-pipeline.yml',)
        expected = {f'JJT-INGSIS/github-workflows/.github/workflows/{workflow}@v0.6.0' for workflow in workflows}
        api = api_factory(f'JJT-INGSIS/{name}', os.environ.get('GH_TOKEN', ''))
        files = api.request(f'/contents/.github/workflows?ref={branch}')
        approved = False
        for entry in files:
            if not entry['name'].endswith(('.yml', '.yaml')):
                continue
            content = api.request(f'/contents/{entry["path"]}?ref={branch}')
            text = base64.b64decode(content['content'], validate=False).decode('utf-8')
            references = central.findall(text)
            if set(references) - expected:
                raise ValueError(f'{name}/{branch}: caller central antiguo o diferente')
            if entry['name'] == 'pipeline.yml' and expected <= set(references):
                approved = True
        if not approved:
            raise ValueError(f'{name}/{branch}: falta caller revisado v0.6.0')
        page = 1
        while True:
            runs = api.request(f'/actions/runs?branch={branch}&per_page=100&page={page}')['workflow_runs']
            if any(run['status'] != 'completed' and run['event'] in ('push', 'workflow_dispatch') for run in runs):
                raise ValueError(f'{name}/{branch}: esperar ejecuciones activas antes del corte')
            if len(runs) < 100:
                break
            page += 1
