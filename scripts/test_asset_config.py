import copy
import unittest

from validate_asset_config import validate_candidate, validate_runtime


def runtime():
    return {
        "asset-service": {
            "image": "ghcr.io/austral-ingsis/snippet-asset-service@sha256:" + "a" * 64,
            "environment": {"AZURE_HOST": "http://azurite", "NEW_RELIC_AGENT_ENABLED": "false"},
            "healthcheck": {"test": ["CMD", "health"]},
        },
        "azurite": {
            "image": "mcr.microsoft.com/azure-storage/azurite:3.35.0@sha256:" + "b" * 64,
            "command": ["azurite-blob", "--blobHost", "0.0.0.0", "--location", "/data", "--skipApiVersionCheck"],
            "volumes": [{"source": "asset_blobs", "target": "/data", "type": "volume"}],
            "healthcheck": {"test": ["CMD", "health"]},
            "deploy": {"placement": {"constraints": ["node.labels.asset_storage == true"]}},
        },
    }


def configs():
    base = {"services": {"snippets-service": {"image": "original-snippets", "environment": {"UNCHANGED": "value"},
                                              "volumes": ["content:/content"]},
                         "permissions-service": {"image": "original-permissions"},
                         "snippets-db": {"image": "original-postgres"}},
            "volumes": {"content": {"name": "original-content"}}, "secrets": {"db": {"external": True}}}
    expanded = copy.deepcopy(base)
    expanded["services"].update(runtime())
    expanded["services"]["snippets-service"]["environment"].update(
        STORAGE_PROVIDER="asset", STORAGE_ASSET_BASE_URL="http://asset-service:8080")
    expanded["volumes"]["asset_blobs"] = {"name": "new-blobs"}
    return base, expanded


class AssetConfigurationTests(unittest.TestCase):
    def test_additive_candidate_preserves_base_without_mutation(self):
        base, expanded = configs()
        before = copy.deepcopy(base)
        validate_candidate(base, expanded, "asset")
        self.assertEqual(base, before)

    def test_rejects_published_runtime_ports(self):
        for name in runtime():
            changed = runtime()
            changed[name]["ports"] = [{"published": 8083, "target": 8080}]
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_runtime(changed)

    def test_rejects_mutable_images_and_runtime_credentials(self):
        for field, value in (("image", "ghcr.io/austral-ingsis/snippet-asset-service:latest"),
                             ("secrets", [{"source": "github_token"}])):
            changed = runtime()
            changed["asset-service"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_runtime(changed)

    def test_requires_volume_at_effective_location(self):
        changed = runtime()
        changed["azurite"]["volumes"][0]["target"] = "/workspace"
        with self.assertRaises(ValueError):
            validate_runtime(changed)

    def test_rejects_changes_to_existing_images_volumes_secrets_or_settings(self):
        for section in ("image", "volume", "secret", "environment", "provider", "placement"):
            base, expanded = configs()
            if section == "image":
                expanded["services"]["permissions-service"]["image"] = "old-image"
            elif section == "volume":
                expanded["volumes"]["content"] = {"name": "wrong-volume"}
            elif section == "secret":
                expanded["secrets"] = {}
            elif section == "environment":
                expanded["services"]["snippets-service"]["environment"]["UNCHANGED"] = "changed"
            elif section == "provider":
                expanded["services"]["snippets-service"]["environment"]["STORAGE_PROVIDER"] = "local"
            else:
                expanded["services"]["azurite"]["deploy"]["placement"]["constraints"] = []
            with self.subTest(section=section), self.assertRaises(ValueError):
                validate_candidate(base, expanded, "asset")


if __name__ == "__main__":
    unittest.main()
