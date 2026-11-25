"""Render a public PROD review bundle. Never contacts Docker, grants access or deploys."""

import argparse
import json
from pathlib import Path

import observability_config
from observability_runtime import split_integrations

REPO = Path(__file__).resolve().parent.parent
ROOT = '/opt/snippet-observability/prod/runtime-v1'
NETWORK = 'snippet-searcher-prod_default'
DATABASES = {'snippets-db': 'snippets', 'permissions-db': 'permissions'}
STORAGE = {
    'storage-local': ('local', '/observed/snippets-content', 'snippets_content', False),
    'snippets-db-disk': ('filesystem', '/observed/snippets-db', 'snippets_data', True),
    'permissions-db-disk': ('filesystem', '/observed/permissions-db', 'permissions_data', True),
}


def validate_topology(config):
    observability_config.validate(config)
    if config['environment'] != 'prod' or config['redis'] is not None:
        raise ValueError('Only the inventoried PROD topology without Redis is supported')
    if {row['service'] for row in config['postgres']} != set(DATABASES):
        raise ValueError('Require the two inventoried databases')
    for row in config['postgres']:
        secret = 'obs_' + row['service'].replace('-', '_') + '_password'
        if (row['host'], row['port'], row['database'], row['passwordFile']) != (
                row['service'], 5432, DATABASES[row['service']], '/run/secrets/' + secret):
            raise ValueError('Database destination differs from the reviewed PROD contract')
    if {row['service'] for row in config['storage']} != set(STORAGE):
        raise ValueError('Require active local storage and both database filesystems')
    for row in config['storage']:
        expected = STORAGE[row['service']]
        if (row['kind'], row.get('path')) != expected[:2]:
            raise ValueError('Storage destination differs from the inventoried volumes')


def bundle(config):
    validate_topology(config)
    locks = json.loads((REPO / 'observability/runtime/images.lock.json').read_text())
    labels = {'environment': 'prod', 'version': config['version']}
    secrets = ['obs_snippets_db_password', 'obs_permissions_db_password']
    collector = {
        'image': locks['collector'],
        'command': ['python3', '-c', 'import time; time.sleep(2147483647)'],
        'read_only': True, 'user': '10001:10001', 'cap_drop': ['ALL'],
        'networks': ['application'], 'secrets': secrets,
        'volumes': [
            {'type': 'tmpfs', 'target': '/tmp', 'tmpfs': {'size': 33554432}},
            ROOT + ':/opt/runtime:ro', ROOT + '/probes:/opt/probes:ro',
            ROOT + '/bin:/opt/bin:ro',
            *[{'type': 'volume', 'source': name, 'target': target,
               'read_only': readonly}
              for name, (_, target, _, readonly) in STORAGE.items()],
        ],
        'deploy': {
            'replicas': 1,
            'placement': {'constraints': ['node.hostname == vm-snippet-prod']},
            'resources': {'limits': {'memory': '256M', 'cpus': '0.50'},
                          'reservations': {'memory': '32M'}},
            'update_config': {'order': 'stop-first', 'failure_action': 'rollback'},
            'restart_policy': {'condition': 'any', 'delay': '10s'},
        },
        'labels': {**labels, 'service': 'dependency-collector'},
        'logging': {'driver': 'json-file', 'options': {'max-size': '5m', 'max-file': '2'}},
    }
    agent = {
        'image': locks['agent'], 'container_name': 'snippet-observability-prod-agent',
        'hostname': 'vm-snippet-prod', 'network_mode': 'host', 'pid': 'host',
        'cgroup': 'host', 'privileged': True, 'cap_add': ['SYS_PTRACE'],
        'restart': 'unless-stopped', 'environment': {'DOCKER_API_VERSION': '1.44'},
        'volumes': [
            '/:/host:ro', '/var/run/docker.sock:/var/run/docker.sock',
            '/etc/snippet-observability/prod/agent.json:/etc/newrelic-infra.yml:ro',
            ROOT + ':/opt/runtime:ro',
            ROOT + '/integrations.json:/etc/newrelic-infra/integrations.d/snippet.json.yml:ro',
            ROOT + '/docker-config.yml:/etc/newrelic-infra/integrations.d/docker-config.yml:ro',
            'agent-state:/var/db/newrelic-infra/data',
        ],
        'mem_limit': '384m', 'cpus': 0.5,
        'labels': {**labels, 'service': 'infrastructure-agent'},
        'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '2'}},
    }
    dispatch = '''#!/bin/sh
set -eu
case "${1:-}" in
  snippets-db|permissions-db|storage-local|snippets-db-disk|permissions-db-disk) ;;
  *) exit 1 ;;
esac
ids=$(/opt/runtime/docker ps --filter label=com.docker.swarm.service.name=snippet-observability-prod_collector --filter status=running --format '{{.ID}}')
test -n "$ids"
test "$(printf '%s\\n' "$ids" | wc -l)" -eq 1
exec /opt/runtime/docker exec "$ids" python3 /opt/runtime/collect.py "$1"
'''
    return {
        'status': 'REVIEW_ONLY_NOT_APPLIED',
        'agentCompose': {'services': {'agent': agent},
                         'volumes': {'agent-state': {'name': 'snippet-observability-prod-agent-state'}}},
        'collectorStack': {
            'version': '3.8', 'services': {'collector': collector},
            'networks': {'application': {'external': True, 'name': NETWORK}},
            'volumes': {name: {'external': True, 'name': 'snippet-searcher-prod_' + volume}
                        for name, (_, _, volume, _) in STORAGE.items()},
            'secrets': {name: {'external': True} for name in secrets},
        },
        'integrations': split_integrations(config),
        'dispatch': dispatch,
        'requiresBeforeApplication': [
            'Revalidate live PROD inventory, UID/GID, DNS and confirmed release',
            'Approve privileged host agent, dedicated pg_monitor grants and PROD ingest destination',
            'Stage pinned binaries and probes; provision dedicated secrets without copying DEV',
            'Validate release/CD compatibility and agent/collector recovery',
        ],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path,
                        default=REPO / 'observability/config.prod-local.example.json')
    args = parser.parse_args()
    try:
        print(json.dumps(bundle(json.loads(args.config.read_text())), indent=2))
    except (ValueError, OSError, KeyError, TypeError):
        raise SystemExit('Invalid PROD candidate; no changes applied') from None
