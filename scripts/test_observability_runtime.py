"""Contract checks for the actual host/private-network boundary."""

import copy
import json
import unittest
from pathlib import Path

import observability_runtime

REPO = Path(__file__).resolve().parent.parent


class RuntimeContract(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (REPO / "observability/config.example.json").read_text()
        )

    def test_agent_configuration_contains_no_database_credentials_or_command_secrets(
        self,
    ):
        result = observability_runtime.integrations(self.config)
        value = json.dumps(result)
        self.assertNotIn("PASSWORD", value)
        self.assertNotIn("passwordFile", value)
        self.assertNotIn("variables", result)
        self.assertEqual(len(result["integrations"]), 8)
        for item in result["integrations"][:3]:
            self.assertEqual(item["exec"][:2], ["/bin/sh", "/opt/runtime/dispatch.sh"])
        self.assertEqual(
            {i["labels"]["service"] for i in result["integrations"]},
            {
                "snippets-db",
                "permissions-db",
                "redis",
                "storage-local",
                "snippets-db-disk",
                "permissions-db-disk",
                "redis-disk",
                "swarm",
            },
        )

    def test_swarm_sample_compares_with_the_release_confirmed_by_cd(self):
        swarm = observability_runtime.integrations(self.config)["integrations"][-1]
        command = swarm["config"]["apis"][0]["commands"][0]["run"]
        self.assertEqual(
            command,
            "python3 /opt/runtime/swarm_sample.py --environment dev --release "
            "/host/home/azureuser/.local/state/snippet-searcher/dev/release.json",
        )

    def test_prod_cannot_be_rendered_by_dev_specific_dispatcher(self):
        config = copy.deepcopy(self.config)
        config["environment"] = "prod"
        with self.assertRaises(ValueError):
            observability_runtime.integrations(config)

    def test_absent_redis_is_not_collected(self):
        self.config["redis"] = None
        self.assertEqual(
            len(observability_runtime.integrations(self.config)["integrations"]), 7
        )


if __name__ == "__main__":
    unittest.main()
