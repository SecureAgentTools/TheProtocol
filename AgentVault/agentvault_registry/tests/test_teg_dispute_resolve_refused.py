"""§MCPTEST30 (V0545) — the registry refuses to forward a TEG dispute resolution, for every caller.

The TEG accepts the registry's mTLS identity as its admin (core/security.py::verify_admin_token delegates to
internal_auth.resolve_internal_caller, which returns for any internal service SVID whatever bearer rides along), so the
registry route `POST /teg/disputes/{id}/resolve` was the only gate in front of the TEG's resolve, and it asked for
`disputes.file`, which every agent holds from its `client` birth role. Only a transport slip stood between any agent and
any dispute's resolution, penalty included: the route sent `resolution` in a JSON body and the TEG reads it from the
query, so every call met the TEG's 422 (cloud-op sbxalphaop's TEG log, 2026-10-02 04:34:19Z: "missing query.resolution",
after "[TEG-AUTH] mode=mtls ... spiffe=.../operator/sbxalphaop/svid-writer"). The route now refuses before it forwards;
who may resolve a TEG dispute through the registry is his decision.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry.routers import teg_integration as T

NULL = "00000000-0000-4000-8000-000000000000"


class _Agent:
    id = 7
    did = "did:theprotocol:x"


def test_every_agent_is_refused_before_anything_reaches_the_teg(monkeypatch):
    def no_client(*a, **k):
        raise AssertionError("the route opened a client to the TEG")

    async def no_token(*a, **k):
        raise AssertionError("the route asked for a TEG token")
    monkeypatch.setattr(T.httpx, "AsyncClient", no_client)
    monkeypatch.setattr(T, "get_teg_token_for_agent", no_token)
    for resolution, penalty in (("RESOLVED_NO_ACTION", None), ("RESOLVED_FAVOR_INITIATOR", "25")):
        with pytest.raises(HTTPException) as e:
            asyncio.run(T.resolve_dispute_proxy(NULL, T.DisputeResolveRequest(resolution=resolution,
                                                                              penalty_amount=penalty), _Agent()))
        assert e.value.status_code == 403
        assert e.value.detail.startswith("Not authorized to resolve disputes"), e.value.detail


def test_a_caller_without_credentials_still_meets_the_agent_gate_first():
    app = FastAPI()
    app.include_router(T.router, prefix="/api/v1")
    r = TestClient(app).post(f"/api/v1/teg/disputes/{NULL}/resolve", json={"resolution": "RESOLVED_NO_ACTION"})
    assert r.status_code == 401, (r.status_code, r.text[:200])


def test_the_contract_does_not_accept_an_answer_that_means_the_call_reached_the_teg():
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    c = MCP_CONTRACTS["theprotocol_resolveTegDispute"]
    assert c.expect_status == "error_4xx" and "Not authorized to resolve disputes" in c.expect_error_message_contains
    assert "Dispute not found" not in c.expect_error_message_contains
    assert c.arguments["dispute_id"] == NULL, "a dispute nobody filed: even a reopened door moves nothing"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
