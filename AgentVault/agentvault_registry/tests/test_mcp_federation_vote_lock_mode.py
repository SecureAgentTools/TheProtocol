"""§MCPTEST30 (V0640): where agents' locked units decide, an agent's federation vote is said by design on its own row.

Where registries decide by ballot or votes count by membership, the route refuses every agent's vote (409) and the
by-design lifecycle says so (V0636). Where agents' locked units decide (neither switch), the vote needs a federation
proposal no run can hold: raising one elevates a passed local proposal to every frame of the federation. The pair
nt261024x5a (2026-10-24 20:26Z) read the row "refusal only" (a vote on a made-up proposal, 400 "Federation proposal not
found"). Pinned: in lock mode the row is NOT MEASURED with that reason and the refusal is a refusal row held to a
400/404 that says "not found"; the ballot path is unchanged; a 403 does not pass for the rule under test.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_agent_public as EAP

VOTE = "theprotocol_federationVoteProposal"
LOCK_ROW = "refusal: federationVoteProposal an agent's vote on a federation proposal that does not exist"
BALLOT_ROW = "refusal: federationVoteProposal an agent's vote where registries or members decide"


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _run(config, vote=("400", 'HTTP 400: EventStore: {"detail":"Federation proposal not found"}')):
    async def rpc(tool, args, jwt="", timeout=20):
        if tool == "theprotocol_getPublicRegistryConfig":
            return True, _answer(config), "200"
        if tool == VOTE:
            return False, _error(vote[1]), vote[0]
        if tool == "theprotocol_guildCrossRegistryBid":
            return False, _error("HTTP 400: price is required"), "400"
        if tool in EAP.PEER_ONLY_READS or tool in {n for n, _ in getattr(EAP, "PEER_ONLY_DEV_TOOLS", ())}:
            return False, _error("HTTP 401: Federation authentication required"), "401"
        if tool in {t for t, _, _ in getattr(EAP, "NOT_DRIVEN", ())}:   # §MCPTEST30 (V0641)
            return False, _error("HTTP 404: not found"), "404"
        raise AssertionError(tool)

    outcomes = {}
    bag = SimpleNamespace(developer_jwt="d", sentinel_jwt="s", flow_values={})
    asyncio.run(EAP.lifecycle_earned_by_design(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes


def test_in_lock_mode_the_vote_is_by_design_and_its_refusal_a_refusal_row():
    out = _run({"governance_weight_mode": "lock"})
    assert out[VOTE]["skip_reason"].startswith("NOT MEASURED") and "locked units" in out[VOTE]["skip_reason"]
    assert out[LOCK_ROW]["healthy"] and out[LOCK_ROW]["status_code"] == 400 and BALLOT_ROW not in out


def test_where_ballots_decide_the_ballot_path_is_unchanged():
    out = _run({"federation_ballot_mode": True}, vote=("409", "HTTP 409: federation_ballot_pending: ballot"))
    assert "registries decide by one ballot" in out[VOTE]["skip_reason"] and out[BALLOT_ROW]["healthy"]
    assert LOCK_ROW not in out


def test_a_permission_refusal_does_not_pass_for_the_rule_under_test():
    out = _run({}, vote=("403", "HTTP 403: Agent lacks required permission: gov.vote"))
    assert not out[LOCK_ROW]["healthy"]
