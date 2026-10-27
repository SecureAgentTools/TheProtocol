"""§BATCH0911 item 4 — `theprotocol_unlockReputationBond`, proven through the REAL public dispatcher.

The tool is wired in the six places a public T2 tool lives (impl + schema in tools_agent, import +
TOOL_DISPATCH + TIER2_TOOLS in server, audit tier set, category, annotation); the AST derive
(`scratchpad/mcp_catalog/derive_tools.py`) counts it. This file pins what a CALLER sees:

  * a refusal is the one outcome of this tool that matters most, and a result dict carrying `error`
    renders as `Error: <error>` with every other key dropped (§BATCH3). `_agent_post` used to leave
    the registry's reason in a side key (`body`), where no caller could read it; the unlock tool asks
    for the reason IN the error, and the 409 bodies here are built by the registry's own exception
    handler, so the fixture is the real wire shape rather than a guess about it;
  * a success keeps its structuredContent;
  * the opt-in leaks nowhere: another agent tool's refusal still reads exactly as it always did.
"""
from __future__ import annotations

import contextlib
import json

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agentvault_registry import errors
from agentvault_registry.mcp import server, tools_agent
from agentvault_registry.mcp.auth_bridge import MCPAuthContext

TOOL = "theprotocol_unlockReputationBond"
PATH = "/api/v1/agents/reputation-bond/unlock"


async def _wire_body(status_code: int, detail) -> bytes:
    """The body the registry actually sends for HTTPException(status_code, detail)."""
    req = Request({"type": "http", "method": "POST", "path": PATH, "headers": [], "query_string": b""})
    resp = await errors.http_exception_handler(req, HTTPException(status_code, detail=detail))
    return resp.body


def _install(monkeypatch, status_code: int, body: bytes, seen: dict):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, params=None, headers=None):
            seen["url"] = url
            seen["auth"] = (headers or {}).get("Authorization")
            return httpx.Response(status_code, content=body, request=httpx.Request("POST", url),
                                  headers={"content-type": "application/json"})

    async def _auth(token, db):
        seen["token"] = token
        return MCPAuthContext(auth_type="agent", agent_did="did:theprotocol:test:unlock", raw_token=token)

    @contextlib.asynccontextmanager
    async def _db():
        yield None

    monkeypatch.setattr(tools_agent.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(server, "authenticate_mcp_token", _auth)
    monkeypatch.setattr(server, "get_db_context", _db)


def test_the_tool_is_a_public_tier2_tool_with_a_schema():
    assert TOOL in server.TOOL_DISPATCH and TOOL in server.TIER2_TOOLS and TOOL in server.AUTH_REQUIRED_TOOLS
    assert any(s.get("name") == TOOL for s in server.ALL_TOOL_SCHEMAS)
    from agentvault_registry.mcp import audit
    assert TOOL in audit._TIER_2_TOOLS, "missing from the audit tier set = tier='unknown' audit rows"
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    assert derive_annotations(TOOL)["destructiveHint"] is True


@pytest.mark.asyncio
async def test_a_not_matured_refusal_names_its_reason(monkeypatch):
    seen: dict = {}
    body = await _wire_body(409, {"message": "The bond has not matured yet.",
                                  "progress": {"blocking": ["age", "trust"], "percent": 41}})
    _install(monkeypatch, 409, body, seen)
    payload, _ = await server._handle_tools_call(TOOL, {"agent_jwt": "inline-agent-jwt"}, token="bridge-token")
    assert payload["isError"] is True
    text = payload["content"][0]["text"]
    assert text.startswith("Error: unlockReputationBond refused (HTTP 409): The bond has not matured yet."), text
    assert "age, trust" in text
    assert seen["url"].endswith(PATH)
    assert seen["token"] == "inline-agent-jwt", "an inline agent_jwt must win over the bridge token"
    assert seen["auth"] == "Bearer inline-agent-jwt"


@pytest.mark.asyncio
async def test_a_plain_string_refusal_is_carried_verbatim(monkeypatch):
    msg = "This registry releases no capital at maturity (enforcement.bond_maturity_releases_percent = 0)."
    _install(monkeypatch, 409, await _wire_body(409, msg), {})
    payload, _ = await server._handle_tools_call(TOOL, {}, token="t")
    assert payload["content"][0]["text"] == f"Error: unlockReputationBond refused (HTTP 409): {msg}"


@pytest.mark.asyncio
async def test_a_cooldown_refusal_says_when(monkeypatch):
    body = await _wire_body(409, {"message": "The unlock opens after the 7-day cooldown.",
                                  "unlock_after": "2026-10-14T00:00:00+00:00"})
    _install(monkeypatch, 409, body, {})
    payload, _ = await server._handle_tools_call(TOOL, {}, token="t")
    assert "unlock_after=2026-10-14T00:00:00+00:00" in payload["content"][0]["text"]


@pytest.mark.asyncio
async def test_a_success_keeps_its_structured_content(monkeypatch):
    ok = {"bond_id": 7, "status": "matured", "unlocked": "150", "still_held": "100", "currency": "ECU",
          "fire": "embers"}
    _install(monkeypatch, 200, json.dumps(ok).encode(), {})
    payload, _ = await server._handle_tools_call(TOOL, {}, token="t")
    assert payload["isError"] is False
    assert payload["structuredContent"]["unlocked"] == "150" and payload["structuredContent"]["fire"] == "embers"


@pytest.mark.asyncio
async def test_control_other_agent_tools_keep_their_error_text(monkeypatch):
    """The `refused (HTTP n)` form is opt-in. Every other tool keeps its "returned HTTP n" text, and since V0514
    (§MCPTEST30, mcp/refusal.http_refusal) that text carries the route's reason after it: the MCP tester counted 47
    tools whose refusal told the caller nothing."""
    _install(monkeypatch, 409, await _wire_body(409, "Agent already has an active bond."), {})
    payload, _ = await server._handle_tools_call("theprotocol_depositReputationBond", {"amount": 250}, token="t")
    assert payload["content"][0]["text"] == ("Error: depositReputationBond returned HTTP 409: "
                                             "Agent already has an active bond.")
