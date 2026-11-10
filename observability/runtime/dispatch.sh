#!/bin/sh
# Runs inside the host agent. No database passwords or license key in argv/env.
set -eu
case "${1:-}" in
  snippets-db|permissions-db|redis|storage-local|snippets-db-disk|permissions-db-disk|redis-disk) ;;
  *) exit 1 ;;
esac
ids=$(/opt/runtime/docker ps --filter label=com.docker.swarm.service.name=snippet-observability-dev_collector --filter status=running --format '{{.ID}}')
# Fail closed during replacement/missing tasks. Do not select an arbitrary task.
test -n "$ids"
test "$(printf '%s\n' "$ids" | wc -l)" -eq 1
exec /opt/runtime/docker exec "$ids" python3 /opt/runtime/collect.py "$1"
