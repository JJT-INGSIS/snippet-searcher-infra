import subprocess
from copy import deepcopy

from deploy_service import Swarm
from stack_release import SERVICES, infrastructure, upgrade_release
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


SCOPES = {
    "proxy": (frozenset({PROXY}), require_proxy_only),
    "apm": (frozenset(SERVICES), require_apm_only),
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
        self.services, self.rule = SCOPES[scope]

    def apply_infrastructure(self, release):
        from deploy_service import docker_json
        self.rule(self.confirmed, release)
        apply_scoped(release, docker_json, self.services)
