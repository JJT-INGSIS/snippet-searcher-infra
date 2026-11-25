import json
import unittest
from pathlib import Path

import observability_runtime
import upgrade_observability_runtime_dev as upgrade

ROOT = Path(__file__).resolve().parent.parent


class RuntimeUpgradeTests(unittest.TestCase):
    def reviewed_compose(self):
        return (ROOT / "observability/runtime/agent.compose.yaml").read_text()

    def test_agent_compose_moves_every_runtime_mount_and_the_version_label(self):
        original = self.reviewed_compose()
        changed = upgrade.agent_compose(original)
        self.assertNotIn(str(upgrade.SOURCE), changed)
        self.assertEqual(changed.count(str(upgrade.TARGET)), original.count(str(upgrade.SOURCE)))
        self.assertIn("version: " + upgrade.VERSION, changed)
        self.assertIn("/etc/snippet-observability/dev/agent.json:/etc/newrelic-infra.yml:ro", changed)
        self.assertIn("snippet-observability-dev-agent-state:/var/db/newrelic-infra/data", changed)

    def test_unexpected_installed_compose_is_refused(self):
        for text in ("services: {}", self.reviewed_compose().replace(upgrade.PREVIOUS_VERSION, "other")):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                upgrade.agent_compose(text)

    def test_upgraded_configuration_renders_the_new_swarm_sample(self):
        config = json.loads((ROOT / "observability/config.example.json").read_text())
        rendered = observability_runtime.integrations(upgrade.upgraded_config(config))
        swarm = rendered["integrations"][-1]
        self.assertEqual(swarm["labels"]["version"], upgrade.VERSION)
        self.assertIn("swarm_sample.py", swarm["config"]["apis"][0]["commands"][0]["run"])

    def test_new_runtime_files_exist_in_the_repository(self):
        for source in upgrade.ADDED.values():
            with self.subTest(source=source.name):
                self.assertTrue(source.is_file())


if __name__ == "__main__":
    unittest.main()
