#!/usr/bin/env bash
# START an ALREADY-PROVISIONED (stopped) Hetzner demo frame — §2026-07-29.
#
# WHY THIS EXISTS
# `standup_hetzner_frame.sh` builds a frame from nothing and takes ~20 min. That is too long to
# hold a sponsor call open. The frame from the rehearsal is already on disk with its own volumes,
# CA and signed card — it just is not running. Bringing THAT back up takes ~2 min, which is a
# thing you can do while people are joining the call.
#
# §FRAMEPROV P0 (2026-09-13): the stack dir is REQUIRED and is asked of frame_guard.sh, the same rule
# teardown_hetzner_frame.sh asks, so start/teardown can never disagree about which frame they mean.
#
# NOT a provisioner: it creates nothing and destroys nothing. If no stack dir exists it exits 3
# and tells you to run the standup instead — silently "succeeding" on a frame that does not exist
# is exactly the failure you would discover live.
#
# The child operator (op-demo) is deliberately NOT started: provisioning it from the frame's own
# Operator Management IS the live demo (Beat B).
#
# Usage: ./start_hetzner_frame.sh STACK_DIR     (required; a protected frame refuses unless FRAME_I_MEAN_IT=<name>)
set -uo pipefail

# shellcheck source=frame_guard.sh
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/frame_guard.sh"
FRAME_NAME="$(frame_guard start "${1:-}")" || exit 3
STACK_DIR="$(readlink -f "$1")"
META="$STACK_DIR/hetzner-demo-run.json"
NAME="$FRAME_NAME"
PROJ=$(basename "$STACK_DIR")
COMPOSE="$STACK_DIR/docker-compose.frame-test.yml"
ENVF="$STACK_DIR/.env.frame-test"
[ -f "$COMPOSE" ] || { echo "[start] missing $COMPOSE"; exit 3; }

echo "[start] frame=$NAME project=$PROJ dir=$STACK_DIR"
cd "$STACK_DIR" || exit 3

docker compose -f "$COMPOSE" --env-file "$ENVF" -p "$PROJ" up -d 2>&1 | tail -5

# ── wait for health ─────────────────────────────────────────────────────────────
# Two of the 13 services (nginx-federation, cert-writer) declare NO healthcheck, so gate on
# "nothing still starting" rather than "all 13 healthy" — the latter can never be true.
for i in $(seq 1 60); do
  STARTING=$(docker ps --filter "name=${NAME}-" --format '{{.Status}}' | grep -c "health: starting")
  UP=$(docker ps --filter "name=${NAME}-" --format '{{.Names}}' | wc -l)
  [ "$STARTING" = "0" ] && [ "$UP" -ge 13 ] && break
  sleep 5
done

REGPORT=$(docker port "${NAME}-registry" 8000/tcp 2>/dev/null | head -1 | sed 's/.*://')
ESPORT=$(docker port "${NAME}-event-store" 2>/dev/null | head -1 | sed 's/.*://')

HEALTH=000
for i in $(seq 1 40); do
  HEALTH=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://localhost:${REGPORT}/health" 2>/dev/null)
  [ "$HEALTH" = "200" ] && break
  sleep 5
done

# ── verify by ARTIFACT, not exit status (§21 — the whole lesson of this project) ──
CARD=$(curl -s --max-time 15 "http://localhost:${REGPORT}/.well-known/registry-card.json" 2>/dev/null \
       | python3 -c "import sys,json;d=json.load(sys.stdin);i=d.get('identity') or {};print(i.get('registry_name') or '?')" 2>/dev/null || echo "?")
DELTA=$(curl -s --max-time 15 "http://localhost:${ESPORT}/api/v1/projections/supply-audit" 2>/dev/null \
       | python3 -c "import sys,json;d=json.load(sys.stdin);print('%s/%s'%(d.get('delta'),d.get('status')))" 2>/dev/null || echo "?")
UPN=$(docker ps --filter "name=${NAME}-" --format '{{.Names}}' | wc -l)
UNHEALTHY=$(docker ps --filter "name=${NAME}-" --format '{{.Status}}' | grep -c unhealthy)

echo "[start] containers_up=$UPN/13 unhealthy=$UNHEALTHY health=$HEALTH card='$CARD' supply_delta/status=$DELTA"
echo "[start] registry  http://localhost:${REGPORT}   (public: https://hetzner.theprotocol.cloud)"
echo "[start] eventstore http://localhost:${ESPORT}"

if [ "$UPN" -ge 13 ] && [ "$HEALTH" = "200" ] && [ "$CARD" != "?" ] && [ "${DELTA%%/*}" = "0.0" ]; then
  echo "HETZNER_FRAME_STARTED ok=1 $(date -u)"
  exit 0
fi
echo "HETZNER_FRAME_STARTED ok=0 $(date -u)  — inspect: docker compose -p $PROJ ps"
exit 1
