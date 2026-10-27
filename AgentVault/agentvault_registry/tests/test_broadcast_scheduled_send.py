"""§SECFIX D6-304 (2026-10-16): a scheduled broadcast goes out as an immediate one does, and only once.

Measured on the wave-1 base (7140a4a6) through these same calls: POST /admin/broadcasts with send_email and a time to
come sent nothing yet (correct), but when the scheduler sent it, it pushed title, message and type only (no id, CTA,
acknowledgement or organization) and sent no email at all, while it stamped email_sent_at as if it had; a broadcast
sent at once with a schedule time already past was pushed a second time by the next scheduler cycle; and a row that
another cycle claimed after both had selected it was sent by both. Now the scheduler claims the row with one checked
UPDATE, pushes admin_broadcast.live_notice (the immediate send's own push) to the broadcast's audience, emails it once
with the audience rule wave 1 gave the email (its developer, its organization's active members, or everyone), and
stamps email_sent_at only when it emailed.

The POST runs through FastAPI on the real router and the scheduler's real cycle runs after it, both over one real
(SQLite) table, so a row sent twice or a mail to the wrong person shows as such. Only the database session, the
caller's identity, the socket push and the mail transport are supplied.
"""
from __future__ import annotations

import contextlib
import datetime as dt

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from agentvault_registry import models
from agentvault_registry.background_tasks import broadcast_scheduler as bs
from agentvault_registry.database import get_db
from agentvault_registry.routers import admin_broadcast as ab
from tests._sqlite_db import AsyncSessionShim, sqlite_db

NOW = dt.datetime.now(dt.timezone.utc)
ADMIN, MEMBER, OUTSIDER, LAPSED = 1, 2, 3, 4          # LAPSED: a membership of org-o that is no longer active
EVERYONE = sorted(f"{n}@example.org" for n in ("admin", "member", "outsider", "lapsed"))


def _sql_now():
    # SQLite has no NOW(); this one answers in the format SQLAlchemy stores a datetime in (UTC here), so the
    # scheduler's own `scheduled_for <= NOW()` compares like Postgres would.
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def _seed():
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationMember, models.AdminBroadcast,
                   models.DeveloperNotificationRead, models.BroadcastEmailFailed)
    raw = db.sync.get_bind().raw_connection()            # one connection (StaticPool): the function serves every session
    raw.driver_connection.create_function("NOW", 0, _sql_now)
    raw.close()
    s = db.sync
    db.devs = {}   # held here: the session's identity map keeps only weak references
    for i, name in ((ADMIN, "admin"), (MEMBER, "member"), (OUTSIDER, "outsider"), (LAPSED, "lapsed")):
        db.devs[i] = models.Developer(id=i, name=name, email=f"{name}@example.org", hashed_password="x",
                                      is_verified=True, is_admin=(i == ADMIN), created_at=NOW - dt.timedelta(days=10))
        s.add(db.devs[i])
    s.add(models.Organization(id="org-o", name="O", slug="o", owner_id=MEMBER))
    s.add(models.OrganizationMember(id="m1", organization_id="org-o", developer_id=MEMBER, is_active=True))
    s.add(models.OrganizationMember(id="m3", organization_id="org-o", developer_id=LAPSED, is_active=False))
    s.commit()
    return db


class _Emitter:
    """Records what reaches the ledger emitter (tests/test_doubles_assert_receipt.py: a double asserts receipt)."""

    def __init__(self):
        self.received: list = []

    async def emit(self, **kw):
        self.received.append(kw)
        return None


_EMITTER = _Emitter()


@pytest.fixture()
def world(monkeypatch):
    db = _seed()
    app = FastAPI()
    app.include_router(ab.router, prefix="/api/v1")
    admin = db.devs[ADMIN]

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    route = next(r for r in ab.router.routes if getattr(r, "path", "") == "/admin/broadcasts" and "POST" in r.methods)
    flag = next(d.call for d in route.dependant.dependencies if "require_admin_flag" in getattr(d.call, "__qualname__", ""))
    app.dependency_overrides[flag] = lambda: admin

    mails: list = []
    pushes: list = []

    async def _send(**kw):
        mails.extend(kw["recipients"])
        return True

    async def _push(message, exclude_user=None, audience=None):
        pushes.append((audience, message))

    async def _no_reach(*_a, **_k):
        return 0

    from agentvault_registry import email_utils
    from agentvault_registry.services import notification_catalog
    monkeypatch.setattr(email_utils, "send_themed_email", _send)
    monkeypatch.setattr(notification_catalog, "get_type", lambda _key: None)   # no preference read: every recipient
    monkeypatch.setattr(ab.ws_manager, "broadcast", _push)                      # the one socket manager both paths use
    monkeypatch.setattr(ab, "live_reach", _no_reach)
    _EMITTER.received.clear()
    monkeypatch.setattr(ab, "get_event_emitter", lambda: _EMITTER)

    session = {"db": db}

    @contextlib.asynccontextmanager
    async def _ctx():
        yield session["db"]

    monkeypatch.setattr(bs, "get_db_context", _ctx)

    async def post(body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/v1/admin/broadcasts", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    async def cycle():
        await bs.BroadcastScheduler()._cycle_once()

    def row(bid):
        db.sync.expire_all()
        return db.sync.execute(select(models.AdminBroadcast).where(models.AdminBroadcast.id == bid)).scalar_one()

    def time_passes(bid):
        db.sync.execute(update(models.AdminBroadcast).where(models.AdminBroadcast.id == bid)
                        .values(scheduled_for=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)))
        db.sync.commit()

    return {"db": db, "session": session, "post": post, "cycle": cycle, "row": row, "time_passes": time_passes,
            "mails": mails, "pushes": pushes}


def _later():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()


async def test_a_scheduled_broadcast_is_emailed_once_to_its_audience_when_it_goes_out(world):
    b = await world["post"]({"title": "t", "body": "b", "send_email": True, "target_org_id": "org-o",
                             "scheduled_for": _later(), "cta_url": "https://example.org/x", "cta_label": "Open",
                             "requires_ack": True})
    assert world["mails"] == [] and world["pushes"] == []          # not out yet

    world["time_passes"](b["id"])
    await world["cycle"]()
    assert sorted(world["mails"]) == ["member@example.org"]        # the organization's active member, nobody else
    assert len(world["pushes"]) == 1
    audience, message = world["pushes"][0]
    assert audience == "org_org-o"
    data = message["data"]
    assert data["broadcast_id"] == b["id"]
    assert (data["cta_url"], data["cta_label"], data["requires_ack"], data["target_org_id"]) == (
        "https://example.org/x", "Open", True, "org-o")
    r = world["row"](b["id"])
    assert r.scheduled_for is None and r.email_sent_at is not None

    await world["cycle"]()                                          # and never again
    assert sorted(world["mails"]) == ["member@example.org"] and len(world["pushes"]) == 1


async def test_control_an_untargeted_scheduled_broadcast_is_emailed_to_every_verified_developer(world):
    b = await world["post"]({"title": "t", "body": "b", "send_email": True, "scheduled_for": _later()})
    world["time_passes"](b["id"])
    await world["cycle"]()
    assert sorted(world["mails"]) == EVERYONE
    assert [a for a, _m in world["pushes"]] == [None]               # everyone's push


async def test_a_scheduled_broadcast_without_email_is_pushed_and_not_recorded_as_emailed(world):
    b = await world["post"]({"title": "t", "body": "b", "scheduled_for": _later()})
    world["time_passes"](b["id"])
    await world["cycle"]()
    assert world["mails"] == [] and len(world["pushes"]) == 1
    r = world["row"](b["id"])
    assert r.scheduled_for is None
    assert r.email_sent_at is None                                  # no email went out, and the record says so


async def test_a_broadcast_sent_now_with_a_past_schedule_is_not_sent_again_by_the_scheduler(world):
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
    b = await world["post"]({"title": "t", "body": "b", "scheduled_for": past})
    assert len(world["pushes"]) == 1                                # it went out at once
    sent = len(_EMITTER.received)
    assert _EMITTER.received, "the broadcast reported nothing to the ledger"
    await world["cycle"]()
    assert len(world["pushes"]) == 1
    assert len(_EMITTER.received) == sent, "the scheduler reported a broadcast that went out already"
    assert world["row"](b["id"]).scheduled_for is None


class _LosesTheRace(AsyncSessionShim):
    """A cycle whose claim comes second: another cycle that selected the same due row claims it just before."""

    async def execute(self, stmt, *a, **k):
        if "SET scheduled_for = NULL" in str(stmt):
            self.sync.execute(stmt, *a, **k)
            self.sync.commit()
        return self.sync.execute(stmt, *a, **k)


async def test_a_row_another_cycle_claimed_first_is_not_sent_again(world):
    b = await world["post"]({"title": "t", "body": "b", "send_email": True, "scheduled_for": _later()})
    world["time_passes"](b["id"])
    world["session"]["db"] = _LosesTheRace(world["db"].sync)
    await world["cycle"]()
    assert world["pushes"] == [] and world["mails"] == []


def test_both_sends_push_the_same_notice():
    b = models.AdminBroadcast(id=7, title="t", body="b", broadcast_type="warning", cta_url="u", cta_label="l",
                              requires_ack=True, target_org_id="org-o")
    assert ab.live_notice(b) == {"type": "notification", "data": {
        "broadcast_id": 7, "title": "t", "message": "b", "type": "warning", "cta_url": "u", "cta_label": "l",
        "requires_ack": True, "target_org_id": "org-o"}}
