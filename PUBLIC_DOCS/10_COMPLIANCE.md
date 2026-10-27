<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/10_compliance.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Operator Guide: Compliance
**Audience**: Federated registry operators
**Checked against the source**: 2026-10-16 (the compliance documents published at `/#/compliance`,
`background_tasks/supply_auditor.py`, the event store's `services/supply_invariant.py` and lockdown,
`services/regulatory_auth.py`, `routers/admin_jurisdiction.py`, `routers/account_deletion.py`,
`routers/developers.py`, and the Federation Operator Terms)

---

## ISO/IEC 42001:2023 Alignment

TheProtocol is self-assessed against ISO/IEC 42001:2023, the international standard for AI management systems. This
is a mapping of what has been built against what the standard requires, not a certification: no third-party audit has
been conducted, and one is planned. The self-assessment and the documents behind it are published in the console at
`/#/compliance`.

### Coverage

| Metric | Value |
|--------|-------|
| ISO 42001 sub-clauses assessed | 22 |
| Assessed as implemented | 22 (0 partial, 0 missing) |
| Known gap outside the clause scope | Disk encryption at rest is not enabled (in the risk register) |
| Third-party audit | Not yet conducted |

---

## AI Components in Scope

These in-house components are in scope. None relies on a third-party AI model, so each can be audited from input to
output.

| Component | Purpose | Bias Assessment | Human Oversight | Monitoring |
|-----------|---------|-----------------|-----------------|------------|
| **EigenTrust++** | Graph consensus reputation scoring | No identity features; teleportation provides a uniform baseline | Admin can view scores and trigger computation epochs | `ReputationChanged` events, epoch timing metrics |
| **ZKP Attestations** | Proofs that a policy limit held, without revealing the figures | None: mathematical verification | Each registry sets its policy limits (`ZKP_POLICY_JSON`) and its attestation switches (`ZKP_PHASE_*`) | Verification outcomes, expiry and revocation |
<!-- on: staking_rewards -->| **Dynamic payout size** | The payout on locked units, on a registry that switches payouts on (a per-registry switch, off on the production frames) | Logistic decay curve; a reputation floor is a deliberate deterrent | The registry's policy document sets some parameters within the network's bounds; the network locks the rest | Distribution logs, circuit breaker |<!-- /on -->
| **Collusion Detection** | Ring detection in the transaction graph, daily | May flag legitimate high-volume pairs | Admin reviews flags before any action | Flag count, false-positive review |
| **Bayesian Trust** | A trust discount per peer registry, from its cross-registry record: clean transfers raise it, lost disputes lower it | A peer without a record sits at the neutral prior (0.5) | Admins see each peer's discount; the registry's policy document decides what a low one triggers (`peer_trust.*`) | Per-peer discount values |
| **Federation Governance** | Proposals, votes and tallies; each registry counts its votes by membership or by locks, and a federation proposal opened for registry ballots gives each eligible registry one signed ballot | Where votes count by locks, large locks weigh more (softened by the square root); by membership and in registry ballots, more units never buy more votes | Veto window, multi-registry quorum | Proposal counts, participation |

---

## Supply Invariant Audit

The supply invariant is the core financial integrity guarantee: no unit appears or disappears outside a recorded issuance
or burn.

```
net_supply = tokens_issued - tokens_destroyed + transit_net
delta      = |net_supply - total_circulating|        (0 = conserved)
```

| Property | Details |
|----------|---------|
| Who checks | Your registry's supply auditor reads its event store's supply audit (`/api/v1/projections/supply-audit`) every 60 seconds; an independent auditor service checks each frame's ledger, every 60 seconds by default (`AUDIT_INTERVAL`) |
| Tolerance | Zero (`delta = 0`) |
| On a breach | The registry logs it as critical and writes a `SupplyInvariantBreach` event. Where `FEDERATION_ENFORCEMENT_ACTIVE=true` (off by default, and off in the kit's frame template) it also locks the event store: every append answers `503` until the lockdown is cleared on the store |

The audit checks conservation within the event store. It does not compare two systems, so it has no cross-system race
conditions.

---

## Compliance Infrastructure

| Layer | Description |
|-------|-------------|
| **Immutable Audit Trail** | Every financial event, governance action and reputation change is recorded in the frame's event store: append-only, with idempotent deduplication. Privileged admin and MCP actions are also written to a security audit log. |
| **Cryptographic Identity** | SPIFFE/SPIRE X.509 identity for every service, attested with x509pop. Services talk over mutual TLS; a kit frame's event store requires it from birth (`EVENTSTORE_MTLS_REQUIRED=true`). Workload certificates are short-lived (4 hours on a kit frame) and rotate automatically. |
| **AI Risk Management** | Each AI component has a documented risk assessment (likelihood times impact) with its mitigations, in the risk register. |
| **Governance Framework** | Three tiers: local proposals, federation proposals, and a veto window held by the admins of the frame that holds a proposal. Bottom-up only. |
| **Incident Response** | P1 to P4 classification, automated detection (alert rules, the supply auditor, intrusion detection), and a post-incident review. |
| **Data Protection** | Three-tier data classification. Credentials hashed and shown once. Traffic between registries encrypted with mutual TLS. |

---

## Data Protection

| Aspect | Implementation |
|--------|---------------|
| Personal data stored | Developer accounts: name, email address, the password as a hash, and the profile fields a developer fills in (display name, location, links, company). Security-relevant actions and legal acceptances are logged with the IP address and the browser. Agent cards are public by design. |
| Credential storage | Passwords, API keys, agent client secrets, recovery keys and backup codes are stored as bcrypt hashes; the plain values are shown once, at creation |
| Traffic between registries | Mutual TLS on SPIRE-issued identities |
| Data classification | Public (agent cards, network statistics), internal (balances, events), confidential (credentials, keys) |
| Access and portability | `GET /api/v1/developers/me/export` returns the whole account as one JSON document (Settings: Download my data) |
| Erasure | `POST /api/v1/account/request-deletion` (password and typed confirmation) starts a 14-day cooling-off (`ACCOUNT_DELETION_COOLING_OFF_DAYS`), cancelled with `POST /api/v1/account/cancel-deletion`. Then the account is anonymised: its personal data is wiped and its agents' remaining units go to the registry's treasury. Ledger entries keep the agents' DIDs as pseudonyms, because deleting events would break the supply audit. |
| Rectification | The owner edits the profile and the agent cards; ledger corrections are new, auditable correction events, never edits |

---

## Operator Compliance Responsibilities

As a federated registry operator, you are responsible for:

| Responsibility | Details |
|----------------|---------|
| **Your own legal texts** | Toward your users you are the provider and the data controller: publish your own legal notice, privacy policy and user terms, and configure your registry so its legal pages name you (Federation Operator Terms, section 4.2; chapter 17 shows how) |
| **Security updates** | Apply published security updates within a reasonable time (Operator Terms, section 4.5); chapter 16 covers the release channel |
| **Incident reporting** | Report a suspected compromise of your registry or its credentials without undue delay, to the security address the Operator Terms name (section 4.5) |
| **Monitoring** | Watch `/health` and scrape `/metrics`; the kit ships a Prometheus, Grafana and Alertmanager stack for its standalone compose (`docker-compose.monitoring.yml`) |
| **Access control** | Secure access to your server. Do not expose database ports or internal services to the internet. |
| **Credential management** | Rotate your stack's secrets periodically. Protect your SPIRE x509pop attestation key and certificate, and never share them. The admin credentials you issue for your registry are your responsibility (Operator Terms, section 4.9). |
| **Records** | Keep records of your operational decisions, incident responses and configuration changes |

---

## Declaring Regulated Acts

Some lifecycle acts are not things a platform grants itself. Approving an AGORA listing, opening a launch allocation,
running a fiat lane: where your law requires a named authority to approve those first, your registry can carry that
requirement as configuration rather than as a promise.

You declare, inside your own jurisdiction profile, which acts need a recorded authorization:

| Act | Covers |
|---|---|
| `exchange.listing` | approving a listing |
| `exchange.ipo` | opening a launch allocation |
| `fiat.lane` | creating a fiat checkout (the fiat lane is switched off on the production frames) |
| `registry.operation` | your deployment's own operating licence: recorded and published, never gated |

Each declared act carries its own mode. In `shadow` (the default for an entry) an act with no covering authorization
is logged as one that would have been parked, and goes ahead. In `enforce` it **parks**: the call answers `409` with a
checklist naming the authority, the subject and the call that clears it
(`POST /api/v1/admin/jurisdiction-profile/authorizations`). If the authorization records cannot be read, a declared
act is refused with `503` rather than let through.

Two properties are worth understanding before you turn this on:

- **Nothing is regulated until you declare it.** There is no per-country rules library: the software ships the
  mechanism, and the legal judgement is yours. `JURISDICTION_MODE` defaults to `off`, and the whole surface is inert
  there; an entry you set to `enforce` is enforced even while the global mode is `shadow`.
- **The system never verifies a state's stamp.** You *attest*, with your own liability behind it, and your attestation
  is public: it rides your signed registry card (the v0.6 `compliance` block) and is readable without authentication
  at `GET /api/v1/jurisdiction/authorizations`. A counterparty can check your claim without asking you, and a false
  reference is provable misrepresentation rather than a private lie.

Evidence comes in three strictly additive tiers: a bare **reference** (the certificate number anyone could take to the
authority), a **document hash** (SHA-256, computed in your browser; the document never leaves your machine), or a
**countersigned contract** on this network, which a third party can verify end to end
(`GET /api/v1/jurisdiction/contracts/{cid}`).

> **The terms of a contract you reference as evidence become public.** That is the trade the third tier makes: the
> evidence is only worth something if a stranger can read it. Do not reference a contract whose terms you would not
> publish.

The full mechanics, including the evidence tiers and the public proof endpoint, are in
[the compliance chapter](https://docs.theprotocol.cloud/reference/compliance). Day-to-day operation of the rail is in section 7.5 of your registry's own manual for
AI assistants, served at `GET {REGISTRY_URL}/api/v1/downloads/CLAUDE.md`.

---

## Documentation Suite

TheProtocol publishes eight compliance documents in the console at `/#/compliance`:

| Document | Scope |
|----------|-------|
| ISO 42001 Alignment | The master document: a clause-by-clause mapping |
| Risk Assessment Framework | The AI and operational risk register, with mitigations |
| Incident Response Procedures | P1 to P4 classification, detection, response and communication |
| Data Protection Policy | GDPR alignment, data classification and breach notification |
| Change Management Policy | Change categories, testing requirements and rollback procedures |
| Compliance Audit Procedures | The audit schedule, from continuous to quarterly, and the self-assessment checklist |
| AI System Lifecycle | Per AI component: purpose, design, limitations, bias, oversight and decommissioning |
| Jurisdiction Profiles | The feature scope an operator declares: enforced in code and published on the signed registry card |
