"""Render legacy/expanded variants read-only. Fixture UI digests are NEVER deployed."""
import hashlib
import json
import os

from stack_release import NGINX_FILES, expected_images, upgrade_release, validate_manifest
from stack_runtime import ROOT, render_release, validate_rendered
from validate_asset_config import render
from validate_nginx_config import NGINX_IMAGE


def candidates():
    for environment in ('dev', 'prod'):
        base = json.loads((ROOT / f'swarm/{environment}-release.json').read_text())
        yield base
        settings = {**os.environ, **validate_manifest(base), 'STORAGE_PROVIDER': 'local'}
        asset = render(['swarm/stack.yaml', 'swarm/stack.asset.yaml'], settings)
        for assets, provider, ui in ((False, 'local', False), (True, 'local', False),
                                      (True, 'asset', False), (True, 'asset', True)):
            value = upgrade_release(base)
            value['infrastructure']['nginx'] = {'image': NGINX_IMAGE, 'hostname': 'snippet.test', 'port': 80,
                'configs': {key: {'name': f'snippet-searcher-{environment}_{key}_v1',
                    'sha256': hashlib.sha256((ROOT / file).read_bytes()).hexdigest()}
                           for key, file in NGINX_FILES.items()}}
            if assets:
                value['infrastructure'].update({name: {'image': asset['services'][name]['image']}
                                                for name in ('asset-service', 'azurite')})
            value['storage_provider'] = provider
            if ui:
                value['images']['ui'] = 'ghcr.io/jjt-ingsis/snippet-searcher-ui@sha256:' + 'c' * 64
            yield value


def main():
    for value in candidates():
        data = render_release(value)
        assert {name: service['image'] for name, service in data['services'].items()} == expected_images(value)
        if 'nginx' in data['services']:
            assert all(not service.get('ports') for name, service in data['services'].items() if name != 'nginx')
        validate_rendered(data)
        print(f'PASS operational render {value["environment"]}; services={len(data["services"])}; '
              f'provider={value.get("storage_provider", "local")}; no deployment')


if __name__ == '__main__':
    main()
