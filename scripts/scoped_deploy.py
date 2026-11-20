import subprocess
from copy import deepcopy

from deploy_service import Swarm
from stack_release import SERVICES, auth_environment, cors_environment, infrastructure, ui_configuration, upgrade_release
from stack_runtime import render_release, require_configs, validate_rendered

PROXY = "nginx"
DEPLOY_SECONDS = 180


def without_proxy_configs(release):
    result = upgrade_release(release)
    proxy = infrastructure(result).get(PROXY)
    if proxy is None:
        raise ValueError("La actualización del proxy requiere NGINX registrado")
    result["infrastructure"][PROXY] = {key: value for key, value in proxy.items() if key != "configs"}
    return result


def require_proxy_only(previous, release):
    if without_proxy_configs(previous) != without_proxy_configs(release):
        raise ValueError("La actualización del proxy sólo admite cambiar configs de NGINX")
    if set(infrastructure(previous)[PROXY]["configs"]) != set(infrastructure(release)[PROXY]["configs"]):
        raise ValueError("La actualización del proxy no agrega ni quita configs")


def without_apm(release):
    result = upgrade_release(release)
    result.pop("apm", None)
    return result


def require_apm_only(previous, release):
    if without_apm(previous) != without_apm(release):
        raise ValueError("La actualización de APM sólo admite cambiar el campo apm")


def without_background(release):
    result = upgrade_release(release)
    result.pop("background", None)
    return result


def require_background_only(previous, release):
    if without_background(previous) != without_background(release):
        raise ValueError("La actualización del procesamiento de fondo sólo admite cambiar el campo background")


def without_auth(release):
    result = upgrade_release(release)
    result.pop('auth', None)
    result.pop('ui', None)
    return result


def require_auth_only(previous, release):
    if 'ui' not in release['images']:
        raise ValueError('El corte Auth0 requiere UI ya instalada')
    if release['environment'] == 'prod':
        from auth_rollout import require_production_identity
        require_production_identity(release)
    if without_auth(previous) != without_auth(release):
        raise ValueError('El corte Auth0 sólo admite cambiar identidad de UI y API')
    # The confirmed legacy state remains a valid rollback target.
    if auth_environment(release)['AUTH_MODE'] == 'auth0' and ui_configuration(release)['identity']['mode'] != 'auth0':
        raise ValueError('UI y API Auth0 incompatibles')


SCOPES = {
    "proxy": (frozenset({PROXY}), require_proxy_only),
    "apm": (frozenset(SERVICES), require_apm_only),
    "background": (frozenset({"snippets-service", "printscript-service"}), require_background_only),
    "auth": (frozenset({'snippets-service', 'ui'}), require_auth_only),
}


def scoped_document(release, services):
    rendered = render_release(release)
    rendered["services"] = {name: deepcopy(spec) for name, spec in rendered["services"].items() if name in services}
    return validate_rendered(rendered)


def apply_scoped(release, docker_json, services):
    document = scoped_document(release, services)
    require_configs(release, docker_json, create=True)
    subprocess.run(["docker", "stack", "deploy", "--resolve-image", "always", "-c", "-",
                    "snippet-searcher-" + release["environment"]], input=document, text=True, check=True,
                   timeout=DEPLOY_SECONDS)


class ScopedSwarm(Swarm):
    def __init__(self, environment, confirmed, scope):
        super().__init__(environment)
        self.confirmed = deepcopy(confirmed)
        self.scope = scope
        self.services, self.rule = SCOPES[scope]

    def apply_infrastructure(self, release):
        from deploy_service import docker_json
        self.rule(self.confirmed, release)
        if self.scope == 'auth':
            from apm_runtime import require_apm_configuration
            require_apm_configuration(self.confirmed, docker_json, 'snippets-service')
        apply_scoped(release, docker_json, self.services)

    def require_recoverable_infrastructure(self, previous, candidate):
        super().require_recoverable_infrastructure(previous, candidate)
        if self.scope != 'auth':
            return
        from deploy_service import docker_json
        spec = docker_json('service', 'inspect', f'snippet-searcher-{self.environment}_snippets-service')[0]
        values = dict(entry.split('=', 1) for entry in spec['Spec']['TaskTemplate']['ContainerSpec'].get('Env', []))
        current = {key: values.get(key, ('dev' if previous['environment'] == 'dev' else 'disabled') if key == 'AUTH_MODE' else '') for key in
                   ('AUTH_MODE', 'AUTH_ISSUER', 'AUTH_AUDIENCE', 'SNIPPETS_CORS_ALLOWED_ORIGINS')}
        if not any(current == {**auth_environment(release), **cors_environment(release)}
                   for release in (previous, candidate)):
            raise ValueError('Identidad API ajena al corte; no sobrescribir configuración de terceros')
        from apm_runtime import require_apm_configuration
        require_apm_configuration(previous, docker_json, 'snippets-service')
