"""SEC-04 (2026-10-17): a wrapped mint stands on a lock the source frame confirms.

POST /api/v1/bridge/mint-wrapped took the transfer id, the amount, the receiver and the source frame from its request
and minted that wrapped balance: nothing asked whether the named frame had locked anything, so any federation caller
could have a wrapped balance minted that no lock stood behind. Now (mirroring D6-345's /unlock, which releases only a
lock the frame itself recorded):

  * the source frame is the caller: an active frame peer, named by its own identity (its peer row gives the address);
    a `source_frame` that names another frame is refused;
  * before anything is minted, that frame confirms the lock: POST /api/v1/bridge/confirm-lock answers `confirmed` only
    for a transfer it recorded and still holds locked (not about to expire), for the owner, receiver and amount the
    mint asks, and only to the frame the transfer targets. Any other answer, or none, mints nothing.

Through FastAPI on the real bridge router; each frame's database is a double holding its bridge records and peer rows,
the TEG is a recorder, and the federation identity is supplied. The last test runs both frames as two apps that call
each other through ASGI, so the transfer, the mint and the confirmation meet as they do between two registries.
RED on 453cc8b8: every test but the end-to-end control (the base mints whatever the request says without asking, and
has no /confirm-lock); the control, an honest transfer between two frames, completes before and after.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.core.federation_auth import get_federation_identity
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import token_bridge

TX = "5c0d7a1e-2222-4333-8444-955566667777"
A_URL, A_TD = "https://frame-a.example.invalid:8443", "frame-a.example.invalid"
B_URL, B_TD = "https://frame-b.example.invalid:8443", "frame-b.example.invalid"
C_TD = "frame-c.example.invalid"
A1, B1 = "did:theprotocol:a:sender", "did:theprotocol:b:receiver"
MINT = {"bridge_tx_id": TX, "source_agent_did": A1, "target_agent_did": B1, "amount": "5", "source_frame": A_TD}


def _lock(status="LOCKED", expires_in=240):
    return SimpleNamespace(id=TX, direction="outbound", source_frame_id=A_TD, target_frame_id=B_URL,
                           source_agent_did=A1, target_agent_did=B1, amount=Decimal("5.000000"), status=status,
                           idempotency_key=f"bridge-{TX}",
                           expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in))


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class _Db:
    """One frame's database: its bridge records (matched on the id or key and the direction the query names) and its
    peer rows (every row: the bridge filters frames by trust domain itself)."""

    def __init__(self, txs=(), frames=()):
        self.txs, self.frames = list(txs), list(frames)

    async def execute(self, stmt, *a, **k):
        if stmt.column_descriptions[0]["name"] == "PeerRegistry":
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


def _frames():
    return [SimpleNamespace(name="frame-a", base_url=A_URL, trust_domain=A_TD, peer_type="frame", status="ACTIVE"),
            SimpleNamespace(name="frame-b", base_url=B_URL, trust_domain=B_TD, peer_type="frame", status="ACTIVE")]


@pytest.fixture()
def wires(monkeypatch):
    calls = {"teg": [], "remote": [], "emitter_calls": [], "confirm": None}

    async def _teg(endpoint, body):
        calls["teg"].append((endpoint, dict(body)))
        return {"tx_id": f"teg-{endpoint}"}

    async def _remote(url, endpoint, body):
        calls["remote"].append((url, endpoint, dict(body)))
        answer = calls["confirm"]
        if callable(answer):
            return answer(body)
        return answer

    async def _emitted(*a, **k):
        calls["emitter_calls"].append(k.get("event_type"))

    async def _no_spend_gate(*a, **k):
        return None
    monkeypatch.setattr(token_bridge, "_call_teg", _teg)
    monkeypatch.setattr(token_bridge, "_call_remote_frame", _remote)
    monkeypatch.setattr(token_bridge, "emit_or_report", _emitted)
    monkeypatch.setattr(token_bridge, "get_event_emitter", lambda: None)
    monkeypatch.setattr(token_bridge, "enforce_agent_spend", _no_spend_gate)
    monkeypatch.setenv("AGENT_RBAC_MODE", "off")
    return calls


def _app(db, *, peer=None, agent=None, frame_td=None, monkeypatch=None):
    app = FastAPI()
    app.include_router(token_bridge.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    if peer:
        app.dependency_overrides[get_federation_identity] = lambda: f"spiffe://{peer}/service/registry"
    if agent:
        app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(did=agent, id=1)
        app.dependency_overrides[security.verify_agent_token] = lambda: {"sub": agent}
    return app


def _client(db, **kw):
    return TestClient(_app(db, **kw), raise_server_exceptions=False)


def _confirmation(**over):
    return dict({"confirmed": True, "bridge_tx_id": TX, "source_agent_did": A1, "target_agent_did": B1,
                 "amount": "5.000000", "source_frame": A_TD}, **over)


# ── the target frame's /mint-wrapped ───────────────────────────────────────────────────────────────────────────────

def test_mint_refuses_a_lock_the_source_frame_does_not_confirm(wires):
    def _no_such_lock(body):
        raise HTTPException(404, "No bridge transfer with this id locked units on this frame")
    wires["confirm"] = _no_such_lock
    db = _Db([], _frames())
    r = _client(db, peer=A_TD).post("/api/v1/bridge/mint-wrapped", json=MINT)
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert "nothing was issued" in r.text
    assert wires["teg"] == [] and db.txs == [] and wires["emitter_calls"] == [], "a refused mint reported an event"


def test_mint_refuses_a_caller_that_is_not_an_active_frame_peer(wires):
    wires["confirm"] = _confirmation()
    r = _client(_Db([], _frames()), peer=C_TD).post("/api/v1/bridge/mint-wrapped",
                                                     json=dict(MINT, source_frame=C_TD))
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert wires["teg"] == [] and wires["remote"] == []


def test_mint_refuses_a_source_frame_that_is_not_the_caller(wires):
    """Frame B's peer A may not name frame C (or any other) as the frame whose lock backs the mint."""
    wires["confirm"] = _confirmation()
    r = _client(_Db([], _frames()), peer=A_TD).post("/api/v1/bridge/mint-wrapped",
                                                     json=dict(MINT, source_frame=C_TD))
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert wires["teg"] == [] and wires["remote"] == []


def test_mint_refuses_a_confirmation_of_another_lock(wires):
    wires["confirm"] = _confirmation(amount="5000")
    db = _Db([], _frames())
    r = _client(db, peer=A_TD).post("/api/v1/bridge/mint-wrapped", json=MINT)
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert wires["teg"] == [] and db.txs == []


def test_mint_refuses_when_the_source_frame_cannot_be_asked(wires):
    def _down(body):
        raise httpx.ConnectError("unreachable")
    wires["confirm"] = _down
    db = _Db([], _frames())
    r = _client(db, peer=A_TD).post("/api/v1/bridge/mint-wrapped", json=MINT)
    assert r.status_code == 503, (r.status_code, r.text[:300])
    assert wires["teg"] == [] and db.txs == []


def test_mint_asks_the_calling_frame_at_its_peer_address_for_this_lock(wires):
    wires["confirm"] = _confirmation()
    _client(_Db([], _frames()), peer=A_TD).post("/api/v1/bridge/mint-wrapped", json=MINT)
    (url, endpoint, body), = wires["remote"]
    assert (url, endpoint) == (A_URL, "confirm-lock")
    assert body == {"bridge_tx_id": TX, "source_agent_did": A1, "target_agent_did": B1, "amount": "5"}


def test_a_confirmed_lock_is_minted_once(wires):
    wires["confirm"] = _confirmation()
    db = _Db([], _frames())
    c = _client(db, peer=A_TD)
    r = c.post("/api/v1/bridge/mint-wrapped", json=MINT)
    assert r.status_code == 200 and r.json()["status"] == "minted", (r.status_code, r.text[:300])
    assert [e for e, _ in wires["teg"]] == ["mint"] and wires["teg"][0][1]["agent_id"] == B1
    (row,) = db.txs
    assert (row.direction, row.source_frame_id, row.status) == ("inbound", A_TD, "COMPLETED")
    again = c.post("/api/v1/bridge/mint-wrapped", json=MINT)
    assert again.status_code == 200 and again.json()["status"] == "already_minted"
    assert [e for e, _ in wires["teg"]] == ["mint"] and len(wires["remote"]) == 1
    assert wires["emitter_calls"] == ["WrappedTokensMinted"], wires["emitter_calls"]


# ── the source frame's /confirm-lock ───────────────────────────────────────────────────────────────────────────────

ASK = {"bridge_tx_id": TX, "source_agent_did": A1, "target_agent_did": B1, "amount": "5"}


def test_confirm_refuses_a_lock_it_never_made(wires):
    r = _client(_Db([], _frames()), peer=B_TD).post("/api/v1/bridge/confirm-lock", json=ASK)
    assert r.status_code == 404 and "locked units on this frame" in r.text, (r.status_code, r.text[:300])


def test_confirm_refuses_a_frame_the_transfer_does_not_target(wires):
    r = _client(_Db([_lock()], _frames()), peer=C_TD).post("/api/v1/bridge/confirm-lock", json=ASK)
    assert r.status_code == 403 and "targets" in r.text, (r.status_code, r.text[:300])


@pytest.mark.parametrize("field,value", [("source_agent_did", "did:theprotocol:a:victim"),
                                         ("target_agent_did", "did:theprotocol:b:other"), ("amount", "500")])
def test_confirm_refuses_another_owner_receiver_or_amount(wires, field, value):
    r = _client(_Db([_lock()], _frames()), peer=B_TD).post("/api/v1/bridge/confirm-lock", json=dict(ASK, **{field: value}))
    assert r.status_code == 409 and "does not match" in r.text, (r.status_code, r.text[:300])


@pytest.mark.parametrize("status", ["INITIATED", "COMPLETED", "FAILED", "EXPIRED", "REDEEMED"])
def test_confirm_refuses_a_lock_it_no_longer_holds(wires, status):
    r = _client(_Db([_lock(status=status)], _frames()), peer=B_TD).post("/api/v1/bridge/confirm-lock", json=ASK)
    assert r.status_code == 409 and status in r.text, (r.status_code, r.text[:300])


def test_confirm_refuses_a_lock_about_to_expire(wires):
    r = _client(_Db([_lock(expires_in=20)], _frames()), peer=B_TD).post("/api/v1/bridge/confirm-lock", json=ASK)
    assert r.status_code == 409 and "expires" in r.text, (r.status_code, r.text[:300])


def test_control_the_target_frame_gets_its_lock_confirmed_and_nothing_changes(wires):
    lock = _lock()
    r = _client(_Db([lock], _frames()), peer=B_TD).post("/api/v1/bridge/confirm-lock", json=ASK)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    body = r.json()
    assert body["confirmed"] is True and body["bridge_tx_id"] == TX and Decimal(body["amount"]) == Decimal("5")
    assert (body["source_agent_did"], body["target_agent_did"]) == (A1, B1)
    assert lock.status == "LOCKED" and wires["teg"] == []


# ── both frames: the transfer, the mint and the confirmation meet ──────────────────────────────────────────────────

def test_control_a_transfer_between_two_frames_still_completes(wires, monkeypatch):
    """Frame A (source) and frame B (target) as two apps, each with its own database; their registries call each other
    through ASGI with the caller's identity as each app sees it. A's transfer locks, B (after asking A to confirm the
    lock, which A does) mints: the lock is COMPLETED on A and the mint recorded once on B, from A."""
    db_a, db_b = _Db([], _frames()), _Db([], _frames())
    app_a = _app(db_a, peer=B_TD, agent=A1)    # A is called by B (confirm-lock) and by its own agent (transfer)
    app_b = _app(db_b, peer=A_TD)              # B is called by A (mint-wrapped)
    apps = {A_URL: app_a, B_URL: app_b}

    async def _between_frames(url, endpoint, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[url]), base_url="http://frame") as c:
            resp = await c.post(f"/api/v1/bridge/{endpoint}", json=body)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Remote frame bridge/{endpoint} failed: {resp.text[:200]}")
        return resp.json()
    monkeypatch.setattr(token_bridge, "_call_remote_frame", _between_frames)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", A_TD)

    r = TestClient(app_a, raise_server_exceptions=False).post("/api/v1/bridge/transfer", json={
        "target_agent_did": B1, "amount": "5", "target_frame_url": B_URL})
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED", (r.status_code, r.text[:400])
    (out,) = db_a.txs
    (inb,) = db_b.txs
    assert out.status == "COMPLETED" and out.direction == "outbound"
    assert (inb.direction, inb.source_frame_id, inb.idempotency_key) == ("inbound", A_TD, f"bridge-{out.id}")
    assert [e for e, _ in wires["teg"]] == ["lock", "mint"]
