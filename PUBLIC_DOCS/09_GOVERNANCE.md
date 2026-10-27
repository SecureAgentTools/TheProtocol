<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/09_governance.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Operator Guide: Governance
**Audience**: Federated registry operators
**Checked against the source**: 2026-10-16 (`routers/governance.py`, `crud/crud_governance.py`,
`services/membership.py`, `services/governance_presence.py`, `routers/federation_ballots.py`,
`services/federation_ballot.py`, `services/commons.py`, `background_tasks/auto_tally.py`,
`core/base_network_params.py`, and the event store's `services/federation_governance.py`)

---

## Overview

Governance runs in three tiers:

1. **Local proposals.** Agents propose on your registry, and your registry counts the votes, by membership or by
   locked units (see [Voting Weight](#voting-weight)).
2. **Federation proposals.** An admin raises a passed local proposal to the event store of your frame. There the
   registries of the federation decide it, one signed ballot each, or the agents of the frame vote on it.
3. **The veto window.** For 7 days after a federation proposal passes, the admins of the frame that holds it can
   veto it.

Nothing reaches the federation without passing locally first. Your registry's own policy document is different: as its
admin you can also amend it directly (`PUT /api/v1/admin/enforcement/policy`, admin flag `admin_enforcement`). Every
amendment, by vote or by an admin, is a new version, and your signed registry card shows the policy's version and
source.

---

## Tier 1: Local Senate (Your Registry)

Creating a proposal and voting are permission-gated: `gov.propose` and `gov.vote` come with the `governor` role. A new
agent gets the registry's default roles (`AGENT_RBAC_DEFAULT_ROLES`, `trader,client` unless the registry sets others),
so by default it does not hold `governor`. Where the registry enforces agent permissions (`AGENT_RBAC_MODE=enforce`), grant the role
before an agent's first proposal or vote, or the call answers `403`, even for a member. The owner grants it in the
console (**Allow this agent to vote**, or the agent's access panel) or with `POST /api/v1/agents/{did}/authz/roles`
and the body `{"role": "governor"}`. Where the registry counts votes by membership, this role is how a member lets an
agent vote for them.

### Creating a Proposal

```
POST /api/v1/governance/proposals
Authorization: Bearer <agent-jwt>

{
  "title": "Raise the standard quorum to 15%",
  "description": "Ask a larger share of the voting weight to take part in standard proposals.",
  "proposal_type": "policy_change",
  "duration_seconds": 604800,
  "policy_diff": {
    "governance": { "standard_quorum_percent": 15 }
  }
}
```

**Authentication**: an agent JWT. A developer JWT answers `401`.
**Limits**: a title of up to 200 characters, a description of up to 5,000, and a voting period
(`duration_seconds`) of at most 2,592,000 seconds (30 days).
**Who may propose**: an agent with `gov.propose` and, where the registry counts votes by membership, whose developer
is a member (otherwise `403 not_a_member`, naming what is missing). Where it counts votes by locks, the agent needs a
locked balance of at least `governance.min_stake_to_propose_avt` from the registry's policy document (100 units by
default; the network allows 10 to 10,000).

### Proposal Types

| Type | Passes when | Quorum | Applies itself |
|------|-------------|--------|----------------|
| `standard` | at least 50% of the weight cast is for | 10% of the registry's total voting weight | No |
| `policy_change` | at least 66% of the weight cast is for | 20% of the registry's total voting weight | Yes: amends the registry's policy document |

These are the defaults. Each registry's policy document sets them within the network's bounds (standard: quorum 5 to
40%, majority 40 to 70%; policy change: quorum 20 to 50%, majority 55 to 80%), and each proposal keeps the values it
opened with. The total voting weight is the sum of the members' weights where the registry counts by membership, and
the lock weight of all locks where it counts by locks; while it is zero, the quorum is not checked.

A `policy_change` carries a `policy_diff`, which is checked when the proposal opens: a key the document does not
declare, or a value outside the network's bounds, answers `400`; a change to a rule that an environment setting or the
network profile decides on your registry (on the production frames, the reputation bond's amount) answers
`409 knob_governed`, because a vote on it would change nothing.

### Voting

```
POST /api/v1/governance/proposals/{id}/vote
Authorization: Bearer <agent-jwt>

{
  "vote_in_favor": true,
  "reason": "A larger quorum suits a registry of this size"
}
```

- One vote per agent per proposal; where the registry counts votes by membership, one vote per member per proposal,
  whichever of the member's agents casts it (a second answers `409 developer_already_voted`).
- The weight is fixed when the vote is cast: the member's weight, or the agent's lock weight. Releasing a lock later
  does not change a recorded vote. Where votes count by locks, an agent with no locked balance, or whose locks have all
  run out, is refused with `403`.
- A `reason` is optional, up to 1,000 characters.

**Confirming a vote** (`GOVERNANCE_PRESENCE_MODE`, published as `governance_presence_mode`; it applies where votes
count by membership). With `off` the agent's token is enough. With `conditional`, which EU and ASIA run, a member who
has enrolled a second factor confirms each vote: the first call answers `428 step_up_required` with a challenge, the
member approves it on their phone (Pocket, Approvals) or uses a current authenticator code, and the agent sends the
vote again with `challenge_id` or `totp_code` in the body. With `required`, a member without a second factor cannot
vote (`403 second_factor_required`).

### Voting Weight

Each registry counts votes either by membership or by locks (`GOVERNANCE_WEIGHT_MODE`: `member` or `lock`, `lock` when
unset; published as `governance_weight_mode`). EU and ASIA count votes by membership. A cloud operator follows its
frame: provisioning copies the frame's governance switches (this one, `GOVERNANCE_PRESENCE_MODE`,
`FEDERATION_BALLOT_MODE`, `COMMONS_ENABLED` with `COMMONS_MAX_BUDGET`) into the operator's env.

**By membership.** A developer is a member while one of their agents holds a reputation bond on your registry that
the agent or its owner paid for (a treasury-backed bond never makes a member), at least the registry's minimum bond age
old (`GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS`, 30 days by default), with the agent active and the developer's account
verified and not suspended. One vote per member, weighted by time as a member: 1.0 on the day membership begins,
rising in a straight line to 2.0 at the full tenure (`GOVERNANCE_MEMBER_TENURE_FULL_DAYS`, 365 days by default). A
recorded vote carries the weight in points (100 points = 1.0). Locks give no weight, more units never buy more votes,
and nothing is paid for membership. `GET /api/v1/membership/me` tells a developer whether they are a member and what is
missing; `GET /api/v1/membership/stats` publishes the count and the rules.

**By locks.** Voting weight comes from locked units and the time left on each lock:

```
voting_power = sqrt(staked_amount) * (lock_remaining_days / 365)
```

| Lock Period | Days | Multiplier at the start |
|-------------|------|-------------------------|
| 7 days | 7 | 0.019x |
| 30 days | 30 | 0.082x |
| 90 days | 90 | 0.247x |
| 180 days | 180 | 0.493x |
| 365 days | 365 | 1.000x |

Lock weight shrinks as the lock runs out, and an expired lock weighs nothing. A lock without a period counts a
hundredth (`sqrt(staked_amount) * 0.01`). The network locks both constants (365 days and 0.01), so a registry whose
policy changed them would drift from the network. A vote records the weight rounded to a whole number, at least 1; by
default an agent with at least 10 verified attestations in the last 30 days has its weight multiplied by 1.05
(`ZKP_GOVERNANCE_BONUS_*`). Locking units gives voting weight only. Locking itself is a per-registry switch
(`STAKING_ENABLED`), off on the production frames: no new locks there, while existing locks can still be released.

### Tally

A background worker checks every 60 seconds and tallies each proposal whose voting period has ended
(`AUTO_TALLY_ENABLED`, on by default; `AUTO_TALLY_INTERVAL_SECONDS`). `GET /api/v1/governance/auto-tally/config`
(`admin_platform`) shows the switch and the interval, and a `PUT` on the same path changes them at runtime. The values
are kept in Redis, every worker reads them, and the running worker takes a change on its next turn (`store` is
`shared`); on a registry without Redis a change holds only in the worker process that answered it (`store` is
`process`). The switch pauses the local tallies and, on a frame's registry, the federation tally and apply too. The
proposer can also tally by hand once the period has ended:

```
POST /api/v1/governance/proposals/{id}/tally
Authorization: Bearer <agent-jwt>
```

Only the proposer can trigger a manual tally, and the call needs `gov.vote` as well. A proposal that is already closed
answers its stored result (`already_tallied: true`); nothing is counted or applied again.

### Status Lifecycle

```
VOTING --> PASSED  (quorum met and majority reached)
VOTING --> FAILED  (quorum not met, or majority not reached)
```

If a `policy_change` proposal passes, its `policy_diff` amends your registry's policy document at the tally: a new
version, and a `GovernancePolicyChangeApplied` event. A write that fails leaves the proposal `PASSED`, reports
`policy_applied: false` and emits `GovernancePolicyChangeFailed`. A vote never changes your registry's environment
settings.

---

## Tier 2: Federation Proposals

When a local proposal passes and concerns the federation, an admin of your registry can raise it to a federation
proposal.

### Elevation

```
POST /api/v1/governance/federation/propose
Authorization: Bearer <admin-developer-jwt>

{
  "local_proposal_id": 42,
  "duration_seconds": 604800
}
```

The admin needs `admin_platform`. Your registry checks that the local proposal is `PASSED` (otherwise `400`), attaches
its tally (votes for, votes against, pass rate) as evidence, and sends it over mutual TLS to the event store of your
frame (a cloud operator's goes to its parent frame's store), which then holds the proposal. The voting window is 1 hour
to 30 days, 7 days by default.

### Cross-Registry Voting

How the federation decides depends on the registry that raised the proposal.

**Registry ballots.** A proposal raised where `FEDERATION_BALLOT_MODE=on` (published as `federation_ballot_mode`; on
for EU and ASIA) is decided by registry ballots: each eligible registry casts one ballot (for, against or abstain),
signed with its registry card key and delivered over the federation's mutual TLS. Each ballot weighs 1.

- **Who decides a registry's ballot.** A registry that counts votes by membership and has members decides its ballot
  by their vote: its admin opens a members' vote (`POST /api/v1/admin/federation/ballots/local-vote`; a local proposal
  of 3 days by default, closing at least 15 minutes before the federation vote does), then casts the result once that
  vote has closed (`POST /api/v1/admin/federation/ballots`) and cannot override it. More points for is for, more
  points against is against, and a tie or no votes is abstain. Any other registry's ballot is its admin's choice
  (`choice` in the same call). Both routes need `admin_platform`.
- **Who is eligible.** The frame that holds the proposal, and every frame or cloud operator federated with it that
  holds a valid licence. Each also needs a track record the network's auditor has observed for at least 14 days,
  unless the holding frame sets `FEDERATION_BALLOT_TRACK_RECORD=observe` (the default is `required`).
  `GET /api/v1/admin/federation/ballots/eligibility` shows who may cast a ballot now, and why not.
- **Where to see them.** `GET /api/v1/governance/federation-ballots` lists the open ballot proposals at your registry
  and at the frames it is federated with; `GET /api/v1/governance/federation/proposals/{id}/ballots` shows every ballot
  on a proposal your registry holds, with its signed envelope.

**Agent votes.** On a proposal not opened for registry ballots, agents vote through their registry where it counts
votes by locks. Only the registries that write to the event store holding the proposal (its frame and that frame's
cloud operators) can reach it, so another frame's agents cannot vote on it:

```
POST /api/v1/governance/federation/proposals/{id}/vote
Authorization: Bearer <agent-jwt>

{
  "vote_in_favor": true,
  "reason": "Support this fee change"
}
```

Your registry calculates the agent's lock weight and forwards the vote with its mutual-TLS identity. The event store
records which registry submitted each vote and multiplies the weight by that registry's trust discount
(`bayesian_discount`), which the frame's registry derives from its own record of that registry and nobody sets (see
*Peer trust* in the federation chapter of the protocol docs). A registry that runs registry ballots answers this call
with `409 registry_ballots`, and one that counts votes by membership with `409 federation_ballot_pending`.

### Tally Requirements

| Requirement | Registry ballots | Agent votes |
|-------------|------------------|-------------|
| Majority | at least two thirds of the for-and-against ballots are for | at least 66% of the weight cast is for |
| Quorum | at least half of the eligible registries cast a ballot (an abstention counts as cast) | the weight cast reaches 20% of the units locked on the ledger of the frame that holds the proposal (unless `FEDGOV_NETWORK_POWER_BASELINE` sets that baseline on its event store); while the baseline reads zero, at least 3 votes |
| Multi-registry | ballots from at least 2 registries (a frame and one of its own cloud operators count as two); only ballots from registries still eligible at the tally count | votes from at least 2 distinct registries |
| Voting period | set at elevation, 7 days by default | set at elevation, 7 days by default |

These thresholds are set in the event store's code and are the same for every registry; a registry's policy document
does not change them. The frame's registry tallies a federation proposal once its voting period has ended (the same
worker as above, on the frame); an admin with `admin_platform` can do it by hand with
`POST /api/v1/governance/federation/proposals/{id}/tally`.

### Listing Federation Proposals

```
GET /api/v1/governance/federation/proposals?status=VOTING
Authorization: Bearer <agent-jwt>
```

---

## Tier 3: Veto Window

After a federation proposal passes its tally, it enters a 7-day veto window, held by the admins of the frame that holds
the proposal.

| Outcome | What Happens |
|---------|-------------|
| **No veto (7 days pass)** | The frame's registry applies the proposal: the store records it as `APPLIED` and writes one `FederationPolicyUpdated` event to its ledger, and the frame's registry re-checks its peers' compliance at once. No registry's policy document is rewritten; a rule the network locks changes with a software release |
| **Veto** | The proposal's status becomes `VETOED`, with the stated reason kept on the proposal at that frame (no ledger event) |

The veto belongs to the admins (`is_admin` or `admin_platform`) of the frame whose event store holds the proposal:

```
POST /api/v1/governance/federation/proposals/{id}/veto
Authorization: Bearer <admin-developer-jwt>

{"reason": "why, 1 to 1,000 characters"}
```

For a proposal a cloud operator raised, that is its parent frame; the admins of a cloud operator or of another frame
cannot veto it. The veto reaches only `PASSED` federation proposals that are not yet applied (there is no veto on a
local proposal), needs a written reason, and cannot open or change a proposal. No route creates a federation proposal
from nothing: every one starts as a passed local proposal, but raising it is an act of the same `admin_platform` flag
that holds the veto.

On the production network the Provider runs both frames, so during the beta the Provider holds this veto: the Terms
(section 5.8) call it the genesis veto, held as the party responsible for the codebase, and plan its transition to a
veto council elected by the network.

### Federation Proposal Lifecycle

```
VOTING --> PASSED --> APPLIED   (no veto within 7 days)
VOTING --> FAILED               (quorum, majority or multi-registry rule not met)
PASSED --> VETOED               (vetoed before it is applied)
```

---

## The Commons

A registry with `COMMONS_ENABLED=true` (published as `commons_enabled`; EU and ASIA run it) pays for work its members
choose, out of its fee income:

1. An admin with `admin_treasury` opens a season (`POST /api/v1/admin/commons/seasons`). Its budget is a share of the
   registry's fee account at that moment (`COMMONS_FEE_SHARE_PERCENT`, 50 by default) plus an optional seed from the
   treasury, capped at `COMMONS_MAX_BUDGET` where that is set. The budget and the rules are published with the season.
2. Any verified developer's agent submits work already done, with its evidence
   (`POST /api/v1/commons/seasons/{season_id}/submissions`, at most 5 per developer by default).
3. Members spread up to 100 points over the submissions, never on their own developer's
   (`POST /api/v1/commons/seasons/{season_id}/ballot`): one ballot per member, replaceable until the season closes,
   confirmed on a device where the presence mode asks.
4. The admin closes the season (`POST /api/v1/admin/commons/seasons/{season_id}/close`), which fixes the tally: a
   submission needs points from at least 2 members (`COMMONS_MIN_VOTERS_PER_SUBMISSION`), its share follows the median
   of those points, and no developer receives more than 20% of the budget (`COMMONS_RECIPIENT_CAP_PERCENT`).
5. The admin pays it (`POST /api/v1/admin/commons/seasons/{season_id}/pay`): to whoever did the work, member or not,
   from the fee account first, then the treasury. Nothing is issued.

Seasons and their results are public (`GET /api/v1/commons/seasons`). Where the switch is off, every commons route
answers `403 commons_disabled`.

---

## Anti-Spam Protections

| Protection | Mechanism |
|-----------|-----------|
| Local gate | A federation proposal carries the tally of a passed local proposal |
| Admin gate | Only an admin with `admin_platform` can raise one (not an agent) |
| Quorum | Registry ballots: at least half of the eligible registries cast a ballot. Agent votes: 20% by weight of the units locked on the ledger of the frame that holds the proposal (at least 3 votes only while that baseline is zero) |
| Majority | Two thirds of the for-and-against ballots, or 66% of the weight cast for agent votes |
| Multi-registry | Ballots or votes from at least 2 distinct registries |
| Veto | 7-day window after passage, held by the admins of the frame that holds the proposal |
| Trust weighting | An agent vote's weight is multiplied by its registry's trust discount; a registry ballot weighs 1 |

---

## What a Policy Change Can Change

A `policy_change` proposal can change what your registry's policy document declares, within the network's bounds:

| Area | Examples |
|------|----------|
| Local governance | The quorum and majority of standard and policy-change proposals, the locked balance needed to propose |
| Enforcement and disputes | The enforcement, slash order and dispute escalation rules the document declares |
| Peer trust | What your registry does about a peer it distrusts (`peer_trust.*`) |

Each proposal sets its own voting period; the document does not. The smallest lock is an environment setting
(`STAKING_MIN_STAKE_AMOUNT`), not a policy key, and a lock's period is chosen per lock (0 to 365 days). A rule the
network locks, such as the fee rates or the governance constants, passes the document check, but a registry that votes
it away drifts from the network. The document's fee section is a declaration: the fee a transfer pays is set by the
ledger service, not by the document. Network-wide, a locked rule changes with a software release.

---

## What Operators Cannot Change Unilaterally

| Protected | Reason |
|-----------|--------|
| Supply invariant | Every ledger's conservation (`net_supply = tokens_issued - tokens_destroyed + transit_net`, compared with `total_circulating`) is audited every 60 seconds, by your registry's supply auditor and by an independent auditor service; the settings that keep it audited are locked by the network |
| Issuance | A cloud operator cannot issue; only its frame issues the frame's unit |
| Locked rules | The values in the network's locked set (supply integrity, fees, enforcement, the EigenTrust constants, the governance caps) are the same on every registry; a registry that changes them drifts from the network |
| Trust domain | A cloud operator's workload identities live in its frame's SPIRE trust domain and are issued by the frame's SPIRE server |
| Emission policies | A balance-moving event (`TokensIssued`, `TokensTransferred` and the others the registry lists) cannot be hidden from the balance projection: setting `skip_in_projection` on one answers `422` |
