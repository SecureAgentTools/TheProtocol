"""§SECBATCH wave 2 (2026-10-16): the store's public websocket withholds personal ids, as the registry's public reads do
since wave 1 (D6-606).

A developer's TEG account id is built from the developer's e-mail address (did:theprotocol:<address with @ written
_at_>), and an event can carry a plain address. Every frame's console opens /ws/events through the frame's public lane
with no credential, and was sent every event as stored: the addresses of everyone who moved money, in the clear, to
anyone. What these tests pin, through FastAPI on the real /ws/events route (only the database session is replaced; the
live path runs the store's own fan-out in the app's event loop):
- a connection with no credential gets each event, live and in its backlog, with an e-mail-derived account id replaced
  by an opaque, stable account:<16 hex> and an address withheld; an agent DID is untouched;
- a connection that presents this store's key (the registry's reactors) gets the events as stored;
- a token that does not verify, on a store that does not require one, makes the connection public, never refused;
- a public connection may not subscribe to a channel named by such an id (one account's activity, asked for by a
  guessed address); a credentialed one may;
- the stats a public caller reads (the stats action, GET /ws/connections) name no such channel.
Run: python -m pytest tests/test_ws_public_stream_withholds_personal_ids.py -q   (needs pytest and httpx)
"""
import datetime
import os
import re
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.database.connection as connection  # noqa: E402
from src import internal_key  # noqa: E402
from src.routers import websocket as ws_router  # noqa: E402

KEY = "sec2-test-internal-key-not-a-secret"   # a test fixture, not a real secret
WALLET = "did:theprotocol:alice.smith_at_example.com"
AGENT = "did:theprotocol:6f1c2a8e-0b1d-4c3e-9f00-sec2agent"
T0 = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=datetime.timezone.utc)
OPAQUE = re.compile(r"^account:[0-9a-f]{16}$")


def _stored(n: int):
    """A stored event with a developer's account as the payer and an invitation's address in its data."""
    return SimpleNamespace(id=uuid.UUID(int=n), event_type="TokensTransferred", aggregate_id=WALLET,
                           aggregate_type="Agent", data={"from": WALLET, "to": AGENT, "amount": "5",
                                                         "note": "invited bob@example.org"},
                           timestamp=T0 + datetime.timedelta(seconds=n), version=1, source_service="registry")


def _live_message():
    return {"type": "event", "event": {"id": "live-1", "event_type": "TokensTransferred", "aggregate_id": WALLET,
                                        "data": {"from": WALLET, "to": AGENT, "amount": "7",
                                                 "invitee": "carol@example.net"},
                                        "timestamp": T0.isoformat(), "version": 1}}


class _Session:
    def __init__(self, ledger):
        self.ledger = ledger

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.ledger.closed.set()
        return False

    async def execute(self, stmt):
        self.ledger.queries += 1
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [_stored(2), _stored(1)]))


class Ledger:
    def __init__(self):
        self.queries = 0
        self.closed = threading.Event()

    def __call__(self):
        return _Session(self)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("EVENTSTORE_WS_AUTH_REQUIRED", raising=False)   # the frames' setting: no token required
    monkeypatch.setattr(internal_key, "_CURRENT", KEY)
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(ws_router.connection_manager, "_redis_url", None)   # local fan-out only, no Redis
    ledger = Ledger()
    monkeypatch.setattr(connection, "AsyncSessionLocal", ledger)
    application = FastAPI()
    application.include_router(ws_router.router)
    return application, ledger


def _drain(ws):
    """Everything the route sent until it answers a ping."""
    ws.send_json({"action": "ping"})
    got = []
    while True:
        msg = ws.receive_json()
        if msg.get("type") == "pong":
            return got
        got.append(msg)


def _subscribe_and_collect(app_and_ledger, url: str, channel: str = "events:all", live: bool = True):
    application, ledger = app_and_ledger
    with TestClient(application) as client, client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"action": "subscribe", "channel": channel})
        ledger.closed.wait(5.0)
        got = _drain(ws)
        if live:
            import asyncio

            client.portal.call(ws_router.connection_manager._local_broadcast_to_channel, channel, _live_message())
            client.portal.call(asyncio.sleep, 0.2)   # the connection's sender task runs before the ping sentinel
            got += _drain(ws)
    return [m["event"] for m in got if m.get("type") == "event"], got


def _text(events) -> str:
    import json
    return json.dumps(events)


def test_a_public_connection_gets_no_address_in_its_backlog_or_live(app):
    events, _ = _subscribe_and_collect(app, "/ws/events")
    assert len(events) == 3, events                      # two from the backlog, one live
    text = _text(events)
    assert "alice" not in text and "_at_" not in text and "@" not in text, text
    for e in events:
        assert OPAQUE.match(e["aggregate_id"]), e
        assert e["data"]["from"] == e["aggregate_id"]    # one account, one public id
        assert e["data"]["to"] == AGENT                  # an agent DID is untouched
    assert len({e["aggregate_id"] for e in events}) == 1  # stable across the backlog and the live stream


def test_a_connection_with_this_stores_key_gets_the_events_as_stored(app):
    events, _ = _subscribe_and_collect(app, f"/ws/events?token={KEY}")
    assert len(events) == 3
    assert all(e["aggregate_id"] == WALLET and e["data"]["from"] == WALLET for e in events), events
    assert "bob@example.org" in _text(events) and "carol@example.net" in _text(events)


def test_a_token_that_does_not_verify_makes_the_connection_public_not_refused(app):
    events, _ = _subscribe_and_collect(app, "/ws/events?token=not-the-key")
    assert events and all(OPAQUE.match(e["aggregate_id"]) for e in events), events


def test_a_public_connection_may_not_subscribe_to_a_personal_channel(app):
    events, got = _subscribe_and_collect(app, "/ws/events", channel=f"agent:{WALLET}", live=False)
    _, ledger = app
    assert events == [] and ledger.queries == 0, got
    assert not any(m.get("type") == "subscription_confirmed" for m in got), got
    assert any(m.get("type") == "error" and "refused" in m.get("message", "") for m in got), got


def test_a_credentialed_connection_may_subscribe_to_it(app):
    events, got = _subscribe_and_collect(app, f"/ws/events?token={KEY}", channel=f"agent:{WALLET}", live=False)
    assert {"type": "subscription_confirmed", "channel": f"agent:{WALLET}"} in got
    assert events and all(e["aggregate_id"] == WALLET for e in events)


def test_public_stats_name_no_personal_channel(app):
    application, ledger = app
    with TestClient(application) as client, client.websocket_connect(f"/ws/events?token={KEY}") as reactor:
        assert reactor.receive_json()["type"] == "connected"
        reactor.send_json({"action": "subscribe", "channel": f"agent:{WALLET}"})
        ledger.closed.wait(5.0)
        _drain(reactor)
        r = client.get("/ws/connections")
        assert r.status_code == 200, r.text
        assert "alice" not in r.text and "_at_" not in r.text, r.text
        assert r.json()["total_channels"] >= 1
        with client.websocket_connect("/ws/events") as visitor:
            assert visitor.receive_json()["type"] == "connected"
            visitor.send_json({"action": "stats"})
            stats = visitor.receive_json()
            assert stats["type"] == "stats" and "alice" not in _text(stats), stats
        reactor.send_json({"action": "stats"})
        assert f"agent:{WALLET}" in reactor.receive_json()["data"]["channels"]


def test_the_public_id_is_keyed_stable_and_distinct():
    import hashlib

    from src.personal_ids import public_account_id, withhold_personal_ids

    one = public_account_id(WALLET)
    assert OPAQUE.match(one) and public_account_id(WALLET) == one
    assert public_account_id("did:theprotocol:bob_at_example.com") != one
    assert one[len("account:"):] not in hashlib.sha256(WALLET.encode()).hexdigest()   # not an unkeyed hash
    assert withhold_personal_ids({WALLET: [f"to {WALLET}", "x@y.io"]}) == {one: [f"to {one}", "[address withheld]"]}


# ── The token is now read on a store that does not require one, so anyone can present one ──────────────────────────

def _jwt(header: dict) -> str:
    import base64
    import json as _json

    def b64(obj):
        return base64.urlsafe_b64encode(_json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{b64(header)}.{b64({'sub': 'spiffe://x/y', 'aud': 'a'})}.c2lnbmF0dXJl"


@pytest.fixture
def jwks(monkeypatch):
    import httpx

    calls = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": [{"kid": "k1", "kty": "EC", "crv": "P-256", "x": "x", "y": "y"}]}

    def fake_get(url, **kwargs):
        calls.append(url)
        if getattr(fake_get, "fail", False):
            raise httpx.ConnectError("the registry is not answering")
        return _Resp()

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(ws_router, "_JWKS_CACHE", {})
    monkeypatch.setattr(ws_router, "_JWKS_FETCH_STATE", {"forced": float("-inf"), "failed": float("-inf")})
    return calls, fake_get


def test_unknown_kids_cannot_make_the_store_fetch_keys_on_every_connection(jwks):
    calls, _ = jwks
    for n in range(6):
        ok, info = ws_router._validate_jwt(_jwt({"alg": "ES256", "kid": f"stranger-{n}"}))
        assert not ok, info
    assert len(calls) == 2, calls   # the first fetch, and one forced refresh per spacing


def test_a_failing_key_fetch_is_not_retried_by_every_token(jwks):
    calls, fake_get = jwks
    fake_get.fail = True
    for _ in range(5):
        assert not ws_router._validate_jwt(_jwt({"alg": "ES256", "kid": "k1"}))[0]
    assert len(calls) == 1, calls


def test_an_algorithm_a_spire_svid_cannot_carry_is_refused(jwks):
    for alg in ("HS256", "none"):
        ok, info = ws_router._validate_jwt(_jwt({"alg": alg, "kid": "k1"}))
        assert not ok and info.startswith("algorithm_not_allowed"), (alg, info)
