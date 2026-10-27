"""D6-272 (2026-10-17): a cross-registry delegation revoke is recorded at the issuer's home whatever became of the ship.

DELETE /api/v1/agents/delegate-cross-registry/{credential_id} sends the revoke to the delegate's home. The issuer
side's record of it (the `ironkey.xreg_delegation_revoke` audit row) is what the issuer-authority answer reads
(services/xreg_issuer_authority.issuer_answer), and the delegate's home asks that answer before the delegation conveys
anything. The record is written whether the send was delivered, refused by the delegate's home, or could not be made
at all.

Corrected for D6-272's durable delivery (2026-10-17): a send that did not land is now sent again later
(tests/test_xreg_revoke_delivery.py), so every recorded revoke answers 200 with `ok` (this send landed) and `delivery`;
the 502 for a send that could not be made and the resolver's 400 are gone, and the session double holds the issue
record the route now looks up (a revoke is sent only for a delegation this agent issued).

Through FastAPI on the real router; the federation client and the peer resolution are doubles, the audit writer and
the event emitter record what they are given. RED on 15620967: the two tests of a ship that could not be sent (no
record at all); the control of a delivered ship and the refused-ship case are green before and after.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_delegation_api as deleg
from agentvault_registry.routers import guild

ISSUER = "did:theprotocol:eu.theprotocol.cloud:issuer-0001"
PEER = "https://asia.example.invalid"
CRED = "cred-0123456789abcdef"


class _Db:
    """The issue record of CRED by ISSUER (the route's lookup), and the owed-delivery row it may add."""

    def __init__(self):
        self.owed = {}

    async def execute(self, stmt, params=None):
        assert "ironkey.xreg_delegation_issue" in str(stmt), str(stmt)
        details = json.dumps({"credential_id": CRED, "delegate_registry": PEER, "permissions": ["teg.transfer"],
                              "expires_at": "2099-01-01T00:00:00+00:00"})
        return SimpleNamespace(all=lambda: [(details,)] if (params or {}).get("iss") == ISSUER else [])

    async def get(self, model, pk):
        return self.owed.get(pk)

    def add(self, obj):
        self.owed[obj.credential_id] = obj


class _Resp:
    def __init__(self, status_code, text="{}"):
        self.status_code, self.text = status_code, text


@pytest.fixture
def route(monkeypatch):
    rec = {"audit": [], "emitter_calls": [], "posts": []}
    state = {"answer": _Resp(200, '{"ok": true}'), "resolve": None}

    async def _audit(db, **k):
        rec["audit"].append(k)

    class _Emitter:
        def emit_background(self, **k):
            rec["emitter_calls"].append(k)

    class _Client:
        def __init__(self, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            rec["posts"].append((url, json))
            a = state["answer"]
            if isinstance(a, Exception):
                raise a
            return a

    async def _resolve(db, url):
        if state["resolve"] is not None:
            raise state["resolve"]
        return url

    import agentvault_registry.event_emitter as em
    monkeypatch.setenv("AGENT_XREG_DELEGATION_ENABLED", "true")
    monkeypatch.setenv("AGENT_RBAC_MODE", "off")
    monkeypatch.setattr(deleg, "log_ironkey_action", _audit)
    monkeypatch.setattr(em, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(guild, "_resolve_peer_url", _resolve)
    monkeypatch.setattr(guild, "_fed_client_config", lambda target: ({}, {}))
    monkeypatch.setattr(guild, "_self_public_url", lambda: "https://eu.example.invalid")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    app = FastAPI()
    app.include_router(deleg.router)
    db = _Db()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(did=ISSUER, id=1, status="active")
    app.dependency_overrides[security.verify_agent_token] = lambda: {"type": "agent"}
    client = TestClient(app, raise_server_exceptions=False)

    def _revoke():
        return client.delete(f"/agents/delegate-cross-registry/{CRED}", params={"delegate_registry_url": PEER})
    return SimpleNamespace(revoke=_revoke, rec=rec, state=state, db=db)


def _the_record(rec):
    rows = [a for a in rec["audit"] if a.get("action") == "xreg_delegation_revoke"]
    assert len(rows) == 1, f"the issuer side recorded {len(rows)} revokes: {rec['audit']}"
    row = rows[0]
    assert (row["actor_id"], row["target_id"], row["actor_type"]) == (ISSUER, CRED, "agent")
    return row


def test_a_revoke_whose_ship_could_not_be_sent_is_recorded_and_says_so(route):
    route.state["answer"] = httpx.ConnectError("connection refused")
    r = route.revoke()
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.json()["ok"] is False and r.json()["delivery"]["state"] == "retrying"
    assert CRED in route.db.owed, "the send that did not land is owed"
    row = _the_record(route.rec)
    assert row["outcome"] == "ship_failed" and row["details"]["ship_error"] == "ConnectError"
    assert row["details"]["peer_status"] is None
    assert len(route.rec["emitter_calls"]) == 1 and route.rec["emitter_calls"][0]["event_type"] == "AgentXRegDelegationRevoked"


def test_a_revoke_to_a_registry_that_is_not_a_peer_is_recorded_before_the_refusal(route):
    route.state["resolve"] = HTTPException(400, detail="not an approved peer")
    r = route.revoke()
    assert r.status_code == 200 and "not an approved peer" in r.json()["delivery"]["last_error"]
    assert route.rec["posts"] == []
    assert _the_record(route.rec)["outcome"] == "ship_failed"


def test_a_revoke_the_delegates_home_refused_is_recorded_and_answers_not_ok(route):
    route.state["answer"] = _Resp(503, "unavailable")
    r = route.revoke()
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["peer_status"] == 503
    assert _the_record(route.rec)["outcome"] == "ship_failed"


def test_control_a_delivered_revoke_is_recorded_as_delivered(route):
    r = route.revoke()
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("ok", "peer_status", "peer_response", "delegate_registry")} == \
        {"ok": True, "peer_status": 200, "peer_response": '{"ok": true}', "delegate_registry": PEER}
    assert r.json()["delivery"]["state"] == "delivered" and route.db.owed == {}
    assert route.rec["posts"] == [(f"{PEER}/api/v1/federation/ironkey/delegation-revoke",
                                   {"credential_id": CRED, "issuer_registry": "https://eu.example.invalid"})]
    assert _the_record(route.rec)["outcome"] == "success"


def test_the_record_is_the_one_the_issuer_authority_answer_reads():
    """The route writes action `xreg_delegation_revoke` through log_ironkey_action, which records `ironkey.<action>`:
    the very action issuer_answer looks for (whatever the outcome)."""
    import inspect
    from agentvault_registry.services import xreg_issuer_authority as xia
    src = inspect.getsource(xia.issuer_answer)
    assert "action = 'ironkey.xreg_delegation_revoke'" in src and "outcome" not in src.split("xreg_delegation_revoke")[1][:80]
