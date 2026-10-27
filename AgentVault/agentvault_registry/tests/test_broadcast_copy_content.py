"""D6-211: a peer's copy of a broadcast reads as the broadcast, waits for its time, and follows its edits.

The receiving reactor read body, cta_url and cta_label from AdminBroadcastSent, and the sender never put them in: every
copy read "[Federated from <registry>]" and lost its call to action. A broadcast scheduled for tomorrow was copied and
pushed live on every peer at once, and an edit reached no copy (its event carried flags only). A broadcast to everyone
now carries its words (copy_content); a targeted one carries none, as it is never copied (§SECFIX D6-305).
"""
import ast
import contextlib
import pathlib
import types
from datetime import datetime, timedelta, timezone

from agentvault_registry.background_tasks import reactor_admin_broadcast_received as r
from agentvault_registry.routers import admin_broadcast as ab

ROUTER = pathlib.Path(ab.__file__)


def _b(**kw):
    base = dict(body="The registry restarts at 02:00Z.", cta_url="https://example.org/status", cta_label="Status",
                target_org_id=None, target_developer_id=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_a_broadcast_to_everyone_carries_its_words():
    assert ab.copy_content(_b()) == {"body": "The registry restarts at 02:00Z.", "cta_url": "https://example.org/status",
                                     "cta_label": "Status"}


def test_a_targeted_broadcast_carries_none():
    assert ab.copy_content(_b(target_org_id="0b6f1d2e-3c4d-4e5f-8a9b-0c1d2e3f4a5b")) == {}
    assert ab.copy_content(_b(target_developer_id=7)) == {}
    assert ab.edit_content(_b(target_developer_id=7, title="t", broadcast_type="info")) == {}


def test_an_oversized_body_stays_home_and_the_rest_rides():
    long_body = "x" * (ab.COPY_BODY_MAX + 1)
    assert ab.copy_content(_b(body=long_body)) == {"body": None, "cta_url": "https://example.org/status",
                                                     "cta_label": "Status"}
    assert ab.copy_content(_b(body="x" * ab.COPY_BODY_MAX))["body"] == "x" * ab.COPY_BODY_MAX
    assert ab.edit_content(_b(body=long_body, title="Moved", broadcast_type="maintenance")) == {
        "title": "Moved", "broadcast_type": "maintenance"}


def test_an_edit_carries_the_new_words():
    assert ab.edit_content(_b(title="Moved", broadcast_type="maintenance")) == {
        "title": "Moved", "broadcast_type": "maintenance", "body": "The registry restarts at 02:00Z."}


def _emit_data(route):
    tree = ast.parse(ROUTER.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == route)
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "emit":
            for kw in call.keywords:
                if kw.arg == "data" and isinstance(kw.value, ast.Dict):
                    return kw.value
    raise AssertionError(f"{route} emits no event with a data dict")


def _spreads(node, name) -> bool:
    return any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == name for c in ast.walk(node))


def test_the_sent_and_edited_events_carry_the_words_by_the_rule():
    for route, rule in (("create_broadcast", "copy_content"), ("update_broadcast", "edit_content")):
        data = _emit_data(route)
        spread = [v for k, v in zip(data.keys, data.values) if k is None]
        assert any(_spreads(v, rule) for v in spread), route


# ── the receiver ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat()


def test_a_deferred_broadcast_waits_for_its_time():
    when = r._deferred_until({"deferred": True, "scheduled_for": _iso(timedelta(hours=5))})
    assert when is not None and when > datetime.now(timezone.utc)
    assert r._deferred_until({"deferred": True, "scheduled_for": _iso(-timedelta(minutes=1))}) is None
    assert r._deferred_until({"deferred": False, "scheduled_for": _iso(timedelta(hours=5))}) is None
    assert r._deferred_until({"deferred": True, "scheduled_for": "not a time"}) is None
    naive = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert r._deferred_until({"deferred": True, "scheduled_for": naive}) is not None


class _Result:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v

    def fetchall(self):
        return [(v,) for v in (self.v or [])]


class _Db:
    def __init__(self, returning=None):
        self.added, self.statements, self.returning = [], [], returning

    async def execute(self, stmt):
        self.statements.append(stmt)
        if "is_admin" in str(stmt):
            return _Result(1)
        return _Result(self.returning)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass

    async def refresh(self, row):
        row.id = 42

    async def rollback(self):
        pass


def _ctx(db):
    @contextlib.asynccontextmanager
    async def _get():
        yield db
    return _get


EVENT = {"source_frame": "Sandbox Beta", "broadcast_id": 9, "title": "Maintenance", "broadcast_type": "maintenance",
         "body": "The registry restarts at 02:00Z.", "cta_url": "https://example.org/status", "cta_label": "Status"}


async def test_the_copy_reads_as_the_broadcast_and_a_scheduled_one_is_copied_as_scheduled(monkeypatch):
    db = _Db()
    monkeypatch.setattr(r, "get_db_context", _ctx(db))
    monkeypatch.setattr(r, "LOCAL_FRAME", "sbx-alpha")
    assert await r._materialize_received_broadcast(dict(EVENT)) == 42
    row = db.added[0]
    assert (row.body, row.cta_url, row.cta_label, row.scheduled_for) == (
        "The registry restarts at 02:00Z.", "https://example.org/status", "Status", None)
    db2 = _Db()
    monkeypatch.setattr(r, "get_db_context", _ctx(db2))
    later = dict(EVENT, deferred=True, scheduled_for=_iso(timedelta(hours=5)))
    assert await r._materialize_received_broadcast(later) == 42
    assert db2.added[0].scheduled_for is not None and db2.added[0].scheduled_for > datetime.now(timezone.utc)


async def test_a_scheduled_copy_is_not_pushed_now(monkeypatch):
    pushed = []

    async def _materialized(event_data, content=None):
        return 42

    async def _push(**kw):
        pushed.append(kw)
    monkeypatch.setattr(r, "_materialize_received_broadcast", _materialized)
    monkeypatch.setattr(r, "broadcast_notification", _push)
    reactor = r.AdminBroadcastSentReceived.__new__(r.AdminBroadcastSentReceived)
    await reactor.handle_event(dict(EVENT, deferred=True, scheduled_for=_iso(timedelta(hours=5))))
    assert pushed == []
    await reactor.handle_event(dict(EVENT))
    assert len(pushed) == 1 and pushed[0]["message"] == "The registry restarts at 02:00Z."


async def test_an_edit_reaches_the_copy(monkeypatch):
    db = _Db(returning=[42])
    monkeypatch.setattr(r, "get_db_context", _ctx(db))
    monkeypatch.setattr(r, "LOCAL_FRAME", "sbx-alpha")
    await r._apply_edit_to_local({"source_frame": "Sandbox Beta", "broadcast_id": 9, "title": "Maintenance (moved)",
                                  "broadcast_type": "maintenance", "body": "The registry restarts at 03:00Z."})
    assert len(db.statements) == 1
    params = db.statements[0].compile().params
    assert params["title"] == "Maintenance (moved)" and params["body"] == "The registry restarts at 03:00Z."
    assert "foreign-9" in params.values()


async def test_an_edit_with_flags_only_changes_nothing(monkeypatch):
    def touched():
        raise AssertionError("the receiver opened its database for an edit that carries no words")
    monkeypatch.setattr(r, "get_db_context", touched)
    monkeypatch.setattr(r, "LOCAL_FRAME", "sbx-alpha")
    await r._apply_edit_to_local({"source_frame": "Sandbox Beta", "broadcast_id": 9, "title_changed": True,
                                  "body_changed": True})
