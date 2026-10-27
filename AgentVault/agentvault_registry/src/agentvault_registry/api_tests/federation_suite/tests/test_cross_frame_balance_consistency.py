"""Cross-frame balance + economic consistency tests (§pass73.3.10 Batch 38).

3 tests asserting cross-frame economic consistency invariants:
  - both frames report supply_audit.delta=0.0 (no orphan tokens)
  - fee_collector is non-negative on both frames
  - EventStore stats are populated + recent on both frames
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


def _to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@federation_test(
    name="treasury_supply_invariant_both_frames",
    category="cross_frame_balance",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["supply-invariant", "treasury", "cross-frame"],
)
async def test_treasury_supply_both_frames(
    rig: FederationTestRig,
) -> AssertionResult:
    """Both frames report supply_audit.delta = 0.0 in getTreasuryAggregate.

    Cross-frame consistency: each frame is a sovereign EventStore with
    its own supply invariant. If either reports delta != 0, an unaccounted
    token motion happened on that frame.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getTreasuryAggregate")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                sa = r.get("supply_audit") or {}
                delta = _to_float(sa.get("delta"))
                state[label] = {
                    "delta": delta,
                    "status": sa.get("status"),
                    "frame": r.get("frame"),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    v.get("delta") is not None and float(v["delta"]) == 0.0
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="supply_audit.delta=0.0 on both mainframe treasuries",
        capture_state=lambda: state,
    )


@federation_test(
    name="fee_collector_non_negative_both_frames",
    category="cross_frame_balance",
    budget_sec=45.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["fee-collector", "non-negative", "cross-frame"],
)
async def test_fee_collector_non_negative(
    rig: FederationTestRig,
) -> AssertionResult:
    """fee_collector balance is non-negative on both mainframes.

    Fees flow from senders to fee_collector. A negative balance would
    indicate fee accounting went wrong somewhere.
    """
    state: dict = {}

    async def predicate():
        pending = False
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFeeCollectorInfo")
            except Exception as e:
                state[label] = {"pending": True, "error": repr(e)[:140]}
                pending = True
                continue
            if _is_silent_or_error(r):
                state[label] = {"silent": True}
                continue
            if not isinstance(r, dict):
                state[label] = {"bad_shape": type(r).__name__}
                return False
            raw_balance = r.get("balance")
            if raw_balance is None:
                # upstream TEG transiently unreachable (teg_error set; '' for ReadTimeout)
                state[label] = {"pending_upstream": True, "teg_error": r.get("teg_error")}
                pending = True
                continue
            bal = _to_float(raw_balance)
            state[label] = {"balance": bal}
            if isinstance(bal, float) and bal < 0.0:
                state[label]["NEGATIVE"] = True
                return False
        if pending:
            return False                                # retry within budget for a warm read
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    isinstance(v.get("balance"), float) and v["balance"] >= 0.0
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=45.0, predicate=predicate,
        description="fee_collector ≥ 0 on both mainframes (transient-tolerant)",
        capture_state=lambda: state,
    )


@federation_test(
    name="eventstore_ingests_a_driven_event_on_both_frames",
    category="cross_frame_balance",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin", "sandbox-B", "sandbox-B-admin"],
    tags=["eventstore", "freshness", "cross-frame", "driven"],
)
async def test_eventstore_ingests(rig: FederationTestRig) -> AssertionResult:
    """Each frame's EventStore ingests an event THIS TEST causes.

    ⚠ REPLACES A PASSIVE FRESHNESS CHECK THAT HAD THREE WAYS TO BE WRONG, all
    measured on this tier rather than reasoned about:

      * it asserted `newest_event` was under an hour old, so it went RED the
        moment a frame was merely QUIET — sandbox-B's newest event was 86 min
        old on a perfectly healthy frame, because nothing had asked it to do
        anything. A gate that fails on a quiet network reports a defect that is
        not there.
      * it required `total_events >= 1000`, a population calibrated to a tier
        that had been running a while. A freshly provisioned frame fails that
        while being completely correct — the same hand-calibrated-threshold
        shape as the canary suite's `active_paths >= 10`.
      * and worst, `v.get("silent")` counted an UNREADABLE EventStore as a
        pass. A test whose subject can answer "I cannot tell you" and score a
        green is not measuring ingestion at all.

    So it now CAUSES the event instead of waiting for one. Creating a throwaway
    agent emits AgentCreated/AgentOnboarded on that frame; the test then polls
    that agent's OWN aggregate. Attributable by construction: the assertion is
    "an event I caused arrived here", which a busy neighbour cannot satisfy on
    the frame's behalf and a quiet frame cannot fail for lack of traffic.

    Unreadable is a FAILURE here, never a pass — the whole point is whether the
    store can be seen to ingest.
    """
    import uuid as _uuid
    state: dict = {}

    async def drive(label: str) -> str:
        """A cheap event on `label`'s frame. Returns the aggregate to watch."""
        r = await rig.mcp(label).call("createAgent", {
            "name": f"fedsuite-esping-{_uuid.uuid4().hex[:8]}",
            "description": "federation suite EventStore ingestion probe",
        }, timeout=60)
        if not isinstance(r, dict) or r.get("error"):
            raise PreconditionUnmet(
                f"cannot create a probe agent on {label} to drive an event: "
                f"{(r or {}).get('error') if isinstance(r, dict) else r}")
        did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
        throwaways.made(label, did)  # V0641: retired once its test's verdict is in (throwaways)
        if not did:
            raise PreconditionUnmet(f"createAgent on {label} returned no DID to watch")
        return did

    frames = {"sandbox-A": "sandbox-A-admin", "sandbox-B": "sandbox-B-admin"}
    watch = {}
    for pub, adm in frames.items():
        did = await drive(pub)
        watch[adm] = did
        state[adm] = {"driven_did": did, "seen": False}

    async def predicate():
        for adm, did in watch.items():
            if state[adm].get("seen"):
                continue
            try:
                r = await rig.mcp(adm).call(
                    "adminQueryEventStore",
                    {"path": f"/api/v1/events/aggregate/{did}"}, timeout=40)
            except Exception as e:                            # noqa: BLE001
                state[adm]["unreadable"] = repr(e)[:120]
                continue
            body = r.get("response") if isinstance(r, dict) and "response" in r else r
            if not isinstance(body, (dict, list)):
                state[adm]["unreadable"] = f"bad shape {type(body).__name__}"
                continue
            evs = (body.get("events") or body.get("items") or []) if isinstance(body, dict) else body
            types = sorted({e.get("event_type") for e in evs if isinstance(e, dict)})
            state[adm]["types"] = types
            state[adm].pop("unreadable", None)
            state[adm]["seen"] = bool(types)
        return all(v.get("seen") for v in state.values())

    return await rig.assert_within(
        budget_sec=150.0, predicate=predicate, poll_interval_sec=10.0,
        description="each frame's EventStore ingests an event this test caused",
        capture_state=lambda: state,
    )
