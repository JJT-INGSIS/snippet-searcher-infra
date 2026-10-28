"""Negative controls for the external acceptance checks; no Azure access in CI."""
import json
import unittest
from unittest.mock import patch

from verify_public_ingress import check_api, check_redirect, check_runtime, header, port_closed


class PublicIngressTests(unittest.TestCase):
    def test_redirect_requires_308_and_exact_destination(self):
        host = 'snippet.test'
        expected = f'https://{host}/api/languages?probe=sni44'
        check_redirect(host, (308, [('Location', expected)], b''))
        for status, destination in ((301, expected), (308, 'http://snippet.test'), (308, 'https://other.test')):
            with self.subTest(status=status, destination=destination), self.assertRaises(ValueError):
                check_redirect(host, (status, [('Location', destination)], b''))

    def test_runtime_rejects_wrong_environment_dev_identity_in_prod_and_cached_config(self):
        def response(environment='prod', identity=None, cache='no-store'):
            return (200, [('Cache-Control', cache)], json.dumps({
                'environment': environment, 'identity': identity or {'mode': 'disabled'}}).encode())
        check_runtime('prod', response())
        for value in (response('dev'), response(identity={'mode': 'dev', 'actorId': 'x'}), response(cache='public')):
            with self.assertRaises(ValueError):
                check_runtime('prod', value)

    def test_api_does_not_accept_html_fallback_or_wrong_status(self):
        check_api((401, [('Content-Type', 'application/problem+json')], b'{"type":"unauthorized"}'), 401)
        for value in ((200, [('Content-Type', 'text/html')], b'<html/>'),
                      (200, [('Content-Type', 'application/json')], b'{}')):
            with self.assertRaises(ValueError):
                check_api(value, 401)

    def test_duplicate_cors_headers_are_detected_case_insensitively(self):
        with self.assertRaises(ValueError):
            header([('Access-Control-Allow-Origin', 'x'), ('access-control-allow-origin', 'x')],
                   'Access-Control-Allow-Origin')

    def test_closed_port_is_not_inferred_from_dns_failure(self):
        for error in (TimeoutError(), ConnectionRefusedError()):
            with patch('socket.create_connection', side_effect=error):
                self.assertTrue(port_closed('snippet.test', 8080))
        with patch('socket.create_connection', side_effect=OSError('DNS failed')), self.assertRaises(OSError):
            port_closed('snippet.test', 8080)


if __name__ == '__main__':
    unittest.main()
