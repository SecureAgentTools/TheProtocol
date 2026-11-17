"""V0663 governed code slice 2 (gwo_dd68911fe7e83b64bc611258): the two routers/guild.py helpers session-watch agreed at
room seq 3519 (scratchpad/govcode/guild_py_slice2_proposal.md), and session-watch's three notes.

  settle_submitted_order  the eval auto-settle's local legs, leg for leg: the guarded flip submitted to settled FIRST,
                          then the royalty payout, the worker's stake released, the reputation fold (stars 5), the
                          verified and settled events, GuildOrderSettled with verify's idempotency key; 409 and nothing
                          moved when the order is not submitted, when its worker is cross-registry, or when the flip
                          finds it already moved (a racing poster verify)
  return_order_bounty     cancel's legs from open, awarded or submitted: the claim to cancelled FIRST and committed,
                          then the escrow refund of the whole bounty to the poster and every held stake back; 409 and
                          nothing moved when nothing is held or the claim loses a race
  note 1                  a 409 from the settle reaches code_changes as {"ok": False} (the order stays submitted for
                          the poster's verify, never marked paid); any other error is not swallowed
  note 2                  neither helper is a route, and only services/code_changes calls them (they carry no poster
                          check and no _require_enabled: the caller authorizes)
The money legs are recorded by replacing the Guild's own primitives (the escrow, the payout, the stakes); the order
of the calls is the assertion. Red on ed49876f1: the helpers do not exist.
"""
from __future__ import annotations

import asyncio
import pathlib
from decimal import Decimal

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import guild as G

ROOT = pathlib.Path(G.__file__).resolve().parents[1]


class _Res:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _Db:
    """Answers the guarded UPDATEs (rowcount 1 unless told to lose the race) and records every statement and commit."""

    def __init__(self, log, *, lose_race=False):
        self.log, self.lose_race = log, lose_race

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().upper().startswith("UPDATE GUILD_WORK_ORDERS"):
            self.log.append(("claim", sql.split("status=", 1)[1].split()[0].strip("',"), dict(params or {})))
            return _Res(0 if self.lose_race else 1)
        if "SELECT DISTINCT bidder_did" in sql:
            class _R:
                def scalars(self_inner):
                    class _S:
                        def all(self_s):
                            return ["did:a:bidder"]
                    return _S()
            return _R()
        self.log.append(("sql", sql[:40]))
        return _Res(1)

    async def commit(self):
        self.log.append(("commit",))


ORDER = {"id": "gwo_1", "status": "submitted", "bounty": "50", "poster_did": "did:a:poster", "worker_did": "did:a:worker",
         "payee_did": None, "payee_org_id": None, "worker_home_registry": None, "title": "Code change: x",
         "currency": "ECU", "fee_bps": 100}


@pytest.fixture
def guild(monkeypatch):
    log, state = [], {"order": dict(ORDER)}

    async def load(db, oid):
        return dict(state["order"])

    async def next_seq(db, oid):
        return 1

    async def audit(db, oid, seq, etype, actor, payload):
        log.append(("event", etype, actor))

    async def payout(db, payee, amount, oid):
        log.append(("payout", payee, Decimal(str(amount))))

    async def stake(db, oid, worker, to, action):
        log.append(("stake", worker, to, action))

    async def all_stakes(db, oid, exclude_bidder=None):
        log.append(("stakes_back", exclude_bidder))

    async def escrow_payout(db, to, amount, oid, leg):
        log.append(("escrow", to, Decimal(str(amount)), leg))

    async def fold(db, poster, payee, stars, volume):
        log.append(("fold", poster, payee, stars))

    async def credential(o, stars):
        return {"stars": stars}

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(G, "_load", load)
    monkeypatch.setattr(G, "_next_seq", next_seq)
    monkeypatch.setattr(G, "_audit", audit)
    monkeypatch.setattr(G, "_payout_with_royalty", payout)
    monkeypatch.setattr(G, "_resolve_worker_stake", stake)
    monkeypatch.setattr(G, "_refund_all_stakes", all_stakes)
    monkeypatch.setattr(G.guild_escrow, "escrow_payout", escrow_payout)
    monkeypatch.setattr(G.guild_reputation, "fold_work_reputation", fold)
    monkeypatch.setattr(G.guild_reputation, "issue_work_credential", credential)
    monkeypatch.setattr(G.guild_contract_mirror, "sync_from_order", noop)
    monkeypatch.setattr(G, "_tr_touch", noop)
    monkeypatch.setattr(G, "_emit", lambda *a, **k: log.append(("emit", a[0], k.get("idempotency_key"))))
    monkeypatch.setattr(G, "_guild_webhook", lambda *a, **k: None)
    monkeypatch.setattr(G, "_notify_owners", lambda *a, **k: log.append(("notify", tuple(a[1]))))
    return log, state


def run(c):
    return asyncio.run(c)


def test_settle_claims_first_then_the_eval_legs(guild):
    log, _ = guild
    out = run(G.settle_submitted_order(_Db(log), "gwo_1", actor="code-change:cc_1", via="governed_code"))
    kinds = [e[0] for e in log]
    assert kinds.index("claim") < kinds.index("payout"), "the flip to settled comes before any money"
    assert ("claim", "settled", {"f": Decimal("0.5000000000"), "o": "gwo_1"}) in log
    assert ("payout", "did:a:worker", Decimal("49.5000000000")) in log
    assert ("stake", "did:a:worker", "did:a:worker", "release") in log
    assert ("fold", "did:a:poster", "did:a:worker", 5) in log
    # F7 (V0663 fixes): the settling event, committed with the claim, comes first
    assert [e[1] for e in log if e[0] == "event"] == ["settling", "verified", "settled"]
    assert ("emit", "GuildOrderSettled", "guild-settled-gwo_1") in log
    assert out["status"] == "settled" and out["stars"] == 5


def test_f7_the_settle_claims_settling_durably_before_it_pays(guild):
    """V0663 fixes (F7, gwo_3b9568ce2782ea55437bcdbc; session-watch's yes at room seq 3575): as verify, the flip to
    settling and its settling event commit together BEFORE the payout (a stop after the claim leaves a datable order the
    reaper ages), then settling to settled."""
    log, _ = guild
    run(G.settle_submitted_order(_Db(log), "gwo_1", actor="code-change:cc_1", via="governed_code"))
    i_claim = log.index(("claim", "settling", {"o": "gwo_1"}))
    i_event = next(i for i, e in enumerate(log) if e[:2] == ("event", "settling"))
    i_commit = next(i for i, e in enumerate(log) if e == ("commit",) and i > i_event)
    i_pay = next(i for i, e in enumerate(log) if e[0] == "payout")
    i_settled = next(i for i, e in enumerate(log) if e[:2] == ("claim", "settled"))
    assert i_claim < i_event < i_commit < i_pay < i_settled, log


@pytest.mark.parametrize("change", [{"status": "awarded"}, {"worker_home_registry": "https://asia.example.org"}])
def test_settle_refuses_and_moves_nothing(guild, change):
    log, state = guild
    state["order"].update(change)
    with pytest.raises(HTTPException) as e:
        run(G.settle_submitted_order(_Db(log), "gwo_1", actor="a", via="governed_code"))
    assert e.value.status_code == 409 and log == []


def test_settle_that_loses_the_race_moves_nothing(guild):
    log, _ = guild
    with pytest.raises(HTTPException) as e:
        run(G.settle_submitted_order(_Db(log, lose_race=True), "gwo_1", actor="a", via="governed_code"))
    assert e.value.status_code == 409 and [x[0] for x in log] == ["claim"]


@pytest.mark.parametrize("held", ["open", "awarded", "submitted"])
def test_return_claims_first_then_refunds_the_whole_bounty_and_every_stake(guild, held):
    log, state = guild
    state["order"]["status"] = held
    out = run(G.return_order_bounty(_Db(log), "gwo_1", actor="code-change:cc_1", via="governed_code",
                                    reason="the members' ballot did not pass"))
    kinds = [e[0] for e in log]
    assert log[0] == ("claim", "cancelled", {"o": "gwo_1", "s": held})
    assert kinds.index("commit") < kinds.index("escrow"), "the claim is committed before any money"
    assert ("escrow", "did:a:poster", Decimal("50"), "refund") in log
    assert ("stakes_back", None) in log, "every held stake back, the worker's too"
    assert ("event", "cancelled", "code-change:cc_1") in log
    assert ("notify", ("did:a:bidder",)) in log
    assert out["status"] == "cancelled" and out["from"] == held and out["refund"] == 50.0


@pytest.mark.parametrize("ended", ["settled", "cancelled", "disputed", "settling"])
def test_return_refuses_when_nothing_is_held(guild, ended):
    log, state = guild
    state["order"]["status"] = ended
    with pytest.raises(HTTPException) as e:
        run(G.return_order_bounty(_Db(log), "gwo_1", actor="a", via="governed_code", reason="x"))
    assert e.value.status_code == 409 and log == []


def test_return_that_loses_the_race_moves_nothing(guild):
    log, _ = guild
    with pytest.raises(HTTPException) as e:
        run(G.return_order_bounty(_Db(log, lose_race=True), "gwo_1", actor="a", via="governed_code", reason="x"))
    assert e.value.status_code == 409 and [x[0] for x in log] == ["claim"]


# --- session-watch's notes ---------------------------------------------------------------------------------------------

def test_note_1_a_409_reaches_code_changes_as_not_paid_and_other_errors_are_not_swallowed(monkeypatch):
    from agentvault_registry.services import code_authority as ca
    from agentvault_registry.services import code_changes as cc
    monkeypatch.setenv(ca.ENV, "eu")                                 # V0666: the store writes only on the registry that governs code
    monkeypatch.setattr(ca, "own_name", lambda: "eu")

    async def refuse(db, oid, **k):
        raise HTTPException(409, detail="a cross-registry worker is paid through the poster's verify")
    monkeypatch.setattr(G, "settle_submitted_order", refuse)
    out = run(cc.DbStore(None).settle_order("gwo_1", actor="a"))
    assert out == {"ok": False, "why": "a cross-registry worker is paid through the poster's verify"}

    async def broken(db, oid, **k):
        raise HTTPException(500, detail="database gone")
    monkeypatch.setattr(G, "settle_submitted_order", broken)
    with pytest.raises(HTTPException):
        run(cc.DbStore(None).settle_order("gwo_1", actor="a"))


def test_note_2_no_route_and_only_code_changes_calls_them():
    src = (ROOT / "routers" / "guild.py").read_text()
    for name in ("settle_submitted_order", "return_order_bounty"):
        head = src.split(f"async def {name}(", 1)[0].rstrip().splitlines()[-1]
        assert not head.lstrip().startswith("@"), f"{name} is decorated: {head}"
        users = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py") if name in p.read_text()
                       and p.name != "guild.py")
        assert users == ["services/code_changes.py"], (name, users)
    routes = {getattr(r, "endpoint", None) for r in G.router.routes}
    assert G.settle_submitted_order not in routes and G.return_order_bounty not in routes
