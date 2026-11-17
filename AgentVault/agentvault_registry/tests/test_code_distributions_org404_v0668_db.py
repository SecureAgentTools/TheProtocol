"""The listing of an organization's release lines through its REAL route on a REAL Postgres (order gwo_a0f717a778ac12962f88773f):
GET /api/v1/organizations/{org_id}/code-distributions answers 404 no_organization for an organization that does not exist, for the
platform admin as for anyone (V0667's pair proof saw 200 [] for the admin); an existing organization lists for its member and for
the admin. Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE. Skipped, never silently passed.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

DB = os.environ.get("CODE_DISTRIBUTIONS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


@pytest.fixture
async def world(monkeypatch):
    from agentvault_registry.models import Base, CodeDistribution, Developer, Organization, OrganizationMember
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    monkeypatch.delenv("REQUIRE_ADMIN_2FA", raising=False)
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        devs = {}
        for key, admin in (("admin", True), ("member", False), ("outsider", False)):
            d = Developer(name=f"{key}-{uuid.uuid4().hex[:6]}", email=f"{key}{uuid.uuid4().hex[:6]}@test.local", hashed_password="x",
                          is_verified=True, is_admin=admin)
            s.add(d)
            devs[key] = d
        await s.flush()
        org = Organization(id=f"org-{uuid.uuid4().hex[:8]}", name="Lyceum Labs", slug=f"lyceum-{uuid.uuid4().hex[:6]}",
                           owner_id=devs["member"].id)
        s.add(org)
        await s.flush()
        s.add(OrganizationMember(id=uuid.uuid4().hex, organization_id=org.id, developer_id=devs["member"].id, role="owner", is_active=True))
        s.add(CodeDistribution(id=uuid.uuid4().hex, organization_id=org.id, slug="lyceum", title="Lyceum", base_release="V0667",
                               open_paths=["agentvault_registry/src/agentvault_registry/static/"], created_by_developer_id=devs["member"].id))
        await s.commit()
    yield {"maker": maker, "devs": devs, "org": org.id}
    await engine.dispose()


async def _list(world, who, org_id):
    from agentvault_registry.routers import code_distributions as R
    async with world["maker"]() as s:
        resp = await R.list_for_org(org_id, developer=world["devs"][who], db=s)
    if isinstance(resp, dict):
        return 200, resp
    return resp.status_code, json.loads(resp.body or b"{}")


async def test_a_missing_organization_is_404_through_the_route_for_the_admin_too(world):
    missing = f"org-{uuid.uuid4().hex[:8]}"
    for who in ("admin", "member", "outsider"):
        st, body = await _list(world, who, missing)
        assert st == 404 and body.get("code") == "no_organization", (who, st, body)


async def test_an_existing_organization_still_lists_for_its_member_and_the_admin(world):
    for who in ("member", "admin"):
        st, body = await _list(world, who, world["org"])
        assert st == 200 and [d["slug"] for d in body["items"]] == ["lyceum"], (who, st, body)
    st, body = await _list(world, "outsider", world["org"])
    assert st == 404 and body.get("code") == "no_organization"
