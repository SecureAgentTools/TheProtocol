# OPERATOR_CLAUDE.md: Operational Briefing

**Audience**: an AI assistant working for the operator of a federated registry, and the operator who hands it this page
**Checked against the source**: 2026-10-16 (V0618: the registry's OpenAPI document; the operator bundle's compose)

> **Read the served manual first.** Every registry serves a manual for assistants, generated for itself:
> `GET {REGISTRY_URL}/api/v1/downloads/CLAUDE.md` (public). It fills in that registry's URL, name, role, unit, trust
> domain and whether issuance works there, and walks through logging in, creating agents and moving units with
> requests you can copy. This page is the short, generic briefing beside it; the repository publishes it as
> `PUBLIC_DOCS/OPERATOR_CLAUDE.md`.

---

## What TheProtocol Is

TheProtocol is a platform for AI agent identity and orchestration: decentralized agent identities (DIDs), platform
units for fees and services (with locks and per-registry governance where a registry switches them on), federated
registries that discover each other's agents, an append-only event ledger, and a SPIFFE/SPIRE identity fabric for
mutual TLS. As a federated operator you run your own registry stack under a parent frame: your agents and your rules,
connected to the federation over mTLS.

---

## The Operator Stack

The bundle a frame provisions for its operator runs ten containers (`<name>` is `REGISTRY_NAME`):

| # | Container | Role | Host port |
|---|-----------|------|-----------|
| 1 | `<name>-registry` | API and web console | `12000` -> 8000 |
| 2 | `<name>-teg` | TEG (the ledger service): balances, transfers, locks | `12080` -> 8080 |
| 3 | `<name>-db` | PostgreSQL 18, the registry's database | internal |
| 4 | `<name>-teg-db` | PostgreSQL 18, the TEG's database | internal |
| 5 | `<name>-pgbouncer` | connection pooler for the registry's database | internal |
| 6 | `<name>-redis` | shared state, leader election, rate limits | internal |
| 7 | `<name>-spire-agent` | SPIRE agent, attested by the parent frame's SPIRE server | internal |
| 8 | `<name>-cert-writer` | writes the SVID and the trust bundle for the two sidecars | internal |
| 9 | `<name>-nginx-federation` | mTLS terminator for federation traffic | `12443` -> 8443 |
| 10 | `<name>-nginx-teg` | internal mTLS gateway in front of the TEG | internal |

The compose publishes `12000`, `12080` and `12443` on every interface: only `12443` needs to be reachable by the frame.

---

## Key Environment Variable Categories

| Category | Variables | Purpose |
|----------|-----------|---------|
| **Identity** | `REGISTRY_NAME`, `OPERATOR_DID`, `FEDERATION_OPERATOR_ID` | Which operator this is |
| **Databases** | `PG_PASS_REGISTRY`, `PG_PASS_TEG` | Generated database passwords |
| **Security** | `SECRET_KEY`, `JWT_SECRET_KEY`, `API_KEY_SECRET`, `TEG_ADMIN_API_KEY` | Signing keys (`API_KEY_SECRET` signs the registry's JWTs) and the TEG's admin key |
| **Federation** | `FEDERATION_LICENSE_KEY`, `EVENT_STORE_URL`, `FEDERATION_BASE_URL`, `SPIFFE_ENDPOINT_SOCKET` | The licence, the parent frame's event store, the federation sidecar, the SPIRE agent's socket |
| **Units** | `MINTING_AUTHORITY`, `GENESIS_GRANT_ENABLED`, `GENESIS_GRANT_AMOUNT` | Issuance (`disabled` on an operator) and the grant a new agent receives |
| **Email** | `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | SMTP for verification mails |
| **Features** | `BETA_INVITE_REQUIRED`, `ENABLE_PROJECTION_SNAPSHOTS` | Switches |

Full reference: operator chapters 02 (Configuration) and 14 (Setup Manual).

---

## Federation Topology

```
Your operator stack                                Your parent frame
+--------------------------------+                 +--------------------------------+
|  registry, TEG, databases      |-- events ------>|  event store (the ledger)      |
|  spire-agent ------------------|-- x509pop ----->|  SPIRE server                  |
|  nginx-federation (mTLS 8443)  |<--- mTLS ------>|  registry (federation sync)    |
+--------------------------------+                 +--------------------------------+
```

- **Events**: your registry writes its ledger events to the parent frame's event store (`EVENT_STORE_URL`, written
  by the frame when it provisions you). An operator has no event store of its own.
- **Agent cards**: registries exchange the cards that changed over mTLS, every `FEDERATION_SYNC_INTERVAL_SECONDS`
  (600 seconds when unset; the kit's generator writes 30).
- **Cross-registry transfers** use a two-phase protocol with a 0.5 % fee.
- **Issuance is disabled** on an operator (`MINTING_AUTHORITY=disabled`); the issuance route answers 404 (`mainframe_only`) outside a
  sovereign frame.

---

## Quick API Reference (Operator-Relevant Endpoints)

Paths as the registry serves them; the credential each one takes is in brackets.

### Authentication
```
POST /api/v1/auth/login                       Developer login [none; form-encoded username=<email>&password=...]
POST /api/v1/auth/agent/token                 Agent JWT [none; form-encoded username=<client_id>&password=<client_secret>]
POST /api/v1/auth/api-keys                    Create an API key [developer JWT]
```

### Agent Management
```
POST /api/v1/onboard/bootstrap/request-token  Bootstrap token [developer JWT or API key]
POST /api/v1/onboard/create_agent             Create an agent [Bootstrap-Token header]
GET  /api/v1/agents/by-did/{did}              An agent by DID [none]
```

### Units and Transfers
```
POST /api/v1/teg/transfer                     Transfer units between agents [agent JWT]
POST /api/v1/teg/cross-registry-transfer      Transfer to an agent on another registry, 0.5 % fee [agent JWT]
GET  /api/v1/teg/balance                      The calling agent's balance [agent JWT]
```

### Locks
```
POST /api/v1/staking/stake                    Lock units [agent JWT; 403 staking_disabled where STAKING_ENABLED is off]
POST /api/v1/staking/unstake                  Release a lock once its period has passed [agent JWT; works with locks switched off]
```

### Governance
```
POST /api/v1/governance/proposals                     Create a proposal [agent JWT]
POST /api/v1/governance/proposals/{proposal_id}/vote  Cast a vote [agent JWT]
GET  /api/v1/governance/proposals                     List proposals [none]
```

### Discovery
```
GET  /api/v1/agent-cards/discover             Search agents [none; q, tag, pricing, sort, limit]
GET  /api/v1/federation/network-stats         Network counts [none]
GET  /api/v1/federation/registries            Federated registries and their health [none]
```

### A2A Payment
```
POST /api/v1/a2a-payment/authorize            Issue a payment token [agent JWT]
POST /api/v1/a2a-payment/verify               Verify a payment token [none]
POST /api/v1/a2a-payment/settle               Settle a payment [agent JWT]
```

The registry's whole surface is its OpenAPI document, `GET {REGISTRY_URL}/api/v1/openapi.json`.

---

## Docker Commands

```bash
# Start the stack
docker compose -f docker-compose.operator.yml --env-file .env.operator up -d

# Stop the stack
docker compose -f docker-compose.operator.yml --env-file .env.operator down

# Container status
docker compose -f docker-compose.operator.yml --env-file .env.operator ps

# Registry and TEG logs
docker logs <name>-registry --tail 50
docker logs <name>-teg --tail 50

# Health check
curl -s http://localhost:12000/health | python3 -m json.tool

# Recreate the registry alone after an env change (its dependencies keep running)
docker compose -f docker-compose.operator.yml --env-file .env.operator up -d --no-deps --force-recreate registry
```

The `tp-operator` host CLI wraps most of these, with backups and restores (operator chapter 12).

---

## Documentation Index

| Chapter | What it covers |
|---------|----------------|
| Operator 00: Quickstart | Setup in brief |
| Operator 01: Architecture | The containers and how they connect |
| Operator 02: Configuration | Environment variables and secrets |
| Operator 03: Federation | mTLS, card sync, cross-registry transfers |
| Operator 04: Units & Fees | Units, fees, locks, disputes |
| Operator 05: API Reference | Endpoints, auth, examples |
| Operator 06: Monitoring | Prometheus, Grafana, alerts |
| Operator 07: Troubleshooting | Common issues and Docker commands |
| Operator 08: Security | mTLS, SPIRE, licences, incidents |
| Operator 09: Governance | Voting, proposals, veto |
| Operator 10: Compliance | ISO 42001, supply audit, GDPR |
| Operator 12: Host CLI | `tp-operator`: status, backups, updates, SPIRE |
| Operator 13: AI Assistants & MCP | The MCP server, the bridges, the served manual |
| Operator 14: Setup Manual | Standalone and federated, step by step |
| Operator 22: Suspension | Suspending and reinstating agents and developers |

---

## Key Constraints

- **Issuance is disabled** on an operator. Units reach it from the federation (cross-registry transfers, liquidity
  from its parent frame); the genesis grant is paid from what its treasury holds.
- **Fees**: a transfer within a registry pays the registry's fee, 0.5 % by default and up to 5 % under high
  velocity (its enforcement policy); a cross-registry transfer pays 0.5 %.
- **Locks**: `STAKING_ENABLED` decides whether units can be locked. On the production frames it is off (no new
  locks; existing locks can be released) and votes count by membership, not by locked units. A payout on locked
  units is a separate switch, `STAKING_REWARDS_ENABLED`, discretionary, paid in platform units, and off on the public
  network; a frame someone else runs sets its own switches.
- **Events are append-only**: every unit movement is recorded in the parent frame's event store.
- **Revocation**: when the frame revokes or suspends your operator, its licence and its SPIRE identity stop working
  at the frame's federation gate.

---

*For the assistant: the served manual (`/api/v1/downloads/CLAUDE.md`) carries this registry's own values; read it
before you act.*
