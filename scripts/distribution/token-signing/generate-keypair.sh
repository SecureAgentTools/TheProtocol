#!/bin/bash
# Generate RSA-2048 keypair for Docker Registry v2 token authentication.
# The private key signs JWTs issued by the token server.
# The certificate is mounted into the Docker Registry container for verification.
# Run once. Re-run to rotate (requires Docker Registry restart).
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "${DIR}/token-signing.key" ]; then
    echo "Keypair already exists in ${DIR}/. Delete first to regenerate."
    exit 1
fi

openssl genrsa -out "${DIR}/token-signing.key" 2048 2>/dev/null

openssl req -new -x509 -days 3650 \
    -key "${DIR}/token-signing.key" \
    -out "${DIR}/token-signing.crt" \
    -subj "/CN=TheProtocol Image Registry Token Auth/O=TheProtocol" \
    2>/dev/null

chmod 600 "${DIR}/token-signing.key"
chmod 644 "${DIR}/token-signing.crt"

echo "Token signing keypair generated:"
echo "  Private key: ${DIR}/token-signing.key"
echo "  Certificate: ${DIR}/token-signing.crt"
echo "  Validity:    10 years"
openssl x509 -in "${DIR}/token-signing.crt" -noout -fingerprint -sha256 2>/dev/null
