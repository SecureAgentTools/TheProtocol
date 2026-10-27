# Risk Assessment Framework
**Version**: 2.2.4
**Status**: DRAFT: self-assessment (not independently audited)
**Last Updated**: 2026-10-17
**Review Cycle**: Quarterly

---

## Table of Contents

1. [Purpose](#purpose)
2. [Scope](#scope)
3. [Methodology](#methodology)
4. [AI Component Risk Register](#ai-component-risk-register)
5. [Operational Risk Register](#operational-risk-register)
6. [Risk Treatment Summary](#risk-treatment-summary)
7. [Review Schedule](#review-schedule)
8. [Appendix: Definitions](#appendix-definitions)

---

## Purpose

This document establishes a structured risk assessment framework for TheProtocol platform. It identifies, evaluates, and prescribes treatment for risks arising from AI-driven components (EigenTrust, ZKP verification, <!-- on: staking_rewards -->the payout on locked units, which is switched off on the production frames, <!-- /on -->and federation governance) and from operational infrastructure (server, networking, identity fabric, credentials).

The framework enables the Commander and future operators to make informed decisions about risk acceptance, mitigation effort, and escalation thresholds.

---

## Scope

This assessment covers:

- **AI/algorithmic components**: EigenTrust reputation, ZKP attestation, <!-- on: staking_rewards -->the payout on locked units (switched off on the production frames), <!-- /on -->federation governance, supply invariant enforcement
- **Operational infrastructure**: Server hardware, Docker orchestration, SPIRE identity fabric, Redis coordination, database layer
- **Data and credential management**: Developer/agent authentication, API keys, cross-border data flows
- **Economic system**: Unit issuance, transfers, locks, fee collection, cross-registry settlement

Out of scope: End-user device security, third-party agent code quality, upstream dependency CVEs (covered separately by Lynis and CrowdSec).

---

## Methodology

### Likelihood Scale

| Level | Label | Description |
|-------|-------|-------------|
| 1 | Rare | May occur only in exceptional circumstances (< 1% annual probability) |
| 2 | Unlikely | Could occur but not expected (1-10% annual probability) |
| 3 | Possible | Might occur at some time (10-50% annual probability) |
| 4 | Likely | Will probably occur in most circumstances (50-90% annual probability) |
| 5 | Almost Certain | Expected to occur in most circumstances (> 90% annual probability) |

### Impact Scale

| Level | Label | Description |
|-------|-------|-------------|
| 1 | Negligible | No meaningful effect on operations, data, or users |
| 2 | Minor | Minor inconvenience, self-resolving, no data loss |
| 3 | Moderate | Service degradation for subset of users, manual intervention required |
| 4 | Major | Significant service disruption, potential data integrity concern, operator impact |
| 5 | Catastrophic | System integrity compromised, unit supply breach, trust model broken, regulatory exposure |

### Risk Score Calculation

```
Risk Score = Likelihood x Impact
```

| Score Range | Classification | Treatment |
|-------------|---------------|-----------|
| 1-6 | LOW | Accept: monitor via existing mechanisms |
| 7-15 | MEDIUM | Mitigate: implement additional controls, document residual risk |
| 16-25 | HIGH | Escalate: immediate Commander attention, block deployment until resolved |

### Residual Risk

After applying existing mitigations, residual risk is re-evaluated using the same scales. Residual risk levels:

- **VERY LOW**: Mitigations reduce effective score to 1-3
- **LOW**: Mitigations reduce effective score to 4-6
- **MEDIUM**: Mitigations reduce effective score to 7-12
- **HIGH**: Mitigations insufficient, escalation required

---

## AI Component Risk Register

| ID | Component | Risk Description | L | I | Score | Existing Mitigations | Residual Risk | Treatment |
|----|-----------|-----------------|---|---|-------|---------------------|---------------|-----------|
| R-AI-01 | EigenTrust | Algorithm systematically disadvantages new agents due to cold-start bias. New agents receive disproportionately low trust scores, reducing discoverability and economic opportunity. | 2 | 3 | 6 | Teleportation factor alpha=0.15 provides uniform prior distribution across all agents. Epoch decay factor 0.95 ensures historical bias diminishes over time. Trust scores normalized per-epoch. New agent bootstrap period grants neutral (not penalized) positioning. | LOW | Accept |
| R-AI-02 | EigenTrust | Coordinated agents collude to artificially inflate or deflate trust scores. Sybil rings exchange positive ratings to boost members or negative ratings to suppress competitors. | 3 | 4 | 12 | Cosine similarity pruning (0.30 threshold) detects rating pattern similarity and discounts collusive ratings. Volume weighting (0.3 exponent) applies sublinear scaling so rating floods have diminishing returns. Collusion detection via Tarjan SCC algorithm runs daily (collusion_worker), identifies strongly-connected components, flags for review. An EigenTrust run stops after at most 100 rounds and writes its result whether or not it converged; no epoch is rejected. | MEDIUM | Mitigate |
| R-AI-03 | ZKP Verification | Malformed or crafted zero-knowledge proofs accepted by the verification circuit, allowing false attestations (e.g., fake capability claims, forged compliance proofs). | 1 | 5 | 5 | Barretenberg cryptographic backend provides mathematically sound verification. Minimum verification key size enforced (512 bytes) to reject trivially malformed proofs. Circuit registry is volume-mounted (read-only at runtime) preventing runtime circuit tampering. Proof verification runs in isolated context with no side-channel leakage. | LOW | Accept |
<!-- on: staking_rewards -->| R-AI-04 | Payout on locked units | Payouts on locked units are switched off on the production frames, so this risk does not arise there. Where a registry switches them on, malicious actors could manipulate the locked share to exploit the payout calculation: a short lock taken only for one payout or coordinated lock and unlock cycles could draw down the fee account and treasury that fund payouts, or create unfair rate advantages. | 2 | 3 | 6 | Circuit breaker activates at a 75% locked share, halting payouts if the locked share shifts abnormally. Reputation gate enforces 5% floor requirement: agents below minimum trust are excluded from payouts. Logistic decay curve prevents outsized payouts at extreme locked shares. A position cannot be unlocked before its own lock period ends (there is no separate cooldown). Velocity snapshot worker tracks locked-share movement for anomaly detection. | LOW | Accept |<!-- /on -->
| R-AI-05 | Federation Governance | Sybil registries (fake or compromised operators) influence mainframe governance decisions. Rogue operators spin up registries solely to accumulate voting power and pass malicious proposals. | 2 | 4 | 8 | Multi-registry quorum requires at least 2 distinct registries to participate for vote validity. 66% supermajority threshold makes it expensive to force outcomes. Commander veto window (7 days) allows override of suspicious proposals before execution. On a proposal opened for registry ballots, only eligible registries vote, one ballot each with weight 1: a frame or cloud operator that is a peer with a valid licence and, by default, an established track record from the auditor. On a proposal decided by voting weight, trust-weighted voting applies a Bayesian discount built from the registry's clean interactions, lost disputes and inactivity, so a registry without a record carries little weight. Federation license revocation provides ultimate quarantine mechanism. | LOW | Mitigate |
| R-AI-06 | Supply Invariant | Rogue operator or compromised service issues unauthorized units, inflating supply and corrupting the ledger every balance relies on. Could occur via direct DB manipulation, unauthorized TEG admin endpoint access, or event replay attacks. | 1 | 5 | 5 | Issuance is disabled for operator registries in federated mode: only a mainframe can issue, and the mainframe EventStore is the single source of truth. An independent supply-invariant auditor verifies delta=0.0 continuously with zero tolerance. Per-event-type emission policies partition which layer may emit each event; the TEG emitter is fail-closed, so unknown event types are blocked there. mTLS is enforced on all EventStore connections via SPIRE/SPIFFE. A TEG admin credential is required for treasury operations. Event deduplication (idempotency_key) prevents replay attacks. Stress-tested to ~275 tx/s intra-registry and ~114 tx/s end-to-end under 16 concurrent simulations, with delta=0.0 maintained throughout. | VERY LOW | Accept |

### AI Risk Mitigation Actions (Active)

| ID | Action | Owner | Status | Target Date |
|----|--------|-------|--------|-------------|
| M-AI-02a | Enhance collusion detection with temporal analysis (detect coordinated timing patterns) | Commander | PLANNED | Q2 2026 |
| M-AI-02b | Implement automatic trust score quarantine for detected SCC members | Commander | PLANNED | Q2 2026 |
| M-AI-05a | Add operator identity verification step to federation license issuance | Commander | PLANNED | Q3 2026 |

---

## Operational Risk Register

| ID | Component | Risk Description | L | I | Score | Existing Mitigations | Residual Risk | Treatment |
|----|-----------|-----------------|---|---|-------|---------------------|---------------|-----------|
| R-OP-01 | Infrastructure | Single server failure (Hetzner TheProtocol-SRV1) causes complete platform outage. Hardware failure, datacenter incident, or network partition renders all services unavailable. | 2 | 5 | 10 | RAID-1 NVMe (dual 1.92TB) protects against single disk failure. ECC RAM (128GB) prevents memory corruption. Hetzner SLA provides datacenter-grade power, cooling, and network redundancy. Docker Compose enables rapid service restart. The production frames and their cloud operators are backed up every 6 hours (a logical dump of each of their databases, their configuration, and the identity volumes that cannot be regenerated); the latest runs are kept on the same server up to a 20 GB cap (an off-site copy is mitigation M-OP-01b), so a restore brings back the state of the latest run, at most 6 hours old. EventStore append-only design preserves data integrity. | MEDIUM | Mitigate |
| R-OP-02 | Identity Fabric | SPIRE CA private key compromise allows attacker to issue valid SVIDs, impersonating any agent or service. Enables man-in-the-middle attacks across the entire trust domain. | 1 | 5 | 5 | x509pop node attestation establishes the trust root; agent SVIDs are short-lived (on the order of 30 minutes) and rotated automatically, limiting the exploitation window for any single compromised SVID. A multi-layer revocation path (EventStore push, polling, and SVID expiry) provides near-immediate revocation. The CA key is stored on-disk with restrictive (root-only) permissions. The SPIRE server runs as a dedicated container with no external network exposure. | LOW | Accept |
| R-OP-03 | Coordination | Redis single point of failure. Redis outage disrupts leader election, rate limiting, WebSocket broadcasts, and cross-worker state. Services degrade but do not lose data. | 2 | 3 | 6 | Leader election has graceful fallback: workers continue serving requests without background task coordination. Redis persistence enabled (AOF) for rapid recovery. Redis runs as dedicated container with restart policy. Background tasks are idempotent: missed cycles self-correct on next run. Rate limiter falls open (allows traffic) on Redis failure rather than blocking. | LOW | Accept |
| R-OP-04 | Federation | Cross-border data transfer between federated registries raises data sovereignty and privacy concerns. Agent metadata, transaction records, and trust scores flow between jurisdictions. | 3 | 3 | 9 | All federation traffic encrypted via mTLS (SPIRE-issued SVIDs). Operators control their own data sovereignty: only agent cards and trust metadata are shared, not raw transaction data. Federation sync is opt-in and configurable per operator. SPIRE trust boundary enforces cryptographic isolation between trust domains. EventStore writes are append-only with operator attribution. | MEDIUM | Mitigate |
| R-OP-05 | Authentication | Developer credential leak (password, API key, or JWT) grants unauthorized access to developer account, agent management, and potentially admin functions. | 3 | 3 | 9 | Passwords hashed with bcrypt (cost factor 12). API keys hashed with bcrypt, with a SHA-256 lookup hash to find the key; plaintext shown once at creation, never stored. JWTs are short-lived with configurable expiry. Rate limiting on auth endpoints (fail2ban + application-level). API key prefix (avreg_) enables quick identification in leaked credential databases. Admin endpoints require is_admin=True flag (not just valid JWT). | MEDIUM | Mitigate |
| R-OP-06 | Containers | Container escape or privilege escalation from application container to host. Attacker gains host-level access from within a compromised registry or TEG container. | 1 | 5 | 5 | Containers run as non-root where possible. Docker socket not mounted into application containers. Network segmentation via Docker networks. CrowdSec provides runtime threat detection. Host OS patched via unattended-upgrades. Lynis security audit baseline (score 75/100). | LOW | Accept |
| R-OP-07 | Database | PostgreSQL data corruption or unauthorized access. Loss of agent records, balances, or governance state. | 1 | 5 | 5 | Separate PostgreSQL instances per service and per frame/operator. Database credentials are unique per instance, stored in environment files (not committed to source control). Docker volumes with host-backed storage on RAID-1. Dump-based recovery from the 6-hourly backup of the production frames' and cloud operators' databases, plus the EventStore's independent append-only audit trail for financial-data reconstruction. | LOW | Accept |
| R-OP-08 | Infrastructure | **Disk encryption at rest is not enabled** (the platform's one acknowledged hardening gap). An attacker with physical access to the drives (datacenter intrusion or improper drive decommissioning) could read on-disk data. | 1 | 4 | 4 | Physical access is controlled by the Hetzner FSN1-DC15 datacenter. Credentials are stored hashed regardless of disk state (bcrypt for passwords, API keys and agent client secrets; an API key also carries a SHA-256 lookup hash). Data files are root-only with container isolation. Block-level encryption (LUKS) evaluation is planned: on a remote bare-metal host it requires a reboot-time unlock strategy and scheduled downtime. | LOW | Mitigate (planned) |

### Operational Risk Mitigation Actions (Active)

| ID | Action | Owner | Status | Target Date |
|----|--------|-------|--------|-------------|
| M-OP-01a | Evaluate Hetzner secondary server for warm standby (Phase 2 multi-server) | Commander | PLANNED | Q3 2026 |
| M-OP-01b | Implement automated off-site backup to Hetzner Storage Box | Commander | PLANNED | Q2 2026 |
| M-OP-04a | Document data flow mapping for federation (GDPR Article 30 readiness) | Commander | PLANNED | Q3 2026 |
| M-OP-05a | Implement API key rotation mechanism (scheduled expiry + notification) | Commander | PLANNED | Q2 2026 |
| M-OP-08a | Evaluate LUKS block-level encryption at rest (unlock strategy + downtime window for a remote bare-metal host) | Commander | PLANNED | Q3 2026 |

---

## Risk Treatment Summary

| Risk Level | Count | Treatment | Examples |
|------------|-------|-----------|----------|
| HIGH (16-25) | 0 | Escalate | None currently |
| MEDIUM (7-15) | 5 | Mitigate | R-AI-02, R-AI-05, R-OP-01, R-OP-04, R-OP-05 |
| LOW (1-6) | <!-- on: staking_rewards -->9<!-- /on --><!-- off: staking_rewards -->8<!-- /off --> | Accept / Mitigate (planned) | R-AI-01, R-AI-03, <!-- on: staking_rewards -->R-AI-04, <!-- /on -->R-AI-06, R-OP-02, R-OP-03, R-OP-06, R-OP-07, R-OP-08 |

### Overall Risk Posture

The platform's risk posture is **ACCEPTABLE** with the following observations:

1. **No HIGH risks identified.** All risks are either accepted at LOW or actively mitigated at MEDIUM.
2. **Supply integrity is robust.** The combination of per-event-type emission policies, an independent continuous supply auditor (delta=0.0), and disabled operator issuance provides defense-in-depth against the highest-impact risk category.
3. **Single-server concentration** (R-OP-01) is the most significant operational risk. Mitigated by hardware redundancy (RAID-1, ECC) but lacks geographic redundancy. Phase 2 multi-server deployment is the planned remediation.
4. **EigenTrust manipulation** (R-AI-02) is the most significant AI risk. Active collusion detection exists but temporal analysis enhancement is planned.
5. **Credential management** (R-OP-05) is well-controlled but API key rotation should be automated.
6. **Disk encryption at rest** (R-OP-08) is the platform's one acknowledged infrastructure hardening gap: low likelihood (datacenter physical security), mitigated by hashed credential storage, with LUKS evaluation planned (M-OP-08a).

---

## Review Schedule

| Activity | Frequency | Next Due | Owner |
|----------|-----------|----------|-------|
| Full risk register review | Quarterly | 2026-06-25 | Commander |
| AI component risk deep-dive | Quarterly | 2026-06-25 | Commander |
| Supply invariant audit verification | Continuous (60s) | Automated | Supply Auditor |
| EigenTrust collusion analysis | Daily | Automated | Collusion Worker |
| Penetration test (external) | Annually | 2027-03-25 | Commander + External |
| Incident-triggered review | On occurrence | As needed | Commander |
| Post-deployment risk check | Per release | As needed | Commander |

### Triggers for Unscheduled Review

- Any P1 or P2 incident (see Incident Response Procedures)
- Supply invariant breach (delta != 0.0)
- New federation operator onboarded
- Major feature deployment affecting units or fees
- External vulnerability disclosure affecting dependencies

---

## Appendix: Definitions

| Term | Definition |
|------|-----------|
| ACU, ECU | Units: the platform-internal accounting units of the ASIA and EU frames; each frame has its own, and a cloud operator uses its parent frame's. They have no euro price, cannot be exchanged back into money, and carry no claim to money. |
| EigenTrust | Distributed reputation algorithm computing global trust scores from local agent interactions |
| EventStore | Immutable append-only CQRS event ledger recording all financial and governance events |
| Federation | Network of independently-operated registries sharing agent discovery and cross-registry transfers |
| Mainframe | A primary TheProtocol frame (on the production network, EU or ASIA) operated by the Commander, with issuing authority and its own EventStore |
| mTLS | Mutual TLS: both client and server authenticate via X.509 certificates |
| Operator | Entity running a federated registry instance under TheProtocol federation license |
| SCC | Strongly Connected Component: graph theory concept used in collusion detection |
| SPIFFE | Secure Production Identity Framework for Everyone: workload identity standard |
| SPIRE | SPIFFE Runtime Environment: the implementation providing SVID issuance and attestation |
| SVID | SPIFFE Verifiable Identity Document: short-lived certificate issued by SPIRE |
| TEG | the ledger service: the service layer managing unit balances and transfers |
| Locked share | the share of all units that is locked across all agents (the code's tvl names) |
| ZKP | Zero-Knowledge Proof: cryptographic proof allowing verification without revealing underlying data |

---

_v2.0.0 (2026-06-12): accuracy overhaul — corrected stress figures, supply/emission mechanics, backup and recovery semantics, SVID TTL, and topology to the live system (16 federated registries, ~280 containers, Hetzner FSN1-DC15 in Germany). Self-assessed; not independently audited._

_v2.1.0 (2026-06-12): added R-OP-08 — disk encryption at rest not enabled (the platform's one acknowledged hardening gap) — with mitigation M-OP-08a (LUKS evaluation, Q3 2026); risk counts updated (9 LOW)._

_v2.2.0 (2026-10-03): wording follows the live network and the agreed public terms: the platform's units named as units (ECU on EU, ACU on ASIA), the production network named as the EU and ASIA frames with four cloud operators, votes counted by membership or by locks as each registry is set, and every surface that is switched off on the production frames named as switched off; R-AI-04 and R-AI-05 restated for the production configuration and for registry ballots, and a position is released when its own lock period ends (there is no separate cooldown). Self-assessed; not independently audited._

_v2.2.1 (2026-10-16): R-AI-02 and R-AI-05 checked against the released software: an EigenTrust run writes its result after at most 100 rounds, converged or not; the Bayesian discount follows clean interactions, lost disputes and inactivity._

_v2.2.2 (2026-10-16): the text without em dashes or double-hyphen dashes: the treatment scale, the registers' mitigations, R-OP-08, the overall posture and the definitions read with colons, semicolons or parentheses. Self-assessed; not independently audited._

_v2.2.3 (2026-10-17): R-OP-01 and R-OP-07 describe the backup that runs for the production frames and their cloud operators (every 6 hours: each database, the configuration and the identity volumes, the latest runs kept on the same server up to a 20 GB cap); R-OP-05 and R-OP-08 name the credential hashes the released software uses (bcrypt, and a SHA-256 lookup hash for each API key). Self-assessed; not independently audited._

_v2.2.4 (2026-10-17): R-OP-01 says what a restore brings back (the state of the latest run, at most 6 hours old). Self-assessed; not independently audited._
