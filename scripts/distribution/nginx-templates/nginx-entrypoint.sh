#!/bin/sh
# =============================================================
# nginx mTLS Sidecar Entrypoint
# =============================================================
# OWL19: Waits for SVID certificate files from the cert-writer
# sidecar, then starts nginx. Periodically reloads nginx to
# pick up rotated certificates.
#
# Environment:
#   CERT_DIR     - certificate directory (default: /certs)
#   RELOAD_SEC   - nginx reload interval in seconds (default: 300)
#   SERVICE_NAME - for logging (default: unknown)
# =============================================================

set -e

CERT_DIR="${CERT_DIR:-/certs}"
RELOAD_SEC="${RELOAD_SEC:-300}"
SERVICE_NAME="${SERVICE_NAME:-unknown}"

echo "[nginx:${SERVICE_NAME}] Waiting for SVID certificates in ${CERT_DIR}..."

# Wait for cert-writer to produce the ready marker
WAIT_COUNT=0
MAX_WAIT=120
while [ ! -f "${CERT_DIR}/.ready" ]; do
    WAIT_COUNT=$((WAIT_COUNT + 1))
    if [ ${WAIT_COUNT} -ge ${MAX_WAIT} ]; then
        echo "[nginx:${SERVICE_NAME}] ERROR: Certificates not ready after ${MAX_WAIT}s"
        echo "[nginx:${SERVICE_NAME}] Contents of ${CERT_DIR}:"
        ls -la "${CERT_DIR}/" 2>/dev/null || echo "(directory does not exist)"
        exit 1
    fi
    if [ $((WAIT_COUNT % 10)) -eq 0 ]; then
        echo "[nginx:${SERVICE_NAME}] Still waiting... (${WAIT_COUNT}/${MAX_WAIT}s)"
    fi
    sleep 1
done

echo "[nginx:${SERVICE_NAME}] Certificates found:"
ls -la "${CERT_DIR}/"

# §2026-06-17: render the per-op TEG upstream into the active conf via envsubst.
# The generic `teg-layer` alias resolves to the MAINFRAME teg-a on the shared
# agentvault_identity_network (op nginx-teg drifts onto it non-deterministically),
# so we target the op's OWN teg by its unique container name. TEG_UPSTREAM_HOST =
# ${REGISTRY_NAME}-teg (globally unique → collision-proof AND network-drift-proof).
export TEG_UPSTREAM_HOST="${TEG_UPSTREAM_HOST:-teg-layer}"
if [ -f /etc/nginx/templates/nginx-teg.conf ]; then
    echo "[nginx:${SERVICE_NAME}] Rendering TEG upstream -> ${TEG_UPSTREAM_HOST}:8080"
    envsubst '${TEG_UPSTREAM_HOST}' < /etc/nginx/templates/nginx-teg.conf > /etc/nginx/conf.d/default.conf
fi

# Validate nginx config
echo "[nginx:${SERVICE_NAME}] Validating nginx configuration..."
nginx -t 2>&1 || {
    echo "[nginx:${SERVICE_NAME}] ERROR: nginx config validation failed"
    exit 1
}
echo "[nginx:${SERVICE_NAME}] Configuration valid"

# Start nginx in background
echo "[nginx:${SERVICE_NAME}] Starting nginx..."
nginx -g 'daemon off;' &
NGINX_PID=$!

echo "[nginx:${SERVICE_NAME}] nginx started (PID: ${NGINX_PID})"

# Cert reload loop — sends SIGHUP to nginx to reload certs
echo "[nginx:${SERVICE_NAME}] Starting cert reload loop (every ${RELOAD_SEC}s)"
while kill -0 ${NGINX_PID} 2>/dev/null; do
    sleep "${RELOAD_SEC}"
    
    if kill -0 ${NGINX_PID} 2>/dev/null; then
        echo "[nginx:${SERVICE_NAME}] Reloading nginx for cert rotation..."
        nginx -s reload 2>&1 || echo "[nginx:${SERVICE_NAME}] WARNING: reload signal failed"
    fi
done

echo "[nginx:${SERVICE_NAME}] nginx process exited"
wait ${NGINX_PID}
