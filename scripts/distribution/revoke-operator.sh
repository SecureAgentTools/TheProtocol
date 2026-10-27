#!/bin/bash
# revoke-operator.sh — Revoke an operator's SPIRE identity and federation access
# Usage: ./revoke-operator.sh <operator-name>
# Run on mainframe only. Two-layer revocation: SPIRE + federation license.
set -e

OPERATOR_NAME="$1"
SPIRE_SERVER="agentvault-spire-server"
SPIRE_BIN="/opt/spire/bin/spire-server"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$OPERATOR_NAME" ]; then
    echo "Usage: $0 <operator-name>"
    exit 1
fi

echo ""
echo "================================================================"
echo "  REVOKING OPERATOR: ${OPERATOR_NAME}"
echo "================================================================"
echo ""

# Step 1: Look up fingerprint from registry
FINGERPRINT=$(grep "^${OPERATOR_NAME}|" "${SCRIPT_DIR}/operator-registry.log" 2>/dev/null | tail -1 | cut -d'|' -f2)
if [ -z "$FINGERPRINT" ]; then
    echo "WARNING: Operator not found in operator-registry.log"
    echo "Searching SPIRE server for matching entries..."
    docker exec "$SPIRE_SERVER" "$SPIRE_BIN" entry show 2>&1 | grep -B2 "${OPERATOR_NAME}"
    echo ""
    echo "Provide fingerprint manually or check the log."
    exit 1
fi

AGENT_SPIFFE="spiffe://agentvault.com/spire/agent/x509pop/${FINGERPRINT}"
echo "Agent SPIFFE ID: ${AGENT_SPIFFE}"

# Step 2: Ban the SPIRE agent (prevents re-attestation)
echo ""
echo "--- Step 1: Ban SPIRE agent ---"
docker exec "$SPIRE_SERVER" "$SPIRE_BIN" agent ban -spiffeID "$AGENT_SPIFFE" 2>&1 && \
    echo "  Agent banned" || echo "  WARNING: Agent ban failed (may already be banned)"

# Step 3: Delete all workload entries for this operator
echo ""
echo "--- Step 2: Delete workload entries ---"
ENTRY_IDS=$(docker exec "$SPIRE_SERVER" "$SPIRE_BIN" entry show 2>&1 | \
    grep -B5 "${OPERATOR_NAME}" | grep "Entry ID" | awk '{print $NF}')
DELETED=0
for eid in $ENTRY_IDS; do
    docker exec "$SPIRE_SERVER" "$SPIRE_BIN" entry delete -entryID "$eid" > /dev/null 2>&1
    DELETED=$((DELETED + 1))
done
echo "  Deleted ${DELETED} entries"

# Step 4: Evict the agent node
echo ""
echo "--- Step 3: Evict agent node ---"
docker exec "$SPIRE_SERVER" "$SPIRE_BIN" agent evict -spiffeID "$AGENT_SPIFFE" 2>&1 && \
    echo "  Agent evicted" || echo "  WARNING: Agent evict failed"

echo ""
echo "================================================================"
echo "  REVOCATION COMPLETE: ${OPERATOR_NAME}"
echo ""
echo "  Immediate effects:"
echo "    - Agent cannot re-attest (banned)"
echo "    - No new SVIDs will be issued"
echo "    - Existing SVIDs expire within 4 hours (default_x509_svid_ttl)"
echo ""
echo "  Remaining manual steps:"
echo "    1. Revoke federation license via admin API"
echo "    2. Remove PARTNER_TEGS entry if cross-TEG was configured"
echo "    3. Purge operator's agent cards from peer registries"
echo "================================================================"
