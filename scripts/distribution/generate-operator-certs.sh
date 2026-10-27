#!/bin/bash
# generate-operator-certs.sh — Generate x509pop attestation cert for a new operator
# Usage: ./generate-operator-certs.sh <operator-name> <output-dir>
# Run on mainframe only. Requires attestation-ca.key.
set -e

OPERATOR_NAME="$1"
OUTPUT_DIR="$2"
CA_DIR="/opt/theprotocol/stack/Agentvault2/identity-fabric/x509pop-certs"
VALIDITY_DAYS=730  # 2 years

if [ -z "$OPERATOR_NAME" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "Usage: $0 <operator-name> <output-dir>"
    exit 1
fi

if [ ! -f "$CA_DIR/attestation-ca.key" ]; then
    echo "ERROR: Attestation CA key not found at $CA_DIR/attestation-ca.key"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "[1/4] Generating operator agent key (RSA-2048)..."
openssl genrsa -out "${OUTPUT_DIR}/agent-attestation.key" 2048 2>/dev/null
chmod 600 "${OUTPUT_DIR}/agent-attestation.key"

echo "[2/4] Generating CSR..."
openssl req -new \
    -key "${OUTPUT_DIR}/agent-attestation.key" \
    -out "${OUTPUT_DIR}/agent.csr" \
    -subj "/C=DE/ST=Bavaria/L=Freilassing/O=TheProtocol/OU=Federation/CN=spire-agent-${OPERATOR_NAME}" 2>/dev/null

echo "[3/4] Signing with attestation CA (${VALIDITY_DAYS} days)..."
openssl x509 -req \
    -in "${OUTPUT_DIR}/agent.csr" \
    -CA "${CA_DIR}/attestation-ca.crt" \
    -CAkey "${CA_DIR}/attestation-ca.key" \
    -CAcreateserial \
    -out "${OUTPUT_DIR}/agent-attestation.crt" \
    -days ${VALIDITY_DAYS} \
    -sha256 \
    -extfile <(printf "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer") 2>/dev/null

rm -f "${OUTPUT_DIR}/agent.csr" "${CA_DIR}/attestation-ca.srl"

echo "[4/4] Verifying..."
openssl verify -CAfile "${CA_DIR}/attestation-ca.crt" "${OUTPUT_DIR}/agent-attestation.crt" 2>&1

FINGERPRINT=$(openssl x509 -in "${OUTPUT_DIR}/agent-attestation.crt" -noout -fingerprint -sha1 | sed 's/://g' | awk -F= '{print tolower($2)}')
EXPIRY=$(openssl x509 -in "${OUTPUT_DIR}/agent-attestation.crt" -noout -enddate | cut -d= -f2)

echo ""
echo "  Operator:    ${OPERATOR_NAME}"
echo "  Fingerprint: ${FINGERPRINT}"
echo "  SPIFFE ID:   spiffe://agentvault.com/spire/agent/x509pop/${FINGERPRINT}"
echo "  Expires:     ${EXPIRY}"
echo "  Files:       ${OUTPUT_DIR}/agent-attestation.{crt,key}"
