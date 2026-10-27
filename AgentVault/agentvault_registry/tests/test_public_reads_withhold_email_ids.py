"""§SECFIX D6-606 (2026-10-16): no public read shows an account id built from an e-mail address.

A developer's TEG account id is `did:theprotocol:<address with @ written _at_>` (identifiers.developer_teg_did), and
existing balances key on it, so the id itself stays. Measured on the base (14520b9f) through these same requests:
GET /api/v1/teg/reputation/rankings (public) listed such ids as they are, and GET /api/v1/public/eventstore-recent
(public) served the ledger's events verbatim, those ids and an invitation's address included. A public answer now
shows `account:<16 hex>` (a keyed hash, stable on the registry, not reversible) and withholds addresses.

The routes run through FastAPI: the rankings on the real router with the TEG's answer supplied over httpx's
MockTransport, the event seed on the real app (main.create_app) with the ring's Redis list supplied.
"""
from __future__ import annotations

import json
import types

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry.database import get_db

AGENT = "did:theprotocol:6f1c2e9a-1b2c-4d5e-8f90-123456789abc"
WALLET = "did:theprotocol:jane.doe+ops_at_example.org"     # developer_teg_did("jane.doe+ops@example.org")
TEG_ANSWER = {
    "rankings": [
        {"rank": 1, "agent_id": AGENT, "reputation_score": 900, "reputation_tier": "expert", "total_transactions": 3},
        {"rank": 2, "agent_id": WALLET, "reputation_score": 500, "reputation_tier": "expert", "total_transactions": 9},
        {"rank": 3, "agent_id": "STAKING_POOL", "reputation_score": 10, "reputation_tier": "standard",
         "total_transactions": 1},
    ],
    "total_agents": 3,
    "timestamp": "2026-10-16T00:00:00+00:00",
}


async def _call(app, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


@pytest.fixture()
def rankings_app(monkeypatch):
    from agentvault_registry.routers import teg_integration as ti
    from agentvault_registry.services import track_record

    def _teg(request):
        assert request.url.path.endswith("/reputation/rankings")
        return httpx.Response(200, json=TEG_ANSWER)

    real_client = httpx.AsyncClient

    def _client(*_a, **_k):
        return real_client(transport=httpx.MockTransport(_teg))

    async def _no_records(_db, _dids):
        return {}

    monkeypatch.setattr(ti, "httpx", types.SimpleNamespace(AsyncClient=_client, RequestError=httpx.RequestError))
    monkeypatch.setattr(ti, "get_httpx_verify", lambda: False)
    monkeypatch.setattr(track_record, "compact_track_records", _no_records)
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield None

    app.dependency_overrides[get_db] = _db
    return app


async def test_the_public_rankings_show_no_address_derived_id(rankings_app):
    r = await _call(rankings_app, "/api/v1/teg/reputation/rankings")
    assert r.status_code == 200, r.text
    assert "_at_" not in r.text and "example.org" not in r.text and "jane" not in r.text
    rows = r.json()["rankings"]
    assert [x["rank"] for x in rows] == [1, 2, 3] and r.json()["total_agents"] == 3      # the ranking itself unchanged
    assert rows[0]["agent_id"] == AGENT and rows[2]["agent_id"] == "STAKING_POOL"       # control: agents, system ids
    assert rows[1]["agent_id"].startswith("account:") and len(rows[1]["agent_id"]) == len("account:") + 16
    again = await _call(rankings_app, "/api/v1/teg/reputation/rankings")
    assert again.json()["rankings"][1]["agent_id"] == rows[1]["agent_id"]               # stable, so a row can be followed


class _Ring:
    def __init__(self, items):
        self.items = [json.dumps(i) for i in items]

    async def lrange(self, _key, start, end):
        return self.items[start:end + 1]


async def test_the_public_event_seed_withholds_address_derived_ids_and_addresses(monkeypatch):
    from agentvault_registry import main
    from agentvault_registry.background_tasks import leader

    ring = _Ring([
        {"event": {"id": "e1", "event_type": "TokensTransferred",
                   "data": {"from_agent_id": WALLET, "to_agent_id": AGENT, "amount": "5"}}},
        {"event": {"id": "e2", "event_type": "OrganizationMemberInvited", "aggregate_id": "org-1",
                   "data": {"org_id": "org-1", "email": "invitee@example.org", "role": "member"}}},
    ])

    async def _redis():
        return ring

    monkeypatch.setattr(leader, "get_redis", _redis)
    r = await _call(main.create_app(), "/api/v1/public/eventstore-recent?limit=10")
    assert r.status_code == 200, r.text
    assert "example.org" not in r.text and "_at_" not in r.text
    first, second = (e["event"] for e in r.json()["events"])
    assert first["data"]["to_agent_id"] == AGENT and first["data"]["amount"] == "5"     # control: the rest as stored
    assert first["data"]["from_agent_id"].startswith("account:")
    assert second["id"] == "e2" and second["data"]["role"] == "member"


def test_the_account_keeps_its_id_and_the_public_one_is_keyed(monkeypatch):
    from agentvault_registry import identifiers as ids
    from agentvault_registry.config import settings

    # balances key on this derivation: it must never change
    assert ids.developer_teg_did("jane.doe+ops@example.org") == WALLET
    assert ids.is_email_derived_account_id(WALLET) and ids.is_email_derived_account_id("did:theprotocol:a_dot_b_at_c_dot_d")
    assert not ids.is_email_derived_account_id(AGENT) and not ids.is_email_derived_account_id("STAKING_POOL")
    one = ids.public_account_id(WALLET)
    monkeypatch.setattr(settings, "API_KEY_SECRET", "another-registrys-secret-0123456789abcdef")
    assert ids.public_account_id(WALLET) != one       # keyed: an address cannot be confirmed by hashing a guess
    nested = ids.withhold_personal_ids({WALLET: [{"note": f"paid {WALLET}, thanks x@y.org"}], "n": 1})
    assert "_at_" not in json.dumps(nested) and "x@y.org" not in json.dumps(nested) and nested["n"] == 1
