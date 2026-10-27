"""§TWOAGENT G1 (V0437): the MCP chat surface reaches the whole G1 feature set.

With the chat flag ON at EU/ASIA, an MCP client could neither START a thread with someone on another registry
(sendChatMessage took only local targets) nor BLOCK anyone (no tool at all), nor LEAVE a thread (respondChatRequest
took accept/decline). The federation suite's G1 flows run through MCP, so each gap was also a test the suite could not
write. Now: sendChatMessage.target_remote_key, blockChatPrincipal / unblockChatPrincipal (all three ptypes), and
respondChatRequest action=leave; the two new tools are wired where every chat tool is (dispatch, tier 2 for the inline
agent_jwt swap, the audit tier set, the account category).

RED on 186ba26f: every test.
"""
from __future__ import annotations

import types

import pytest

HOME = "https://sandbox-b.test"


def _record(monkeypatch):
    from agentvault_registry.mcp import tools_agent as ta
    calls: list = []

    async def _req(auth, method, path, json_body=None, params=None, op_name=""):
        calls.append((method, path, json_body, op_name))
        return {"ok": True}
    monkeypatch.setattr(ta, "_chat_request", _req)
    return ta, calls, types.SimpleNamespace(auth_type="developer", raw_token="x")


async def test_a_thread_with_someone_on_another_registry_starts_by_address(monkeypatch):
    ta, calls, auth = _record(monkeypatch)
    await ta.chat_send_message(auth, "hello", target_remote_key=f"did:theprotocol:b:w@{HOME}", client_ref="ref-12345678")
    await ta.chat_send_message(auth, "hello", target_remote_key=f"ana@{HOME}", client_ref="ref-12345679")
    assert [(c[0], c[1], c[2]["target"]) for c in calls] == [
        ("POST", "/api/v1/chat/conversations", {"ptype": "agent", "remote_key": f"did:theprotocol:b:w@{HOME}"}),
        ("POST", "/api/v1/chat/conversations", {"ptype": "developer", "remote_key": f"ana@{HOME}"})]


async def test_a_principal_on_another_registry_can_be_blocked_and_unblocked(monkeypatch):
    ta, calls, auth = _record(monkeypatch)
    await ta.chat_block_principal(auth, "remote", remote_key=f"ana@{HOME}")
    await ta.chat_unblock_principal(auth, "remote", remote_key=f"ana@{HOME}")
    await ta.chat_block_principal(auth, "agent", agent_did="did:theprotocol:x")
    assert calls == [("POST", "/api/v1/chat/blocks", {"ptype": "remote", "remote_key": f"ana@{HOME}"}, "blockChatPrincipal"),
                     ("DELETE", "/api/v1/chat/blocks", {"ptype": "remote", "remote_key": f"ana@{HOME}"}, "unblockChatPrincipal"),
                     ("POST", "/api/v1/chat/blocks", {"ptype": "agent", "agent_did": "did:theprotocol:x"}, "blockChatPrincipal")]


async def test_an_incomplete_block_never_reaches_the_server(monkeypatch):
    ta, calls, auth = _record(monkeypatch)
    out = await ta.chat_block_principal(auth, "remote")
    assert "error" in out and calls == []


async def test_a_thread_can_be_left(monkeypatch):
    ta, calls, auth = _record(monkeypatch)
    await ta.chat_respond_request(auth, "conv-1", "leave")
    assert calls == [("POST", "/api/v1/chat/conversations/conv-1/leave", None, "respondChatRequest")]


def test_the_new_tools_are_wired_like_every_chat_tool():
    from agentvault_registry.mcp import audit, server, tool_categories
    from agentvault_registry.mcp.tools_agent import AGENT_TOOL_SCHEMAS
    names = {s["name"] for s in AGENT_TOOL_SCHEMAS}
    for tool in ("theprotocol_blockChatPrincipal", "theprotocol_unblockChatPrincipal"):
        assert tool in names and tool in server.TOOL_DISPATCH and tool in server.TIER2_TOOLS
        assert tool in audit._TIER_2_TOOLS
        assert tool_categories.PUBLIC_TOOL_CATEGORIES.get(tool.split("_", 1)[1]) == "account"
    send = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "theprotocol_sendChatMessage")
    assert "target_remote_key" in send["inputSchema"]["properties"]


async def test_a_chat_refusal_reaches_the_caller_with_its_reason(monkeypatch):
    """The consent ask is a 409 whose sentence tells the owner what to do. `_chat_request` left that sentence under
    `body`, and the dispatcher renders an error result as `Error: <error>` alone, so the caller read a bare status.
    Driven through the real formatter, with the prefix the refusal contracts pin still in place."""
    import httpx
    from agentvault_registry.mcp import server, tools_agent as ta

    detail = ("household_join_confirm: opening this thread tells the other side that you joined, as the owner of "
              "Scrivener. Open it again with join=true to continue.")

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **k):
            return httpx.Response(409, json={"detail": detail, "type": "about:blank", "title": "Conflict",
                                             "status": 409, "instance": "/x"})
    monkeypatch.setattr(ta.httpx, "AsyncClient", _Client)
    out = await ta.chat_read_thread(types.SimpleNamespace(auth_type="developer", raw_token="x"), "conv-1")
    text = server._tool_result_payload(out)["content"][0]["text"]
    assert text.startswith("Error: readThread returned HTTP")
    assert "household_join_confirm:" in text and "join=true" in text
