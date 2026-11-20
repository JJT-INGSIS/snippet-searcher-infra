"""Public Auth0 cutover parameters; never creates clients, grants or credentials."""

from copy import deepcopy
import json
from pathlib import Path

from stack_release import auth_environment, infrastructure, ui_configuration, validate_manifest

ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_ORIGIN = 'https://jjt-snippets-prod.duckdns.org'


def public_identity(environment):
    if environment not in ('dev', 'prod'):
        raise ValueError('Ambiente Auth0 desconocido')
    filename = 'production' if environment == 'prod' else 'development'
    public = json.loads((ROOT / f'auth0/{filename}.public.json').read_text())
    if environment == 'prod':
        if public.get('status') != 'ADMIN_CONFIRMED_READY_FOR_ROLLOUT':
            raise ValueError('Auth0 PROD requiere confirmación administrativa')
        return {**public, 'client_id': public['clientId']}
    return public


def plan_identity(release, environment):
    if release['environment'] != environment or 'ui' not in release['images']:
        raise ValueError('Auth0 requiere el ambiente elegido con UI instalada')
    public = public_identity(environment)
    proxy = infrastructure(release).get('nginx', {})
    origin = 'https://' + proxy.get('hostname', '')
    if not proxy.get('tls') or origin not in public['origins']:
        raise ValueError('Ingreso HTTPS distinto de las origins Auth0 aprobadas')
    if environment == 'prod' and origin != PRODUCTION_ORIGIN:
        raise ValueError('El corte PROD requiere el hostname de PROD')
    candidate = deepcopy(release)
    candidate['auth'] = {'mode': 'auth0', **{key: public[key] for key in ('issuer', 'audience')}}
    candidate['ui'] = {'auth': {key: public[key] for key in ('domain', 'client_id', 'audience')}}
    validate_manifest(candidate)
    return candidate


def require_production_identity(release):
    # The previous disabled state remains a valid recovery target. Never introduce a dev actor.
    if auth_environment(release)['AUTH_MODE'] == 'disabled':
        if ui_configuration(release)['identity']['mode'] != 'disabled':
            raise ValueError('Recuperación PROD requiere UI y API deshabilitadas')
        return
    expected = plan_identity(release, 'prod')
    if release.get('auth') != expected['auth'] or release.get('ui') != expected['ui']:
        raise ValueError('Identidad PROD distinta de la confirmada; no usar parámetros DEV')
