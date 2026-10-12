#!/usr/bin/env bash
set -euo pipefail
# Ejecutar dentro de la VM. No inicializa otro Swarm ni modifica contraseñas existentes.
readonly ENVIRONMENT="${1:?Indicar dev o prod}"
case "$ENVIRONMENT" in dev|prod) ;; *) echo 'Ambiente inválido' >&2; exit 1 ;; esac
[[ "$(hostname)" == "vm-snippet-$ENVIRONMENT" ]] || { echo 'VM equivocada' >&2; exit 1; }
[[ "$(docker info --format '{{.Swarm.ControlAvailable}}')" == true ]] || { echo 'Se necesita un manager de Swarm' >&2; exit 1; }
[[ "$(docker node ls -q | wc -l | tr -d ' ')" == 1 ]] || { echo 'Este procedimiento requiere un Swarm de un nodo' >&2; exit 1; }
command -v python3 >/dev/null
command -v openssl >/dev/null
command -v flock >/dev/null
readonly NODE="$(docker info --format '{{.Swarm.NodeID}}')"
# Comprobar ambos casos antes de crear secretos: nunca inventar una contraseña
# para una base con datos que fue inicializada con una contraseña anterior.
for service in snippets permissions; do
  if ! docker secret inspect "${service}_db_password" >/dev/null 2>&1 &&
     docker volume inspect "snippet-searcher-${ENVIRONMENT}_${service}_data" >/dev/null 2>&1; then
    echo "Existe el volumen de $service pero falta su secreto. Recuperar la contraseña original." >&2
    exit 1
  fi
done
docker node update --label-add database=true "$NODE" >/dev/null
for service in snippets permissions; do
  if docker secret inspect "${service}_db_password" >/dev/null 2>&1; then
    echo "Se conserva ${service}_db_password"
  else
    openssl rand -hex 32 | tr -d '\n' | docker secret create "${service}_db_password" - >/dev/null
    echo "Creado ${service}_db_password (valor oculto)"
  fi
done
docker node ls
echo "Preparación de $ENVIRONMENT completada. No se desplegaron servicios."
