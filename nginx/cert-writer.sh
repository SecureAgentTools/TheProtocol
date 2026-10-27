#!/bin/sh
# =============================================================
# SPIRE SVID Certificate Writer for nginx mTLS Sidecars
# =============================================================
# OWL19: Fetches X.509 SVIDs from the SPIRE Workload API and
# writes them to /certs/ for nginx to read.
#
# Runs in a container with the SPIRE agent socket mounted.
# The container's Docker labels determine which SVID is issued
# (via SPIRE Docker workload attestor).
#
# Output files:
#   /certs/svid.0.pem    - certificate chain (server cert)
#   /certs/svid.0.key    - private key
#   /certs/bundle.0.pem  - trust bundle (CA certs)
#
# Usage: Set as container entrypoint.
# Environment:
#   SPIRE_SOCKET   - path to agent socket (default: /opt/spire/sockets/agent.sock)
#   CERT_DIR       - output directory (default: /certs)
#   REFRESH_SEC    - refresh interval in seconds (default: 300)
#   SERVICE_NAME   - for logging (default: unknown)
# =============================================================

set -e

SPIRE_SOCKET="${SPIRE_SOCKET:-/opt/spire/sockets/agent.sock}"
CERT_DIR="${CERT_DIR:-/certs}"
REFRESH_SEC="${REFRESH_SEC:-300}"
SERVICE_NAME="${SERVICE_NAME:-unknown}"

echo "[cert-writer:${SERVICE_NAME}] Starting SVID certificate writer"
echo "[cert-writer:${SERVICE_NAME}] Socket: ${SPIRE_SOCKET}"
echo "[cert-writer:${SERVICE_NAME}] Output: ${CERT_DIR}"
echo "[cert-writer:${SERVICE_NAME}] Refresh: every ${REFRESH_SEC}s"

# Ensure output directory exists
mkdir -p "${CERT_DIR}"

# Wait for SPIRE agent socket to be available
echo "[cert-writer:${SERVICE_NAME}] Waiting for SPIRE agent socket..."
WAIT_COUNT=0
MAX_WAIT=60
while [ ! -S "${SPIRE_SOCKET}" ]; do
    WAIT_COUNT=$((WAIT_COUNT + 1))
    if [ ${WAIT_COUNT} -ge ${MAX_WAIT} ]; then
        echo "[cert-writer:${SERVICE_NAME}] ERROR: SPIRE socket not available after ${MAX_WAIT}s"
        exit 1
    fi
    sleep 1
done
echo "[cert-writer:${SERVICE_NAME}] SPIRE agent socket found"

# ONE PUBLISH STEP for the first fetch and every refresh (§SECFIX 2026-09-26). SPIRE's -write puts the SVID, its key,
# the local bundle and ONE federated_bundle.<svid>.<n>.pem PER TRUST DOMAIN the entry federates with TODAY into a
# directory; this fetches into a temporary one and publishes the whole set: bundle.0.pem = the local CAs + every
# current federated root, the current federated_bundle files copied, and every federated_bundle file the fetch did
# NOT produce removed. Before this, nothing ever removed one: a federation that ended (salut's, and an older
# sandbox-b bundle, measured on sbx-alpha and sbxalphaop) stayed on disk, where the TEG's cross-TEG client reads every
# federated_bundle.* file as a trusted root, and the first fetch after a restart appended the leftovers to
# bundle.0.pem as well (it wrote into CERT_DIR and globbed it) until the next refresh replaced it.
_fetch_and_publish() {
    # not TMPDIR: that is the name mktemp itself reads for its parent directory
    FETCH_DIR=$(mktemp -d) || return 1
    if ! /opt/spire/bin/spire-agent api fetch x509 \
        -socketPath "${SPIRE_SOCKET}" \
        -write "${FETCH_DIR}" 2>&1; then
        rm -rf "${FETCH_DIR}"
        return 1
    fi
    if [ ! -f "${FETCH_DIR}/svid.0.pem" ] || [ ! -f "${FETCH_DIR}/svid.0.key" ] || [ ! -f "${FETCH_DIR}/bundle.0.pem" ]; then
        echo "[cert-writer:${SERVICE_NAME}] the fetch wrote no complete SVID set"
        rm -rf "${FETCH_DIR}"
        return 1
    fi
    FED_COUNT=0
    for FED_FILE in "${FETCH_DIR}"/federated_bundle.*.pem; do
        [ -f "${FED_FILE}" ] || continue
        cat "${FED_FILE}" >> "${FETCH_DIR}/bundle.0.pem"
        FED_COUNT=$((FED_COUNT + 1))
    done
    # set -e does not reach inside a function called as an `if` condition, so every copy states its own failure
    cp "${FETCH_DIR}/svid.0.pem" "${CERT_DIR}/svid.0.pem" \
        && cp "${FETCH_DIR}/svid.0.key" "${CERT_DIR}/svid.0.key" \
        && cp "${FETCH_DIR}/bundle.0.pem" "${CERT_DIR}/bundle.0.pem" \
        || { echo "[cert-writer:${SERVICE_NAME}] could not write the SVID set into ${CERT_DIR}"; rm -rf "${FETCH_DIR}"; return 1; }
    for FED_FILE in "${FETCH_DIR}"/federated_bundle.*.pem; do
        [ -f "${FED_FILE}" ] || continue
        cp "${FED_FILE}" "${CERT_DIR}/" \
            || { echo "[cert-writer:${SERVICE_NAME}] could not write $(basename "${FED_FILE}")"; rm -rf "${FETCH_DIR}"; return 1; }
    done
    STALE=0
    for FED_FILE in "${CERT_DIR}"/federated_bundle.*.pem; do
        [ -f "${FED_FILE}" ] || continue
        if [ ! -f "${FETCH_DIR}/$(basename "${FED_FILE}")" ]; then
            rm -f "${FED_FILE}"
            STALE=$((STALE + 1))
            echo "[cert-writer:${SERVICE_NAME}] removed $(basename "${FED_FILE}"): no federation of this entry produced it"
        fi
    done
    # Make key readable by non-root processes (registries, TEG layers)
    # §F5 (2026-09-26): with one identity per volume only ONE reader mounts the key, so it may be owned by that reader
    # and closed to everyone else. KEY_MODE (default 644, the shared-volume shape) and KEY_OWNER (uid[:gid], unset =
    # untouched) are opt-in: a writer started without them behaves exactly as before.
    chmod "${KEY_MODE:-644}" "${CERT_DIR}/svid.0.key" 2>/dev/null || true
    if [ -n "${KEY_OWNER:-}" ]; then
        chown "${KEY_OWNER}" "${CERT_DIR}/svid.0.key" 2>/dev/null \
            || echo "[cert-writer:${SERVICE_NAME}] WARNING: could not chown the key to ${KEY_OWNER}"
    fi
    rm -rf "${FETCH_DIR}"
    echo "[cert-writer:${SERVICE_NAME}] published: ${FED_COUNT} federated bundle(s) in the trust chain, ${STALE} stale removed"
    return 0
}

# Initial fetch with retries
echo "[cert-writer:${SERVICE_NAME}] Fetching initial SVID..."
RETRY=0
MAX_RETRIES=12
while [ ${RETRY} -lt ${MAX_RETRIES} ]; do
    if _fetch_and_publish; then
        echo "[cert-writer:${SERVICE_NAME}] Initial SVID fetched successfully"
        break
    fi
    RETRY=$((RETRY + 1))
    echo "[cert-writer:${SERVICE_NAME}] SVID fetch attempt ${RETRY}/${MAX_RETRIES} failed, retrying in 5s..."
    sleep 5
done

if [ ${RETRY} -ge ${MAX_RETRIES} ]; then
    echo "[cert-writer:${SERVICE_NAME}] ERROR: Failed to fetch SVID after ${MAX_RETRIES} attempts"
    exit 1
fi

# Verify cert files exist
if [ ! -f "${CERT_DIR}/svid.0.pem" ] || [ ! -f "${CERT_DIR}/svid.0.key" ] || [ ! -f "${CERT_DIR}/bundle.0.pem" ]; then
    echo "[cert-writer:${SERVICE_NAME}] ERROR: Expected cert files not found in ${CERT_DIR}"
    ls -la "${CERT_DIR}/"
    exit 1
fi

echo "[cert-writer:${SERVICE_NAME}] Certificate files verified:"
ls -la "${CERT_DIR}/"

# Log the SPIFFE ID from the cert
SPIFFE_ID=$(openssl x509 -in "${CERT_DIR}/svid.0.pem" -noout -ext subjectAltName 2>/dev/null | grep -o 'URI:spiffe://[^ ,]*' | sed 's/URI://' || echo "unknown")
echo "[cert-writer:${SERVICE_NAME}] SVID SPIFFE ID: ${SPIFFE_ID}"

# Create a ready marker file for nginx healthcheck
touch "${CERT_DIR}/.ready"
echo "[cert-writer:${SERVICE_NAME}] Ready marker created — nginx can start"

# Refresh loop
echo "[cert-writer:${SERVICE_NAME}] Entering refresh loop (every ${REFRESH_SEC}s)"
while true; do
    sleep "${REFRESH_SEC}"
    
    echo "[cert-writer:${SERVICE_NAME}] Refreshing SVID..."
    if _fetch_and_publish; then
        echo "[cert-writer:${SERVICE_NAME}] SVID refreshed at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    else
        echo "[cert-writer:${SERVICE_NAME}] WARNING: SVID refresh failed, keeping existing certs"
    fi
done
