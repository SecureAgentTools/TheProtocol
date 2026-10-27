# AgentVault Library

> Core Python SDK for building agents and clients on the AgentVault sovereign network.

## What This Is

`agentvault_library` is the foundational Python package that provides everything needed to interact with the AgentVault ecosystem: the A2A protocol client, agent card models, secure credential management, MCP context formatting, and high-level APIs for onboarding, locks, and governance.

This library is consumed by the CLI, the Server SDK, and any third-party agent or client application.

## Core Modules

### `client.py` — AgentVaultClient (A2A Protocol)
The primary interface for communicating with remote agents via JSON-RPC 2.0 over HTTP/SSE.

- `initiate_task()` — Start a new task on a remote agent
- `send_message()` — Send follow-up messages to an active task
- `get_task_status()` — Poll current task state
- `terminate_task()` — Request graceful task cancellation
- `receive_messages()` — Subscribe to real-time SSE event stream

**Features:**
- Full A2A protocol compliance (tasks/send, tasks/get, tasks/cancel, tasks/sendSubscribe)
- HTTP/2 with automatic redirect following
- OAuth2 Client Credentials Grant with token caching and expiry management
- API Key authentication (`X-Api-Key` header)
- SSE stream processing with proper event type mapping and Pydantic validation
- MCP context embedding in message metadata
- Webhook URL support for push notifications

### `key_manager.py` — KeyManager (Credential Management)
Multi-source credential manager with priority-based resolution.

**Priority order (highest to lowest):**
1. Key file (`.env` or `.json`)
2. Environment variables
3. OS Keyring (optional, via `keyring` package)

**Supports:**
- API Keys: `AGENTVAULT_KEY_<SERVICE_ID>` env vars, file entries, keyring storage
- OAuth2 Credentials: Client ID + Client Secret via env vars (`AGENTVAULT_OAUTH_<SERVICE_ID>_CLIENT_ID/SECRET`), JSON file nested `oauth` blocks, or keyring pairs

### `models/` — Pydantic Data Models
- `agent_card.py` — `AgentCard` model with authentication schemes, capabilities, and A2A endpoint
- `a2a_protocol.py` — Full A2A protocol models: `Message`, `Task`, `TaskState`, `TextPart`, `DataPart`, `FilePart`, `Artifact`, SSE event types (`TaskStatusUpdateEvent`, `TaskMessageEvent`, `TaskArtifactUpdateEvent`), JSON-RPC request/response types

### `agent_card_utils.py` — Agent Card Utilities
- `fetch_agent_card_from_url()` — Fetch agent card from remote URL
- `load_agent_card_from_file()` — Load from local JSON file
- `parse_agent_card_from_dict()` — Parse from dictionary
- `discover_agents_federated()` — Federated discovery across all peer registries

### `mcp_utils.py` — MCP Context Formatting
- `format_mcp_context()` — Format MCP context data for embedding in A2A message metadata

### `onboarding.py` — Agent Registration
- `register_agent_with_bootstrap_token()` — Complete two-phase onboarding: exchange a single-use bootstrap token for permanent agent credentials (DID + OAuth2 client ID/secret)
- Supports configurable DID methods (default: `cos` for Concierge-OS)
- Optional proof-of-work challenge response

### `staking.py` — Lock Operations
- `stake_tokens()` — Lock units for governance participation, where the registry opens locks
- `unstake_tokens()` — Release a lock (with lock period tracking)
- `get_staking_balance()` — Retrieve the full lock status including voting power

### `governance.py` — Governance Participation
- `VoteChoice` enum: `FOR`, `AGAINST`, `ABSTAIN`
- `create_proposal()` — Create governance proposals with validation
- `cast_vote()` — Vote on active proposals with optional comments
- `get_proposal()` — Retrieve full proposal details including vote counts
- `list_proposals()` — Paginated proposal listing with status/category filters

## Exception Hierarchy

```
AgentVaultError
├── A2AError
│   ├── A2AConnectionError
│   ├── A2AAuthenticationError
│   ├── A2ARemoteAgentError (status_code, response_body)
│   ├── A2ATimeoutError
│   └── A2AMessageError
├── KeyManagementError
├── OnboardingError (status_code, response_body)
└── AgentCardError
    ├── AgentCardValidationError
    └── AgentCardFetchError (status_code, response_body)
```

## Installation

```bash
# From the monorepo root
cd AgentVault/agentvault_library
poetry install

# With OS keyring support
poetry install --extras os_keyring
```

Published wheels are available in `dist/`.

## Test Suite

- `test_client.py` — A2A client with mocked HTTP (respx)
- `test_key_manager.py` — Multi-source credential resolution
- `test_mcp_utils.py` — MCP context formatting
- `test_onboarding.py` — Bootstrap token registration flow
- `test_agent_card_utils.py` — Agent card loading and parsing

## Status

**Production-ready.** Core A2A client, credential management, and agent card utilities are fully operational in the bilateral federation stack. The lock and governance modules provide complete API interfaces for the units and fees system.
