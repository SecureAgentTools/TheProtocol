#!/usr/bin/env bash
# Hetzner Frame live-demo standup — thin wrapper with logging.
# Plan: sessionlogs2026/STRATEGY_2026-07-26_HETZNER_FRAME_LIVE_DEMO.md
# UNTESTED until R1 (defer full runs while host load is high / FE session builds).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$DIR/logs"
LOG="$DIR/logs/standup-$(date +%Y%m%d-%H%M%S).log"
# The HOST python has docker-py 5.0.3, which is incompatible with requests>=2.32
# ("Not supported URL scheme http+docker"). Use the isolated venv (docker>=7.1)
# so we never mutate host-wide Python for a demo script.
PY="$DIR/.venv/bin/python"; [ -x "$PY" ] || PY=python3
echo "[wrapper] python: $PY"
echo "[wrapper] logging to $LOG"
exec "$PY" "$DIR/standup_driver.py" "$@" 2>&1 | tee "$LOG"
