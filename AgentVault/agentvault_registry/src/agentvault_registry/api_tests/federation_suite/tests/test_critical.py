"""5 critical federation tests — Phase B of the federation suite (§pass73.3.4).

Coverage of 3 cross-registry mechanisms:
  - Broadcast pipeline (federation event → reactor materialization)
  - Federation peer admission (handshake state symmetry)
  - Pull-sync (agent_card replication across federated peers)
  - Cross-frame supply invariant (Δ=0 on all EventStores)

Phase B is intentionally light on state mutation. Phase C will add the
destructive economic + lifecycle tests with proper teardown patterns.
"""
from __future__ import annotations

import os as _os

import time

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.broadcast_cleanup import composed_id, retract_own
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    require_readable_eventstore,
    require_crossframe_es_replication,
    PULL_CYCLE_SEC, propagated_subject,
)


# ──────────────────────────────────────────────────────────────────────────
# 1. broadcast_propagation_mainframe_to_cloudop
# ──────────────────────────────────────────────────────────────────────────

@federation_test(
    name="broadcast_propagation_mainframe_to_cloudop",
    category="cross_registry_events",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin", "sandboxalpha-admin"],
    tags=["broadcast", "frame-a", "mainframe-to-cloudop"],
)
async def test_broadcast_propagation_mainframe_to_cloudop(
    rig: FederationTestRig,
) -> AssertionResult:
    """Compose a broadcast on sandbox-A (mainframe) and verify it materializes
    on sandboxalpha (cloud-op) via the federation reactor pipeline.

    Mechanism: sandbox-A emits AdminBroadcastSent → EventStore replicates →
    sandboxalpha reactor_admin_broadcast_received materializes local row
    keyed by (source_frame, idempotency_key).
    """
    # §FEDESWIRE: broadcast federation is ES-driven, and this target cannot read
    # an EventStore on this tier (its EVENT_STORE_URL points at the RETIRED
    # hetzner-es). Skip loudly rather than measure the wiring; a target whose
    # ES IS readable and still misses the broadcast stays RED.
    await require_readable_eventstore(rig, "sandboxalpha-admin")
    title_marker = f"fed-test-bcast-{int(time.time() * 1000)}"
    body = f"federation suite test broadcast {title_marker}"

    # Act — compose on mainframe
    compose_resp = await rig.mcp("sandbox-A-admin").call(
        "composeBroadcast",
        {"title": title_marker, "body": body, "broadcast_type": "info",
         "send_email": False, "requires_ack": False},
    )
    broadcast_id = (
        compose_resp.get("id")
        or compose_resp.get("broadcast", {}).get("id")
        or compose_resp.get("broadcast_id")
    )
    if not broadcast_id:
        # Some envelopes return the row directly; try common locations
        for k in ("data", "result"):
            v = compose_resp.get(k, {})
            if isinstance(v, dict) and v.get("id"):
                broadcast_id = v["id"]
                break

    # Assert — poll sandboxalpha admin broadcasts for our title marker
    seen_titles: list = []

    async def predicate():
        nonlocal seen_titles
        resp = await rig.mcp("sandboxalpha-admin").call("getAdminBroadcasts")
        # getAdminBroadcasts returns a BARE LIST (no envelope) — handle both shapes
        if isinstance(resp, list):
            broadcasts = resp
        elif isinstance(resp, dict):
            broadcasts = resp.get("broadcasts") or resp.get("items") or resp.get("data") or []
        else:
            broadcasts = []
        seen_titles = [b.get("title") for b in broadcasts if isinstance(b, dict)][:20]
        return any(b.get("title") == title_marker for b in broadcasts if isinstance(b, dict))

    async def capture_state():
        return {
            "title_marker": title_marker,
            "source_broadcast_id": broadcast_id,
            "seen_titles_on_cloudop": seen_titles[:10],
            "compose_response_keys": list(compose_resp.keys()) if isinstance(compose_resp, dict) else [],
        }

    result = await rig.assert_within(
        budget_sec=30.0,
        predicate=predicate,
        description=f"broadcast {title_marker!r} from sandbox-A reaches sandboxalpha",
        poll_interval_sec=2.0,
        capture_state=capture_state,
    )
    return await retract_own(rig, "sandbox-A-admin", composed_id(compose_resp) or broadcast_id, result)


# ──────────────────────────────────────────────────────────────────────────
# 2. broadcast_propagation_cross_frame_mainframes
# ──────────────────────────────────────────────────────────────────────────

@federation_test(
    name="broadcast_propagation_cross_frame_mainframes",
    category="cross_registry_events",
    budget_sec=45.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["broadcast", "cross-frame", "mainframe-to-mainframe"],
)
async def test_broadcast_propagation_cross_frame(
    rig: FederationTestRig,
) -> AssertionResult:
    """Compose on sandbox-A, verify materialization on sandbox-B.

    Mechanism: sandbox-A's AdminBroadcastSent → cross-frame replication
    (SF-4 / federation bus) → sandbox-B's reactor materializes locally.
    Longer budget than test #1 because cross-frame has an extra hop.
    """
    # §FEDESWIRE: the receiver's ES has never synced from a cross-frame peer on
    # this tier (its one peer row points at the RETIRED sandbox-events-b vhost),
    # so a broadcast has no road to travel. A peer that HAS synced and stopped
    # still goes RED.
    await require_crossframe_es_replication(rig, "sandbox-B-admin")
    title_marker = f"fed-test-cf-bcast-{int(time.time() * 1000)}"
    body = f"federation suite cross-frame broadcast {title_marker}"

    compose_resp = await rig.mcp("sandbox-A-admin").call(
        "composeBroadcast",
        {"title": title_marker, "body": body, "broadcast_type": "info"},
    )

    seen_titles: list = []

    async def predicate():
        nonlocal seen_titles
        resp = await rig.mcp("sandbox-B-admin").call("getAdminBroadcasts")
        if isinstance(resp, list):
            broadcasts = resp
        elif isinstance(resp, dict):
            broadcasts = resp.get("broadcasts") or resp.get("items") or resp.get("data") or []
        else:
            broadcasts = []
        seen_titles = [b.get("title") for b in broadcasts if isinstance(b, dict)][:20]
        return any(b.get("title") == title_marker for b in broadcasts if isinstance(b, dict))

    async def capture_state():
        return {
            "title_marker": title_marker,
            "seen_titles_on_sandbox_b": seen_titles[:10],
        }

    result = await rig.assert_within(
        budget_sec=45.0,
        predicate=predicate,
        description=f"broadcast {title_marker!r} reaches sandbox-B from sandbox-A (cross-frame)",
        poll_interval_sec=3.0,
        capture_state=capture_state,
    )
    return await retract_own(rig, "sandbox-A-admin", composed_id(compose_resp), result)


# ──────────────────────────────────────────────────────────────────────────
# 3. supply_invariant_holds_on_all_4_eventstores
# ──────────────────────────────────────────────────────────────────────────

@federation_test(
    name="supply_invariant_holds_on_all_eventstores",
    category="distributed_economic_state",
    budget_sec=30.0,
    severity="critical",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["supply", "invariant", "auditor", "all-frames"],
)
async def test_supply_invariant_all_eventstores(
    rig: FederationTestRig,
) -> AssertionResult:
    """Verify Δ=0 on every EventStore the rig can reach.

    Read-only assertion — does not generate load. Validates the auditor's
    static claim that supply is conserved within each EventStore at any
    instant.

    Only probes mainframes' admin bridges because cloud-op admins can't
    proxy adminQueryEventStore to the parent's EventStore (the cloud-op
    container has no event-store URL configured; adminQueryEventStore
    returns empty body). The 2 sandbox mainframes own the 2 distinct
    sandbox EventStores; cloud-ops share their parent's ES so this is
    not a coverage loss.
    """
    deltas: dict = {}

    async def predicate():
        nonlocal deltas
        deltas = {}
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call(
                    "adminQueryEventStore",
                    {"path": "/api/v1/projections/supply-audit"},
                )
                # adminQueryEventStore returns {"path","status_code","response":{...},"ok"}
                # The actual ES projection payload lives under "response"
                payload = r.get("response") if isinstance(r, dict) else None
                if not isinstance(payload, dict):
                    payload = r if isinstance(r, dict) else {}
                delta = payload.get("delta")
                deltas[label] = delta
            except Exception as e:
                deltas[label] = f"error: {e!r}"
        # Pass if every probe returned Δ=0 (or "0", "0.0", 0)
        for v in deltas.values():
            if isinstance(v, str) and v.startswith("error:"):
                return False
            try:
                if float(v) != 0.0:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    async def capture_state():
        return {"per_registry_delta": deltas}

    return await rig.assert_within(
        budget_sec=30.0,
        predicate=predicate,
        description="supply Δ=0 on every reachable EventStore",
        poll_interval_sec=2.0,
        capture_state=capture_state,
    )


# ──────────────────────────────────────────────────────────────────────────
# 4. federation_peer_visible_bidirectional
# ──────────────────────────────────────────────────────────────────────────

@federation_test(
    name="cloud_op_sees_parent_mainframe_as_peer",
    category="federation_handshake",
    budget_sec=15.0,
    severity="high",
    requires=["sandboxalpha-admin", "sandboxdelta-admin"],
    tags=["peer-admission", "handshake", "cloud-op-side"],
)
async def test_cloud_op_sees_parent(
    rig: FederationTestRig,
) -> AssertionResult:
    """Each cloud-op admin lists its parent mainframe in its peer set.

    Asymmetric model (the model federation actually uses): cloud-ops list
    their direct parent mainframe via getAllFederationPeersAdmin; mainframes
    list other MAINFRAMES (not their child cloud-ops — those are tracked in a
    separate cloud-operator lifecycle table). So we verify the cloud-op-side
    of the handshake on both surviving cloud-ops.

    sandboxalpha (frame-a child) must see its parent mainframe; sandboxdelta
    (frame-b child) likewise. The expected peer-name substrings default to the
    retired tier's names and are overridable via API_TEST_FED_{A,B}_PEER_MATCH.
    """
    views: dict = {}

    async def _peer_names_for(label: str) -> list:
        resp = await rig.mcp(label).call("getAllFederationPeersAdmin")
        peers = (
            resp.get("peers") or resp.get("items") or resp.get("data") or []
        ) if isinstance(resp, dict) else (resp if isinstance(resp, list) else [])
        return [
            (p.get("registry_id") or p.get("name") or p.get("peer_name") or "")
            for p in peers if isinstance(p, dict)
        ]

    async def predicate():
        nonlocal views
        try:
            alpha_names = await _peer_names_for("sandboxalpha-admin")
            delta_names = await _peer_names_for("sandboxdelta-admin")
            views = {
                "sandboxalpha_peers": alpha_names[:10],
                "sandboxdelta_peers": delta_names[:10],
            }
            # §FEDTARGETS: the parent's PEER NAME is tier-specific — the retired
            # tier used "registry-test"/"registry-test-b", a fresh tier uses its
            # own (e.g. "Sandbox Alpha"/"Sandbox Beta"). Env-overridable, old
            # literals as defaults, so a correct federation stops reading as a
            # failure just because the frames were renamed.
            _a_match = _os.getenv("API_TEST_FED_A_PEER_MATCH", "registry-test").lower()
            _b_match = _os.getenv("API_TEST_FED_B_PEER_MATCH", "registry-test-b").lower()
            alpha_sees_parent = any(_a_match in n.lower() for n in alpha_names)
            delta_sees_parent = any(
                _b_match in n.lower() or "test-b" in n.lower() for n in delta_names
            )
            return alpha_sees_parent and delta_sees_parent
        except Exception:
            return False

    async def capture_state():
        return views

    return await rig.assert_within(
        budget_sec=15.0,
        predicate=predicate,
        description="sandboxalpha sees sandbox-A AND sandboxdelta sees sandbox-B as federation peers",
        poll_interval_sec=2.0,
        capture_state=capture_state,
    )


# ──────────────────────────────────────────────────────────────────────────
# 5. agent_card_federation_pull_sync_works
# ──────────────────────────────────────────────────────────────────────────

@federation_test(
    name="agent_card_federation_pull_sync_works",
    category="federation_pull_sync",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A", "sandboxalpha"],
    tags=["pull-sync", "agent-card", "federation"],
)
async def test_agent_card_pull_sync(
    rig: FederationTestRig,
) -> AssertionResult:
    """A canary agent registered on sandbox-A should be visible on sandboxalpha
    via the federated agent-card cache (populated by the pull-sync worker).

    Discovery flow:
      1. Pick a known canary DID from sandbox-A's network stats / discover.
      2. Query sandboxalpha for the same DID via discoverAgents or
         listFederationAgentCards.
      3. Assert the agent is visible cross-registry within budget.
    """
    canary_did_on_parent: str = ""
    discovery_result_on_cloudop: dict = {}

    # Arrange — find a known canary DID on sandbox-A. Try multiple endpoints
    # to handle envelope variation; canary-sb-a's DID is stable across runs
    # but its DID changes after reset; query live.
    # §EVTYPES7 — subject chosen BY AGE, not by "the first canary-named row".
    # This test waited 20 s for a card that propagates on a 6 h cycle, so it could
    # only ever pass on an agent that had already crossed one; picking by name
    # alone let a FRESH canary-named agent in and turned a steady-state check into
    # a coin flip. Same rule as the two tests in test_pull_sync.py, imported from
    # the rig so there is one copy of it.
    # V0615: read past the first page when it holds only young agents (the rig's propagated_subject says why).
    canary_did_on_parent, _seen = "", 0
    try:
        canary_did_on_parent, _, _, _seen = await propagated_subject(rig, "sandbox-A", PULL_CYCLE_SEC)
    except Exception:
        pass

    if not canary_did_on_parent:
        # Nothing old enough to have propagated is a PRECONDITION, not a pull-sync
        # failure — there is no subject, so there is nothing to be wrong about.
        raise PreconditionUnmet(
            "fixture propagation-subject absent: no agent on sandbox-A is older "
            "than one pull-sync cycle ({c}s) - {n} candidate(s) seen".format(
                c=PULL_CYCLE_SEC, n=_seen)
        )

    # Assert — query sandboxalpha for the same DID
    async def predicate():
        nonlocal discovery_result_on_cloudop
        try:
            r = await rig.mcp("sandboxalpha").call(
                "getAgentByDID", {"did": canary_did_on_parent},
            )
            # ⚠ AN ERROR ENVELOPE IS NOT AN ABSENCE. A B6-shaped refusal
            # ({status_code, upstream_error, body, path}) means the QUERY failed,
            # which says nothing about whether the card propagated — reading it as
            # "not found" is the "classify by the body, never the status" rule
            # inverted. Recorded separately so a failing run says which it was.
            _errored = isinstance(r, dict) and isinstance(
                r.get("upstream_error"), str) and bool(r.get("upstream_error"))
            discovery_result_on_cloudop = {
                "found_keys": list(r.keys())[:10] if isinstance(r, dict) else [],
                "query_errored": _errored,
                "has_did": isinstance(r, dict) and (
                    r.get("did") == canary_did_on_parent
                    or r.get("agent_did") == canary_did_on_parent
                ),
            }
            return discovery_result_on_cloudop["has_did"]
        except Exception as e:
            discovery_result_on_cloudop = {"error": repr(e)}
            return False

    async def capture_state():
        return {
            "queried_did": canary_did_on_parent,
            "discovery_on_cloudop": discovery_result_on_cloudop,
        }

    return await rig.assert_within(
        budget_sec=20.0,
        predicate=predicate,
        description=f"agent {canary_did_on_parent[:32]}... visible on sandboxalpha via pull-sync",
        poll_interval_sec=2.0,
        capture_state=capture_state,
    )
