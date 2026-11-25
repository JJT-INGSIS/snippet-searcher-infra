"""Exercise the actual SSH tar in an isolated Python process, without the checkout on sys.path."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from redis_runtime import specification
from ssh_deploy import create_bundle
from test_expanded_release import expanded


class CdBundleTests(unittest.TestCase):
    def test_every_local_python_import_is_shipped_including_conditional_imports(self):
        root = Path(__file__).resolve().parent
        local = {file.stem for file in root.glob('*.py')}
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'tools.tar'
            create_bundle(bundle)
            with tarfile.open(bundle) as archive:
                modules = {Path(name).stem for name in archive.getnames() if name.startswith('scripts/')}
                for member in archive.getmembers():
                    if not member.name.endswith('.py'):
                        continue
                    tree = ast.parse(archive.extractfile(member).read(), filename=member.name)
                    for node in ast.walk(tree):
                        imported = ([node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module
                                    else [alias.name.split('.')[0] for alias in node.names]
                                    if isinstance(node, ast.Import) else [])
                        for name in set(imported) & local:
                            self.assertIn(name, modules, f'{member.name} imports missing {name}')

    def test_extracted_bundle_validates_and_renders_a_redis_release_without_repo_imports(self):
        release = expanded(assets=True, ui=True)
        release['infrastructure']['redis'] = specification('dev')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'tools.tar'
            extracted = root / 'deployed'
            extracted.mkdir()
            create_bundle(bundle)
            with tarfile.open(bundle) as archive:
                archive.extractall(extracted, filter='data')
            manifest = root / 'release.json'
            manifest.write_text(json.dumps(release))
            code = '''import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root/'scripts'))
import deploy_service,bootstrap_swarm,rollout_checks,redis_cd,redis_preflight
from stack_release import validate_manifest,expected_images
from stack_runtime import render_release,validate_rendered
from redis_runtime import REDIS_FILES
release=json.loads(Path(sys.argv[2]).read_text()); validate_manifest(release)
for key,file in REDIS_FILES.items():
 assert hashlib.sha256((root/file).read_bytes()).hexdigest()==release['infrastructure']['redis']['configs'][key]['sha256']
rendered=render_release(release); validate_rendered(rendered)
assert {name:spec['image'] for name,spec in rendered['services'].items()}==expected_images(release)
assert not rendered['services']['redis'].get('ports')
assert rendered['services']['permissions-service']['deploy']['update_config']['order']=='start-first'
print('PASS isolated extracted CD bundle: Redis imports, resources and existing images')
'''
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(extracted), str(manifest)],
                                    cwd=root, text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
