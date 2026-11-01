"""V0652 (w) (order gwo_213e530b4ca2de3130c4a1d1, agentvault2-14, 2026-10-31): OurChat for a phone client over MCP.

The maintainer, from his phone (the sessions' room, seq 225): "the Claude phone integration lost of tools to use needs
whole ourchat endpoints too if the agent is permitted to use it ... I would like to update it so I can use Claude
integration on the chat with direct voice or chat". The set a phone client lives on; each new tool is EXACTLY its route
(the route decides who may: no new grant, RBAC unchanged), dual-auth like the chat tools (a developer key passes
through, agent_jwt speaks as an agent), but the cross-room list of what waits on you, a decider's read (tier 3). The
descriptions are written to be spoken. Each case fails on 05441be31 (the V0651 recut), which has none of the five.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from agentvault_registry.mcp import audit, server
from agentvault_registry.mcp import tools_agent as ta

NEW = ["theprotocol_markChatRead", "theprotocol_getChatUnreadCount", "theprotocol_listChatApprovals",
       "theprotocol_listWaitingChatApprovals", "theprotocol_getChatAttachment"]
AUTH = types.SimpleNamespace(auth_type="developer", raw_token="tok")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def _req(auth, method, path, json_body=None, params=None, op_name="", timeout=None):
        seen.append((method, path, json_body, params, op_name))
        return {"ok": True}

    monkeypatch.setattr(ta, "_chat_request", _req)
    return seen


def test_each_tool_is_exactly_its_route(calls):
    run(ta.chat_mark_read(AUTH, "room 1", 12))
    run(ta.chat_unread_count(AUTH))
    run(ta.chat_list_approvals(AUTH, "room-1"))
    run(ta.chat_list_approvals(AUTH, "room-1", status="all", limit=999))
    run(ta.chat_waiting_approvals(AUTH, limit=0))
    assert calls == [
        ("POST", "/api/v1/chat/conversations/room%201/read", {"seq": 12}, None, "markChatRead"),
        ("GET", "/api/v1/chat/unread-count", None, None, "getChatUnreadCount"),
        ("GET", "/api/v1/chat/conversations/room-1/approvals", None, {"status": "pending", "limit": 50},
         "listChatApprovals"),
        ("GET", "/api/v1/chat/conversations/room-1/approvals", None, {"status": "all", "limit": 200}, "listChatApprovals"),
        ("GET", "/api/v1/chat/approvals", None, {"limit": 50}, "listWaitingChatApprovals"),
    ]


def test_what_cannot_be_asked_never_reaches_the_route(calls):
    assert "conversation_id" in run(ta.chat_mark_read(AUTH, "", 1))["error"]
    assert "seq" in run(ta.chat_mark_read(AUTH, "room-1", "x"))["error"]
    assert "status" in run(ta.chat_list_approvals(AUTH, "room-1", status="maybe"))["error"]
    assert "conversation_id" in run(ta.chat_list_approvals(AUTH, ""))["error"]
    assert calls == []


def test_a_shared_text_file_reads_as_text_and_any_other_as_its_name():
    a = ta.attachment_answer("att-1", "plan.md", "# Plan\nship it".encode())
    assert a["text"] == "# Plan\nship it" and a["truncated"] is False
    big = ta.attachment_answer("att-2", "log.txt", ("x" * (ta.ATTACHMENT_TEXT_MAX + 5)).encode())
    assert len(big["text"]) == ta.ATTACHMENT_TEXT_MAX and big["truncated"] is True
    png = ta.attachment_answer("att-3", "shot.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert png["text"] is None and "open it in the app" in png["note"] and png["bytes"] == 16
    bad = ta.attachment_answer("att-4", "x.bin", b"\xff\xfe\xfa")
    assert bad["text"] is None


def test_the_attachment_tool_asks_the_route_with_the_callers_token(monkeypatch):
    seen = {}

    class _Resp:
        status_code = 200
        headers = {"content-disposition": 'attachment; filename="notes.txt"'}
        content = b"three lines\nof text\n"

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            seen["url"], seen["auth"] = url, (headers or {}).get("Authorization")
            return _Resp()

    monkeypatch.setattr(ta, "mcp_http_client", lambda timeout=None: _Client())
    out = run(ta.chat_get_attachment(AUTH, "att-9"))
    assert seen["url"].endswith("/api/v1/chat/attachments/att-9") and seen["auth"] == "Bearer tok"
    assert out["name"] == "notes.txt" and out["text"] == "three lines\nof text\n"
    anon = run(ta.chat_get_attachment(types.SimpleNamespace(auth_type="anonymous", raw_token=None), "att-9"))
    assert "requires authentication" in anon["error"]


def test_the_new_tools_are_wired_like_every_chat_tool():
    names = {s["name"] for s in ta.AGENT_TOOL_SCHEMAS}
    for t in NEW:
        assert t in names and t in server.TOOL_DISPATCH and t in server.AUTH_REQUIRED_TOOLS, t
    for t in NEW[:3] + NEW[4:]:
        assert t in server.TIER2_TOOLS and t in audit._TIER_2_TOOLS, t      # dual-auth: agent_jwt swaps in
    assert "theprotocol_listWaitingChatApprovals" in server.TIER3_TOOLS        # a decider's read: a developer
    assert "theprotocol_listWaitingChatApprovals" in audit._TIER_3_TOOLS


def test_the_descriptions_can_be_spoken():
    schemas = {s["name"]: s for s in ta.AGENT_TOOL_SCHEMAS if s["name"] in NEW}
    assert sorted(schemas) == sorted(NEW)       # a loop over no schema would pass loudest
    for name, s in schemas.items():
        d = s["description"]
        assert d.startswith("OurChat: ") and "Needs " in d, name     # what it does, then what it needs
        assert len(d) <= 260 and "\n" not in d, name


def test_the_tester_holds_a_contract_for_each():
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    for t in NEW:
        assert t in MCP_CONTRACTS, t
