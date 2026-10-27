"""§MCPTEST30 (V0545) — arguments that do not bind to a tool are the caller's -32602, audited as a refusal under the
caller, never as an unhandled tool failure attributed to "anonymous".

One sweep's empty-argument probe left 225 `mcp_tool_failed` rows (outcome error, an ERROR log line each) in 15 minutes
on sbx-alpha: `accept_contract() missing 2 required positional arguments` and the like. The call raised TypeError, the
dispatcher audited it as a tool failure under "anonymous" (the auth context is returned only by a call that succeeds),
and then answered the caller -32602. Both dispatchers now bind the arguments to the tool's own signature first.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from agentvault_registry.mcp import arguments as A
from agentvault_registry.mcp import server as S
from agentvault_registry.mcp import server_admin as SA


def _req(path, body):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": path, "query_string": b"",
                    "headers": [(b"content-type", b"application/json"), (b"authorization", b"Bearer phase6-token")]},
                   receive)


def _call(handler, path, tool, args):
    resp = asyncio.run(handler(_req(path, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                            "params": {"name": tool, "arguments": args}})))
    return json.loads(resp.body)


CALLER = SimpleNamespace(is_anonymous=False, is_developer=True, is_agent=False, auth_type="developer", developer_id=42,
                         agent_did=None, is_admin=True, raw_token="t", agent_id=None)


async def _bump(auth, needed: str):
    return {"ok": needed}


async def _bug(auth, x: str):
    return None + 1   # a TypeError INSIDE a running tool: a real failure, not the caller's arguments


@pytest.fixture
def audit(monkeypatch):
    rows = []

    async def rec(**kw):
        rows.append(kw)
    monkeypatch.setattr(S, "emit_mcp_audit", rec)
    monkeypatch.setattr(SA, "emit_mcp_audit", rec)

    async def auth(token, db):
        return CALLER
    monkeypatch.setattr(S, "authenticate_mcp_token", auth)
    return rows


def _public_tool(monkeypatch, name, fn):
    monkeypatch.setitem(S.TOOL_DISPATCH, name, fn)
    monkeypatch.setattr(S, "AUTH_REQUIRED_TOOLS", set(S.AUTH_REQUIRED_TOOLS) | {name})


def test_binding_names_the_missing_and_the_unexpected():
    with pytest.raises(A.ToolArgumentsRefused) as e:
        A.refuse_unbindable(_bump, (CALLER,), {}, CALLER)
    assert "needed" in str(e.value) and e.value.auth_ctx is CALLER and isinstance(e.value, TypeError)
    with pytest.raises(A.ToolArgumentsRefused) as e:
        A.refuse_unbindable(_bump, (CALLER,), {"needed": "y", "reason": "z"})
    assert "reason" in str(e.value)
    assert A.refuse_unbindable(_bump, (CALLER,), {"needed": "y"}) is None

    class _NoSignature:
        __signature__ = "not a signature"   # inspect.signature raises TypeError: the call goes ahead as before

        async def __call__(self, *a, **k):
            return None
    assert A.refuse_unbindable(_NoSignature(), (), {"anything": 1}) is None


def test_the_public_dispatcher_refuses_a_missing_argument_as_the_callers(monkeypatch, audit):
    _public_tool(monkeypatch, "theprotocol_zzBump", _bump)
    out = _call(S.handle_rpc, "/mcp/rpc", "theprotocol_zzBump", {})
    assert out["error"]["code"] == -32602 and "needed" in out["error"]["message"]
    assert len(audit) == 1 and audit[0]["outcome"] == "failure", audit
    assert audit[0]["auth_ctx"] is CALLER, "the audit names the caller, not anonymous"
    assert audit[0]["result_or_error"].startswith("Invalid params: ")


def test_the_public_dispatcher_still_calls_a_good_call(monkeypatch, audit):
    _public_tool(monkeypatch, "theprotocol_zzBump", _bump)
    out = _call(S.handle_rpc, "/mcp/rpc", "theprotocol_zzBump", {"needed": "yes"})
    assert "error" not in out and audit[0]["outcome"] == "success"


def test_a_typeerror_inside_a_running_tool_is_still_a_failure_under_its_caller(monkeypatch, audit):
    _public_tool(monkeypatch, "theprotocol_zzBug", _bug)
    _call(S.handle_rpc, "/mcp/rpc", "theprotocol_zzBug", {"x": "1"})
    assert len(audit) == 1 and audit[0]["outcome"] == "error"
    assert audit[0]["auth_ctx"] is CALLER, "a failed call is audited under the caller who made it"


def test_the_admin_dispatcher_refuses_a_missing_argument_as_the_callers(monkeypatch, audit):
    name = "theprotocol_zzAdminBump"
    monkeypatch.setitem(SA.ADMIN_TOOL_DISPATCH, name, _bump)

    async def admin_auth(*a, **k):
        return CALLER
    for attr in ("authenticate_admin_mcp_token", "authenticate_mcp_token"):
        if hasattr(SA, attr):
            monkeypatch.setattr(SA, attr, admin_auth)
    out = _call(SA.handle_admin_rpc, "/mcp/admin/rpc", name, {})
    assert out["error"]["code"] == -32602 and "needed" in out["error"]["message"], out
    rows = [r for r in audit if r.get("tool_name") == name]
    assert rows and rows[-1]["outcome"] == "failure", audit


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
