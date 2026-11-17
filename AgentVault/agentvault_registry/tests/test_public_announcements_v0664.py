"""V0664 (order gwo_1b3e2cc74c1afec6c6cedc3d, his yes seq 3638): announcements an admin marks public, readable by visitors.

A broadcast carries a `public` mark (column is_public, migration 0227, default FALSE). `GET /api/v1/public/announcements`
(no sign-in) serves ONLY the broadcasts an admin marked public that are active, already sent and addressed to everyone, and
only the fields a visitor needs: no author, no recipient counts, no mail flag, no organization or developer id. A broadcast
addressed to an organization or one developer can never be public (refused at the mark, and left out by the read as well, so a
row that got there by another path still leaks nothing). The mark is local: the copy a peer registry makes of a broadcast
(copy_content) never carries it, so no peer's copy of an announcement is public.

The route runs through FastAPI on the real router over a real (SQLite) table, as test_broadcast_audience_reads does.
RED on v0663/cut b7ca684e9: no column, no route, no rule, no field.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers import admin_broadcast as ab
from tests._sqlite_db import sqlite_db

NOW = dt.datetime.now(dt.timezone.utc)
SAFE = {"id", "title", "body", "broadcast_type", "created_at", "cta_url", "cta_label"}
REPO = pathlib.Path(__file__).resolve().parents[1]


def _world():
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationMember, models.AdminBroadcast,
                   models.DeveloperNotificationRead)
    s = db.sync
    db.admin = models.Developer(id=1, name="admin", email="admin@example.org", hashed_password="x", is_verified=True,
                                is_admin=True, created_at=NOW - dt.timedelta(days=10))
    s.add(db.admin)
    s.add(models.Organization(id="org-o", name="O", slug="o", owner_id=1))
    rows = {
        "public_all": {"is_public": True, "cta_url": "https://example.org/go", "cta_label": "Read"},
        "public_old": {"is_public": True, "created_at": NOW - dt.timedelta(days=3)},
        "unmarked": {},
        "public_org": {"is_public": True, "target_org_id": "org-o"},
        "public_note": {"is_public": True, "target_developer_id": 1},
        "public_later": {"is_public": True, "scheduled_for": NOW + dt.timedelta(days=1)},
        "public_retracted": {"is_public": True, "is_active": False},
    }
    for title, extra in rows.items():
        s.add(models.AdminBroadcast(title=title, body="the body", created_by=1, send_email=True, requires_ack=True,
                                    source_frame="eu", idempotency_key="k-" + title, **extra))
    s.commit()
    return db


@pytest.fixture()
def visitor():
    db = _world()
    app = FastAPI()
    app.include_router(ab.router, prefix="/api/v1")

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db     # no identity override: this caller has none

    async def get(path="/api/v1/public/announcements"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.get(path)

    return get


async def test_a_visitor_reads_exactly_the_public_untargeted_sent_active_ones_newest_first(visitor):
    r = await visitor()
    assert r.status_code == 200, r.text
    assert [b["title"] for b in r.json()] == ["public_all", "public_old"]


async def test_the_answer_holds_only_the_fields_a_visitor_needs(visitor):
    rows = (await visitor()).json()
    assert rows and all(set(b) == SAFE for b in rows)
    assert rows[0]["cta_url"] == "https://example.org/go" and rows[0]["cta_label"] == "Read"


async def test_the_page_size_is_bounded(visitor):
    assert (await visitor("/api/v1/public/announcements?limit=51")).status_code == 422
    assert (await visitor("/api/v1/public/announcements?limit=1")).json()[0]["title"] == "public_all"


def test_the_member_routes_still_need_a_sign_in():
    src = (pathlib.Path(ab.__file__)).read_text()
    block = src[src.index('"/community/announcements"'):src.index("async def _send_broadcast_email")]
    assert "get_current_developer" in block


@pytest.mark.parametrize("kw, word", [
    ({"target_org_id": "org-1"}, "everyone"),
    ({"target_developer_id": 9}, "everyone"),
])
def test_a_targeted_broadcast_cannot_be_marked_public(kw, word):
    why = ab.public_refusal(public=True, target_org_id=kw.get("target_org_id"),
                            target_developer_id=kw.get("target_developer_id"))
    assert why and word in why


def test_nothing_else_is_refused_by_the_public_rule():
    assert ab.public_refusal(public=True, target_org_id=None, target_developer_id=None) is None
    assert ab.public_refusal(public=False, target_org_id="org-1", target_developer_id=None) is None


def test_the_mark_defaults_to_off_everywhere():
    assert ab.BroadcastCreate(title="t", body="b").public is False
    assert ab.BroadcastUpdate().public is None
    assert models.AdminBroadcast.__table__.c.is_public.server_default is not None
    assert str(models.AdminBroadcast.__table__.c.is_public.server_default.arg).lower() in ("false", "0")
    assert ab.BroadcastOut.model_fields["public"].default is False


def test_the_mark_is_not_copied_to_a_peer():
    b = models.AdminBroadcast(title="t", body="b", created_by=1, is_public=True)
    assert "public" not in ab.copy_content(b) and "is_public" not in ab.copy_content(b)
    assert "public" not in ab.edit_content(b) and "is_public" not in ab.edit_content(b)


def test_the_migration_adds_the_column_off_on_the_current_head():
    src = (REPO / "alembic" / "versions" / "0227_broadcast_public.py").read_text()
    assert re.search(r'revision\s*=\s*"0227_broadcast_public"', src)
    assert re.search(r'down_revision\s*=\s*"0226_chat_outbox_drop"', src)    # re-pointed at the V0664 cut (was 0225)
    assert "is_public" in src and "server_default" in src and "false" in src.lower()
