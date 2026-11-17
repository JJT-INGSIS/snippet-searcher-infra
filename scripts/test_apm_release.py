import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apm_runtime
import create_apm_license_secret
from stack_release import select_release, validate_manifest
from stack_runtime import render_release
from test_expanded_release import release
from test_tls_release import secured

JAVA_SERVICES = {"snippets-service", "permissions-service", "printscript-service"}
FAKE_LICENSE = "fixture-license-0123456789abcdef"
SECRET = "snippet-observability-dev-newrelic-license"


def with_apm(manifest, enabled=True):
    result = copy.deepcopy(manifest)
    result["apm"] = {"enabled": enabled}
    return result


def service_spec(enabled, environment="dev", secret=True):
    env = [f"NEW_RELIC_ENABLED={'true' if enabled else 'false'}", f"NEW_RELIC_ENVIRONMENT={environment}"]
    secrets = [{"SecretName": SECRET}] if secret else []
    return [{"Spec": {"TaskTemplate": {"ContainerSpec": {"Env": env, "Secrets": secrets}}}}]


class ApmReleaseTests(unittest.TestCase):
    def test_apm_is_an_explicit_boolean_of_v2_releases(self):
        validate_manifest(with_apm(secured()))
        validate_manifest(with_apm(secured(), enabled=False))
        for value in ({"enabled": "true"}, {"enabled": True, "extra": 1}, {}, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_manifest(secured() | {"apm": value})
        with self.assertRaises(ValueError):
            validate_manifest(release() | {"apm": {"enabled": True}})

    def test_an_infrastructure_change_carries_the_requested_apm(self):
        previous = secured()
        selected = select_release(with_apm(previous), previous, change_infrastructure=True)
        self.assertEqual(selected["apm"], {"enabled": True})

    def test_render_adds_activation_and_license_only_to_the_java_services(self):
        rendered = render_release(with_apm(secured()))
        for name, service in rendered["services"].items():
            environment = service.get("environment") or {}
            secrets = {entry["source"] for entry in service.get("secrets", [])}
            with self.subTest(service=name):
                if name in JAVA_SERVICES:
                    self.assertEqual(environment.get("NEW_RELIC_ENABLED"), "true")
                    self.assertEqual(environment.get("NEW_RELIC_ENVIRONMENT"), "dev")
                    self.assertIn("newrelic_license", secrets)
                else:
                    self.assertNotIn("NEW_RELIC_ENABLED", environment)
                    self.assertNotIn("newrelic_license", secrets)
        self.assertEqual(rendered["secrets"]["newrelic_license"], {"external": True, "name": SECRET})

    def test_render_without_apm_keeps_the_services_as_before(self):
        rendered = render_release(secured())
        self.assertNotIn("newrelic_license", rendered.get("secrets", {}))
        for name in JAVA_SERVICES:
            self.assertNotIn("NEW_RELIC_ENABLED", rendered["services"][name].get("environment") or {})


class ApmEffectiveConfigurationTests(unittest.TestCase):
    def check(self, manifest, spec, application=None):
        apm_runtime.require_apm_configuration(manifest, lambda *arguments: copy.deepcopy(spec), application)

    def test_running_services_must_match_the_release(self):
        self.check(with_apm(secured()), service_spec(True))
        self.check(secured(), service_spec(False, secret=False))
        mismatches = ((with_apm(secured()), service_spec(False)),
                      (with_apm(secured()), service_spec(True, secret=False)),
                      (with_apm(secured()), service_spec(True, environment="prod")),
                      (secured(), service_spec(True)))
        for manifest, spec in mismatches:
            with self.subTest(spec=json.dumps(spec)), self.assertRaises(ValueError):
                self.check(manifest, spec)

    def test_an_application_deploy_checks_only_that_service(self):
        calls = []
        apm_runtime.require_apm_configuration(with_apm(secured()),
                                              lambda *arguments: calls.append(arguments) or service_spec(True),
                                              "permissions-service")
        apm_runtime.require_apm_configuration(with_apm(secured()), lambda *arguments: calls.append(arguments), "ui")
        self.assertEqual(calls, [("service", "inspect", "snippet-searcher-dev_permissions-service")])


class LicenseSecretTests(unittest.TestCase):
    def run_create(self, exists, content):
        commands = []

        def run(command, **options):
            commands.append((command, options.get("input")))
            return subprocess.CompletedProcess(command, 0 if exists else 1, "", "")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "agent.json"
            if content is not None:
                source.write_text(content)
            with patch("create_apm_license_secret.agent_configuration", return_value=source):
                name = create_apm_license_secret.create("dev", run)
        return name, commands

    def test_the_agent_license_goes_to_docker_through_stdin_only(self):
        name, commands = self.run_create(False, json.dumps({"license_key": FAKE_LICENSE}))
        self.assertEqual(name, SECRET)
        self.assertEqual(commands[-1], (["docker", "secret", "create", SECRET, "-"], FAKE_LICENSE))
        self.assertTrue(all(FAKE_LICENSE not in " ".join(command) for command, _ in commands))

    def test_an_existing_secret_is_never_replaced(self):
        with self.assertRaises(ValueError):
            self.run_create(True, json.dumps({"license_key": FAKE_LICENSE}))

    def test_a_missing_or_invalid_agent_license_fails_without_echoing_it(self):
        with self.assertRaises(ValueError):
            self.run_create(False, None)
        with self.assertRaises(ValueError) as error:
            self.run_create(False, json.dumps({"license_key": FAKE_LICENSE + " "}))
        self.assertNotIn(FAKE_LICENSE, str(error.exception))


if __name__ == "__main__":
    unittest.main()
