#!/usr/bin/env bash
set -euo pipefail
EXPECTED_HOST=${1:?Pass the expected VM hostname}
[[ $(hostname) == "$EXPECTED_HOST" ]] || { echo 'Unexpected VM'; exit 1; }
d() { sudo -n docker "$@"; }
date -u +%Y-%m-%dT%H:%M:%SZ
hostname
id -nG
systemctl is-active docker
systemctl is-enabled docker
d version --format 'Client={{.Client.Version}} Server={{.Server.Version}}'
d info --format 'Architecture={{.Architecture}} Swarm={{.Swarm.LocalNodeState}} Control={{.Swarm.ControlAvailable}} NodeID={{.Swarm.NodeID}} Nodes={{.Swarm.Nodes}} Managers={{.Swarm.Managers}}'
[[ $(d info --format '{{.Swarm.LocalNodeState}}/{{.Swarm.ControlAvailable}}/{{.Swarm.Nodes}}/{{.Swarm.Managers}}') == active/true/1/1 ]] || { echo 'Unexpected Swarm topology'; exit 1; }
d node ls --format 'Node={{.ID}} Host={{.Hostname}} Status={{.Status}} Availability={{.Availability}} Manager={{.ManagerStatus}}'
d info --format 'ClusterID={{.Swarm.Cluster.ID}}'
d node inspect self --format 'Role={{.Spec.Role}} NodeState={{.Status.State}} Availability={{.Spec.Availability}} Address={{.Status.Addr}}'
[[ $(d node inspect self --format '{{.Status.State}}/{{.Spec.Availability}}/{{.ManagerStatus.Leader}}') == ready/active/true ]] || { echo 'Manager not ready'; exit 1; }
TEST_NAME="sni21-check-$(date +%s)-$$"
BEFORE=$(mktemp -d)
SERVICE_CREATED=no
SECRET_CREATED=no
cleanup() {
  STATUS=$?
  trap - EXIT
  if [[ $SERVICE_CREATED == yes ]]; then
    d service rm "$TEST_NAME" || STATUS=1
  fi
  if [[ $SECRET_CREATED == yes ]]; then
    for attempt in {1..15}; do
      if d secret rm "$TEST_NAME" >/dev/null 2>&1; then SECRET_CREATED=no; break; fi
      sleep 2
    done
    [[ $SECRET_CREATED == no ]] || { echo "CLEANUP FAILED secret=$TEST_NAME"; STATUS=1; }
  fi
  d service ls --format '{{.ID}} {{.Name}}' | sort > "$BEFORE/services-after"
  d secret ls --format '{{.ID}} {{.Name}}' | sort > "$BEFORE/secrets-after"
  diff -u "$BEFORE/services" "$BEFORE/services-after" || STATUS=1
  diff -u "$BEFORE/secrets" "$BEFORE/secrets-after" || STATUS=1
  echo "Cleanup status=$STATUS; original services/secrets compared"
  rm -rf "$BEFORE"
  exit "$STATUS"
}
d service ls --format '{{.ID}} {{.Name}}' | sort > "$BEFORE/services"
d secret ls --format '{{.ID}} {{.Name}}' | sort > "$BEFORE/secrets"
trap cleanup EXIT
printf 'SNI21 disposable runtime probe' | d secret create --label ticket=SNI-21 "$TEST_NAME" -
SECRET_CREATED=yes
d service create --detach --name "$TEST_NAME" --label ticket=SNI-21 --replicas 1 --restart-condition on-failure --secret "source=$TEST_NAME,target=sni21_probe" --env SNI21_REVISION=1 alpine:3.23 sh -c 'test -s /run/secrets/sni21_probe && exec sleep 86400'
SERVICE_CREATED=yes
wait_revision() {
  EXPECTED_REVISION=$1
  for attempt in {1..60}; do
    CONTAINER_ID=$(d ps -q --filter "label=com.docker.swarm.service.name=$TEST_NAME" --filter status=running)
    if [[ -n $CONTAINER_ID ]] && [[ $(d exec "$CONTAINER_ID" printenv SNI21_REVISION 2>/dev/null || true) == "$EXPECTED_REVISION" ]]; then
      d exec "$CONTAINER_ID" test -s /run/secrets/sni21_probe
      echo "PASS running revision=$EXPECTED_REVISION secret mounted"
      return 0
    fi
    sleep 2
  done
  d service ps --no-trunc "$TEST_NAME"
  return 1
}
wait_revision 1
d service inspect "$TEST_NAME" --format 'Test={{.Spec.Name}} Image={{.Spec.TaskTemplate.ContainerSpec.Image}} Ports={{json .Endpoint.Spec.Ports}}'
d service update --detach --env-add SNI21_REVISION=2 "$TEST_NAME"
wait_revision 2
d service ps "$TEST_NAME" --format 'Task={{.ID}} State={{.CurrentState}} Desired={{.DesiredState}}'
echo 'PASS service create/update and runtime secret; cleanup follows'
