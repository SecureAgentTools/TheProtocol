#!/usr/bin/env bash
# ============================================================================
# apply_frame_mail.sh — give a HANDED-OVER frame a real outbound mail relay,
# then (and only then) re-enable email verification.
#
# Strategy + rationale: PRODUCTION_DOCS/08_SECURITY/Frame_Outbound_Mail_And_Push.md
#
# WHY THIS IS A SCRIPT AND NOT A COMPOSE EDIT
#   §OPGUIDE-2 proved the failure mode: REQUIRE_EMAIL_VERIFICATION=true with an
#   unreachable relay locks EVERY self-registered account out permanently, and
#   the only remedy is an admin endpoint that exists in no frontend. So the
#   order is load-bearing: configure relay -> PROVE a real send -> only then
#   require verification. This script refuses to do them out of order.
#
# THE TOKEN IS NEVER WRITTEN INTO THE COMPOSE FILE. It goes into
# .env.frame-test (chmod 600), which is not copied into any image and has no
# scattered .bak siblings the way the compose file does.
#
# Usage:
#   ./apply_frame_mail.sh --token '<proton smtp token>' \
#                         --address noreply@frames.theprotocol.cloud \
#                         --test-recipient you@example.com \
#                         [--server smtp.protonmail.ch] [--port 587] \
#                         [--from-name 'TheProtocol Frame (Hetzner)'] \
#                         [--stack /opt/theprotocol/stack/hetzner-frame-1785128860] \
#                         [--service hetzner-frame-registry] [--no-verify-flip]
# ============================================================================
set -euo pipefail

STACK="/opt/theprotocol/stack/hetzner-frame-1785128860"
SERVICE="hetzner-frame-registry"
COMPOSE="docker-compose.frame-test.yml"
SERVER="smtp.protonmail.ch"; PORT="587"
FROM_NAME="TheProtocol Frame (Hetzner)"
TOKEN=""; ADDRESS=""; TEST_RCPT=""; FLIP_VERIFY=1
LOAD_MAX=60

while [ $# -gt 0 ]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2;;
    --address) ADDRESS="$2"; shift 2;;
    --test-recipient) TEST_RCPT="$2"; shift 2;;
    --server) SERVER="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --from-name) FROM_NAME="$2"; shift 2;;
    --stack) STACK="$2"; shift 2;;
    --service) SERVICE="$2"; shift 2;;
    --no-verify-flip) FLIP_VERIFY=0; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -n "$TOKEN" ]     || { echo "FATAL: --token is required" >&2; exit 2; }
[ -n "$ADDRESS" ]   || { echo "FATAL: --address is required" >&2; exit 2; }
[ -n "$TEST_RCPT" ] || { echo "FATAL: --test-recipient is required (we prove a real send before flipping verification)" >&2; exit 2; }

ENVF="$STACK/.env.frame-test"
[ -f "$ENVF" ] || { echo "FATAL: no env file at $ENVF" >&2; exit 1; }

# ── PART 1 load gate. Never recreate anything while the box is loaded. ──────
LOAD1=$(awk '{print int($1)}' /proc/loadavg)
if [ "$LOAD1" -ge "$LOAD_MAX" ]; then
  echo "ABORT: load1m=$LOAD1 >= $LOAD_MAX. Wait for the box to settle (PART 1)." >&2; exit 1
fi
echo "[gate] load1m=$LOAD1 (< $LOAD_MAX) OK"

STAMP=$(date +%Y%m%d-%H%M%S)
cp -p "$ENVF" "$ENVF.bak-pre-mail-$STAMP"
echo "[backup] $ENVF.bak-pre-mail-$STAMP"

# ── 1. Write MAIL_* into the env file (replace in place, never append a dup) ─
python3 - "$ENVF" "$SERVER" "$PORT" "$ADDRESS" "$TOKEN" "$FROM_NAME" <<'PY'
import sys, re
envf, server, port, address, token, from_name = sys.argv[1:7]
vals = {
    "MAIL_SERVER": server, "MAIL_PORT": port,
    "MAIL_USERNAME": address, "MAIL_PASSWORD": token,
    "MAIL_FROM": address, "MAIL_FROM_NAME": from_name,
    "MAIL_STARTTLS": "true", "MAIL_SSL_TLS": "false",
}
lines = open(envf).read().split("\n")
seen = set()
for i, l in enumerate(lines):
    m = re.match(r'^([A-Z0-9_]+)=', l)
    if m and m.group(1) in vals:
        k = m.group(1); lines[i] = f"{k}={vals[k]}"; seen.add(k)
for k, v in vals.items():
    if k not in seen:
        lines.append(f"{k}={v}")
open(envf, "w").write("\n".join(lines))
print(f"[env] set {len(vals)} MAIL_* keys ({len(seen)} replaced, {len(vals)-len(seen)} appended)")
PY
chmod 600 "$ENVF"

# ── 2. Validate + recreate the registry ────────────────────────────────────
cd "$STACK"
docker compose -f "$COMPOSE" --env-file .env.frame-test config >/dev/null \
  || { echo "FATAL: compose config invalid; restoring env" >&2; cp -p "$ENVF.bak-pre-mail-$STAMP" "$ENVF"; exit 1; }
echo "[compose] config valid"

docker compose -f "$COMPOSE" --env-file .env.frame-test up -d --no-deps --force-recreate "$SERVICE" >/dev/null
echo "[deploy] $SERVICE recreated; waiting for health"
for _ in $(seq 1 60); do
  sleep 3
  docker inspect "$SERVICE" --format '{{.State.Status}}' 2>/dev/null | grep -q running && break
done

# ── 3. PROVE a real send, using the SAME transport the registry uses ───────
# aiosmtplib start_tls=MAIL_STARTTLS and not MAIL_SSL_TLS (email_utils.py:313).
echo "[verify] sending a real test message to $TEST_RCPT ..."
if ! docker exec "$SERVICE" python3 - "$TEST_RCPT" <<'PY'
import os, smtplib, ssl, sys
from email.message import EmailMessage
rcpt = sys.argv[1]
host = os.environ["MAIL_SERVER"]; port = int(os.environ["MAIL_PORT"])
user = os.environ["MAIL_USERNAME"]; pwd = os.environ["MAIL_PASSWORD"]
sender = os.environ["MAIL_FROM"]; name = os.environ.get("MAIL_FROM_NAME", "")
starttls = os.environ.get("MAIL_STARTTLS", "true").lower() == "true"
ssl_tls  = os.environ.get("MAIL_SSL_TLS", "false").lower() == "true"
msg = EmailMessage()
msg["Subject"] = "Frame relay test"
msg["From"] = f"{name} <{sender}>" if name else sender
msg["To"] = rcpt
msg.set_content("Outbound mail from this frame is working. Sent by apply_frame_mail.sh.")
try:
    if ssl_tls:
        s = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        if starttls:
            s.starttls(context=ssl.create_default_context())
    s.login(user, pwd)
    s.send_message(msg)
    s.quit()
    print("SEND OK")
except Exception as e:
    print(f"SEND FAILED: {type(e).__name__}: {e}", file=sys.stderr); sys.exit(1)
PY
then
  echo "FATAL: the relay did not accept a message. Verification flag left UNCHANGED (still off)," >&2
  echo "       so registration keeps working via invite codes. Fix the credential and re-run." >&2
  exit 1
fi
echo "[verify] relay accepted the message"

# ── 4. Only now is it safe to require verification ────────────────────────
if [ "$FLIP_VERIFY" -eq 1 ]; then
  cp -p "$COMPOSE" "$COMPOSE.bak-pre-verifyflip-$STAMP"
  python3 - "$COMPOSE" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
new, n = re.subn(r'REQUIRE_EMAIL_VERIFICATION:\s*"false"', 'REQUIRE_EMAIL_VERIFICATION: "true"', s)
if n != 1:
    print(f"REFUSING: expected exactly 1 REQUIRE_EMAIL_VERIFICATION line, found {n}", file=sys.stderr); sys.exit(1)
open(p, "w").write(new); print("[compose] REQUIRE_EMAIL_VERIFICATION -> true")
PY
  docker compose -f "$COMPOSE" --env-file .env.frame-test config >/dev/null || {
      echo "FATAL: compose invalid after flip; restoring" >&2
      cp -p "$COMPOSE.bak-pre-verifyflip-$STAMP" "$COMPOSE"; exit 1; }
  docker compose -f "$COMPOSE" --env-file .env.frame-test up -d --no-deps --force-recreate "$SERVICE" >/dev/null
  echo "[deploy] recreated with verification required"
fi

# ── 5. Report what the frame now advertises publicly ──────────────────────
BASE=$(docker inspect "$SERVICE" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^BASE_URL=//p')
echo
echo "DONE. Public registration config now reads:"
curl -s --max-time 10 "$BASE/api/v1/auth/registration-config" || true
echo
echo "Rollback: cp -p $ENVF.bak-pre-mail-$STAMP $ENVF  (and the .bak-pre-verifyflip compose), then recreate."
echo "Instant kill without touching the frame: revoke that SMTP token in Proton."
