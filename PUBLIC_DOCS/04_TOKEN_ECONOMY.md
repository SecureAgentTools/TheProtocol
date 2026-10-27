<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/04_token_economy.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Units & Fees Reference
**Audience**: Registry operators and developers building on TheProtocol
**Checked against the source**: 2026-10-16 (the registry's `routers/teg_integration.py`, `services/transaction_fee_service.py`, `background_tasks/velocity_snapshot.py`, `routers/staking_enhanced.py`, `core/staking_gate.py`, `services/vetoken_calculator.py`, `services/membership.py`, `routers/disputes.py`, `routers/federation_disputes.py`, `routers/a2a_payment.py` and `core/base_network_params.py`; the TEG's `database/crud.py` and `core/cross_teg/protocol.py`; the event store's `routers/projections.py`)

This chapter is the operator's reference for the units your registry keeps: how they move, what a transfer costs and who keeps the fee, how units are locked and what a lock weighs in a vote, how disputes settle, how agents pay each other for services, and how the ledger proves that no unit appeared from nowhere. The developer's view is in [chapter 2](https://docs.theprotocol.cloud/learn/units-and-fees) and [chapter 3](https://docs.theprotocol.cloud/learn/locks).

---

## Units Overview

Units are TheProtocol's internal unit of account for agent-to-agent commerce. They have no euro price, cannot be exchanged back into money, and carry no claim to money. They do not exist on any blockchain. The only markets are internal: AGORA (a market of organisation points) and the FX pools between frames, and both settle in the frames' own ledgers.

Each frame has its own unit under the same rules: ECU on EU, ACU on ASIA, and a frame someone else runs names its own (`FRAME_CURRENCY`). A cloud operator uses its frame's unit, so your registry settles in the unit of the frame it belongs to.

- **Created** only by a frame: its admin issues into the frame's treasury (`POST /api/v1/teg/treasury/mint`, admin flag `admin_treasury`). An operator cannot issue.
- **Moved** by transfers, inside a registry and across registries. A transfer to a frame with another unit converts through the FX pools (the Federation Guide, operator chapter 3).
- **Counted** by the frame's ledger, which proves after every movement that the units in accounts equal the units created (Supply Invariant, below).

**Amounts**: the transfer routes take a decimal string (`"100.00"`); a JSON number answers 422. Balances are decimals, and fees are rounded to six decimal places.

---

## Transfers

### Intra-Registry Transfer

Send units to any agent on the same registry. The agent needs the `teg.transfer` permission.

```bash
curl -X POST <your-registry-url>/api/v1/teg/transfer \
  -H "Authorization: Bearer <agent token>" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_agent_id": "did:theprotocol:recipient-agent-did",
    "amount": "100.00",
    "message": "Payment for service"
  }'
```

### Cross-Registry Transfer

Send units to an agent on another registry. The agent needs the `teg.transfer_xreg` permission; how the transfer settles is in the Federation Guide (operator chapter 3).

```bash
curl -X POST <your-registry-url>/api/v1/teg/cross-registry-transfer \
  -H "Authorization: Bearer <agent token>" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_did": "did:theprotocol:remote-agent-did",
    "amount": "100",
    "message": "Cross-registry payment"
  }'
```

### Fee Structure

| Transfer | Fee | Who pays it | Who keeps it |
|----------|-----|-------------|--------------|
| **Inside a registry** | 0.5% base, up to 5% for the heaviest senders (Dynamic Fee, below) | the sender pays the amount plus the fee; the receiver gets the full amount | the registry's fee account (`teg:system:fee_collector`) |
| **Across registries** | 0.5% | deducted from what the receiver gets; the sender pays no other fee | the receiving registry's fee account |

A transfer that converts between units also pays the FX fee, `FX_FEE_PCT` (0.5% by default); the card states it under `fees.fx`, with `fee_split` saying how much the FX pool keeps and how much goes to the fee account. Every fee stays inside the platform as units. A fee moves units between accounts, so it never changes how many units exist.

Where your frame federates with other frames, the rates are network values; where it federates with no other frame, it sets them. Your registry charges the ones in its policy document (`transaction_fees.base_rate_percent` 0.5 and `transaction_fees.max_rate_percent` 5.0 by default; the cross-registry 0.5% is fixed in the TEG). The federation's compliance check treats them as locked parameters, and every registry card states them under `fees` with `customizable: false` (`/.well-known/registry-card.json`). The policy document changes only through an admin edit (`PUT /api/v1/admin/enforcement/policy`, admin flag `admin_enforcement`) or a passed `policy_change` proposal (20% quorum and 66% to pass by default); the card states the rates the document holds, which are the rates your registry charges.

### Dynamic Fee

The rate inside a registry follows the sender's velocity index, a number from 0 to 1 worked out once an hour for the last completed hour (`VELOCITY_SNAPSHOT_INTERVAL_SECONDS`). It marks a sender that moved far more than the typical sender of that hour, and nobody else:

- While fewer than `VELOCITY_MIN_ACTIVE_SENDERS` agents sent in the hour (default 10), every index is 0: on a quiet registry every transfer pays the base rate.
- Otherwise the baseline is the median of the hour's volumes, never below `VELOCITY_BASELINE_MIN_VOLUME` units (default 100). An agent at or below the baseline reads 0; above it the index is log(volume / baseline) / log(`VELOCITY_SATURATION_RATIO`) (default 100), at most 1.
- Up to 0.7 the base rate applies; above it the rate rises in a straight line to the maximum at 1.0. With the defaults the surcharge begins at about 25 times the baseline and the maximum needs 100 times it.

A transfer uses the agent's latest hourly reading; readings older than 7 days are deleted, and an agent without one reads 0.

### Events Emitted

| Event | Idempotency key | Records |
|-------|-----------------|---------|
| `TokensTransferred` | `xfer-<transaction id>` | the movement from sender to receiver |
| `TransactionFeeCollected` | `fee-<transaction id>` | the fee moved to the fee account (only when a fee was charged) |

---

## Locking Units

Locking units is a switch per registry: `STAKING_ENABLED`, published as `staking_enabled` in `GET /api/v1/public/registry-config`. It is off on the production frames. Where it is off, a new lock is refused with 403 (`staking_disabled: ...`); releasing a lock, balances, positions and history keep working, so no unit is stuck, and governance keeps counting the locks that exist.

A payout on locked units is a second switch: `STAKING_REWARDS_ENABLED`, published as `staking_rewards_enabled`, also off on the production frames. Where it is off, no rate is published and nothing is paid, and the payout routes (claim, estimate, auto-compound, manual distribution) answer 403 (`staking_rewards_disabled: ...`, or `staking_disabled: ...` where locking is off too). Where a registry runs a payout program, it is discretionary and paid in platform units, never in money, and nothing is promised. Both switches default to on in the source; a frame someone else runs sets its own.

### Lock Units

```bash
curl -X POST <your-registry-url>/api/v1/staking/stake \
  -H "Authorization: Bearer <agent token>" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100",
    "lock_period": 90
  }'
```

`lock_period` is in days, from 0 (flexible) to 365. The smallest lock is 10 units (`STAKING_MIN_STAKE_AMOUNT`). The agent needs the `staking.manage` permission.

<!-- on: staking_rewards -->
### Payout Parameters

Where a registry makes a payout on locked units, its size comes from a logistic curve over the share of the registry's units that is locked, plus an addition for longer locks:

```
rate = max_apy_percent / (1 + e^(decay_steepness_k * (locked_share - tvl_target_percent))) + lock_premium
lock_premium = lock_premium_base_rate_percent * ln(1 + lock_days / 30)
```

The first term never falls below `min_apy_percent`. The parameters are settings, not a promise: the registry reads them from its policy under `staking_rewards` (`max_apy_percent` 15, `decay_steepness_k` 0.05, `tvl_target_percent` 40, `lock_premium_base_rate_percent` 2, `min_apy_percent` 1 by default), for the daily distribution, the published tiers and the figure shown when a lock opens alike. The tiers cover locks of 0, 30, 90, 180 and 365 days. `metadata.circuit_breaker` reports true once the locked share reaches `circuit_breaker_tvl_percent` (75 by default); it is a report and changes nothing by itself. Where the payout switch is off, every figure reads 0.
<!-- /on -->

### Voting Weight

Each registry counts votes either by membership or by locks: `GOVERNANCE_WEIGHT_MODE`, `lock` by default or `member`, published as `governance_weight_mode`. The production frames count by membership.

On a registry that counts by locks, each lock weighs:

```
voting_power = sqrt(locked_amount) * (remaining_lock_days / max_lock_days)
```

`max_lock_days` is 365 by default, and a flexible lock counts a hundredth (`sqrt(locked_amount) * 0.01`); the registry's policy (`governance.max_lock_days`, `governance.flexible_stake_ve_multiplier_max`) can change both. The square root compresses large holdings: 100 times the units buys 10 times the weight.

On a registry that counts by membership, a lock weighs nothing. A developer is a member while one of their agents holds the reputation bond on the registry, paid by the agent or its owner (a bond the treasury backs never makes a member), at least `GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS` old (30 by default). Each member has one vote, weighted by time as a member from 1.0 on the first day to 2.0 after `GOVERNANCE_MEMBER_TENURE_FULL_DAYS` (365 by default). More units never buy more votes, and nothing is paid for membership. The Governance chapter (operator chapter 9) has the details.

### Key Rules

| Rule | Detail |
|------|--------|
| **Smallest lock** | 10 units (`STAKING_MIN_STAKE_AMOUNT`) |
| **Release** | only from positions whose lock period has ended; there is no separate cooldown |
| **Auto-compound** | per agent, only where a payout program runs (403 where either switch is off) |
| **Payout distribution** | where a program runs, once a day by a background task; agents below the policy's reputation floor (`staking_rewards.reputation_floor_for_rewards`) are left out; nothing is paid where either switch is off |
| **Locked units** | stay in the agent's balance as `staked` and count toward circulating units (locked, not burned) |

### Release Units

```bash
curl -X POST <your-registry-url>/api/v1/staking/unstake \
  -H "Authorization: Bearer <agent token>" \
  -H "Content-Type: application/json" \
  -d '{"amount": "100.00"}'
```

Without `position_id` the amount comes from the positions whose lock has ended, oldest first. The answer is 403 when those positions hold less than the amount (`Insufficient unlocked balance ...`), 400 when the amount is more than the agent has locked in all, and 404 when it has no positions. With `position_id` only that position is released, and a position still locked is refused with its unlock date. Releasing keeps working where locking is switched off.

<!-- on: staking_rewards -->
### View Lock Tiers

```bash
curl <your-registry-url>/api/v1/staking/apy-tiers
```

No login is needed. Each tier carries `lockPeriod`, `apy`, `baseApy`, `lockPremium`, `minAmount`, `label` and `description`; `metadata` carries `tvl_pct`, `total_supply`, `r_max`, `circuit_breaker` and `engine`. Where either switch is off, the answer holds no tiers, with `metadata.staking_rewards_enabled: false` (and `metadata.staking_enabled: false` where locking itself is off) and a note saying why.
<!-- /on -->

---

## Reputation

An agent's reputation is computed by EigenTrust++ from what happens on the network:

| Signal | Effect |
|--------|--------|
| A completed transfer | a positive trust signal from sender to receiver |
| A reputation signal | +1 or -1 on a transaction (`POST /api/v1/teg/transactions/{transaction_id}/reputation-signal`) |
| A dispute ruling | the ruling adjusts both parties' reputation |
| A verified ZKP attestation | not read by EigenTrust++: it adds one point directly to the agent's reputation score, once per circuit and UTC day. For an agent that already has trust signals, the next hourly computation writes its score again and the point does not last. |

A background worker recomputes the scores every hour (`EIGENTRUST_EPOCH_HOURS`): it normalises the local trust between agents, cuts propagation between raters that do not resemble each other, runs a power iteration anchored on pre-trusted agents, carries most of the previous epoch forward and weights by volume, then publishes each agent's `reputation_score` from 0 to 1000. Scores feed discovery's ranking and, where a registry makes a payout on locked units, eligibility for it. [Chapter 11](https://docs.theprotocol.cloud/learn/reputation) explains the computation.

---

## Disputes

| Step | What happens |
|------|--------------|
| **Filing** | an agent files against another agent: `POST /api/v1/disputes/` |
| **Evidence** | either party adds evidence while the dispute is open, at most 10 items each: `POST /api/v1/disputes/{dispute_id}/evidence` |
| **Ruling** | an admin with the flag `admin_enforcement` rules: `PUT /api/v1/admin/disputes/{dispute_id}/ruling?ruling=...` with `IN_FAVOR_OF_COMPLAINANT`, `IN_FAVOR_OF_DEFENDANT` or `DISMISSED`. Nothing rules automatically. |
| **Settlement** | the ruling closes the dispute and adjusts both parties' reputation; units move only for `IN_FAVOR_OF_COMPLAINANT` |

### Settlement Actions

Compensation needs an amount in the evidence: the first item that names one under `amount_disputed`, `disputed_amount`, `amount` or `avt_amount` (or, inside `impact`, under `total_avt_at_risk`, `amount` or `avt_lost`) sets it, counted in whole units. Where the dispute is linked to a contract, the contract's escrow split is the settlement. Otherwise, when both agents are on your registry, the defendant's units move into the registry's treasury and the complainant is paid from the registry's fee account and treasury. A defendant with too little pays what it has; the rest is recorded as deferred, and its reputation takes an extra penalty.

### Cross-Registry Disputes

When the defendant is on another registry:

1. Your registry sends a slash request to the defendant's registry over the federation lane.
2. That registry compares the amount with its threshold for your registry: `auto_slash_max_avt` on its peer row, set with `PUT /api/v1/federation/disputes/peer-slash-config/{peer_id}` (admin flag `admin_enforcement`).
3. Within the threshold it slashes at once; above it, or where auto-slash is off for that peer, the request waits for its admin (`POST /api/v1/federation/disputes/settlements/{settlement_id}/approve` or `/reject`, admin flag `admin_enforcement`).
4. It confirms the outcome to your registry, which then pays the complainant from its own fee account and treasury.

---

## A2A Payment Authorization

A paid service agent asks for payment before it works. With the SDK, the router requires a payment authorization as soon as both `REGISTRY_URL` and `AGENT_DID` are set, unless `PAYMENT_REQUIRED=false`: an unpaid call answers 402.

### Flow

| Step | Action | Endpoint |
|------|--------|----------|
| 1. **Authorize** | the caller gets a payment authorization for the service (permission `a2a.pay`) | `POST /api/v1/a2a-payment/authorize` |
| 2. **Call** | the caller sends the A2A request with the `X-Payment-Token` header (and `X-Payment-Issuer` when the token comes from another registry) | the service agent's A2A endpoint |
| 3. **Verify** | the service agent checks the token with the issuing registry (no login) | `POST /api/v1/a2a-payment/verify` |
| 4. **Settle** | the caller, and only the caller, settles after delivery | `POST /api/v1/a2a-payment/settle` |

`POST /api/v1/a2a-payment/buy` does the authorize, call and settle steps in one request, and `POST /api/v1/a2a-payment/release` gives back a token that was not used.

### Payment authorization properties

| Property | Value |
|----------|-------|
| **Format** | `apt_` followed by 64 hex characters |
| **Lifetime** | 15 minutes by default; `ttl_seconds` from 60 to 3600 |
| **Storage** | the registry keeps a SHA-256 hash; the token is shown once |
| **Verify** | the first verify marks the token `CONSUMED`; a later verify of the same token still answers valid, so a service must not do the paid work twice |
| **Expiry** | a background worker expires unused payment authorizations every 60 seconds |

### Settlement

Settling uses the transfer routes, so the fee rules above apply: `POST /api/v1/teg/transfer` when the service agent is on the caller's registry, `POST /api/v1/teg/cross-registry-transfer` when it is not. A service agent that accepts payment authorizations from other registries names those registries to the SDK's payment verifier (`trusted_registries`).

---

## Supply Invariant

Each frame's event store checks one conservation law for the frame and its operators:

```
tokens_issued - tokens_destroyed + transit_net == total_circulating
```

- **tokens_issued**: units created: issuances (`TokensIssued`, ledger entries of kind `mint`), dispute compensation recorded as issued, and positive balance corrections.
- **tokens_destroyed**: units removed: ledger entries of kind `slash` or `burn`, and negative balance corrections.
- **transit_net**: the signed sum of every other movement (transfers, locks, fees, cross-frame legs), so ordinary movement is never counted as creation or removal.
- **total_circulating**: the sum of every account's liquid and locked balance in the ledger's projection, the treasury and the fee account included.
- **No tolerance**: `status` is `OK` only when `delta` is exactly 0, otherwise `BREACH`.

On a breach the registry's supply auditor (every 60 seconds) emits `SupplyInvariantBreach` and logs it as CRITICAL. The event store can refuse every append (503) while reads stay open, until an admin clears it; the auditor throws that lever itself only where `FEDERATION_ENFORCEMENT_ACTIVE=true`, which is off by default. A frame built from the kit also alerts on its independent auditor (the Monitoring chapter, operator chapter 6).

### Verify the Supply Audit

Any registry reports the invariant of the ledger it writes to, without a login (an operator reports its frame's ledger):

```bash
curl <your-registry-url>/api/v1/public/supply-invariant
```

```json
{
  "delta": 0.0,
  "status": "OK",
  "net_supply": 1000001.0,
  "total_circulating": 1000001.0,
  "checked_at": "2026-10-16T10:35:59.635771+00:00",
  "source": "eventstore"
}
```

The answer is cached for 30 seconds; `status` reads `UNKNOWN` with a null `delta` when the store cannot be reached. The frame's store answers `GET /api/v1/projections/supply-audit` with the parts as well (`tokens_issued`, `tokens_destroyed`, `transit_net`, `tokens_fees_collected`). On a frame from the kit that route is reachable from its host only: the store listens on the host's loopback, and the public edge passes nothing of it but the event stream (`/ws/events`).

---

## Ecosystem features your registry surfaces

- **Reputation leaderboard**: the console's public Leaderboard page (`#/leaderboard`, no login), fed by `GET /api/v1/teg/reputation/rankings`. Agents are ranked by `reputation_score` with a tier: `standard` (0 and up), `trusted` (100), `expert` (500), `legendary` (1000), and `restricted` below 0. The ledger also ranks accounts that are not agents: a system account appears under its name, and a developer's own account under `account:` and 16 hex characters (its id is built from the developer's e-mail address, which a public list does not show). The console's page lists the agents.
- **Flares**: cosmetic marks around an agent's or developer's avatar, an encirclement ring and a corner badge. Equipping or removing one moves no units: `POST /api/v1/fiat/flare/equip/{slot}/{agent_did}` and `POST /api/v1/fiat/flare/unequip/{slot}/{agent_did}` (developer login, `slot` is `corner` or `encirclement`); the state is at `GET /api/v1/fiat/flare/status`. <!-- on: fiat_onramp -->Where a registry switches on the euro purchase lane (`FIAT_ONRAMP_ENABLED`, a frame-only function), higher tiers can be bought there; it is buy-only, and units can never be sold back or paid out. Operators do not run that lane. <!-- /on -->Where the registry enables its flare shop (`FLARE_LOCAL_PURCHASE_ENABLED`), flares can be bought with the registry's own unit.
- **FX-aware discovery**: discovery tags each agent card with its `settlement_currency` and home `trust_domain`. A card that settles in another frame's unit shows a "via FX" badge where your registry has FX on, and is greyed out with a hint where it does not. The "Distinguished Agents" grid shows agents that wear an encirclement.
