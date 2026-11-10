#!/bin/sh
# Public deployment metadata and replica counts, without environment/secrets.
set -eu
rows=$(/opt/runtime/docker service ls --filter label=com.docker.stack.namespace=snippet-searcher-dev --format '{{.Name}} {{.Replicas}} {{.Image}}')
test -n "$rows"
printf '['
printf '%s\n' "$rows" | (
  separator=''
  while read -r service replicas image; do
    case "$service$image" in *[!a-zA-Z0-9_./:@-]*) exit 1 ;; esac
    running=${replicas%/*}
    desired=${replicas#*/}
    case "$running:$desired" in *[!0-9:]*) exit 1 ;; esac
    test -n "$running" && test -n "$desired"
    printf '%s{"environment":"dev","service":"%s","image":"%s","running":%s,"desired":%s}' "$separator" "$service" "$image" "$running" "$desired"
    separator=,
  done
)
printf ']\n'
