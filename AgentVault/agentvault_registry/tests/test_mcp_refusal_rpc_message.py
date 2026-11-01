"""§MCPTEST30 (V0651, agentvault2-d3, 2026-10-31): a refusal row reads the words of a refusal the MCP layer gives.

V0650's pair proof (nt261031x6, 14:28Z) failed one row: "refusal: decideChatApproval an agent's own token", HTTP 401
"but not for the rule under test". The refusal was right and in the contract's words: decideChatApproval is tier 3, the
tool's require_developer_auth raised MCPAuthError, and the dispatcher answered JSON-RPC -32001 "This tool requires
developer authentication. ..." (session-release reproduced it on sbx-beta, the same image). refusal_step matched its
words against `inner`, and `parse` keeps only `result`: a JSON-RPC error's message was never read. RED on the code
before: refusal_step does not see the message, and _exec_step has no keep_rpc_message.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Tuple

from agentvault_registry.api_tests.contracts import earned_ad_chat_approvals as CA
from agentvault_registry.api_tests.contracts import earned_fixtures as ef
from agentvault_registry.api_tests.contracts import mcp_lifecycles as M

TOOL = "theprotocol_decideChatApproval"
WHAT = "an agent's own token"
ROW = "refusal: decideChatApproval an agent's own token"
SAID = ("This tool requires developer authentication. Provide a developer JWT from POST /api/v1/auth/login as the "
        "Bearer token in the Authorization header.")


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else {}


class _Rpc:
    """Answers one JSON-RPC envelope, as the bridge returns it: (ok, body, the HTTP code)."""

    def __init__(self, body: Dict[str, Any], code: str):
        self.body, self.code = body, code

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20) -> Tuple[bool, dict, str]:
        return False, self.body, self.code


def _rpc_error(message: str, code: int = -32001) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}}


def _refuse(body: Dict[str, Any], code: str = "401", **kw) -> Tuple[bool, dict]:
    out: Dict[str, dict] = {}
    passed = asyncio.run(ef.refusal_step(_Rpc(body, code), _parse, TOOL, "3",
                                         {"conversation_id": "c", "decision": "approve"}, "agent-token", out, WHAT,
                                         text="requires developer authentication", **kw))
    return passed, out[ROW]


def test_the_words_in_a_json_rpc_error_pass_the_row():
    passed, row = _refuse(_rpc_error(SAID))
    assert passed is True and row["healthy"] is True and not row.get("fail_reason"), row
    assert "_rpc_message" not in row, "the message is read, never kept in the row"


def test_other_words_in_a_json_rpc_error_stay_red():
    passed, row = _refuse(_rpc_error("This tool requires agent authentication."))
    assert passed is False and "not for the rule under test" in row["fail_reason"], row


def test_words_in_the_tools_own_answer_still_pass():
    passed, row = _refuse({"jsonrpc": "2.0", "id": 1, "result": {"_text": "Error: HTTP 401: " + SAID}})
    assert passed is True and row["healthy"] is True, row


def test_a_code_outside_the_refusal_codes_stays_red_whatever_it_says():
    passed, row = _refuse(_rpc_error(SAID), code="200")
    assert passed is False and row["healthy"] is False, row


def test_a_permission_first_403_is_read_in_the_message_too():
    out: Dict[str, dict] = {}
    passed = asyncio.run(ef.refusal_step(
        _Rpc(_rpc_error("Agent lacks required permission: gov.tally"), "403"), _parse, "theprotocol_tallyProposal", "2",
        {"proposal_id": "7"}, "j", out, "a proposal whose voting period has not ended", codes=(400,),
        text="has not ended", permission_first_unmeasured=True))
    row = out["refusal: tallyProposal a proposal whose voting period has not ended"]
    assert passed is False and row["skip_reason"].startswith("NOT MEASURED: the agent permission check answered first")


def test_a_step_keeps_no_message_unless_its_caller_asks():
    for keep, want in ((False, False), (True, True)):
        out: Dict[str, dict] = {}
        asyncio.run(M._exec_step(_Rpc(_rpc_error(SAID), "401"), _parse, TOOL, "3", {}, "j", out,
                                 expect_status="error_4xx", keep_rpc_message=keep))
        assert ("_rpc_message" in out[TOOL]) is want, (keep, out[TOOL])
        if want:
            assert out[TOOL]["_rpc_message"].startswith("This tool requires developer authentication")


def test_the_chat_approvals_lifecycle_still_asks_for_the_contracts_words():
    src = inspect.getsource(CA.lifecycle_earn_chat_approvals)
    assert '"an agent\'s own token", text="requires developer authentication"' in src
