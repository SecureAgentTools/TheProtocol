"""V0652 (ai) (order gwo_b13813d486f28d456a324293, agentvault2-14, 2026-10-31): support tickets, played through.

session-tester filed and played a ticket through on EU (sessionlogs2026/FINDINGS_2026-10-31_SUPPORT_TICKET_EU.md, the
maintainer's ask at seq 301, its recommendations approved at seq 311/313): the lifecycle completes and access holds,
with six defects. Each case below pins one fix and fails on 84e840985 (V0651):

  1+2  the support thread's rows reached the requester as raw machine strings (`support.in_progress`), and every desk
       act notified two or three times: the thread's writes now deliver live only, so the ticket's one typed notice is
       the one per act, and a desk reply's notice carries its words;
  3    a requester's reply that reopens a resolved ticket writes its status row (authored by the requester) and cues
       the desk;
  4    the review-grant lines name what happened: the grant row promises "resolved or closed", and the line that ends
       it says "resolved" at a resolve;
  5    the desk is told durably: a typed `support.desk` notice to every admin_support holder (not suspended, not
       deleted, not the person who acted) on a new ticket, a requester's reply and a reopen, its click the chat desk;
  6    the five developer-only support routes declare it (x-callers), and the reference reads that;
  minor: a thread read names the support rail ("Support", never a blank author).
"""
from __future__ import annotations

import asyncio
import inspect
import types

import pytest

from agentvault_registry.services import chat_service as cs
from agentvault_registry.services import chat_support
from agentvault_registry.routers import support as sup


def run(coro):
    return asyncio.run(coro)


# ── 1+2: one notice per desk act ─────────────────────────────────────────────────────────────────────────────────────

def test_the_support_rail_delivers_live_only(monkeypatch):
    seen = {}

    async def _recipients(_db, _conv, _sender):
        return [{"ptype": "developer", "owner_developer_id": 16, "muted": False, "agent_did": None}]

    def _deliver(*a, **k):
        seen["args"], seen["kw"] = a, k

    monkeypatch.setattr(cs, "recipients_snapshot", _recipients)
    monkeypatch.setattr(cs, "deliver", _deliver)
    run(chat_support._announce(None, types.SimpleNamespace(id="c1", kind="support"), chat_support.SUPPORT_DESK,
                               {"id": "m1", "seq": 2, "kind": "system", "body": "support.in_progress"}))
    assert seen["kw"].get("notify_absent") is False, seen


def _fan_out(monkeypatch, **kw):
    spawned = []

    def _spawn(coro, what=""):
        spawned.append(what)
        coro.close()

    class _Manager:
        async def broadcast_to_subscribers(self, *_a, **_k):
            return None

    import agentvault_registry.routers.websocket as ws
    monkeypatch.setattr(ws, "manager", _Manager(), raising=False)
    monkeypatch.setattr(cs, "spawn", _spawn)
    run(cs.fan_out_message("c1", "support", {"id": "m1", "seq": 2},
                           [{"ptype": "developer", "owner_developer_id": 16, "muted": False, "agent_did": None}],
                           "Support", **kw))
    return [w for w in spawned if "offline notices" in w]


def test_the_fan_out_leaves_the_absent_notice_out_when_asked(monkeypatch):
    assert _fan_out(monkeypatch, notify_absent=False) == []
    # control: every other caller keeps its notice
    assert len(_fan_out(monkeypatch)) == 1


def test_a_desk_replys_one_notice_carries_its_words():
    src = inspect.getsource(sup.admin_reply_to_ticket)
    assert "_excerpt(payload.message)" in src and "has a new reply from the admin team" not in src
    assert sup._excerpt("  a\n reply   with  space ") == "a reply with space"
    long = "x" * 400
    out = sup._excerpt(long)
    assert len(out) == 160 and out.endswith("…")


# ── 3: a reopen writes its row, authored by the requester ────────────────────────────────────────────────────────────

class _DB:
    def __init__(self):
        self.added, self.commits = [], 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def _reply(monkeypatch, status):
    calls = []

    async def _mirror(fn, *a, **k):
        calls.append((fn.__name__, a[2:], k))

    async def _emit(*_a, **_k):
        return None

    async def _desk(db, ticket, event, text=None, exclude_dev=None):
        calls.append(("desk", event, exclude_dev))
        return 1

    monkeypatch.setattr(sup, "_mirror", _mirror)
    monkeypatch.setattr(sup, "_emit_support_event", _emit)
    monkeypatch.setattr(sup, "_notify_desk", _desk)
    ticket = types.SimpleNamespace(id=1, status=status, developer_id=16, subject="s")
    dev = types.SimpleNamespace(id=16, display_name="P", name="p", email="p@example.test")
    run(sup.add_developer_reply(_DB(), ticket, dev, "a reply after the resolve"))
    return ticket, calls


def test_a_reply_that_reopens_writes_the_status_row_and_cues_the_desk(monkeypatch):
    ticket, calls = _reply(monkeypatch, "resolved")
    assert ticket.status == "open"
    rows = [c for c in calls if c[0] == "mirror_status"]
    assert rows == [("mirror_status", ("resolved", "open"), {"by_name": "P", "by_owner": True})], calls
    assert ("desk", "reopen", 16) in calls


def test_a_plain_reply_writes_no_status_row_and_tells_the_desk_it_is_a_reply(monkeypatch):
    ticket, calls = _reply(monkeypatch, "in_progress")
    assert ticket.status == "in_progress"
    assert not [c for c in calls if c[0] == "mirror_status"]
    assert ("desk", "reply", 16) in calls


def test_an_owner_moved_status_row_is_authored_by_the_owner(monkeypatch):
    seen = {}

    async def _thread(_db, _ticket):
        return types.SimpleNamespace(id="c1", kind="support")

    async def _write(_db, _conv, *, sender, kind, body, card, client_ref, mark_read):
        seen.update(sender=sender, kind=kind, body=body, mark_read=mark_read)
        return {"id": "m1"}

    async def _announce(*_a, **_k):
        return None

    monkeypatch.setattr(chat_support, "ensure_thread", _thread)
    monkeypatch.setattr(chat_support, "_write", _write)
    monkeypatch.setattr(chat_support, "_announce", _announce)
    t = types.SimpleNamespace(id=1, developer_id=16)
    run(chat_support.mirror_status(None, t, "resolved", "open", by_name="P", by_owner=True))
    assert seen["sender"].ptype == "developer" and int(seen["sender"].developer_id) == 16
    assert seen["body"] == "support.open" and seen["kind"] == "system" and seen["mark_read"] is True
    # control: the desk's own change stays the rail's
    run(chat_support.mirror_status(None, t, "open", "in_progress", by_name="Support"))
    assert seen["sender"].ptype == "system" and seen["mark_read"] is False


# ── 4: the review lines name what happened ───────────────────────────────────────────────────────────────────────────

def test_the_review_line_says_resolved_at_a_resolve(monkeypatch):
    said = []
    grant = types.SimpleNamespace(conversation_id="c9", revoked_at=None, revoked_reason=None)

    class _Res:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    class _DB2:
        def __init__(self):
            self.n = 0

        async def execute(self, *_a, **_k):
            self.n += 1
            return _Res([grant] if self.n == 1 else [types.SimpleNamespace(id="c9", kind="org")])

    async def _revoke(_db, g, reason):
        g.revoked_reason = reason

    async def _announce_event(_db, _conv, _sender, text):
        said.append(text)

    monkeypatch.setattr(chat_support, "revoke_review_grant", _revoke)
    monkeypatch.setattr(chat_support, "announce_review_event", _announce_event)
    run(chat_support.end_review_grants_for_ticket(_DB2(), 1, reason="ticket_resolved"))
    assert said == ["The support desk's review access ended: ticket #1 resolved."], said


def test_the_grant_row_promises_resolved_or_closed():
    from agentvault_registry.routers import chat
    src = inspect.getsource(chat)
    assert "until the ticket is resolved or closed" in src and "until the ticket closes" not in src


# ── 5: the desk is told durably ──────────────────────────────────────────────────────────────────────────────────────

def test_the_catalog_carries_the_desks_notice():
    from agentvault_registry.services import notification_catalog as nc
    t = nc.get_type("support.desk")
    assert t is not None and t.audience == "admin" and t.category == "ops" and not t.mandatory
    assert nc.BY_KEY["support.desk"] is t


def test_the_desks_notice_names_the_ticket_and_opens_the_chat_desk(monkeypatch):
    sent = []

    async def _recipients(_db, exclude_dev=None):
        return [1, 2]

    async def _notify(event, devs, **kw):
        sent.append((event, devs, kw))

    import agentvault_registry.background_tasks.push_notify as pn
    monkeypatch.setattr(sup, "_desk_recipients", _recipients)
    monkeypatch.setattr(pn, "notify", _notify)
    ticket = types.SimpleNamespace(id=7, subject="My agent cannot pay")
    assert run(sup._notify_desk(None, ticket, "created", "It says 402 every time.")) == 2
    (event, devs, kw), = sent
    assert event == "support.desk" and devs == [1, 2]
    assert kw["title"] == "New support ticket #7"
    assert kw["message"] == '"My agent cannot pay": It says 402 every time.'
    assert kw["click"] == "/ui#/admin/chatdesk?ticket=7"


def test_the_desks_notice_never_fails_the_ticket(monkeypatch):
    async def _boom(_db, exclude_dev=None):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(sup, "_desk_recipients", _boom)
    assert run(sup._notify_desk(None, types.SimpleNamespace(id=7, subject="s"), "reply", "t")) == 0


def test_the_desk_is_every_support_holder_but_the_one_who_acted():
    from agentvault_registry import models
    from tests._sqlite_db import sqlite_db
    db = sqlite_db(models.Developer)
    s = db.sync
    rows = [
        (1, True, False, False, None),    # an admin: told
        (2, False, True, False, None),    # admin_support: told
        (3, False, False, False, None),   # a member: not
        (4, False, True, True, None),     # suspended: not
        (5, True, False, False, "x"),     # deleted: not
        (16, True, False, False, None),   # the requester, an admin on a one-operator registry: left out
    ]
    import datetime as dt
    for i, admin, support, susp, deleted in rows:
        s.add(models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.test", hashed_password="x",
                               is_admin=admin, admin_support=support, is_suspended=susp,
                               deleted_at=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc) if deleted else None))
    s.commit()
    assert sorted(run(sup._desk_recipients(db, exclude_dev=16))) == [1, 2]


# ── 6: the reference names who may call the support routes ──────────────────────────────────────────────────────────

def test_the_developer_only_support_routes_say_so():
    from agentvault_registry.routers import chat
    want = {("GET", "/conversations/{conversation_id}/support"), ("POST", "/conversations/{conversation_id}/support-reply"),
            ("POST", "/support/open"), ("POST", "/conversations/{conversation_id}/support-review"),
            ("DELETE", "/conversations/{conversation_id}/support-review/{grant_id}")}
    got = set()
    for r in chat.router.routes:
        extra = getattr(r, "openapi_extra", None) or {}
        for m in getattr(r, "methods", ()) or ():
            rel = r.path[len(chat.router.prefix):] if r.path.startswith(chat.router.prefix) else r.path
            if (m, rel) in want and extra.get("x-callers") == ["developer"]:
                got.add((m, rel))
            if (m, rel) == ("GET", "/conversations/{conversation_id}/support-review"):
                assert "x-callers" not in extra, "agents in the room read the grant banner: it stays open to them"
    assert got == want, sorted(want - got)


def test_the_reference_reads_a_declared_caller():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "gen_reference_docs.py").read_text()
    assert 'op.get("x-callers")' in src


# ── minor: the support rail has a name in a thread read ──────────────────────────────────────────────────────────────

def test_a_thread_read_names_the_support_rail():
    m = types.SimpleNamespace(sender_ptype="system", sender_id="support")
    assert cs.system_sender_name(m) == "Support"
    assert cs.system_sender_name(types.SimpleNamespace(sender_ptype="system", sender_id="deal-rail")) == ""
    assert cs.system_sender_name(types.SimpleNamespace(sender_ptype="developer", sender_id="6")) == ""


# ── the recut (session-tester's trial 7, the sessions' room seq 609/610): a close with a message is ONE desk act ─────
# supportCloseTicket posted the message as a reply, then the status: the requester got "New Reply" and "Resolved" for one
# act. The status route now takes the closing message and notifies once, in its words; the tool makes one call. Each case
# fails on 7204fa130 (no apply_admin_status; the tool's two calls).

def _status(monkeypatch, old, new, message):
    calls, notices = [], []

    async def _mirror(fn, *a, **k):
        calls.append(fn.__name__)

    async def _emit(_ticket, kind):
        calls.append(("event", kind))

    async def _notice(**k):
        notices.append(k)

    monkeypatch.setattr(sup, "_mirror", _mirror)
    monkeypatch.setattr(sup, "_emit_support_event", _emit)
    monkeypatch.setattr(sup, "_send_ticket_notification", _notice)
    db = _DB()
    ticket = types.SimpleNamespace(id=4, status=old, developer_id=16, subject="the export stops at 10k rows")
    admin = types.SimpleNamespace(id=6, display_name=None)
    sent = run(sup.apply_admin_status(db, ticket, admin, new, message))
    return ticket, db, calls, notices, sent


def test_a_close_with_a_message_sends_one_notice_in_its_words(monkeypatch):
    ticket, db, calls, notices, sent = _status(monkeypatch, "in_progress", "resolved", "  Fixed in V0652, thanks.  ")
    assert sent == 1 and len(notices) == 1
    assert notices[0]["title"] == "Support Ticket #4: Resolved"
    assert notices[0]["body"] == '"the export stops at 10k rows": Fixed in V0652, thanks.'
    assert ticket.status == "resolved" and db.commits == 1
    [m] = db.added
    assert (m.sender_type, m.sender_name, m.message) == ("admin", "Support", "Fixed in V0652, thanks.")
    assert calls[:2] == ["mirror_desk_message", "mirror_status"]          # the message, then the status row
    assert ("event", "reply") in calls and ("event", "status") in calls


def test_a_close_without_a_message_keeps_its_one_notice(monkeypatch):
    ticket, db, calls, notices, sent = _status(monkeypatch, "in_progress", "closed", None)
    assert sent == 1 and [n["title"] for n in notices] == ["Support Ticket #4: Closed"]
    assert notices[0]["body"] == 'Your support ticket "the export stops at 10k rows" has been closed.'
    assert db.added == [] and calls[0] == "mirror_status"


def test_a_message_with_no_closing_move_is_one_reply_notice(monkeypatch):
    ticket, db, calls, notices, sent = _status(monkeypatch, "in_progress", "in_progress", "Still looking.")
    assert sent == 1 and [n["title"] for n in notices] == ["Support Ticket #4: New Reply"]
    assert "mirror_status" not in calls                                   # no move, no status row


def test_a_status_move_that_is_not_a_close_notifies_no_one(monkeypatch):
    ticket, db, calls, notices, sent = _status(monkeypatch, "open", "in_progress", None)
    assert sent == 0 and notices == [] and calls[0] == "mirror_status"


def test_the_close_tool_makes_one_call_carrying_the_message(monkeypatch):
    from agentvault_registry.mcp import tools_admin as ta
    posts = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"id": 4, "status": "resolved"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posts.append((url.rsplit("/", 1)[-1], json))
            return _Resp()

    monkeypatch.setattr(ta, "require_admin_auth", lambda auth: None)
    monkeypatch.setattr(ta, "_get_effective_jwt", lambda auth: "jwt")
    monkeypatch.setattr(ta.httpx, "AsyncClient", _Client)
    out = run(ta.support_close_ticket(types.SimpleNamespace(), 4, "resolved", " Fixed, thanks. "))
    assert out["ok"] is True and out["reply_sent"] is True
    assert posts == [("status", {"status": "resolved", "message": "Fixed, thanks."})]
    posts.clear()
    run(ta.support_close_ticket(types.SimpleNamespace(), 4, "closed"))
    assert posts == [("status", {"status": "closed"})]


def test_the_status_route_takes_the_message_and_the_owner_route_does_not():
    assert sup.TicketStatusUpdate(status="resolved", message="done").message == "done"
    assert sup.TicketStatusUpdate(status="resolved").message is None
    assert "message" not in sup.OwnerStatusUpdate.model_fields
    with pytest.raises(Exception):
        sup.TicketStatusUpdate(status="resolved", message="")
