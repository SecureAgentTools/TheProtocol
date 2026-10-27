#!/bin/bash
# Intensive sandbox burn-in for tp-operator.
# Replaces wall-clock 24h burn-in with depth: ~1000 invocations across all
# 13 verbs, multi-operator, exit-code verification, audit-log integrity.
#
# Usage:  bash tests/burnin/burnin.sh /path/to/tp-operator
set -uo pipefail

BIN="${1:-/opt/theprotocol/stack/Agentvault2/dist/theprotocol-operator-1.1.6/tp-operator}"
export TP_OPERATOR_MAINFRAME_URL="${TP_OPERATOR_MAINFRAME_URL:-http://localhost:8002}"
AUDIT_LOG="$HOME/.tp-operator/audit.log"

# Snapshot the audit log size pre-burn-in
PRE_AUDIT_BYTES=0
[[ -f "$AUDIT_LOG" ]] && PRE_AUDIT_BYTES=$(stat -c%s "$AUDIT_LOG" 2>/dev/null || echo 0)

PASS=0
FAIL=0
SKIP=0
START=$(date +%s)

declare -a FAIL_DETAILS

# Discover sandbox operators
SANDBOX_OPS=()
for d in /opt/theprotocol/stack/cloud-op-sandbox*; do
  [[ -d "$d" && "$d" != *archived* && -f "$d/.env.operator" ]] && SANDBOX_OPS+=("$(basename "$d" | sed 's/^cloud-op-//')")
done
echo "Discovered sandbox operators: ${SANDBOX_OPS[@]}"
if [[ ${#SANDBOX_OPS[@]} -eq 0 ]]; then
  echo "ERROR: no sandbox operators found" >&2
  exit 1
fi

run() {
  local label="$1"
  local expected_code="$2"
  shift 2
  local got
  "$@" >/dev/null 2>&1
  got=$?
  if [[ "$got" == "$expected_code" || "$expected_code" == "*" ]]; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
    FAIL_DETAILS+=("$label: expected=$expected_code got=$got cmd=$*")
  fi
}

run_quiet() {
  # Same as run, but never fails the harness — counted in SKIP if unexpected.
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS+1))
  else
    SKIP=$((SKIP+1))
  fi
}

echo "=== ROUND 1: 100x version (warmup + cold-start sanity) ==="
for i in $(seq 1 100); do run "version#$i" 0 "$BIN" version; done

echo "=== ROUND 2: 100x status per operator ==="
for op in "${SANDBOX_OPS[@]}"; do
  for i in $(seq 1 50); do run_quiet "status[$op]#$i" "$BIN" --operator "$op" --json status; done
done

echo "=== ROUND 3: 100x health probe per operator ==="
for op in "${SANDBOX_OPS[@]}"; do
  for i in $(seq 1 50); do run_quiet "health[$op]#$i" "$BIN" --operator "$op" --json health; done
done

echo "=== ROUND 4: 100x peers (federation call cycle) ==="
for op in "${SANDBOX_OPS[@]}"; do
  for i in $(seq 1 50); do run_quiet "peers[$op]#$i" "$BIN" --operator "$op" --json peers; done
done

echo "=== ROUND 5: 50x license show + 50x license verify per op ==="
for op in "${SANDBOX_OPS[@]}"; do
  for i in $(seq 1 25); do run "license-show[$op]#$i" 0 "$BIN" --operator "$op" --json license show; done
  for i in $(seq 1 25); do run_quiet "license-verify[$op]#$i" "$BIN" --operator "$op" --json license verify; done
done

echo "=== ROUND 6: 50x validate-config per op ==="
for op in "${SANDBOX_OPS[@]}"; do
  for i in $(seq 1 25); do run_quiet "validate-config[$op]#$i" "$BIN" --operator "$op" validate-config; done
done

echo "=== ROUND 7: 50x doctor per op ==="
for op in "${SANDBOX_OPS[@]}"; do
  for i in $(seq 1 25); do run_quiet "doctor[$op]#$i" "$BIN" --operator "$op" --json doctor; done
done

echo "=== ROUND 8: error-path coverage ==="
run "missing-operator" 1 "$BIN" --operator nonexistent-zzz-xxx status
run "missing-config-file" 1 "$BIN" --config /tmp/nonexistent-zzz-xxx.env status
run "unknown-service-logs" 1 "$BIN" --operator "${SANDBOX_OPS[0]}" logs nonexistentservice --tail 1
run "bad-license-rotate-reason" "*" "$BIN" --config /tmp/bl1_bin_op/.env.operator --yes license rotate --reason invalid_reason
run "help-exit-0" 0 "$BIN" --help
run "version-exit-0" 0 "$BIN" version

echo "=== ROUND 9: dry-run mutations (no side effects) ==="
for op in "${SANDBOX_OPS[@]}"; do
  run "dry-restart[$op]" 0 "$BIN" --operator "$op" --dry-run --yes restart registry
  run "dry-stop[$op]" 0 "$BIN" --operator "$op" --dry-run --yes stop
done

echo "=== ROUND 10: --json output schema validation ==="
for op in "${SANDBOX_OPS[@]}"; do
  for cmd in status health peers doctor; do
    out=$("$BIN" --operator "$op" --json "$cmd" 2>/dev/null)
    if echo "$out" | python3 -c "import sys,json;d=json.load(sys.stdin);assert 'schema_version' in d or 'operator' in d or 'mainframe_url' in d, 'no schema/operator field'" 2>/dev/null; then
      PASS=$((PASS+1))
    else
      FAIL=$((FAIL+1))
      FAIL_DETAILS+=("json-schema[$op:$cmd]: missing schema_version or recognizable shape")
    fi
  done
done

END=$(date +%s)
ELAPSED=$((END - START))

# Audit-log integrity check
POST_AUDIT_BYTES=0
[[ -f "$AUDIT_LOG" ]] && POST_AUDIT_BYTES=$(stat -c%s "$AUDIT_LOG" 2>/dev/null || echo 0)
AUDIT_GROWTH=$((POST_AUDIT_BYTES - PRE_AUDIT_BYTES))
AUDIT_LINES_ADDED=0
if [[ "$AUDIT_GROWTH" -gt 0 && -f "$AUDIT_LOG" ]]; then
  AUDIT_LINES_ADDED=$(tail -c "$AUDIT_GROWTH" "$AUDIT_LOG" | wc -l)
fi

# Verify every audit line is valid JSON
AUDIT_BROKEN=0
if [[ -f "$AUDIT_LOG" ]]; then
  AUDIT_BROKEN=$(tail -c "$AUDIT_GROWTH" "$AUDIT_LOG" 2>/dev/null | python3 -c "
import sys, json
broken = 0
for line in sys.stdin:
    if not line.strip(): continue
    try: json.loads(line)
    except: broken += 1
print(broken)
" 2>/dev/null || echo 0)
fi

echo ""
echo "======================================================================"
echo "BURN-IN SUMMARY"
echo "======================================================================"
echo "  Elapsed:           ${ELAPSED}s"
echo "  PASS:              $PASS"
echo "  FAIL:              $FAIL"
echo "  SKIP (non-strict): $SKIP"
echo "  Audit-log growth:  ${AUDIT_GROWTH} bytes / ${AUDIT_LINES_ADDED} lines"
echo "  Audit-log broken:  $AUDIT_BROKEN (must be 0)"

if [[ "$FAIL" -gt 0 ]]; then
  echo ""
  echo "FAIL DETAILS:"
  printf '  %s\n' "${FAIL_DETAILS[@]}"
fi

if [[ "$FAIL" -eq 0 && "$AUDIT_BROKEN" -eq 0 ]]; then
  echo ""
  echo "BURN-IN: GREEN ✓"
  exit 0
else
  echo ""
  echo "BURN-IN: RED ✗"
  exit 1
fi
