#!/bin/sh
set -eu
# Runtime-only environment of redis-cli, never part of Docker Config.Env.
# Suppress all output, including errors, from the healthcheck log.
export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"
test "$(redis-cli --raw ping 2>/dev/null)" = PONG
test "$(redis-cli --raw CONFIG GET appendonly 2>/dev/null | tail -n 1)" = yes
test "$(redis-cli --raw INFO persistence 2>/dev/null | tr -d '\r' | sed -n 's/^aof_last_write_status://p')" = ok
