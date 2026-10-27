"""SEC-12 (2026-10-17): an account shows ONE public id on a frame, on the registry's public reads and in its store's stream.

D6-606 shows a developer's own account (its id is built from its e-mail address) on a public answer as `account:<16
hex>`, an HMAC that cannot be turned back into the address. The registry keyed it with its API_KEY_SECRET; its event
store keys the same form with its own internal key (agentvault-event-store/src/personal_ids.py) for its public
/ws/events stream. A console that seeds its ledger from the registry (GET /api/v1/public/eventstore-recent) and then
follows the store's stream showed one account under two ids. The registry already presents the store's internal key on
every event it writes there (EVENT_STORE_API_KEY: a frame's template gives it the store's INTERNAL_API_KEY), so it now
keys its public id with that key: no new secret is shared. Without a usable store key it keeps API_KEY_SECRET.

Through FastAPI: the event seed on the real app (main.create_app) with the ring's Redis list supplied, and the public
rankings on the real router with the TEG's answer supplied over httpx's MockTransport. The store's side is its own
formula (personal_ids.public_account_id: HMAC-SHA256 under its key, the label, the first 16 hex), written out below as
the contract. RED on 453cc8b8 (its identifiers.py and event_emitter.py mounted): the seed and the rankings show the
API_KEY_SECRET id, not the store's.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import types

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry.database import get_db

WALLET = "did:theprotocol:jane.doe+ops_at_example.org"     # identifiers.developer_teg_did("jane.doe+ops@example.org")
AGENT = "did:theprotocol:6f1c2e9a-1b2c-4d5e-8f90-123456789abc"
STORE_KEY = "the-frames-store-internal-key-0123456789abcdef"


def _store_public_id(key: str, account_id: str) -> str:
    """agentvault-event-store/src/personal_ids.public_account_id, as the store computes it for its public stream."""
    mac = hmac.new(key.encode(), b"public-account-id\x00" + account_id.strip().encode(), hashlib.sha256).hexdigest()
    return "account:" + mac[:16]


class _Ring:
    def __init__(self, items):
        self.items = [json.dumps(i) for i in items]

    async def lrange(self, _key, start, end):
        return self.items[start:end + 1]


async def _get(app, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


@pytest.fixture()
def seed(monkeypatch):
    from agentvault_registry import main
    from agentvault_registry.background_tasks import leader

    ring = _Ring([{"event": {"id": "e1", "event_type": "TokensTransferred",
                             "data": {"from_agent_id": WALLET, "to_agent_id": AGENT, "amount": "5"}}}])

    async def _redis():
        return ring
    monkeypatch.setattr(leader, "get_redis", _redis)
    app = main.create_app()

    async def _from():
        r = await _get(app, "/api/v1/public/eventstore-recent?limit=10")
        assert r.status_code == 200, r.text
        return r.json()["events"][0]["event"]["data"]["from_agent_id"]
    return _from


@pytest.fixture()
def rankings(monkeypatch):
    from agentvault_registry.routers import teg_integration as ti
    from agentvault_registry.services import track_record

    def _teg(request):
        return httpx.Response(200, json={"rankings": [
            {"rank": 1, "agent_id": WALLET, "reputation_score": 500, "reputation_tier": "expert",
             "total_transactions": 9}], "total_agents": 1, "timestamp": "2026-10-17T00:00:00+00:00"})

    real_client = httpx.AsyncClient

    async def _no_records(_db, _dids):
        return {}
    monkeypatch.setattr(ti, "httpx", types.SimpleNamespace(AsyncClient=lambda *a, **k: real_client(
        transport=httpx.MockTransport(_teg)), RequestError=httpx.RequestError))
    monkeypatch.setattr(ti, "get_httpx_verify", lambda: False)
    monkeypatch.setattr(track_record, "compact_track_records", _no_records)
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield None
    app.dependency_overrides[get_db] = _db

    async def _first():
        r = await _get(app, "/api/v1/teg/reputation/rankings")
        assert r.status_code == 200, r.text
        return r.json()["rankings"][0]["agent_id"]
    return _first


async def test_the_registrys_public_reads_show_the_id_the_store_streams(monkeypatch, seed, rankings):
    monkeypatch.setenv("EVENT_STORE_API_KEY", STORE_KEY)
    want = _store_public_id(STORE_KEY, WALLET)
    assert await seed() == want, "the event seed shows another id than the store's public stream"
    assert await rankings() == want, "and so do the public rankings"


async def test_the_older_name_of_the_store_key_counts_too(monkeypatch, seed):
    monkeypatch.delenv("EVENT_STORE_API_KEY", raising=False)
    monkeypatch.setenv("EVENT_STORE_INTERNAL_KEY", STORE_KEY)
    assert await seed() == _store_public_id(STORE_KEY, WALLET)


@pytest.mark.parametrize("store_key", [None, "", "short-key"])
async def test_without_a_usable_store_key_the_registry_keeps_its_own(monkeypatch, seed, store_key):
    from agentvault_registry.config import settings
    monkeypatch.delenv("EVENT_STORE_INTERNAL_KEY", raising=False)
    if store_key is None:
        monkeypatch.delenv("EVENT_STORE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("EVENT_STORE_API_KEY", store_key)
    got = await seed()
    assert got == _store_public_id(str(settings.API_KEY_SECRET), WALLET), "control: as before, keyed by the registry"
    assert got.startswith("account:") and "_at_" not in got
