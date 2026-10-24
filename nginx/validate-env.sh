#!/bin/sh
set -eu

# Configuration is controlled by operators, not the incoming Host header.
# Restrict substitutions so an invalid env value cannot inject NGINX directives.
case "${PROXY_HOSTNAME:-}" in
    ''|*[!a-z0-9.-]*|.*|*..*|*.) echo 'Invalid PROXY_HOSTNAME' >&2; exit 1 ;;
esac
test "${#PROXY_HOSTNAME}" -le 253 || { echo 'PROXY_HOSTNAME too long' >&2; exit 1; }
case "${PROXY_PUBLIC_PORT:-}" in
    ''|*[!0-9]*) echo 'Invalid PROXY_PUBLIC_PORT' >&2; exit 1 ;;
esac
test "${#PROXY_PUBLIC_PORT}" -le 5 && test "$PROXY_PUBLIC_PORT" -ge 1 && test "$PROXY_PUBLIC_PORT" -le 65535 || {
    echo 'Invalid PROXY_PUBLIC_PORT range' >&2; exit 1;
}

exec /docker-entrypoint.sh "$@"
