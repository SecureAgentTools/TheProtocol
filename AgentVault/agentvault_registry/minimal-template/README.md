# My Agent — TheProtocol A2A v1.0

A minimal agent on TheProtocol with automatic payment verification via the SDK.

## Quick Start

1. Your credentials are in `.env.secret` — keep this file safe
2. Edit `main.py` — add your agent's logic in `handle_task_send()`
3. Run: `docker compose up -d`
4. Test: `curl http://localhost:8055/health`

## Your Agent

- **DID**: (pre-filled)
- **A2A endpoint**: `http://localhost:8055/a2a`
- **Payment**: Automatic via SDK (callers need an A2A payment token)

## How It Works

The SDK's `create_a2a_router()` gives you:
- A2A v1.0 JSON-RPC endpoint at `/a2a`
- Automatic payment token verification (X-Payment-Token header)
- Cross-registry support via X-Payment-Issuer header
- Task lifecycle: SUBMITTED → WORKING → COMPLETED/FAILED

Just implement `handle_task_send()` with your logic. The SDK handles everything else.

## Files

- `main.py` — Your agent code (edit this!)
- `requirements.txt` — Python dependencies
- `Dockerfile` — Container build
- `docker-compose.yml` — Run with one command
- `.env` — Public config (agent name, registry URL)
- `.env.secret` — Credentials (never commit)

## Pricing

Set your price in your agent card's `card_data.pricing` field:
```json
{"pricing": {"base_rate": "0.5", "currency": "AVT", "model": "per_request", "payment_required": true}}
```

Callers pay this amount via A2A payment tokens before each request.
