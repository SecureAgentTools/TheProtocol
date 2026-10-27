#!/bin/sh
# =============================================================
# The Directory sidecar's entrypoint (§SOVKIT T4, 2026-09-14)
# =============================================================
# Renders nginx-directory.conf.template with the proxy trust marker, then hands over to the SHARED
# sidecar entrypoint (/opt/nginx-entrypoint.sh: waits for the SVID, validates, runs nginx, reloads
# for rotation). The shared entrypoint substitutes nothing and nginx cannot read the environment, so
# the one value is rendered here, BY NAME: a bare `envsubst` would also eat nginx's own $host,
# $upstream and $remote_addr. Refuses to start rather than run a sidecar the Directory would refuse.
# Never prints the secret.
# =============================================================
set -e

TEMPLATE="${DIRECTORY_NGINX_TEMPLATE:-/etc/nginx/templates/nginx-directory.conf.template}"
OUT=/etc/nginx/conf.d/default.conf
SERVICE_NAME="${SERVICE_NAME:-directory-nginx}"
secret="${DIRECTORY_PROXY_TRUST_SECRET:-}"

case "$secret" in
    *[!A-Za-z0-9._~-]*)
        echo "[nginx:${SERVICE_NAME}] REFUSED: DIRECTORY_PROXY_TRUST_SECRET has characters outside [A-Za-z0-9._~-]"
        exit 1 ;;
esac
if [ "${#secret}" -lt 32 ]; then
    echo "[nginx:${SERVICE_NAME}] REFUSED: DIRECTORY_PROXY_TRUST_SECRET is unset or shorter than 32 characters"
    exit 1
fi
if [ ! -f "$TEMPLATE" ]; then
    echo "[nginx:${SERVICE_NAME}] REFUSED: template ${TEMPLATE} is missing"
    exit 1
fi

envsubst '${DIRECTORY_PROXY_TRUST_SECRET}' < "$TEMPLATE" > "$OUT"

if ! grep -q '^ *proxy_set_header X-Directory-Proxy-Auth "' "$OUT"; then
    echo "[nginx:${SERVICE_NAME}] REFUSED: the rendered conf carries no X-Directory-Proxy-Auth line"
    exit 1
fi
if grep -q '\${DIRECTORY_PROXY_TRUST_SECRET}' "$OUT"; then
    echo "[nginx:${SERVICE_NAME}] REFUSED: the marker variable was not substituted"
    exit 1
fi
echo "[nginx:${SERVICE_NAME}] rendered ${OUT} from ${TEMPLATE} (marker set, ${#secret} characters)"

exec /bin/sh /opt/nginx-entrypoint.sh
