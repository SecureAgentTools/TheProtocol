"""The 146 event types no suite verifies (§FEDEVENTS batch 5).

Two earlier numbers of mine were wrong, both because a measurement's SCOPE was
narrower than the claim built on it. Corrected here, and the corrections are the
point of the file:

  1. **The census was keyword-only.** It read `event_type="X"` and could not see
     `_emit("GuildBidPlaced", ...)` or `_emit_legacy("ContractCreated", ...)` —
     114 sites and 84 event types, 40 of which have live rows in the EventStore.
     Widened: **330 emit sites, 256 distinct types** (was 217/172).
  2. **I said the suite verified 2 types.** The FEDERATION suite did. But
     `mcp_tester.py::_EMIT_MAP` maps **100 tools to 93 event types** and is
     consumed at `:1572` against a real EventStore poll with a `REAL MISS`
     failure state. That is substantial pre-existing coverage I reported as
     absent, because I only looked in `federation_suite/tests/`.

The honest picture, and what this file is for:

```
emitted types (widened census)          256
  verified by the MCP sweep (_EMIT_MAP)  93
  named by the federation suite          47
  union already covered                 110
  UNCOVERED                             146   ← this file
     observably firing here (class A)     30   → assert their SHAPE on real events
     never fire here (class B)           116   → structural only
```

Class A gets a shape contract because those events genuinely occur: contracts,
the exchange, guild orders, reward distribution, compliance polls. Driving them
would mean building flows for rails the suite does not otherwise exercise; the
events are already there to be read, so reading them is both cheaper and more
honest — it checks what the system actually emits rather than what a test can
provoke.

Class B cannot be driven at all: they fire on timeouts, breaches, quarantine,
multi-day windows. For those the emit SITE is the only available subject, and
batch 4 already gates it. What is added here is the **ratchet**: the uncovered
set may not GROW. A new event type must arrive either covered or deliberately
listed.

Δ-irrelevant: reads only.
"""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _done,
)
from agentvault_registry.api_tests.federation_suite.tests.test_event_emission_matrix import (
    _events_of_type,
)
from agentvault_registry.api_tests.federation_suite.tests.test_event_emission_contract import (
    _census, _VALUE,
)

_ADMIN = "sandbox-A-admin"

# The documented backlog: every emitted type that neither `_EMIT_MAP` nor the
# federation suite verifies, measured 2026-09-04. This is a CEILING — the
# ratchet fails when a type appears that is neither covered nor listed here.
# Entries marked `# observed` have live rows in the EventStore and are the ones
# the shape contract below actually reads.
_UNCOVERED_BASELINE: Set[str] = {
    # ── §MEMBERSHIP phase B 2026-10-02 (commons/v1, migration 0183) ──────────
    # (V0551, agentvault2-09: CommonsSeasonOpened, CommonsSeasonClosed and CommonsAwardPaid left this list: the MCP
    # tester carries the commons tools and maps them in _EMIT_MAP; the season lifecycle drives open and close.)
    # ── V0397 2026-09-17 ───────────────────────────────────────────────────
    # An admin broadcast addressed to ONE developer is audited under its own type, because every AdminBroadcastSent
    # is copied to all developers of each registry reading the same store. Coverage DEBT: the emission matrix drives
    # composeBroadcast against the sandbox pair, which runs an older image with no target_developer_id; the matrix
    # can drive a targeted notice once the pair runs V0397.
    "AdminDirectNoticeSent",             # V0397: POST /admin/broadcasts with target_developer_id
    # ── §NIGHTLYTRUTH 2026-09-14 ────────────────────────────────────────────
    # The ratchet fired on five NEW types (six once the census reads the conditional name as two): rails that
    # shipped in the 09-11/09-12 batches without emission coverage. Listed with the session that added each,
    # as coverage DEBT to be paid by the driven trust test (the two PeerTrust* actions and the state change
    # fire on the sandbox pair from the §TRUSTPOLICY recorder) and by the observed-shape test for the rest.
    "GovernancePolicyChangeFailed",      # §FRAMEPOLICY 2026-09-11: a policy amendment the validator refused
    "OrphanedListingsSwept",             # §BATCH0911: the AGORA sweep of listings whose org is gone
    "PeerTrustActionApplied",            # §TRUSTPOLICY 2026-09-11: a peer withheld from for trust
    "PeerTrustActionObserved",           # §TRUSTPOLICY 2026-09-11: the same decision in observe mode
    "PeerTrustStateChanged",             # §TRUSTPOLICY 2026-09-11: a peer moved between trust states
    "ReputationBondUnlocked",            # §BATCH0911: the bond returned when a service agent stops providing
    # ── §EVTYPES 2026-09-05 ────────────────────────────────────────────────
    # This ratchet fired on seven NEW uncovered types — the §REPBOND and
    # §ENFPROP rails shipped without emission coverage and nothing else noticed.
    # It did its job. Of the seven:
    #   • AgentReinstated is NOT listed here — it was a genuine MAP gap, now
    #     covered (`bulkReinstateAgents` → AgentReinstated in _EMIT_MAP). A stale
    #     comment in mcp_tester.py had claimed it "has NO live emitter anywhere in
    #     the tree" while admin_agents.py:1032 emitted it; corrected there.
    #   • the six below ARE deliberately listed, each with the reason it cannot be
    #     driven from a sweep. Two of them (EnforcementSlashWaterfallApplied,
    #     ReputationBondForfeited) DO fire on the sandbox — 26 rows each, from the
    #     §REPBOND enforcement proof, not from any test — so they are coverage DEBT,
    #     not dead rails. Recorded in EVENT_TYPE_MAP_2026-09-05.md; a driven test
    #     for the slash/forfeit path is the follow-up, and listing them here is what
    #     keeps that visible instead of silently green.
    "EnforcementSlashWaterfallApplied",   # fires (26 on sbx) via enforcement_engine._slash_waterfall; no MCP tool drives the whole waterfall
    "EnforcementSlashWaterfallPlanned",   # 0 on sbx: the PLAN half only emits when a waterfall is previewed, not applied
    "ReputationBondForfeited",            # fires (26 on sbx) from the slash path above; same missing driver
    "ReputationBondMatured",              # 0 on sbx: maturation is time-based (worker), unreachable inside a sweep
    "ReputationBondReleased",             # 0 on sbx: needs a matured bond + release cooldown to have elapsed
    "SlashWaterfallChanged",              # 0 on sbx: emitted only when the slash_waterfall POLICY SECTION is rewritten
    "AccountAnonymized",
    "AgentAutoEnrolled",
    "AgentCapabilityCircuitBreakerTripped",
    "AgentCardJWSVerifyFailed",
    "AgentCardPersistentDrift",
    "AgentCardPulled",
    "AgentFlaggedForJWSFailures",
    "AgentUpdated",
    "AgentXRegDelegationReceived",  # observed
    "AgentXRegDelegationRevoked",
    "AttestationDueReminder",
    "AttestationExpired",
    "AttestationReputationClawed",
    "BridgeTransferExpired",
    "BundleVisibilityChanged",
    "CICDNotificationSent",
    "CanaryRebalancerErrored",
    "CanaryRebalancerFunded",
    "CommandCenterAction",  # observed
    "CommandCenterProbe",  # observed
    "CommanderFlaggedDrift",  # observed
    "ComplianceBaselineRecorded",  # §TRUSTCHAIN: first-sight baseline, emitted once per peer
    # §MCPTEST30 V0561: an admin accepted a peer's reviewed policy as its baseline. Never driven by a sweep: accepting a
    # drift is an admin's decision, and a tester that took it would silence the drift monitor on the frame it tests.
    # The MCP tester measures the refusal (a hash the peer does not publish) and the unchanged path, which emit nothing.
    "ComplianceBaselineAccepted",
    "ComplianceDryRunDrift",
    "CompliancePollCycleCompleted",  # observed
    "ContractCancelled",
    "ContractDisputed",
    "ContractExpired",
    "ContractMirrored",
    "ContractResolved",
    "ContractTemplatePublished",
    "ContractTemplatePurchased",
    "CrossFrameTransferInitiated",
    "CrossFrameTransferRefunded",
    "CrossFrameTransferReversed",
    "CrossFrameTransferSettled",
    "CrossRegistryBlockedBySuspension",
    "DailyDistributionCompleted",  # observed
    "DeploymentWebhookExhausted",  # observed
    "DisputeCompensationApplied",
    "DisputeCompensationDeferred",
    "DisputeCompensationMinted",
    "DisputeCompensationRequest",
    "ExchangeCircuitBreakerSet",
    "ExchangeDividendDeclared",  # observed
    "ExchangeDividendPaid",  # observed
    "ExchangeListingApproved",  # observed
    "ExchangeListingCreated",  # observed
    "ExchangeListingHalted",
    "ExchangePriceBandSet",
    "ExchangeProposalOpened",
    "ExchangeProposalTallied",
    "ExchangeShareRefloated",
    "ExchangeSharesIssued",
    "ExchangeSharesSplit",
    "ExchangeStopTriggered",
    "ExchangeTradeExecuted",
    "ExchangeVoteCast",
    "FederationStateDriftDetected",  # observed
    "FiatPurchaseDisputed",
    "FiatPurchaseInitiated",
    "FiatPurchaseRefunded",
    "FiatPurchaseSettled",
    "FiatRoutedSettlementCompleted",
    "FiatRoutedSettlementInitiated",
    "FxRouteRefunded",
    "FxRouteSettled",
    "FxSwapRefunded",
    "FxSwapSettled",
    "GovernancePolicyChangeApplied",
    "GuildCredentialReceived",
    "GuildOrderCancelled",  # observed
    "GuildOrderDisputed",
    "GuildOrderResolved",
    "OperatorCliAction",
    "OperatorRenamed",
    "OrganizationAgentAuthorityBulkApplied",
    "OrganizationAgentAuthorityBulkRevoked",
    "OrganizationMemberRoleChanged",
    "OrganizationOwnershipTransferInitiated",
    "OrganizationOwnershipTransferred",
    "PeerRegistryUrlAutoCorrected",
    "PeerTopologyRefreshed",  # observed
    "PhoneSessionEnded",
    "PhoneSessionStarted",
    "ProposalAutoTallied",  # observed
    "RegistryCardUpdated",  # observed
    "RegulatoryAuthorizationRecorded",
    "RegulatoryAuthorizationRevoked",
    "RegulatoryCountersignBroken",
    "RewardsAutoCompoundSkipped",
    "RewardsAutoCompounded",  # observed
    "RewardsDistributed",  # observed
    "SettlementCompensationMinted",
    "SettlementFinalized",
    "SettlementRolledBack",
    "SettlementSagaInitiated",
    "SettlementSagaTimedOut",
    "SettlementSlashConfirmed",
    "SettlementSlashFailed",
    "SettlementSlashRequested",
    "SettlementTimeout",
    "StakeForceUnstaked",
    "SupplyInvariantBreach",
    "TreasuryBankruptcyQuarantineTriggered",
    "TreasuryQuarantineLifted",
    "TreasurySlashReceived",  # observed
    "WebhookRetryExhausted",
    "agent.health_changed",
    "agent.reinstated",
    "agent.slashed",
    "agent.suspended",
    "attestation.due_reminder",
    "attestation.expired",
    "attestation.revoked",
    "bridge.transfer_expired",
    "claim_reward.completed",
    "developer.reinstated",
    "developer.suspended",
    "federation.drift_detected",
    "federation.dry_run_drift",
    "federation.emission_policy_updated",
    "federation.peer_added",
    "frame_federation.revoked",
    "game.invite",
    "game.started",
    "operator.application_revoked",
    "stake.completed",
    "supply.invariant_breach",
    "test.ping",
    "treasury.balance_corrected",
    "unstake.completed",
    "webhook.retry_exhausted",
    "webhook.test",}

_AMOUNT_KEYS = re.compile(
    r"^(amount|balance|price|fee|total|value|payout|reward|stake|budget|"
    r"quantity|credit|debit|delta|remaining|approved_amount|requested_amount|"
    r"budget_total|budget_remaining|tx_volume)$")


def _emitted_types() -> Set[str]:
    return {r["event"] for r in _census()}


def _mcp_expected() -> Set[str]:
    """The tool→event map the MCP lifecycle sweep verifies.

    Read from source rather than duplicated here: a copy would drift, and the
    whole point of this file is that a scope which drifts from its subject
    reports confidence it has not earned.
    """
    import agentvault_registry
    p = os.path.join(os.path.dirname(agentvault_registry.__file__),
                     "routers", "mcp_tester.py")
    try:
        src = open(p, encoding="utf-8").read()
    except Exception:
        return set()
    out: Set[str] = set()
    for _tool, body in re.findall(r'"([A-Za-z0-9_]+)"\s*:\s*\[([^\]]*)\]', src):
        out.update(re.findall(r'"([A-Z][A-Za-z0-9_.]+)"', body))
    return out


def _federation_named(emitted: Set[str]) -> Set[str]:
    """Event types NAMED by a federation test — excluding this file.

    ⚠ THIS FILE MUST BE EXCLUDED, and a control is what proved it. The
    `_UNCOVERED_BASELINE` literal below lists all 146 uncovered type names as
    strings, so a scan that included this module found every one of them
    "named by the federation suite", computed `uncovered = 0`, and produced a
    ratchet that could never fire. The gate's own baseline had made its subject
    disappear.

    That is the day's recurring shape one more time — a check whose scope
    includes something other than the thing it is checking — and the reason the
    control suite mutates the baseline and demands a RED.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    self_name = os.path.basename(__file__).replace(".pyc", ".py")
    named: Set[str] = set()
    for fn in os.listdir(here):
        if not fn.endswith(".py") or fn == self_name:
            continue
        try:
            s = open(os.path.join(here, fn), encoding="utf-8").read()
        except Exception:
            continue
        for e in emitted:
            if f'"{e}"' in s or f"'{e}'" in s:
                named.add(e)
    return named


async def _stats_counts(rig) -> Optional[Dict[str, int]]:
    """Per-type event counts, or None when the EventStore cannot be READ.

    ⚠ `None` (unreadable) and `{}` (readable, no events yet) are DIFFERENT and
    both are returned. The first version collapsed them, because `{}` is falsy
    and every caller tested truthiness — so a fresh network with a perfectly
    healthy EventStore reported "projection stats unreadable" and would have
    sent an operator chasing a connectivity fault that did not exist. Found by
    the fresh-frame control, not by reading the code: the §VITALS
    could-not-check-versus-checked-and-empty distinction, which I had been
    careful about everywhere else in this file and lost here.
    """
    r, refused = await _call(rig, _ADMIN, "adminQueryEventStore",
                             {"path": "/api/v1/projections/stats"})
    if refused:
        return None
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    if not isinstance(body, dict):
        return None
    counts = body.get("event_counts")
    return counts if isinstance(counts, dict) else None


# ─── the ratchet ───────────────────────────────────────────────────────────

@federation_test(
    name="emission_coverage_ratchet",
    category="event_contract",
    budget_sec=120.0,
    severity="critical",
    requires=[],
    # §EVTYPES 2026-09-05: "no-probe" added. This ratchet is STRUCTURAL — it
    # censuses source and never touches the tier — so it makes zero probes, and
    # decorator.py marks a zero-probe PASS "vacuous" unless the test declares
    # itself structural. Its siblings in test_event_emission_contract.py already
    # carry the tag; this one did not, which nobody could see while it was
    # failing. The moment it went green it reported vacuous instead.
    tags=["no-probe", "event_emission", "contract", "ratchet", "static"],
)
async def test_emission_coverage_ratchet(rig: FederationTestRig) -> AssertionResult:
    """A new event type may not arrive uncovered and unnoticed.

    146 types are verified by nothing today. That number is not a failure to
    report — most of them fire only on breaches and timeouts — but it is a
    number that must not quietly grow, and until now nothing could tell whether
    it had. Adding an emission is a two-line change; adding one that no test
    ever looks at is the same two lines.

    The gate: every emitted type is verified by `_EMIT_MAP`, or named by the
    federation suite, or listed in the documented baseline above. Anything else
    is new and unaccounted for, and the failure names it.

    Also reports types that have DROPPED out of the baseline — a type that is no
    longer emitted at all is worth noticing too, because a renamed emitter
    leaves the old name in ledger history while nothing writes it any more.
    """
    emitted = _emitted_types()
    if len(emitted) < 200:
        raise PreconditionUnmet(
            f"census found only {len(emitted)} event types — it is reading the "
            f"wrong tree, and a small census would make this gate pass wrongly")
    mcp = _mcp_expected()
    fed = _federation_named(emitted)
    covered = (mcp | fed) & emitted
    uncovered = emitted - covered
    new_uncovered = sorted(uncovered - _UNCOVERED_BASELINE)
    retired = sorted(_UNCOVERED_BASELINE - emitted)
    state = {
        "emitted_types": len(emitted),
        "verified_by_mcp_emit_map": len(mcp & emitted),
        "named_by_federation_suite": len(fed),
        "covered_union": len(covered),
        "uncovered_now": len(uncovered),
        "uncovered_baseline": len(_UNCOVERED_BASELINE),
        "NEW_uncovered": new_uncovered[:25],
        "no_longer_emitted": retired[:25],
    }
    return _done(not new_uncovered,
                 "no event type is emitted without being covered or deliberately listed",
                 state)


# ─── class A: assert the shape of what actually fires ──────────────────────

@federation_test(
    name="observed_events_have_a_sound_shape",
    category="event_contract",
    budget_sec=240.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "contract", "shape"],
)
async def test_observed_events_have_a_sound_shape(rig: FederationTestRig) -> AssertionResult:
    """Every event type the EventStore has actually seen must be well formed.

    This is how the uncovered-but-firing types get tested without building
    flows for rails the suite does not otherwise exercise: contracts, the
    exchange, guild orders, reward distribution and the compliance poller all
    emit continuously, so their events can be READ rather than provoked. That
    is cheaper and it checks what the system emits rather than what a test can
    make it emit.

    The contract asserted is the minimum an audit record needs: a type, an
    aggregate that identifies the subject, and a dict payload. An event with no
    aggregate cannot be found from the entity it describes — the whole suite
    queries `/events/aggregate/{id}` — and one with a non-dict payload cannot be
    read by any consumer.
    """
    counts = await _stats_counts(rig)
    if counts is None:
        raise PreconditionUnmet("EventStore projection stats UNREADABLE — nothing was measured")
    if not counts:
        raise PreconditionUnmet(
            "EventStore is readable and holds NO events yet — a fresh frame, not a "
            "fault. `observed_uncovered_types_are_pinned` is the gate that still "
            "says something useful here")
    present = sorted(t for t, c in counts.items() if c)
    if len(present) < 20:
        raise PreconditionUnmet(f"only {len(present)} types have rows — too thin to assert on")

    bad_aggregate: List[str] = []
    bad_payload: List[str] = []
    unreadable: List[str] = []
    checked = 0
    for etype in present:
        evs = await _events_of_type(rig, etype, limit=3)
        if evs is None:
            unreadable.append(etype)
            continue
        if not evs:
            continue
        checked += 1
        for e in evs:
            agg = e.get("aggregate_id") or e.get("aggregateId")
            if not agg or not str(agg).strip():
                bad_aggregate.append(f"{etype}")
                break
        for e in evs:
            d = e.get("data") if "data" in e else e.get("payload")
            if d is not None and not isinstance(d, dict):
                bad_payload.append(f"{etype}:{type(d).__name__}")
                break

    state = {
        "types_with_rows": len(present),
        "types_inspected": checked,
        "types_unreadable": len(unreadable),
        "missing_aggregate": sorted(set(bad_aggregate))[:20],
        "non_dict_payload": sorted(set(bad_payload))[:20],
    }
    if checked < 20:
        raise PreconditionUnmet(
            f"only {checked} types could be inspected — a pass over that few would "
            f"be a claim about the probe, not about the events")
    return _done(not bad_aggregate and not bad_payload,
                 "every observed event type carries an aggregate and a dict payload", state)


@federation_test(
    name="observed_value_events_carry_parseable_amounts",
    category="event_contract",
    budget_sec=240.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "contract", "money"],
)
async def test_observed_value_events_carry_parseable_amounts(
        rig: FederationTestRig) -> AssertionResult:
    """Amounts in value-touching events must parse as Decimal.

    The supply invariant is arithmetic over these fields. A malformed amount is
    not a cosmetic defect: it either crashes the projection or, worse, is
    coerced and silently changes the number. Two shapes are known to appear
    here and both are asserted against — balances come back in SCIENTIFIC
    NOTATION (`"1E+3"`, on which `int()` RAISES), and `velocity_metrics.tx_volume`
    spent months as a BigInteger rounding sub-unit values to zero.

    `Decimal(str(v))` is the check because it accepts every legitimate form the
    platform uses — int, float, scientific-notation string — and rejects the
    ones that would corrupt a sum.
    """
    counts = await _stats_counts(rig)
    if counts is None:
        raise PreconditionUnmet("EventStore projection stats UNREADABLE — nothing was measured")
    if not counts:
        raise PreconditionUnmet(
            "EventStore is readable and holds NO events yet — no amounts exist to check")
    value_types = sorted(t for t, c in counts.items() if c and _VALUE.search(t))
    if not value_types:
        raise PreconditionUnmet("no value-touching event types have rows here")

    offenders: List[str] = []
    inspected = 0
    fields_seen = 0
    for etype in value_types:
        evs = await _events_of_type(rig, etype, limit=5)
        if not evs:
            continue
        inspected += 1
        for e in evs:
            d = e.get("data") or e.get("payload") or {}
            if not isinstance(d, dict):
                continue
            for k, v in d.items():
                if not _AMOUNT_KEYS.match(str(k)):
                    continue
                if v is None:
                    continue
                fields_seen += 1
                try:
                    Decimal(str(v))
                except (InvalidOperation, ValueError, TypeError):
                    offenders.append(f"{etype}.{k}={v!r}")
    state = {
        "value_types_with_rows": len(value_types),
        "types_inspected": inspected,
        "amount_fields_checked": fields_seen,
        "unparseable": sorted(set(offenders))[:20],
    }
    if fields_seen == 0:
        raise PreconditionUnmet(
            "no amount fields found in any value event — the field census matched "
            "nothing, so a pass would be about the matcher rather than the data")
    return _done(not offenders,
                 "every amount in a value-touching event parses as Decimal", state)


# ─── orphans in both directions ────────────────────────────────────────────

@federation_test(
    name="observed_event_types_have_an_emit_site",
    category="event_contract",
    budget_sec=120.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "contract", "drift"],
)
async def test_observed_event_types_have_an_emit_site(
        rig: FederationTestRig) -> AssertionResult:
    """A type in the ledger with no emitter in code is drift worth naming.

    Two things produce it and both matter. A RENAMED emitter leaves the old type
    in ledger history while nothing writes it any more — so a consumer keyed on
    the old name silently stops seeing anything. And a type written by something
    other than this registry (the TEG, the EventStore itself, a retired service)
    is a writer nobody here can account for.

    Reported rather than failed on its own: history legitimately outlives code,
    and a frame restored from a backup will carry types the current build no
    longer emits. What fails is the population GROWING past what was measured —
    the same ratchet discipline as the rest of this file.
    """
    counts = await _stats_counts(rig)
    if counts is None:
        raise PreconditionUnmet("EventStore projection stats UNREADABLE — nothing was measured")
    if not counts:
        # A readable-but-empty ledger genuinely HAS no orphans. That is a real
        # pass, not an absence of measurement.
        return _done(True, "the ledger holds no growing population of types nothing emits",
                     {"types_in_the_ledger": 0, "note": "fresh frame — no events yet"})
    emitted = _emitted_types()
    observed = {t for t, c in counts.items() if c}
    orphans = sorted(observed - emitted)
    state = {
        "types_in_the_ledger": len(observed),
        "types_emitted_by_code": len(emitted),
        "in_ledger_with_no_emit_site": len(orphans),
        "examples": orphans[:25],
    }
    # Ceiling measured 2026-09-04 on this tier, after the census was widened.
    return _done(len(orphans) <= 12,
                 "the ledger holds no growing population of types nothing emits", state)


# ─── the 30 that fire but nothing verifies ─────────────────────────────────

# Measured 2026-09-04: emitted by code, present in this frame's EventStore, and
# verified by neither `_EMIT_MAP` nor a federation test. These are the ones worth
# pinning BEFORE a fresh-network standup — on a frame with history the shape gate
# above covers them incidentally, but a NEW network has no rows at all, so that
# gate inspects nothing and passes having checked almost nothing. Exactly when it
# matters least. This list turns that silence into a checklist.
# ⚠ Six of these (the four contract-spine types, ContractCreated and GuildBidPlaced)
# are DRIVEN-covered as of 2026-09-04 and were removed from _UNCOVERED_BASELINE.
# They are kept HERE on purpose: this set is the fresh-frame standup checklist —
# "does this rail fire at all on a new network" — which stays worth asking about a
# money rail even once a test drives it. Membership here means observed, not uncovered.
_OBSERVED_UNCOVERED: Set[str] = {
    "AgentXRegDelegationReceived",
    # ⚠ The three org-treasury types are DRIVEN-covered as of 2026-09-04
    # (`test_org_treasury_economic.py` performs remit → fund → sweep and demands
    # the rows) and were removed from _UNCOVERED_BASELINE. They stay HERE for the
    # same reason the contract-spine four do: this set is the fresh-frame standup
    # checklist — "does this rail fire at all on a new network" — which stays
    # worth asking about a money rail even once a test drives it. Membership here
    # means OBSERVED, not uncovered.
    "OrganizationTreasuryFunded",
    "OrganizationTreasuryRemitted",
    "OrganizationTreasurySwept",
    "CommandCenterAction",
    "CommandCenterProbe",
    "CommanderFlaggedDrift",
    "CompliancePollCycleCompleted",
    "ContractAgreed",
    "ContractCreated",
    "ContractMilestoneReleased",
    "ContractMilestoneSubmitted",
    "ContractOffered",
    "DailyDistributionCompleted",
    "DeploymentWebhookExhausted",
    "ExchangeDividendDeclared",
    "ExchangeDividendPaid",
    "ExchangeListingApproved",
    "ExchangeListingCreated",
    "ExchangeOrderCancelled",
    "ExchangeOrderPlaced",
    "FederationStateDriftDetected",
    "GuildBidPlaced",
    "GuildOrderAwarded",
    "GuildOrderCancelled",
    "GuildOrderPosted",
    "GuildWorkSubmitted",
    "PeerTopologyRefreshed",
    "ProposalAutoTallied",
    "RegistryCardUpdated",
    "RewardsAutoCompounded",
    "RewardsDistributed",
    "TreasurySlashReceived",
}


@federation_test(
    name="observed_uncovered_types_are_pinned",
    category="event_contract",
    budget_sec=240.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "contract", "standup"],
)
async def test_observed_uncovered_types_are_pinned(
        rig: FederationTestRig) -> AssertionResult:
    """Pin the 30 types that fire here and nothing verifies.

    `observed_events_have_a_sound_shape` checks whatever the ledger happens to
    hold. That is the right instrument on an established frame and the wrong one
    on a fresh network: with no rows it inspects nothing, and its own
    "too few types to assert on" guard fires — a truthful skip that still leaves
    every one of these unverified on the day a new network is stood up and they
    begin firing for the first time.

    So this names them explicitly and reports THREE states per type:

      * observed + sound   — fired here and carries an aggregate + dict payload
      * observed + MALFORMED — fired and is wrong. The only failing state.
      * not yet observed   — has not fired on this frame. Not a failure; on a
        fresh network this list IS the standup acceptance checklist.

    Failing on "not yet observed" would make the test red on exactly the frame
    it exists to serve, which is how a gate earns the right to be ignored.
    """
    sound: List[str] = []
    malformed: List[str] = []
    not_yet: List[str] = []
    unreadable: List[str] = []

    for etype in sorted(_OBSERVED_UNCOVERED):
        evs = await _events_of_type(rig, etype, limit=3)
        if evs is None:
            unreadable.append(etype)
            continue
        if not evs:
            not_yet.append(etype)
            continue
        why = None
        for e in evs:
            agg = e.get("aggregate_id") or e.get("aggregateId")
            if not agg or not str(agg).strip():
                why = "no aggregate_id"
                break
            d = e.get("data") if "data" in e else e.get("payload")
            if d is not None and not isinstance(d, dict):
                why = f"payload is {type(d).__name__}"
                break
        (malformed.append(f"{etype}: {why}") if why else sound.append(etype))

    state = {
        "pinned_types": len(_OBSERVED_UNCOVERED),
        "observed_and_sound": len(sound),
        "observed_and_MALFORMED": malformed,
        "not_yet_observed_here": not_yet,
        "unreadable": unreadable,
    }
    if unreadable and not sound and not malformed:
        raise PreconditionUnmet(
            f"EventStore unreadable for all {len(unreadable)} pinned types — "
            f"nothing was measured")
    return _done(not malformed,
                 "every pinned type that has fired here is well formed", state)
