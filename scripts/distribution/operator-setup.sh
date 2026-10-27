#!/bin/bash
# operator-setup.sh — One-command TheProtocol operator setup
# Usage: ./operator-setup.sh [operator-name] [mode: federated|standalone]
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

NAME="${1:-my-registry}"
MODE="${2:-standalone}"

echo "============================================"
echo "  TheProtocol Operator Setup"
echo "  Operator: ${NAME}"
echo "  Mode:     ${MODE}"
echo "============================================"
echo ""

# Validate mode
if [[ "$MODE" != "federated" && "$MODE" != "standalone" ]]; then
    echo "ERROR: Mode must be 'federated' or 'standalone'"
    echo "Usage: ./operator-setup.sh [operator-name] [mode]"
    exit 1
fi

# Check dependencies
for cmd in docker openssl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' is required but not installed."
        exit 1
    fi
done

if ! docker compose version &>/dev/null; then
    echo "ERROR: 'docker compose' (v2) is required."
    echo "       Install: https://docs.docker.com/compose/install/"
    exit 1
fi

# A federated operator's stack is not a file of this kit: it is the bundle its frame provisions (the frame's SPIRE
# material, the compose, the env generator, the mTLS terminators' confs). The docker-compose.operator.yml this mode
# used was an older copy of that compose and is retired (CB-112, CB-227): no nginx-teg, and a federation sidecar that
# sent no proxy marker, so its registry authenticated no peer.
if [ "$MODE" == "federated" ]; then
    echo "FEDERATED MODE: a federated operator runs the bundle its frame provisions, not a file of this kit."
    echo "  1. Apply on the frame you want to join (its console's operator application form)."
    echo "  2. When its admin approves, activate with the code you are mailed: POST /api/v1/operators/activate."
    echo "  3. The frame hosts your stack, or you download the bundle (GET /api/v1/operators/my-bundle), run"
    echo "     ./generate-operator-env.sh <name> in its directory and start its docker-compose.operator.yml."
    exit 1
fi

# Generate secrets
if [ -f .env.operator ]; then
    echo "WARNING: .env.operator already exists."
    read -p "Overwrite? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Keeping existing .env.operator"
    else
        ./generate-operator-env.sh "$NAME"
        echo "Generated new .env.operator"
    fi
else
    ./generate-operator-env.sh "$NAME"
    echo "Generated .env.operator"
fi

COMPOSE="docker-compose.standalone.yml"
echo ""
echo "STANDALONE MODE:"
echo "  Local EventStore included: fully self-contained."
echo "  Issuance is enabled: your TEG can issue units."
echo "  No federation dependency."

echo ""
echo "Using: $COMPOSE"
echo ""
echo "============================================"
echo "  NEXT STEPS"
echo "============================================"
echo ""
echo "  1. Edit .env.operator"
echo "     - Configure email settings (MAIL_* variables)"
echo "     - Set TRUST_DOMAIN to your DNS name (the generated ${NAME}.local suits a local trial only)"
echo "     - Add REGISTRY_HTTP_PORT=<port> if port 8000 is taken on this host"
echo ""
echo "  2. Build the images from this repository (a local build; nothing is pulled):"
echo "     ./build.sh"
echo ""
echo "  3. Start the stack:"
echo "     docker compose -f $COMPOSE --env-file .env.operator up -d"
echo ""
echo "  4. Wait ~2 minutes for database migrations and startup"
echo ""
echo "  5. Check health:"
echo "     docker compose -f $COMPOSE --env-file .env.operator ps"
echo ""
echo "  6. Open http://localhost:8000. The first admin's password is printed once in the registry's logs:"
echo "     docker logs ${NAME}-registry 2>&1 | grep -A3 \"FIRST-BOOT ADMIN PASSWORD\""
echo ""
echo "  7. As that admin, issue the initial supply (a standalone treasury starts empty):"
echo "     POST /api/v1/teg/treasury/mint  {\"amount\": \"1000000\", \"reason\": \"initial supply\"}"
echo "     No SMTP yet? Verify a registrant from the admin rail:"
echo "     POST /api/v1/admin/developers/{id}/force-email-verify"
echo ""
echo "  Optional: add monitoring:"
echo "     docker compose -f $COMPOSE -f docker-compose.monitoring.yml --env-file .env.operator up -d"
echo ""
