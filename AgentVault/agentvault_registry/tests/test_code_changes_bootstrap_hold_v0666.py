"""V0666 (order gwo_b4ab7b9b7b3595d6dad05e6b; found by session-code, room seq 4626 and 4636): THE BOOTSTRAP RULE'S TWO HOLES.

1. The bounty. While real members are below CODE_CHANGES_BOOTSTRAP_MEMBERS, the maintainer's go passes a change whose ballot
   failed only for lack of quorum (v0666/code-changes-bootstrap). For a bounty change the sweep (close_money) returned the bounty
   to its poster as soon as the ballot failed, the go could pass the change later, and at the merge close_money settles only an
   order still submitted: the worker's merged work went unpaid (no units lost, delta stays 0). Now such a ballot HOLDS its bounty
   for CODE_CHANGES_BOOTSTRAP_HOLD_HOURS (72 by default, counted from the tally; 0 returns at once, as before); a go inside the hold
   passes the change and the merge pays the worker as for any passed change; with no go the sweep returns the bounty when the
   hold ends, with the same record; a go after the return refuses with its own code (bounty_returned). The change's view says
   the bounty is held and until when. The Guild reaper never disputes the order of a failed change: the code-change sweep owns
   that money (returns it, or holds it), so a hold past the order's 7-day submitted timeout is not taken for an abandoned order.
2. The real store. _bootstrap_go reads the ballot's tally_quorum_met, and DbStore.proposal() never returned it: on a real
   registry every go answered 409 rejected_by_vote. The tests above it set the field in their fake store.

Every other path is pinned unchanged: a ballot that met its quorum and failed returns at once and is never passed by the go;
at or above the threshold, with the rule off or with the hold at 0 the bounty returns at once; a change without a bounty is
untouched; no new money path (the Guild's escrow and close_money only).
RED on v0666/code-changes-bootstrap 2200f0c46: the test_red_* tests.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_bootstrap_v0666 import BootStore, _balloted, _failed_for_quorum
from tests.test_code_changes_flow_v0663 import (   # noqa: F401 (the autouse fixture sets the maintainer and the checker key)
    ADMIN, PROPOSER, SHA, T0, _accept, _flow, _maintainer_and_release_line, _mb, _propose, _refused, _review, run)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
HOLD_END = T0 + dt.timedelta(hours=72)


def _order(s, cid):
    return s.orders[s.rows[cid]["order_id"]]


def _failed_held(real=3):
    """A bounty change, delivered, accepted, reviewed and balloted, whose ballot failed for lack of quorum (tallied at T0),
    read an hour later."""
    s = BootStore(real=real)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    assert run(_flow(s).view(cid))["state"] == "failed"
    return s, cid


# --- 1. the hole, end to end ---------------------------------------------------------------------------------------------

def test_red_a_quorum_only_failure_holds_the_bounty_and_a_go_inside_the_hold_pays_the_worker_at_merge():
    s, cid = _failed_held()
    run(cc.sweep_ended(s))                                                   # the reaper's pass right after the tally
    assert _order(s, cid)["status"] == "submitted", "the bounty went back to its poster at once"
    view = run(_flow(s).view(cid))
    assert view["bounty_hold_until"] == HOLD_END.isoformat()
    s.clock = T0 + dt.timedelta(hours=71)
    run(cc.sweep_ended(s))
    assert _order(s, cid)["status"] == "submitted"                           # still held, an hour before the end
    out = run(_flow(s).go(ADMIN, cid))
    assert out["state"] == "passed" and out["bootstrap"]["members"] == 3
    assert out["bounty_hold_until"] is None                                  # passed: the bounty is escrowed as for any passed change
    run(cc.sweep_ended(s))
    assert _order(s, cid)["status"] == "submitted"                           # a passed change's money waits for the merge
    out = run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))
    assert out["state"] == "merged"
    assert _order(s, cid)["status"] == "settled", "the worker's merged work was not paid"
    assert out["settlement"] == {"ok": True, "status": "settled"}


def test_red_the_hold_ends_with_no_go_the_sweep_returns_the_bounty_and_a_late_go_refuses_with_its_own_code():
    s, cid = _failed_held()
    s.clock = HOLD_END - dt.timedelta(seconds=1)
    run(cc.sweep_ended(s))
    assert _order(s, cid)["status"] == "submitted"
    s.clock = HOLD_END
    run(cc.sweep_ended(s))
    assert _order(s, cid)["status"] == "cancelled"                          # returned, as before, once the hold is over
    assert run(_flow(s).view(cid))["bounty_hold_until"] is None
    e = _refused(_flow(s).go(ADMIN, cid), 409, "bounty_returned")
    assert "returned to its poster" in e.sentence and "propose" in e.sentence
    assert s.rows[cid]["state"] == "failed" and not s.rows[cid].get("go")   # nothing passed, nothing recorded


def test_red_a_go_refuses_whenever_the_order_no_longer_holds_the_bounty():
    s, cid = _failed_held()
    _order(s, cid)["status"] = "disputed"                                     # taken out of the code change's hands by other means
    _refused(_flow(s).go(ADMIN, cid), 409, "bounty_returned")


def test_red_the_hold_is_counted_from_the_tally_and_its_length_is_a_setting(monkeypatch):
    monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_HOLD_HOURS", "5")
    s, cid = _failed_held()
    assert run(_flow(s).view(cid))["bounty_hold_until"] == (T0 + dt.timedelta(hours=5)).isoformat()
    s.clock = T0 + dt.timedelta(hours=5)
    run(cc.sweep_ended(s))
    assert _order(s, cid)["status"] == "cancelled"


@pytest.mark.parametrize("raw, hours", [("", 72), ("abc", 72), ("-3", 72), ("0", 0), ("12", 12), ("1.5", 1.5)])
def test_red_the_hold_setting_reads_a_number_and_falls_back_to_72(monkeypatch, raw, hours):
    monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_HOLD_HOURS", raw)
    assert cc.bootstrap_hold_hours() == hours


# --- every other path, pinned -------------------------------------------------------------------------------------------

def test_control_a_ballot_that_met_its_quorum_and_failed_returns_at_once_and_the_go_never_passes_it():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid, met=True)
    run(cc.sweep_ended(s))
    assert _order(s, cid)["status"] == "cancelled"
    _refused(_flow(s).go(ADMIN, cid), 409, "rejected_by_vote")


@pytest.mark.parametrize("setup", ["at_threshold", "rule_off", "hold_zero"])
def test_control_where_the_rule_cannot_pass_the_change_or_the_hold_is_off_the_bounty_returns_at_once(monkeypatch, setup):
    if setup == "rule_off":
        monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_MEMBERS", "0")
    if setup == "hold_zero":
        monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_HOLD_HOURS", "0")
    s = BootStore(real=10 if setup == "at_threshold" else 3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    run(cc.sweep_ended(s))
    assert _order(s, cid)["status"] == "cancelled"
    assert run(_flow(s).view(cid)).get("bounty_hold_until") is None


def test_control_a_change_with_its_own_branch_and_no_bounty_passes_on_the_go_as_before():
    s = BootStore(real=3)
    cid = _propose(s, bounty=None, currency=None, branch="fix/order-page", commit=SHA)["id"]
    _accept(s, cid)
    _review(s, cid, 7)
    run(_flow(s).open_ballot(PROPOSER, cid))
    s.repo.contained.add(("v0663/cut", SHA))
    _failed_for_quorum(s, cid)
    assert run(_flow(s).view(cid)).get("bounty_hold_until") is None
    assert run(_flow(s).go(ADMIN, cid))["state"] == "passed"
    assert run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))["state"] == "merged"


def test_control_no_new_money_path():
    txt = (SRC / "services" / "code_changes.py").read_text()
    # the money still moves through the store's two Guild calls only, each named once in close_money
    assert txt.count("await self.s.settle_order(") == 1 and txt.count("await self.s.return_order(") == 1


# --- 2. the real store reads the ballot's quorum ------------------------------------------------------------------------

class _Proposal:
    id, status, tallied_at, end_timestamp, tally_quorum_met = 5, "FAILED", T0, T0, False


class _Db:
    async def get(self, model, pid):
        return _Proposal() if pid == 5 else None

    async def refresh(self, obj):
        return None

    async def execute(self, stmt):
        # V0668 (gwo_2d51e1af): proposal() also reads the votes' weight for and against; a session with no votes answers none
        class _Rows:
            def all(self):
                return []
        return _Rows()


def test_red_the_real_store_returns_whether_the_ballot_met_its_quorum():
    p = run(cc.DbStore(_Db()).proposal(5))
    assert p["tally_quorum_met"] is False, "without it every bootstrap go on a real registry answers rejected_by_vote"
    assert p["status"] == "FAILED" and p["tallied_at"] == T0


# --- the reaper leaves a failed change's order to the code-change sweep --------------------------------------------------

def test_red_the_reaper_never_disputes_the_order_of_a_failed_change():
    assert "failed" in cc.SWEEP_OWNED_STATES and set(cc.ACTIVE_STATES) <= set(cc.SWEEP_OWNED_STATES)
    reaper = (SRC / "background_tasks" / "guild_order_reaper.py").read_text()
    body = reaper.split("async def _sweep_abandoned_submitted", 1)[1].split("\nasync def ", 1)[0]
    assert "SWEEP_OWNED_STATES" in body and "ACTIVE_STATES" not in body


def test_nothing_else_names_the_hold():
    hits = [p.name for p in SRC.rglob("*.py") if "CODE_CHANGES_BOOTSTRAP_HOLD_HOURS" in p.read_text()]
    assert hits == ["code_changes.py"]
