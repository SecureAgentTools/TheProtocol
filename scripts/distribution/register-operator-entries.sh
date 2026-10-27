#!/bin/bash
# register-operator-entries.sh — Register SPIRE workload entries for an operator
# Usage: ./register-operator-entries.sh <operator-name> <cert-file>
# Run on mainframe only.
set -e

OPERATOR_NAME="$1"
CERT_FILE="$2"
SPIRE_SERVER="agentvault-spire-server"
SPIRE_BIN="/opt/spire/bin/spire-server"

if [ -z "$OPERATOR_NAME" ] || [ -z "$CERT_FILE" ]; then
    echo "Usage: $0 <operator-name> <cert-file>"
    exit 1
fi

if [ ! -f "$CERT_FILE" ]; then
    echo "ERROR: Certificate file not found: $CERT_FILE"
    exit 1
fi

# Calculate fingerprint → SPIFFE ID
FINGERPRINT=$(openssl x509 -in "$CERT_FILE" -noout -fingerprint -sha1 | sed 's/://g' | awk -F= '{print tolower($2)}')
PARENT_ID="spiffe://agentvault.com/spire/agent/x509pop/${FINGERPRINT}"

echo "Operator:  ${OPERATOR_NAME}"
echo "Parent ID: ${PARENT_ID}"
echo ""

echo "[1/3] Registering operator registry entry..."
docker exec "$SPIRE_SERVER" "$SPIRE_BIN" entry create \
    -parentID "$PARENT_ID" \
    -spiffeID "spiffe://agentvault.com/service/registry-${OPERATOR_NAME}" \
    -selector "docker:label:com.agentvault.service:registry" \
    -x509SVIDTTL 14400 > /dev/null 2>&1 && echo "  Registry: OK" || echo "  Registry: WARN"

echo "[2/3] Registering operator SVID writer entry..."
docker exec "$SPIRE_SERVER" "$SPIRE_BIN" entry create \
    -parentID "$PARENT_ID" \
    -spiffeID "spiffe://agentvault.com/service/registry-${OPERATOR_NAME}" \
    -selector "docker:label:com.agentvault.service:svid-writer-operator" \
    -dns "nginx-federation" \
    -x509SVIDTTL 14400 > /dev/null 2>&1 && echo "  SVID Writer: OK" || echo "  SVID Writer: WARN"

echo "[3/3] Registering operator TEG entry..."
docker exec "$SPIRE_SERVER" "$SPIRE_BIN" entry create \
    -parentID "$PARENT_ID" \
    -spiffeID "spiffe://agentvault.com/service/teg-${OPERATOR_NAME}" \
    -selector "docker:label:com.agentvault.service:teg-layer" \
    -x509SVIDTTL 14400 > /dev/null 2>&1 && echo "  TEG: OK" || echo "  TEG: WARN"

echo ""
echo "Entries registered. Verify:"
echo "  docker exec $SPIRE_SERVER $SPIRE_BIN entry show | grep ${OPERATOR_NAME}"
