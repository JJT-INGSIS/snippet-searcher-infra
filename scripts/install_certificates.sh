#!/usr/bin/env bash
set -euo pipefail
readonly ENVIRONMENT="${1:?Indicar dev o prod}"
case "$ENVIRONMENT" in dev|prod) ;; *) echo 'Ambiente inválido' >&2; exit 1 ;; esac
[[ "$(hostname)" == "vm-snippet-$ENVIRONMENT" ]] || { echo 'VM equivocada' >&2; exit 1; }
[[ "$(id -u)" == 0 ]] || { echo 'Ejecutar con sudo' >&2; exit 1; }
readonly STORE="/var/lib/snippet-searcher/$ENVIRONMENT/letsencrypt"
readonly TOOLS=/usr/local/lib/snippet-searcher
install -d -m 0755 /var/lib/snippet-searcher "$TOOLS"
install -d -m 0700 "/var/lib/snippet-searcher/$ENVIRONMENT" "$STORE" "$STORE/live" "$STORE/archive"
install -m 0644 scripts/certificates.py scripts/stack_release.py "$TOOLS/"
install -m 0644 systemd/snippet-certificates@.service systemd/snippet-certificates@.timer /etc/systemd/system/
systemctl daemon-reload
echo "Preparado $STORE (root, 0700) e instaladas las unidades. El timer se habilita después del primer certificado."
