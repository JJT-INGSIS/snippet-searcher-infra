#!/bin/sh
set -eu
umask 077
password_file=/run/secrets/redis_password
test -s "$password_file"
test "$(wc -c < "$password_file")" -eq 64
LC_ALL=C grep -qE '^[a-f0-9]{64}$' "$password_file"
mkdir -p /run/redis
chmod 700 /run/redis
digest="$(sha256sum "$password_file")"
digest="${digest%% *}"
printf 'user default on #%s ~* &* +@all\n' "$digest" > /run/redis/users.acl
monitor_file=/run/secrets/obs_redis_password
if test -e "$monitor_file"; then
    if test "$(wc -c < "$monitor_file")" -eq 64 && LC_ALL=C grep -qE '^[a-f0-9]{64}$' "$monitor_file"; then
        monitor_digest="$(sha256sum "$monitor_file")"
        monitor_digest="${monitor_digest%% *}"
        printf 'user nri_monitor on #%s -@all +info +ping\n' "$monitor_digest" >> /run/redis/users.acl
    else
        printf '%s\n' 'Invalid monitoring credential; monitoring user disabled' >&2
    fi
fi
chown -R redis:redis /run/redis
exec /usr/local/bin/docker-entrypoint.sh redis-server /etc/redis/redis.conf
