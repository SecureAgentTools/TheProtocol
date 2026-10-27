# Data Protection Policy

| Field       | Value                          |
|-------------|--------------------------------|
| Version     | 2.2.3                          |
| Status      | DRAFT: self-assessment (not independently audited) |
| Date        | 2026-10-17                     |
| Owner       | Commander ruFFa                |
| Review Cycle| Quarterly                      |

---

## 1. Purpose

This policy defines how TheProtocol classifies, processes, stores, and protects data across the sovereign AI agent orchestration platform. It applies to all data processed by production registries, TEG layers, the EventStore, identity fabric, and federated peer registries.

---

## 2. Scope

This policy covers:
- All data processed by the frames and cloud operators the provider runs (the current set is on the public status page), and any federated peer registries
- TEG Layer financial data (balances, transfers, lock positions)
- EventStore immutable event ledger
- SPIRE/SPIFFE identity material
- Developer accounts, agent identities, and governance records
- Monitoring and alerting data (Prometheus, Grafana, Alertmanager)

---

## 3. Data Classification

### 3.1 PUBLIC

Data freely accessible without authentication. Exposure carries no confidentiality risk.

| Data Type              | Examples                                              | Access Method                    |
|------------------------|-------------------------------------------------------|----------------------------------|
| Agent cards            | Name, description, capabilities, A2A endpoint URL     | GET /api/v1/agents/              |
| Decentralized IDs      | `did:theprotocol:xxxx-xxxx-xxxx-xxxx`                 | Agent discovery endpoints        |
| Governance proposals   | Title, description, vote counts, status                | GET /api/v1/governance/proposals |
| Network statistics     | Registry and agent counts, network health, last sync time | GET /api/v1/federation/network-stats |
<!-- on: staking_rewards -->| Payout tiers (locked units) | None while payouts on locked units are switched off: the production frames answer an empty tier list | GET /api/v1/staking/apy-tiers    |<!-- /on -->
| Registry operator info | Operator name, location (self-declared), registry URL  | GET /api/v1/agents/locations/    |

### 3.2 INTERNAL

Data accessible only to authenticated developers or agents. Exposure may compromise operational integrity or financial privacy.

| Data Type              | Examples                                              | Access Control                   |
|------------------------|-------------------------------------------------------|----------------------------------|
| Unit balances          | Liquid balance, locked balance, voting weight          | Agent JWT (own balance only)     |
| Transaction events     | TokensTransferred, TransactionFeeCollected             | EventStore (internal network)    |
| Transfer history       | Sender DID, recipient DID, amount, timestamp           | Agent JWT (own transactions)     |
| Reputation scores      | EigenTrust score (0-1000), trust graph edges           | Agent JWT (own score), Admin     |
| Lock positions         | Lock ID, amount, lock period, unlock timestamp         | Agent JWT (own positions)        |
| Dispute records        | Complainant, defendant, description, resolution        | Agent JWT (own disputes), Admin  |
| Audit flag logs        | Collusion flags, Bayesian trust discounts              | Admin only                       |
| Federation sync data   | Peer registry agent cards, health status               | Internal service-to-service      |

### 3.3 CONFIDENTIAL

Data whose exposure would compromise system security or enable unauthorized access. Maximum protection required.

| Data Type              | Storage Method                                        | Access                           |
|------------------------|-------------------------------------------------------|----------------------------------|
| Developer passwords    | bcrypt hash (never stored in plaintext)                | Auth endpoint only (form-encoded)|
| API keys               | bcrypt hash and a SHA-256 lookup hash (plaintext shown once at creation) | Developer who created it (once)  |
| Agent client secrets   | bcrypt hash (plaintext shown once at onboarding)       | Developer who onboarded (once)   |
| Federation license keys| SHA-256 hash                                           | Registry operator (once)         |
| JWT signing secrets    | Environment variable (each registry's own env file, mode 600) | Container runtime only           |
| TEG admin API key      | Environment variable (each registry's own env file, mode 600) | TEG containers only              |
| SPIRE SVIDs            | Short-lived X.509 SVIDs, rotated automatically (cert-writers refresh roughly every 300s); JWT SVIDs are short-lived (minutes)   | SPIRE agent workload API         |
| Database passwords     | Environment variable (each registry's own env file, mode 600) | Container runtime only           |
| TLS private keys       | File system (SPIRE agent, cert-writer volumes)         | Container volume mounts          |
| A2A payment authorizations | SHA-256 hash (plaintext shown once at authorization)   | Caller agent (once)              |

---

## 4. Processing Purposes

TheProtocol processes personal and operational data for the following purposes:

| Purpose                         | Legal Basis (GDPR)          | Data Categories Used                  |
|---------------------------------|-----------------------------|---------------------------------------|
| Agent identity management       | Contract (Art. 6(1)(b))     | DIDs, agent cards, developer accounts |
| Unit ledger operations          | Contract (Art. 6(1)(b))     | Balances, transfers, fees, locks      |
| Governance voting               | Legitimate interest (Art. 6(1)(f)) | Proposals, votes, voting weight (membership or locks) |
| Federation synchronization      | Legitimate interest (Art. 6(1)(f)) | Agent cards, peer registry status |
| Reputation computation          | Legitimate interest (Art. 6(1)(f)) | Transaction graph, dispute outcomes |
| Dispute resolution              | Contract (Art. 6(1)(b))     | Dispute records, evidence, outcomes   |
| Security monitoring             | Legitimate interest (Art. 6(1)(f)) | Access logs, rate limiting, alerts |
| Supply invariant audit          | Legitimate interest (Art. 6(1)(f)) | All financial events (aggregate)  |

---

## 5. Data Retention

| Data Type                  | Retention Period                          | Rationale                                    |
|----------------------------|-------------------------------------------|----------------------------------------------|
| EventStore events          | Immutable, append-only, never deleted     | CQRS ledger integrity; supply audit depends on complete history |
| Credentials (passwords)    | Until account deletion or password change | bcrypt hashed; old hashes overwritten        |
| API keys                   | Until the account is deleted              | bcrypt hashed; revocation deactivates the key, account deletion deletes it |
| JWT sessions               | Configurable TTL (default 24h)            | Short-lived; no server-side session storage  |
| Agent data                 | Persistent until account deletion request | Required for DID resolution and federation   |
| Federation sync cache      | Incremental with 60-second buffer         | Stale entries overwritten on next sync cycle |
| SPIRE SVIDs                | 4h X509 TTL / 5m JWT TTL, cert-writers rotate every 300s   | Short-lived by design; no long-term storage  |
| Prometheus metrics         | 30 days hot, 60 days cold (VictoriaMetrics) | Operational metrics only; no personal data   |
| Docker container logs      | Rotated per Docker daemon config          | Operational debugging only                   |
| Security audit logs        | Persistent (security_audit_logs table)    | Required for compliance review               |
| A2A payment authorizations | Until consumed, expired, or released      | SHA-256 hashed; expiry worker cleans stale   |

---

## 6. Data Subject Rights

### 6.1 Right of Access (Art. 15)

Developers can access their data via authenticated API endpoints:
- The whole account as one JSON document: `GET /api/v1/developers/me/export` (developer login; Settings: Download my data)
- Account details: `GET /api/v1/developers/me` (developer login)
- Agent data: `GET /api/v1/agents/by-did/{did}`
- Balances: `GET /api/v1/teg/balance` (agent JWT)
- Transaction history: `GET /api/v1/teg/transactions` (agent JWT)
- Reputation: `GET /api/v1/reputation/{did}/trust-score` (developer login)

### 6.2 Right to Erasure (Art. 17)

- **Developer account deletion**: `POST /api/v1/account/request-deletion` (the typed confirmation `DELETE MY ACCOUNT` and the password) starts a 14-day cooling-off period (a registry setting, `ACCOUNT_DELETION_COOLING_OFF_DAYS`); `POST /api/v1/account/cancel-deletion` keeps the account within it. Then the account is anonymised, not removed: the personal fields of the developer record are cleared in place (the record stays as the reference of the records that must be kept), API keys and webhooks are deleted, the agents are revoked, their cards are reduced to the DID and capabilities and marked inactive, and the agents' unlocked units go to the registry's treasury. A request is refused (409) while a purchase is pending, while a dispute is open, or while the account runs a registry that has active peer registries.
- **Limitation**: EventStore events are immutable by design. Deletion of individual events would break the supply invariant and is not supported. Agent DIDs referenced in historical events remain as pseudonymous identifiers.

### 6.3 Right to Data Portability (Art. 20)

- **Agents stay on their registry**: an agent, its DID and its locks stay on the registry that registered it. A cross-registry transfer (`POST /api/v1/teg/cross-registry-transfer`) moves units to an agent on another registry; it does not move the agent.
- **Data export**: `GET /api/v1/developers/me/export` returns the whole account as one JSON document (Settings: Download my data); each agent's card exports separately.

### 6.4 Right to Explanation

- **EigenTrust scores**: `GET /api/v1/reputation/{did}/trust-score` (developer login) returns the agent's global trust, its similarity score, the integer projection used elsewhere and the epoch it was computed in; `GET /api/v1/reputation/{did}/trust-graph` the trust relationships behind it.
- **Collusion flags**: Agents flagged by the auditor can request explanation via dispute resolution process.
<!-- on: staking_rewards -->- **Payout rate on locked units**: the payout formula is documented and deterministic (no opaque ML model), and payouts on locked units are switched off on the production frames.<!-- /on -->

### 6.5 Right to Rectification (Art. 16)

- Agent card metadata (name, description, capabilities) can be updated by the owning developer.
- Financial data (balances, events) cannot be rectified due to immutable ledger design. Corrections are handled via `BalanceCorrected` events that create an auditable correction trail.

---

## 7. Cross-Border Data Transfers

### 7.1 Federation Architecture

All of TheProtocol's own registries (the frames and cloud operators listed on the public status page) run on a single dedicated Hetzner bare-metal server in **FSN1-DC15, Falkenstein, Germany (EU)**. Physical data residency for the platform's own infrastructure is therefore Germany/EU. An operator's *self-declared* location (for example, the EU frame declares Brussels, Belgium, and the ASIA frame declares Singapore) is a display attribute used for the network map; it is not where the data physically resides.

What the federation model enables is jurisdictional diversity for *third parties*: an independent operator may run their own registry under a federation license, on their own hardware, in their own country and under their own applicable law. In that case the third-party operator, not TheProtocol, is the controller of the data on their server.

Federation sync replicates agent cards (PUBLIC data) between registries. All federation traffic is encrypted via mTLS using SPIRE-issued SVIDs.

### 7.2 Data Sovereignty

Each registry operator controls:
- Their own database (PostgreSQL instance)
- Their own server infrastructure
- Their own jurisdiction and applicable law
- Which agents they host and which peers they federate with

Federated registries write events to their home frame's mainframe EventStore. The platform's own EventStores are hosted in the EU (Hetzner, FSN1-DC15, Germany).

### 7.3 Transfer Safeguards

| Safeguard                        | Implementation                                        |
|----------------------------------|-------------------------------------------------------|
| Encryption in transit            | mTLS via SPIRE-issued X.509 SVIDs, short-lived and rotated automatically (cert-writers refresh roughly every 300s) |
| Encryption at rest               | Data resides on RAID-1 NVMe protected by OS-level (root-only) file permissions and container isolation; full-disk block-level encryption is not currently enabled: this is the platform's one acknowledged hardening gap, tracked as risk R-OP-08 with LUKS evaluation planned (M-OP-08a). Credentials are stored hashed regardless of disk state (bcrypt for passwords, API keys and agent client secrets; an API key also carries a SHA-256 lookup hash). |
| Access control                   | Federation license key required for all cross-registry operations |
| Data minimization                | Federation sync transfers only PUBLIC agent card data  |
| Revocation                       | Federation license can be revoked, triggering economic quarantine |

### 7.4 Location Declaration

Registry operator location is currently self-declared. Jurisdiction-binding verification (e.g., via IP geolocation or notarized attestation) is planned for a future release.

---

## 8. Data Protection Impact Assessment (DPIA)

### 8.1 When Required

A DPIA must be conducted before:
- Adding a new AI/ML component to the platform
- Introducing a new data processing purpose not listed in Section 4
- Changing cross-border data flow scope (new federation peer in new jurisdiction)
- Processing new categories of personal data
- Deploying automated decision-making that affects agent access or balances

### 8.2 DPIA Template

| Section            | Content Required                                                |
|--------------------|-----------------------------------------------------------------|
| Purpose            | What processing activity and why                                |
| Necessity          | Why this processing is required (no less invasive alternative)  |
| Proportionality    | Data minimization: only what is needed                          |
| Risks              | Risks to data subjects (unauthorized access, bias, errors)      |
| Mitigations        | Technical and organizational measures to reduce identified risks |
| Consultation       | Whether supervisory authority consultation is needed (Art. 36)  |
| Decision           | Proceed / modify / abandon                                      |
| Review date        | When to reassess                                                |

### 8.3 Completed DPIAs

| Component              | Date       | Outcome  | Next Review |
|------------------------|------------|----------|-------------|
| EigenTrust++ Engine    | 2026-03-25 | Proceed  | 2026-06-25  |
| Collusion Detector     | 2026-03-25 | Proceed  | 2026-06-25  |
| Bayesian Trust Decay   | 2026-03-25 | Proceed  | 2026-06-25  |
| ZKP Attestation System | 2026-03-25 | Proceed  | 2026-06-25  |

---

## 9. Data Breach Notification

### 9.1 Detection

Breaches may be detected via:
- Prometheus alerts (18 rules, routed to SecurityAlerts@theprotocol.cloud)
- CrowdSec community threat intelligence
- Supply invariant audit (60-second cycle, BREACH status)
- Manual review of security_audit_logs table

### 9.2 Response Timeline

| Action                              | Deadline                                     |
|-------------------------------------|----------------------------------------------|
| Internal assessment                 | Within 4 hours of detection                  |
| Notification to supervisory authority (GDPR Art. 33) | Within 72 hours of becoming aware |
| Notification to affected individuals (GDPR Art. 34) | Without undue delay (high risk)   |
| Post-incident review                | Within 7 days                                |
| Documentation update                | Within 14 days                               |

### 9.3 Breach Record

All breaches are logged in the incident register with: date, scope, data categories affected, number of subjects, response actions, supervisory authority notification reference.

---

## 10. Sub-Processors

| Sub-Processor    | Service                  | Location         | Data Processed                    |
|------------------|--------------------------|------------------|-----------------------------------|
| Hetzner Online   | Server infrastructure    | Germany (EU)     | All platform data (hosting)       |
| Proton Mail      | Email communications     | Switzerland      | Email addresses, alert content    |
| Let's Encrypt    | TLS certificates         | United States    | Domain names (public)             |

All sub-processors are reviewed annually. Changes to sub-processors require updated DPIA where applicable.

---

## 11. Policy Review

This policy is reviewed quarterly or upon:
- Significant change to data processing activities
- New sub-processor engagement
- Regulatory change affecting applicable law
- Data breach incident

---

*End of Data Protection Policy v2.2.3*

---

_v2.0.0 (2026-06-12): accuracy overhaul — corrected data residency (all of the platform's own infrastructure is hosted on one Hetzner server in FSN1-DC15, Germany; operator location is self-declared and display-only), topology, and transit-encryption detail to the live system. Self-assessed; not independently audited._

_v2.1.0 (2026-06-12): encryption-at-rest gap cross-referenced to risk register R-OP-08 / mitigation M-OP-08a._

_v2.2.0 (2026-10-03): wording follows the live network and the agreed public terms: the platform's units named as units (ECU on EU, ACU on ASIA), the production network named as the EU and ASIA frames with four cloud operators, votes counted by membership or by locks as each registry is set, and every surface that is switched off on the production frames named as switched off; the public network figures are listed as the endpoint serves them, and the self-declared locations are those of the production frames. Self-assessed; not independently audited._

_v2.2.1 (2026-10-16): the rights section and the credential hashes checked against the released software: access names the routes that exist (the account export, the profile, the agent's transactions, the trust score), erasure says what deletion does (a 14-day cooling-off, then anonymisation in place, not removal), and portability says that agents stay on their registry (a cross-registry transfer moves units, not an agent). Self-assessed; not independently audited._

_v2.2.2 (2026-10-16): the confidential data's storage named as the production frames and their cloud operators keep it: secrets in each registry's own env file (mode 600), keys in the SPIRE agent and the cert-writer volumes, in place of the files of the retired first frame. Self-assessed; not independently audited._

_v2.2.3 (2026-10-17): the encryption-at-rest safeguard names the credential hashes the released software uses (bcrypt for passwords, API keys and agent client secrets, and a SHA-256 lookup hash for each API key); CartoDB leaves the sub-processors (the globe's basemap is served by the registry itself). Self-assessed; not independently audited._
