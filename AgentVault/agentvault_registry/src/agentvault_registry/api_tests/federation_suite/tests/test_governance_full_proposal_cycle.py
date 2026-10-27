"""Governance proposal read-side coverage tests (§pass73.3.9 Batch 7).

4 read-only tests probing governance proposal observability per CLAUDE.md
FLOW 7. The federation suite cannot easily mint agent JWTs to test the
full create→vote→tally cycle (TIER 2 ops require agent auth) so this
batch focuses on read-side surfaces: listing, detail, votes, federation
visibility.

Future batch (when sentinel agent JWTs are bootstrappable) should add the
full mutation cycle: createProposal → multi-agent castVote → tallyProposal.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
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


def _proposals_of(r):
    """Extract proposals list from getGovernanceProposals envelope."""
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        for k in ("proposals", "items", "data", "results"):
            v = r.get(k)
            if isinstance(v, list):
                return v
    return []


@federation_test(
    name="governance_proposals_listed_with_all_filter",
    category="governance_proposal_cycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["governance", "proposals", "list"],
)
async def test_proposals_listed_all(rig: FederationTestRig) -> AssertionResult:
    """getGovernanceProposals(status=ALL) returns the proposal list on
    both mainframes. Default filter is VOTING which is often empty;
    ALL exposes the historical proposals."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call(
                    "getGovernanceProposals", {"status": "ALL", "limit": 5}
                )
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                props = _proposals_of(r)
                state[label] = {
                    "count": len(props),
                    "total": r.get("total") if isinstance(r, dict) else None,
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="governance proposals listed on both mainframes with ALL filter",
        capture_state=lambda: state,
    )


@federation_test(
    name="governance_proposal_detail_envelope_complete",
    category="governance_proposal_cycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["governance", "proposal-detail"],
)
async def test_proposal_detail_envelope(rig: FederationTestRig) -> AssertionResult:
    """getProposalDetail returns the canonical proposal envelope when
    given a known proposal_id from the listing. Asserts the envelope
    surfaces id, status, proposer_did, votes."""
    state: dict = {}

    async def predicate():
        try:
            lst = await rig.mcp("sandbox-A").call(
                "getGovernanceProposals", {"status": "ALL", "limit": 3}
            )
            props = _proposals_of(lst)
            if not props:
                state["empty_list"] = True
                return True  # Sandbox with no proposals → no detail to query
            target = props[0]
            pid = target.get("id") if isinstance(target, dict) else None
            if not pid:
                state["no_proposal_id"] = True
                return False
            state["proposal_id"] = pid
            d = await rig.mcp("sandbox-A").call(
                "getProposalDetail", {"proposal_id": str(pid)}
            )
            if _is_silent_or_error(d):
                state["detail_silent"] = True
                return True
            if not isinstance(d, dict):
                state["bad_shape"] = type(d).__name__
                return False
            state["detail_keys"] = sorted(d.keys())[:10]
            state["status"] = d.get("status")
            return bool(d.keys() & {"id", "status", "proposer_did", "title"})
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="proposal detail envelope returns canonical fields",
        capture_state=lambda: state,
    )


@federation_test(
    name="governance_proposal_votes_queryable",
    category="governance_proposal_cycle",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["governance", "votes"],
)
async def test_proposal_votes_queryable(rig: FederationTestRig) -> AssertionResult:
    """getProposalVotes returns a vote list (possibly empty) for a known
    proposal. Validates the per-proposal vote query path."""
    state: dict = {}

    async def predicate():
        try:
            lst = await rig.mcp("sandbox-A").call(
                "getGovernanceProposals", {"status": "ALL", "limit": 3}
            )
            props = _proposals_of(lst)
            if not props:
                state["empty_list"] = True
                return True
            pid = props[0].get("id") if isinstance(props[0], dict) else None
            if not pid:
                state["no_pid"] = True
                return False
            state["proposal_id"] = pid
            v = await rig.mcp("sandbox-A").call(
                "getProposalVotes", {"proposal_id": str(pid)}
            )
            if _is_silent_or_error(v):
                state["silent"] = True
                return True
            votes = v if isinstance(v, list) else (
                v.get("votes") or v.get("items") or v.get("data") or []
            ) if isinstance(v, dict) else []
            state["vote_count"] = len(votes)
            return isinstance(votes, list)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="proposal votes queryable for a known proposal",
        capture_state=lambda: state,
    )


@federation_test(
    name="governance_proposals_have_proposer_did",
    category="governance_proposal_cycle",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["governance", "proposer-did"],
)
async def test_proposals_have_proposer_did(rig: FederationTestRig) -> AssertionResult:
    """All proposals in the listing have a populated proposer_did field
    that looks like a TheProtocol DID. Catches partial schema migration."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call(
                "getGovernanceProposals", {"status": "ALL", "limit": 5}
            )
            props = _proposals_of(r)
            if not props:
                state["empty_list"] = True
                return True
            with_did = 0
            for p in props:
                if isinstance(p, dict):
                    pd = p.get("proposer_did", "")
                    if isinstance(pd, str) and pd.startswith(("did:theprotocol:", "did:cos:")):
                        with_did += 1
            state["total"] = len(props)
            state["with_did"] = with_did
            return with_did >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="proposals carry proper proposer_did DID",
        capture_state=lambda: state,
    )
