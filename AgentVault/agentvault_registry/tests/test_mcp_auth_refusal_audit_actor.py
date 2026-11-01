"""V0651 (agentvault2-14, 2026-10-31, from agentvault2-d3's reading of V0650's pair proof): a tool's own refusal of a
caller's credential is audited under that caller.

nt261031x6's lifecycle row 'refusal: decideChatApproval an agent's own token' was audited as `Actor: anonymous/None`
(the pair's kept log, 14:23:26Z), while the same agent token was audited as the agent 160 ms later. The token was
read: decide_chat_approval's require_developer_auth refused the agent context, and the dispatcher's
except-MCPAuthError arm audited `auth_ctx_for_audit`, which stays None when _handle_tools_call raises. The context
rides on the exception since V0545 (`e.mcp_auth_ctx`, read by the generic arm); now the auth arm reads it too, and so
does the task-augmented path. Each case marked BASE fails on 48d07ecf2 (V0650).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from agentvault_registry.mcp import server as S
from agentvault_registry.mcp.auth_bridge import require_developer_auth

AGENT = SimpleNamespace(is_anonymous=False, is_developer=False, is_agent=True, auth_type="agent", developer_id=None,
                        agent_did="did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-000000000001",
                        is_admin=False, raw_token="agent-jwt", agent_id=None)
NOBODY = SimpleNamespace(is_anonymous=True, is_developer=False, is_agent=False, auth_type="anonymous",
                         developer_id=None, agent_did=None, is_admin=False, raw_token=None, agent_id=None)


def _req(body):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/mcp/rpc", "query_string": b"",
                    "headers": [(b"content-type", b"application/json"), (b"authorization", b"Bearer some-token")]},
                   receive)


def _call(tool, args):
    resp = asyncio.run(S.handle_rpc(_req({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                          "params": {"name": tool, "arguments": args}})))
    return json.loads(resp.body)


async def _developer_only(auth, x: str = ""):
    require_developer_auth(auth)
    return {"ok": True}


class _Rows(list):
    """The audit rows, with the context the stubbed authenticator returns (`who`)."""


@pytest.fixture
def audited(monkeypatch):
    rows, who = _Rows(), {"ctx": AGENT}

    async def rec(**kw):
        rows.append(kw)

    async def auth(token, db):
        return who["ctx"]
    monkeypatch.setattr(S, "emit_mcp_audit", rec)
    monkeypatch.setattr(S, "authenticate_mcp_token", auth)
    rows.who = who
    return rows


def test_a_tier3_refusal_of_an_agent_is_audited_under_the_agent(monkeypatch, audited):
    # BASE: auth_ctx is None (the arm audited auth_ctx_for_audit, unset when the call raises)
    name = "theprotocol_zzDeveloperOnly"
    monkeypatch.setitem(S.TOOL_DISPATCH, name, _developer_only)
    monkeypatch.setattr(S, "AUTH_REQUIRED_TOOLS", set(S.AUTH_REQUIRED_TOOLS) | {name})
    out = _call(name, {})
    assert out["error"]["code"] == -32001 and "requires developer authentication" in out["error"]["message"]
    assert len(audited) == 1 and audited[0]["outcome"] == "failure"
    assert audited[0]["auth_ctx"] is AGENT, "the refused caller is named, not anonymous"


def test_the_real_decide_tool_refuses_an_agent_and_the_audit_names_the_agent(audited):
    # BASE: auth_ctx is None
    out = _call("theprotocol_decideChatApproval", {"conversation_id": "room-1", "decision": "approve"})
    assert out["error"]["code"] == -32001 and "requires developer authentication" in out["error"]["message"]
    assert audited[0]["tool_name"] == "theprotocol_decideChatApproval" and audited[0]["auth_ctx"] is AGENT


def test_an_unrecognized_token_is_still_audited_under_its_anonymous_context(monkeypatch, audited):
    audited.who["ctx"] = NOBODY
    name = "theprotocol_zzDeveloperOnly"
    monkeypatch.setitem(S.TOOL_DISPATCH, name, _developer_only)
    monkeypatch.setattr(S, "AUTH_REQUIRED_TOOLS", set(S.AUTH_REQUIRED_TOOLS) | {name})
    out = _call(name, {})
    assert out["error"]["code"] == -32001 and audited[0]["auth_ctx"] is NOBODY


def test_the_task_path_audits_a_refusal_under_the_caller_too():
    # BASE: the task arm leaves bg_ctx None (read from the source: the arm must take the exception's context)
    import inspect
    src = inspect.getsource(S)
    arm = src[src.index("except (MCPAuthError, MCPAuthUnavailable) as e:"):][:300]
    assert 'getattr(e, "mcp_auth_ctx", None)' in arm


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
