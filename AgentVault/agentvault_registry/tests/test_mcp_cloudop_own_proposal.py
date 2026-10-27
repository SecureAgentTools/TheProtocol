"""§MCPTEST30 (V0640): an operator run votes and asks for the premature tally on a proposal of its own.

V0639 gave the operator sweep's sentinel `governor` for the run, so castVote and the premature tally reach their rules
there; but the proposal they were handed was cloudop_pick_proposal's read-only pick (V0545: any status, an earlier
run's). A preview of V0640's tester on V0638's operators (2026-10-24 23:11-23:19Z) read castVote red on both ("Proposal
4 is not open for voting"; on sbxbetaop a non-member refused for the proposal's state before membership was asked) and
the premature tally red ("Only the proposal creator can trigger the tally", HTTP 403). Pinned: the run opens a proposal
of its own through POST /governance/proposals as the sentinel, with a window that outlasts the run; where it cannot, it
says why, and the governance lifecycle then asks neither the vote nor the premature tally on the pick and says so on
castVote's row, the member row and the refusal row; with a proposal of its own the lifecycle is unchanged (control);
the operator sweep asks for one after the pick (read off its AST).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_fixtures as ef
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts import mcp_switches

TALLY_ROW = ef.refusal_row("theprotocol_tallyProposal", "a proposal whose voting period has not ended")
NO_OWN = "the sentinel could not open a proposal of its own (HTTP 403: not_a_member: Only members of this registry)"


def _open(answer):
    seen = []

    async def http(container, method, path, *, body=None, bearer="", **_kw):
        seen.append({"container": container, "method": method, "path": path, "bearer": bearer,
                     "body": json.loads(body) if body else None})
        return answer
    return asyncio.run(F.cloudop_open_own_proposal("op-registry", "sentinel-jwt", http=http)), seen


def test_the_run_opens_a_proposal_of_its_own_as_the_sentinel():
    (pid, why), seen = _open(("201", json.dumps({"id": 42, "status": "VOTING"})))
    assert (pid, why) == ("42", None)
    assert len(seen) == 1 and seen[0]["method"] == "POST" and seen[0]["path"] == "/api/v1/governance/proposals"
    assert seen[0]["bearer"] == "sentinel-jwt" and seen[0]["container"] == "op-registry"
    sent = seen[0]["body"]
    assert sent["duration_seconds"] == F._CLOUDOP_OWN_PROPOSAL_SECONDS >= 900, "the window outlasts a run"
    assert sent["proposal_type"] == "standard" and "MCP tester" in sent["title"]


def test_a_sentinel_that_may_not_open_one_says_why():
    (pid, why), _ = _open(("403", json.dumps({"error": "not_a_member",
                                              "message": "not_a_member: Only members of this registry can do this."})))
    assert pid is None and "HTTP 403" in why and "not_a_member" in why


def test_a_2xx_without_an_id_is_not_a_proposal():
    (pid, why), _ = _open(("200", "{}"))
    assert pid is None and "HTTP 200" in why


def test_no_sentinel_asks_nothing():
    async def http(*_a, **_kw):
        raise AssertionError("no call without a sentinel")
    pid, why = asyncio.run(F.cloudop_open_own_proposal("op-registry", "", http=http))
    assert pid is None and "no sentinel" in why


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _run(flow_values, mode=None):
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append(tool)
        if tool in ("theprotocol_getProposalDetail", "theprotocol_getProposalVotes", "theprotocol_getMyVoteOnProposal"):
            return True, _answer({"id": 4, "status": "VOTING", "votes": [], "has_voted": False}), "200"
        if tool == "theprotocol_getMyVotingPower":
            return True, _answer({"mode": "member", "canVote": True, "votingPower": 100}), "200"
        if tool == "theprotocol_castVote":
            return True, _answer({"status": "recorded", "voting_power": 100}), "200"
        if tool == "theprotocol_tallyProposal":
            return False, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text":
                           "Error: HTTP 400: Voting period has not ended yet"}], "isError": True}}, "400"
        raise AssertionError(tool)

    bag = SimpleNamespace(developer_jwt="dev", sentinel_jwt="sentinel", flow_values=dict(flow_values),
                          event_verifier=None, second_agent_jwt="", second_agent_did="")
    outcomes = {}
    token = mcp_switches._TARGET.set({"governance_weight_mode": mode} if mode else {})
    try:
        asyncio.run(L.lifecycle_governance_proposal_vote_tally(rpc, F._parse_rpc_result, bag, outcomes))
    finally:
        mcp_switches._TARGET.reset(token)
    return outcomes, calls


@pytest.mark.parametrize("mode", [None, "member"])
def test_without_a_proposal_of_its_own_neither_the_vote_nor_the_tally_is_asked_on_the_pick(mode):
    out, calls = _run({"proposal_id": "4", "proposal_vote_unavailable": NO_OWN}, mode)
    assert "theprotocol_castVote" not in calls and "theprotocol_tallyProposal" not in calls
    for row in ("theprotocol_castVote", TALLY_ROW) + ((L.MEMBER_VOTE_ROW,) if mode else ()):
        assert out[row]["skip_reason"].startswith("NOT MEASURED: no proposal of the run's own to vote on"), row
        assert NO_OWN in out[row]["skip_reason"] and not out[row]["healthy"], row
    # the reads still serve, on the pick
    assert out["theprotocol_getProposalDetail"]["healthy"] and out["theprotocol_getProposalVotes"]["healthy"]


def test_with_a_proposal_of_its_own_the_vote_and_the_premature_tally_are_asked():
    out, calls = _run({"proposal_id": "42"})
    assert "theprotocol_castVote" in calls and "theprotocol_tallyProposal" in calls
    assert out[TALLY_ROW]["healthy"] and out[TALLY_ROW]["status_code"] == 400
    assert not str(out["theprotocol_castVote"].get("skip_reason") or "").startswith("NOT MEASURED")


def test_the_operator_sweep_opens_one_after_the_pick():
    tree = ast.parse(textwrap.dedent(inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)))
    lines = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name in ("cloudop_pick_proposal", "cloudop_open_own_proposal"):
                lines.setdefault(name, n.lineno)
    assert set(lines) == {"cloudop_pick_proposal", "cloudop_open_own_proposal"}, lines
    assert lines["cloudop_pick_proposal"] < lines["cloudop_open_own_proposal"]
    keys = {n.slice.value for n in ast.walk(tree) if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store)
            and isinstance(getattr(n, "slice", None), ast.Constant)}
    assert "proposal_vote_unavailable" in keys


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
