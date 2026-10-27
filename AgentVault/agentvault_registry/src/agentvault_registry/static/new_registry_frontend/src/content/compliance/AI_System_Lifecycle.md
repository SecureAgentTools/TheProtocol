# AI System Lifecycle Documentation

> **Implementation cross-references**: AI lifecycle stages map to:
> - Reputation scoring → `03_SERVICES/Federation_Policy_Enforcement.md` + EigenTrust workers
<!-- on: staking_rewards -->> - Payout distribution → `05_API_REFERENCE/REWARDS_WIRING.md` (gold-standard reference)<!-- /on -->
> - Policy enforcement → `05_API_REFERENCE/Enforcement_Admin.md`
> - Audit trails → EventStore (`03_SERVICES/Event_Store/Overview.md`)



| Field       | Value                          |
|-------------|--------------------------------|
| Version     | 2.2.2                          |
| Status      | DRAFT: self-assessment (not independently audited) |
| Date        | 2026-10-17                     |
| Owner       | Commander ruFFa                |
| Review Cycle| Quarterly                      |

---

## 1. Purpose

This document provides lifecycle documentation for every AI and algorithmic decision-making component in TheProtocol. For each component, it records: purpose, design rationale, inputs, outputs, known limitations, bias assessment, human oversight mechanisms, monitoring, and decommission procedure.

This documentation supports ISO 42001 Annex A.3 (AI system lifecycle) and enables meaningful human oversight of automated decision-making.

---

## 2. Component Inventory

| # | Component                      | Type              | Risk Level | Status    |
|---|--------------------------------|-------------------|------------|-----------|
| 1 | EigenTrust++ Reputation Engine | Trust computation | HIGH       | Production|
| 2 | ZKP Attestation System         | Cryptographic     | LOW        | Production|
<!-- on: staking_rewards -->| 3 | Payout on Locked Units (payout engine) | Financial | MEDIUM | Built; switched off on the production frames |<!-- /on -->
| 4 | Collusion Detector             | Fraud detection   | HIGH       | Production|
| 5 | Bayesian Cross-Registry Trust  | Trust computation | MEDIUM     | Production|
| 6 | Federation Governance          | Decision-making   | HIGH       | Production|

---

## 3. Component 1: EigenTrust++ Reputation Engine

### 3.1 Purpose

Compute agent trust scores from the transaction graph, enabling the network to distinguish reliable agents from malicious or low-quality ones. Scores are published per agent and are not an input to governance voting weight.<!-- on: staking_rewards --> Where a registry switches payouts on locked units on, scores also gate payout eligibility (payouts on locked units are switched off on the production frames).<!-- /on -->

### 3.2 Design Rationale

EigenTrust++ extends the original EigenTrust algorithm with six stages designed for adversarial environments:

1. **Local trust aggregation**: build directed trust edges from transfer history and dispute outcomes
2. **Normalize**: row-normalize the trust matrix so each agent's outgoing trust sums to 1.0
3. **Cosine pruning**: remove edges between agents whose trust profiles are too similar (prevents cluster dominance)
4. **Power iteration**: iteratively compute the global trust vector until convergence
5. **Epoch decay**: apply time decay so recent behavior weighs more than historical
6. **Volume weighting**: scale by transaction volume to prevent low-activity manipulation

### 3.3 Inputs

| Input                  | Source                          | Update Frequency        |
|------------------------|---------------------------------|-------------------------|
| Transfer events        | EventStore (TokensTransferred)  | Continuous (event-driven)|
| Dispute outcomes       | Registry DB (disputes table)    | On dispute resolution   |
| ZKP attestations       | Registry DB (attestations table)| On attestation submission|
| Pre-trusted agents     | Configuration (seed set)        | Static (code change)    |

### 3.4 Outputs

| Output               | Format                         | Consumer                        |
|----------------------|--------------------------------|---------------------------------|
| reputation_score     | Integer 0-1000 per agent       | Agent profiles and discovery, track record ranking, Guild |
| Trust graph edges    | LocalTrustScore table          | Collusion detector, analytics   |
| ReputationChanged    | EventStore event               | Audit trail                     |
| Epoch metrics        | computation_time_ms, iterations| Prometheus                      |

### 3.5 Known Limitations

- **Cold start**: New agents start at score 0. Meaningful scores require minimum network activity (transfers, attestations).
- **Convergence**: Power iteration may require many iterations in sparse graphs. Capped at configurable maximum.
- **Sybil resistance**: Depends on transaction volume weighting. Pure identity proliferation without economic activity brings no trust gain.
- **Epoch boundary**: Scores update at epoch boundaries (1-hour default), not in real time.

### 3.6 Bias Assessment

| Concern                        | Mitigation                                                      |
|--------------------------------|-----------------------------------------------------------------|
| Early mover advantage          | Epoch decay ensures old trust decays; new activity can overtake |
| Cluster dominance              | Cosine pruning removes edges between suspiciously similar profiles |
| Demographic/identity bias      | No demographic or identity-based features are used as inputs    |
| Uniform baseline               | Teleportation factor alpha=0.15 ensures every agent has a nonzero baseline trust contribution |
| Volume manipulation            | Volume weighting uses logarithmic scaling to limit whale influence |

### 3.7 Human Oversight

| Action                          | Method                                                    |
|---------------------------------|-----------------------------------------------------------|
| View scores                     | `GET /api/v1/reputation/{did}/trust-score`                |
| View individual breakdown       | `GET /api/v1/governance/voting-power/{did}`               |
| Trigger manual epoch            | `POST /api/v1/reputation/admin/trigger-computation`       |
| Adjust algorithm constants      | Code change + deploy (Change Management Policy applies)   |
| Override individual score       | Not supported (by design: it prevents admin manipulation) |

### 3.8 Monitoring

| Metric                          | Source              | Alert Threshold                  |
|---------------------------------|---------------------|----------------------------------|
| Epoch computation time          | Prometheus          | > 30 seconds                     |
| Convergence iterations          | Prometheus          | > 100 iterations                 |
| ReputationChanged event rate    | EventStore          | Anomalous spike/drop             |
| Score distribution              | Grafana dashboard   | Manual review (weekly)           |

### 3.9 Decommission Procedure

1. Set `EIGENTRUST_ENABLED=false` in environment configuration
2. Redeploy registry containers
3. Agents retain their last computed score (frozen, not deleted)
4. No new epochs are computed
5. Governance voting weight is unchanged (trust scores are not an input to it)
6. Reverse: Set `EIGENTRUST_ENABLED=true` and redeploy

---

## 4. Component 2: ZKP Attestation System

### 4.1 Purpose

Allow agents to prove that a public policy limit held for a private figure (a markup over a cost, a reported usage against a meter log, the fees of a transfer batch, the rejection rate of a moderation log) without revealing the figure. A verified attestation adds one reputation point per agent, circuit and UTC day.

### 4.2 Design Rationale

Uses Barretenberg UltraHonk (`bb` 0.82.2, invoked by `core/zkp_verifier.py`) over four published Noir policy circuits (v2.0.0). Each circuit takes its policy limit as a public input and commits to the private figure. The registry checks the stated public inputs against the proof, refuses a limit looser than its own policy (`ZKP_POLICY_JSON`), and requires the proof's reference to be derived from the submitting agent's DID, so a proof counts once and only for the agent that made it. Each circuit has a published verification key whose digest is checked; the reference string is pinned and ships in the image. Proofs are verified server-side in the registry backend; no blockchain is involved.

### 4.3 Inputs

| Input                  | Source                          | Format                          |
|------------------------|---------------------------------|---------------------------------|
| Proof bytes            | Agent submission                | Binary (Barretenberg format)    |
| Public inputs          | Agent submission                | Named values: the policy limit, the stated figure, the reference and its label |
| Circuit ID             | Agent submission                | String identifier               |
| Verification key       | Circuit registry (in the image) | Binary file per circuit, SHA-256 in its metadata |

### 4.4 Outputs

| Output                  | Format                         | Consumer                        |
|-------------------------|--------------------------------|---------------------------------|
| Verification result     | verified / rejected            | Submitting agent, reputation    |
| Reputation point        | +1 for the first stored verified attestation per agent, circuit and UTC day | `reputation_score`, directly (EigenTrust++ does not read attestations) |
| AttestationSubmitted    | EventStore event               | Audit trail                     |

### 4.5 Known Limitations

- Four policy circuits at v2.0.0; the v1.0.0 circuits, whose limits nothing bound, are retired and refused
- `proof_of_reputation` is not a proof: it answers `not_a_proof` and counts for nothing; a zero-knowledge proof of a reputation threshold is still to be built
- A proof binds a committed figure; it does not show the figure is true (the agent can open the commitment to an auditor)
- New or changed circuits ship with an image build (no hot-reload)
- Proof generation is client-side (SDK responsibility); the registry only verifies, apart from a tutorial endpoint that proves fixed demo figures

### 4.6 Bias Assessment

No bias concerns. The system performs pure cryptographic verification with no ML components, no demographic features, and no subjective judgment. A valid proof whose stated inputs match it and whose limit is within the registry's policy passes; any other fails, with the reason recorded.

### 4.7 Human Oversight

| Action                          | Method                                                    |
|---------------------------------|-----------------------------------------------------------|
| View attestation history        | EventStore query (AttestationSubmitted events)            |
| Manage circuit registry         | Change `agentvault_circuit_registry/` and build an image; set this registry's limits with `ZKP_POLICY_JSON` |
| Retire a circuit                | Mark it retired in the circuit registry and build (as v1.0.0 was); the verifier refuses it and names its successor |
| Revoke an attestation           | `POST /api/v1/attestations/admin/{id}/revoke` (admin); final, and it takes back the point it gave |
| Review verification stats       | Prometheus metrics (success/failure rate)                  |

### 4.8 Monitoring

| Metric                          | Source              | Alert Threshold                  |
|---------------------------------|---------------------|----------------------------------|
| Verification success rate       | Prometheus          | < 50% (may indicate bad proofs)  |
| AttestationSubmitted rate       | EventStore          | Anomalous spike                  |
| Circuit registry file count     | File system check   | Mismatch with expected count     |

### 4.9 Decommission Procedure

1. Switch the phases off (`ZKP_PHASE_1_ENABLED` to `ZKP_PHASE_5_ENABLED=false`, or Frame Management's zero-knowledge switch): nothing is stored and nothing is granted; a proof still verifies and emits `AttestationSubmitted`
2. To refuse submissions as well, ship an image whose circuit registry holds no active circuit: every submission then answers `failed` (unknown circuit)
3. Historical attestation events remain in EventStore (immutable)
4. Points already given stay; no new ones are given

---

<!-- on: staking_rewards -->
## 5. Component 3: Payout on Locked Units (switched off on the production frames)

### 5.1 Purpose

Where a registry switches payouts on locked units on (`STAKING_REWARDS_ENABLED`, a discretionary switch per registry, switched off on the production frames), compute the payout rate from network conditions: the rate falls as the share of units locked rises. The production frames publish no rate and pay nothing.

### 5.2 Design Rationale

Logistic decay curve: the rate is highest at a low locked share (the share of units locked) and decays smoothly as that ratio rises, with a circuit breaker at a 75% locked share. An operator-configured lock addition adds to the rate for longer locks. Trust score gate excludes very low-reputation agents.

### 5.3 Inputs

| Input                  | Source                          | Update Frequency        |
|------------------------|---------------------------------|-------------------------|
| Total locked units     | TEG Layer (aggregate balance)   | Per distribution cycle  |
| Total supply           | EventStore (supply audit)       | 60-second cycle         |
| Lock period            | Lock position record            | When the lock opens     |
| Agent trust score      | EigenTrust (latest epoch)       | Hourly                  |

### 5.4 Outputs

| Output                  | Format                         | Consumer                        |
|-------------------------|--------------------------------|---------------------------------|
| Rate per lock tier      | Percentage (float); no tiers while payouts on locked units are switched off | Public API, frontend |
| Payout amount           | Units per position; none while switched off | Payout distributor |
| RewardsDistributed      | EventStore event               | Audit trail (skip_in_projection)|

### 5.5 Known Limitations

- Relies on accurate TVL calculation from TEG; if TEG reports stale data, the computed rate may be incorrect
- Does not account for unit velocity directly (only TVL ratio)
- Circuit breaker is a hard cutoff at 75%, not a gradual taper
- Lock period bonus is linear; very long locks do not receive a disproportionate payout

### 5.6 Bias Assessment

| Concern                        | Mitigation                                                      |
|--------------------------------|-----------------------------------------------------------------|
| Reputation gate                | Agents with very low trust scores (below 5% floor) are excluded from payouts. This is an intentional economic deterrent against malicious behavior, not demographic bias. |
| Whale advantage                | Lock period multiplier partially compensates; the payout scales linearly with the amount locked, not exponentially |
| Timing of a position           | Does not apply while payouts on locked units are switched off, as on the production frames. Where a registry switches them on, each day's rate follows that day's locked share for old and new positions alike: it is not fixed when a position is opened. |

### 5.7 Human Oversight

| Action                          | Method                                                    |
|---------------------------------|-----------------------------------------------------------|
| View the rate tiers             | `GET /api/v1/staking/apy-tiers` (public; answers no tiers while payouts on locked units are switched off) |
| Adjust curve parameters         | RegistryEnforcementPolicy (governance-changeable)         |
| Adjust circuit breaker          | Code change + deploy (SIGNIFICANT change)                 |
| Switch payouts off              | `STAKING_REWARDS_ENABLED=false` (as on the production frames), or a policy change via governance or admin override that sets the rate to zero |
| Review distribution logs        | Container logs + RewardsDistributed events                 |

### 5.8 Monitoring

| Metric                          | Source              | Alert Threshold                  |
|---------------------------------|---------------------|----------------------------------|
| Daily payout total              | EventStore          | > 1% of total supply             |
| Treasury balance                | TEG Layer           | Below payout reserve threshold   |
| TVL ratio                       | Prometheus          | Approaching 75% circuit breaker  |
| Distribution failures           | Container logs      | Any failure                      |

### 5.9 Decommission Procedure

1. Set `STAKING_REWARDS_ENABLED=false` (the production frames run this way), or set the rate to zero via a RegistryEnforcementPolicy update
2. Existing lock positions remain locked (honor existing lock periods)
3. No new payouts are made
4. Agents can unlock once each position's own lock period has ended
5. Reverse: Set `STAKING_REWARDS_ENABLED=true`, or restore the policy rate

---
<!-- /on -->

## 6. Component 4: Collusion Detector

### 6.1 Purpose

Detect coordinated agent rings that manipulate trust scores or fee structures through circular transfer patterns.

### 6.2 Design Rationale

Applies Tarjan's Strongly Connected Components (SCC) algorithm on the directed trust graph. Rings of 3+ agents where >= 75% of transfers are internal to the ring are flagged as potential collusion.

### 6.3 Inputs

| Input                  | Source                          | Update Frequency        |
|------------------------|---------------------------------|-------------------------|
| LocalTrustScore edges  | Registry DB                     | Per detection cycle     |
| Transfer counts        | Minimum 10 transfers per edge   | Accumulated over time   |
| Agent DIDs             | Registry DB                     | Current agent set       |

### 6.4 Outputs

| Output                  | Format                         | Consumer                        |
|-------------------------|--------------------------------|---------------------------------|
| AuditorFlagLog entries  | DB records with severity HIGH  | Admin review queue              |
| ring_members            | List of agent DIDs             | Admin investigation             |
| collusion_score         | Float (internal ratio metric)  | Flag severity classification    |

### 6.5 Known Limitations

- Requires `networkx` Python library; graceful degradation if missing (logs warning, skips detection)
- Minimum ring size is 3; colluding pairs are not detected by SCC
- Minimum 10 transfers per edge required; low-activity collusion may evade detection
- False positives possible for legitimate high-volume trading pairs within a cluster

### 6.6 Bias Assessment

| Concern                        | Mitigation                                                      |
|--------------------------------|-----------------------------------------------------------------|
| False positives                | Flagging only (no automatic enforcement); human review required |
| Legitimate trading clusters    | 75% threshold is conservative; normal clusters rarely exceed this |
| New agent targeting            | New agents with few transfers do not meet minimum edge threshold |

### 6.7 Human Oversight

| Action                          | Method                                                    |
|---------------------------------|-----------------------------------------------------------|
| Review flagged rings            | Query AuditorFlagLog table (admin)                        |
| Investigate specific agent      | `GET /api/v1/agents/by-did/{did}` + transfer history      |
| Take enforcement action         | Manual decision: warn, restrict, or ban via admin endpoint|
| Dismiss false positive          | Update flag status in AuditorFlagLog                      |
| Adjust detection parameters     | Code change (threshold, min transfers) + deploy           |

### 6.8 Monitoring

| Metric                          | Source              | Alert Threshold                  |
|---------------------------------|---------------------|----------------------------------|
| Flags per detection cycle       | Prometheus          | > 5 new flags (investigate)      |
| False positive rate             | Manual review log   | Track quarterly                  |
| Detection cycle duration        | Container logs      | > 60 seconds                     |
| networkx availability           | Container startup   | Missing library alert            |

### 6.9 Decommission Procedure

1. Set `COLLUSION_WORKER_ENABLED=false` in environment configuration
2. Redeploy registry containers
3. Existing AuditorFlagLog entries remain for historical reference
4. No new collusion detection cycles run
5. Reverse: Set `COLLUSION_WORKER_ENABLED=true` and redeploy

---

## 7. Component 5: Bayesian Cross-Registry Trust

### 7.1 Purpose

Discount trust and governance voting weight from peer registries based on their dispute history, preventing a registry with poor track record from exercising disproportionate influence in federation governance.

### 7.2 Design Rationale

Uses a Beta distribution model: `discount = (alpha + success) / (alpha + success + beta + disputes_lost)`. The prior (alpha=1, beta=1) is a neutral 0.5 for a new peer: no evidence either way, neither trust nor distrust. Inactivity decay pulls the discount toward 0.5 (neutral), not toward 0 (distrust).

### 7.3 Inputs

| Input                  | Source                          | Update Frequency        |
|------------------------|---------------------------------|-------------------------|
| total_interactions     | PeerRegistry table              | Per federation sync     |
| disputes_lost_with     | PeerRegistry table              | On dispute resolution   |
| Last activity timestamp| PeerRegistry table              | Per federation sync     |
| Inactivity threshold   | Configuration                   | Static                  |

### 7.4 Outputs

| Output                  | Format                         | Consumer                        |
|-------------------------|--------------------------------|---------------------------------|
| bayesian_discount       | Float 0.0-1.0 per peer        | Federation governance voting    |
| Discount change events  | Log entries                    | Admin review                    |

### 7.5 Known Limitations

- Inactivity decay may penalize legitimate low-traffic registry operators
- Requires sufficient interaction history for meaningful discount (sparse data = near-prior)
- Discount applies uniformly to all agents from a peer registry (no per-agent granularity at federation level)
- Manual override available but not reflected in the formula (admin sets value directly)

### 7.6 Bias Assessment

| Concern                        | Mitigation                                                      |
|--------------------------------|-----------------------------------------------------------------|
| New peer disadvantage          | Prior (alpha=1, beta=1): a new peer starts at a neutral 0.5      |
| Inactivity punishment          | Decay pulls to 0.5 (neutral), not 0.0 (distrust)               |
| Recovery from disputes         | New successful interactions increase discount; past is not permanent |
| Geographic/identity bias       | No geographic or identity features used; purely interaction-based |

### 7.7 Human Oversight

| Action                          | Method                                                    |
|---------------------------------|-----------------------------------------------------------|
| View per-peer discounts         | Query PeerRegistry table (admin)                          |
| Manually override discount      | Direct DB update on bayesian_discount field (admin)       |
| Adjust prior parameters         | Code change (alpha, beta values) + deploy                 |
| Adjust inactivity threshold     | Configuration change + deploy                             |
| Review discount trends          | Historical PeerRegistry snapshots                         |

### 7.8 Monitoring

| Metric                          | Source              | Alert Threshold                  |
|---------------------------------|---------------------|----------------------------------|
| Per-peer discount values        | PeerRegistry table  | < 0.3 (investigate disputes)     |
| Inactivity leak timestamps      | PeerRegistry table  | Peer inactive > 7 days           |
| Discount change frequency       | Log analysis        | Anomalous rapid changes          |

### 7.9 Decommission Procedure

1. Set all bayesian_discount values to 1.0 (full trust) across all PeerRegistry records
2. Comment out decay logic in federation sync background task
3. Redeploy registry containers
4. All peer registries receive full governance voting weight
5. Reverse: Restore decay logic and let discounts recalculate from interaction history

---

## 8. Component 6: Federation Governance

### 8.1 Purpose

Enable cross-registry policy proposals where multiple registries can collectively decide on federation-wide parameter changes, with democratic bottom-up governance and a centralized safety valve.

### 8.2 Design Rationale

Three-tier governance model:
1. **Local senate**: votes on proposals within a registry are counted by membership (one vote per member, weighted by time as a member) or by locks (weight from locked units), as the registry is set (`governance_weight_mode`); the production frames and their cloud operators count by membership
2. **Federation proposal**: passed local proposals can be escalated to federation scope; a federation proposal opened for registry ballots is decided by one signed ballot per eligible registry, each weighing 1
3. **Mainframe veto**: Commander has a 7-day veto window on all passed federation proposals

This balances democratic participation with operational safety.

### 8.3 Inputs

| Input                  | Source                          | Update Frequency        |
|------------------------|---------------------------------|-------------------------|
| Proposals              | Agent submission (agent JWT)    | On creation             |
| Votes                  | Agent submission (voting weight); registry ballots on a ballot proposal | During voting period    |
| Voting weight          | Membership tenure (member mode), or lock positions plus a bonus for recent verified ZKP attestations (lock mode) | Per governance query    |
| Registry mTLS identity | SPIRE SVID                      | Per federation request  |
| Bayesian discount      | PeerRegistry table              | Per vote weight calc    |

### 8.4 Outputs

| Output                  | Format                         | Consumer                        |
|-------------------------|--------------------------------|---------------------------------|
| Proposal status         | VOTING / PASSED / FAILED / VETOED | Public API, frontend        |
| Vote tallies            | For/against counts with weight | Public API                      |
| Policy changes          | Applied to RegistryEnforcementPolicy | All federated registries |
| FederationProposal events| EventStore                    | Audit trail                     |

### 8.5 Known Limitations

- Requires participation from at least 2 registries for federation-scope proposals
- Commander veto is centralized by design (single point of authority)
- Manual tally required to finalize proposal results (no automatic execution)
- Voting period is fixed at creation (duration_seconds parameter); cannot be extended
- Agents can only vote on proposals on their own registry (no cross-registry voting on local proposals)

### 8.6 Bias Assessment

| Concern                        | Mitigation                                                      |
|--------------------------------|-----------------------------------------------------------------|
| Wealth concentration           | By membership: one vote per member, so more units never buy more votes; by locks: weight grows with the square root of the locked units, not in proportion to them |
| Trust-weighted voting          | Registries with dispute history have less federation influence on a proposal decided by voting weight (intentional, via Bayesian discount); on a registry-ballot proposal each ballot weighs 1 |
| Commander veto power           | Veto is transparent (logged) and time-limited (7 days); no silent override |
| Participation barrier          | By membership: a member proposes and votes through an agent they allow to vote (the governor role), and nothing is paid for membership; by locks: an agent allowed to vote needs locked units to carry any weight |

### 8.7 Human Oversight

| Action                          | Method                                                    |
|---------------------------------|-----------------------------------------------------------|
| View proposals                  | `GET /api/v1/governance/proposals` (public)               |
| View vote details               | `GET /api/v1/governance/proposals/{id}` (public)          |
| Tally results                   | `POST /api/v1/governance/proposals/{id}/tally` (agent JWT)|
| Exercise veto                   | Admin endpoint within 7-day window                        |
| Create proposal                 | `POST /api/v1/governance/proposals` (agent JWT)           |

### 8.8 Monitoring

| Metric                          | Source              | Alert Threshold                  |
|---------------------------------|---------------------|----------------------------------|
| Active proposals                | Registry DB         | Information only                 |
| Vote participation rate         | Proposal records    | < 10% of eligible voting weight  |
| Federation proposal escalations | EventStore          | Track for activity trends        |
| Veto exercises                  | Admin audit log     | Any veto (review justification)  |

### 8.9 Decommission Procedure

1. Remove federation governance endpoints from router configuration
2. Redeploy registry containers
3. Existing local governance continues to function (proposals, votes, tallies)
4. Federation-scope proposals can no longer be created or escalated
5. Historical federation governance events remain in EventStore
6. Reverse: Restore endpoints and redeploy

---

## 9. Lifecycle Stage Summary

| Component              | Design   | Development | Testing  | Deployment | Monitoring | Review   |
|------------------------|----------|-------------|----------|------------|------------|----------|
| EigenTrust++           | Complete | Complete    | Stress tested (16-sim) | Production | Prometheus + ES | Quarterly |
| ZKP Attestation        | Complete | Complete    | Unit + integration | Production | Prometheus | Quarterly |
<!-- on: staking_rewards -->| Payout on locked units | Complete | Complete    | Simulation verified | Switched off on the production frames | Prometheus + ES | Quarterly |<!-- /on -->
| Collusion Detector     | Complete | Complete    | Graph test scenarios | Production | Prometheus | Quarterly |
| Bayesian Trust         | Complete | Complete    | Federation test pair | Production | DB monitoring | Quarterly |
| Federation Governance  | Complete | Complete    | Multi-registry voting | Production | ES + admin log | Quarterly |

---

## 10. Cross-Component Dependencies

```
EigenTrust++ ──produces──> reputation_score
    │                           │
<!-- on: staking_rewards -->    │                           ├──> Dynamic reward rate (trust gate; switched off on the production frames)<!-- /on -->
    │                           ├──> Agent profiles, discovery, track record, Guild (published score)
    │                           └──> Bayesian Trust (indirect via disputes)
    │
    ├──(not read)──> ZKP Attestation (its point goes to reputation_score directly; its trust signal is an audit record)
    └──consumes──> Collusion Detector (flagged agents investigated)

Collusion Detector ──reads──> EigenTrust trust graph (LocalTrustScore edges)
Bayesian Trust ──feeds──> Federation Governance (peer registry voting weight)
```

Decommissioning any component may affect downstream consumers. Refer to individual decommission procedures and test dependencies before disabling.

---

## 11. Review Schedule

| Review Type                     | Frequency  | Scope                                           |
|---------------------------------|------------|-------------------------------------------------|
| Operational review              | Monthly    | Metrics, alerts, performance                    |
| Bias and fairness review        | Quarterly  | Score distributions, flag rates, false positives|
| Full lifecycle review           | Quarterly  | All sections of this document                   |
| DPIA refresh                    | Quarterly  | Data Protection Policy cross-reference          |
| Stakeholder feedback            | Ongoing    | Agent/developer reports, dispute patterns       |

---

*End of AI System Lifecycle Documentation v2.2.2*

---

_v2.0.0 (2026-06-12): accuracy overhaul — corrected the ZKP verifier description (Barretenberg PlonK, server-side, no blockchain) and version/date to the live system. Self-assessed; not independently audited._

_v2.1.0 (2026-10-03): wording follows the live network and the agreed public terms: the platform's units named as units (ECU on EU, ACU on ASIA), the production network named as the EU and ASIA frames with four cloud operators, votes counted by membership or by locks as each registry is set, and every surface that is switched off on the production frames named as switched off; trust scores are stated as what they are: published per agent and not an input to voting weight. Self-assessed; not independently audited._

_v2.2.0 (2026-10-13): the ZKP component follows the v2.0.0 circuits: public limits and committed figures, the reference bound to the submitting agent, v1.0.0 retired, `proof_of_reputation` not a proof, one point per agent, circuit and UTC day, and the phase switches as the decommission path. Self-assessed; not independently audited._

_v2.2.1 (2026-10-16): the text without em dashes (the EigenTrust++ stages, the score override and the Commander veto read with colons); the header carries the version of the latest note (it had stayed at 2.1.0 when v2.2.0 was recorded). Self-assessed; not independently audited._

_v2.2.2 (2026-10-17): the Bayesian trust prior described as the code sets it (§7.2 and §7.6): a neutral 0.5 for a new peer, no evidence either way, where it read as a benefit of the doubt. Self-assessed; not independently audited._
