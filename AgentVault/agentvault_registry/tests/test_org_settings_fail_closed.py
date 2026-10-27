"""§SECFIX D6-491 (2026-10-16): an organization's settings that cannot be read refuse; they never read as "none".

An organization's settings only TIGHTEN what the registry allows: liability, the spend ceiling, the consent posture,
standing consent. Measured on the wave-1 base (7140a4a6) through the calls below: org_policy.get_org_settings turned
every read error into {} (no organization), so a database error lifted them all at once. GET /liability/posture
answered the registry's weaker posture as the one in force, the liability gate let an action through that the
organization's liability mode would have stopped, and an anchored payment was admitted past the organization's spend
ceiling. The spend gate already refused a failed read under enforce (§SECFIX-1), but the read never failed, so that
refusal could not fire (tests/test_authz_reads_fail_closed.py pinned it with a stand-in that raised where the real
reader did not; it now runs the real one).

Now the read raises OrgSettingsUnavailable (503, nothing done, Retry-After), and every caller refuses. The session
below is the only stand-in: its query fails as a lost connection does, or answers the organization's settings row.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import OperationalError

from agentvault_registry import models
from agentvault_registry.config import settings as app_settings
from agentvault_registry.database import get_db
from agentvault_registry.routers import liability as liability_router
from agentvault_registry.security import get_current_developer

AGENT = "did:theprotocol:sandbox-a.theprotocol.cloud:org-agent-0001"
TARGET = "did:theprotocol:sandbox-a.theprotocol.cloud:service-0002"


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False          # a real SAVEPOINT is rolled back here; the error goes on to the caller


class _Rows:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Db:
    """The read org_policy.get_org_settings makes: the organization's settings row, or a lost connection."""

    def __init__(self, org_settings=None, fails=False):
        self.org_settings, self.fails, self.reads = org_settings, fails, 0

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt, params=None):
        self.reads += 1
        if self.fails:
            raise OperationalError(str(stmt), params, ConnectionResetError("server closed the connection"))
        return _Rows((self.org_settings,) if self.org_settings is not None else None)


HARDENED_ORG = {"cockpit_posture": "hardened", "liability": {"mode": "enforce"}, "org_spend_ceiling_avt": 1}


# ── the consent posture, through FastAPI on the real router ─────────────────────────────────────────────────────

@pytest.fixture()
def posture(monkeypatch):
    monkeypatch.setattr(app_settings, "LIABILITY_MODE", "shadow", raising=False)
    monkeypatch.delenv("COCKPIT_POSTURE", raising=False)             # the registry's own posture: swift
    app = FastAPI()
    app.include_router(liability_router.router)
    app.dependency_overrides[get_current_developer] = lambda: models.Developer(id=5, name="d", email="d@example.org")

    async def get(db):
        async def _db():
            yield db
        app.dependency_overrides[get_db] = _db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.get("/api/v1/liability/posture", params={"agent_did": AGENT})

    return get


async def test_control_the_organizations_stricter_posture_is_the_one_in_force(posture):
    r = await posture(_Db(HARDENED_ORG))
    assert r.status_code == 200, r.text
    assert (r.json()["posture"], r.json()["source"]) == ("hardened", "organization")


async def test_an_unreadable_organization_refuses_rather_than_answer_the_registrys_posture(posture):
    db = _Db(fails=True)
    r = await posture(db)
    assert db.reads == 1
    assert r.status_code == 503, r.text                 # the base answered 200: swift, from the registry
    assert r.json()["detail"].startswith("org_settings_unavailable")
    assert r.headers.get("retry-after") == "5"


# ── the liability gate ─────────────────────────────────────────────────────────────────────────────────────────

async def test_the_liability_gate_refuses_when_the_organizations_mode_cannot_be_read(monkeypatch):
    from agentvault_registry.services import liability as liab
    monkeypatch.setattr(app_settings, "LIABILITY_MODE", "off", raising=False)   # only the organization enforces
    with pytest.raises(HTTPException) as e:
        await liab.check_liability_gate(_Db(fails=True), AGENT, "contracts.engage", amount=10, currency="SBXA",
                                        counterparty_did=None)
    assert e.value.status_code == 503           # the base returned None: the action went ahead with no mandate


async def test_control_an_agent_without_an_organization_passes_a_gate_the_registry_leaves_off(monkeypatch):
    from agentvault_registry.services import liability as liab
    monkeypatch.setattr(app_settings, "LIABILITY_MODE", "off", raising=False)
    assert await liab.check_liability_gate(_Db(None), AGENT, "contracts.engage", amount=10, currency="SBXA",
                                           counterparty_did=None) is None


# ── an anchored payment's purse: the organization's spend ceiling ──────────────────────────────────────────────

@pytest.fixture()
def purse(monkeypatch):
    from agentvault_registry import agent_authz
    from agentvault_registry.routers import a2a_payment

    async def _perms(*_a, **_k):
        return {"teg.transfer"}

    async def _policy(*_a, **_k):
        return True, None

    async def _local(*_a, **_k):
        return True

    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce")
    monkeypatch.setattr(agent_authz, "resolve_agent_permissions", _perms)
    monkeypatch.setattr(agent_authz, "check_spend_policy", _policy)
    monkeypatch.setattr(a2a_payment, "_is_local_agent", _local)
    return lambda db: a2a_payment._purse_refusal(db, AGENT, Decimal("5"), TARGET)


async def test_an_unreadable_organization_refuses_the_purse(purse):
    assert await purse(_Db(fails=True)) == "its organization's spend ceiling could not be read"   # base: None


async def test_control_the_organizations_ceiling_refuses_the_purse(purse):
    assert "spend ceiling" in (await purse(_Db(HARDENED_ORG)) or "")
    assert await purse(_Db(None)) is None
