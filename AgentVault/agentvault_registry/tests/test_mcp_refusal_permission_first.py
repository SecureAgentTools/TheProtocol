"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): a refusal row whose route's permission check answers first is NOT
MEASURED, naming the permission, where the caller opts in.

agentvault2-66's operator sweeps on V0637 read two refusal rows red per operator: tallyProposal on a proposal whose
voting period has not ended (expected 400 "has not ended") and federationVoteProposal where members decide (expected
409 "ballot"), both answered 403 "Agent lacks required permission: gov..." on the sandbox operators, which enforce agent
permissions since V0637 and whose run agent holds no governance role. The rule under test was never reached. With
permission_first_unmeasured the row says so, NOT MEASURED; without it, and for a 403 that is not the permission check's,
the row stays the failure it was. The first test fails on V0637's earned_fixtures (no such option: the control).
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Tuple

from agentvault_registry.api_tests.contracts import earned_agent_public, earned_fixtures as ef, mcp_lifecycles

TOOL = "theprotocol_tallyProposal"
WHAT = "a proposal whose voting period has not ended"
ROW = "refusal: tallyProposal a proposal whose voting period has not ended"
DENIED = "Error: tallyProposal returned HTTP 403: Agent lacks required permission: gov.tally"


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else {}


class _Rpc:
    def __init__(self, answer: Tuple[bool, Dict[str, Any], str]):
        self.answer = answer

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        ok, result, code = self.answer
        return ok, {"result": result}, code


def _run(answer, **kw):
    out: Dict[str, dict] = {}
    passed = asyncio.run(ef.refusal_step(_Rpc(answer), _parse, TOOL, "2", {"proposal_id": "7"}, "j", out, WHAT,
                                         codes=(400,), text="has not ended", **kw))
    return passed, out[ROW]


def test_the_permission_checks_403_is_not_measured_where_the_caller_opts_in():
    passed, row = _run((False, {"_text": DENIED}, "403"), permission_first_unmeasured=True)
    assert passed is False and row["tool_name"] == ROW
    assert row["skip_reason"].startswith("NOT MEASURED: the agent permission check answered first (HTTP 403, gov.tally)")
    assert WHAT + " was not reached" in row["skip_reason"]


def test_without_the_option_the_403_stays_the_failure():
    passed, row = _run((False, {"_text": DENIED}, "403"))
    assert passed is False and row["healthy"] is False and "not one of [400]" in row["fail_reason"]


def test_a_403_that_is_not_the_permission_checks_stays_the_failure():
    passed, row = _run((False, {"_text": "Error: tallyProposal returned HTTP 403: proposals are closed here"}, "403"),
                       permission_first_unmeasured=True)
    assert passed is False and row["healthy"] is False and not row.get("skip_reason")


def test_the_rule_under_test_still_passes():
    passed, row = _run((False, {"_text": "Error: tallyProposal returned HTTP 400: Voting period has not ended"}, "400"),
                       permission_first_unmeasured=True)
    assert passed is True and row["healthy"] is True


def test_the_two_governance_refusals_opt_in():
    assert "codes=(400,), text='has not ended', permission_first_unmeasured=True" in inspect.getsource(
        mcp_lifecycles.lifecycle_governance_proposal_vote_tally)
    assert 'codes=(409,), text="ballot", permission_first_unmeasured=True' in inspect.getsource(earned_agent_public)
