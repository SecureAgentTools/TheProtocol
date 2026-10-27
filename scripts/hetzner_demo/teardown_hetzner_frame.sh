#!/usr/bin/env bash
# Hetzner Frame live-demo TEARDOWN — removes the demo frame + its chained op,
# disables the demo vhosts, and honors the "we take it down afterwards" promise
# (containers, volumes, network, stack dir, any showcase operator data).
# Usage: teardown_hetzner_frame.sh /opt/theprotocol/stack/<name>-<ts>
#        §FRAMEPROV P0 (2026-09-13): the stack dir is REQUIRED. The old no-argument default (the newest
#        hetzner-frame-* dir) is what the admin UI's target-less Tear down would have removed: the retired Hetzner
#        stack. frame_guard.sh also refuses a dir without a run meta name, and a protected frame.
set -euo pipefail
# shellcheck source=frame_guard.sh
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/frame_guard.sh"
FRAME_NAME="$(frame_guard teardown "${1:-}")" || exit 2
STACK_DIR="$(readlink -f "$1")"
[ -n "$STACK_DIR" ] && [ -d "$STACK_DIR" ] || { echo "[teardown] no stack dir at $1"; exit 2; }
META="$STACK_DIR/hetzner-demo-run.json"
NAME="$FRAME_NAME"
TS=$(python3 -c "import json;print(json.load(open('$META'))['ts'])" 2>/dev/null || basename "$STACK_DIR" | sed 's/.*-//')
# Trust domain of THIS demo frame — the guard that keeps the 13 production
# operators (which live in the same directory tree) untouchable. Defaulting to a
# sentinel rather than a real domain means a missing/corrupt meta skips every
# operator instead of matching one.
TRUST_DOMAIN=$(python3 -c "import json;print(json.load(open('$META'))['trust_domain'])" 2>/dev/null || echo "__no_trust_domain__")
IDENTITY_NET=$(grep -E "^(FT_REG_IDENTITY_NETWORK|IDENTITY_NETWORK)=" "$STACK_DIR/.env.frame-test" 2>/dev/null | head -1 | cut -d= -f2)
echo "[teardown] frame=$NAME ts=$TS dir=$STACK_DIR"

# 0) §ONESHOT P2.2 (2026-09-12) — the frame's slot in every SIDECAR FIRST, before its operators and containers go
#     (the auditor's compose names the frame's network as external: removing it after the network is
#     gone leaves the auditor unable to recreate; and Prometheus sits on every operator net, which
#     `compose down` cannot remove while it is attached — measured: cloud-op-juiceop_operator-net left behind). Only this frame's slots: its Prometheus jobs, its
#     auditor entry + network, its SNI line, its apex ledger socket, its FRESH_NETWORK_JSON tile, its
#     bundle under the refresh (+ its identity net's federated file when no frame is left on that net),
#     its five vhosts, its docker networks. NO_UNWIRE=1 skips it (a host without the manifest logs and goes on).
if [ "${NO_UNWIRE:-0}" != "1" ] && [ -f "$META" ]; then
  python3 /opt/theprotocol/stack/Agentvault2/scripts/hetzner_demo/sidecars.py unwire "$STACK_DIR" \
    || echo "[teardown] unwire did not complete (see above) — continuing with the frame itself"
fi

# 1) Chained showcase operator first (created by Beat B, if any) — its SPIRE
#    entries live on the frame's own spire-server and die with it below.
#    The slug is read from the run meta, NEVER discovered by globbing
#    `cloud-op-op-*`: that pattern also matches the 13 PRODUCTION operators
#    (op-berlin, op-london, op-doha …) and would tear the fleet down.
OP_SLUG=$(python3 -c "import json;print(json.load(open('$META')).get('operator_slug',''))" 2>/dev/null || true)
OP_DIRS=""
[ -n "$OP_SLUG" ] && OP_DIRS="/opt/theprotocol/stack/cloud-op-$OP_SLUG"
# legacy demo slugs from earlier rehearsals (explicit, never a wildcard over op-*)
for LEGACY in op-micha op-demo; do
  [ "$LEGACY" = "$OP_SLUG" ] && continue
  [ -d "/opt/theprotocol/stack/cloud-op-$LEGACY" ] && OP_DIRS="$OP_DIRS /opt/theprotocol/stack/cloud-op-$LEGACY"
done
# §ONESHOT (2026-09-12) — an operator PROVISIONED but never RECORDED (the driver refused between the
# provision and the meta write: the operator gate, a card failure) is otherwise orphaned by this teardown.
# Every operator dir is considered and selected by the SAME trust-domain guard the named slug passes
# below: a child's agent.conf carries the frame's trust domain, a production operator's never does.
# The sentinel default keeps a corrupt meta from matching anything.
if [ "$TRUST_DOMAIN" != "__no_trust_domain__" ]; then
  for D_ in /opt/theprotocol/stack/cloud-op-*/; do
    D_=${D_%/}; [ -d "$D_" ] || continue
    case "$D_" in *-archived-*) continue ;; esac      # an archived dir is kept on purpose (measured: six of them matched)
    case " $OP_DIRS " in *" $D_ "*) continue ;; esac
    grep -q "trust_domain *= *\"$TRUST_DOMAIN\"" "$D_/spire/agent.conf" 2>/dev/null && { OP_DIRS="$OP_DIRS $D_"; echo "[teardown] operator discovered by trust domain: $D_"; }
  done
fi
for OP_DIR in $OP_DIRS; do
  [ -d "$OP_DIR" ] || continue
  OP=$(basename "$OP_DIR" | sed 's/^cloud-op-//')
  # HARD GUARD — only ever remove an operator that belongs to THIS demo frame.
  # A child op's agent.conf carries the trust domain of the frame that provisioned
  # it, so a production op (agentvault.com / frame-b / frame-c) can never match
  # hetzner.theprotocol.cloud. This makes a bad slug in the run meta inert instead
  # of catastrophic: the 13 production operators live in the same directory tree.
  if ! grep -q "trust_domain *= *\"$TRUST_DOMAIN\"" "$OP_DIR/spire/agent.conf" 2>/dev/null; then
    echo "[teardown] SKIP $OP — not a child of $TRUST_DOMAIN (refusing to touch it)"
    continue
  fi
  echo "[teardown] removing showcase operator: $OP_DIR"
  (cd "$OP_DIR" && docker compose -f docker-compose.operator.yml --env-file .env.operator down -v --remove-orphans) || true
  # §ONESHOT (2026-09-12): `compose down` ABORTS on the first container the daemon cannot stop ("tried to
  # kill container, but did not receive an exit event" — measured on cloud-op-juiceop-nginx-teg) and leaves
  # the rest running; `|| true` hid it and `rm -rf` then took the compose file away from the survivors.
  # Force-remove whatever is left, anchored on the exact slug, BEFORE the dir goes.
  docker ps -a --format '{{.Names}}' | grep -E "^cloud-op-${OP}-" | xargs -r docker rm -f >/dev/null 2>&1 || true
  # and the operator's own network, which an aborted `compose down` never reaches (exact name, measured twice:
  # the operator's nginx-teg is the container the daemon fails to stop cleanly every time)
  docker network rm "cloud-op-${OP}_operator-net" >/dev/null 2>&1 || true
  rm -rf "$OP_DIR"
  # Belt-and-braces volume purge. `down -v` only removes volumes DECLARED in the
  # compose file it was handed, and it is skipped entirely if that dir/compose is
  # already gone. A surviving volume is NOT cosmetic — the next operator that takes
  # the same slug inherits it and fails in two ways we hit live:
  #   spire-agent-data → verifies the NEW frame's SVID against the OLD frame's CA
  #                      ("x509: certificate signed by unknown authority"), crash-loops,
  #                      so cert-writer never starts and the registry stays `Created`
  #   teg-data/registry-data → Postgres keeps the OLD password (POSTGRES_PASSWORD only
  #                      applies to an EMPTY data dir) → "password authentication
  #                      failed for user teg"
  # Anchored on the exact slug (plus a -N re-provision suffix); never a bare op-* glob.
  docker volume ls --format '{{.Name}}' \
    | grep -E "^cloud-op-${OP}(-[0-9]+)?_" \
    | xargs -r docker volume rm >/dev/null 2>&1 || true
  rm -f "/etc/nginx/sites-enabled/cloud-op-$OP" "/etc/nginx/sites-available/cloud-op-$OP"
  # stream SNI map lines for this op (best-effort, anchored on the op name)
  if [ -f /etc/nginx/stream.d/federation-mtls.conf ]; then
    sed -i "/$OP\./d" /etc/nginx/stream.d/federation-mtls.conf || true
  fi
done

# 2) The frame itself, via the provisioner module's own teardown
# venv python: host docker-py 5.0.3 is incompatible with requests>=2.32.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/.venv/bin/python"; [ -x "$PY" ] || PY=python3
# §BATCH5 (2026-09-05): frame_test_provisioner imports `agentvault_registry.core…` — loading it by file path needs the
# source tree on sys.path or the teardown dies AFTER its guard and BEFORE removing anything (measured on the JUICE frame:
# 15 containers + 8 volumes left behind, exit 0 reported by the wrapper). The standup wrapper had the same need.
export PYTHONPATH="/opt/theprotocol/stack/Agentvault2/AgentVault/agentvault_registry/src${PYTHONPATH:+:$PYTHONPATH}"
"$PY" - "$NAME" "$TS" "$STACK_DIR" <<'PY'
import importlib.util, sys, os
name, ts, stack = sys.argv[1], int(sys.argv[2]), sys.argv[3]
os.environ.setdefault("FRAME_TEST_TEMPLATE_DIR",
    "/opt/theprotocol/stack/Agentvault2/templates/frame-test")
p = "/opt/theprotocol/stack/Agentvault2/AgentVault/agentvault_registry/src/agentvault_registry/services/frame_test_provisioner.py"
spec = importlib.util.spec_from_file_location("ftp", p)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ctx = m.FrameTestContext(ts=ts, registry_name=name)
ctx.stack_dir_host = stack; ctx.stack_dir_container = stack
r = m.teardown_frame_test(ctx)
print(f"[teardown] containers={r.containers_removed} volumes={r.volumes_removed} "
      f"networks={r.networks_removed} stack_dir_removed={r.stack_dir_removed}")
PY

# 2b) §ONESHOT — the identity net's opt-in line goes only once the net is EMPTY, which is only true after step 2
if [ "${NO_UNWIRE:-0}" != "1" ] && [ -n "${IDENTITY_NET:-}" ]; then
  python3 /opt/theprotocol/stack/Agentvault2/scripts/hetzner_demo/sidecars.py unwire-net "$IDENTITY_NET" || true
fi

# 3) Demo vhosts off — the retired hetzner names (a frame's own five are removed by the unwire above)
for V in hetzner-frame hetzner-es hetzner-spire; do rm -f "/etc/nginx/sites-enabled/$V"; done
nginx -t && systemctl reload nginx && echo "[teardown] vhosts disabled, nginx reloaded"
echo "[teardown] DONE — takedown promise honored"
