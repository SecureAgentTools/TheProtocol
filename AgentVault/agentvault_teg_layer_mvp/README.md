# AgentVault TEG Layer (MVP)

> Token Exchange Gateway — the economic engine of the AgentVault sovereign network.

## What This Is

The TEG (Trusted Ecosystem Governance) Layer is the largest and most complex microservice in AgentVault. It is the central authority for all units and fees, agent identity management, locks, governance, dispute resolution, reputation scoring, ZKP attestation verification, and cross-TEG federation. Every financial operation in the network flows through the TEG.

## Architecture

- **Runtime**: Python 3.11 / FastAPI
- **Database**: PostgreSQL 15 (via SQLAlchemy 2.0 async, Alembic migrations)
- **Auth**: OAuth 2.0 federation (multi-issuer), JWT-SVID (SPIRE), API key, admin impersonation (dev only)
- **Port**: `8100` (TEG-A), `8101` (TEG-B)
- **Event Store Integration**: Emits all token events to the Event Store via internal API

## API Surface

The TEG exposes a comprehensive REST API under `/api/v1/`, organized into these endpoint groups:

### Authentication (`/auth`)
- OAuth2 token exchange, session management

### Token Management (`/token`)
- Token transfers between agents
- Balance queries
- Transaction history
- Supports JWT-SVID auth mode (`USE_JWT_SVID_AUTH=true`) or standard bearer tokens

### Units and fees (`/tokenomics`)
- Lock operations (lock, release, balance)
- Payouts on locked units and their relocking, where a registry switches them on
- Transaction history with filtering
- Treasury operations

### Administration (`/admin`)
- Agent management (create, update, fund, list)
- Genesis grant distribution
- Treasury transfers and receives (OWL26)
- System configuration
- Admin impersonation for dev/test environments

### Governance (`/governance`)
- Proposal creation and management
- Voting with lock-weighted voting power
- Proposal listing with status/category filters

### Agent Management (`/agent`)
- Agent registration and profile management
- Agent card linkage
- Status tracking

### Attestations (`/attestation`)
- ZKP attestation submission and verification
- Circuit registry integration
- Attestation history queries

### Auditor (`/auditor`)
- Automated compliance checking
- Rule-based auditing engine
- Audit report generation

### Disputes (`/disputes`)
- Four-phase dispute resolution protocol
- Dispute filing, evidence submission, ruling
- Slashing (DisputeSlash) and compensation payments (DisputeCompensationMinted, a historical event name)
- Dispute history and status tracking

### Reputation (`/reputation`)
- Reputation score queries
- Reputation signal submission and processing
- Score calculation based on transaction history, attestations, and dispute outcomes

### AVTP Integration (`/avtp`)
- AgentVault Transaction Protocol endpoints
- Transaction initiation and completion
- Resource usage tracking

### Onboarding (`/onboarding`)
- Bootstrap token generation and validation
- Two-phase agent registration protocol
- DID assignment (Concierge-OS method)

### Internal (`/internal`)
- Service-to-service communication endpoints
- Health checks, federation sync, event propagation

### Cross-TEG Federation
- Cross-TEG transfer protocol (distributed transactions)
- Peer TEG discovery and communication
- Security monitoring with configurable alert handlers

## Core Components

### Security & Auth
- `secure_config.py` — Pydantic Settings with environment variable binding
- `enhanced_security.py` — Security headers middleware (CSP, HSTS, X-Frame-Options)
- `jwt_auth.py` / `jwt_svid/` — JWT and SPIRE JWT-SVID authentication
- `oauth/` — Multi-issuer OAuth 2.0 federation support
- `security_middleware.py` — Request-level security processing
- `cross_teg_security/` — Cross-TEG security monitoring and alerting

### Business Logic
- `reputation_logic.py` — Reputation score calculation engine
- `automated_auditor.py` — Rule-based automated compliance auditing
- `auditor_rules.py` — Configurable audit rule definitions
- `zkp_verifier.py` — Zero-Knowledge Proof verification (reads from Circuit Registry)
- `idempotency.py` — Idempotency key tracking for financial operations
- `validators.py` — Input validation utilities

### Infrastructure
- `logging.py` / `structured_logging.py` — Structured logging with request ID tracking
- `error_handling.py` / `errors.py` — Unified error handling (POLISH-001)
- `cross_teg/` — Cross-TEG transfer protocol, distributed transaction coordinator, client factory
- `event_store_integration.py` — Event Store client for emitting token events
- `event_emitter.py` — Event emission helper

### Database
- `database/db_session.py` — Async SQLAlchemy engine and session management
- `database/models.py` — Full ORM model hierarchy
- `alembic/` — Database migration scripts

## Docker Deployment

| Container | Port | Database | Network |
|---|---|---|---|
| `agentvault_teg_layer` (TEG-A) | 8100 | `teg-db-a` (5436) | agentvault-network |
| `agentvault_teg_layer_b` (TEG-B) | 8101 | `teg-db-b` (5437) | agentvault-network |
| `agentvault_teg_layer_test` (Sandbox-A) | 8102 | `teg-db-test-a` (5440) | agentvault-network |
| `agentvault_teg_layer_test_b` (Sandbox-B) | 8103 | `teg-db-test-b` (5441) | agentvault-network |

### Key Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `INTERNAL_API_KEY` | Shared secret for service-to-service auth |
| `USE_JWT_SVID_AUTH` | Enable SPIRE JWT-SVID auth mode |
| `OAUTH_ISSUER_*` | Multi-issuer OAuth configuration |
| `CROSS_TEG_PEER_URL` | URL of peer TEG instance for federation |
| `EVENT_STORE_URL` | Event Store service URL |
| `EVENT_STORE_API_KEY` | Event Store internal API key |
| `ADMIN_IMPERSONATION_ENABLED` | Enable admin impersonation (dev only) |
| `CORS_ALLOWED_ORIGINS` | CORS configuration |

## Integration Points

- **Registry A/B**: Agent registration, card management, onboarding flow
- **Event Store**: All token operations emit events for immutable audit trail
- **SPIRE**: JWT-SVID identity validation via SPIFFE Workload API
- **Circuit Registry**: ZKP verification key loading for attestation validation
- **Peer TEG**: Cross-TEG transfers via distributed transaction protocol
- **Cognitive Shield Agent**: Automated auditing integration
- **Mission Control Dashboard**: Balance, transaction, and governance data feeds

## Documentation

- `CONFIGURATION.md` — Full configuration reference
- `SECURITY.md` — Security architecture and threat model
- `INTERNAL_ARCHITECTURE.md` — Internal design documentation
- `TEG_EVENT_STORE_INTEGRATION_PATCH.md` — Event Store integration details
- `OPERATION_KEYSTONE_CONCORDANCE_REPORT.md` — Cross-TEG concordance testing
- `CROSS_TEG_ENV_EXAMPLE.env` — Cross-TEG environment template
- `OAUTH_FEDERATION_ENV_EXAMPLE.env` — OAuth federation environment template
- `openapi_jwt_svid.yaml` / `openapi_oauth.yaml` — OpenAPI specifications

## Test Suite

Comprehensive test coverage across unit, integration, and architectural tests:
- Token transfer and balance tests
- Lock lifecycle tests
- Dispute resolution tests
- Reputation calculation tests
- Onboarding protocol tests
- Cross-TEG federation tests
- Security and authentication tests
- Automated auditor tests

## Status

**Production-ready.** The TEG Layer is fully operational in the bilateral federation stack with complete units and fees, dispute resolution (OWL25), locks, governance, ZKP attestation verification, and cross-TEG federation. OAuth multi-issuer federation and SPIRE JWT-SVID authentication are both supported.
