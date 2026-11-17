"""V0664 (order gwo_efdd53bd198423a5ec2b742d): the admins' delivery panel can act on one stuck outbox row.

  rows      GET /api/v1/admin/chat/federation/delivery/rows?peer=  a peer's undelivered, undropped rows, oldest first,
            each with its state (given_up, backing_off, held behind an earlier row of its thread, due now) and what an
            admin may do with it; never the payload (the message's text stays out of the panel)
  retry     POST .../rows/{row_id}/retry   the row is tried at once: its next attempt now; a given-up row gets ONE more
            try (attempts MAX_ATTEMPTS - 1: a further failure gives up again); refused while it is held (retry the earlier
            row) or due now (the drain may be sending it)
  drop      POST .../rows/{row_id}/drop {reason}   the row stops (dropped_at, dropped_by, drop_reason, migration
            0226_chat_outbox_drop; an audit row with the reason); a dropped row is never due and never holds its thread;
            the message itself is never deleted, here or on the outbox (an UPDATE, no DELETE); refused while due now
  both      behind admin_federation; a guarded UPDATE (not delivered, not dropped, given up or backing off) so neither
            races the drain's own write; the drain is woken after the commit
Red on v0663/cut b7ca684e9: the routes, the statements and the columns do not exist.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import pathlib

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from agentvault_registry.services import chat_delivery as cd

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
NOW = dt.datetime(2026, 11, 14, 11, 0, tzinfo=dt.timezone.utc)
ASIA = "https://asia.example.org"
MAX = 12


def _r(rid, *, conv="c1", seq=1, attempts=1, next_in=60, delivered=None, dropped=None, created=0, event=None):
    return {"id": rid, "conversation_id": conv, "seq": seq, "event_id": event, "peer_base_url": ASIA,
            "attempts": attempts, "next_attempt_at": NOW + dt.timedelta(seconds=next_in),
            "last_error": "HTTP 503: busy", "created_at": NOW - dt.timedelta(hours=1, seconds=-created),
            "delivered_at": delivered, "dropped_at": dropped, "dropped_by": None, "drop_reason": None}


def run(c):
    return asyncio.run(c)


def sql(stmt) -> str:
    return " ".join(str(stmt.compile(dialect=postgresql.dialect())).lower().split())


# --- the columns ---------------------------------------------------------------------------------------------------

def test_a_drop_has_its_own_columns_and_migration():
    from agentvault_registry.models import ChatFederationOutbox as O
    cols = O.__table__.columns
    assert {"dropped_at", "dropped_by", "drop_reason"} <= set(cols.keys())
    assert all(cols[c].nullable for c in ("dropped_at", "dropped_by", "drop_reason"))
    mig = (SRC.parents[1] / "alembic" / "versions" / "0226_chat_outbox_drop.py").read_text()
    assert 'revision = "0226_chat_outbox_drop"' in mig and 'down_revision = "0225_code_changes"' in mig


# --- states --------------------------------------------------------------------------------------------------------

def test_each_row_says_its_state_and_what_an_admin_may_do():
    given = _r("g", attempts=MAX, next_in=-3600)
    backing = _r("b", conv="c2", attempts=3, next_in=300)
    due = _r("d", conv="c3", attempts=2, next_in=-5)
    states = {r["id"]: r for r in cd.row_states([given, backing, due], now=NOW)}
    assert (states["g"]["state"], states["g"]["can_retry"], states["g"]["can_drop"]) == ("given_up", True, True)
    assert (states["b"]["state"], states["b"]["can_retry"], states["b"]["can_drop"]) == ("backing_off", True, True)
    assert (states["d"]["state"], states["d"]["can_retry"], states["d"]["can_drop"]) == ("due", False, False)


def test_a_row_behind_a_backing_off_row_of_its_thread_is_held_and_names_it():
    head = _r("h", seq=1, attempts=4, next_in=600)
    later = _r("l", seq=2, attempts=0, next_in=-60, created=5)
    later_waiting = _r("w", seq=3, attempts=1, next_in=900, created=9)
    states = {r["id"]: r for r in cd.row_states([head, later, later_waiting], now=NOW)}
    assert states["h"]["state"] == "backing_off" and states["h"]["held_by"] is None
    assert (states["l"]["state"], states["l"]["held_by"], states["l"]["can_retry"]) == ("held", "h", False)
    assert states["l"]["can_drop"] is False, "due by its own clock: the drain may hold it; drop the head first"
    assert (states["w"]["state"], states["w"]["can_retry"], states["w"]["can_drop"]) == ("held", False, True)


def test_a_given_up_head_holds_nothing():
    head = _r("h", seq=1, attempts=MAX, next_in=-3600)
    later = _r("l", seq=2, attempts=0, next_in=-60, created=5)
    states = {r["id"]: r for r in cd.row_states([head, later], now=NOW)}
    assert states["l"]["state"] == "due" and states["l"]["held_by"] is None


# --- the statements ------------------------------------------------------------------------------------------------

def test_the_rows_read_never_selects_the_payload_and_skips_delivered_and_dropped():
    s = sql(cd.rows_stmt(ASIA, 50))
    assert s.startswith("select") and "payload" not in s
    assert "delivered_at is null" in s and "dropped_at is null" in s and "order by" in s


def test_retry_is_one_guarded_update_of_the_outbox():
    s = sql(cd.retry_stmt("r1"))
    assert s.startswith("update chat_federation_outbox set")
    assert "next_attempt_at=now()" in s.replace(" ", "") and "least(" in s
    assert "delivered_at is null" in s and "dropped_at is null" in s
    assert "attempts >=" in s and "next_attempt_at > now()" in s, "given up or backing off: never a row the drain holds"


def test_drop_is_one_guarded_update_recording_who_and_why_and_deletes_nothing():
    s = sql(cd.drop_stmt("r1", actor_id=7, reason="peer retired"))
    assert s.startswith("update chat_federation_outbox set")
    for col in ("dropped_at", "dropped_by", "drop_reason"):
        assert col in s
    assert "delivered_at is null" in s and "dropped_at is null" in s and "next_attempt_at > now()" in s
    src = (SRC / "services" / "chat_delivery.py").read_text().lower()
    assert "delete from" not in src and ".delete(" not in src, "the panel deletes nothing: not a message, not a row"


def test_the_drain_neither_sends_a_dropped_row_nor_lets_it_hold_its_thread():
    from sqlalchemy import select
    from agentvault_registry.models import ChatFederationOutbox
    from agentvault_registry.services import chat_federation as fed
    s = sql(select(ChatFederationOutbox.id).where(*fed._due_conditions()))
    assert s.count("dropped_at is null") == 2, "the row itself, and the earlier row that would hold it"


def test_the_panel_counts_no_dropped_row_as_waiting():
    s = sql(cd.delivery_stmt())
    # session-watch, room seq 3636: all six waiting figures (waiting, oldest, attempts, given up, next attempt, latest
    # error) leave a dropped row out, and the dropped ones are counted apart
    assert s.count("delivered_at is null and dropped_at is null") == 6 and "dropped_at is not null" in s
    out = cd.delivery_view([{"peer_base_url": ASIA, "waiting": 0, "oldest_waiting_at": None, "max_attempts": 0,
                             "given_up": 0, "next_attempt_at": None, "last_error": None, "last_delivered_at": None,
                             "dropped": 2}], {ASIA: "asia"}, now=NOW)
    assert out[0]["verdict"] == "clear" and out[0]["dropped"] == 2


def test_the_status_counts_skip_dropped_rows():
    src = (SRC / "routers" / "chat.py").read_text()
    i = src.index("async def federation_status(")
    body = src[i:src.index("\n\n\n", i)]
    assert body.count("dropped_at IS NULL") == 2


# --- the flow ------------------------------------------------------------------------------------------------------

class _Res:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class Db:
    """Records the statements; an UPDATE answers the rowcount it is told."""

    def __init__(self, rowcount=1):
        self.rowcount, self.stmts, self.commits = rowcount, [], 0

    async def execute(self, stmt, params=None):
        self.stmts.append(sql(stmt) if hasattr(stmt, "compile") else str(stmt))
        return _Res(self.rowcount)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def world(monkeypatch):
    rows, audits, wakes = {}, [], []

    async def read_row(db, rid):
        return dict(rows[rid]) if rid in rows else None

    async def thread_rows(db, row):
        return [dict(r) for r in rows.values() if r["conversation_id"] == row["conversation_id"]]

    async def audit(db, **kw):
        audits.append(kw)

    async def wake():
        wakes.append(True)
    monkeypatch.setattr(cd, "read_row", read_row)
    monkeypatch.setattr(cd, "thread_rows", thread_rows)
    monkeypatch.setattr(cd, "audit", audit)
    monkeypatch.setattr(cd, "wake", wake)
    monkeypatch.setattr(cd, "db_now", lambda: NOW)
    return rows, audits, wakes


def _refused(coro, status, code):
    with pytest.raises(cd.DeliveryRefusal) as e:
        run(coro)
    assert (e.value.status, e.value.code) == (status, code), (e.value.status, e.value.code, e.value.sentence)


def test_retry_moves_one_row_records_it_and_wakes_the_drain(world):
    rows, audits, wakes = world
    rows["g"] = _r("g", attempts=MAX, next_in=-3600)
    db = Db()
    out = run(cd.retry_row(db, "g", actor_id=7))
    assert out["ok"] is True and db.stmts[0].startswith("update chat_federation_outbox") and db.commits == 1
    assert audits[0]["action"] == "chat_federation.outbox_retry" and audits[0]["target_id"] == "g"
    assert audits[0]["actor_id"] == "7" and audits[0]["details"]["attempts_before"] == MAX
    assert wakes == [True]


def test_drop_records_the_reason_and_moves_nothing_else(world):
    rows, audits, wakes = world
    rows["g"] = _r("g", attempts=MAX, next_in=-3600)
    db = Db()
    out = run(cd.drop_row(db, "g", actor_id=7, reason="  the peer left the federation  "))
    assert out["ok"] is True and len(db.stmts) == 1 and db.commits == 1
    assert audits[0]["action"] == "chat_federation.outbox_drop" and audits[0]["severity"] == "warning"
    assert audits[0]["details"]["reason"] == "the peer left the federation"
    assert audits[0]["details"]["conversation_id"] == "c1" and wakes == [True], "a drop may release its thread"


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
def test_a_drop_needs_a_reason(world, reason):
    rows, audits, _ = world
    rows["g"] = _r("g", attempts=MAX, next_in=-3600)
    db = Db()
    _refused(cd.drop_row(db, "g", actor_id=7, reason=reason), 422, "reason")
    assert db.stmts == [] and audits == []


@pytest.mark.parametrize("row,code", [
    (dict(delivered=NOW), "delivered"),
    (dict(dropped=NOW), "dropped"),
    (dict(attempts=2, next_in=-5), "due_now"),
])
def test_retry_and_drop_refuse_a_row_that_is_not_stuck(world, row, code):
    rows, audits, _ = world
    rows["x"] = _r("x", **row)
    for call in (cd.retry_row(Db(), "x", actor_id=7), cd.drop_row(Db(), "x", actor_id=7, reason="r")):
        _refused(call, 409, code)
    assert audits == []


def test_retry_of_a_held_row_names_the_row_to_retry(world):
    rows, _, _ = world
    rows["h"] = _r("h", seq=1, attempts=4, next_in=600)
    rows["l"] = _r("l", seq=2, attempts=1, next_in=900, created=5)
    _refused(cd.retry_row(Db(), "l", actor_id=7), 409, "held")
    assert run(cd.drop_row(Db(), "l", actor_id=7, reason="superseded"))["ok"] is True


def test_an_unknown_row_is_a_404_and_a_lost_race_moves_nothing(world):
    rows, audits, wakes = world
    _refused(cd.retry_row(Db(), "nope", actor_id=7), 404, "not_found")
    rows["g"] = _r("g", attempts=MAX, next_in=-3600)
    db = Db(rowcount=0)
    _refused(cd.drop_row(db, "g", actor_id=7, reason="r"), 409, "changed")
    assert db.commits == 0 and audits == [] and wakes == []


# --- the routes ----------------------------------------------------------------------------------------------------

def _app(monkeypatch, world):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import chat_delivery_admin as route

    class Admin:
        id = 7
    app = FastAPI()
    app.include_router(route.router)

    async def get_db():
        yield Db()
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[route._ADMIN] = lambda: Admin()
    return app


def _call(app, method, path, body=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.request(method, path, json=body)
    return run(go())


def test_the_routes_list_retry_and_drop(monkeypatch, world):
    rows, audits, _ = world
    rows["g"] = _r("g", attempts=MAX, next_in=-3600)

    async def peer_rows(db, peer, limit):
        return [dict(r) for r in rows.values()]
    monkeypatch.setattr(cd, "peer_rows", peer_rows)
    app = _app(monkeypatch, world)
    r = _call(app, "GET", f"/api/v1/admin/chat/federation/delivery/rows?peer={ASIA}")
    assert r.status_code == 200 and r.json()["rows"][0]["state"] == "given_up" and "payload" not in r.json()["rows"][0]
    assert _call(app, "POST", "/api/v1/admin/chat/federation/delivery/rows/g/retry").json()["ok"] is True
    r = _call(app, "POST", "/api/v1/admin/chat/federation/delivery/rows/g/drop", {"reason": ""})
    assert r.status_code == 422
    r = _call(app, "POST", "/api/v1/admin/chat/federation/delivery/rows/nope/drop", {"reason": "gone"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_every_delivery_route_is_behind_the_federation_admin_flag():
    src = (SRC / "routers" / "chat_delivery_admin.py").read_text()
    assert '_ADMIN = require_admin_flag("admin_federation")' in src
    assert src.count("Security(_ADMIN)") == 4, "the panel, the rows, retry and drop"
