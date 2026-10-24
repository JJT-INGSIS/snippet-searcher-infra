import copy
import os
import subprocess
import unittest

from validate_nginx_config import NGINX_IMAGE, ROOT, validate_candidate


def configs():
    base = {"services": {"snippets-service": {"image": "original", "ports": [{"published": "8080", "target": 8080}],
                                              "environment": {"PROFILE": "prod"}},
                         "permissions-db": {"image": "original-postgres", "volumes": [{"source": "db", "target": "/data"}]}},
            "volumes": {"db": {"name": "original-data"}}, "secrets": {"db-password": {"external": True}}}
    candidate = copy.deepcopy(base)
    del candidate["services"]["snippets-service"]["ports"]
    candidate["services"]["nginx"] = {
        "image": NGINX_IMAGE, "ports": [{"published": "80", "target": 8080}],
        "configs": [{"source": name} for name in ("nginx_main", "nginx_routes", "nginx_env_check")],
        "volumes": [{"source": "ingress_acme", "target": "/var/www/acme", "read_only": True}],
    }
    candidate["configs"] = {name: {"name": "snippet-searcher-dev_" + name + "_v1", "file": "config"}
                            for name in ("nginx_main", "nginx_routes", "nginx_env_check")}
    return base, candidate


class NginxCandidateTests(unittest.TestCase):
    def test_candidate_only_removes_app_ports_and_adds_proxy(self):
        base, candidate = configs()
        original = copy.deepcopy(base)
        validate_candidate(base, candidate)
        self.assertEqual(base, original)

    def test_rejects_app_ports_remaining_or_other_app_changes(self):
        for change in ("ports", "image", "profile", "database"):
            base, candidate = configs()
            if change == "ports":
                candidate["services"]["snippets-service"]["ports"] = base["services"]["snippets-service"]["ports"]
            elif change == "image":
                candidate["services"]["snippets-service"]["image"] = "older-image"
            elif change == "profile":
                candidate["services"]["snippets-service"]["environment"]["PROFILE"] = "dev"
            else:
                candidate["services"]["permissions-db"]["volumes"] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_candidate(base, candidate)

    def test_rejects_lost_secrets_volumes_or_unexpected_services(self):
        for section in ("secrets", "volumes", "services"):
            base, candidate = configs()
            if section == "services":
                candidate["services"]["unexpected"] = {"image": "anything"}
            else:
                candidate[section] = {}
            with self.subTest(section=section), self.assertRaises(ValueError):
                validate_candidate(base, candidate)

    def test_rejects_mutable_proxy_image_secrets_or_public_nonhttp_port(self):
        for change in ("image", "secrets", "ports"):
            base, candidate = configs()
            nginx = candidate["services"]["nginx"]
            nginx[change] = {"image": "nginx:latest", "secrets": ["db-password"],
                             "ports": [{"published": "9090", "target": 8080}]}[change]
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_candidate(base, candidate)

    def test_configs_require_version_but_allow_a_future_reviewed_revision(self):
        base, candidate = configs()
        candidate["configs"]["nginx_routes"]["name"] = "snippet-searcher-dev_nginx_routes_v2"
        validate_candidate(base, candidate)
        candidate["configs"]["nginx_routes"]["name"] = "mutable-config"
        with self.assertRaises(ValueError):
            validate_candidate(base, candidate)

    def test_challenge_mount_cannot_be_writable(self):
        base, candidate = configs()
        candidate["services"]["nginx"]["volumes"][0]["read_only"] = False
        with self.assertRaises(ValueError):
            validate_candidate(base, candidate)


class NginxEnvironmentTests(unittest.TestCase):
    def test_invalid_substitutions_fail_before_entrypoint_without_echoing_value(self):
        values = [("attacker; return 200;", "80"), ("*.test", "80"), ("x..test", "80"), ("", "80"),
                  ("snippet.test", "0"), ("snippet.test", "65536"), ("snippet.test", "80;evil"),
                  ("snippet.test", "9999999999999999999999999")]
        for host, port in values:
            with self.subTest(host=host, port=port):
                result = subprocess.run(["sh", str(ROOT / "nginx/validate-env.sh"), "nginx", "-t"],
                                        env={**os.environ, "PROXY_HOSTNAME": host, "PROXY_PUBLIC_PORT": port},
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid", result.stderr)
                self.assertNotIn("return 200", result.stderr)

    def test_approved_limits_and_no_retry_or_global_streaming_settings(self):
        config = (ROOT / "nginx/nginx.conf").read_text()
        for setting in ("client_max_body_size 8m;", "proxy_connect_timeout 2s;", "proxy_read_timeout 60s;",
                        "proxy_send_timeout 60s;", "proxy_next_upstream off;", "proxy_intercept_errors off;"):
            self.assertIn(setting, config)
        self.assertNotIn("proxy_buffering off;", config)
        self.assertNotIn("$request_uri", config)
        self.assertNotIn("$http_authorization", config)


if __name__ == "__main__":
    unittest.main()
