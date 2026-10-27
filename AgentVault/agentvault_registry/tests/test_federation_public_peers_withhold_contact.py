"""§SECBATCH wave 3 (2026-10-16): the public peer routes leave out each peer administrator's contact e-mail; the admin
federation routes and the registering developer's own registrations keep it.

Measured on the base (1032dca8): GET /api/v1/federation/peers/ (no credential) listed every active peer with its
`admin_contact_email`, and GET /api/v1/federation/peers/{peer_id} answered it for any active peer: both serialized the
admin read model, PeerRegistryRead.

Why no test caught it: no test read the public routes; the MCP tester's listFederationPeers and getFederationPeerByID
contracts asked only that an answer came back.

The routes run through FastAPI on the real routers (federation_peers, and admin_federation for the admin list) over real
(SQLite) rows; only the session and, for the authenticated routes, the developer are supplied (the admin flag gate runs).
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.routers import admin_federation, federation_peers
from tests._sqlite_db import sqlite_db

ADMIN, OWNER = 1, 2
CONTACT = "peer-admin@example.org"
T0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)


@pytest.fixture()
def call():
    db = sqlite_db(models.Developer, models.PeerRegistry)
    s = db.sync
    devs = {ADMIN: models.Developer(id=ADMIN, name="admin", email="a@example.org", hashed_password="x", is_admin=True),
            OWNER: models.Developer(id=OWNER, name="owner", email="o@example.org", hashed_password="x")}
    s.add_all(devs.values())
    s.add(models.PeerRegistry(id=10, owner_developer_id=OWNER, name="peer-one", base_url="https://peer-one.example",
                              admin_contact_email=CONTACT, status="ACTIVE", discovery_auth_info={"type": "api_key"},
                              registered_at=T0))
    s.commit()

    app = FastAPI()
    app.include_router(federation_peers.router, prefix="/api/v1")
    app.include_router(admin_federation.router, prefix="/api/v1")
    who = {}

    async def _db():
        yield db

    async def _developer():
        if who.get("dev") is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Not authenticated")
        return devs[who["dev"]]

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = _developer

    async def _call(path, dev=None):
        who.clear()
        who["dev"] = dev
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.get(path)

    return _call


async def test_the_public_list_leaves_out_the_contact(call):
    r = await call("/api/v1/federation/peers/")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [p["name"] for p in items] == ["peer-one"]
    assert "admin_contact_email" not in items[0], items[0]
    assert CONTACT not in r.text
    assert items[0]["base_url"] == "https://peer-one.example" and items[0]["status"] == "ACTIVE"


async def test_the_public_detail_leaves_out_the_contact(call):
    r = await call("/api/v1/federation/peers/10")
    assert r.status_code == 200, r.text
    assert "admin_contact_email" not in r.json() and CONTACT not in r.text
    assert r.json()["name"] == "peer-one"


async def test_the_admin_list_and_the_owners_registrations_keep_it(call):
    r = await call("/api/v1/admin/federation/peers/all", dev=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["admin_contact_email"] == CONTACT
    r = await call("/api/v1/federation/peers/my/registrations", dev=OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["admin_contact_email"] == CONTACT
    assert (await call("/api/v1/admin/federation/peers/all", dev=OWNER)).status_code == 403   # not an admin
