"""V0658 (e), polish 17 and 18 of the disputes discovery: when work is due, and how long after its deadline a missed one
goes to a dispute.

17. Before: an awarded Guild order kept the deadline set when it was POSTED, so a bid with an ETA past it was due before
    its own estimate (guild_order_reaper reused the posting deadline as a soft ceiling). Now the award sets the work
    deadline to the later of the order's deadline and the award + the winning bid's ETA, and says it: in the award's
    answer, the winner's notice and the award webhook.
18. Before: a Guild order went to a dispute 1 hour after its deadline, a contract 24 hours after. Now one rule for both,
    services/deadline_grace.grace_hours(), 24 hours by default (the Commander's yes, room seq 1617/1633), and the day-
    before reminders say it.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import types

import pytest

T_AWARD = dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.timezone.utc)


class _Result:
    def __init__(self, rows=(), rowcount=None, scalar=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount
        self._scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def fetchall(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar


class _Db:
    def __init__(self, handlers=()):
        self.handlers = list(handlers)
        self.calls = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, params or {}))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, params or {}) if callable(res) else res
        return _Result([], rowcount=0)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


# ── 18: one grace rule ───────────────────────────────────────────────────────────────────────────────────────────────
def test_the_grace_is_a_day_by_default(monkeypatch):
    from agentvault_registry.services import deadline_grace as g
    monkeypatch.delenv("DEADLINE_GRACE_HOURS", raising=False)
    monkeypatch.delenv("CONTRACT_DEADLINE_GRACE_HOURS", raising=False)
    assert g.grace_hours() == 24
    assert g.grace_words() == "a day"


def test_one_setting_for_both_and_the_old_contract_name_still_counts(monkeypatch):
    from agentvault_registry.services import deadline_grace as g
    monkeypatch.delenv("DEADLINE_GRACE_HOURS", raising=False)
    monkeypatch.setenv("CONTRACT_DEADLINE_GRACE_HOURS", "48")
    assert g.grace_hours() == 48                       # an operator who set the contract's name keeps it, for both
    monkeypatch.setenv("DEADLINE_GRACE_HOURS", "6")
    assert g.grace_hours() == 6 and g.grace_words() == "6 hours"
    for bad in ("0", "-3", "soon", ""):
        monkeypatch.setenv("DEADLINE_GRACE_HOURS", bad)
        assert g.grace_hours() == 48, bad               # nonsense falls back, never to no grace at all


def test_a_guild_order_goes_to_dispute_after_the_grace_not_an_hour(monkeypatch):
    from agentvault_registry.background_tasks import guild_order_reaper as reaper
    from agentvault_registry.services import deadline_grace
    monkeypatch.setattr(deadline_grace, "grace_hours", lambda: 24)
    db = _Db([("status='open'", _Result([]))])

    async def zero(db):
        return 0
    monkeypatch.setattr(reaper, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(reaper, "_sweep_stuck_money_states", zero)
    monkeypatch.setattr(reaper, "_sweep_abandoned_submitted", zero)
    asyncio.run(reaper._sweep_once())
    overdue = [(s, p) for s, p in db.calls if "WHERE status='awarded' AND deadline" in s]
    assert overdue, "the sweep reads the overdue awarded orders"
    sql, params = overdue[0]
    assert "interval '1 hour'" not in sql
    assert params.get("grace_h") == 24, params


def test_a_contract_goes_to_dispute_after_the_same_grace(monkeypatch):
    from agentvault_registry.background_tasks import contract_reaper as cr
    from agentvault_registry.services import deadline_grace
    monkeypatch.setattr(deadline_grace, "grace_hours", lambda: 30)
    db = _Db([("UPDATE contracts SET status='disputed'", _Result([]))])
    asyncio.run(cr._sweep_deadline_disputes(db))
    sql, params = next((s, p) for s, p in db.calls if "UPDATE contracts SET status='disputed'" in s)
    assert params.get("grace_h") == 30, (sql, params)


def test_the_guild_reminder_says_the_grace(monkeypatch):
    from agentvault_registry.background_tasks import guild_order_reaper as gr
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import deadline_grace
    sent = []

    async def owners(type_key, dids, **kw):
        sent.append((type_key, tuple(dids), kw.get("message")))

    async def claim(key, ttl):
        return True

    async def thread(*a, **k):
        sent.append(("thread", a[0], a[3]))
    monkeypatch.setattr(push_notify, "notify_agent_owners", owners)
    monkeypatch.setattr(push_notify, "claim_once", claim)
    monkeypatch.setattr(gr, "_tell_the_agent", thread)
    monkeypatch.setattr(deadline_grace, "grace_hours", lambda: 24)
    when = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)
    rows = [{"id": "gwo_1", "title": "Port the docs", "status": "awarded", "poster_did": "did:p", "worker_did": "did:w",
             "deadline": when}]
    monkeypatch.setattr(gr, "AsyncSessionLocal", lambda: _Db([("FROM guild_work_orders", _Result(rows))]))
    assert asyncio.run(gr.remind_deadlines()) == 1
    push, mine = sent
    assert "a day after" in push[2] and "an hour after" not in push[2]
    assert mine[0] == "thread" and mine[2] == push[2]          # both reminders say the same, the agent's thread too


# ── 17: the work deadline at the award ───────────────────────────────────────────────────────────────────────────────
def _award(monkeypatch, eta, posted_deadline):
    from agentvault_registry.routers import guild
    order = {"id": "gwo_a", "poster_did": "did:p", "status": "open", "title": "Port the docs", "bounty": "10",
             "currency": "SBXB", "deadline": posted_deadline}
    bid = {"id": 7, "bidder_did": "did:w", "status": "open", "on_behalf_of_org_id": None, "home_registry_url": None,
           "payee_did_hint": None, "eta_seconds": eta}
    work_deadline = max(posted_deadline, T_AWARD + dt.timedelta(seconds=eta)) if eta else posted_deadline
    db = _Db([("FROM guild_bids WHERE id=:b", _Result([bid])),
              ("SET status='awarded'", _Result([{"deadline": work_deadline}], rowcount=1)),
              ("RETURNING bidder_did", _Result([]))])
    told, hooks = [], []

    async def load(db, oid):
        return dict(order)

    async def nothing(*a, **k):
        return None

    async def owners(type_key, dids, **kw):
        told.append((type_key, kw.get("message")))
    monkeypatch.setattr(guild, "_require_enabled", lambda: None)
    monkeypatch.setattr(guild, "_load", load)
    monkeypatch.setattr(guild, "_refund_all_stakes", nothing)
    monkeypatch.setattr(guild, "_audit", nothing)

    async def seq(db, oid):
        return 3
    monkeypatch.setattr(guild, "_next_seq", seq)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(guild, "_notify_owners", lambda *a, **k: None)
    monkeypatch.setattr(guild, "_guild_webhook", lambda kind, dids, data: hooks.append(data))
    monkeypatch.setattr(guild.guild_contract_mirror, "sync_from_order", nothing)
    from agentvault_registry.background_tasks import push_notify
    monkeypatch.setattr(push_notify, "notify_agent_owners", owners)

    async def go():
        r = await guild.award("gwo_a", guild.AwardIn(bid_id=7), types.SimpleNamespace(did="did:p"), db)
        await asyncio.sleep(0)          # the post-commit notice task
        return r
    return asyncio.run(go()), db, told, hooks, work_deadline


def test_the_award_sets_the_work_deadline_from_the_winning_bids_eta(monkeypatch):
    posted = T_AWARD + dt.timedelta(hours=2)
    r, db, told, hooks, want = _award(monkeypatch, eta=3 * 86400, posted_deadline=posted)
    claim_sql, claim_params = next((s, p) for s, p in db.calls if "SET status='awarded'" in s)
    assert "GREATEST(" in claim_sql and "RETURNING deadline" in claim_sql
    assert claim_params["eta"] == 3 * 86400
    assert r["work_deadline"] == want.isoformat()
    assert hooks and hooks[0]["work_deadline"] == want.isoformat()
    assert told and "due 2026-11-11 12:00 UTC" in told[0][1], told


def test_an_eta_inside_the_posting_deadline_keeps_the_deadline(monkeypatch):
    posted = T_AWARD + dt.timedelta(days=5)
    r, *_rest, want = _award(monkeypatch, eta=3600, posted_deadline=posted)
    assert want == posted and r["work_deadline"] == posted.isoformat()


def test_a_bid_with_no_eta_keeps_the_order_deadline(monkeypatch):
    posted = T_AWARD + dt.timedelta(days=1)
    r, db, *_rest = _award(monkeypatch, eta=None, posted_deadline=posted)
    _sql, params = next((s, p) for s, p in db.calls if "SET status='awarded'" in s)
    assert params["eta"] is None and r["work_deadline"] == posted.isoformat()


def test_the_reapers_read_one_rule():
    from agentvault_registry.background_tasks import contract_reaper, guild_order_reaper
    assert "grace_hours()" in inspect.getsource(guild_order_reaper._sweep_once)
    assert "grace_hours()" in inspect.getsource(contract_reaper._sweep_deadline_disputes)
    assert 'os.getenv("CONTRACT_DEADLINE_GRACE_HOURS"' not in inspect.getsource(contract_reaper._sweep_deadline_disputes)
