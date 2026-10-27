# AgentVault Event Store

> Immutable event-sourced ledger for the AgentVault sovereign network.

## What This Is

The Event Store is a standalone FastAPI microservice that serves as the single source of financial truth for the entire AgentVault ecosystem. Every movement of units (issuance, transfer, locking, unlocking, dispute slashes, compensation payments and payouts on locked units) is recorded as an immutable event. Current balances are never stored directly; they are always calculated by replaying the event stream (CQRS/Event Sourcing pattern).

## Architecture

- **Runtime**: Python 3.11 / FastAPI 0.104
- **Database**: PostgreSQL 15 (via SQLAlchemy 2.0 + asyncpg)
- **Real-time**: WebSocket pub/sub for live event streaming
- **Port**: `8200` (container), mapped to `8200` (host)
- **Auth**: Internal API key (`X-Internal-Key` header) — not user-facing

## Event Types

| Event Type | Effect | Source |
|---|---|---|
| `TokensIssued` | +liquid | Registry genesis grants, TEG treasury |
| `TokensTransferred` | -liquid (sender), +liquid (receiver) | Agent-to-agent transfers via TEG |
| `TokensStaked` | -liquid, +locked | Lock operations |
| `TokensUnstaked` | +liquid, -locked | Unlock operations |
| `RewardsDistributed` | +liquid | Payouts on locked units |
| `RewardsAutoCompounded` | +locked | Payouts relocked automatically |
| `DisputeSlash` | -liquid (defendant) | Dispute resolution system |
| `DisputeCompensationMinted` | +liquid (complainant) | Dispute resolution system |
| `AgentCreated` | (metadata only) | Registry onboarding |
| `AgentUpdated` | (metadata only) | Registry agent updates |
| `AttestationSubmitted` | (metadata only) | ZKP attestation pipeline |
| `ReputationChanged` | (metadata only) | Reputation system |

## API Endpoints

### Events (`/api/v1/events`)
- `POST /` — Append event (requires `X-Internal-Key`)
- `GET /` — List all events with pagination (requires `X-Internal-Key`)
- `GET /aggregate/{aggregate_id}` — Events for a specific agent (requires `X-Internal-Key`)
- `GET /health` — Health check (no auth)

### Projections (`/api/v1/projections`)
- `GET /balance/{agent_did}` — Current balance for an agent (calculated from event stream). Supports `?refresh=true` to bypass 30s cache.
- `GET /balances` — All agent balances (single-pass O(n) calculation). Supports `?refresh=true`.
- `GET /transactions/{agent_did}` — Human-readable transaction history with optional type filtering.
- `GET /balance/{agent_did}/at/{timestamp}` — Historical balance at any point in time (event sourcing time-travel).
- `GET /stats` — System-wide statistics (total events, unique agents, event type counts, time range). Uses SQL aggregation, not in-memory.

### WebSocket (`/ws/events`)
- Real-time event streaming via WebSocket
- Channel subscription model: `agent:{did}`, `events:all`, `events:{type}`
- Actions: `subscribe`, `unsubscribe`, `ping`, `stats`

### Root
- `GET /` — Service info and endpoint directory
- `GET /health` — Simple health check

## Key Design Decisions

- **Balance Cache (P2-005)**: In-memory TTL cache (30s) avoids replaying entire event stream on every balance query. Cache can be bypassed with `?refresh=true` for post-write consistency.
- **Single-Pass Balances (P2-006)**: `GET /balances` processes all events once instead of calling `calculate_balance()` per agent, reducing O(n×m) to O(n).
- **SQL Aggregation (P2-007)**: Stats endpoint uses SQL `COUNT`/`MIN`/`MAX` instead of loading events into memory.
- **Connection Pooling (P3-003)**: Uses `AsyncAdaptedQueuePool` with pool_size=5, max_overflow=10.
- **Transfer Awareness**: Balance projection correctly handles both sides of transfers — the agent as sender (debit) AND as recipient (credit via JSONB query on `data->>'to'`).

## Docker Deployment

The Event Store runs as two containers in the stack:

| Container | Image | Port | Network |
|---|---|---|---|
| `agentvault_event_store` | Custom (Dockerfile) | 8200:8200 | agentvault-network |
| `agentvault_event_store_db` | postgres:15-alpine | 5435:5432 | agentvault-network |

**Sandbox mirror**: `agentvault_event_store_test` + `agentvault_event_store_test_db` (ports 8201, 5442) for the API Tester bilateral sandbox.

### Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (asyncpg) |
| `INTERNAL_API_KEY` | Shared secret for authenticated endpoints |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins |
| `SQL_ECHO` | Enable SQLAlchemy SQL logging (`true`/`false`) |

## Integration Points

- **Registry A/B**: Emit events on agent creation, token operations, dispute actions
- **TEG Layer A/B**: Emit events on transfers, locks, attestations
- **Mission Control Dashboard**: Reads projections for balance displays, subscribes via WebSocket for real-time updates
- **Dispute System**: Emits `DisputeSlash` and `DisputeCompensationMinted` events during four-phase dispute resolution

## Database Schema

Single `events` table with JSONB `data` and `event_metadata` columns. Indexed on `aggregate_id`, `event_type`, `timestamp`, and composite `(aggregate_id, timestamp)`.

## Utilities

- `check_agent_events.sql` — SQL script for direct event inspection
- `inspect_databases.py` — Database diagnostic tool
- `verify_event_store.py` — Integration verification script
- `diagnostic.py` — Runtime diagnostic module
- `event_emitter.py` — Client-side helper for services emitting events

## Test Suite

- `test_event_store.py` — Core event append/query tests
- `test_projections.py` — Balance calculation and projection tests
- `test_websocket.py` — WebSocket connection and subscription tests
- `test_teg_event_store_integration.py` — End-to-end TEG integration tests

## Status

**Production-ready.** Running in the bilateral federation stack with full event coverage for every movement of units, dispute resolution (OWL25) and payouts on locked units (OWL20-PREP) included.
