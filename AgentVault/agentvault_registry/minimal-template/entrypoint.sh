#!/bin/sh
set -e

# Source env files if mounted by docker-compose
if [ -f /app/.env.secret ]; then . /app/.env.secret; fi
if [ -f /app/.env ]; then . /app/.env; fi

echo "[Agent] Starting ${AGENT_NAME:-My Agent} on port 8055..."
exec uvicorn main:app --host 0.0.0.0 --port 8055 --log-level info
