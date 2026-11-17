import copy
import json
import unittest
from unittest.mock import patch

import scoped_deploy
from bootstrap_swarm import plan_release
from test_tls_release import secured

CHANGED_CONFIGS = ("nginx_main", "nginx_routes")


def renamed(release, version="v2"):
    result = copy.deepcopy(release)
    for key in CHANGED_CONFIGS:
        spec = result["infrastructure"]["nginx"]["configs"][key]
        spec["name"] = spec["name"].rsplit("_v", 1)[0] + "_" + version
        spec["sha256"] = "f" * 64
    return result


class ProxyOnlyChangeTests(unittest.TestCase):
    def test_renamed_nginx_configs_and_the_confirmed_release_are_accepted(self):
        previous = secured()
        scoped_deploy.require_proxy_only(previous, renamed(previous))
        scoped_deploy.require_proxy_only(previous, copy.deepcopy(previous))

    def test_any_other_change_is_rejected(self):
        previous = secured()
        changes = {
            "image": lambda value: value["images"].update({"snippets-service": value["images"]["snippets-service"][:-1] + "0"}),
            "proxy image": lambda value: value["infrastructure"]["nginx"].update(image="nginx@sha256:" + "0" * 64),
            "hostname": lambda value: value["infrastructure"]["nginx"].update(hostname="other.test"),
            "tls": lambda value: value["infrastructure"]["nginx"].update(tls=False),
            "storage": lambda value: value.update(storage_provider="asset"),
            "component": lambda value: value["infrastructure"].update(redis={"image": "redis@sha256:" + "0" * 64}),
            "removed config": lambda value: value["infrastructure"]["nginx"]["configs"].pop("nginx_tls"),
        }
        for name, change in changes.items():
            candidate = renamed(previous)
            change(candidate)
            with self.subTest(change=name), self.assertRaises(ValueError):
                scoped_deploy.require_proxy_only(previous, candidate)

    def test_plan_with_a_new_config_version_is_a_proxy_only_change(self):
        previous = secured()
        for key in CHANGED_CONFIGS:
            previous["infrastructure"]["nginx"]["configs"][key]["sha256"] = "0" * 64
        planned = plan_release(previous, previous["infrastructure"]["nginx"]["hostname"], tls=True, config_version=2)
        names = {key: spec["name"] for key, spec in planned["infrastructure"]["nginx"]["configs"].items()}
        self.assertEqual({key for key, name in names.items() if name.endswith("_v2")}, set(CHANGED_CONFIGS))
        scoped_deploy.require_proxy_only(previous, planned)

    def test_release_without_proxy_is_rejected(self):
        previous = secured()
        missing = copy.deepcopy(previous)
        del missing["infrastructure"]["nginx"]
        with self.assertRaises(ValueError):
            scoped_deploy.require_proxy_only(previous, missing)


class ProxyApplyTests(unittest.TestCase):
    def rendered(self):
        return {"services": {"nginx": {"image": "nginx"}, "snippets-db": {"image": "postgres"},
                             "redis": {"image": "redis"}}, "configs": {"nginx_main": {"external": True}}}

    def test_only_the_proxy_service_is_deployed_without_prune(self):
        release = renamed(secured())
        with patch("scoped_deploy.render_release", return_value=self.rendered()), \
                patch("scoped_deploy.validate_rendered", side_effect=json.dumps), \
                patch("scoped_deploy.require_configs") as configs, \
                patch("scoped_deploy.subprocess.run") as run:
            scoped_deploy.apply_scoped(release, lambda *arguments: [], scoped_deploy.SCOPES["proxy"][0])
        document = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(set(document["services"]), {"nginx"})
        self.assertEqual(document["configs"], {"nginx_main": {"external": True}})
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "stack", "deploy"])
        self.assertEqual(command[-1], "snippet-searcher-dev")
        self.assertNotIn("--prune", command)
        configs.assert_called_once()
        self.assertTrue(configs.call_args.kwargs["create"])

    def test_proxy_swarm_refuses_other_changes_before_any_docker_call(self):
        previous = secured()
        candidate = renamed(previous)
        candidate["infrastructure"]["nginx"]["hostname"] = "other.test"
        swarm = scoped_deploy.ScopedSwarm("dev", previous, "proxy")
        with patch("scoped_deploy.apply_scoped") as apply, self.assertRaises(ValueError):
            swarm.apply_infrastructure(candidate)
        apply.assert_not_called()

    def test_proxy_swarm_restores_the_confirmed_release_the_same_way(self):
        previous = secured()
        swarm = scoped_deploy.ScopedSwarm("dev", previous, "proxy")
        with patch("scoped_deploy.apply_scoped") as apply:
            swarm.apply_infrastructure(renamed(previous))
            swarm.apply_infrastructure(copy.deepcopy(previous))
        self.assertEqual(apply.call_count, 2)


def with_apm(release, enabled=True):
    result = copy.deepcopy(release)
    result["apm"] = {"enabled": enabled}
    return result


class ApmScopeTests(unittest.TestCase):
    def test_turning_apm_on_or_off_is_an_apm_only_change(self):
        previous = secured()
        scoped_deploy.require_apm_only(previous, with_apm(previous))
        scoped_deploy.require_apm_only(with_apm(previous), with_apm(previous, enabled=False))
        scoped_deploy.require_apm_only(previous, copy.deepcopy(previous))

    def test_any_other_change_is_rejected_with_apm(self):
        previous = secured()
        for change in (renamed(with_apm(previous)), with_apm(previous) | {"storage_provider": "asset"}):
            with self.subTest(change=sorted(change)), self.assertRaises(ValueError):
                scoped_deploy.require_apm_only(previous, change)

    def test_only_the_three_java_services_are_deployed(self):
        rendered = {"services": {name: {"image": name} for name in
                                 ("nginx", "snippets-db", "redis", "ui", "snippets-service", "permissions-service",
                                  "printscript-service")}}
        with patch("scoped_deploy.render_release", return_value=rendered), \
                patch("scoped_deploy.validate_rendered", side_effect=json.dumps), \
                patch("scoped_deploy.require_configs"), \
                patch("scoped_deploy.subprocess.run") as run:
            scoped_deploy.apply_scoped(with_apm(secured()), lambda *arguments: [], scoped_deploy.SCOPES["apm"][0])
        document = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(set(document["services"]),
                         {"snippets-service", "permissions-service", "printscript-service"})
        self.assertNotIn("--prune", run.call_args.args[0])

    def test_apm_scope_refuses_a_proxy_change_before_any_docker_call(self):
        previous = secured()
        swarm = scoped_deploy.ScopedSwarm("dev", previous, "apm")
        with patch("scoped_deploy.apply_scoped") as apply, self.assertRaises(ValueError):
            swarm.apply_infrastructure(renamed(with_apm(previous)))
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
