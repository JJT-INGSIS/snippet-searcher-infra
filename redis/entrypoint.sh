#!/bin/sh
# No tracing, passwords in argv or credentials in inspectable service environment.
set -eu
umask 077
password_file=/run/secrets/redis_password
test -s "$password_file"
# A fixed-length random hexadecimal credential avoids ACL/config quoting ambiguity.
test "$(wc -c < "$password_file")" -eq 64
LC_ALL=C grep -qE '^[a-f0-9]{64}$' "$password_file"
mkdir -p /run/redis
chmod 700 /run/redis
digest="$(sha256sum "$password_file")"
digest="${digest%% *}"
printf 'user default on #%s ~* &* +@all\n' "$digest" > /run/redis/users.acl
chown -R redis:redis /run/redis
# The official entrypoint drops privileges and initializes the persistent volume.
exec /usr/local/bin/docker-entrypoint.sh redis-server /etc/redis/redis.conf
