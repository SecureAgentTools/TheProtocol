"""V0663, governed code, slice 2 (order gwo_dd68911fe7e83b64bc611258): a code change's bounty settles to its worker when
the merge of the voted commit is recorded, and returns to the poster when the change failed its ballot, was vetoed or
was withdrawn. Only the Guild moves the money (routers/guild.settle_submitted_order, return_order_bounty: the legs of
the eval auto-settle and of cancel), so there is no new money path and Δ=0 by the existing rails.

  merge      record_merge settles the order (a submitted order, a local worker); a branch change has no order; an
             order the Guild will not settle here (a cross-registry worker) keeps the merge and says why, and the
             poster's verify still pays it (slice 1's gate passes on merged)
  veto       returns the bounty
  withdraw   a new step: the proposer's agent or a platform admin, before the ballot opens (proposed or accepted);
             returns the bounty; refused once the members are voting
  failed     a ballot that closed FAILED returns the bounty when the guild reaper's sweep runs (sweep_ended), never
             from a read: a GET of a failed change moves no money
  once       every money step reads the order first; a second sweep, a second veto read, a merge after a return: nothing
             moves twice (and the Guild's claims refuse it anyway)
Red on 005e4614e: no money step, no withdraw, no sweep.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import pathlib

import pytest

from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import (ADMIN, CHECKER_PUB_B64, PROPOSER, SHA, T0, FakeStore, _accept,
                                                _deliver, _mb, _propose, _refused, _review,
                                                acceptance_record, run)


class MoneyStore(FakeStore):
    """FakeStore plus the two Guild calls, which move an order the way the Guild does (claims included)."""

    def __init__(self, *a, remote_worker=False, **k):
        super().__init__(*a, **k)
        self.calls, self.remote_worker = [], remote_worker

    async def settle_order(self, oid, *, actor):
        self.calls.append(("settle", oid))
        o = self.orders[oid]
        if o["status"] != "submitted":
            return {"ok": False, "why": f"Order is {o['status']}, not submitted"}
        if self.remote_worker:
            return {"ok": False, "why": "a cross-registry worker is paid through the poster's verify"}
        o["status"] = "settled"
        return {"ok": True, "status": "settled"}

    async def return_order(self, oid, *, actor, reason):
        self.calls.append(("return", oid, reason))
        o = self.orders[oid]
        if o["status"] not in ("open", "awarded", "submitted"):
            return {"ok": False, "why": f"Order is {o['status']}: no bounty held to return"}
        o["status"] = "cancelled"
        return {"ok": True, "status": "cancelled"}

    async def ended(self):
        return [dict(r) for r in self.rows.values()
                if r["state"] in ("balloting", "failed", "vetoed", "withdrawn", "merged") and r.get("order_id")]


def _flow(store):
    return cc.CodeChangeFlow(store)


def _to_ballot(store):
    """A bounty change, delivered, accepted, reviewed and on its ballot."""
    cid = _propose(store)["id"]
    oid = store.rows[cid]["order_id"]
    _deliver(store, oid)
    _accept(store, cid)
    _review(store, cid, 7)
    run(_flow(store).open_ballot(ADMIN, cid))
    return cid, oid


def _close(store, cid, status):
    p = store.proposals[store.rows[cid]["proposal_id"]]
    p.update(status=status, tallied_at=store.clock)


@pytest.fixture(autouse=True)
def _maintainer_and_release_line(monkeypatch):
    """V0663 fixes (F3, F8): the maintainer (ADMIN, developer 99) and the release line these tests merge into."""
    monkeypatch.setenv("CODE_CHANGES_MAINTAINER", "99")
    monkeypatch.setenv("CODE_CHANGES_RELEASE_BRANCHES", "v0663/cut")
    monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", CHECKER_PUB_B64)


def _passed_and_window_over(store, cid):
    _close(store, cid, "PASSED")
    store.repo.contained.add(("v0663/cut", SHA))
    store.clock = T0 + dt.timedelta(hours=cc.veto_window_hours() + 1)
    run(_flow(store).view(cid))


# --- merge settles ---------------------------------------------------------------------------------------------------

def test_a_recorded_merge_settles_the_order():
    s = MoneyStore()
    cid, oid = _to_ballot(s)
    _passed_and_window_over(s, cid)
    out = run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))
    assert out["state"] == "merged" and s.orders[oid]["status"] == "settled"
    assert s.calls == [("settle", oid)]
    assert out["order_status"] == "settled" and out["settlement"]["ok"] is True


def test_a_branch_change_has_no_order_and_moves_nothing():
    s = MoneyStore()
    cid = _propose(s, bounty=None, branch="feat/x", commit=SHA)["id"]
    _accept(s, cid)
    _review(s, cid, 7)
    run(_flow(s).open_ballot(ADMIN, cid))
    _passed_and_window_over(s, cid)
    out = run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))
    assert out["state"] == "merged" and s.calls == [] and out["settlement"] is None


def test_an_order_the_guild_will_not_settle_here_keeps_the_merge_and_says_why():
    s = MoneyStore(remote_worker=True)
    cid, oid = _to_ballot(s)
    _passed_and_window_over(s, cid)
    out = run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))
    assert out["state"] == "merged" and s.orders[oid]["status"] == "submitted"
    assert out["settlement"]["ok"] is False and "poster's verify" in out["settlement"]["why"]


# --- veto, withdraw and a failed ballot return ------------------------------------------------------------------------

def test_a_veto_returns_the_bounty():
    s = MoneyStore()
    cid, oid = _to_ballot(s)
    _close(s, cid, "PASSED")
    out = run(_flow(s).veto(ADMIN, cid, {"reason": "not now"}))
    assert out["state"] == "vetoed" and s.orders[oid]["status"] == "cancelled"
    assert s.calls == [("return", oid, "the maintainer vetoed the merge")]


def test_the_proposer_withdraws_before_the_ballot_and_the_bounty_returns():
    s = MoneyStore()
    cid = _propose(s)["id"]
    oid = s.rows[cid]["order_id"]
    out = run(_flow(s).withdraw(PROPOSER, cid, {"reason": "solved another way"}))
    assert out["state"] == "withdrawn" and s.orders[oid]["status"] == "cancelled"
    assert s.calls == [("return", oid, "the proposer withdrew the change: solved another way")]


def test_an_admin_may_withdraw_an_accepted_change():
    """V0663 fixes (F4): an accepted BOUNTY change has a submitted order, and withdraw is refused once a worker holds the
    order (tests/test_code_changes_security_fixes_v0663.py); an admin still withdraws an accepted branch change, and a
    bounty change while its order is open (the bounty returns)."""
    s = MoneyStore()
    cid = _propose(s, bounty=None, currency=None, branch="docs/clearer-guild", commit=SHA)["id"]
    _accept(s, cid)
    assert s.rows[cid]["state"] == "accepted"
    out = run(_flow(s).withdraw(ADMIN, cid, {}))
    assert out["state"] == "withdrawn" and s.calls == []
    s2 = MoneyStore()
    cid2 = _propose(s2)["id"]
    oid = s2.rows[cid2]["order_id"]
    out = run(_flow(s2).withdraw(ADMIN, cid2, {}))
    assert out["state"] == "withdrawn" and s2.orders[oid]["status"] == "cancelled"


def test_withdraw_is_refused_to_others_and_once_the_members_vote():
    s = MoneyStore()
    cid, _oid = _to_ballot(s)
    _refused(_flow(s).withdraw({"did": "did:a:r7", "developer_id": 7}, cid, {}), 403, "not_yours")
    _refused(_flow(s).withdraw(PROPOSER, cid, {}), 409, "wrong_state")
    assert s.calls == []


def test_a_failed_ballot_returns_on_the_sweep_never_on_a_read():
    s = MoneyStore()
    cid, oid = _to_ballot(s)
    _close(s, cid, "FAILED")
    view = run(_flow(s).view(cid))
    assert view["state"] == "failed" and s.calls == [], "a GET moves no money"
    moved = run(cc.sweep_ended(s))
    assert moved == 1 and s.orders[oid]["status"] == "cancelled"
    assert s.calls == [("return", oid, "the members' ballot did not pass")]


def test_nothing_moves_twice():
    s = MoneyStore()
    cid, oid = _to_ballot(s)
    _close(s, cid, "FAILED")
    run(cc.sweep_ended(s))
    assert run(cc.sweep_ended(s)) == 0, "the order is cancelled: the second sweep reads it and moves nothing"
    assert [c[0] for c in s.calls] == ["return"]
    s2 = MoneyStore()
    cid2, oid2 = _to_ballot(s2)
    _passed_and_window_over(s2, cid2)
    run(_flow(s2).record_merge(ADMIN, cid2, _mb(s2, cid2, SHA, "v0663/cut")))
    assert run(cc.sweep_ended(s2)) == 0 and [c[0] for c in s2.calls] == ["settle"]


def test_the_sweep_settles_a_merge_whose_settle_had_not_happened():
    s = MoneyStore(remote_worker=True)
    cid, oid = _to_ballot(s)
    _passed_and_window_over(s, cid)
    run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))
    s.remote_worker = False   # e.g. the Guild could not settle it then; the sweep tries again
    assert run(cc.sweep_ended(s)) == 1 and s.orders[oid]["status"] == "settled"


# --- session-lead's yes at room seq 3523 (session-watch's note 3): no bounty for one's own developer --------------------

def test_a_bounty_worked_by_the_proposers_own_developer_is_not_accepted():
    s = MoneyStore()
    s.agents["did:a:proposer2"] = 1          # a second agent of the proposer's developer
    cid = _propose(s)["id"]
    oid = s.rows[cid]["order_id"]
    _deliver(s, oid, worker="did:a:proposer2")
    s.repo.touched[SHA] = [cc.CONSOLE_PREFIX + "views/GuildBoard.vue"]
    rec = {"signed": acceptance_record(s, cid, SHA)}         # V0664: what the host checker signs
    e = _refused(_flow(s).record_acceptance(ADMIN, cid, rec), 409, "own_bounty")
    assert "branch" in e.sentence and "withdraw" in e.sentence, e.sentence
    assert s.rows[cid]["state"] == "proposed" and s.calls == [], "refused, and no money moved"


def test_another_developers_worker_is_accepted_as_before():
    s = MoneyStore()
    cid = _propose(s)["id"]
    _deliver(s, s.rows[cid]["order_id"])          # did:a:worker, developer 2
    assert _accept(s, cid)["state"] == "accepted"


# --- the money path is the Guild's ------------------------------------------------------------------------------------

SRC = pathlib.Path(cc.__file__).read_text()


def test_code_changes_moves_no_money_of_its_own():
    for word in ("escrow_payout", "escrow_deposit", "/teg/", "fund-agent", "_payout_with_royalty"):
        assert word not in SRC, word
    assert "settle_submitted_order" in SRC and "return_order_bounty" in SRC


def test_the_reaper_runs_the_sweep():
    reaper = (pathlib.Path(cc.__file__).parents[1] / "background_tasks" / "guild_order_reaper.py").read_text()
    assert "sweep_ended" in reaper


def test_the_withdraw_route_exists():
    from agentvault_registry.routers import code_changes as r
    paths = {(m, getattr(x, "path", "")) for x in r.router.routes for m in getattr(x, "methods", [])}
    assert ("POST", "/api/v1/code-changes/{cid}/withdraw") in paths
    assert ("POST", "/api/v1/admin/code-changes/{cid}/withdraw") in paths
