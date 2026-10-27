# ISO/IEC 42001:2023 AI Management System Alignment

**Version**: 2.3.3
**Status**: DRAFT: self-assessment (not independently audited)
**Last Updated**: 2026-10-17 (earlier: 2026-10-16, 2026-10-13, 2026-10-03 and 2026-08-09; the jurisdiction-profiles document joined the suite 2026-07-31)
**Scope**: TheProtocol AI Agent Orchestration Platform

---

## Executive Summary

TheProtocol is a sovereign AI agent orchestration and identity platform whose production network is two federated frames, EU and ASIA, and four cloud operators (Amsterdam and Lisbon under EU, Shenzhen and Ho Chi Minh City under ASIA), on a dedicated Hetzner bare-metal server (FSN1-DC15). The platform enables decentralized AI agent identity (DIDs), platform-internal accounting units (each frame has its own: ECU on EU, ACU on ASIA), bilateral federated registries, an immutable CQRS event ledger, SPIFFE/SPIRE-based mTLS identity fabric, and OPA policy enforcement.

This document maps the requirements of ISO/IEC 42001:2023 (Artificial Intelligence Management System, AIMS) to TheProtocol's existing infrastructure, policies, and operational procedures. The assessment covers these in-house AI components: EigenTrust++ reputation engine, Zero-Knowledge Proof attestations, <!-- on: staking_rewards -->the payout on locked units (the payout engine, switched off on the production frames), <!-- /on -->Collusion Detection network analysis, Bayesian Trust scoring, and Federation Governance consensus.

Current assessment (self-assessed, re-reviewed 2026-06-12): all 22 ISO/IEC 42001 sub-clauses evaluated are implemented: the controls are deployed, and the eight-document compliance suite that evidences them is complete, published (in-app at `/compliance`) and version-controlled. Two caveats, stated plainly: (1) this is a self-assessment, and an independent audit by an accredited assessor has not yet been conducted; (2) one infrastructure hardening gap outside the ISO clause scope remains open: block-level disk encryption at rest is not enabled (risk register R-OP-08; credentials are stored hashed regardless of disk state).

TheProtocol's supply invariant audit (`delta = 0.0`, continuously verified by an independent atomic auditor and validated under load to roughly 275 transactions/second intra-registry and ~114 transactions/second end-to-end under 16 concurrent simulations) demonstrates the level of engineering rigor applied across the platform. The same discipline extends to AI component governance: all six AI algorithms are built in-house with no opaque third-party AI dependencies, enabling full auditability from input to output.

The platform serves four stakeholder tiers: Commander (sole maintainer, full admin), registry operators (federation license holders), developers (agent creators), and autonomous agents (DID-bearing software actors). Governance operates through a 3-tier model with proposals recorded in the immutable event ledger (no blockchain is involved), votes counted by membership or by locks as each registry is set (the production frames and their cloud operators count by membership), one signed ballot per eligible registry on a federation proposal opened for registry ballots, and Commander veto authority.

---

## Clause 4: Context of the Organization

### 4.1 Understanding the Organization and Its Context

| Aspect | Implementation | Evidence |
|--------|---------------|----------|
| Organization structure | Sole maintainer (Commander ruFFa), full decision authority | `CLAUDE.md` Part 7 |
| Infrastructure | Hetzner FSN1-DC15, Ryzen 9 3900, 128GB ECC, 2x1.92TB NVMe RAID-1 | `PRODUCTION_DOCS/04_DEPLOYMENT/` |
| Production topology | Two sovereign frames (EU and ASIA) and four cloud operators (Amsterdam and Lisbon under EU, Shenzhen and Ho Chi Minh City under ASIA), each with its own registry, TEG and database, plus the frames' EventStores and SPIRE trust roots, Redis, service agents and the monitoring stack | Each frame's and cloud operator's own compose file |
| Domain | `theprotocol.cloud` (API: `api.theprotocol.cloud`; EU: `eu.theprotocol.cloud`; ASIA: `asia.theprotocol.cloud`) | nginx configs, `PRODUCTION_DOCS/04_DEPLOYMENT/` |
| AI components in scope | EigenTrust++, ZKP attestations, <!-- on: staking_rewards -->payout on locked units (switched off on the production frames), <!-- /on -->Collusion Detection, Bayesian Trust, Federation Governance | `PRODUCTION_DOCS/02_ARCHITECTURE/` |
| External context | No regulatory mandates currently binding; voluntary ISO 42001 alignment for market readiness | This document |

**Status**: IMPLEMENTED

### 4.2 Understanding the Needs and Expectations of Interested Parties

| Interested Party | Needs & Expectations | How Addressed |
|-----------------|---------------------|---------------|
| Commander (ruFFa) | Full sovereignty, supply integrity, platform stability | Admin JWT (`is_admin=True`), veto power, more than 90 vmalert alerting rules |
| Developers | Reliable agent onboarding, fair unit accounting, API stability | `PRODUCTION_DOCS/09_DEVELOPER_GUIDES/`, an API test harness covering hundreds of endpoints across ~89 categories plus a federation conformance suite |
| Registry Operators | Federation license, cross-registry trust, economic autonomy | Federation sync (`background_tasks/federation_sync.py`), license key auth |
| Autonomous Agents | Identity (DID), balance integrity, reputation accuracy | `did:theprotocol:*` identities, EigenTrust scores, supply audit |
| Federation Peers | Interoperability, idempotent cross-registry transfers | Idempotent dedup (`xfer-{transaction_id}`), trusted registry whitelist |

**Status**: IMPLEMENTED

### 4.3 Determining the Scope of the AIMS

The AIMS scope covers all AI decision-making components within TheProtocol:

| AI Component | Function | Location |
|-------------|----------|----------|
| EigenTrust++ | Reputation scoring across agent interaction graph | `background_tasks/eigentrust_worker.py` |
| ZKP Attestations | Zero-knowledge proof verification for agent claims | `routers/attestations.py`, `core/zkp_verifier.py` (Barretenberg `bb` UltraHonk over four published Noir policy circuits, v2.0.0) |
<!-- on: staking_rewards -->| Payout on locked units | Payout rate on locked units from network metrics, switched off on the production frames | `routers/staking_enhanced.py`, the payout rate engine |<!-- /on -->
| Collusion Detection | Graph-based detection of coordinated manipulation | `background_tasks/collusion_worker.py` |
| Bayesian Trust | A trust discount for each peer registry: from a neutral Beta(1,1) prior, clean cross-registry settlements raise it, disputes lost against that peer lower it, and inactivity pulls it back toward 0.5; it weights that peer's federation votes, and the peer trust policy reads it | `services/bayesian_trust.py` |
| Federation Governance | Proposal/vote/tally system: votes counted by membership or by locks, and one ballot per eligible registry on a federation proposal opened for registry ballots | `routers/governance.py` |

Excluded from scope: infrastructure monitoring (Prometheus/Grafana), Docker orchestration, nginx reverse proxy, and DNS management. These are operational IT, not AI systems.

**Status**: IMPLEMENTED

### 4.4 AI Management System

The AIMS is documented across:
- This document (`11_COMPLIANCE/ISO_42001_Alignment.md`), the master alignment
- Supporting compliance documents in `PRODUCTION_DOCS/11_COMPLIANCE/`
- The operational doctrine (the primary operational briefing), kept outside the public repository
- The `PRODUCTION_DOCS/` suite covering architecture, operations, API reference, security and compliance

**Status**: IMPLEMENTED. The AIMS is established and maintained: policies are codified as runtime invariants, the eight-document compliance suite is complete and published, and the audit/improvement loop operates continuously. Independent third-party certification has not yet been conducted (a certification step, not a 4.4 documentation gap, tracked on the roadmap).

---

## Clause 5: Leadership

### 5.1 Leadership and Commitment

| Requirement | Implementation | Evidence |
|------------|---------------|----------|
| Top management commitment | Commander is the sole maintainer, architect, and operator; directly authors all AI policy | `CLAUDE.md`, governance veto power |
| Resource allocation | Dedicated Hetzner bare-metal server; the production frames and cloud operators provisioned and maintained on it | Each frame's and cloud operator's own compose file |
| AI policy integration | AI policies enforced at runtime via per-event-type emission policies and a continuous supply auditor | `event_emitter.py`, `background_tasks/supply_auditor.py` |
| Continual improvement | Stress-testing regime (~275 tx/s intra-registry, ~114 tx/s end-to-end under 16 concurrent simulations), governance proposals for parameter changes | `PRODUCTION_DOCS/06_OPERATIONS/Stress_Test_And_Simulation.md` |

**Status**: IMPLEMENTED

### 5.2 AI Policy

TheProtocol's AI policy is codified as enforceable runtime invariants:

| Policy | Enforcement Mechanism | Violation Response |
|--------|----------------------|-------------------|
| Supply integrity (delta = 0.0) | Supply auditor (60s cycle), EventStore projection | `BREACH` status, Alertmanager notification to `SecurityAlerts@theprotocol.cloud` |
| Emission authorization | `event_emission_policies` table (per-event-type policy rows), policy gate in `event_emitter.py` | Unauthorized emission blocked at code level |
| Federation integrity | 8 invariant rules, issuance disabled in federated mode | License revocation = economic quarantine |
| Transfer atomicity | DB-backed 2PC coordination (`coordination_store.py`), idempotent dedup | Failed transfers roll back; no partial state |
| Reputation fairness | EigenTrust convergence criteria, collusion detection | Flagged agents excluded from trust propagation |
| Governance legitimacy | Votes counted by membership or by locks, signed registry ballots, Commander veto, duration enforcement | Invalid votes rejected (403), tallies require quorum |

**Status**: IMPLEMENTED

### 5.3 Organizational Roles, Responsibilities, and Authorities

| Role | Auth Tier | Scope | Evidence |
|------|----------|-------|----------|
| Commander (ruFFa) | Admin JWT (`is_admin=True`) | Full platform control: treasury, emission policies, enforcement, federation licensing | `CLAUDE.md` Part 6 |
| Registry Operator | Federation license key | Own registry operations: fee rates, governance, treasury, agent management | `PRODUCTION_DOCS/03_SERVICES/` |
| Developer | Developer JWT | Agent creation, API key management, dispute filing | `routers/auth_secure.py` |
| Agent | Agent JWT (`client_id` + `client_secret`) | Unit transfers, locks (where a registry enables them), governance voting, A2A payments | `routers/teg_integration.py`, `routers/governance.py` |
| Background Workers | Internal (leader-elected via Redis) | Automated tasks: supply audit, EigenTrust, <!-- on: staking_rewards -->the payout distributor for locked units (switched off on the production frames), <!-- /on -->federation sync | `background_tasks/leader.py` |

**Status**: IMPLEMENTED

---

## Clause 6: Planning

### 6.1 Actions to Address Risks and Opportunities

AI-specific risks are documented in the companion document `Risk_Assessment_Framework.md`. Key risk categories:

| Risk Category | Example Risk | Mitigation | Status |
|--------------|-------------|-----------|--------|
| Supply inflation | Rogue issuance from federated registry | Issuance disabled in federated mode; mainframe EventStore is single source of truth | IMPLEMENTED |
| Reputation manipulation | Sybil attack on EigenTrust scores | Collusion detection worker (`collusion_worker.py`), volume-weighted trust | IMPLEMENTED |
| Governance capture | Single entity accumulating a majority of the voting weight | Commander veto; one vote per member where a registry counts votes by membership (more units never buy more votes); square-root lock weight where it counts by locks; velocity-scaled fees (5% max) | IMPLEMENTED |
| Data integrity | EventStore corruption or tampering | Immutable append-only CQRS ledger, PostgreSQL WAL, RAID-1 NVMe | IMPLEMENTED |
| AI bias in trust scoring | EigenTrust favoring established agents | Uniform pre-trust in EigenTrust++ (a new agent starts from the same share as every other), periodic convergence validation | IMPLEMENTED |
| Payment authorization abuse | Replay or double-spend of A2A payment authorizations | Atomic CONSUMED state on first verify, SHA-256 hashed storage, TTL expiry | IMPLEMENTED |

**Status**: IMPLEMENTED. The risk register is documented in `Risk_Assessment_Framework.md`.

### 6.2 AI Objectives and Planning to Achieve Them

| Objective | Metric | Target | Measurement | Current |
|-----------|--------|--------|-------------|---------|
| Supply integrity | Supply audit delta | 0.0 (zero tolerance) | `GET /api/v1/projections/supply-audit` (60s cycle) | 0.0 |
| Reputation accuracy | EigenTrust convergence | < 0.001 delta between epochs | EigenTrust worker logs, 1h epoch cycle | Converging |
| Transfer reliability | Success rate under load | > 99.9% under sustained load | Stress test suite (16-sim) | 100% (0 errors) |
| Governance participation | Proposal completion rate | > 80% of proposals reach tally | `GET /api/v1/governance/proposals` | Tracked |
| Federation uptime | Peer health check | > 99% availability | `background_tasks/federation_sync.py` + admin topology peer probes | Monitored |
| AI fairness | New agent trust score | Non-zero starting share (uniform pre-trust) | EigenTrust initialization logic | Active |

**Status**: IMPLEMENTED

### 6.3 Planning of Changes

Changes to AI components follow the established deployment pipeline:

1. Code change on host filesystem (`/opt/theprotocol/stack/Agentvault2/AgentVault/`)
2. A new revision of the registry's Alembic migrations if the schema changes
3. Frontend rebuild if UI affected (`npm run build-only` before Docker rebuild)
4. Docker rebuild: `docker compose -f docker-compose.production.yml --env-file .env.production up -d --build <service>`
5. Verification via live API call, container logs, or the full API test suite (650+ endpoints)
6. Session log appended to `sessionlogs2026/`

Formal change management policy documented in `Change_Management_Policy.md`.

**Status**: IMPLEMENTED. The change process is documented in the published `Change_Management_Policy.md` and followed in practice (canary-first fleet rollouts, gated on health + version + supply Δ=0, with one-command rollback). A formal change advisory board is not applicable and is documented as such (sole maintainer).

---

## Clause 7: Support

### 7.1 Resources

| Resource | Specification | Evidence |
|----------|--------------|----------|
| Compute | AMD Ryzen 9 3900 (12C/24T), 128GB ECC DDR4 | Hetzner contract, `PRODUCTION_DOCS/04_DEPLOYMENT/` |
| Storage | 2x1.92TB NVMe RAID-1 (hardware mirror) | Hetzner contract |
| Network | 1 Gbit/s, one public IPv4 address | Hetzner contract |
| Containers | The production frames (EU, ASIA) and cloud operators, each with its own registry, TEG and database, plus the frames' EventStores, Redis, SPIRE, service agents and the monitoring stack | `docker ps` output |
| Utilization | High by design at fleet scale: RAM ~80-90% (working set + page cache), disk ~74%, load avg ~15-28 on 24 threads; capacity plan maintained | Prometheus/Grafana dashboards, `PRODUCTION_DOCS/10_SCALING_ARCHITECTURE/Capacity_Snapshot_2026-05-31.md` |
| Database | PostgreSQL, isolated instances (one per registry and per TEG, plus the frames' EventStores, the sandboxes and monitoring) | `docker ps`, compose files |
| Cache | Redis per registry (each frame and each cloud operator runs its own instance) | `CLAUDE.md` Part 9 |

**Status**: IMPLEMENTED

### 7.2 Competence

| Area | Competence Evidence |
|------|-------------------|
| Full-stack development | The sole maintainer built the entire platform: FastAPI backend, Vue 3 frontend, Docker orchestration |
| AI/ML engineering | In-house implementation of EigenTrust++, ZKP, Bayesian Trust, Collusion Detection |
| Cryptography | SPIFFE/SPIRE mTLS identity fabric, ZKP circuit design, SHA-256 token hashing |
| Infrastructure | Docker estate of the production frames and cloud operators, nginx reverse proxy, Let's Encrypt SSL, CrowdSec/fail2ban |
| Operational | 16-hour sustained engineering sessions documented in session logs |

**Status**: IMPLEMENTED

### 7.3 Awareness

| Audience | Awareness Mechanism | Evidence |
|----------|-------------------|----------|
| Operators | 90+ files in `PRODUCTION_DOCS/`, 7 public documentation pages | `PRODUCTION_DOCS/` directory |
| Developers | API reference (650+ endpoints across ~89 categories), SDK documentation, developer guides | `PRODUCTION_DOCS/05_API_REFERENCE/`, `PRODUCTION_DOCS/09_DEVELOPER_GUIDES/` |
| AI components | The operational doctrine (read before any code change) | Kept outside the public repository |
| Public | Landing page teasers, Services showcase (`/ui#/services`) | Frontend views |

**Status**: IMPLEMENTED

### 7.4 Communication

| Channel | Purpose | Evidence |
|---------|---------|---------|
| Alertmanager | more than 90 vmalert alerting rules to `SecurityAlerts@theprotocol.cloud` | `PRODUCTION_DOCS/07_MONITORING/` |
| WebSocket | Live event broadcast to connected clients (Redis Pub/Sub cross-worker) | Frontend WebSocket integration |
| Prometheus | Metrics collection from all services | `prometheus.theprotocol.cloud` |
| Grafana | Visual dashboards for operational monitoring | `grafana.theprotocol.cloud` |
| Session logs | Append-only record of all engineering sessions | `sessionlogs2026/` |

**Status**: IMPLEMENTED

### 7.5 Documented Information

| Document Category | Location | Count |
|------------------|----------|-------|
| System overview | `PRODUCTION_DOCS/01_SYSTEM_OVERVIEW/` | Multiple |
| Architecture | `PRODUCTION_DOCS/02_ARCHITECTURE/` | Multiple |
| Service documentation | `PRODUCTION_DOCS/03_SERVICES/` | Per-service |
| Deployment guides | `PRODUCTION_DOCS/04_DEPLOYMENT/` | Multiple |
| API reference | `PRODUCTION_DOCS/05_API_REFERENCE/` | 90+ files |
| Operations runbooks | `PRODUCTION_DOCS/06_OPERATIONS/` | Multiple |
| Monitoring | `PRODUCTION_DOCS/07_MONITORING/` | Multiple |
| Security | `PRODUCTION_DOCS/08_SECURITY/` | Multiple |
| Developer guides | `PRODUCTION_DOCS/09_DEVELOPER_GUIDES/` | Multiple |
| Scaling architecture | `PRODUCTION_DOCS/10_SCALING_ARCHITECTURE/` | Multiple |
| Compliance (this suite) | `PRODUCTION_DOCS/11_COMPLIANCE/` | Complete, published in-app at `/compliance` |
| Operational doctrine | `CLAUDE.md` | 1 (continuously maintained) |
| Credentials reference | `PRODUCTION_DOCS/CREDENTIALS_REFERENCE.md` | 1 |

**Status**: IMPLEMENTED. Documented information is created, version-controlled (git), versioned (per-document version headers and changelogs), reviewed (multi-pass accuracy audits recorded in session logs) and published (rendered in-app at `/compliance`). Independent certification is a separate roadmap item, not a 7.5 control gap.

---

## Clause 8: Operation

### 8.1 Operational Planning and Control

| Control | Implementation | Evidence |
|---------|---------------|----------|
| Production manifest | Each frame's and cloud operator's own compose file, with its own env file | Each registry's deployment directory |
| Migration versioning | The registry's Alembic migrations, applied at container startup | `AgentVault/agentvault_registry/alembic/versions/` |
| Leader election | Redis-based single-worker election across 70+ background workers and event reactors | `background_tasks/leader.py` |
| Multi-worker safety | Several worker processes per registry and per TEG, sharing state through Redis (on the production network: 4 gunicorn workers per frame registry and 8 per cloud operator registry; 4 uvicorn workers per frame TEG and 8 gunicorn workers per cloud operator TEG) | Each frame's and cloud operator's compose file, `gunicorn_conf.py` |
| Rate limiting | Redis-backed shared counters across workers | Rate limiter middleware |
| Deployment guard | Bare `docker compose up` intentionally fails (requires `-f` flag) | `CLAUDE.md` Rule 12 |

**Status**: IMPLEMENTED

### 8.2 AI System Lifecycle

Detailed in companion document `AI_System_Lifecycle.md`. Summary:

| AI Component | Development | Deployment | Monitoring | Retirement |
|-------------|------------|-----------|-----------|-----------|
| EigenTrust++ | In-house, networkx graph library | Background task (1h epochs) | Convergence metrics, Prometheus | Version-gated via migration |
| ZKP Attestations | In-house circuits, Barretenberg verifier | API endpoints (`/api/v1/attestations/*`, `/api/v1/circuits/*`) | Verification success/failure rates | Circuit version and verification-key digest pinned |
<!-- on: staking_rewards -->| Payout on locked units | In-house algorithm | Switched off on the production frames (no rate published, nothing paid) | Tier endpoint (`/staking/apy-tiers`, no tiers while switched off) | Parameter changes via governance |<!-- /on -->
| Collusion Detection | In-house graph analysis | Background task | Detection event logging | Threshold tuning via admin |
| Bayesian Trust | In-house statistical model | Per peer registry: updated on each cross-registry settlement and settled federation dispute, decayed daily for inactivity | Per-peer discount values | Discounts reset to 1.0 (`AI_System_Lifecycle.md` §7.9) |
| Federation Governance | In-house proposal/vote/tally | API endpoints (`/governance/*`) | Proposal completion metrics | Governed by own proposals |

**Status**: IMPLEMENTED. The components in scope are operational<!-- on: staking_rewards --> (the payout on locked units where a registry switches it on)<!-- /on -->, and the lifecycle (development, deployment, monitoring, retirement) is documented in the published `AI_System_Lifecycle.md`.

### 8.3 Data Management

| Data Category | Storage | Protection | Retention | Evidence |
|--------------|---------|-----------|-----------|----------|
| Agent identities (DIDs) | PostgreSQL (registry DBs) | Unique constraints, DID format validation | Permanent | `models.py` |
| Unit balances | PostgreSQL (TEG DBs) | Atomic transactions, supply auditor | Permanent | TEG `endpoints_token.py` |
| Event ledger | PostgreSQL (EventStore DB) | Append-only, idempotency keys, RAID-1 | Permanent (immutable) | `agentvault-event-store/` |
| Agent credentials | PostgreSQL | bcrypt-hashed `client_secret` and API keys (an API key also carries a SHA-256 lookup hash) | Permanent (hashed) | `routers/auth_secure.py` |
| Payment authorizations | PostgreSQL | SHA-256 hashed, atomic state transitions, TTL expiry | Until consumed/expired | `routers/a2a_payment.py` |
| Session data | Redis | Per-frame instance isolation with per-service logical DBs, volatile | Session-scoped | Redis config |
| Production secrets | Each registry's own env file | Not committed to source control, readable only by its owner (mode 600) | N/A | `.gitignore` |

Detailed in companion document `Data_Protection_Policy.md`.

Known limitation, stated plainly: block-level disk encryption at rest is **not** enabled: data protection at rest relies on root-only file permissions, container isolation and hashed credential storage (risk register R-OP-08; see `Data_Protection_Policy.md` §7.3 Transfer Safeguards).

**Status**: IMPLEMENTED (with the encryption-at-rest limitation documented above)

### 8.4 Third-Party AI Components

TheProtocol uses no third-party AI models or AI-as-a-service. All of its AI components are built in-house.

| External Dependency | Type | Purpose | Risk Assessment |
|-------------------|------|---------|----------------|
| Barretenberg | ZKP verifier binary (Aztec Protocol) | Proof verification for ZKP attestations | Open-source, deterministic, version-pinned |
| networkx | Python graph library | Graph operations for EigenTrust/Collusion | Open-source, well-audited, no AI decision-making |
| PostgreSQL | Database | Data persistence | Not an AI component |
| Redis | Cache/coordination | Leader election, rate limiting | Not an AI component |

**Status**: IMPLEMENTED. Minimal third-party AI surface area by design.

---

## Clause 9: Performance Evaluation

### 9.1 Monitoring, Measurement, Analysis, and Evaluation

| Monitoring System | Scope | Frequency | Evidence |
|------------------|-------|-----------|----------|
| Supply Auditor | Unit supply invariant (delta = 0.0) | Every 60 seconds | `background_tasks/supply_auditor.py`, `GET /api/v1/projections/supply-audit` |
| EigenTrust Worker | Reputation score convergence | 1-hour epochs | `background_tasks/eigentrust_worker.py` |
| Prometheus | Infrastructure and application metrics | 15s scrape interval | `prometheus.theprotocol.cloud` |
| Grafana | Visual dashboards (CPU, memory, request rates, error rates) | Real-time | `grafana.theprotocol.cloud` |
| Alertmanager | more than 90 alerting rules (vmalert), email to `SecurityAlerts@theprotocol.cloud` | Continuous | Alert rule configs |
| Agent Health Checker + Federation Sync | Agent endpoint health; federation peer availability and card sync | Background task cycles | `background_tasks/agent_health_checker.py`, `background_tasks/federation_sync.py` |
| Velocity Snapshot | Transaction velocity for dynamic fee scaling | Background task cycle | `background_tasks/velocity_snapshot.py` (referenced in `CLAUDE.md`) |
| API Test Suite | 650+ endpoints across ~89 categories | On-demand | API Tester |
| Stress Test | ~275 tx/s intra-registry, ~114 tx/s end-to-end, 16 concurrent simulations | On-demand | `PRODUCTION_DOCS/06_OPERATIONS/Stress_Test_And_Simulation.md` |

**Status**: IMPLEMENTED

### 9.2 Internal Audit

Internal audit procedures are documented in `Compliance_Audit_Procedures.md`. Current practice:

- Supply invariant audit runs continuously (60s cycle) with zero-tolerance breach detection
- The full API test suite (650+ endpoints across ~89 categories) is required to pass
- Stress tests verify system behavior under load (~275 tx/s intra-registry, ~114 tx/s end-to-end)
- Session logs provide complete audit trail of all engineering changes
- CrowdSec, fail2ban, and Lynis provide security audit capability

**Status**: IMPLEMENTED. The audit programme and schedule are documented in the published `Compliance_Audit_Procedures.md` (§2 continuous automated, §3 daily, §4 weekly, §5 monthly, §6 quarterly) and practiced: recent deep-audit records include the user-funds conservation audit (2026-06-09), the shadow-bookkeeping audit (2026-06-10) and the compliance-documentation accuracy audit (2026-06-12), all in `sessionlogs2026/`.

### 9.3 Management Review

| Review Activity | Frequency | Mechanism | Evidence |
|----------------|-----------|-----------|----------|
| Supply audit review | Continuous (automated) | Supply auditor background task | Alertmanager breach notifications |
| Governance proposal review | Per-proposal | Commander reviews all proposals, veto power | `routers/governance.py` |
| Federation health review | Continuous (automated) | Peer health checker + federation sync | Background task logs |
| Security review | On-demand | CrowdSec alerts, fail2ban status, Lynis audit | `monitor-security.sh` |
| Performance review | On-demand | Grafana dashboards, Prometheus queries | `grafana.theprotocol.cloud` |

**Status**: IMPLEMENTED. Automated reviews active; formal management review meeting cadence not applicable (sole maintainer).

---

## Clause 10: Improvement

### 10.1 Nonconformity and Corrective Action

Incident classification and response procedures are documented in `Incident_Response_Procedures.md`. Summary:

| Priority | Definition | Response Time | Example |
|----------|-----------|---------------|---------|
| P1 (Critical) | Supply invariant breach, data loss, complete service outage | Immediate | Supply audit `BREACH` status |
| P2 (High) | AI component failure, federation desync, payment system error | < 1 hour | EigenTrust convergence failure |
| P3 (Medium) | Single agent service outage, non-critical background task failure | < 4 hours | Service agent container crash |
| P4 (Low) | Documentation gap, cosmetic UI issue, non-critical metric anomaly | < 24 hours | Grafana dashboard misconfiguration |

Corrective action workflow: Detection (automated monitoring) -> Investigation (container logs, DB queries) -> Fix (code change, migration) -> Verification (live API call, test suite) -> Documentation (session log).

**Status**: IMPLEMENTED. Procedures are documented in the published `Incident_Response_Procedures.md` (P1-P4 classification, containment, post-incident review) and exercised in practice (incident records in `sessionlogs2026/`).

### 10.2 Continual Improvement

| Improvement Mechanism | Implementation | Evidence |
|----------------------|---------------|----------|
| Stress testing | Validated to ~275 tx/s intra-registry and ~114 tx/s end-to-end under 16 concurrent simulations | `PRODUCTION_DOCS/06_OPERATIONS/Stress_Test_And_Simulation.md` |
| Governance proposals | Parameter-change proposals recorded in the immutable event ledger, with agent voting | `routers/governance.py` |
| Migration versioning | Incremental schema evolution (the registry's Alembic migrations) | Alembic versions directory |
| Feature flags | Emission policies (32 types), projection snapshots toggle | `event_emission_policies` table, `ENABLE_PROJECTION_SNAPSHOTS` env var |
| Session logging | Every engineering session documented with changes and outcomes | `sessionlogs2026/` |

**Status**: IMPLEMENTED. Improvement mechanisms are active and the review cycle is documented (`Compliance_Audit_Procedures.md` §6 quarterly audits and §12 policy review). Practice exceeds the documented cadence: every engineering session produces logged improvements (`sessionlogs2026/`, `CLAUDE.md` changelog).

---

## Gap Analysis Summary

| Clause | Requirement | Status | Evidence | Gap |
|--------|-------------|--------|----------|-----|
| 4.1 | Organization context | IMPLEMENTED | `CLAUDE.md`, this document | None |
| 4.2 | Interested parties | IMPLEMENTED | Stakeholder analysis above | None |
| 4.3 | AIMS scope | IMPLEMENTED | 6 AI components documented | None |
| 4.4 | AIMS documentation | IMPLEMENTED | `PRODUCTION_DOCS/`, `11_COMPLIANCE/` suite published | None |
| 5.1 | Leadership commitment | IMPLEMENTED | Commander sole authority | None |
| 5.2 | AI policy | IMPLEMENTED | Runtime invariants, emission policies | None |
| 5.3 | Roles and responsibilities | IMPLEMENTED | 4-tier auth model | None |
| 6.1 | Risk assessment | IMPLEMENTED | Published risk register (`Risk_Assessment_Framework.md`) + active mitigations | None |
| 6.2 | AI objectives | IMPLEMENTED | Measurable metrics with targets | None |
| 6.3 | Planning of changes | IMPLEMENTED | Published `Change_Management_Policy.md` + gated canary-first rollouts | None |
| 7.1 | Resources | IMPLEMENTED | Hetzner dedicated server, production frames and cloud operators | None |
| 7.2 | Competence | IMPLEMENTED | Sole maintainer's full-stack expertise | None |
| 7.3 | Awareness | IMPLEMENTED | 90+ documentation files, public pages | None |
| 7.4 | Communication | IMPLEMENTED | Alertmanager, WebSocket, Prometheus | None |
| 7.5 | Documented information | IMPLEMENTED | Version-controlled, versioned, published in-app | None |
| 8.1 | Operational planning | IMPLEMENTED | Docker Compose, migrations, leader election | None |
| 8.2 | AI system lifecycle | IMPLEMENTED | Published `AI_System_Lifecycle.md`; all components operational | None |
| 8.3 | Data management | IMPLEMENTED | Per-category protections documented | None |
| 8.4 | Third-party AI | IMPLEMENTED | Minimal: Barretenberg, networkx only | None |
| 9.1 | Monitoring | IMPLEMENTED | 9 monitoring systems active | None |
| 9.2 | Internal audit | IMPLEMENTED | Published audit programme (`Compliance_Audit_Procedures.md` §§2-6) + audit records | None |
| 9.3 | Management review | IMPLEMENTED | Automated + Commander review | None |
| 10.1 | Nonconformity | IMPLEMENTED | Published `Incident_Response_Procedures.md` + incident records | None |
| 10.2 | Continual improvement | IMPLEMENTED | Documented review cycle + per-session improvement records | None |

**Summary**: 22 IMPLEMENTED, 0 PARTIAL, 0 MISSING (self-assessed). Outstanding items sit outside the clause table: independent third-party certification (roadmap) and the disk-encryption-at-rest hardening gap (risk register R-OP-08, documented under 8.3).

---

## Cross-References

### Companion Documents (11_COMPLIANCE/)

| Document | Purpose | Status |
|----------|---------|--------|
| `ISO_42001_Alignment.md` | This document: master alignment | Published v2.3.2 |
| `Risk_Assessment_Framework.md` | AI-specific risk register (Clause 6.1) | Published v2.2.3 |
| `AI_System_Lifecycle.md` | Lifecycle management for 6 AI components (Clause 8.2) | Published v2.2.1 |
| `Data_Protection_Policy.md` | Data classification and protection (Clause 8.3) | Published v2.2.3 |
| `Change_Management_Policy.md` | Change advisory and deployment process (Clause 6.3) | Published v2.1.2 |
| `Compliance_Audit_Procedures.md` | Internal audit schedule and procedures (Clause 9.2) | Published v2.2.2 |
| `Incident_Response_Procedures.md` | P1-P4 incident classification and response (Clause 10.1) | Published v2.1.2 |
| `Jurisdiction_Profiles.md` | Declared, enforced and attested feature scope per deployment | Published (revised 2026-10-03) |

All eight documents are rendered in-app at `/compliance` (public).

### Key PRODUCTION_DOCS References

| Document | Relevance |
|----------|-----------|
| `PRODUCTION_DOCS/01_SYSTEM_OVERVIEW/` | Organization context (Clause 4) |
| `PRODUCTION_DOCS/02_ARCHITECTURE/` | AI component architecture (Clauses 4.3, 8.2) |
| `PRODUCTION_DOCS/03_SERVICES/` | Service documentation (Clauses 7.3, 8.1) |
| `PRODUCTION_DOCS/04_DEPLOYMENT/` | Infrastructure resources (Clause 7.1) |
| `PRODUCTION_DOCS/05_API_REFERENCE/` | API documentation, 90+ files (Clause 7.5) |
| `PRODUCTION_DOCS/06_OPERATIONS/` | Operational procedures, stress testing (Clauses 8.1, 10.2) |
| `PRODUCTION_DOCS/07_MONITORING/` | Monitoring configuration (Clause 9.1) |
| `PRODUCTION_DOCS/08_SECURITY/` | Security controls (Clauses 5.2, 6.1) |
| `PRODUCTION_DOCS/CREDENTIALS_REFERENCE.md` | Auth tier documentation (Clause 5.3) |

### Key Source Files

| File | Relevance |
|------|-----------|
| `CLAUDE.md` | Operational doctrine: rules, architecture, credentials (Clauses 4-5) |
| Each frame's and cloud operator's compose file | Production container manifests (Clause 8.1) |
| `AgentVault/agentvault_registry/src/agentvault_registry/event_emitter.py` | Emission policy gate (Clause 5.2) |
| `AgentVault/agentvault_registry/src/agentvault_registry/background_tasks/supply_auditor.py` | Supply invariant audit (Clause 9.1) |
| `AgentVault/agentvault_registry/src/agentvault_registry/background_tasks/eigentrust_worker.py` | EigenTrust AI component (Clause 8.2) |
| `AgentVault/agentvault_registry/src/agentvault_registry/background_tasks/collusion_worker.py` | Collusion detection AI component (Clause 8.2) |
| `AgentVault/agentvault_registry/src/agentvault_registry/routers/governance.py` | Governance AI component (Clause 8.2) |
| `agentvault-event-store/src/services/projections.py` | EventStore projections, supply audit endpoint (Clause 9.1) |

### Key API Endpoints

| Endpoint | Relevance |
|----------|-----------|
| `GET /api/v1/projections/supply-audit` | Supply invariant verification (Clause 9.1) |
| `GET /api/v1/admin/event-emission-policies` | Emission policy management (Clause 5.2) |
| `POST /api/v1/admin/projection-snapshot` | Projection baseline snapshots (Clause 9.1) |
| `GET /api/v1/governance/proposals` | Governance monitoring (Clause 9.3) |
<!-- on: staking_rewards -->| `GET /api/v1/staking/apy-tiers` | Payout disclosure: no tiers while payouts on locked units are switched off, as on the production frames (Clause 8.2) |<!-- /on -->

---

*End of ISO/IEC 42001:2023 Alignment Document*
*TheProtocol: Sovereign AI Agent Orchestration Platform*
*Assessment: 22/22 sub-clauses IMPLEMENTED (self-assessed; independent certification pending; known hardening gap: disk encryption at rest, R-OP-08)*

---

_v2.0.0 (2026-06-12): accuracy overhaul — corrected topology (16 federated registries, ~280 containers), API/stress/alert figures, file paths, the ZKP and lock mechanisms, and the self-assessment framing to the live system._

_v2.1.0 (2026-06-12): false-gap audit — all 8 former PARTIAL sub-clauses upgraded to IMPLEMENTED: each cited as its gap a "formal document" that this suite itself published (6.1, 6.3, 8.2, 10.1), an audit schedule that `Compliance_Audit_Procedures.md` §§2-6 already defines (9.2, 10.2), or conflated independent certification with a documentation requirement (4.4, 7.5). Also corrected stale infrastructure figures (utilization, container/instance counts, worker model — gunicorn-supervised since V0041/V0049) and a non-existent file reference (`peer_health_checker.py` → `agent_health_checker.py`/`federation_sync.py`). The remaining honest caveats: self-assessed (no independent audit yet) and no block-level disk encryption at rest (risk register R-OP-08). Not legal advice._

_v2.2.0 (2026-10-03): wording follows the live network and the agreed public terms: the platform's units named as units (ECU on EU, ACU on ASIA), the production network named as the EU and ASIA frames with four cloud operators, votes counted by membership or by locks as each registry is set, and every surface that is switched off on the production frames named as switched off; the companion table carries the current versions and lists the eighth document. Self-assessed; not independently audited._

_v2.3.0 (2026-10-13): the ZKP rows name UltraHonk, the four v2.0.0 policy circuits and the real endpoints. Self-assessed; not independently audited._

_v2.3.1 (2026-10-16): the text without em dashes (the gap table's empty cells read None and its empty sub-clause column is gone); the maintainer named as the sole maintainer, not a founder; the production topology, manifests, worker counts and secrets named as the EU and ASIA frames and their four cloud operators run them, in place of the retired first frames' files; the Sybil mitigation named as volume-weighted trust (EigenTrust weights by transaction volume, and locks are switched off on the production frames); the retired PPAO dashboard removed from the public channels; the companion table carries the current versions. Self-assessed; not independently audited._

_v2.3.2 (2026-10-17): the Bayesian trust component described as the released software runs it (a discount for each peer registry, weighting its federation votes and read by the peer trust policy), and new-agent fairness as EigenTrust++'s uniform pre-trust; the operational doctrine named as kept outside the public repository; schema versions named as the registry's Alembic migrations; the credential hashes as the released software keeps them; the encryption-at-rest reference points at the Data Protection Policy's §7.3; the companion table carries the current versions. Self-assessed; not independently audited._

_v2.3.3 (2026-10-17): the alerting rules counted as vmalert evaluates them (more than 90; Prometheus only scrapes) in the stakeholder table and the two monitoring rows. Self-assessed; not independently audited._
