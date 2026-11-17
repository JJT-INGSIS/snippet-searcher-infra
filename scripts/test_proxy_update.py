import copy
import json
import unittest
from unittest.mock import patch

import proxy_update
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
        proxy_update.require_proxy_only(previous, renamed(previous))
        proxy_update.require_proxy_only(previous, copy.deepcopy(previous))

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
                proxy_update.require_proxy_only(previous, candidate)

    def test_plan_with_a_new_config_version_is_a_proxy_only_change(self):
        previous = secured()
        for key in CHANGED_CONFIGS:
            previous["infrastructure"]["nginx"]["configs"][key]["sha256"] = "0" * 64
        planned = plan_release(previous, previous["infrastructure"]["nginx"]["hostname"], tls=True, config_version=2)
        names = {key: spec["name"] for key, spec in planned["infrastructure"]["nginx"]["configs"].items()}
        self.assertEqual({key for key, name in names.items() if name.endswith("_v2")}, set(CHANGED_CONFIGS))
        proxy_update.require_proxy_only(previous, planned)

    def test_release_without_proxy_is_rejected(self):
        previous = secured()
        missing = copy.deepcopy(previous)
        del missing["infrastructure"]["nginx"]
        with self.assertRaises(ValueError):
            proxy_update.require_proxy_only(previous, missing)


class ProxyApplyTests(unittest.TestCase):
    def rendered(self):
        return {"services": {"nginx": {"image": "nginx"}, "snippets-db": {"image": "postgres"},
                             "redis": {"image": "redis"}}, "configs": {"nginx_main": {"external": True}}}

    def test_only_the_proxy_service_is_deployed_without_prune(self):
        release = renamed(secured())
        with patch("proxy_update.render_release", return_value=self.rendered()), \
                patch("proxy_update.validate_rendered", side_effect=json.dumps), \
                patch("proxy_update.require_configs") as configs, \
                patch("proxy_update.subprocess.run") as run:
            proxy_update.apply_proxy(release, lambda *arguments: [])
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
        swarm = proxy_update.ProxySwarm("dev", previous)
        with patch("proxy_update.apply_proxy") as apply, self.assertRaises(ValueError):
            swarm.apply_infrastructure(candidate)
        apply.assert_not_called()

    def test_proxy_swarm_restores_the_confirmed_release_the_same_way(self):
        previous = secured()
        swarm = proxy_update.ProxySwarm("dev", previous)
        with patch("proxy_update.apply_proxy") as apply:
            swarm.apply_infrastructure(renamed(previous))
            swarm.apply_infrastructure(copy.deepcopy(previous))
        self.assertEqual(apply.call_count, 2)


if __name__ == "__main__":
    unittest.main()
