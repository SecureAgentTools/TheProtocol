"""V0666 (order gwo_bb133d0532d29d7c10cb5cba; the maintainer's word, room seq 4404, 4424 and 4431: build through Code changes now): THE BOOTSTRAP RULE.

While the frame has fewer than CODE_CHANGES_BOOTSTRAP_MEMBERS real members (default 10; "real" = members that are not the frame's service accounts, defined in one
place: services/membership.real_member_ids), a change whose ballot ended without reaching quorum may pass on the maintainer's go. The record says so in plain words and
keeps who did vote. The checks and the reviews stay required at the go; a ballot the members rejected (quorum met, not enough in favour) is never overridden; nobody but
the maintainer gives the go; at and above the threshold the rule is off by itself.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from agentvault_registry.services import code_changes as cc
from agentvault_registry.services import membership
from tests.test_code_changes_flow_v0663 import (   # noqa: F401 (the autouse fixture sets the maintainer and the checker key)
    ADMIN, CONSOLE, PROPOSER, SHA, T0, FakeStore, _accept, _accepted, _flow, _maintainer_and_release_line, _mb, _propose, _refused, _review, _deliver, run)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


class BootStore(FakeStore):
    """FakeStore with what the bootstrap rule asks of the store: the real member count and who voted on a ballot."""

    def __init__(self, *a, real=3, votes=None, **kw):
        super().__init__(*a, **kw)
        self.real, self.voters = real, votes if votes is not None else [{"developer_id": 7, "vote": True}, {"developer_id": 8, "vote": True}]

    async def real_member_count(self):
        return self.real

    async def ballot_votes(self, pid):
        return list(self.voters)


def _balloted(s, *, sensitive=False):
    if sensitive:
        cid = _propose(s, paths=[CONSOLE + "stores/auth.ts"])["id"]
        _deliver(s, s.rows[cid]["order_id"])
        _accept(s, cid, touched=[CONSOLE + "stores/auth.ts"])
        _review(s, cid, 7)
        _review(s, cid, 8)
    else:
        cid = _accepted(s)
        _review(s, cid, 7)
    run(_flow(s).open_ballot(PROPOSER, cid))
    s.repo.contained.add(("v0663/cut", SHA))
    return cid


def _failed_for_quorum(s, cid, met=False):
    s.proposals[1].update(status="FAILED", tallied_at=T0, tally_quorum_met=met)
    s.clock = T0 + dt.timedelta(hours=1)


def test_below_the_threshold_the_maintainers_go_passes_a_ballot_that_missed_its_quorum():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    assert run(_flow(s).view(cid))["state"] == "failed"
    out = run(_flow(s).go(ADMIN, cid))
    assert out["state"] == "passed"
    rec = out["bootstrap"]
    assert rec["members"] == 3 and rec["threshold"] == 10 and rec["by"] == 99
    assert rec["sentence"] == "passed on the maintainer's go: the frame has 3 members, fewer than 10"
    assert rec["voted"] == [{"developer_id": 7, "vote": True}, {"developer_id": 8, "vote": True}]      # the members who did vote, beside it


def test_the_change_then_merges_at_once_and_only_the_voted_commit():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    run(_flow(s).go(ADMIN, cid))
    _refused(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, "b" * 40, "v0663/cut")), 409, "merge_refused")
    out = run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))
    assert out["state"] == "merged" and out["bootstrap"]["members"] == 3                  # no veto window to wait for: the go is the maintainer's


def test_at_and_above_the_threshold_the_rule_is_off_by_itself():
    for n in (10, 11, 40):
        s = BootStore(real=n)
        cid = _balloted(s)
        _failed_for_quorum(s, cid)
        e = _refused(_flow(s).go(ADMIN, cid), 409, "bootstrap_closed")
        assert str(n) in e.sentence and "10" in e.sentence
        assert run(_flow(s).view(cid))["state"] == "failed"


def test_the_threshold_is_an_env_and_a_bad_value_is_the_default(monkeypatch):
    monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_MEMBERS", "3")
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    _refused(_flow(s).go(ADMIN, cid), 409, "bootstrap_closed")                              # 3 members, threshold 3: off
    monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_MEMBERS", "banana")
    assert cc.bootstrap_members() == 10
    monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_MEMBERS", "0")
    assert cc.bootstrap_members() == 0                                                      # 0 turns the rule off for good
    monkeypatch.delenv("CODE_CHANGES_BOOTSTRAP_MEMBERS")
    assert cc.bootstrap_members() == 10


def test_a_ballot_the_members_rejected_is_never_overridden():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid, met=True)                                                     # quorum reached, not enough in favour
    _refused(_flow(s).go(ADMIN, cid), 409, "rejected_by_vote")
    s2 = BootStore(real=3)
    c2 = _balloted(s2)
    s2.proposals[1].update(status="FAILED", tallied_at=T0)                                  # no record of the quorum at all: not overridden either
    _refused(_flow(s2).go(ADMIN, c2), 409, "rejected_by_vote")


def test_the_reviews_and_the_checks_stay_required_at_the_go():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    s.revs.append({"code_change_id": cid, "reviewer_developer_id": 8, "verdict": "changes", "commit": SHA, "findings": "not yet", "at": 1.0})   # asked for changes after the ballot failed
    _refused(_flow(s).go(ADMIN, cid), 409, "reviews_short")
    s2 = BootStore(real=3)
    c2 = _balloted(s2)
    _failed_for_quorum(s2, c2)
    s2.rows[c2]["acceptance"]["ok"] = False                                                 # the checker's record no longer holds
    _refused(_flow(s2).go(ADMIN, c2), 409, "acceptance")


def test_a_sensitive_change_still_needs_its_two_approving_reviews():
    s = BootStore(real=3)
    cid = _balloted(s, sensitive=True)
    _failed_for_quorum(s, cid)
    s.revs[:] = [r for r in s.revs if r["reviewer_developer_id"] != 8]                      # one approval is gone: a sensitive change needs two
    _refused(_flow(s).go(ADMIN, cid), 409, "reviews_short")
    s2 = BootStore(real=3)
    c2 = _balloted(s2, sensitive=True)
    _failed_for_quorum(s2, c2)
    assert run(_flow(s2).go(ADMIN, c2))["state"] == "passed"                                 # with its two, the go passes it


def test_nobody_but_the_maintainer_can_give_the_go():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    _refused(_flow(s).go({"developer_id": 7}, cid), 403, "admin_only")
    _refused(_flow(s).go({"developer_id": 98, "admin": True}, cid), 403, "not_maintainer")    # another platform admin is not him
    assert run(_flow(s).view(cid))["state"] == "failed"


def test_with_no_maintainer_named_nobody_goes(monkeypatch):
    monkeypatch.delenv("CODE_CHANGES_MAINTAINER")
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    _refused(_flow(s).go(ADMIN, cid), 403, "no_maintainer")


def test_a_store_that_cannot_count_members_leaves_the_rule_off():
    s = FakeStore()                                                                          # no real_member_count at all
    cid = _balloted_plain(s)
    _failed_for_quorum(s, cid)
    _refused(_flow(s).go(ADMIN, cid), 409, "bootstrap_closed")


def _balloted_plain(s):
    cid = _accepted(s)
    _review(s, cid, 7)
    run(_flow(s).open_ballot(PROPOSER, cid))
    return cid


def test_the_go_on_a_ballot_that_is_still_open_or_not_decided_is_refused_as_before():
    s = BootStore(real=3)
    cid = _balloted(s)
    _refused(_flow(s).go(ADMIN, cid), 409, "wrong_state")                                    # still balloting
    s2 = BootStore(real=3)
    c2 = _balloted(s2)
    s2.proposals[1].update(status="PASSED", tallied_at=T0)
    assert run(_flow(s2).go(ADMIN, c2))["state"] == "passed"                                 # a passed ballot's go is unchanged
    assert "bootstrap" not in run(_flow(s2).view(c2)) or run(_flow(s2).view(c2))["bootstrap"] is None


def test_a_failed_change_without_the_go_still_cannot_merge():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    _refused(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")), 409, "merge_refused")


def test_the_bootstrap_go_can_be_vetoed_inside_the_window_like_any_pass():
    s = BootStore(real=3)
    cid = _balloted(s)
    _failed_for_quorum(s, cid)
    run(_flow(s).go(ADMIN, cid))
    out = run(_flow(s).veto(ADMIN, cid, {"reason": "changed my mind"}))
    assert out["state"] == "vetoed"


# --- real members, in one place -------------------------------------------------------------------------------------------

def test_a_real_member_is_a_member_that_is_not_a_service_account():
    assert membership.real_member_ids({1, 2, 3, 4}, service_ids={2, 4}) == {1, 3}
    assert membership.real_member_ids(set(), service_ids={2}) == set()
    assert membership.real_member_ids({5}, service_ids=set()) == {5}


def test_the_store_counts_real_members_through_that_one_place_and_records_the_voters():
    txt = (SRC / "services" / "code_changes.py").read_text()
    body = txt.split("class DbStore:", 1)[1]
    assert "async def real_member_count" in body and "membership.real_member_count" in body
    assert "async def ballot_votes" in body
    mem = (SRC / "services" / "membership.py").read_text()
    assert "async def real_member_count" in mem and "agents_unlisted_by_default" in mem     # the registry's own mark of a service account
    assert txt.count("agents_unlisted_by_default") == 0, "no second definition of a service account in the flow"


def test_nothing_else_names_the_threshold():
    assert "CODE_CHANGES_BOOTSTRAP_MEMBERS" in (SRC / "services" / "code_changes.py").read_text()
