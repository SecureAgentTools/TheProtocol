"""D6-055 (V0658 (a)): an agent's locks and payouts are its owner's to read.

Four developer reads of the TEG: an agent's locked balance, its lock history, its pending payouts and its payout history
(the MCP tools getAgentLockedBalance, getAgentLockHistory, getAgentPendingPayouts and getAgentPayoutHistory). They follow
the rule of SEC-01's ledger reads (teg_transactions.reads_every_ledger): a developer reads the agents it created, a
treasury administrator reads every agent's, and anyone else is refused 403 before the TEG is asked.

Through FastAPI on the real TEG router. Doubles: the developer credential, the database session (it answers the
ownership read), and the TEG (it records each read it gets). RED on v0657/cut (e70fb58b2): the refusals.
"""
from __future__ import annotations

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.routers.teg_transactions import NOT_YOUR_LEDGER

AGENT = "did:theprotocol:eu.theprotocol.cloud:7d1e0c5a-2b44-4c6e-9b0b-0f6a3c2d1e55"
OWNER_ID = 7

ROUTES = {   # the registry's path -> (the TEG path it reads, the TEG's answer)
    "/api/v1/teg/staking/balance/{did}": ("/tokenomics/staking/balance/", {
        "agent_id": AGENT, "staked_balance": "5", "locked_balance": "5", "available_to_unstake": "0",
        "active_stakes": []}),
    "/api/v1/teg/staking/history/{did}": ("/tokenomics/staking/history/", {"transactions": [], "total": 0}),
    "/api/v1/teg/rewards/pending/{did}": ("/tokenomics/rewards/", {"pending_rewards": "0", "reward_sources": []}),
    "/api/v1/teg/rewards/history/{did}": ("/tokenomics/rewards/history/", {"rewards": [], "total_earned": "0"}),
}


def _developer(dev_id, **flags):
    base = {"is_admin": False, "admin_treasury": False, "must_change_password": False, "two_fa_enabled": False}
    base.update(flags)
    return types.SimpleNamespace(id=dev_id, email=f"dev{dev_id}@example.test", **base)


class _Row:
    def __init__(self, hit):
        self._hit = hit

    def first(self):
        return (1,) if self._hit else None


class _Db:
    """Answers the ownership read: the agent was created by OWNER_ID."""

    def __init__(self):
        self.asked = []

    async def execute(self, stmt, params=None):
        p = stmt.compile().params
        self.asked.append(p)
        return _Row(OWNER_ID in p.values() and AGENT in p.values())

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def teg(monkeypatch):
    """The TEG: records each path it is asked and answers the route's body."""
    asked = []

    class _Resp:
        def __init__(self, body):
            self.status_code, self._body = 200, body

        def json(self):
            return self._body

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            asked.append(url)
            tail = url.split("/tokenomics", 1)[1]
            for teg_path, body in sorted(ROUTES.values(), key=lambda v: -len(v[0])):
                if ("/tokenomics" + tail).startswith(teg_path):
                    return _Resp(body)
            raise AssertionError(f"unexpected TEG read {url}")
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    return asked


def _get(path, developer, db):
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = lambda: developer
    return TestClient(app, raise_server_exceptions=False).get(path.format(did=AGENT))


@pytest.mark.parametrize("path", list(ROUTES))
def test_another_developers_agent_is_refused_before_the_teg_is_asked(teg, path):
    r = _get(path, _developer(99), _Db())
    assert r.status_code == 403, (path, r.status_code, r.text[:300])
    assert r.json()["detail"] == NOT_YOUR_LEDGER
    assert teg == [], teg


@pytest.mark.parametrize("path", list(ROUTES))
def test_the_agents_owner_reads_it(teg, path):
    r = _get(path, _developer(OWNER_ID), _Db())
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    assert len(teg) == 1 and AGENT in teg[0], teg


@pytest.mark.parametrize("flags", [{"is_admin": True}, {"admin_treasury": True}])
@pytest.mark.parametrize("path", list(ROUTES))
def test_a_treasury_administrator_reads_any_agents(teg, path, flags):
    db = _Db()
    r = _get(path, _developer(99, **flags), db)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    assert db.asked == [] and len(teg) == 1, (db.asked, teg)


@pytest.mark.parametrize("path", list(ROUTES))
def test_an_administrator_who_must_change_the_password_reads_only_its_own(teg, path):
    r = _get(path, _developer(99, is_admin=True, must_change_password=True), _Db())
    assert r.status_code == 403 and teg == [], (path, r.status_code, teg)


def test_the_mcp_tools_say_whose_agent():
    import pathlib
    from agentvault_registry.mcp import tools_developer as td
    text = pathlib.Path(td.__file__).read_text()
    for n in ("theprotocol_getAgentPayoutHistory", "theprotocol_getAgentPendingPayouts",
              "theprotocol_getAgentLockedBalance", "theprotocol_getAgentLockHistory"):
        i = text.index(f'{{"name": "{n}"')
        line = text[i:text.index("\n", i)]
        assert "any agent DID" not in line and "an agent you created" in line, line
