#!/bin/bash
# generate-operator-env.sh — Generate unique .env, pgbouncer.ini and userlist.txt for a new operator
#
# Usage: ./generate-operator-env.sh <operator-name>
#
# This generates:
#   1. .env.operator — all secrets and config
#   2. pgbouncer.ini — connection pooler config with matching DB password
#   3. userlist.txt — the pooler's client passwords (SCRAM), the same two values
#   4. for an operator run on its own host (any name but cloud-op-*): its proxy trust secrets and Redis passwords in
#      .env.operator, redis-users.acl (their sha256 only) and the markers rendered into nginx/nginx-federation.conf and
#      nginx/nginx-teg.conf, everything the compose needs to boot on its own (CB-111)
#
# The operator-name argument is REQUIRED — it becomes the REGISTRY_NAME
# and is used for container naming, logging, and identification.
#
# The files land in the CURRENT directory, 0600; what it did goes to stderr and stdout stays empty, the contract of
# scripts/distribution/generate-operator-env.sh too (CB-006). A run redirected into .env.operator therefore no longer
# writes its progress lines over the head of the file it just wrote.
set -e
umask 077

OPERATOR_NAME="${1:?Usage: $0 <operator-name>}"

# ── Generate secrets
PG_PASS_REGISTRY=$(openssl rand -hex 24)
PG_PASS_TEG=$(openssl rand -hex 24)
API_KEY_SECRET=$(openssl rand -hex 32)

# ── Write .env.operator
cat > .env.operator << ENVEOF
# .env.operator — Generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Operator: ${OPERATOR_NAME}
# DO NOT COMMIT — contains secrets

# ── Identity
REGISTRY_NAME="${OPERATOR_NAME}"
OPERATOR_DID=did:theprotocol:operator-$(openssl rand -hex 8)

# ── Database passwords
PG_PASS_REGISTRY=${PG_PASS_REGISTRY}
PG_PASS_TEG=${PG_PASS_TEG}
PG_PASS_EVENT_STORE=$(openssl rand -hex 24)

# ── Security keys
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)
API_KEY_SECRET=${API_KEY_SECRET}
TEG_REGISTRY_JWT_SECRET=${API_KEY_SECRET}
TEG_ADMIN_API_KEY=$(openssl rand -hex 32)
TEG_AVTP_SYSTEM_API_KEY=$(openssl rand -hex 32)
TEG_TOKEN_SIGNING_KEY=$(openssl rand -hex 32)
# §SOVKIT-2 R2 (2026-09-14): no EVENT_STORE_INTERNAL_API_KEY; the operator authenticates to its parent's store by SVID.

# ── Token economy
MINTING_AUTHORITY=disabled

# ── Federation
FEDERATION_LICENSE_KEY=
KAFKA_BOOTSTRAP_SERVERS=
KAFKA_ENABLED=false

# ── Cross-TEG transfers
CROSS_TEG_ENABLED=true

# ── Email (CONFIGURE BEFORE DEPLOY)
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=noreply@example.com
MAIL_PASSWORD=CHANGE_ME
MAIL_FROM=noreply@example.com
MAIL_FROM_NAME="${OPERATOR_NAME}"
MAIL_STARTTLS=True
MAIL_SSL_TLS=False

# ── Monitoring
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 16)

# ── Features
ENABLE_PROJECTION_SNAPSHOTS=true
GENESIS_GRANT_ENABLED=true
GENESIS_GRANT_AMOUNT=5000.0
BETA_INVITE_REQUIRED=false
AUDITED_BALANCE_ENABLED=true

# ── Releases: the registry reads the signed release channel and tells its admins (a plain GET; false opts out)
RELEASE_CHANNEL_CHECK_ENABLED=true
ENVEOF

chmod 600 .env.operator
echo "[generate] Created .env.operator for '${OPERATOR_NAME}'" >&2

# ── Write pgbouncer.ini with matching DB passwords (registry + TEG)
# §pass66 (2026-05-22) — TEG now routes through pgbouncer too (per paris's
# pattern). Adding the teg_layer database route makes /admin/treasury/cross-
# teg-fund-send + all TEG transactions reachable. Without this the TEG
# container loops at "bouncer config error" and the whole operator stack
# fails docker compose up (TEG is a healthcheck dependency for registry).
cat > pgbouncer.ini << PGEOF
[databases]
agentvault_registry = host=db port=5432 dbname=agentvault_registry user=registry password=${PG_PASS_REGISTRY}
teg_layer = host=teg-db port=5432 dbname=teg_layer user=teg password=${PG_PASS_TEG} pool_size=200

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 800
default_pool_size = 150
reserve_pool_size = 10
ignore_startup_parameters = extra_float_digits,options
PGEOF

# §SECFIX (2026-09-25): the pooler checks every client's password. It was `auth_type = any`, which never asks: any
# container on the operator's network could open the registry's or the TEG's database as its owner with no password
# at all (measured on the sandbox operators: the right password, a wrong one and none all connected). The userlist
# carries the same two values the [databases] lines already hold, so SCRAM compares what the apps send against them.
cat > userlist.txt << ULEOF
"registry" "${PG_PASS_REGISTRY}"
"teg" "${PG_PASS_TEG}"
ULEOF

# Both files hold database passwords, so neither is world-readable. The compose runs pgbouncer as uid 1000 (the
# stack's own uid) so it can read them at 0600; a generator run as root hands them to that uid.
chmod 600 pgbouncer.ini userlist.txt
if [ "$(id -u)" = "0" ]; then
  chown 1000:1000 pgbouncer.ini userlist.txt
fi
echo "[generate] Created pgbouncer.ini and userlist.txt with matching passwords (0600)" >&2

# ── This operator's own secrets (CB-111): one marker per mTLS terminator (the app counts a forwarded certificate only
# beside its own proxy's), one Redis password per client, the ACL file Redis starts with (--aclfile), and the markers
# rendered into the two terminator confs. Without them the compose interpolates blanks, Redis cannot start and the
# bundle cannot boot on its own host. Same values, same shapes as the frame's renderer (services/operator_provisioner.
# py apply_operator_secrets and write_redis_acl). A CLOUD operator's frame creates and renders all of these itself after
# running this script (both its paths name the stack cloud-op-<safe>), and it refuses a conf whose marker already
# carries another value: a cloud-op-* name therefore leaves all of it to the frame.
case "$OPERATOR_NAME" in
  cloud-op-*)
    echo "[generate] ${OPERATOR_NAME} is a cloud operator: its frame writes the proxy trust secrets, the Redis passwords," \
         "redis-users.acl and the terminator markers" >&2
    exit 0
    ;;
esac

REGISTRY_PROXY_TRUST_SECRET=$(openssl rand -hex 32)
TEG_PROXY_TRUST_SECRET=$(openssl rand -hex 32)
REDIS_PASSWORD_REGISTRY=$(openssl rand -hex 32)
REDIS_PASSWORD_TEG=$(openssl rand -hex 32)
cat >> .env.operator << SECEOF

# ── This operator's own secrets: each mTLS terminator's marker and one Redis password per client
REGISTRY_PROXY_TRUST_SECRET=${REGISTRY_PROXY_TRUST_SECRET}
TEG_PROXY_TRUST_SECRET=${TEG_PROXY_TRUST_SECRET}
REDIS_PASSWORD_REGISTRY=${REDIS_PASSWORD_REGISTRY}
REDIS_PASSWORD_TEG=${REDIS_PASSWORD_TEG}
SECEOF

# One ACL user per client with everything the app needs and nothing administrative; the default user keeps PING for
# the healthcheck. Hashes only: the passwords live in .env.operator.
sha256_hex() { printf '%s' "$1" | openssl dgst -sha256 | awk '{print $NF}'; }
REDIS_APP_RULES="~* &* +@all -flushall -flushdb -config -debug -shutdown -acl -monitor -replicaof -slaveof -module -save -bgsave -bgrewriteaof -failover -cluster -migrate -restore -sync -psync -swapdb"
{
  echo "user default on nopass resetkeys resetchannels -@all +ping"
  echo "user registry on #$(sha256_hex "$REDIS_PASSWORD_REGISTRY") ${REDIS_APP_RULES}"
  echo "user teg on #$(sha256_hex "$REDIS_PASSWORD_TEG") ${REDIS_APP_RULES}"
} > redis-users.acl.tmp
mv -f redis-users.acl.tmp redis-users.acl
if [ "$(id -u)" = "0" ]; then
  # Redis in the image runs as uid 999 (group 1000): it reads the file, nobody else does
  chown 999:1000 redis-users.acl
  echo "[generate] Created redis-users.acl (0600, the redis uid's)" >&2
else
  # only root can give it to Redis's uid; it holds sha256 hashes of 256-bit secrets, nothing a reader can use
  chmod 644 redis-users.acl
  echo "[generate] Created redis-users.acl (0644: run this as root to give it to the redis uid at 0600)" >&2
fi

# The markers: each commented placeholder line (or a line an earlier run rendered) becomes the live directive with
# this run's value. nginx-federation.conf also fronts the operator's TEG (its cross-TEG block), so it carries both.
render_marker() {  # render_marker <conf> <header> <value>
  sed -E "s|^([[:space:]]*)(#OPDIST-MARKER#[[:space:]]+)?proxy_set_header[[:space:]]+$2[[:space:]]+\"[^\"]*\";|\\1proxy_set_header $2 \"$3\";|" \
    "$1" > "$1.tmp"
  mv -f "$1.tmp" "$1"
}
for conf in nginx/nginx-federation.conf nginx/nginx-teg.conf; do
  if [ ! -f "$conf" ]; then
    echo "[generate] $conf is not here (not a bundle directory?): its marker is not rendered" >&2
    continue
  fi
  if [ "$conf" = nginx/nginx-federation.conf ]; then
    render_marker "$conf" X-Registry-Proxy-Auth "$REGISTRY_PROXY_TRUST_SECRET"
  fi
  render_marker "$conf" X-TEG-Proxy-Auth "$TEG_PROXY_TRUST_SECRET"
  if grep -q -e '#OPDIST-MARKER#' -e '__REGISTRY_PROXY_TRUST_SECRET__' -e '__TEG_PROXY_TRUST_SECRET__' "$conf"; then
    echo "[generate] ERROR: $conf still carries a marker placeholder: its terminator would send a marker its app" \
         "refuses, so every mTLS call through it would be refused" >&2
    exit 1
  fi
  echo "[generate] Rendered the marker(s) in $conf (0600)" >&2
done
