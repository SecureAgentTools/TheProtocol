#!/bin/sh
set -e

CONFIG_DIR="/root/.theprotocol"
mkdir -p "$CONFIG_DIR"

# Source env files if they exist (docker-compose mounts them)
if [ -f /app/.env.secret ]; then . /app/.env.secret; fi
if [ -f /app/.env ]; then . /app/.env; fi

# Write credentials from env vars
cat > "$CONFIG_DIR/credentials.json" << CREDS
{"agent_did":"${PPAO_AGENT_DID}","client_id":"${PPAO_CLIENT_ID}","client_secret":"${PPAO_CLIENT_SECRET}","developer_email":"${PPAO_DEV_EMAIL}","developer_password":"${PPAO_DEV_PASSWORD}","developer_token":null,"agent_token":null}
CREDS
chmod 600 "$CONFIG_DIR/credentials.json"

# Write config
cat > "$CONFIG_DIR/config.toml" << CONF
[orchestrator]
registry_url = "${REGISTRY_URL:-https://api.theprotocol.cloud}"
registry_b_url = "${REGISTRY_B_URL:-https://registry-b.theprotocol.cloud}"
max_spend_per_task = ${MAX_SPEND_PER_TASK:-100.0}
max_spend_per_day = ${MAX_SPEND_PER_DAY:-500.0}
auto_approve_below = ${AUTO_APPROVE_BELOW:-10.0}
default_timeout = 60
use_docker_urls = ${USE_DOCKER_URLS:-false}
ai_provider = "none"
mcp_port = 3100
CONF
chmod 600 "$CONFIG_DIR/config.toml"

echo "[]" > "$CONFIG_DIR/history.json"

echo "[PPAO] Starting on port 3100..."
exec python3 -m uvicorn theprotocol_orchestrator.dashboard:create_dashboard_app --factory --host 0.0.0.0 --port 3100 --log-level info
