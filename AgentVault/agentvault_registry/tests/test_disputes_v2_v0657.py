"""V0657 (a), session-code 2026-11-06: disputes v2, the backend (order gwo_b16c7d6b52f7e48b825e1264; the discovery: room
seq 1441, disputes_v2_discovery_2026-11-06.md; the Commander's approval: room seq 1409, 1473, 1482).

What a ruler decided blind before, and what each test pins:
- item 1, one settlement authority: a ruling on a record about a Guild order splits the order's escrow BEFORE the
  ruling is written (a failed split writes no ruling), and the Guild's own resolve closes the order's record;
- item 2: no wallet compensation for a dispute about an escrow, and none from an amount in free-form evidence (only the
  complainant's explicit claim);
- items 5, 10, 12, 4: the ruling keeps who ruled and why; every filing path says why the dispute opened and who filed
  it; the parties and the rulers are told when one opens;
- item 11: a dispute the system filed has outcome rules of its own (nobody accused anybody);
- items 3, 7, 8, 9: the ruler's queue, the preview, the record's evidence and the parties by name;
- the correction rail: the old ruling's reputation and enforcement effects reversed, why kept, no money moved.

Every case runs the real functions over a recording fake database and stubs only the money rails and the notices.
RED on origin/v0656/cut (9715878984) for every case but the controls (test_control_*), which pass on both trees.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from decimal import Decimal

import pytest
from fastapi import HTTPException

POSTER = "did:theprotocol:eu.test:poster"
WORKER = "did:theprotocol:eu.test:worker"
OID = "gwo_d1spute0000000000000001"


# ── a recording fake database ───────────────────────────────────────────────────────────────────────────────────────
class _Result:
    def __init__(self, rows=(), rowcount=None, scalar=None, obj=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount
        self._scalar = scalar
        self._obj = obj

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar(self):
        if self._scalar is not None:
            return self._scalar
        r = self.first()
        if r is None:
            return None
        return r[0] if isinstance(r, (tuple, list)) else r

    def scalar_one_or_none(self):
        return self._obj

    def scalar_one(self):
        assert self._obj is not None, "no row"
        return self._obj

    def scalars(self):
        return self


class _Db:
    def __init__(self, handlers=()):
        self.handlers = list(handlers)
        self.calls = []
        self.added = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, params or {}))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, params or {}) if callable(res) else res
        return _Result([], rowcount=0)

    async def commit(self):
        self.calls.append(("COMMIT", {}))

    async def rollback(self):
        self.calls.append(("ROLLBACK", {}))

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None

    def add(self, obj):
        self.added.append(obj)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _dispute(**kw):
    base = dict(id=12, status="OPEN", ruling=None, complainant_did=POSTER, defendant_did=WORKER, evidence=[],
                contract_id=None, contract_ref=None, guild_order_id=None, reason=None, filed_by=None,
                amount_claimed=None, outcome=None, ruled_by=None, ruled_at=None, ruling_note=None,
                created_at=None, updated_at=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _run(coro):
    return asyncio.run(coro)


# ── item 11: a system-filed dispute's own outcome rules ─────────────────────────────────────────────────────────────
def _reputation_calls(monkeypatch, dispute):
    from agentvault_registry.core import reputation_manager as rm
    calls = []

    async def fake_update(db, did, change, reason):
        calls.append((did, change))
        return 50

    async def no_trust(*a, **k):
        return None
    monkeypatch.setattr(rm, "update_reputation", fake_update)
    monkeypatch.setattr(rm.local_trust_updater, "on_dispute_resolved", no_trust)
    _run(rm.record_dispute_outcome(_Db([("reputation_score", _Result(scalar=40))]), dispute))
    return calls


def test_a_ruling_for_the_worker_on_a_system_filed_dispute_costs_the_poster_nothing(monkeypatch):
    """The reaper accused nobody: before V0657 this marked the poster -10 'false accusation'."""
    calls = _reputation_calls(monkeypatch, _dispute(ruling="IN_FAVOR_OF_DEFENDANT", filed_by="system",
                                                    reason="deadline_missed"))
    assert calls == [(WORKER, 2)]


def test_a_stuck_payout_ruled_for_the_poster_costs_the_worker_nothing(monkeypatch):
    calls = _reputation_calls(monkeypatch, _dispute(ruling="IN_FAVOR_OF_COMPLAINANT", filed_by="system",
                                                    reason="stuck_payout"))
    assert calls == []


def test_a_system_filed_dismissal_costs_nobody(monkeypatch):
    calls = _reputation_calls(monkeypatch, _dispute(ruling="DISMISSED", filed_by="system", reason="poster_silent"))
    assert calls == []


def test_a_missed_deadline_ruled_for_the_poster_still_costs_the_worker(monkeypatch):
    calls = _reputation_calls(monkeypatch, _dispute(ruling="IN_FAVOR_OF_COMPLAINANT", filed_by="system",
                                                    reason="deadline_missed"))
    assert calls == [(WORKER, -10)]


@pytest.mark.parametrize("ruling,expected", [
    ("IN_FAVOR_OF_COMPLAINANT", [(WORKER, -10), (POSTER, 2)]),
    ("IN_FAVOR_OF_DEFENDANT", [(POSTER, -10), (WORKER, 2)]),
    ("DISMISSED", [(POSTER, -3), (WORKER, -3)]),
])
def test_control_a_partys_filing_keeps_its_rules(monkeypatch, ruling, expected):
    assert _reputation_calls(monkeypatch, _dispute(ruling=ruling)) == expected


# ── item 2: no wallet compensation from free-form evidence, nor for an escrow dispute ───────────────────────────────
def _compensation(monkeypatch, dispute, evidence_amount=50):
    from agentvault_registry.crud import crud_disputes as cd
    moved = []

    async def evidence_says(db, dispute_id):
        return evidence_amount

    async def local(db, dispute, ruling, defendant, amount, result):
        moved.append(amount)
        return {**result, "applied": True, "amount": amount}
    monkeypatch.setattr(cd, "extract_disputed_amount", evidence_says, raising=False)
    monkeypatch.setattr(cd, "_process_local_compensation", local)
    agent = types.SimpleNamespace(did=WORKER)
    out = _run(cd.process_compensation(_Db([("FROM agents", _Result(obj=agent))]), dispute, "IN_FAVOR_OF_COMPLAINANT"))
    return moved, out


def test_an_amount_in_evidence_moves_no_wallet_money(monkeypatch):
    moved, out = _compensation(monkeypatch, _dispute())
    assert moved == [] and out["applied"] is False


def test_a_dispute_about_a_guild_order_moves_no_wallet_money(monkeypatch):
    moved, out = _compensation(monkeypatch, _dispute(guild_order_id=OID, amount_claimed=Decimal("7")))
    assert moved == [] and "escrow" in (out.get("reason") or "")


def test_the_complainants_explicit_claim_is_what_moves(monkeypatch):
    moved, _ = _compensation(monkeypatch, _dispute(amount_claimed=Decimal("7")), evidence_amount=50)
    assert moved == [7]


# ── item 1: a ruling on a Guild order's record settles its escrow first ─────────────────────────────────────────────
@pytest.fixture
def ruling_route(monkeypatch):
    """The ruling route with its collaborators recorded: the Guild split, the ruling, the wallet compensation, the
    contract spine. The order of calls is kept."""
    from agentvault_registry.routers import admin
    from agentvault_registry.crud import crud_disputes as cd
    from agentvault_registry.background_tasks import reactor_helpers as rh
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import contract_settlement as cs
    state = {"dispute": _dispute(guild_order_id=OID, filed_by="system", reason="deadline_missed"),
             "order": {"id": OID, "status": "disputed", "bounty": Decimal("25"), "currency": "ECU",
                       "poster_did": POSTER, "worker_did": WORKER, "deliverable": {"text": "done"},
                       "submitted_at": object(), "dispute_id": "12"},
             "split_raises": None}
    log = []

    async def get_dispute(db, dispute_id):
        return state["dispute"]

    async def update_ruling(db, dispute_id, ruling, **kw):
        log.append(("ruling", ruling, kw))
        d = state["dispute"]
        d.status, d.ruling = "CLOSED", ruling
        d.ruled_by, d.ruling_note = kw.get("ruled_by"), kw.get("note")
        d.updated_at = type("T", (), {"isoformat": lambda self: "2026-11-06T00:00:00+00:00"})()
        d.ruled_at = d.updated_at
        d.outcome = {"money": kw.get("money")}
        return d

    async def compensation(db, dispute, ruling):
        log.append(("wallet", ruling))
        return {"applied": False, "amount": 0}

    async def spine(db, dispute, ruling):
        log.append(("contract", ruling))
        return None

    async def nothing(*a, **k):
        return 0

    async def linked(db, dispute):
        return dict(state["order"]) if getattr(dispute, "guild_order_id", None) else None

    async def split(db, o, share, **kw):
        log.append(("split", str(share), kw.get("actor")))
        if state["split_raises"]:
            raise state["split_raises"]
        return {"ok": True, "worker_share": str(share)}
    monkeypatch.setattr(cd, "get_dispute_by_id", get_dispute)
    monkeypatch.setattr(cd, "update_dispute_ruling", update_ruling)
    monkeypatch.setattr(cd, "process_compensation", compensation)
    monkeypatch.setattr(cs, "settle_linked_contract_for_ruling", spine)
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", nothing)
    monkeypatch.setattr(push_notify, "notify_agent_owners", nothing)
    try:
        from agentvault_registry.services import dispute_settlement as ds
        monkeypatch.setattr(ds, "linked_guild_order", linked)
    except ImportError:
        pass
    from agentvault_registry.routers import guild
    monkeypatch.setattr(guild, "split_disputed_order", split, raising=False)
    admin_dev = types.SimpleNamespace(id=6, email="ruler@example.invalid")

    def rule(body=None, query=None):
        kw = {"ruling": query}
        if body is not None:      # the control calls as the MCP tool does (a query parameter only), on either tree
            kw["body"] = body
        async def go():
            return await admin.update_dispute_ruling_endpoint(
                12, db=_Db([("FROM agents", _Result(obj=None))]), current_admin=admin_dev, **kw)
        return asyncio.run(go())
    return types.SimpleNamespace(rule=rule, log=log, state=state, admin=admin)


def _body(admin, **kw):
    return admin.DisputeRulingIn(**kw)


def test_a_ruling_for_the_worker_splits_the_order_to_the_worker_before_the_ruling(ruling_route):
    r = ruling_route
    out = r.rule(body=_body(r.admin, ruling="IN_FAVOR_OF_DEFENDANT", note="It delivered on time."))
    kinds = [e[0] for e in r.log]
    assert kinds == ["split", "ruling"], r.log
    assert r.log[0][1] == "1" and r.log[0][2] == "admin:6"
    assert r.log[1][2]["ruled_by"] == 6 and r.log[1][2]["note"] == "It delivered on time."
    assert out["compensation"]["applied"] is False and out["ruling_note"] == "It delivered on time."


def test_a_ruling_for_the_poster_refunds_the_poster_and_a_split_is_the_rulers(ruling_route):
    r = ruling_route
    r.rule(body=_body(r.admin, ruling="IN_FAVOR_OF_COMPLAINANT"))
    assert r.log[0][:2] == ("split", "0")
    r.log.clear()
    r.state["dispute"] = _dispute(guild_order_id=OID)
    r.rule(body=_body(r.admin, ruling="DISMISSED", worker_share=Decimal("0.4")))
    assert r.log[0][:2] == ("split", "0.4")


def test_a_failed_split_writes_no_ruling(ruling_route):
    r = ruling_route
    r.state["split_raises"] = HTTPException(502, detail="park failed; order stays disputed")
    with pytest.raises(HTTPException) as e:
        r.rule(body=_body(r.admin, ruling="IN_FAVOR_OF_DEFENDANT"))
    assert e.value.status_code == 502
    assert [x[0] for x in r.log] == ["split"], "no ruling is written when its money did not move"


def test_an_order_settled_elsewhere_moves_nothing_and_the_ruling_still_closes_the_record(ruling_route):
    r = ruling_route
    r.state["order"]["status"] = "settled"
    out = r.rule(body=_body(r.admin, ruling="IN_FAVOR_OF_DEFENDANT"))
    assert [x[0] for x in r.log] == ["ruling"], r.log
    assert "settled already" in out["compensation"]["guild"]["split"]


def test_an_order_whose_settlement_is_in_flight_is_refused_409_and_writes_no_ruling(ruling_route):
    """session-lead's review (room seq 1598): an order in 'resolving' is a settlement in flight (another split holds it
    and may be moving the money now), never one that is over: 409, and neither a split nor a ruling."""
    r = ruling_route
    r.state["order"]["status"] = "resolving"
    with pytest.raises(HTTPException) as e:
        r.rule(body=_body(r.admin, ruling="IN_FAVOR_OF_DEFENDANT"))
    assert e.value.status_code == 409 and "in flight" in str(e.value.detail)
    assert r.log == [], r.log


def test_a_worker_share_on_a_dispute_about_no_order_is_refused(ruling_route):
    r = ruling_route
    r.state["dispute"] = _dispute()
    with pytest.raises(HTTPException) as e:
        r.rule(body=_body(r.admin, ruling="DISMISSED", worker_share=Decimal("0.5")))
    assert e.value.status_code == 400


def test_control_the_query_parameter_still_rules_and_a_plain_dispute_runs_wallet_compensation(ruling_route):
    r = ruling_route
    r.state["dispute"] = _dispute()
    r.rule(query="IN_FAVOR_OF_COMPLAINANT")
    assert [x[0] for x in r.log] == ["ruling", "contract", "wallet"], r.log


# ── item 1: the Guild's own resolve closes the order's record ───────────────────────────────────────────────────────
@pytest.fixture
def resolve(monkeypatch):
    from agentvault_registry.routers import guild
    from agentvault_registry.crud import crud_disputes as cd
    from agentvault_registry.background_tasks import push_notify
    order = {"id": OID, "poster_did": POSTER, "worker_did": WORKER, "title": "Fix the board", "bounty": "25",
             "currency": "ECU", "fee_bps": 250, "status": "disputed", "dispute_id": "12",
             "worker_home_registry": None, "payee_did": None}
    log = []

    async def load(db, oid):
        return dict(order)

    async def payout(db, did, amount, oid, leg, *a, **k):
        log.append(("payout", did, str(amount), leg))

    async def stake(*a, **k):
        return None

    async def nothing(*a, **k):
        return None

    async def get_dispute(db, dispute_id):
        return _dispute(id=int(dispute_id), guild_order_id=OID)

    async def update_ruling(db, dispute_id, ruling, **kw):
        log.append(("ruling", dispute_id, ruling, kw.get("ruled_by")))
        return _dispute(id=dispute_id, status="CLOSED", ruling=ruling)

    async def compensation(*a, **k):
        log.append(("wallet",))
        return {"applied": False}
    monkeypatch.setattr(guild, "_load", load)
    monkeypatch.setattr(guild.guild_escrow, "escrow_payout", payout)
    monkeypatch.setattr(guild, "_resolve_worker_stake", stake)
    monkeypatch.setattr(guild, "_tr_touch", nothing)
    monkeypatch.setattr(guild.guild_contract_mirror, "sync_from_order", nothing)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(cd, "get_dispute_by_id", get_dispute)
    monkeypatch.setattr(cd, "update_dispute_ruling", update_ruling)
    monkeypatch.setattr(cd, "process_compensation", compensation)
    monkeypatch.setattr(push_notify, "notify_agent_owners", nothing)
    dev = types.SimpleNamespace(id=6, is_admin=True)
    monkeypatch.setattr(guild, "_require_admin", lambda d: None)

    def run(share):
        db = _Db([("SET status='resolving'", _Result(rowcount=1)), ("COALESCE(MAX(seq)", _Result(scalar=3))])
        return asyncio.run(guild.admin_resolve(OID, guild.DisputeResolveIn(worker_share=share, note="split it"),
                                               dev=dev, db=db))
    return types.SimpleNamespace(run=run, log=log)


@pytest.mark.parametrize("share,ruling", [(1.0, "IN_FAVOR_OF_DEFENDANT"), (0.0, "IN_FAVOR_OF_COMPLAINANT"),
                                          (0.5, "DISMISSED")])
def test_the_guild_resolve_closes_the_orders_record_with_the_ruling_its_split_implies(resolve, share, ruling):
    resolve.run(share)
    rulings = [e for e in resolve.log if e[0] == "ruling"]
    assert rulings == [("ruling", 12, ruling, 6)], resolve.log
    assert ("wallet",) not in resolve.log, "the split is the settlement: no wallet compensation"


def test_control_the_guild_resolve_still_pays_the_split(resolve):
    resolve.run(0.4)
    pays = [e for e in resolve.log if e[0] == "payout"]
    assert pays == [("payout", WORKER, "10.0000000000", "split_worker"), ("payout", POSTER, "15.0000000000", "split_poster")]


# ── items 10, 19, 12: every filing path says why and who; the deadline sweep claims first ───────────────────────────
def _record_filing(monkeypatch):
    from agentvault_registry.crud import crud_disputes as cd
    filed, log = [], []

    async def create(db, complainant_did, defendant_did, *a, **kw):
        filed.append(kw)
        log.append("file")
        return types.SimpleNamespace(id=31)

    async def evidence(db, dispute_id, submitter, data):
        filed.append({"evidence": (dispute_id, submitter, data)})
    monkeypatch.setattr(cd, "create_dispute", create)
    monkeypatch.setattr(cd, "add_evidence_to_dispute", evidence)
    return filed, log


def test_the_deadline_sweep_claims_the_order_first_and_files_a_linked_system_record(monkeypatch):
    from agentvault_registry.background_tasks import guild_order_reaper as reaper
    filed, log = _record_filing(monkeypatch)

    def claim(sql, p):
        log.append("claim")
        return _Result(rowcount=1)
    db = _Db([("status='open'", _Result([])),
              ("WHERE status='awarded' AND deadline", _Result([{"id": OID, "poster_did": POSTER, "worker_did": WORKER}])),
              ("SET status='disputed'", claim),
              ("COALESCE(MAX(seq)", _Result(scalar=4))])

    async def zero(db):
        return 0
    monkeypatch.setattr(reaper, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(reaper, "_sweep_stuck_money_states", zero)
    monkeypatch.setattr(reaper, "_sweep_abandoned_submitted", zero)
    monkeypatch.setattr("agentvault_registry.routers.guild._emit", lambda *a, **k: None)
    asyncio.run(reaper._sweep_once())
    assert log[:2] == ["claim", "file"], log
    assert filed[0] == {"guild_order_id": OID, "reason": "deadline_missed", "filed_by": "system"}, filed
    events = [p for s, p in db.calls if "INSERT INTO guild_order_events" in s]
    assert events and "deadline_missed" in str(events[0]), "the sweep writes the order's 'disputed' event"


@pytest.mark.parametrize("note,reason", [({"reason": "submitted_timeout", "days": 7}, "poster_silent"),
                                         ({"stuck": "settling", "xreg": True}, "stuck_payout")])
def test_the_reapers_other_flags_say_why(monkeypatch, note, reason):
    from agentvault_registry.background_tasks import guild_order_reaper as reaper
    filed, _ = _record_filing(monkeypatch)
    monkeypatch.setattr("agentvault_registry.routers.guild._emit", lambda *a, **k: None)
    db = _Db([("SET status='disputed'", _Result(rowcount=1)), ("COALESCE(MAX(seq)", _Result(scalar=2))])
    assert asyncio.run(reaper._flag_disputed(db, OID, POSTER, WORKER, note, "submitted"))
    assert filed[0] == {"guild_order_id": OID, "reason": reason, "filed_by": "system"}


def test_a_posters_reject_files_a_linked_party_record_with_its_reason_as_the_first_statement(monkeypatch):
    from agentvault_registry.routers import guild
    filed, _ = _record_filing(monkeypatch)
    order = {"id": OID, "poster_did": POSTER, "worker_did": WORKER, "status": "submitted", "title": "t",
             "worker_home_registry": None}

    async def load(db, oid):
        return dict(order)

    async def nothing(*a, **k):
        return None
    monkeypatch.setattr(guild, "_load", load)
    monkeypatch.setattr(guild, "_require_enabled", lambda: None)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(guild, "_guild_webhook", lambda *a, **k: None)
    monkeypatch.setattr(guild.guild_contract_mirror, "sync_from_order", nothing)
    db = _Db([("SET status='disputed'", _Result(rowcount=1)), ("COALESCE(MAX(seq)", _Result(scalar=5))])
    agent = types.SimpleNamespace(did=POSTER)
    asyncio.run(guild.verify(OID, guild.VerifyIn(accept=False, feedback="The tests fail on main."),
                             request=None, agent=agent, db=db))
    assert filed[0] == {"guild_order_id": OID, "reason": "rejected_by_poster", "filed_by": "party"}, filed
    assert filed[1]["evidence"][1] == POSTER and filed[1]["evidence"][2]["content"] == "The tests fail on main."


# ── polish item 13: the day-before reminder reaches the agent itself, not only its owners ───────────────────────────
def test_the_deadline_reminder_is_posted_in_the_agents_own_guild_thread(monkeypatch):
    from datetime import datetime, timezone
    from agentvault_registry.background_tasks import guild_order_reaper as reaper
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import guild_thread
    deadline = datetime(2026, 11, 7, 17, 0, tzinfo=timezone.utc)
    rows = [{"id": OID, "title": "Fix the board", "status": "awarded", "poster_did": POSTER, "worker_did": WORKER,
             "deadline": deadline},
            {"id": "gwo_open", "title": "Open one", "status": "open", "poster_did": POSTER, "worker_did": None,
             "deadline": deadline}]
    posted, pushed = [], []

    async def claim(key, ttl):
        return True

    async def owners(type_key, dids, **kw):
        pushed.append(list(dids))
        return 1

    async def notice(db, agent_did, body, client_ref):
        posted.append((agent_did, body, client_ref))
        return {}
    monkeypatch.setattr(reaper, "AsyncSessionLocal", lambda: _Db([("FROM guild_work_orders", _Result(rows))]))
    monkeypatch.setattr(push_notify, "claim_once", claim)
    monkeypatch.setattr(push_notify, "notify_agent_owners", owners)
    monkeypatch.setattr(guild_thread, "post_notice", notice, raising=False)
    monkeypatch.setattr("agentvault_registry.database.get_db_context", lambda: _Db())
    assert asyncio.run(reaper.remind_deadlines()) == 2
    assert pushed == [[WORKER], [POSTER]], "the owners' push stands"
    assert [(a, r) for a, _, r in posted] == [(WORKER, f"gdl-{OID}-{int(deadline.timestamp())}"),
                                             (POSTER, f"gdl-gwo_open-{int(deadline.timestamp())}")], posted
    assert posted[0][1].startswith(f"Order {OID}: ") and "submit the work" in posted[0][1]


# ── item 12 and 4: who hears that a dispute opened ──────────────────────────────────────────────────────────────────
def test_opening_a_dispute_tells_the_defendant_the_rulers_and_a_complainant_who_did_not_file(monkeypatch):
    from agentvault_registry.crud import crud_disputes as cd
    from agentvault_registry.background_tasks import push_notify
    told = []

    async def owners(type_key, dids, **kw):
        told.append((type_key, list(dids), kw.get("message")))
        return 1

    async def devs(type_key, ids, **kw):
        told.append((type_key, list(ids), kw.get("message")))
        return 1

    async def rulers(db):
        return [6]
    monkeypatch.setattr(push_notify, "notify_agent_owners", owners)
    monkeypatch.setattr(push_notify, "notify", devs)
    monkeypatch.setattr(cd, "_rulers", rulers, raising=False)
    monkeypatch.setattr("agentvault_registry.database.AsyncSessionLocal", lambda: _Db())
    asyncio.run(cd.notify_dispute_opened(31, POSTER, WORKER, "deadline_missed", "system"))
    assert [t[0] for t in told] == ["dispute.filed_against_you", "dispute.opened", "dispute.desk"], told
    assert told[0][1] == [WORKER] and told[1][1] == [POSTER] and told[2][1] == [6]
    assert "deadline" in told[0][2] and "evidence" in told[0][2]
    told.clear()
    asyncio.run(cd.notify_dispute_opened(32, POSTER, WORKER, "filed_by_party", "party"))
    assert [t[0] for t in told] == ["dispute.filed_against_you", "dispute.desk"], "the complainant filed it: it knows"


def test_create_dispute_keeps_why_and_who_and_schedules_the_notices(monkeypatch):
    from agentvault_registry.crud import crud_disputes as cd
    from agentvault_registry.background_tasks import reactor_helpers as rh
    seen = []

    async def told(*a, **k):
        seen.append(a)

    async def nothing(*a, **k):
        return None
    monkeypatch.setattr(cd, "notify_dispute_opened", told, raising=False)
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", nothing)
    db = _Db()

    async def go():
        d = await cd.create_dispute(db, POSTER, WORKER, guild_order_id=OID, reason="deadline_missed",
                                    filed_by="system", amount_claimed=Decimal("3"))
        await asyncio.sleep(0)
        return d
    d = asyncio.run(go())
    assert (d.guild_order_id, d.reason, d.filed_by, d.amount_claimed) == (OID, "deadline_missed", "system", Decimal("3"))
    assert seen and seen[0][1:] == (POSTER, WORKER, "deadline_missed", "system")


# ── item 7: the preview, from the rules the ruling applies ──────────────────────────────────────────────────────────
def test_the_preview_says_who_gets_what_each_reputation_change_and_the_enforcement_step(monkeypatch):
    from agentvault_registry.services import dispute_settlement as ds
    from agentvault_registry.services import enforcement_engine as ee
    order = {"id": OID, "status": "disputed", "bounty": Decimal("25"), "currency": "ECU", "worker_did": WORKER,
             "deliverable": None, "submitted_at": None}

    async def linked(db, dispute):
        return dict(order)

    async def names(db, dids):
        return {POSTER: "session-lead", WORKER: "session-tester"}

    async def stake(db, o):
        return Decimal("5")

    class _Engine:
        async def plan_dispute_outcome(self, db, did, amount):
            return {"offense_count_before": 0, "escalation_level": 1, "action": "warn", "slash_amount": None,
                    "pause_days": 0, "suspends": False}
    monkeypatch.setattr(ds, "linked_guild_order", linked)
    monkeypatch.setattr(ds, "_names", names)
    monkeypatch.setattr(ds, "held_stake", stake)
    monkeypatch.setattr(ee, "get_enforcement_engine", lambda: _Engine())
    d = _dispute(guild_order_id=OID, filed_by="system", reason="deadline_missed")
    p = asyncio.run(ds.preview(_Db(), d, "IN_FAVOR_OF_COMPLAINANT"))
    assert p["money"]["worker_gets"] == "0E-10" or Decimal(p["money"]["worker_gets"]) == 0
    assert Decimal(p["money"]["poster_gets"]) == 25 and p["money"]["stake"]["goes_to"] == "the poster (slashed)"
    assert p["reputation"] == [{"did": WORKER, "name": "session-tester", "change": -10,
                                "why": "missed the deadline (the ruling)"}]
    assert p["enforcement"]["action"] == "warn" and p["enforcement"]["agent_name"] == "session-tester"
    p2 = asyncio.run(ds.preview(_Db(), d, "DISMISSED"))
    assert Decimal(p2["money"]["worker_gets"]) == 0, "nothing handed in: a dismissal refunds the poster"
    assert p2["reputation"] == [] and p2["enforcement"] is None


# ── the correction rail ─────────────────────────────────────────────────────────────────────────────────────────────
class _Store:
    """What a correction touches, as committed: the record, the agents, the enforcement actions, the corrections; and
    the row locks a Postgres UPDATE or SELECT ... FOR UPDATE takes until its transaction ends."""

    def __init__(self, dispute, scores, actions):
        self.dispute = dispute
        self.scores = dict(scores)
        self.agents = {did: {"offense_count": 1, "rewards_paused_until": None, "enforcement_status": "active",
                             "enforcement_level": 1} for did in scores}
        self.actions = {a.id: a for a in actions}
        self.corrections = []
        self.locks = {}
        self.trust = []


class _Session:
    """One request's session over the store: reads see what is committed; its writes wait for its commit; a lock it
    takes is held until its commit or rollback, and another session that wants the row waits (as Postgres makes it)."""

    def __init__(self, store, fail_effect=None):
        self.st = store
        self.staged = []
        self.held = set()
        self.objs = []
        self.fail_effect = fail_effect
        self.reversing = set()      # the actions this session's open transaction reversed (its own reads see it)

    async def _lock(self, key):
        while self.st.locks.get(key) not in (None, self):
            await asyncio.sleep(0)
        self.st.locks[key] = self
        self.held.add(key)

    def _release(self):
        for k in self.held:
            if self.st.locks.get(k) is self:
                del self.st.locks[k]
        self.held = set()

    async def execute(self, stmt, params=None):
        await asyncio.sleep(0)
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        st = self.st
        if self.fail_effect and self.fail_effect in sql:
            raise RuntimeError("the database went away mid-correction")
        if sql.startswith("UPDATE disputes SET ruling"):
            await self._lock("dispute")
            d = st.dispute
            ok = (d.status == "CLOSED" and d.ruling == p["old"]
                  and not any(c.status == "applying" for c in st.corrections if c.dispute_id == d.id))
            if ok:
                self.staged.append(lambda: setattr(d, "ruling", p["new"]))
            return _Result(rowcount=1 if ok else 0)
        if "FROM dispute_corrections WHERE dispute_id" in sql and "applying" in sql:
            ids = [c.id for c in st.corrections if c.dispute_id == p["d"] and c.status == "applying"]
            return _Result([(i,) for i in ids])
        if "FROM dispute_corrections" in sql:          # the step's SELECT ... FOR UPDATE, or finish's read
            if "FOR UPDATE" in sql:
                await self._lock("correction")
            return _Result(obj=st.corrections[-1] if st.corrections else None)
        if "FROM disputes" in sql:                     # each session reads its own copy, as of now; the close locks it
            if "FOR UPDATE" in sql:
                await self._lock("dispute")
                return _Result(obj=st.dispute)
            return _Result(obj=types.SimpleNamespace(**vars(st.dispute)))
        if "FROM enforcement_actions" in sql:
            return _Result([a for a in st.actions.values() if a.status in ("executed", "pending_approval")])
        if sql.startswith("SELECT reputation_score FROM agents"):
            await self._lock("agent:" + p["d"])
            return _Result(scalar=st.scores.get(p["d"]))
        if sql.startswith("UPDATE agents SET reputation_score"):
            self.staged.append(lambda: st.scores.__setitem__(p["d"], p["s"]))
            return _Result(rowcount=1)
        if sql.startswith("UPDATE enforcement_actions SET status = 'reversed'"):
            a = st.actions.get(p["id"])
            ok = a is not None and a.status in ("executed", "pending_approval")
            if ok:
                self.reversing.add(a.id)
                self.staged.append(lambda: (setattr(a, "status", "reversed"), setattr(a, "rejected_reason", p["why"])))
            return _Result(rowcount=1 if ok else 0)
        if sql.startswith("SELECT offense_count"):
            await self._lock("agent:" + p["d"])
            g = st.agents[p["d"]]
            return _Result([(g["offense_count"], g["rewards_paused_until"], g["enforcement_status"])])
        if sql.startswith("UPDATE agents SET offense_count"):
            def _w():
                g = st.agents[p["d"]]
                g["offense_count"], g["enforcement_level"] = p["o"], p["l"]
                if p["lift"]:
                    g["rewards_paused_until"] = None
            self.staged.append(_w)
            return _Result(rowcount=1)
        raise AssertionError(f"the fake was not told about: {sql}")

    def add(self, obj):
        self.objs.append(obj)

    async def commit(self):
        await asyncio.sleep(0)
        for w in self.staged:
            w()
        for o in self.objs:
            if o not in self.st.corrections:
                o.id = len(self.st.corrections) + 1
                self.st.corrections.append(o)
        self.staged, self.objs, self.reversing = [], [], set()
        self._release()

    async def rollback(self):
        self.staged, self.objs, self.reversing = [], [], set()
        self._release()

    async def flush(self):
        return None


@pytest.fixture
def correction(monkeypatch):
    """Dispute 1's shape (ruled for the poster before V0657, a warning on the worker that had delivered and was paid),
    over the store; the trust signal, the ledger and the notices recorded."""
    from agentvault_registry.services import dispute_correction as dc
    from agentvault_registry.services import enforcement_engine as ee
    from agentvault_registry.services import local_trust_updater as ltu
    from tests._doubles import StrictEmitter
    d = _dispute(id=1, status="CLOSED", ruling="IN_FAVOR_OF_COMPLAINANT", filed_by="system", reason="deadline_missed")
    action = types.SimpleNamespace(id="ea_1", agent_did=WORKER, action_type="warn", status="executed",
                                   escalation_level=1, amount=None, rejected_reason=None)
    store = _Store(d, {POSTER: 12, WORKER: 2}, [action])

    class _Engine:
        async def _load_policy(self, db):
            return {}

        async def _count_recent_offenses(self, db, did, policy):    # in the caller's transaction, as Postgres reads it
            return sum(1 for a in store.actions.values() if a.agent_did == did and a.status == "executed"
                       and a.id not in getattr(db, "reversing", ()))

    async def trust(db, **kw):
        store.trust.append(kw["ruling"])
    emitter = StrictEmitter()
    monkeypatch.setattr(ee, "get_enforcement_engine", lambda: _Engine())
    monkeypatch.setattr(ltu, "on_dispute_resolved", trust)
    monkeypatch.setattr("agentvault_registry.event_emitter.get_event_emitter", lambda: emitter)
    monkeypatch.setattr("agentvault_registry.background_tasks.push_notify.notify_agent_owners", _async_none)
    return types.SimpleNamespace(dc=dc, store=store, action=action, emitter=emitter, d=d)


NOTE = "It delivered and was paid; the record stayed open by mistake."


def test_correcting_dispute_ones_shape_reverses_its_reputation_and_its_warning_and_keeps_why(correction):
    """The correction to a ruling for the worker undoes the party rules of the time (-10 the worker, +2 the poster),
    reverses the warning, applies the corrected rule (system-filed: the worker +2, the poster nothing), keeps why and
    who on the record and the correction's row, tells the ledger once, and moves no money."""
    c = correction
    with pytest.raises(c.dc.CorrectionRefused):
        _run(c.dc.apply(_Session(c.store), 1, "IN_FAVOR_OF_DEFENDANT", note="short", corrected_by=6))
    out = _run(c.dc.apply(_Session(c.store), 1, "IN_FAVOR_OF_DEFENDANT", note=NOTE, corrected_by=6))
    assert c.store.scores == {WORKER: 2 + 10 + 2, POSTER: 12 - 2}, c.store.scores
    assert c.action.status == "reversed" and "delivered" in c.action.rejected_reason
    assert c.store.agents[WORKER]["offense_count"] == 0 and c.store.agents[WORKER]["enforcement_level"] == 0
    assert c.store.dispute.ruling == "IN_FAVOR_OF_DEFENDANT"
    corrected = c.store.dispute.outcome["corrected"]
    assert (corrected["from"], corrected["by"], corrected["note"]) == ("IN_FAVOR_OF_COMPLAINANT", 6, NOTE)
    assert c.store.dispute.outcome["reputation"][0]["after"] == 14
    corr = c.store.corrections[0]
    assert corr.status == "applied" and corr.note == NOTE and corr.to_ruling == "IN_FAVOR_OF_DEFENDANT"
    assert sorted(corr.steps) == ["apply_reputation:0", "close", "reverse_enforcement:ea_1", "reverse_reputation:0",
                                  "reverse_reputation:1", "trust_signal"], sorted(corr.steps)
    assert out["money"].startswith("none") and out["status"] == "applied"
    ev = c.emitter.assert_received("DisputeRulingCorrected")
    assert ev["data"]["from_ruling"] == "IN_FAVOR_OF_COMPLAINANT" and ev["data"]["to_ruling"] == "IN_FAVOR_OF_DEFENDANT"
    assert c.store.trust == ["IN_FAVOR_OF_DEFENDANT"]
    with pytest.raises(c.dc.CorrectionRefused):
        _run(c.dc.apply(_Session(c.store), 1, "IN_FAVOR_OF_DEFENDANT", note="a second time, the same ruling",
                        corrected_by=6))


def test_two_corrections_at_once_one_is_refused_409_and_every_change_is_made_once(correction):
    """session-lead's review (room seq 1597): two corrections sent at the same moment (a double click, a retry after a
    timeout) both read the old ruling. The record is claimed before any effect, so the second finds the ruling moved
    and is refused; the old ruling's reputation is reversed once and the corrected rule applied once."""
    c = correction

    async def both():
        return await asyncio.gather(
            c.dc.apply(_Session(c.store), 1, "IN_FAVOR_OF_DEFENDANT", note=NOTE, corrected_by=6),
            c.dc.apply(_Session(c.store), 1, "IN_FAVOR_OF_DEFENDANT", note=NOTE + " (again)", corrected_by=6),
            return_exceptions=True)
    results = _run(both())
    refused = [r for r in results if isinstance(r, c.dc.CorrectionInFlight)]
    done = [r for r in results if isinstance(r, dict)]
    assert len(refused) == 1 and len(done) == 1, results
    assert c.store.scores == {WORKER: 14, POSTER: 10}, c.store.scores
    assert len(c.store.corrections) == 1 and c.store.corrections[0].status == "applied"
    assert c.store.agents[WORKER]["offense_count"] == 0
    assert c.store.trust == ["IN_FAVOR_OF_DEFENDANT"]


def test_a_correction_that_fails_midway_stays_applying_and_is_finished_never_redone(correction):
    """A failure after the claim leaves the correction 'applying' with the steps it made on the record. Another
    correction is refused while it applies; finish() does the rest from the stored plan, and nothing is done twice."""
    c = correction
    with pytest.raises(RuntimeError):
        _run(c.dc.apply(_Session(c.store, fail_effect="UPDATE enforcement_actions"), 1, "IN_FAVOR_OF_DEFENDANT",
                        note=NOTE, corrected_by=6))
    corr = c.store.corrections[0]
    assert corr.status == "applying" and sorted(corr.steps) == ["reverse_reputation:0", "reverse_reputation:1"]
    assert c.store.scores == {WORKER: 12, POSTER: 10}, "the reversal made before the failure stands, once"
    assert c.action.status == "executed", "the failed step left nothing"
    with pytest.raises(c.dc.CorrectionInFlight) as e:
        _run(c.dc.apply(_Session(c.store), 1, "DISMISSED", note=NOTE, corrected_by=6))
    assert "finish it first" in str(e.value) and e.value.correction_id == corr.id
    out = _run(c.dc.finish(_Session(c.store), 1, corr.id))
    assert out["status"] == "applied" and corr.status == "applied"
    assert c.store.scores == {WORKER: 14, POSTER: 10}, c.store.scores
    assert c.action.status == "reversed" and c.store.agents[WORKER]["offense_count"] == 0
    with pytest.raises(c.dc.CorrectionRefused):
        _run(c.dc.finish(_Session(c.store), 1, corr.id))
    assert c.store.scores == {WORKER: 14, POSTER: 10}


async def _async_none(*a, **k):
    return None


def test_the_routes_exist_for_the_screen():
    from agentvault_registry.routers import admin
    paths = {(r.path, tuple(sorted(r.methods))) for r in admin.router.routes}
    for p, m in (("/api/v1/admin/disputes/queue", ("GET",)),
                 ("/api/v1/admin/disputes/queue/{kind}/{ref}/record", ("POST",)),
                 ("/api/v1/admin/disputes/{dispute_id}/preview", ("GET",)),
                 ("/api/v1/admin/disputes/{dispute_id}/correction-preview", ("GET",)),
                 ("/api/v1/admin/disputes/{dispute_id}/correct", ("POST",)),
                 ("/api/v1/admin/disputes/{dispute_id}/corrections/{correction_id}/finish", ("POST",))):
        assert (p, m) in paths, (p, sorted(paths))


# ── items 3, 8, 9: the queue and the record as a ruler reads them ───────────────────────────────────────────────────
def test_the_queue_lists_open_records_and_disputed_orders_and_contracts_without_one(monkeypatch):
    from agentvault_registry.services import dispute_queue as dq
    import agentvault_registry.services.dispute_parties as dp

    async def names(db, dids):
        return {POSTER: "session-lead", WORKER: "session-tester"}
    monkeypatch.setattr(dp, "names_for", names)
    db = _Db([
        ("FROM disputes d LEFT JOIN guild_work_orders", _Result([{
            "id": 1, "complainant_did": POSTER, "defendant_did": WORKER, "reason": "deadline_missed",
            "filed_by": "system", "guild_order_id": OID, "contract_ref": None, "contract_id": None,
            "amount_claimed": None, "created_at": None, "order_bounty": Decimal("25"), "order_currency": "ECU",
            "order_title": "Fix the board", "order_status": "disputed", "contract_title": None}, {
            "id": 7, "complainant_did": POSTER, "defendant_did": WORKER, "reason": "filed_by_party",
            "filed_by": "party", "guild_order_id": None, "contract_ref": None, "contract_id": None,
            "amount_claimed": Decimal("4"), "created_at": None, "order_bounty": None, "order_currency": None,
            "order_title": None, "order_status": None, "contract_title": None}])),
        ("FROM guild_work_orders o LEFT JOIN disputes", _Result([{
            "id": "gwo_orphan", "title": "Lost record", "poster_did": POSTER, "worker_did": WORKER, "bounty": 3,
            "currency": "ECU", "dispute_id": None, "created_at": None}])),
        ("FROM contracts c LEFT JOIN disputes", _Result([{
            "id": "ctr_late", "title": "Late work", "client_did": POSTER, "provider_did": WORKER, "currency": "ECU",
            "dispute_id": None, "updated_at": None, "remainder": 4}])),
    ])
    q = asyncio.run(dq.queue(db))
    assert q["counts"] == {"dispute": 2, "guild": 1, "contract": 1}
    assert [i["title"] for i in q["items"]] == ["Fix the board", "Dispute #7", "Lost record", "Late work"], \
        "every row names its subject (a party's filing about no order is the record itself)"
    assert len({(i["kind"], str(i["id"])) for i in q["items"]}) == len(q["items"])
    first = q["items"][0]
    assert first["defendant_name"] == "session-tester" and first["reason_text"].startswith("The worker handed nothing")
    assert first["at_stake"] == {"amount": "25", "currency": "ECU", "what": "the order's escrow"}
    contract_sql = [s for s, _ in db.calls if "FROM contracts c" in s][0]
    assert "origin_surface <> 'guild'" in contract_sql, "a Guild order's contract mirror is the order's, never listed twice"


def test_a_records_answer_carries_names_why_who_ruled_and_the_orders_evidence(monkeypatch):
    from agentvault_registry.routers import disputes as R
    d = _dispute(guild_order_id=OID, reason="deadline_missed", filed_by="system", status="CLOSED",
                 ruling="IN_FAVOR_OF_DEFENDANT", ruled_by=6, ruling_note="It delivered.",
                 created_at=type("T", (), {"isoformat": lambda s: "2026-11-01T00:00:00+00:00"})(),
                 updated_at=type("T", (), {"isoformat": lambda s: "2026-11-06T00:00:00+00:00"})())
    parties = {POSTER: {"did": POSTER, "name": "session-lead", "owner": "Commander", "home": "this registry"},
               WORKER: {"did": WORKER, "name": "session-tester", "owner": "Commander", "home": "this registry"}}
    detail = {"guild_order": {"id": OID, "spec": "Fix it", "handed_in": False, "events": []}, "corrections": []}
    r = R._serialize_dispute(d, parties, detail)
    assert (r.complainant_name, r.defendant_name) == ("session-lead", "session-tester")
    assert r.reason_text.startswith("The worker handed nothing") and r.filed_by == "system"
    assert (r.ruled_by, r.ruling_note) == (6, "It delivered.")
    assert r.guild_order["spec"] == "Fix it" and r.parties["defendant"]["owner"] == "Commander"


def test_control_the_contract_spine_keeps_its_own_ruling_rule():
    """The Guild's DISMISSED differs from the spine's only when nothing was handed in; the spine itself is untouched."""
    cs = importlib.import_module("agentvault_registry.services.contract_settlement")
    d = types.SimpleNamespace(complainant_did=POSTER)
    c = {"client_did": POSTER}
    assert [cs.ruling_to_provider_pct(c, d, r) for r in ("IN_FAVOR_OF_COMPLAINANT", "IN_FAVOR_OF_DEFENDANT",
                                                         "DISMISSED")] == [0, 100, 100]
