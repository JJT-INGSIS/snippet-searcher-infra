import copy
import json
import unittest
from unittest.mock import patch

from github_cd import GitHub, TASK, record_evidence, require_authorized_head, require_verified_image, select_evidence, valid_evidence
from test_deploy_service import CHECKS, request


def receipt():
    return {**request(), 'schema': 1, 'outcome': 'verified', 'verified-at': '2026-10-13T12:00:00Z',
            'checks': CHECKS, 'previous-image': 'old', 'actual-image': request()['image-ref']}


def deployment():
    return {'id': 1, 'task': TASK, 'environment': 'dev', 'sha': request()['target-sha'],
            'creator': {'login': 'github-actions[bot]'}, 'payload': receipt()}


class FakeGitHub:
    def __init__(self, repository=None):
        self.repository = repository or request()['repository']
        self.records = [deployment()]
        self.current_sha = 'd' * 40
        self.tree = 'c' * 40
        self.protected = True
        self.merged_pr = True
        self.event = 'push'
        self.conclusion = 'success'
        self.workflows = [
            {'path': f'JJT-INGSIS/github-workflows/.github/workflows/{name}@v0.4.0', 'sha': 'a' * 40}
            for name in ('kotlin-service-pipeline.yml', 'cd.yml')]
        self.calls = []

    def pages(self, path):
        if path.startswith('/commits/'):
            return iter([{'merged_at': '2026-10-13', 'merge_commit_sha': self.current_sha,
                          'base': {'ref': 'main'}, 'head': {'ref': 'dev', 'repo': {'full_name': self.repository}}}]
                        if self.merged_pr else [])
        return iter(self.records)

    def request(self, path, data=None):
        self.calls.append((path, data))
        if data is not None:
            return {'id': 20}
        if path.startswith('/branches/'):
            return {'commit': {'sha': self.current_sha}, 'protected': self.protected}
        if path.startswith('/git/commits/'):
            return {'tree': {'sha': self.tree}}
        if '/actions/runs/' in path:
            return {'conclusion': self.conclusion, 'status': 'completed', 'event': self.event,
                    'head_branch': 'dev', 'head_sha': 'b' * 40,
                    'referenced_workflows': self.workflows,
                    'path': '.github/workflows/pipeline.yml', 'repository': {'full_name': self.repository}}
        raise AssertionError('Unexpected API call: ' + path)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHub()

    def test_historical_inactive_evidence_survives_status_retention(self):
        historical = deployment()
        historical['status'] = 'inactive'
        # No statuses or log endpoint exists on the fake: selection must use the
        # explicit persisted receipt and successful original workflow attempt.
        self.api.records = [
            {'task': 'deploy', 'environment': 'dev', 'payload': {}},
            {**deployment(), 'payload': {**receipt(), 'source-tree': 'f' * 40}},
            historical,
        ]
        selected = select_evidence(self.api, 'snippets-service', 'c' * 40)
        self.assertEqual(selected['image-ref'], request()['image-ref'])
        self.assertFalse(any('/statuses' in path for path, _ in self.api.calls))

    def test_different_main_sha_same_tree_promotes_exact_historical_digest(self):
        promoted = {**request('prod'), 'target-sha': self.api.current_sha}
        require_authorized_head(self.api, promoted)
        selected = select_evidence(self.api, 'snippets-service', promoted['source-tree'])
        self.assertEqual(selected['image-ref'], promoted['image-ref'])
        self.assertNotEqual(selected['source-sha'], promoted['target-sha'])

    def test_mismatched_tree_or_digest_and_missing_evidence_fail(self):
        for tree, image in [('e' * 40, None), ('c' * 40, 'different-digest')]:
            with self.subTest(tree=tree), self.assertRaises(ValueError):
                select_evidence(self.api, 'snippets-service', tree, image)
        self.api.records = []
        with self.assertRaises(ValueError):
            select_evidence(self.api, 'snippets-service', 'c' * 40)

    def test_prod_proof_requires_exact_digest_but_dev_does_not_need_previous_proof(self):
        promoted = {**request('prod'), 'target-sha': self.api.current_sha}
        require_verified_image(self.api, promoted)
        self.api.records = []
        require_authorized_head(self.api, promoted)
        with self.assertRaises(ValueError):
            require_verified_image(self.api, promoted)
        require_verified_image(self.api, request())

    def test_generic_or_untrusted_or_failed_receipt_is_not_evidence(self):
        cases = [
            {'task': 'deploy'}, {'environment': 'prod'}, {'creator': {'login': 'a-user'}},
            {'payload': {**receipt(), 'checks': {}}},
            {'payload': {**receipt(), 'image-ref': 'ghcr.io/jjt-ingsis/permissions-service@sha256:' + 'a' * 64}},
            {'sha': 'f' * 40}, {'payload': None},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertIsNone(valid_evidence(self.api, {**deployment(), **changes}, 'snippets-service', 'c' * 40))

    def test_failed_or_pr_run_cannot_validate_receipt(self):
        for event, conclusion in [('pull_request', 'success'), ('push', 'failure'), ('push', 'cancelled')]:
            with self.subTest(event=event, conclusion=conclusion):
                self.api.event, self.api.conclusion = event, conclusion
                self.assertIsNone(valid_evidence(self.api, deployment(), 'snippets-service', 'c' * 40))

    def test_git_commit_is_verified_against_receipt_tree(self):
        self.api.tree = 'e' * 40
        self.assertIsNone(valid_evidence(self.api, deployment(), 'snippets-service', 'c' * 40))

    def test_local_or_mixed_revision_workflow_cannot_supply_evidence(self):
        for workflows in ([], [{'path': '.github/workflows/cd.yml', 'sha': 'a' * 40}],
                          [self.api.workflows[0], {**self.api.workflows[1], 'sha': 'b' * 40}]):
            with self.subTest(workflows=workflows):
                self.api.workflows = workflows
                self.assertIsNone(valid_evidence(self.api, deployment(), 'snippets-service', 'c' * 40))

    def test_direct_push_or_unprotected_main_cannot_authorize_prod(self):
        promoted = {**request('prod'), 'target-sha': self.api.current_sha}
        for protected, merged in [(False, True), (True, False)]:
            self.api.protected, self.api.merged_pr = protected, merged
            with self.subTest(protected=protected), self.assertRaises(ValueError):
                require_authorized_head(self.api, promoted)

    def test_branch_advanced_is_rejected(self):
        with self.assertRaises(ValueError):
            require_authorized_head(self.api, request('prod'))

    def test_record_is_idempotent_and_never_auto_merges(self):
        self.api.records = []
        record_evidence(self.api, receipt())
        created = next(data for path, data in self.api.calls if path == '/deployments')
        self.assertFalse(created['auto_merge'])
        self.assertEqual(created['payload']['image-ref'], request()['image-ref'])
        self.assertFalse(self.api.calls[-1][1]['auto_inactive'])
        self.api.records = [deployment()]
        self.api.calls.clear()
        record_evidence(self.api, receipt())
        self.assertFalse(any(path == '/deployments' for path, _ in self.api.calls))

    def test_api_failure_does_not_mutate_receipt_or_vm_state(self):
        value = receipt()
        before = copy.deepcopy(value)
        with patch.object(self.api, 'request', side_effect=RuntimeError('GitHub unavailable')), self.assertRaises(RuntimeError):
            record_evidence(self.api, value)
        self.assertEqual(value, before)

    def test_recovered_or_prod_receipt_cannot_be_registered_as_dev_evidence(self):
        for changed in ({'outcome': 'recovered'}, {'environment': 'prod'}):
            with self.assertRaises(ValueError):
                record_evidence(self.api, {**receipt(), **changed})

    def test_pagination_finds_older_evidence_beyond_first_page(self):
        api = GitHub('JJT-INGSIS/snippets-service', '')
        get = self.api.request
        def response(path, data=None):
            if path.startswith('/deployments?'):
                return [{}] * 100 if path.endswith('&page=1') else [deployment()]
            return get(path, data)
        with patch.object(api, 'request', side_effect=response):
            self.assertEqual(select_evidence(api, 'snippets-service', 'c' * 40)['image-ref'], request()['image-ref'])


if __name__ == '__main__':
    unittest.main()
