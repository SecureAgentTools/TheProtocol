"""Agent-card federation pull-sync tests (W1/W2/W3/W4).

Validates that federated agent_cards replicate cross-registry via the
pull-sync worker. The reactor_agent_card_drift + federation_card_gc workers
maintain the cache.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    PULL_CYCLE_SEC as _PULL_CYCLE_SEC, propagated_subject as _propagated_subject,
)
from agentvault_registry.api_tests.federation_suite.peer_feed_probe import peer_feed_row

# ── §EVTYPES7 2026-09-06 — THE BUDGET WAS 1/1080th OF THE CADENCE ────────────
# `agent_card_pull_sync_alpha_sees_parent_agent` waited 20 SECONDS for a card to
# appear on the child. The agent-card pull-sync worker runs every 6 HOURS
# (`AGENT_CARD_PULLSYNC_INTERVAL_SEC`, default 21600, unset on both sandbox
# operators — measured). So no amount of waiting could ever make this pass: it
# passed only when `_pick_canary_did` happened to return an agent that had
# propagated in some earlier cycle, and it FAILED the moment a busy evening of
# sweeps filled the head of `discoverAgents` with fresh agents — a lottery over a
# population the rest of the suite changes.
#
# Waiting is the wrong instrument. The honest assertion is STEADY STATE: an agent
# old enough to have been through at least one pull cycle IS mirrored on the
# child. So the subject is chosen BY AGE, derived from `created_at`, and a run
# with no old-enough subject is a PRECONDITION, not a failure — the suite has a
# skip taxonomy precisely so that distinction survives.


def _unwrap_agents(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        # Common envelope keys for collections — extended for federation responses
        for k in ("agents", "items", "cards", "agent_cards", "data", "results",
                   "registries", "peers", "operators", "events"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
    return []


@federation_test(
    name="agent_card_pull_sync_alpha_sees_parent_agent",
    category="federation_pull_sync",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A", "sandboxalpha"],
    tags=["pull-sync", "frame-a"],
)
async def test_pull_sync_alpha(rig: FederationTestRig) -> AssertionResult:
    """An agent on sandbox-A that is OLD ENOUGH to have crossed a pull cycle
    is mirrored on sandboxalpha.

    Steady state, not propagation timing — see the module note: the worker's
    cadence is 6 h, so "wait for it to appear" was never a measurement this suite
    could make in a 20-second budget.
    """
    canary_did = ""
    result: dict = {}

    # V0615: past the first page when it holds only young agents (the rig's propagated_subject says why)
    canary_did, _subject_age, _eligible, _seen = await _propagated_subject(rig, "sandbox-A", _PULL_CYCLE_SEC)
    if not canary_did:
        raise PreconditionUnmet(
            "fixture propagation-subject absent: no agent on sandbox-A is "
            "older than one "
            "pull-sync cycle ({cycle}s) - {seen} candidate(s) seen, all too young "
            "to have been pulled yet. Not a pull-sync failure: there is nothing "
            "that could have propagated.".format(cycle=_PULL_CYCLE_SEC, seen=_seen)
        )

    async def predicate():
        nonlocal result
        try:
            r = await rig.mcp("sandboxalpha").call(
                "getAgentByDID", {"did": canary_did},
            )
            result = {"keys": list(r.keys())[:6] if isinstance(r, dict) else None}
            return isinstance(r, dict) and (
                r.get("did") == canary_did or r.get("agent_did") == canary_did
            )
        except Exception as e:
            result = {"error": repr(e)}
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description=(f"agent {canary_did[:32]}… (created {_subject_age/3600:.1f} h "
                     f"ago, > one {_PULL_CYCLE_SEC}s pull cycle) is mirrored on sandboxalpha"),
        capture_state=lambda: {"did": canary_did,
                               "subject_age_sec": round(_subject_age),
                               "pull_cycle_sec": _PULL_CYCLE_SEC,
                               "eligible_subjects": _eligible,
                               "result": result},
    )


@federation_test(
    name="agent_card_pull_sync_delta_sees_parent_agent",
    category="federation_pull_sync",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-B", "sandboxdelta"],
    tags=["pull-sync", "frame-b"],
)
async def test_pull_sync_delta(rig: FederationTestRig) -> AssertionResult:
    """An agent on sandbox-B that is OLD ENOUGH to have crossed a pull cycle
    is mirrored on sandboxdelta.

    Steady state, not propagation timing — see the module note: the worker's
    cadence is 6 h, so "wait for it to appear" was never a measurement this suite
    could make in a 20-second budget.
    """
    canary_did = ""
    result: dict = {}

    # V0615: past the first page when it holds only young agents (the rig's propagated_subject says why)
    canary_did, _subject_age, _eligible, _seen = await _propagated_subject(rig, "sandbox-B", _PULL_CYCLE_SEC)
    if not canary_did:
        raise PreconditionUnmet(
            "fixture propagation-subject absent: no agent on sandbox-B is "
            "older than one "
            "pull-sync cycle ({cycle}s) - {seen} candidate(s) seen, all too young "
            "to have been pulled yet. Not a pull-sync failure: there is nothing "
            "that could have propagated.".format(cycle=_PULL_CYCLE_SEC, seen=_seen)
        )

    async def predicate():
        nonlocal result
        try:
            r = await rig.mcp("sandboxdelta").call(
                "getAgentByDID", {"did": canary_did},
            )
            result = {"keys": list(r.keys())[:6] if isinstance(r, dict) else None}
            return isinstance(r, dict) and (
                r.get("did") == canary_did or r.get("agent_did") == canary_did
            )
        except Exception as e:
            result = {"error": repr(e)}
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description=(f"agent {canary_did[:32]}… (created {_subject_age/3600:.1f} h "
                     f"ago, > one {_PULL_CYCLE_SEC}s pull cycle) is mirrored on sandboxdelta"),
        capture_state=lambda: {"did": canary_did,
                               "subject_age_sec": round(_subject_age),
                               "pull_cycle_sec": _PULL_CYCLE_SEC,
                               "eligible_subjects": _eligible,
                               "result": result},
    )


@federation_test(
    name="federation_agent_cards_endpoint_reachable",
    category="federation_pull_sync",
    budget_sec=90.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["pull-sync", "listing", "mtls", "read-only"],
)
async def test_federation_agent_cards_listed(rig: FederationTestRig) -> AssertionResult:
    """§MCPTEST30 (V0547): the peers' agent-card feed (what the pull-sync worker reads), read the way a peer reads it
    (peer_feed_probe): sandbox-B's registry with its own SVID at the address its peer row names, and a caller with no
    certificate refused. This row called the MCP wrapper, which turned the route's 401 into an empty list, and passed on
    any dict: it could not fail."""
    return await peer_feed_row(rig, "/api/v1/federation/agent-cards?limit=5", "agent-card feed")


@federation_test(
    name="discover_agents_lists_federated_agents",
    category="federation_pull_sync",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["discover", "federation"],
)
async def test_discover_agents_each_registry(rig: FederationTestRig) -> AssertionResult:
    """discoverAgents returns ≥1 agent on every sandbox registry.

    An operator has no agents of its own, so on the two cloud operators every agent
    it lists has to arrive by federation. The question this row was left red for is
    answered (V0640, agentvault2-aa, 2026-10-25): the cards DO flow (146 mirrors on
    each operator of the pair nt261025x1), but GET /discover, the route this tool
    reads, took for its federated half only cards with agent_did NULL, and every
    mirror federation_sync stores carries agent_did, so it listed none. The row
    passed for weeks on the operators' only local agents, the opmoney pair left
    behind by its test; V0639's tester retires that pair once its verdict is in, and
    the row went red on the pair proof (sandboxalpha 0, sandboxdelta 0). Since V0640
    the mirrors pass discovery's one population rule (agent_cards.CARD_POPULATION_SQL,
    tests/test_discover_lists_mirrors.py), so an operator lists what its parent
    federates. `peer_registry_card_cache_populated` next door asserts sync health
    separately.
    """
    counts: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("discoverAgents", {"limit": 20})
                agents = _unwrap_agents(r)
                counts[label] = len(agents)
            except Exception as e:
                counts[label] = f"error: {e!r}"
        return all(isinstance(v, int) and v >= 1 for v in counts.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="discoverAgents finds ≥1 agent on every sandbox registry",
        capture_state=lambda: counts,
    )


@federation_test(
    name="federation_registries_listed_from_cloudop",
    category="federation_pull_sync",
    budget_sec=15.0,
    severity="medium",
    requires=["sandboxalpha", "sandboxdelta"],
    tags=["discover-registries", "federation"],
)
async def test_listed_federation_registries(rig: FederationTestRig) -> AssertionResult:
    """listFederationRegistries returns ≥1 entry on each cloud-op.

    Cloud-ops know their parent + (at minimum) one peer. Empty = pull-sync
    or federation_sync worker is dead.
    """
    counts: dict = {}

    async def predicate():
        for label in ("sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("listFederationRegistries", {})
                # Response shape: {"registries": [...], "total": N}
                if isinstance(r, dict):
                    total = r.get("total")
                    if isinstance(total, int):
                        counts[label] = total
                    else:
                        counts[label] = len(_unwrap_agents(r))
                else:
                    counts[label] = len(_unwrap_agents(r))
            except Exception as e:
                counts[label] = f"error: {e!r}"
        return all(isinstance(v, int) and v >= 1 for v in counts.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="listFederationRegistries non-empty on both cloud-ops",
        capture_state=lambda: counts,
    )
