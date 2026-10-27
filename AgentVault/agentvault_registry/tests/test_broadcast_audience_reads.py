"""§SECFIX D6-212 / D6-305 (2026-10-16): every developer read of a broadcast, and its email, follows ONE audience rule.

Measured on the base (14520b9f) through these same requests: GET /community/announcements listed every active broadcast
to every signed-in developer (another developer's direct notice, another organization's broadcast, one scheduled for
later); GET /notifications/{id} returned another organization's broadcast; an organization's broadcast with send_email
was emailed to every verified developer of the registry; and a registry that copies broadcasts from its ledger copied an
organization's broadcast for ALL of its own developers. The rule is admin_broadcast.visible_to (audience_clause in
SQL): a direct notice only its developer, an organization's broadcast only that organization's ACTIVE members,
anything else everyone, and nothing before it is sent.

The routes run through FastAPI on the real router over a real (SQLite) table, so a WHERE clause that keeps another
person's row is seen as that row in the answer. Only the database session and the caller's identity are supplied.
"""
from __future__ import annotations

import contextlib
import datetime as dt

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.routers import admin_broadcast as ab
from tests._sqlite_db import sqlite_db

NOW = dt.datetime.now(dt.timezone.utc)
ADMIN, MEMBER, OUTSIDER, LAPSED = 1, 2, 3, 4          # LAPSED: a membership of org-o that is no longer active


def _seed():
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationMember, models.AdminBroadcast,
                   models.DeveloperNotificationRead)
    s = db.sync
    db.devs = {}   # held here: the session's identity map keeps only weak references
    for i, name in ((ADMIN, "admin"), (MEMBER, "member"), (OUTSIDER, "outsider"), (LAPSED, "lapsed")):
        db.devs[i] = models.Developer(id=i, name=name, email=f"{name}@example.org", hashed_password="x",
                                      is_verified=True, is_admin=(i == ADMIN), created_at=NOW - dt.timedelta(days=10))
        s.add(db.devs[i])
    s.add(models.Organization(id="org-o", name="O", slug="o", owner_id=MEMBER))
    s.add(models.Organization(id="org-p", name="P", slug="p", owner_id=OUTSIDER))
    s.add(models.OrganizationMember(id="m1", organization_id="org-o", developer_id=MEMBER, is_active=True))
    s.add(models.OrganizationMember(id="m2", organization_id="org-p", developer_id=OUTSIDER, is_active=True))
    s.add(models.OrganizationMember(id="m3", organization_id="org-o", developer_id=LAPSED, is_active=False))
    rows = {
        "all": {},
        "org_o": {"target_org_id": "org-o"},
        "org_p": {"target_org_id": "org-p"},
        "note_member": {"target_developer_id": MEMBER},
        "note_outsider": {"target_developer_id": OUTSIDER},
        "later": {"scheduled_for": NOW + dt.timedelta(days=1)},
        "retracted": {"is_active": False},
    }
    ids = {}
    for title, extra in rows.items():
        b = models.AdminBroadcast(title=title, body="b", created_by=ADMIN, **extra)
        s.add(b)
        s.flush()
        ids[title] = b.id
    s.commit()
    return db, ids


@pytest.fixture()
def world():
    db, ids = _seed()
    app = FastAPI()
    app.include_router(ab.router, prefix="/api/v1")
    caller = {"id": MEMBER}

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = lambda: db.devs[caller["id"]]

    async def get(path, as_dev):
        caller["id"] = as_dev
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.get(path)

    return app, db, ids, get


def _titles(resp):
    assert resp.status_code == 200, resp.text
    return {b["title"] for b in resp.json()}


@pytest.mark.parametrize("dev, expected", [
    (MEMBER, {"all", "org_o", "note_member"}),
    (OUTSIDER, {"all", "org_p", "note_outsider"}),
    (LAPSED, {"all"}),
])
async def test_the_community_page_lists_only_what_the_caller_may_see(world, dev, expected):
    _app, _db, _ids, get = world
    assert _titles(await get("/api/v1/community/announcements", dev)) == expected


@pytest.mark.parametrize("dev, expected", [
    (MEMBER, {"all", "org_o", "note_member"}),
    (OUTSIDER, {"all", "org_p", "note_outsider"}),
    (LAPSED, {"all"}),
])
async def test_the_bell_asks_the_same_rule(world, dev, expected):
    _app, _db, _ids, get = world
    assert _titles(await get("/api/v1/notifications/unread", dev)) == expected


@pytest.mark.parametrize("dev, title, status", [
    (MEMBER, "org_o", 200),          # control: the organization's member reads its broadcast
    (OUTSIDER, "org_o", 404),        # the defect: another organization's broadcast, read by id
    (LAPSED, "org_o", 404),          # a membership that is no longer active reads nothing of it
    (MEMBER, "org_p", 404),
    (OUTSIDER, "all", 200),          # control: an untargeted broadcast stays everyone's
    (MEMBER, "note_outsider", 404),  # another developer's direct notice, as before
    (MEMBER, "later", 404),          # not sent yet
    (MEMBER, "retracted", 404),
])
async def test_one_broadcast_by_id_answers_404_to_whoever_may_not_see_it(world, dev, title, status):
    _app, _db, ids, get = world
    r = await get(f"/api/v1/notifications/{ids[title]}", dev)
    assert r.status_code == status, r.text
    if status == 404:
        assert r.json()["detail"] == "Broadcast not found"   # the same answer as an id that does not exist


async def test_marking_another_organizations_broadcast_read_is_refused_like_a_missing_one(world, monkeypatch):
    app, db, ids, _get = world

    async def _read(dev, title):
        app.dependency_overrides[security.get_current_developer] = lambda: db.devs[dev]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post(f"/api/v1/notifications/{ids[title]}/read")

    async def _no_push(*a, **k):
        return None

    monkeypatch.setattr(ab.ws_manager, "broadcast", _no_push)
    assert (await _read(OUTSIDER, "org_o")).status_code == 404
    assert (await _read(MEMBER, "org_o")).status_code == 204       # control: its member may


class _Emitter:
    """Records what reaches the emitter, so a broadcast that stops reporting itself to the ledger is noticed
    (tests/test_doubles_assert_receipt.py: a double must assert receipt)."""

    def __init__(self):
        self.received: list = []

    async def emit(self, **kw):
        self.received.append(kw)
        return None


@pytest.fixture()
def sent_mail(world, monkeypatch):
    """POST /admin/broadcasts through the router; the email's recipients are recorded instead of sent."""
    app, db, _ids, _get = world
    admin = db.devs[ADMIN]
    route = next(r for r in ab.router.routes if getattr(r, "path", "") == "/admin/broadcasts" and "POST" in r.methods)
    flag = next(d.call for d in route.dependant.dependencies if "require_admin_flag" in getattr(d.call, "__qualname__", ""))
    app.dependency_overrides[flag] = lambda: admin
    recipients: list = []

    async def _send(**kw):
        recipients.extend(kw["recipients"])
        return True

    async def _no_push(*a, **k):
        return None

    async def _no_reach(*a, **k):
        return 0

    from agentvault_registry import email_utils
    from agentvault_registry.services import notification_catalog
    monkeypatch.setattr(email_utils, "send_themed_email", _send)
    monkeypatch.setattr(notification_catalog, "get_type", lambda _key: None)   # no preference read: every recipient
    monkeypatch.setattr(ab.ws_manager, "broadcast", _no_push)
    monkeypatch.setattr(ab, "live_reach", _no_reach)
    emitter = _Emitter()
    monkeypatch.setattr(ab, "get_event_emitter", lambda: emitter)

    async def post(body):
        recipients.clear()
        emitter.received.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/v1/admin/broadcasts", json=body)
        assert r.status_code == 201, r.text
        assert emitter.received, "the broadcast reported nothing to the ledger"
        return sorted(recipients)

    return post


async def test_an_organizations_broadcast_is_emailed_to_its_active_members_only(sent_mail):
    assert await sent_mail({"title": "t", "body": "b", "send_email": True, "target_org_id": "org-o"}) == [
        "member@example.org"]


async def test_control_an_untargeted_broadcast_is_emailed_to_every_verified_developer(sent_mail):
    assert await sent_mail({"title": "t", "body": "b", "send_email": True}) == sorted(
        f"{n}@example.org" for n in ("admin", "member", "outsider", "lapsed"))


def test_the_rule_and_its_sql_twin_agree():
    org = type("B", (), {"target_developer_id": None, "target_org_id": "org-o"})()
    note = type("B", (), {"target_developer_id": 7, "target_org_id": None})()
    assert ab.visible_to(org, 1, ["org-o"]) and not ab.visible_to(org, 1) and not ab.visible_to(org, 1, ["org-p"])
    assert ab.visible_to(note, 7) and not ab.visible_to(note, 8, ["org-o"])
    from sqlalchemy.dialects import postgresql
    sql = str(ab.audience_clause(9, ["org-o"]).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "target_developer_id IS NULL" in sql and "target_org_id IS NULL" in sql and "'org-o'" in sql


async def test_a_copy_of_an_organizations_broadcast_is_never_made_on_another_registry(monkeypatch):
    """A registry reading the sender's ledger copied every AdminBroadcastSent for ALL its developers; an organization's
    members are developers of the sending registry, so its broadcast is not copied (a direct notice is not either)."""
    from agentvault_registry.background_tasks import reactor_admin_broadcast_received as r
    db = sqlite_db(models.Developer, models.AdminBroadcast)
    db.sync.add(models.Developer(id=1, name="a", email="a@example.org", hashed_password="x", is_admin=True))
    db.sync.commit()

    @contextlib.asynccontextmanager
    async def _ctx():
        yield db

    monkeypatch.setattr(r, "get_db_context", _ctx)
    event = {"source_frame": "peer-frame", "broadcast_id": 5, "title": "for org members", "broadcast_type": "info"}
    assert await r._materialize_received_broadcast({**event, "target_org_id": "org-o"}) is None
    assert db.sync.query(models.AdminBroadcast).count() == 0
    assert await r._materialize_received_broadcast(event) is not None          # control: an untargeted one is copied
    assert db.sync.query(models.AdminBroadcast).count() == 1
