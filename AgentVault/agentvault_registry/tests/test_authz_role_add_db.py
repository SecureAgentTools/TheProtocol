"""§MEMBERSHIP (2026-10-02, agentvault2-0f's finding): POST /agents/{did}/authz/roles grants ONE role and touches no
other grant. The control: the replacing PUT stamps the whole set with the call's one expiry (its documented time-box),
which is exactly what made "add governor" turn a time-limited role permanent.

Skipped unless MEMBERSHIP_TEST_DB names a throwaway database it may WIPE.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest

DB = os.environ.get("MEMBERSHIP_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

UTC = dt.timezone.utc


@pytest.fixture
async def session():
    from agentvault_registry.models import Base
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _setup(s):
    from agentvault_registry.models import Agent, Developer
    owner = Developer(name="owner", email="owner@test.local", hashed_password="x", is_verified=True)
    other = Developer(name="other", email="other@test.local", hashed_password="x", is_verified=True)
    s.add_all([owner, other])
    await s.flush()
    a = Agent(did=f"did:theprotocol:{uuid.uuid4()}", client_id=f"cid-{uuid.uuid4().hex[:12]}", hashed_client_secret="x",
              creator_developer_id=owner.id, status="active", enforcement_status="active")
    s.add(a)
    await s.flush()
    now = dt.datetime.now(UTC)
    for role, exp in (("trader", None), ("client", now + dt.timedelta(days=2)), ("staker", now - dt.timedelta(days=1))):
        await s.execute(text("INSERT INTO agent_role_grants (agent_did, grant_type, value, granted_by_dev_id, expires_at) "
                             "VALUES (:d, 'role', :r, :dev, :e)"), {"d": a.did, "r": role, "dev": owner.id, "e": exp})
    await s.commit()
    return owner, other, a


async def _grants(s, did):
    rows = (await s.execute(text("SELECT value, expires_at FROM agent_role_grants WHERE agent_did = :d AND "
                                 "grant_type = 'role' ORDER BY value"), {"d": did})).all()
    return {v: e for v, e in rows}


async def test_one_role_is_added_and_every_other_grant_keeps_its_expiry(session):
    from agentvault_registry.routers import agent_authz_api as api
    s = session
    owner, other, a = await _setup(s)
    did = a.did
    before = await _grants(s, did)
    out = await api.add_agent_role(did, api.RoleAdd(role="governor"), current=owner, db=s)
    assert out["changed"] is True and "governor" in out["roles"] and "gov.vote" in out["effective_permissions"]
    after = await _grants(s, did)
    assert after["governor"] is None, "permanent unless asked otherwise"
    assert after["client"] == before["client"] and after["trader"] is None and after["staker"] == before["staker"], \
        "no other grant was read into a new expiry"

    again = await api.add_agent_role(did, api.RoleAdd(role="client"), current=owner, db=s)
    assert again["changed"] is False and (await _grants(s, did))["client"] == before["client"], "an active grant stays"

    later = (dt.datetime.now(UTC) + dt.timedelta(days=10)).isoformat()
    revived = await api.add_agent_role(did, api.RoleAdd(role="staker", expires_at=later), current=owner, db=s)
    assert revived["changed"] is True and (await _grants(s, did))["staker"] > dt.datetime.now(UTC), "an expired one is renewed"


async def test_the_refusals(session):
    from agentvault_registry.routers import agent_authz_api as api
    s = session
    owner, other, a = await _setup(s)
    for kwargs, who, code in ((dict(role="emperor"), owner, 422), (dict(role="legacy-full"), owner, 403),
                              (dict(role="governor"), other, 403),
                              (dict(role="governor", expires_at="2020-01-01T00:00:00Z"), owner, 422)):
        with pytest.raises(HTTPException) as e:
            await api.add_agent_role(a.did, api.RoleAdd(**kwargs), current=who, db=s)
        assert e.value.status_code == code, (kwargs, e.value.status_code)
    with pytest.raises(HTTPException) as e:
        await api.add_agent_role("did:theprotocol:nobody", api.RoleAdd(role="governor"), current=owner, db=s)
    assert e.value.status_code == 404


async def test_control_the_replacing_put_stamps_the_whole_set(session):
    """Why the rail exists: the PUT with the read roles plus governor makes the time-limited `client` permanent."""
    from agentvault_registry.routers import agent_authz_api as api
    s = session
    owner, other, a = await _setup(s)
    did = a.did
    assert (await _grants(s, did))["client"] is not None
    await api._apply_roles(s, did, ["trader", "client", "governor"], owner.id, expires_at=None)
    await s.commit()
    assert (await _grants(s, did))["client"] is None, "the documented time-box of the PUT: one expiry for the set"
