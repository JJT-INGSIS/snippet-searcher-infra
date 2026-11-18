import copy
import json
import unittest
from unittest.mock import patch

import background_runtime
import scoped_deploy
from bootstrap_swarm import plan_release, switched_background
from stack_release import background_environment, select_release, validate_manifest
from stack_runtime import render_release
from test_tls_release import secured

BACKGROUND_SERVICES = {"snippets-service", "printscript-service"}
BACKGROUND_KEYS = {"SNIPPETS_OUTBOX_ENABLED", "SNIPPETS_WORKER_ENABLED"}


def with_redis():
    return plan_release(secured(), install_redis=True)


def with_background(manifest, publisher=True, consumer=True):
    result = copy.deepcopy(manifest)
    result["background"] = {"publisher": publisher, "consumer": consumer}
    return result


def service_spec(**environment):
    env = [f"{key}={value}" for key, value in environment.items()]
    return [{"Spec": {"TaskTemplate": {"ContainerSpec": {"Env": env}}}}]


class BackgroundReleaseTests(unittest.TestCase):
    def test_background_is_two_explicit_booleans_and_needs_redis(self):
        validate_manifest(with_background(with_redis()))
        validate_manifest(with_background(secured(), publisher=False, consumer=False))
        invalid = ({"publisher": True}, {"publisher": "true", "consumer": True},
                   {"publisher": True, "consumer": True, "extra": False}, True)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_manifest(with_redis() | {"background": value})
        with self.assertRaises(ValueError):
            validate_manifest(with_background(secured()))

    def test_flags_translate_to_the_three_service_variables(self):
        self.assertEqual(background_environment(secured()),
                         {"SNIPPETS_OUTBOX_ENABLED": "false", "SNIPPETS_WORKER_ENABLED": "false",
                          "PRINTSCRIPT_OPERATIONS_ENABLED": "false"})
        self.assertEqual(background_environment(with_background(with_redis(), consumer=False)),
                         {"SNIPPETS_OUTBOX_ENABLED": "true", "SNIPPETS_WORKER_ENABLED": "false",
                          "PRINTSCRIPT_OPERATIONS_ENABLED": "true"})

    def test_an_infrastructure_change_carries_the_requested_background(self):
        previous = with_redis()
        selected = select_release(with_background(previous, consumer=False), previous, change_infrastructure=True)
        self.assertEqual(selected["background"], {"publisher": True, "consumer": False})

    def test_render_turns_on_only_snippets_and_printscript(self):
        rendered = render_release(with_background(with_redis()))
        for name, service in rendered["services"].items():
            environment = service.get("environment") or {}
            with self.subTest(service=name):
                if name == "snippets-service":
                    self.assertEqual(environment["SNIPPETS_OUTBOX_ENABLED"], "true")
                    self.assertEqual(environment["SNIPPETS_WORKER_ENABLED"], "true")
                elif name == "printscript-service":
                    self.assertEqual(environment["PRINTSCRIPT_OPERATIONS_ENABLED"], "true")
                else:
                    self.assertFalse(BACKGROUND_KEYS & set(environment))

    def test_render_without_background_keeps_processing_off(self):
        rendered = render_release(with_redis())
        self.assertFalse(BACKGROUND_KEYS & set(rendered["services"]["snippets-service"].get("environment") or {}))
        self.assertEqual(rendered["services"]["printscript-service"]["environment"]["PRINTSCRIPT_OPERATIONS_ENABLED"],
                         "false")

    def test_plan_switches_only_the_requested_flag(self):
        on = with_background(with_redis())
        self.assertEqual(switched_background(on, publisher=None, consumer="off"),
                         {"publisher": True, "consumer": False})
        self.assertEqual(switched_background(with_redis(), publisher="on", consumer=None),
                         {"publisher": True, "consumer": False})


class BackgroundEffectiveConfigurationTests(unittest.TestCase):
    def check(self, manifest, specs, application=None):
        background_runtime.require_background_configuration(
            manifest, lambda *arguments: copy.deepcopy(specs[arguments[-1].split("_", 1)[1]]), application)

    def test_running_services_must_match_the_release(self):
        on = {"snippets-service": service_spec(SNIPPETS_OUTBOX_ENABLED="true", SNIPPETS_WORKER_ENABLED="true"),
              "printscript-service": service_spec(PRINTSCRIPT_OPERATIONS_ENABLED="true")}
        off = {"snippets-service": service_spec(), "printscript-service": service_spec()}
        self.check(with_background(with_redis()), on)
        self.check(with_redis(), off)
        for manifest, specs in ((with_background(with_redis()), off), (with_redis(), on),
                                (with_background(with_redis(), consumer=False), on)):
            with self.subTest(specs=json.dumps(specs)), self.assertRaises(ValueError):
                self.check(manifest, specs)

    def test_an_application_deploy_checks_only_its_own_variables(self):
        calls = []
        background_runtime.require_background_configuration(
            with_redis(), lambda *arguments: calls.append(arguments) or service_spec(), "printscript-service")
        background_runtime.require_background_configuration(
            with_redis(), lambda *arguments: calls.append(arguments), "permissions-service")
        self.assertEqual(calls, [("service", "inspect", "snippet-searcher-dev_printscript-service")])


class BackgroundScopeTests(unittest.TestCase):
    def test_switching_background_is_a_background_only_change(self):
        previous = with_redis()
        scoped_deploy.require_background_only(previous, with_background(previous))
        scoped_deploy.require_background_only(with_background(previous), with_background(previous, consumer=False))

    def test_any_other_change_is_rejected_with_background(self):
        previous = with_redis()
        for change in (with_background(previous) | {"apm": {"enabled": True}},
                       with_background(previous) | {"storage_provider": "asset"}):
            with self.subTest(change=sorted(change)), self.assertRaises(ValueError):
                scoped_deploy.require_background_only(previous, change)

    def test_only_snippets_and_printscript_are_deployed(self):
        rendered = {"services": {name: {"image": name} for name in
                                 ("nginx", "snippets-db", "redis", "ui", "snippets-service", "permissions-service",
                                  "printscript-service")}}
        with patch("scoped_deploy.render_release", return_value=rendered), \
                patch("scoped_deploy.validate_rendered", side_effect=json.dumps), \
                patch("scoped_deploy.require_configs"), \
                patch("scoped_deploy.subprocess.run") as run:
            scoped_deploy.apply_scoped(with_background(with_redis()), lambda *arguments: [],
                                       scoped_deploy.SCOPES["background"][0])
        document = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(set(document["services"]), BACKGROUND_SERVICES)
        self.assertNotIn("--prune", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
