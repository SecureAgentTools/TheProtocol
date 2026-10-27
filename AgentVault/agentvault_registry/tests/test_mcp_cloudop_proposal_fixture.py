"""§MCPTEST30 (V0545) — the cloud-op sweep reads a proposal the operator already holds, and says when it holds none.

Round 11: getProposalDetail, getProposalVotes and getMyVoteOnProposal skipped as "cloud-op fixture missing:
['proposal_id'] ... needs a fundable operator treasury (B8)" on both operator runs, while sbxbetaop held a proposal
(created on it 2026-09-05). Creating one locks a balance; READING one costs nothing, like the agent template pick
beside it. An operator that holds none is told apart from a read that failed: the first is "unavailable" with the
read that said so, the second stays "missing" (nothing was learned).

The same version makes the emission verdicts say when the TARGET read this run's store for the console (V0542's
relay): "ES-VERIFIED" alone sent a reader looking for a route the console does not have.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.routers import mcp_tester as mt


def _answer(obj, ok=True, code="200"):
    return ok, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                       "structuredContent": obj}}, code


def _pick(answer):
    seen = []

    async def call(target, tool, args, jwt="", timeout=30):
        seen.append((tool, dict(args), jwt))
        return answer
    out = asyncio.run(F.cloudop_pick_proposal(call, "op-target", "dev-jwt"))
    return out, seen


def test_a_held_proposal_is_picked_read_only_at_any_status():
    (pid, why), seen = _pick(_answer({"proposals": [{"id": None}, {"id": 7, "status": "TALLIED"}], "total": 2}))
    assert (pid, why) == ("7", None)
    assert seen == [("theprotocol_getGovernanceProposals", {"status": "all", "limit": 5}, "dev-jwt")], \
        "one read, every status (a closed proposal serves a read), as the operator admin"


def test_an_operator_holding_none_is_named_unavailable():
    (pid, why), _ = _pick(_answer({"proposals": [], "total": 0, "status_filter": "all"}))
    assert pid is None and "holds no governance proposal" in why and "locks a balance" in why


@pytest.mark.parametrize("answer", [
    _answer({"error": "governance/proposals answered HTTP 503", "proposals": None}),
    (False, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "boom"}}, "500"),
    _answer(["not", "a", "dict"]),
])
def test_a_read_that_carried_no_list_learns_nothing(answer):
    (pid, why), _ = _pick(answer)
    assert (pid, why) == (None, None), "a failed read must not claim the operator holds no proposal"


def test_the_skip_sentence_names_the_cause_it_measured():
    gen = F.cloudop_fixture_skip("theprotocol_getProposalVotes", ["proposal_id"], {}, {})
    assert gen.startswith("cloud-op fixture missing: ['proposal_id']") and "(B8)" in gen
    una = F.cloudop_fixture_skip("theprotocol_getProposalVotes", ["proposal_id"], {},
                                 {"proposal_id": F._CLOUDOP_NO_PROPOSAL})
    assert una == "cloud-op fixture unavailable: ['proposal_id'] — " + F._CLOUDOP_NO_PROPOSAL
    # one fixture unavailable and another merely missing: the generic sentence, never half a claim
    mixed = F.cloudop_fixture_skip("theprotocol_x", ["proposal_id", "scratch_listing"], {},
                                   {"proposal_id": F._CLOUDOP_NO_PROPOSAL})
    assert mixed.startswith("cloud-op fixture missing:")
    # the Guild switched off wins for a guild tool (§GUILDDARK), as before
    dark = F.cloudop_fixture_skip("theprotocol_guildGetOrder", ["guild_order_id"], {"guild": "GUILD_ENABLED unset"},
                                  {})
    assert dark == "cloud-op fixture unavailable: ['guild_order_id'] — GUILD_ENABLED unset"
    # the same cause named once even when two fixtures share it
    two = F.cloudop_fixture_skip("theprotocol_x", ["a", "b"], {}, {"a": "same why", "b": "same why"})
    assert two.count("same why") == 1


def test_the_unavailable_sentence_lands_in_the_operator_family():
    una = F.cloudop_fixture_skip("theprotocol_getProposalDetail", ["proposal_id"], {},
                                 {"proposal_id": F._CLOUDOP_NO_PROPOSAL})
    assert F.classify_tool_skip(una) == "cloudop_lacks_frame_fixture_or_flag"


def test_the_three_proposal_reads_wait_on_the_published_name():
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    for tool in ("theprotocol_getProposalDetail", "theprotocol_getProposalVotes", "theprotocol_getMyVoteOnProposal"):
        assert MCP_CONTRACTS[tool].arguments.get("proposal_id") == "${proposal_id}", tool


def test_the_relayed_store_is_named_in_the_verdicts():
    assert mt._local_read_note({}) == "" and mt._local_read_note(None) == ""
    note = mt._local_read_note({"__via_target__": "read THROUGH http://sbx-alpha-registry:8000 (store x)"})
    assert note == " · local events read THROUGH http://sbx-alpha-registry:8000 (store x)"


def test_every_ok_or_degraded_emission_verdict_carries_the_note():
    """The ok and degraded verdicts of local_emission and es_reachable: each sentence that claims the store was read
    ends with the note (read off the function's AST, counted per verdict, so a fifth verdict without it fails)."""
    import ast
    import inspect
    src = inspect.getsource(mt._compute_emission_integrity)
    tree = ast.parse(src)
    claims = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript)):
            continue
        key = node.targets[0].slice
        if not (isinstance(key, ast.Constant) and key.value in ("local_emission", "es_reachable")):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        fields = {k.value: v for k, v in zip(node.value.keys, node.value.values) if isinstance(k, ast.Constant)}
        status = fields.get("status")
        if isinstance(status, ast.Constant) and status.value in ("ok", "degraded"):
            claims += 1
            assert "_local_read_note(emit_diag)" in ast.unparse(fields["detail"]), ast.unparse(fields["detail"])[:120]
    assert claims == 4, f"expected the 4 ok/degraded verdicts, read {claims}"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
