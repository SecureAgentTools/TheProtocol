"""V0657 recut: an agent filing a dispute through MCP can claim an amount, as the console and REST callers can.

V0657 (a) item 2 takes a ruling's compensation and the offence's slash only from the amount the complainant claims when
filing (`amount_claimed` on POST /api/v1/disputes/), never from a key in free-form evidence. The MCP tool
theprotocol_submitDispute had no such argument and sent only the defendant, so no MCP caller could claim an amount: a
ruling for an MCP complainant moved nothing ("not applied (0 AVT)"), and the cross-frame settlement rail could not be
reached through MCP at all. session-tester's federation suite found it on nt261107x2 (room seq 1929): both
xframe_settlement legs stop at the_origin_rules_for_the_complainant. The tool now takes amount_claimed as a numeric
string and passes it to the route as written; the route's own bounds decide. Red on 3f56e9c4f.
"""
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentvault_registry.mcp import tools_developer as td
from agentvault_registry.mcp.auth_bridge import MCPAuthContext

ME = "did:theprotocol:v0657-claimant"
THEM = "did:theprotocol:v0657-defendant"


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = json.dumps(body)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


def _route(monkeypatch, status=201):
    posts = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posts.append((url, json))
            if url.endswith("/api/v1/disputes/"):
                if status != 201:
                    return _Resp(status, {"detail": "amount_claimed: Input should be greater than 0"})
                # create_dispute's answer names the claim it recorded (routers/disputes.py, _dispute_response)
                claimed = json.get("amount_claimed")
                return _Resp(201, {"id": 11, "status": "OPEN", "complainant_did": ME,
                                   "defendant_did": json["defendant_did"], "created_at": "2026-11-07T14:30:00Z",
                                   "amount_claimed": str(Decimal(claimed)) if claimed is not None else None})
            raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(td.httpx, "AsyncClient", _Client)
    return posts


def _me():
    return MCPAuthContext(auth_type="agent", agent_did=ME, raw_token="t")


def _schema():
    return next(s for s in td.DEVELOPER_TOOL_SCHEMAS if s["name"] == "theprotocol_submitDispute")


def test_the_schema_offers_the_claim_and_still_asks_only_for_the_defendant():
    s = _schema()
    prop = s["inputSchema"]["properties"]["amount_claimed"]
    # a string or a number (session-tester, seq 1933); string first, so the census reads it as the string it is sent as
    assert prop["type"] == ["string", "number"] and "numeric string" in prop["description"]
    assert "evidence" in prop["description"], "the caller is told an amount in evidence moves nothing"
    assert s["inputSchema"]["required"] == ["defendant_did"]


async def test_a_claim_is_sent_to_the_route_as_the_caller_wrote_it(monkeypatch):
    posts = _route(monkeypatch)
    out = await td.submit_dispute(_me(), defendant_did=THEM, amount_claimed="12.5")
    assert "error" not in out and out["dispute_id"] == 11
    assert posts == [(f"{td.REGISTRY_SELF_URL}/api/v1/disputes/", {"defendant_did": THEM, "amount_claimed": "12.5"})]
    assert out["amount_claimed"] == "12.5", "the result names the claim the route recorded"


@pytest.mark.parametrize("given,sent", [(10001, "10001"), (12.5, "12.5"), ("10001", "10001")])
async def test_a_number_is_sent_as_the_string_it_reads_as(monkeypatch, given, sent):
    from agentvault_registry.mcp.arguments import argument_problems
    assert argument_problems(_schema()["inputSchema"], {"defendant_did": THEM, "amount_claimed": given}) == []
    posts = _route(monkeypatch)
    await td.submit_dispute(_me(), defendant_did=THEM, amount_claimed=given)
    assert posts[0][1] == {"defendant_did": THEM, "amount_claimed": sent}


@pytest.mark.parametrize("given", [None, ""])
async def test_no_claim_sends_none(monkeypatch, given):
    posts = _route(monkeypatch)
    out = await td.submit_dispute(_me(), defendant_did=THEM, amount_claimed=given)
    assert posts == [(f"{td.REGISTRY_SELF_URL}/api/v1/disputes/", {"defendant_did": THEM})]
    assert out["amount_claimed"] is None


async def test_a_claim_the_route_refuses_is_reported_as_its_refusal(monkeypatch):
    _route(monkeypatch, status=422)
    out = await td.submit_dispute(_me(), defendant_did=THEM, amount_claimed="0")
    assert out["error"].startswith("Dispute filing failed (HTTP 422)")


def test_the_route_takes_the_tools_body_and_its_bounds_decide():
    from agentvault_registry.routers.disputes import DisputeCreate
    assert DisputeCreate(defendant_did=THEM, amount_claimed="12.5").amount_claimed == Decimal("12.5")
    for bad in ("0", "-3", "1.0000000000000000001", "twelve"):
        with pytest.raises(ValidationError):
            DisputeCreate(defendant_did=THEM, amount_claimed=bad)


def test_the_compensation_reads_the_claim_the_tool_now_sends():
    """The other half of the gap: what the ruling moves is the filed claim, so the tool's argument reaches money."""
    from types import SimpleNamespace

    from agentvault_registry.crud import crud_disputes as cd
    filed = SimpleNamespace(amount_claimed=Decimal("12.5"), guild_order_id=None, contract_ref=None)
    assert cd.enforcement_amount(filed) == 12
    assert cd.enforcement_amount(SimpleNamespace(amount_claimed=None, guild_order_id=None, contract_ref=None)) == 0
