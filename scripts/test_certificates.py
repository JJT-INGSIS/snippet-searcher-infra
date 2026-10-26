import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import certificates

CHAIN = '-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----\nBBBB\n-----END CERTIFICATE-----\n'


class StateDirectory:
    def __init__(self, tls=True, pending=False, lock=True):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        release = {'environment': 'dev', 'infrastructure': {'nginx': {'hostname': 'snippet-dev.test', 'tls': tls}}}
        (self.path / 'release.json').write_text(json.dumps(release))
        if lock:
            (self.path / 'deploy.lock').write_text('')
        if pending:
            (self.path / 'pending.json').write_text('{}')

    def __enter__(self):
        self.patch = patch('certificates.state_directory', return_value=self.path)
        self.patch.start()
        return self

    def __exit__(self, *details):
        self.patch.stop()
        self.temporary.cleanup()


def certbot_run(result=0):
    return patch('certificates.subprocess.run', return_value=subprocess.CompletedProcess([], result))


class CertbotCommandTests(unittest.TestCase):
    def test_one_shot_pinned_container_sees_only_its_store_and_webroot(self):
        command = certificates.certbot('prod', 'renew')
        self.assertEqual(command[:3], ['docker', 'run', '--rm'])
        self.assertIn('certbot/certbot:v5.8.0@sha256:', certificates.CERTBOT_IMAGE)
        self.assertIn('/var/lib/snippet-searcher/prod/letsencrypt:/etc/letsencrypt', command)
        self.assertIn('snippet-searcher-prod_ingress_acme:/var/www/acme', command)
        self.assertNotIn('docker.sock', ' '.join(command))
        self.assertEqual(command[-1], '--non-interactive')

    def test_issue_uses_webroot_for_the_registered_name_and_staging_only_when_asked(self):
        staging = certificates.issue_arguments('snippet-dev.test', True, False)
        self.assertEqual(staging[:4], ['certonly', '--webroot', '-w', '/var/www/acme'])
        self.assertIn('--staging', staging)
        self.assertIn('--register-unsafely-without-email', staging)
        self.assertNotIn('--force-renewal', staging)
        replacement = certificates.issue_arguments('snippet-dev.test', False, True)
        self.assertNotIn('--staging', replacement)
        self.assertIn('--force-renewal', replacement)

    def test_only_the_leaf_of_the_chain_is_compared_with_the_served_certificate(self):
        self.assertEqual(certificates.leaf(CHAIN), '-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n')


class IssueTests(unittest.TestCase):
    def test_production_is_requested_once_and_never_replaced_by_staging(self):
        for staging in (False, True):
            with self.subTest(staging=staging), StateDirectory(), \
                    patch('certificates.certificate', return_value=CHAIN), \
                    patch('certificates.is_staging', return_value=False), certbot_run() as run, \
                    self.assertRaises(ValueError):
                certificates.issue('dev', staging)
            run.assert_not_called()

    def test_staging_certificate_is_replaced_by_production_and_reloaded(self):
        with StateDirectory(), patch('certificates.certificate', return_value=CHAIN), \
                patch('certificates.is_staging', return_value=True), patch('certificates.report'), \
                patch('certificates.reload_proxy') as reload, certbot_run() as run:
            certificates.issue('dev', False)
        self.assertIn('--force-renewal', run.call_args.args[0])
        self.assertNotIn('--staging', run.call_args.args[0])
        reload.assert_called_once_with('dev', 'snippet-dev.test', CHAIN)

    def test_first_issue_in_plain_http_does_not_touch_nginx(self):
        with StateDirectory(tls=False), patch('certificates.certificate', side_effect=[None, CHAIN]), \
                patch('certificates.report'), patch('certificates.reload_proxy') as reload, certbot_run() as run:
            certificates.issue('dev', True)
        self.assertIn('--staging', run.call_args.args[0])
        reload.assert_not_called()


class RenewTests(unittest.TestCase):
    def test_changed_certificate_is_reloaded_only_when_tls_is_published(self):
        for tls in (True, False):
            with self.subTest(tls=tls), StateDirectory(tls=tls), \
                    patch('certificates.certificate', side_effect=[CHAIN, CHAIN + 'new']), \
                    patch('certificates.report'), patch('certificates.reload_proxy') as reload, certbot_run():
                certificates.renew('dev', False)
            self.assertEqual(reload.called, tls)

    def test_unchanged_or_dry_run_certificate_does_not_reload(self):
        with StateDirectory(), patch('certificates.certificate', return_value=CHAIN), \
                patch('certificates.report'), patch('certificates.reload_proxy') as reload, certbot_run() as run:
            certificates.renew('dev', True)
        self.assertIn('--dry-run', run.call_args.args[0])
        reload.assert_not_called()

    def test_failed_renewal_is_reported_and_keeps_the_valid_certificate(self):
        with StateDirectory(), patch('certificates.certificate', return_value=CHAIN), \
                patch('certificates.describe', return_value=('issuer', 'Jan 20 00:00:00 2027 GMT')), \
                patch('certificates.reload_proxy') as reload, certbot_run(1), \
                self.assertRaisesRegex(RuntimeError, 'se conserva el certificado vigente, que vence Jan 20'):
            certificates.renew('dev', False)
        reload.assert_not_called()


class LockTests(unittest.TestCase):
    def test_pending_deployment_blocks_certificate_changes(self):
        with StateDirectory(pending=True), patch('certificates.certificate', return_value=CHAIN), \
                certbot_run() as run, self.assertRaisesRegex(RuntimeError, 'pendiente'):
            certificates.renew('dev', False)
        run.assert_not_called()

    def test_lock_is_never_created_by_root_outside_the_bootstrap(self):
        with StateDirectory(lock=False) as state, certbot_run() as run, self.assertRaises(FileNotFoundError):
            certificates.renew('dev', False)
        self.assertFalse((state.path / 'deploy.lock').exists())
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
