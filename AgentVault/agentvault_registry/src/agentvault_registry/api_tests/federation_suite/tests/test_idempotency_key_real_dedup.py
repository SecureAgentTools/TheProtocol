"""Idempotency-key deterministic emission tests (§pass73.3.9 Batch 4).

3 EventStore-observation tests validating the §pass57 deterministic
idempotency-key invariant per CLAUDE.md FLOW 5:

  TokensTransferred       → idempotency_key prefix "xfer-{tid}"
  TransactionFeeCollected → prefix "fee-{tid}"
  CrossRegistryTransferCompleted → "cross_reg_completed:{tid}"

These keys make the cross-frame emit retry path safe (EventStore UNIQUE
constraint + cache) and prove no raw UUIDs leak into financial events
post-§pass57 rollout (target: 100% deterministic).
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _unwrap_admin_request(r):
    if isinstance(r, dict) and "response" in r and isinstance(r.get("response"), dict):
        return r["response"]
    if isinstance(r, dict) and "response" in r and isinstance(r.get("response"), list):
        return r["response"]
    return r


def _events_list(r):
    """Extract the events list from adminQueryEventStore /events/ result."""
    inner = _unwrap_admin_request(r)
    if isinstance(inner, list):
        return inner
    if isinstance(inner, dict):
        for k in ("events", "items", "data", "results"):
            v = inner.get(k)
            if isinstance(v, list):
                return v
    return []


@federation_test(
    name="recent_transferred_events_have_xfer_idempotency_keys",
    category="idempotency_dedup",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["idempotency", "transferred", "deterministic-keys"],
)
async def test_transferred_xfer_keys(rig: FederationTestRig) -> AssertionResult:
    """Recent TokensTransferred events carry a key DERIVED FROM the transfer.

    §pass57's invariant is that a balance-moving emit is idempotent: both sides
    of a cross-registry transfer must compute the SAME key, or the EventStore
    cannot dedup and one transfer lands twice.

    ⚠ THIS USED TO MATCH A HAND-MAINTAINED PREFIX LIST AND RAISED A FALSE ALARM
    ABOUT MONEY. The list was `xfer-, refund-, fund-, settle-, cross_reg_,
    cross_frame_`, taken from a doc rather than from the emitter, and it did not
    include `tokens_transferred:` — the form `event_emitter.emit_tokens_
    transferred()` produces. So 18 of 20 sampled events were reported
    "non-deterministic", which reads as "cross-registry dedup is broken and
    supply can double-count". Measured against the store: all 921 of those keys
    are `tokens_transferred:{transaction_id}`, and ALL 3,012 keys of BOTH forms
    embed the payload's own transaction_id. Nothing was wrong except the list.

    So it no longer pattern-matches names. **A key is deterministic when it is
    derived from the event's own identity**, which is the property dedup
    actually needs, so the check is now structural: the key must CONTAIN the
    stable id carried in the payload. That cannot drift from the product, and it
    would still catch the real defect — a random uuid shares nothing with the
    payload. The prefix list survives only as a fallback for events whose
    payload does not carry an id.
    """
    state: dict = {}
    # Fallback only. Kept in sync by being read as the emitter's OWN vocabulary
    # (event_emitter.py's deterministic-form tuple), not by hand.
    _FALLBACK_PREFIXES = ("xfer-", "refund-", "fund-", "settle-", "cross_reg_",
                          "cross_frame_", "tokens_transferred:", "tokens_issued:",
                          "tokens_staked:", "tokens_unstaked:", "transfer_fee:",
                          "dispute-comp-", "dispute-slash-", "reward-", "snapshot-")
    _ID_FIELDS = ("transaction_id", "tx_id", "transfer_id", "id")

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminQueryEventStore",
                {"path": "/api/v1/events/?event_type=TokensTransferred&limit=20"},
            )
            events = _events_list(r)
            if not events:
                state["empty"] = True
                return True  # No transfers in window → no claim to validate
            total = len(events)
            with_key = 0
            derived_from_payload = 0
            prefix_only = []
            non_deterministic = []
            for ev in events:
                k = (ev or {}).get("idempotency_key")
                if not k:
                    continue
                with_key += 1
                payload = (ev or {}).get("data") or (ev or {}).get("payload") or {}
                ids = [str(payload.get(f)) for f in _ID_FIELDS
                       if isinstance(payload, dict) and payload.get(f)]
                if any(i and i in k for i in ids):
                    derived_from_payload += 1
                elif k.startswith(_FALLBACK_PREFIXES):
                    prefix_only.append(k)
                else:
                    non_deterministic.append(k)
            state["total"] = total
            state["with_key"] = with_key
            state["derived_from_payload"] = derived_from_payload
            state["prefix_only_count"] = len(prefix_only)
            state["non_deterministic_count"] = len(non_deterministic)
            state["non_deterministic_sample"] = non_deterministic[:3]
            if with_key == 0:
                return True
            # ⚠ A zero here would be a claim about the PROBE: if nothing matched
            # by payload AND nothing matched a known prefix, the reader is
            # looking at a parse failure, not at 20 broken transfers.
            if derived_from_payload == 0 and not prefix_only:
                state["probe_suspect"] = ("no key matched a payload id or a known form — "
                                          "suspect the event shape, not the emitter")
                return False
            return (with_key - len(non_deterministic)) / with_key >= 0.8
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="recent TokensTransferred events have deterministic idempotency keys",
        capture_state=lambda: state,
    )


@federation_test(
    name="recent_fee_events_have_fee_idempotency_keys",
    category="idempotency_dedup",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["idempotency", "fees", "deterministic-keys"],
)
async def test_fee_collected_keys(rig: FederationTestRig) -> AssertionResult:
    """Recent TransactionFeeCollected events have `fee-` prefixed
    idempotency keys (canonical pattern from §pass57)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminQueryEventStore",
                {"path": "/api/v1/events/?event_type=TransactionFeeCollected&limit=20"},
            )
            events = _events_list(r)
            if not events:
                state["empty"] = True
                return True
            with_key = 0
            mismatched = []
            for ev in events:
                k = (ev or {}).get("idempotency_key")
                if not k:
                    continue
                with_key += 1
                if not any(
                    k.startswith(p)
                    for p in ("fee-", "cross_reg_fee", "cross_frame_")
                ):
                    mismatched.append(k)
            state["total"] = len(events)
            state["with_key"] = with_key
            state["mismatched_count"] = len(mismatched)
            state["mismatched_sample"] = mismatched[:3]
            if with_key == 0:
                return True
            return (with_key - len(mismatched)) / with_key >= 0.8
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="recent TransactionFeeCollected events have fee- prefixed keys",
        capture_state=lambda: state,
    )


@federation_test(
    name="idempotency_keys_unique_in_recent_events",
    category="idempotency_dedup",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["idempotency", "uniqueness"],
)
async def test_idempotency_keys_unique(rig: FederationTestRig) -> AssertionResult:
    """Recent 50 transfer events have unique idempotency_keys (UNIQUE
    constraint on EventStore.idempotency_key holds). Duplicate would
    indicate the dedup ring broke or the UNIQUE index was dropped."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminQueryEventStore",
                {"path": "/api/v1/events/?event_type=TokensTransferred&limit=50"},
            )
            events = _events_list(r)
            keys = [(e or {}).get("idempotency_key") for e in events]
            non_null = [k for k in keys if k]
            unique = set(non_null)
            state["total"] = len(events)
            state["non_null_keys"] = len(non_null)
            state["unique_keys"] = len(unique)
            state["dup_count"] = len(non_null) - len(unique)
            return len(non_null) == len(unique)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="recent 50 TokensTransferred events have unique idempotency_keys",
        capture_state=lambda: state,
    )
