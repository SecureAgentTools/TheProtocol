#!/bin/bash
# generate-operator-env.sh — Generate unique .env for a new operator
#
# Usage: ./generate-operator-env.sh [operator-name]
#
# Writes .env.operator in the current directory (mode 0600) and says so on stderr; stdout stays empty. The generator a
# frame's operator bundle carries (nginx-templates/generate-operator-env.sh) has the same contract, so the two scripts
# that share this name behave alike (CB-006), and the older form `./generate-operator-env.sh <name> > .env.operator`
# still leaves the same file (nothing is written to the redirect).
set -e
umask 077

OPERATOR_NAME="${1:-my-registry}"

{
echo "# .env.operator — Generated $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "# Operator: $OPERATOR_NAME"
echo "# DO NOT COMMIT — contains secrets"
echo ""

echo "# ── Identity"
echo "REGISTRY_NAME=\"$OPERATOR_NAME\""
echo "OPERATOR_DID=did:theprotocol:operator-$(openssl rand -hex 8)"
echo "# The trust domain this registry signs its card with and issues its DIDs under (§DIDWIDEN): your real DNS name in"
echo "# production; the default keeps a standalone registry from claiming anyone else's."
echo "TRUST_DOMAIN=${OPERATOR_NAME}.local"
echo ""

echo "# ── Database passwords"
echo "PG_PASS_REGISTRY=$(openssl rand -hex 24)"
echo "PG_PASS_TEG=$(openssl rand -hex 24)"
echo "PG_PASS_EVENT_STORE=$(openssl rand -hex 24)"
echo ""

echo "# ── Security keys"
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "JWT_SECRET_KEY=$(openssl rand -hex 32)"

# API_KEY_SECRET and TEG_REGISTRY_JWT_SECRET must match
API_KEY_SECRET=$(openssl rand -hex 32)
echo "API_KEY_SECRET=$API_KEY_SECRET"
echo "TEG_REGISTRY_JWT_SECRET=$API_KEY_SECRET"

echo "TEG_ADMIN_API_KEY=$(openssl rand -hex 32)"
echo "TEG_AVTP_SYSTEM_API_KEY=$(openssl rand -hex 32)"
echo "TEG_TOKEN_SIGNING_KEY=$(openssl rand -hex 32)"
echo "EVENT_STORE_INTERNAL_API_KEY=$(openssl rand -hex 32)"
echo ""

# CB-015: neither was written, so setting BASE_URL as the kit's README says made the standalone registry refuse to start
echo "# ── Production checks: a BASE_URL that is not localhost turns the registry's production checks on, and it"
echo "# then refuses to start with CORS open to every origin or, as a standalone registry is its own frame, without a"
echo "# federation health-check secret. Both are set here. ALLOWED_ORIGINS is a JSON list (a bare URL or a comma list"
echo "# does not parse, \"*\" is refused): put your public https address in it when you set BASE_URL. The console is"
echo "# served from the registry itself, so it needs no entry."
echo 'ALLOWED_ORIGINS=["http://localhost:8000"]'
echo "FEDERATION_HEALTH_CHECK_SECRET=$(openssl rand -hex 32)"
echo ""

echo "# ── Token economy"
echo "TEG_ID=teg-layer  # must match MINTING_AUTHORITY for issuance to work"
echo "MINTING_AUTHORITY=teg-layer  # standalone mode. Set to 'disabled' for federated"
# CB-320: no DEFAULT_FEE_RATE / MAX_FEE_RATE. No service reads them: the transfer fee is the registry's enforcement
# policy (0.5 % base, at most 5 % under high velocity by default)
echo ""

echo "# ── Federation (leave empty for standalone)"
echo "FEDERATION_LICENSE_KEY="
echo "KAFKA_BOOTSTRAP_SERVERS="
echo "KAFKA_ENABLED=false"
echo "# How often this registry asks each federated peer for the agent cards that changed, in seconds. The production"
echo "# network runs 30 (measured 2026-10-07: a new agent reached five other registries within 28 s); unset, it is 600."
echo "FEDERATION_SYNC_INTERVAL_SECONDS=30"
echo ""

echo "# ── Email (CONFIGURE BEFORE DEPLOY)"
echo "MAIL_SERVER=smtp.example.com"
echo "MAIL_PORT=587"
echo "MAIL_USERNAME=noreply@example.com"
echo "MAIL_PASSWORD=CHANGE_ME"
echo "MAIL_FROM=noreply@example.com"
echo "MAIL_FROM_NAME=\"$OPERATOR_NAME\""
echo "MAIL_STARTTLS=True"
echo "MAIL_SSL_TLS=False"
echo ""

echo "# ── Monitoring"
echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 16)"
echo ""

echo "# ── Features"
echo "ENABLE_PROJECTION_SNAPSHOTS=true"
echo "GENESIS_GRANT_ENABLED=true"
echo "GENESIS_GRANT_AMOUNT=5000.0"
echo "BETA_INVITE_REQUIRED=false"
echo "AUDITED_BALANCE_ENABLED=true"
echo ""

echo "# ── Ledger bus (§SOVKIT K1 2026-09-14): the event store is the broker's ONLY client. Its SCRAM password at the"
echo "# broker (RP_BOOTSTRAP_USER on redpanda, KAFKA_SASL_PASSWORD on the store) and the key every record is signed with"
echo "# (ES_KAFKA_RECORD_KEY: the consumer takes a record only when this store signed it, ES_KAFKA_RECORD_AUTH=enforce)."
echo "KAFKA_ES_PASSWORD=$(openssl rand -hex 32)"
echo "ES_KAFKA_RECORD_KEY=$(openssl rand -hex 32)"
} > .env.operator.tmp
mv -f .env.operator.tmp .env.operator
echo "[generate] Created .env.operator for '${OPERATOR_NAME}' (0600)" >&2
