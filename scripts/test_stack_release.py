import copy
import json
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import bootstrap_swarm
from stack_release import select_release, update_service, validate_manifest, validate_promotion, write_record


def manifest(environment='dev'):
    return json.loads((bootstrap_swarm.ROOT / f'swarm/{environment}-release.json').read_text())


class ReleaseContractTests(unittest.TestCase):
    def test_reapply_preserves_current_app_and_database_references_without_mutation(self):
        requested = manifest()
        current = {**requested, 'images': {**requested['images'], 'permissions-service': 'ghcr.io/jjt-ingsis/permissions-service@sha256:' + 'a'*64}, 'database_image': 'postgres:18.6-bookworm@sha256:' + 'b'*64}
        before = copy.deepcopy(current)
        selected = select_release(requested,current)
        self.assertEqual(selected['images'],current['images'])
        self.assertEqual(selected['database_image'],current['database_image'])
        self.assertEqual(current,before)

    def test_reapply_preserves_cd_receipts(self):
        current = {**manifest(), 'deployments': {'snippets-service': {'run-id': 10, 'outcome': 'verified'}}}
        self.assertEqual(select_release(manifest(), current)['deployments'], current['deployments'])

    def test_bootstrap_refuses_unresolved_cd_before_any_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            state = home / '.local/state/snippet-searcher/dev'
            state.mkdir(parents=True)
            write_record(state / 'pending.json', {'operation': 'snippets-service-10-1'})
            source = home / 'manifest.json'
            write_record(source, manifest())
            with patch('bootstrap_swarm.sys.argv', ['bootstrap_swarm.py', 'deploy', str(source)]), \
                    patch('bootstrap_swarm.pwd.getpwnam', return_value=SimpleNamespace(pw_dir=str(home))), \
                    patch('bootstrap_swarm.os.geteuid', return_value=1000), \
                    patch('bootstrap_swarm.execute') as execute, self.assertRaises(RuntimeError):
                bootstrap_swarm.main()
            execute.assert_not_called()

    def test_update_changes_only_target_and_leaves_input_unchanged(self):
        old=manifest()
        original=copy.deepcopy(old)
        changed=update_service(old,'printscript-service','ghcr.io/jjt-ingsis/printscript-service@sha256:'+'a'*64)
        self.assertEqual(old,original)
        for name in ('snippets-service','permissions-service'):
            self.assertEqual(changed['images'][name],old['images'][name])
        self.assertNotEqual(changed['images']['printscript-service'],old['images']['printscript-service'])

    def test_cross_environment_and_mutable_or_wrong_package_rejected(self):
        with self.assertRaises(ValueError): select_release(manifest(),manifest('prod'))
        for image in ('ghcr.io/jjt-ingsis/snippets-service:latest',manifest()['images']['permissions-service'],'$(touch /tmp/unsafe)'):
            candidate={**manifest(),'images':{**manifest()['images'],'snippets-service':image}}
            with self.subTest(image=image),self.assertRaises(ValueError): validate_manifest(candidate)

    def test_promotion_requires_confirmed_dev_and_identical_digests(self):
        dev={**manifest(),'checks':{'sql_and_internal_http':'passed'}}
        validate_promotion(manifest('prod'),dev)
        with self.assertRaises(ValueError): validate_promotion(manifest('prod'),manifest())
        altered=update_service(manifest('prod'),'permissions-service','ghcr.io/jjt-ingsis/permissions-service@sha256:'+'a'*64)
        with self.assertRaises(ValueError): validate_promotion(altered,dev)

    def test_wrong_vm_fails_before_pull_or_deploy(self):
        with patch('bootstrap_swarm.docker_json',return_value={'Name':'vm-snippet-prod','Swarm':{'ControlAvailable':True}}),patch('bootstrap_swarm.subprocess.run') as run,self.assertRaises(ValueError):
            bootstrap_swarm.preflight(manifest(),{})
        run.assert_not_called()

    def test_failed_submission_convergence_or_checks_preserve_confirmed_record(self):
        for stage in range(3):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                state=Path(directory)
                old=manifest()
                write_record(state/'release.json',old)
                outcomes=[subprocess.CompletedProcess([],0) for _ in range(3)]
                outcomes[stage]=subprocess.CalledProcessError(1,'verification')
                with patch('bootstrap_swarm.preflight'),patch('bootstrap_swarm.verify_database_images'),patch('bootstrap_swarm.subprocess.run',side_effect=outcomes),self.assertRaises(subprocess.CalledProcessError):
                    bootstrap_swarm.execute(manifest(),{},state)
                self.assertEqual(json.loads((state/'release.json').read_text()),old)
                self.assertFalse((state/'history').exists())

    def test_success_confirms_record_after_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            with patch('bootstrap_swarm.preflight'),patch('bootstrap_swarm.verify_database_images'),patch('bootstrap_swarm.subprocess.run'):
                bootstrap_swarm.execute(manifest(),{},state)
            record=json.loads((state/'release.json').read_text())
            self.assertEqual(record['images'],manifest()['images'])
            self.assertEqual(record['checks']['sql_and_internal_http'],'passed')
            self.assertEqual(len(list((state/'history').glob('*.json'))),1)


class ConvergenceGuardTests(unittest.TestCase):
    def test_database_digest_mismatch_is_rejected(self):
        import os
        import wait_for_stack
        from stack_release import STACK_SERVICES
        release=manifest()
        selected=validate_manifest(release)
        expected={**release['images'], 'snippets-db':release['database_image'], 'permissions-db':release['database_image']}
        def response(*arguments):
            name=arguments[-1].split('_',1)[-1]
            if arguments[0]=='service':
                image=expected[name] if name!='snippets-db' else 'postgres:18.6-bookworm@sha256:'+'a'*64
                return [{'UpdateStatus':{'State':'completed'},'Spec':{'TaskTemplate':{'ContainerSpec':{'Image':image}},'Mode':{'Replicated':{'Replicas':1}}}}]
            return [{'Status':{'State':'running'},'Spec':{'ContainerSpec':{'Image':expected[name]}}}]
        with patch.dict(os.environ,selected),patch('wait_for_stack.docker_json',side_effect=response),patch('wait_for_stack.subprocess.check_output',side_effect=lambda args,**kwargs:args[-1]),self.assertRaises(RuntimeError):
            wait_for_stack.converged('snippet-searcher-dev')
