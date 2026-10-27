"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): a federated broadcast retracted before its copy arrives stays retracted.

Sent and Retracted are separate reactors with separate lags, so the retract of a broadcast taken back seconds after it
was sent can reach a receiving registry before the copy does. The retract's UPDATE found nothing and said nothing, and the
copy materialized afterwards ACTIVE for good: broadcast 1095 on the sandbox's alpha operator was sent 17:10:25.6Z and
retracted 17:10:39.9Z, and the beta operator materialized it at 17:10:53.2Z; 24 such "phase6 sweep" copies lived on the
two sandbox operators (agentvault2-66's count). Now the retract holds the copy's place retracted, and the copy that meets
it stays retracted with no live toast. The tests drive the reactor's functions against a fake table keyed like the real
UNIQUE (source_frame, idempotency_key). A retract of an organization's broadcast or a direct notice (never copied)
holds no place, and a place no copy met within a week is pruned, so the rows stay bounded (agentvault2-d6's ask).
Five of these tests fail on V0638's modules (the control); the other four pin what must not change.

An edit loses the same race (agentvault2-66's finding, 2026-10-24: 29 "fedsuite event probe" copies on the beta
operator kept their pre-edit titles), so an edit that comes first holds the place too, with the edited words, inactive
and marked HELD_FOR_COPY; the copy that meets it goes live with them, and a retract in between keeps it retracted. The
edit tests fail on fa5b6c1a's module (the control).
"""
from __future__ import annotations

import contextlib
import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Delete, Update

from agentvault_registry.background_tasks import reactor_admin_broadcast_received as r
from agentvault_registry.routers import admin_broadcast

FRAME = "cloud-op-sbxalphaop"
SENT = {"source_frame": FRAME, "broadcast_id": 1095, "title": "phase6 sweep", "body": "phase6 admin-bridge sweep test",
        "broadcast_type": "info"}
RETRACTED = {"source_frame": FRAME, "broadcast_id": 1095, "retracted_by": 1}


class _Result:
    def __init__(self, rows: List[Any] = (), scalar: Any = None):
        self.rows, self.scalar = list(rows), scalar

    def fetchall(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.scalar


class _Table:
    """admin_broadcasts as the reactor sees it: rows by (source_frame, idempotency_key), the UNIQUE the real index holds."""

    def __init__(self):
        self.rows: Dict[Tuple[str, str], Any] = {}
        self.next_id = 100


class _Db:
    def __init__(self, table: _Table, admins: Tuple[int, ...] = (1,)):
        self.t, self.admins, self.pending = table, admins, []

    @staticmethod
    def _key(stmt) -> Tuple[str, str]:
        p = stmt.compile().params
        return (next(v for k, v in p.items() if k.startswith("source_frame")),
                next(v for k, v in p.items() if k.startswith("idempotency_key")))

    async def execute(self, stmt):
        text = str(stmt)
        if isinstance(stmt, Delete):
            p = stmt.compile().params
            title = next(v for k, v in p.items() if k.startswith("title"))
            held = next((v for k, v in p.items() if k.startswith("ws_recipients")), object())
            cutoff = next(v for k, v in p.items() if k.startswith("created_at"))
            gone = [k for k, row in self.t.rows.items()
                    if (row.title == title or row.ws_recipients == held) and row.is_active is False
                    and row.created_at < cutoff]
            return _Result([(self.t.rows.pop(k).id,) for k in gone])
        if isinstance(stmt, Update):
            row = self.t.rows.get(self._key(stmt))
            if row is None:
                return _Result([])
            for k, v in stmt.compile().params.items():          # the SET values (the WHERE's names carry a suffix)
                if k in ("title", "body", "broadcast_type", "is_active", "ws_recipients"):
                    setattr(row, k, v)
            return _Result([(row.id,)])
        if "developers" in text:
            return _Result(scalar=min(self.admins) if self.admins else None)
        return _Result(scalar=self.t.rows.get(self._key(stmt)))

    def add(self, row):
        self.pending.append(row)

    async def commit(self):
        pending, self.pending = self.pending, []
        for row in pending:
            key = (row.source_frame, row.idempotency_key)
            if key in self.t.rows:
                raise IntegrityError("INSERT INTO admin_broadcasts", {}, Exception("uq_admin_broadcasts_source_idem"))
            if row.is_active is None:
                row.is_active = True               # the column's server default
            if row.ws_recipients is None:
                row.ws_recipients = 0
            if getattr(row, "created_at", None) is None:
                row.created_at = datetime.now(timezone.utc)
            row.id, self.t.next_id = self.t.next_id, self.t.next_id + 1
            self.t.rows[key] = row

    async def rollback(self):
        self.pending = []

    async def refresh(self, row):
        pass


def _sent_reactor():
    # without __init__: a second instance in one session would collide on the leader key it registers
    return r.AdminBroadcastSentReceived.__new__(r.AdminBroadcastSentReceived)


def _use(monkeypatch, table: _Table) -> None:
    @contextlib.asynccontextmanager
    async def ctx():
        yield _Db(table)
    monkeypatch.setattr(r, "get_db_context", ctx)
    monkeypatch.setattr(r, "LOCAL_FRAME", "cloud-op-sbxbetaop")


async def test_a_retract_that_comes_first_keeps_the_later_copy_retracted(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    await r._apply_retract_to_local(dict(RETRACTED))         # the retract reactor wins the race
    assert await r._materialize_received_broadcast(dict(SENT)) is None    # None: no live toast
    (row,) = table.rows.values()
    assert row.is_active is False
    assert row.title == "phase6 sweep" and row.body == "phase6 admin-bridge sweep test"   # the admin list reads the real one


async def test_the_sent_reactor_pushes_no_toast_for_it(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    pushed: List[str] = []

    async def push(**kw):
        pushed.append(kw.get("title"))
    monkeypatch.setattr(r, "broadcast_notification", push)
    await r._apply_retract_to_local(dict(RETRACTED))
    await _sent_reactor().handle_event(dict(SENT))
    assert pushed == []


async def test_the_usual_order_is_unchanged(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    local_id = await r._materialize_received_broadcast(dict(SENT))
    assert local_id is not None and table.rows[(FRAME, "foreign-1095")].is_active is True
    await r._apply_retract_to_local(dict(RETRACTED))
    assert table.rows[(FRAME, "foreign-1095")].is_active is False and len(table.rows) == 1


async def test_a_redelivered_sent_for_a_live_copy_still_answers_its_id(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    first = await r._materialize_received_broadcast(dict(SENT))
    assert await r._materialize_received_broadcast(dict(SENT)) == first


async def test_a_copy_landing_between_the_update_and_the_placeholder_is_retracted(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    real_retract = r._retract_rows
    calls = {"n": 0}

    async def retract_then_copy_lands(db, source_frame, idem):
        calls["n"] += 1
        ids = await real_retract(db, source_frame, idem)
        if calls["n"] == 1:                                    # the copy commits right after the first UPDATE
            await r._materialize_received_broadcast(dict(SENT))
        return ids
    monkeypatch.setattr(r, "_retract_rows", retract_then_copy_lands)
    await r._apply_retract_to_local(dict(RETRACTED))
    assert calls["n"] == 2 and table.rows[(FRAME, "foreign-1095")].is_active is False and len(table.rows) == 1


async def test_a_local_retract_writes_nothing(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    await r._apply_retract_to_local({**RETRACTED, "source_frame": "cloud-op-sbxbetaop"})
    assert table.rows == {}


async def test_a_targeted_broadcasts_retract_holds_no_place(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    await r._apply_retract_to_local({**RETRACTED, "targeted": True})     # an org's broadcast or a direct notice
    assert table.rows == {}


def test_the_senders_retract_says_whether_its_broadcast_was_targeted():
    src = inspect.getsource(admin_broadcast.retract_broadcast)
    assert '"targeted": broadcast.target_org_id is not None or broadcast.target_developer_id is not None' in src


async def test_placeholders_no_copy_met_in_a_week_are_pruned_and_nothing_else(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    old = datetime.now(timezone.utc) - timedelta(days=8)
    for i, (title, created) in enumerate([(r.PLACEHOLDER_TITLE, old),                     # stale placeholder: pruned
                                           ("phase6 sweep", old),                          # a real retracted copy: kept
                                           (r.PLACEHOLDER_TITLE, datetime.now(timezone.utc))]):   # fresh: kept
        row = r.models.AdminBroadcast(title=title, body="b", broadcast_type="info", created_by=1, send_email=False,
                                      ws_recipients=0, is_active=False, source_frame=FRAME,
                                      idempotency_key=f"foreign-{900 + i}")
        row.id, row.created_at = 900 + i, created
        table.rows[(FRAME, row.idempotency_key)] = row
    await r._apply_retract_to_local(dict(RETRACTED))          # writes a placeholder, then prunes
    assert sorted(k[1] for k in table.rows) == ["foreign-1095", "foreign-901", "foreign-902"]


# ─── an edit that comes before its copy (agentvault2-66's finding) ───────────────────────────────────────────────────

EDITED = {"source_frame": FRAME, "broadcast_id": 1095, "title": "phase6 sweep edited", "broadcast_type": "warning",
          "body": "phase6 admin-bridge sweep test, edited"}


async def test_an_edit_that_comes_first_reaches_the_copy(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    await r._apply_edit_to_local(dict(EDITED))                # the edit reactor wins the race
    (held,) = table.rows.values()
    assert held.is_active is False and held.ws_recipients == r.HELD_FOR_COPY      # not live before its copy
    content: Dict[str, Any] = {}
    local_id = await r._materialize_received_broadcast(dict(SENT, cta_url="https://x.example/s"), content)
    assert local_id == held.id
    (row,) = table.rows.values()
    assert row.is_active is True and row.ws_recipients == 0 and row.cta_url == "https://x.example/s"
    assert (row.title, row.body, row.broadcast_type) == ("phase6 sweep edited", "phase6 admin-bridge sweep test, edited",
                                                         "warning")
    assert content == {"title": "phase6 sweep edited", "body": "phase6 admin-bridge sweep test, edited",
                       "broadcast_type": "warning"}


async def test_its_live_toast_carries_the_edited_words(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    pushed: List[Tuple[str, str]] = []

    async def push(**kw):
        pushed.append((kw.get("title"), kw.get("message")))
    monkeypatch.setattr(r, "broadcast_notification", push)
    await r._apply_edit_to_local(dict(EDITED))
    await _sent_reactor().handle_event(dict(SENT))
    assert pushed == [("phase6 sweep edited", "phase6 admin-bridge sweep test, edited")]


async def test_an_edit_then_a_retract_before_the_copy_keeps_it_retracted_with_the_edited_words(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    await r._apply_edit_to_local(dict(EDITED))
    await r._apply_retract_to_local(dict(RETRACTED))
    assert await r._materialize_received_broadcast(dict(SENT)) is None              # no toast
    (row,) = table.rows.values()
    assert row.is_active is False and row.ws_recipients == 0 and row.title == "phase6 sweep edited"


async def test_a_retract_then_an_edit_before_the_copy_keeps_it_retracted_with_the_edited_words(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    await r._apply_retract_to_local(dict(RETRACTED))
    await r._apply_edit_to_local(dict(EDITED))
    assert await r._materialize_received_broadcast(dict(SENT)) is None
    (row,) = table.rows.values()
    assert row.is_active is False and row.title == "phase6 sweep edited"     # the edit is newer than the Sent


async def test_a_scheduled_copy_whose_edit_came_first_waits_for_its_time(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    pushed: List[str] = []

    async def push(**kw):
        pushed.append(kw.get("title"))
    monkeypatch.setattr(r, "broadcast_notification", push)
    when = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    await r._apply_edit_to_local(dict(EDITED))
    await _sent_reactor().handle_event(dict(SENT, deferred=True, scheduled_for=when))
    (row,) = table.rows.values()
    assert row.is_active is True and row.scheduled_for is not None and pushed == []
    assert row.title == "phase6 sweep edited"            # live at its time with the edited words


async def test_a_copy_landing_between_the_edits_update_and_its_place_takes_the_edit(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    real_edit = r._edit_rows
    calls = {"n": 0}

    async def edit_then_copy_lands(db, source_frame, idem, values):
        calls["n"] += 1
        ids = await real_edit(db, source_frame, idem, values)
        if calls["n"] == 1:                                    # the copy commits right after the first UPDATE
            await r._materialize_received_broadcast(dict(SENT))
        return ids
    monkeypatch.setattr(r, "_edit_rows", edit_then_copy_lands)
    await r._apply_edit_to_local(dict(EDITED))
    (row,) = table.rows.values()
    assert calls["n"] == 2 and row.is_active is True and row.title == "phase6 sweep edited"


async def test_an_edit_carrying_part_of_the_words_holds_no_place(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    await r._apply_edit_to_local({"source_frame": FRAME, "broadcast_id": 1095, "title": "only the title"})
    assert table.rows == {}


async def test_held_edits_no_copy_met_in_a_week_are_pruned_and_nothing_else(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    old = datetime.now(timezone.utc) - timedelta(days=8)
    for i, (ws, created) in enumerate([(r.HELD_FOR_COPY, old),                          # stale held edit: pruned
                                        (0, old),                                         # a real retracted copy: kept
                                        (r.HELD_FOR_COPY, datetime.now(timezone.utc))]):  # fresh: kept
        row = r.models.AdminBroadcast(title=f"edited {i}", body="b", broadcast_type="info", created_by=1,
                                      send_email=False, ws_recipients=ws, is_active=False, source_frame=FRAME,
                                      idempotency_key=f"foreign-{800 + i}")
        row.id, row.created_at = 800 + i, created
        table.rows[(FRAME, row.idempotency_key)] = row
    await r._apply_edit_to_local(dict(EDITED))                 # holds a place, then prunes
    assert sorted(k[1] for k in table.rows) == ["foreign-1095", "foreign-801", "foreign-802"]
