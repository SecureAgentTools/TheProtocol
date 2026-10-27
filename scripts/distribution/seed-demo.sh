#!/bin/bash
# seed-demo.sh — populate a fresh TheProtocol registry with demo agents so a new
# operator's install feels alive on first boot. Pure public-API; no DB access.
#
# Usage:
#   REGISTRY_URL=http://localhost:8000 ADMIN_EMAIL=admin@... ADMIN_PASSWORD=... \
#     ./seed-demo.sh                 # create demo agents (default 3)
#   ... ./seed-demo.sh --cleanup     # delete the demo agents this script created
#
# Env:
#   REGISTRY_URL     (default http://localhost:8000)
#   ADMIN_EMAIL      (required)   — a developer/admin account on the registry
#   ADMIN_PASSWORD   (required)
#   DEMO_COUNT       (default 3)
#   DEMO_PREFIX      (default "demo") — agent name prefix + tracking tag
#   DEMO_FUND        (default 100)  — AVT/BVT/JDAY funded to each agent (admin only)
set -euo pipefail

REGISTRY_URL="${REGISTRY_URL:-http://localhost:8000}"
API="${REGISTRY_URL%/}/api/v1"
DEMO_COUNT="${DEMO_COUNT:-3}"
DEMO_PREFIX="${DEMO_PREFIX:-demo}"
DEMO_FUND="${DEMO_FUND:-100}"
STATE_FILE="${DEMO_STATE_FILE:-/tmp/theprotocol-seed-demo-${DEMO_PREFIX}.json}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required." >&2; exit 1; }; }
need curl; need jq

: "${ADMIN_EMAIL:?set ADMIN_EMAIL}"; : "${ADMIN_PASSWORD:?set ADMIN_PASSWORD}"

login() {
  # /auth/login is FORM-ENCODED (username=&password=), returns a developer JWT.
  local resp
  resp="$(curl -fsS -X POST "$API/auth/login" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "username=$ADMIN_EMAIL" \
    --data-urlencode "password=$ADMIN_PASSWORD")" || { echo "login failed" >&2; exit 1; }
  echo "$resp" | jq -r '.access_token // .partial_token // empty'
}

DEV_JWT="$(login)"
[ -n "$DEV_JWT" ] || { echo "ERROR: no token (2FA-enabled account? use a non-2FA seed account)." >&2; exit 1; }
AUTH=(-H "Authorization: Bearer $DEV_JWT")

if [ "${1:-}" = "--cleanup" ]; then
  [ -f "$STATE_FILE" ] || { echo "No state file ($STATE_FILE) — nothing to clean up."; exit 0; }
  echo "Cleaning up demo agents from $STATE_FILE ..."
  jq -r '.agents[].did' "$STATE_FILE" | while read -r did; do
    curl -fsS -X DELETE "$API/agents/by-did/$did" "${AUTH[@]}" >/dev/null 2>&1 \
      && echo "  deleted $did" || echo "  (skip) $did"
  done
  rm -f "$STATE_FILE"
  echo "Cleanup done."
  exit 0
fi

echo "Seeding $DEMO_COUNT demo agent(s) on $REGISTRY_URL ..."
echo "{\"prefix\":\"$DEMO_PREFIX\",\"agents\":[]}" > "$STATE_FILE"

for i in $(seq 1 "$DEMO_COUNT"); do
  name="${DEMO_PREFIX}-agent-$i"

  # 1) Bootstrap token (dev JWT → short-lived Bootstrap-Token header).
  btok="$(curl -fsS -X POST "$API/onboard/bootstrap/request-token" "${AUTH[@]}" \
    -H 'Content-Type: application/json' -d '{}' | jq -r '.bootstrap_token // .token // empty')"
  [ -n "$btok" ] || { echo "  bootstrap failed for $name" >&2; continue; }

  # 2) Create agent (Option C: agent_host stub card).
  created="$(curl -fsS -X POST "$API/onboard/create_agent" \
    -H "Bootstrap-Token: $btok" -H 'Content-Type: application/json' \
    -d "{\"agent_did_method\":\"theprotocol\",\"agent_host\":\"https://example.invalid/$name\"}")"
  did="$(echo "$created" | jq -r '.agent_did // .did // empty')"
  [ -n "$did" ] || { echo "  create_agent failed for $name: $(echo "$created" | jq -c . 2>/dev/null || echo "$created")" >&2; continue; }
  echo "  created $name → $did"

  # 3) Fund from treasury (admin only; ignored/echoed if the seed account isn't admin).
  fund="$(curl -fsS -X POST "$API/teg/treasury/fund-agent" "${AUTH[@]}" \
    -H 'Content-Type: application/json' \
    -d "{\"agent_did\":\"$did\",\"amount\":\"$DEMO_FUND\"}" 2>/dev/null || echo '{}')"
  echo "$fund" | jq -e '.transaction_id // .status' >/dev/null 2>&1 \
    && echo "    funded $DEMO_FUND" || echo "    (fund skipped — needs admin)"

  # Track for --cleanup.
  tmp="$(jq --arg d "$did" --arg n "$name" '.agents += [{"did":$d,"name":$n}]' "$STATE_FILE")"
  echo "$tmp" > "$STATE_FILE"
done

echo ""
echo "Supply invariant check:"
curl -fsS "$API/public/badge/supply" 2>/dev/null | jq -r '"  " + .label + ": " + .message' \
  || echo "  (badge endpoint unavailable on this build)"
echo ""
echo "Done. $DEMO_COUNT agent(s) seeded (prefix '$DEMO_PREFIX'). State: $STATE_FILE"
echo "Remove them later with:  ./seed-demo.sh --cleanup"
