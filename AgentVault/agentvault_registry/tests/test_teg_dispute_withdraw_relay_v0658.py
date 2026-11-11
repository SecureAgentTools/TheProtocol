"""D6-825 (V0658 (c)): the registry relays a claimant's withdrawal of its own OPEN TEG dispute, and audits it.

The TEG's own route (POST /api/v1/disputes/{id}/withdraw) takes the claimant's OPEN dispute to WITHDRAWN. The registry
relays it with the agent's TEG token, as /teg/disputes/log relays the filing, writes its audit row as the agent
(security_audit_logs, teg_dispute.withdraw) for a withdrawal the TEG made, passes the TEG's refusals on in its words, and
says when its TEG is older than the route. The MCP tool withdrawTegDispute is the relay's MCP door (the MCP tester's run
withdraws the dispute fixture it files with it).

Through FastAPI on the real TEG router. Doubles: the agent credential, the agent's TEG token, the TEG (it records what it
is asked and answers per case) and the audit writer. RED on v0657/cut (e70fb58b2): the route and the tool do not exist.
"""
from __future__ import annotations

import asyncio
import types

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import admin_audit

AGENT = types.SimpleNamespace(id=11, did="did:theprotocol:sentinel-1", mtls_enabled=False, spiffe_id=None,
                              status="active")
DISPUTE = "6b1c0a58-1111-4b0e-9c3e-1d2a3b4c5d6e"


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body
        self.text = str(body)

    def json(self):
        return self._body


@pytest.fixture
def teg(monkeypatch):
    """The TEG answers `teg.answer` (a (status, body) pair, or an exception to raise); records each POST it gets."""
    state = types.SimpleNamespace(answer=(200, {}), asked=[], audited=[])

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            state.asked.append((url, json))
            if isinstance(state.answer, Exception):
                raise state.answer
            return _Resp(*state.answer)

    async def token(agent_id, agent_did):
        return "teg-token"

    async def audit(db, **kw):
        state.audited.append(kw)
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", token)
    monkeypatch.setattr(admin_audit, "_log_action", audit)
    return state


def _withdraw(body=None):
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield None

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_agent] = lambda: AGENT
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    kw = {} if body is None else {"json": body}
    return TestClient(app, raise_server_exceptions=False).post(f"/api/v1/teg/disputes/{DISPUTE}/withdraw", **kw)


WITHDRAWN = {"dispute_log_id": DISPUTE, "status": "WITHDRAWN",
             "resolution_notes": f"Withdrawn by its claimant {AGENT.did} at 2026-11-07T00:00:00+00:00: the run's fixture",
             "withdrawn_at": "2026-11-07T00:00:00+00:00"}


def test_a_withdrawal_the_teg_made_is_relayed_and_audited_as_the_agent(teg):
    teg.answer = (200, WITHDRAWN)
    r = _withdraw({"reason": "the run's fixture"})
    assert r.status_code == 200 and r.json() == WITHDRAWN, r.text
    assert teg.asked == [(f"{ti.TEG_API_BASE_URL}{ti.TEG_API_V1_PREFIX}/disputes/{DISPUTE}/withdraw",
                          {"reason": "the run's fixture"})], teg.asked
    assert len(teg.audited) == 1, teg.audited
    a = teg.audited[0]
    assert (a["prefix"], a["action"], a["actor_type"], a["actor_id"], a["target_type"], a["target_id"]) == \
        ("teg_dispute", "withdraw", "agent", AGENT.did, "teg_dispute", DISPUTE), a
    assert a["details"] == {"status": "WITHDRAWN", "reason": "the run's fixture"}


def test_the_reason_is_optional(teg):
    teg.answer = (200, WITHDRAWN)
    assert _withdraw().status_code == 200
    assert teg.asked[0][1] == {}, teg.asked


@pytest.mark.parametrize("code,detail", [
    (403, "Only the dispute's claimant can withdraw it"),
    (404, "Dispute not found"),
    (409, "Only an OPEN dispute can be withdrawn; this one is WITHDRAWN"),
])
def test_the_tegs_refusal_is_passed_on_in_its_words_and_nothing_is_audited(teg, code, detail):
    teg.answer = (code, {"detail": detail})
    r = _withdraw()
    assert r.status_code == code and r.json()["detail"] == detail, r.text
    assert teg.audited == [], teg.audited


@pytest.mark.parametrize("code", [404, 405])
def test_a_teg_older_than_the_route_is_named(teg, code):
    teg.answer = (code, {"detail": "Not Found" if code == 404 else "Method Not Allowed"})
    r = _withdraw()
    assert r.status_code == 503 and "does not take a withdrawal yet" in r.json()["detail"], r.text
    assert teg.audited == []


def test_an_unreachable_teg_is_503(teg):
    teg.answer = httpx.ConnectError("refused")
    r = _withdraw()
    assert r.status_code == 503 and r.json()["detail"] == "TEG service unavailable", r.text
    assert teg.audited == []


def test_a_reason_longer_than_500_is_refused_before_the_teg_is_asked(teg):
    r = _withdraw({"reason": "x" * 501})
    assert r.status_code == 422 and teg.asked == [], (r.status_code, teg.asked)


# ── the MCP door ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_mcp_tool_posts_to_the_relay(monkeypatch):
    from agentvault_registry.mcp import tools_agent as ta
    sent = []

    async def post(auth, path, json_body=None, params=None, op_name="", refusal_reason=False, headers=None):
        sent.append((path, json_body, op_name, refusal_reason))
        return WITHDRAWN
    monkeypatch.setattr(ta, "_agent_post", post)
    out = asyncio.run(ta.withdraw_teg_dispute(object(), DISPUTE, reason="done"))
    assert out == WITHDRAWN
    assert sent == [(f"/api/v1/teg/disputes/{DISPUTE}/withdraw", {"reason": "done"}, "withdrawTegDispute", True)], sent
    assert asyncio.run(ta.withdraw_teg_dispute(object(), "")) == {"error": "dispute_log_id is required"}


def test_the_mcp_tool_is_wired_as_an_agent_tool():
    from agentvault_registry.mcp import audit, server, tool_categories, tools_agent as ta
    name = "theprotocol_withdrawTegDispute"
    assert server.TOOL_DISPATCH[name] is ta.withdraw_teg_dispute
    assert name in server.TIER2_TOOLS and name in audit._TIER_2_TOOLS
    assert tool_categories.get_category(name) == "payments-a2a"
    schema = next(t for t in ta.AGENT_TOOL_SCHEMAS if t["name"] == name)
    assert schema["inputSchema"]["required"] == ["dispute_log_id"]
    assert set(schema["inputSchema"]["properties"]) == {"dispute_log_id", "reason", "agent_jwt"}
