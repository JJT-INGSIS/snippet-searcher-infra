import subprocess
from copy import deepcopy

from deploy_service import Swarm
from stack_release import infrastructure, upgrade_release
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


def proxy_document(release):
    rendered = render_release(release)
    rendered["services"] = {PROXY: deepcopy(rendered["services"][PROXY])}
    return validate_rendered(rendered)


def apply_proxy(release, docker_json):
    document = proxy_document(release)
    require_configs(release, docker_json, create=True)
    subprocess.run(["docker", "stack", "deploy", "--resolve-image", "always", "-c", "-",
                    "snippet-searcher-" + release["environment"]], input=document, text=True, check=True,
                   timeout=DEPLOY_SECONDS)


class ProxySwarm(Swarm):
    def __init__(self, environment, confirmed):
        super().__init__(environment)
        self.confirmed = deepcopy(confirmed)

    def apply_infrastructure(self, release):
        from deploy_service import docker_json
        require_proxy_only(self.confirmed, release)
        apply_proxy(release, docker_json)
