"""D6-345 (2026-10-16): a bridge unlock releases one recorded lock, once, for the frame that holds its wrapped units.

POST /api/v1/bridge/unlock took the agent, the amount and an id from the request and asked the TEG to move that much
from that agent's locked balance (which 2PC locks also use) to its liquid one: any federation caller could release
any agent's locked units without a bridge transfer behind them. POST /api/v1/bridge/redeem likewise took the source
frame's URL and the agent whose units are locked from the caller. Now:

  * /redeem names the bridge transfer (`bridge_tx_id`); the caller must be the agent its wrapped units were minted to,
    it must not be redeemed yet, and the amount, the locked agent and the source frame (from the peer table) come
    from this frame's record of that transfer;
  * /unlock releases exactly the lock it names: the owner and amount come from the lock's record (a sent value must
    match), the caller must be the frame the wrapped units were minted on, and a released lock is not released again.

Through FastAPI on the real bridge router; the database is a double holding the bridge records and peer rows, the
TEG and the remote frame are recorders, and the agent and federation identities are supplied.
RED on 7140a4a6: every test named *refuses* or *only* (the base moves units for what the request says).
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.core.federation_auth import get_federation_identity
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import token_bridge

TX = "0b0e5f4e-1111-4222-8333-944455556666"
A_URL, A_TD = "https://frame-a.example.invalid:8443", "frame-a.example.invalid"
B_URL, B_TD = "https://frame-b.example.invalid:8443", "frame-b.example.invalid"
C_TD = "frame-c.example.invalid"
A1, B1, B2 = "did:theprotocol:a:sender", "did:theprotocol:b:holder", "did:theprotocol:b:stranger"


def _outbound(status="COMPLETED"):
    return SimpleNamespace(id=TX, direction="outbound", source_frame_id=A_TD, target_frame_id=B_URL,
                           source_agent_did=A1, target_agent_did=B1, amount=Decimal("5.000000"), status=status,
                           idempotency_key=f"bridge-{TX}", unlock_tx_id=None, burn_tx_id=None, error_message=None)


def _inbound(status="COMPLETED"):
    return SimpleNamespace(id="row-b-1", direction="inbound", source_frame_id=A_TD, target_frame_id=B_TD,
                           source_agent_did=A1, target_agent_did=B1, amount=Decimal("5.000000"), status=status,
                           idempotency_key=f"bridge-{TX}", unlock_tx_id=None, burn_tx_id=None, error_message=None)


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class _Db:
    def __init__(self, txs=(), frames=()):
        self.txs, self.frames = list(txs), list(frames)

    async def execute(self, stmt, *a, **k):
        entity = stmt.column_descriptions[0]["name"]
        if entity == "PeerRegistry":
            return _Result(self.frames)
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        return _Result([t for t in self.txs
                        if (f"'{t.id}'" in sql or f"'{t.idempotency_key}'" in sql) and f"'{t.direction}'" in sql])

    def add(self, obj):
        self.txs.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass


def _frames():
    return [SimpleNamespace(name="frame-a", base_url=A_URL, trust_domain=A_TD, peer_type="frame", status="ACTIVE"),
            SimpleNamespace(name="frame-b", base_url=B_URL, trust_domain=B_TD, peer_type="frame", status="ACTIVE")]


@pytest.fixture()
def wires(monkeypatch):
    calls = {"teg": [], "remote": [], "emitter_calls": []}

    async def _teg(endpoint, body):
        calls["teg"].append((endpoint, dict(body)))
        return {"tx_id": f"teg-{endpoint}"}

    async def _remote(url, endpoint, body):
        calls["remote"].append((url, endpoint, dict(body)))
        return {"status": "unlocked", "tx_id": "remote-unlock"}

    async def _no_spend_gate(*a, **k):
        return None

    async def _emitted(*a, **k):
        calls["emitter_calls"].append((a, k))
        return None

    monkeypatch.setattr(token_bridge, "_call_teg", _teg)
    monkeypatch.setattr(token_bridge, "_call_remote_frame", _remote)
    monkeypatch.setattr(token_bridge, "enforce_agent_spend", _no_spend_gate)
    monkeypatch.setattr(token_bridge, "emit_or_report", _emitted)
    monkeypatch.setattr(token_bridge, "get_event_emitter", lambda: None)
    monkeypatch.setenv("AGENT_RBAC_MODE", "off")
    return calls


def _client(db, *, agent=None, peer=None):
    app = FastAPI()
    app.include_router(token_bridge.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    if agent:
        app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(did=agent, id=1)
        app.dependency_overrides[security.verify_agent_token] = lambda: {"sub": agent}
    if peer:
        app.dependency_overrides[get_federation_identity] = lambda: f"spiffe://{peer}/service/registry"
    return TestClient(app, raise_server_exceptions=False)


# ── the source frame's /unlock ─────────────────────────────────────────────────────────────────────────────────────

def test_unlock_refuses_a_lock_it_never_made(wires):
    r = _client(_Db([], _frames()), peer=B_TD).post("/api/v1/bridge/unlock", json={
        "bridge_tx_id": "no-such-transfer", "agent_did": A1, "amount": "5"})
    assert r.status_code == 404, (r.status_code, r.text[:300])
    assert wires["teg"] == []
    assert not wires["emitter_calls"], "a refused unlock reported an event"


def test_unlock_refuses_another_owner_or_amount(wires):
    db = _Db([_outbound()], _frames())
    r = _client(db, peer=B_TD).post("/api/v1/bridge/unlock", json={
        "bridge_tx_id": TX, "agent_did": "did:theprotocol:a:victim", "amount": "500"})
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert wires["teg"] == []


def test_unlock_refuses_a_frame_that_does_not_hold_the_wrapped_units(wires):
    r = _client(_Db([_outbound()], _frames()), peer=C_TD).post("/api/v1/bridge/unlock", json={
        "bridge_tx_id": TX, "agent_did": A1, "amount": "5"})
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert wires["teg"] == []


def test_unlock_refuses_a_transfer_that_never_completed(wires):
    r = _client(_Db([_outbound(status="FAILED")], _frames()), peer=B_TD).post("/api/v1/bridge/unlock", json={
        "bridge_tx_id": TX, "agent_did": A1, "amount": "5"})
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert wires["teg"] == []


def test_control_the_holder_frame_releases_the_recorded_lock(wires):
    lock = _outbound()
    db = _Db([lock], _frames())
    c = _client(db, peer=B_TD)
    r = c.post("/api/v1/bridge/unlock", json={"bridge_tx_id": TX, "agent_did": A1, "amount": "5"})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert len(wires["teg"]) == 1 and wires["teg"][0][0] == "unlock"
    assert wires["teg"][0][1]["agent_id"] == A1 and Decimal(wires["teg"][0][1]["amount"]) == Decimal("5")
    r2 = c.post("/api/v1/bridge/unlock", json={"bridge_tx_id": TX, "agent_did": A1, "amount": "5"})
    assert r2.status_code == 200, (r2.status_code, r2.text[:300])


def test_a_released_lock_is_only_released_once(wires):
    db = _Db([_outbound()], _frames())
    c = _client(db, peer=B_TD)
    for _ in range(2):
        assert c.post("/api/v1/bridge/unlock", json={"bridge_tx_id": TX, "agent_did": A1, "amount": "5"}).status_code == 200
    assert [e for e, _ in wires["teg"]] == ["unlock"], wires["teg"]


# ── the holder frame's /redeem ─────────────────────────────────────────────────────────────────────────────────────

LEGACY_BODY = {"bridge_tx_id": TX, "amount": "5", "source_frame_url": A_URL, "source_agent_did": A1}


def test_redeem_refuses_a_caller_the_units_were_not_minted_to(wires):
    r = _client(_Db([_inbound()], _frames()), agent=B2).post("/api/v1/bridge/redeem", json=LEGACY_BODY)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert wires["teg"] == [] and wires["remote"] == []


def test_redeem_refuses_to_name_another_locked_agent(wires):
    body = dict(LEGACY_BODY, source_agent_did="did:theprotocol:a:victim", source_frame_url="https://elsewhere.invalid")
    r = _client(_Db([_inbound()], _frames()), agent=B1).post("/api/v1/bridge/redeem", json=body)
    assert r.status_code == 422, (r.status_code, r.text[:300])
    assert wires["teg"] == [] and wires["remote"] == []


def test_redeem_refuses_a_transfer_already_redeemed(wires):
    r = _client(_Db([_inbound(status="REDEEMED")], _frames()), agent=B1).post("/api/v1/bridge/redeem", json=LEGACY_BODY)
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert wires["teg"] == [] and wires["remote"] == []


def test_control_the_holder_redeems_its_transfer(wires):
    row = _inbound()
    r = _client(_Db([row], _frames()), agent=B1).post("/api/v1/bridge/redeem", json=LEGACY_BODY)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert [e for e, _ in wires["teg"]] == ["burn"], wires["teg"]
    (url, endpoint, body), = wires["remote"]
    assert endpoint == "unlock" and url.rstrip("/") == A_URL and body["agent_did"] == A1


def test_redeem_dials_only_the_frame_and_the_lock_of_its_record(wires):
    """The unlock goes to the source frame the peer table names, for the transfer's own id."""
    _client(_Db([_inbound()], _frames()), agent=B1).post("/api/v1/bridge/redeem", json=LEGACY_BODY)
    (url, endpoint, body), = wires["remote"]
    assert body["bridge_tx_id"] == TX, body
