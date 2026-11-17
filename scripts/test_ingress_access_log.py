import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FORMAT = re.compile(r"log_format ingress escape=json((?:\s*'[^']*')+);")
QUOTED = re.compile(r"'([^']*)'")
VARIABLE = re.compile(r"\$[a-z_]+")
LOCATION = re.compile(r"^location ([^{]+)\{(.*?)^\}", re.MULTILINE | re.DOTALL)
SAMPLE_VALUE = "1"
FIELDS = {"time", "request_id", "method", "path", "route", "status", "bytes_sent", "request_time",
          "upstream", "upstream_status", "upstream_connect_time", "upstream_response_time"}
NUMERIC_FIELDS = {"status", "bytes_sent", "request_time"}
FORBIDDEN = ("$remote_addr", "$http_", "$cookie_", "$args", "$arg_", "$query_string", "$request_uri",
             "$request ", "$request'", "$request_body", "$remote_user", "$sent_http_")
ROUTE_MAP = ("map $uri $ingress_route {", "~^/api/executions/ executions;", "~^/api(?:/|$) api;", "default ui;")
REQUEST_ID_HEADER = "add_header X-Request-ID $request_id always;"


def nginx_config():
    return (ROOT / "nginx/nginx.conf").read_text()


def routes_template():
    return (ROOT / "nginx/templates/routes.conf.template").read_text()


def ingress_format():
    found = LOG_FORMAT.search(nginx_config())
    if found is None:
        raise AssertionError("Missing JSON ingress log_format")
    return "".join(QUOTED.findall(found.group(1)))


class IngressLogFormatTests(unittest.TestCase):
    def test_each_line_is_json_with_the_approved_fields(self):
        line = json.loads(VARIABLE.sub(SAMPLE_VALUE, ingress_format()))
        self.assertEqual(set(line), FIELDS)
        for field in NUMERIC_FIELDS:
            self.assertIsInstance(line[field], int)
        for field in FIELDS - NUMERIC_FIELDS:
            self.assertIsInstance(line[field], str)

    def test_path_never_contains_the_query_string(self):
        self.assertIn('"path":"$uri"', ingress_format())

    def test_no_client_address_credentials_headers_or_query(self):
        log_format = ingress_format()
        for variable in FORBIDDEN:
            with self.subTest(variable=variable):
                self.assertNotIn(variable, log_format + "'")

    def test_access_log_uses_the_json_format(self):
        self.assertIn("access_log /dev/stdout ingress;", nginx_config())

    def test_route_is_derived_from_the_path_with_executions_before_api(self):
        config = nginx_config()
        positions = [config.find(line) for line in ROUTE_MAP]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        self.assertIn('"route":"$ingress_route"', ingress_format())


class RequestIdResponseTests(unittest.TestCase):
    def test_request_id_is_always_generated_by_nginx(self):
        template = routes_template()
        self.assertIn("proxy_set_header X-Request-ID $request_id;", template)
        self.assertIn("proxy_hide_header X-Request-ID;", template)
        self.assertNotIn("$http_x_request_id", template + nginx_config())

    def test_every_proxied_response_returns_the_request_id(self):
        template = routes_template()
        top_level = LOCATION.sub("", template)
        self.assertIn(REQUEST_ID_HEADER, top_level)
        for path, body in LOCATION.findall(template):
            if "add_header" in body:
                with self.subTest(location=path.strip()):
                    self.assertIn(REQUEST_ID_HEADER, body)


class IngressLoggingDriverTests(unittest.TestCase):
    def test_nginx_writes_to_journald_with_a_fixed_tag(self):
        stack = (ROOT / "swarm/stack.ingress.yaml").read_text()
        self.assertRegex(stack, r"logging:\n\s+driver: journald\n\s+options:\n\s+tag: snippet-ingress")

    def test_local_compose_keeps_the_default_driver(self):
        self.assertNotIn("journald", (ROOT / "compose.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
