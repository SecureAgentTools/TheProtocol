# AgentVault CLI

> Command-line interface for interacting with the AgentVault sovereign network.

## What This Is

The AgentVault CLI (`agentvault_cli`) is a full-featured command-line tool for developers and agent operators to interact with the AgentVault ecosystem. It provides commands for agent discovery, task execution via the A2A protocol, credential management, agent onboarding, locks, and governance participation.

Built on `asyncclick` (async Click) with `httpx` for HTTP/2 communication and `rich` for formatted terminal output.

## Command Groups

### `agentvault discover` — Agent Discovery
- Search and list agents registered in any AgentVault Registry
- Supports pagination (`--limit`, `--offset`)
- **Federated discovery** (`--federated`): Searches across all peer registries in the federation, aggregating results with origin registry attribution
- Environment variable override: `AGENTVAULT_REGISTRY_URL`

### `agentvault run` — Task Execution (A2A Protocol)
- Execute tasks on remote agents via the Agent-to-Agent protocol
- Agent reference by: Registry ID, URL, or local JSON file path
- Supports MCP context injection via `--context-file`
- Real-time SSE streaming of task status, messages, and artifacts
- Artifact auto-saving to disk for large outputs (`--output-artifacts`)
- Rich terminal formatting with syntax highlighting for code artifacts
- Graceful cancellation via Ctrl+C (sends `tasks/cancel` to agent)
- Handles `apiKey`, `oauth2`, and `none` authentication schemes

### `agentvault config` — Credential Management
- `config set` — Configure API keys and OAuth2 credentials
  - `--env` — Guidance for environment variable setup
  - `--file` — Guidance for .env/.json file setup
  - `--keyring` — Store API key in OS keyring (secure)
  - `--oauth-configure` — Store OAuth Client ID/Secret in OS keyring
- `config get` — Check credential source and status for a service
- `config list` — List all configured credential sources

### `agentvault agent` — Agent Lifecycle
- `agent onboard` — Generate bootstrap tokens for new agent registration
  - Implements OAuth 2.0 Device Authorization Flow
  - Auto-opens browser for authentication
  - Returns single-use, time-limited bootstrap token + onboarding URL
  - Options: `--agent-type`, `--requested-by`, `--no-browser`

### `agentvault stake` — Locks
- `stake deposit` — Lock units to take part in governance, where the registry opens locks
- `stake withdraw` — Release a lock (after its lock period)
- `stake balance` — Check the locked balance, pending releases, and voting power (`--detailed` for full breakdown)

### `agentvault govern` — Governance Participation
- `govern create-proposal` — Create governance proposals (`--title`, `--description`, `--category`, `--tags`)
- `govern vote` — Cast votes on active proposals (`--for`, `--against`, `--abstain`, `--comment`)
- `govern show` — View full proposal details including voting results
- `govern list` — List proposals with filters (`--status`, `--category`, pagination)

## Configuration

All settings are configurable via environment variables (see `config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `AGENTVAULT_REGISTRY_URL` | `https://registry.agentvault.org` | Default registry URL |
| `AGENTVAULT_OAUTH_CLIENT_ID` | `agentvault-cli` | OAuth client ID |
| `AGENTVAULT_OAUTH_DEVICE_AUTH_URL` | `https://auth.agentvault.org/oauth/device/code` | Device auth endpoint |
| `AGENTVAULT_OAUTH_TOKEN_URL` | `https://auth.agentvault.org/oauth/token` | Token endpoint |
| `AGENTVAULT_HTTP_TIMEOUT` | `30.0` | HTTP request timeout (seconds) |
| `AGENTVAULT_AUTO_OPEN_BROWSER` | `true` | Auto-open browser for OAuth flows |
| `AGENTVAULT_AUTH_TOKEN` | (none) | Bearer token for locks and governance |

## Dependencies

- `asyncclick` — Async CLI framework
- `httpx` — HTTP/2 async client
- `rich` — Terminal formatting, panels, syntax highlighting
- `agentvault` (library) — Core models, A2A client, key management, agent card utilities

## Installation

```bash
# From the monorepo root
cd AgentVault/agentvault_cli
poetry install
```

Published wheels are available in `dist/`.

## Test Suite

- `test_agent_commands.py` — Agent onboarding command tests
- `test_config_commands.py` — Credential management tests
- `test_discover_command.py` — Discovery and federated search tests
- `test_run_command.py` — Full A2A task execution tests
- `test_utils.py` — Utility function tests

## Status

**Feature-complete for MVP.** All six command groups implemented. Lock and governance commands use placeholder auth (`AGENTVAULT_AUTH_TOKEN` env var) — full OAuth flow integration is planned. Discovery and task execution are fully operational against the bilateral federation stack.
