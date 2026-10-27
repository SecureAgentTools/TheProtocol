# `downloads/` — public static files baked into the registry image

This directory exists so the Dockerfile's `COPY ./agentvault_registry/ .` step
picks up files served by `routers/downloads.py` at `/api/v1/downloads/...`.

## Files

- `mcp-stdio-bridge.js` — public MCP bridge for Claude Code / Desktop
  - Canonical source: `/opt/theprotocol/stack/Agentvault2/mcp-stdio-bridge.js`
  - This is a copy. Keep in sync when the canonical changes.
- `mcp-stdio-bridge-admin.js` — admin MCP bridge (admin developer JWT required at runtime)
  - Canonical source: `/opt/theprotocol/stack/Agentvault2/mcp-stdio-bridge-admin.js`

## Sync helper

Update both copies before `docker compose build registry-a`:
```bash
cp /opt/theprotocol/stack/Agentvault2/mcp-stdio-bridge.js \
   /opt/theprotocol/stack/Agentvault2/AgentVault/agentvault_registry/downloads/
cp /opt/theprotocol/stack/Agentvault2/mcp-stdio-bridge-admin.js \
   /opt/theprotocol/stack/Agentvault2/AgentVault/agentvault_registry/downloads/
```

§pass66.8 (2026-05-23) — Commander requested downloadable bridge so developers
can plug Claude Code into TheProtocol without manually fetching from repo root.
