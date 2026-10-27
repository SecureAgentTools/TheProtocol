"""§MCPTEST30 (2026-10-01) — three enum filters speak their routes' vocabulary.

Measured on sbx-alpha (V0526) by hand: getMyPaymentAuthorizations advertised uppercase statuses while the column holds
lowercase ones and the route compared exactly (every advertised value matched nothing); getRecentWebhookDeliveries
advertised `failure` while its route accepts `failed` (400); getInviteCodes advertised `revoked` (revoking deletes a code)
and its route answered every code for it. The MCP schema, the route and the console now agree.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.mcp import tools_admin as TA
from agentvault_registry.mcp import tools_agent as TG
from agentvault_registry.models import A2APaymentStatus
from agentvault_registry.routers import a2a_payment as AP
from agentvault_registry.routers import admin_invite_codes as IC

# the console's sources sit in the TREE beside this test: an image ships the built dist, so a path from the module
# (which the build's artifact gate imports from the image) has no TypeScript to read
FE = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "static" / "new_registry_frontend"
      / "src" / "services" / "api")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _enum(schemas, tool, param):
    t = next(t for t in schemas if t["name"] == tool)
    return t["inputSchema"]["properties"][param]["enum"]


def test_the_a2a_token_tool_lowercases_and_names_every_status(monkeypatch):
    sent = {}

    async def fake_get(auth, path, params=None, op_name=""):
        sent.update(params or {})
        return []

    monkeypatch.setattr(TG, "_agent_get", fake_get)
    _run(TG.get_my_a2a_payment_tokens(SimpleNamespace(), status="SETTLED"))
    assert sent["status"] == "settled"
    advertised = {v.lower() for v in _enum(_all_schemas(), "theprotocol_getMyPaymentAuthorizations", "status")}
    assert advertised == {s.value for s in A2APaymentStatus}, "the schema names exactly the statuses the column holds"


def _all_schemas():
    from agentvault_registry.mcp import server as S
    return S.ALL_TOOL_SCHEMAS


class _Session:
    def __init__(self):
        self.stmt = None

    async def execute(self, stmt):
        self.stmt = stmt
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


def _list_tokens(status):
    db = _Session()
    fn = getattr(AP.list_my_tokens, "__wrapped__", AP.list_my_tokens)
    _run(fn(current_agent=SimpleNamespace(did="did:theprotocol:x"), db=db, status_filter=status, limit=50))
    return str(db.stmt.compile(compile_kwargs={"literal_binds": True}))


def test_the_a2a_token_route_takes_any_case_and_refuses_an_unknown_status():
    assert "'settled'" in _list_tokens("SETTLED") and "'settled'" in _list_tokens("settled")
    with pytest.raises(HTTPException) as e:
        _list_tokens("PAID")
    assert e.value.status_code == 422


def test_webhook_deliveries_speak_the_route_and_console_vocabulary():
    from agentvault_registry.mcp import server_admin as SA
    advertised = set(_enum(SA.ADMIN_TOOL_SCHEMAS, "theprotocol_getRecentWebhookDeliveries", "status"))
    fe = set(re.findall(r"'(\w+)'", re.search(r"DeliveryStatus\s*=([^\n]+)", (FE / "webhooksAdmin.ts").read_text()).group(1)))
    route = pathlib.Path(TA.__file__).resolve().parents[1] / "routers" / "admin_health.py"
    # D6-786: the route takes the shared outcome rule's words (services/webhook_service.DELIVERY_OUTCOMES, the rule a
    # developer's own list reads) and its own literal branches
    from agentvault_registry.services.webhook_service import DELIVERY_OUTCOMES
    src = route.read_text()
    assert "if sf in DELIVERY_OUTCOMES:" in src
    branches = set(DELIVERY_OUTCOMES) | set(re.findall(r'sf == "(\w+)"', src)) | {"all"}
    assert advertised == fe == branches, (advertised, fe, branches)


def test_invite_codes_speak_the_crud_and_console_vocabulary_and_refuse_anything_else():
    from agentvault_registry.mcp import server_admin as SA
    advertised = set(_enum(SA.ADMIN_TOOL_SCHEMAS, "theprotocol_getInviteCodes", "status_filter"))
    fe = set(re.findall(r"'(\w+)'", re.search(r"InviteCodeStatus\s*=([^\n]+)", (FE / "inviteCodes.ts").read_text()).group(1)))
    assert advertised == fe == {"active", "used", "expired"}
    fn = getattr(IC.list_codes, "__wrapped__", IC.list_codes)
    with pytest.raises(HTTPException) as e:
        _run(fn(http_request=None, status_filter="revoked", limit=10, offset=0, current_developer=None, db=None))
    assert e.value.status_code == 422
