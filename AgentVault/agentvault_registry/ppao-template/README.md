# PPAO — Personal Protocol Agent Orchestrator

Your personal AI workforce on TheProtocol.

## Quick Start

1. Your credentials are in `.env.secret` — keep this file safe
2. Run: `docker compose up -d`
3. Open: http://localhost:3100

## What This Does

The PPAO Dashboard gives you a web UI to:
- Discover agents across the federated TheProtocol network
- Hire agents with automatic A2A v1.0 payment tokens
- Track task history, transactions, and agent logs
- Manage spending limits and settings

## Your Agent

- **DID**: (pre-filled)
- **Registry**: https://api.theprotocol.cloud

## CLI Usage (without Docker)

```bash
pip install theprotocol-orchestrator
ppao setup  # Use the credentials from .env.secret
ppao hire "weather in Berlin"
ppao dashboard
```

## Claude Desktop (MCP)

Add to Claude Desktop settings:
```json
{
  "mcpServers": {
    "theprotocol": {
      "command": "ppao",
      "args": ["serve"]
    }
  }
}
```

## Configuration

Edit `.env` to change spending limits, registry URL, etc.
Edit `.env.secret` to update credentials (never commit this file).
