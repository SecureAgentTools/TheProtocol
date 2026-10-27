"""CB-457 (2026-10-16): authorize asks every payer's wallet the settlement's permission question, not only a delegated one.

The settlement of a payment token is an ordinary transfer from the paying wallet: /teg/transfer (teg.transfer) to a
payee on this registry, /teg/cross-registry-transfer (teg.transfer_xreg) to one on another. POST
/api/v1/a2a-payment/authorize checked that permission only for an anchored hand's wallet, so under enforce an agent
holding `client` (a2a.pay, teg.transfer) but not teg.transfer_xreg was authorized to pay a remote service, the service
delivered, and the settlement was refused (403): delivered work, a failed token. Now authorize refuses such a payment
(403, nothing authorized) before any service is called; a payer whose rail admits it is authorized as before.

Through FastAPI on the real route under AGENT_RBAC_MODE=enforce; the database is a double (the agent's role grants,
whether the payee is local, the pending-token count, the new token row), the provider gates (bond, enforcement) and the
spend-policy read are stubbed, and the authenticated agent is supplied.
RED on 7140a4a6: test_a_client_cannot_authorize_a_remote_payment (200 on the base).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import a2a_payment

PAYER = "did:theprotocol:sec2:payer"
LOCAL_PAYEE = "did:theprotocol:sec2:local-service"
REMOTE_PAYEE = "did:theprotocol:elsewhere:remote-service"


class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows, self._scalar = list(rows), scalar

    def fetchall(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._scalar


class _Db:
    def __init__(self, roles):
        self.roles = roles
        self.added = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "FROM agent_role_grants" in sql:
            return _Result(rows=[("role", r) for r in self.roles])
        if "FROM agents" in sql:   # _is_local_agent: is the payee on this registry?
            local = LOCAL_PAYEE in str(stmt.compile(compile_kwargs={"literal_binds": True}))
            return _Result(scalar=1 if local else None)
        return _Result()

    async def scalar(self, stmt):
        return 0   # no pending tokens

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = obj.id or "tok-0001"

    async def rollback(self):
        pass

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    async def _admit(*a, **k):
        return None

    async def _emitted(*a, **k):
        return None

    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce")
    monkeypatch.setattr(a2a_payment._rb, "gate", _admit)
    monkeypatch.setattr(a2a_payment._ep, "gate", _admit)
    monkeypatch.setattr(a2a_payment, "enforce_agent_spend", _admit)
    monkeypatch.setattr(a2a_payment, "emit_or_report", _emitted)


def _authorize(roles, payee):
    db = _Db(roles)
    app = FastAPI()
    app.include_router(a2a_payment.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(
        did=PAYER, id=3, liquid_balance=100, status="active")
    app.dependency_overrides[security.verify_agent_token] = lambda: {"sub": PAYER, "type": "agent"}
    r = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/a2a-payment/authorize", json={"target_agent_did": payee, "amount": "1.5"})
    return r, db


def test_a_client_cannot_authorize_a_remote_payment():
    r, db = _authorize(["client"], REMOTE_PAYEE)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert "teg.transfer_xreg" in r.text and "Nothing was authorized" in r.text
    assert db.added == [], "a token was minted for a payment the settlement would refuse"


def test_control_a_client_authorizes_a_local_payment():
    r, db = _authorize(["client"], LOCAL_PAYEE)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.json()["token"].startswith("apt_") and len(db.added) == 1


def test_control_a_trader_and_client_authorizes_a_remote_payment():
    r, _ = _authorize(["client", "trader"], REMOTE_PAYEE)
    assert r.status_code == 200, (r.status_code, r.text[:300])
