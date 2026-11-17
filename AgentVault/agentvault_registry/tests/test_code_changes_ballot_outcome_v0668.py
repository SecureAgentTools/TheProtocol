"""V0668 (order gwo_2d51e1af1b2a21a0bcdff5e7, session-lead; found retaking journal 55's hero on Sandbox Alpha, 2026-11-17 09:40Z,
cc_f2bee2d81b67f9791cb21331): A CHANGE'S RECORD SAYS WHY ITS BALLOT DID NOT PASS, AND WHEN IT WAS TALLIED.

The page read DID NOT PASS beside "300 for, 0 against · 3 voted" while the tally knew why (tally_quorum_met false, 300 of the 330.6
required), and "What happened" dated the failure at the ballot's opening (the sync moved the state and never the record's time).
The view now carries `ballot_outcome` for a decided ballot, main line or a line's own: the reason (quorum not met, with the weight
that took part and the weight required; or rejected, with the share in favour against the pass rule), the tally time, and the
numbers in one shape; an open ballot, or a change with none, carries no such key (a main-line change reads as before).
"""
from __future__ import annotations

import datetime as dt

from agentvault_registry.services import code_changes as cc
from agentvault_registry.services import code_distributions as cd
from tests.test_code_changes_bootstrap_v0666 import ADMIN, BootStore, _balloted
from tests.test_code_changes_flow_v0663 import T0, _flow, run
from tests.test_code_changes_flow_v0663 import _maintainer_and_release_line  # noqa: F401 (the autouse fixture: the maintainer, the release line, the checker key)
from tests import test_code_distributions_v0666 as lines
from tests.test_code_distributions_v0666 import _env  # noqa: F401 (the autouse switches for the line tests)

AT = T0 + dt.timedelta(days=1, minutes=1)          # the tally ran a day after the ballot opened (the hero: opened 11-16 09:25, tallied 11-17 09:26)


def _tallied(s, *, status="FAILED", met=False, for_=300.0, against=0.0, required=330.6, network=3306.0, mode="member", at=AT):
    s.proposals[1].update(status=status, tallied_at=at, tally_quorum_met=met, votes_for=for_, votes_against=against,
                          tally_quorum_required=required, tally_network_power=network, tally_weight_mode=mode,
                          quorum_percent=10.0, pass_percent=50.0)
    s.clock = (at or T0 + dt.timedelta(days=1)) + dt.timedelta(minutes=14)


def test_a_ballot_that_missed_its_quorum_says_so_with_the_weight_that_took_part_and_the_weight_required():
    s = BootStore(real=27)
    cid = _balloted(s)
    opened = s.rows[cid]["updated_at"]
    _tallied(s)
    out = run(_flow(s).view(cid))
    o = out["ballot_outcome"]
    assert out["state"] == "failed"
    assert (o["status"], o["reason"], o["unit"]) == ("FAILED", "quorum_not_met", "member")
    assert (o["took_part"], o["required"], o["quorum_percent"], o["for"], o["against"]) == (300.0, 330.6, 10.0, 300.0, 0.0)
    assert o["tallied_at"] == cc._iso(AT), "the outcome is dated by its tally, not by the ballot's opening"
    assert o["sentence"] == "the ballot missed its quorum: 300 of the 330.6 members' points required took part (10 percent of 3306)"
    assert out["updated_at"] == cc._iso(s.clock) and out["updated_at"] != cc._iso(opened), \
        "the record's own time moves when the ballot's result reaches it"


def test_a_ballot_the_members_rejected_says_so_with_the_share_in_favour_against_the_pass_rule():
    s = BootStore(real=27)
    cid = _balloted(s)
    _tallied(s, met=True, for_=100.0, against=200.0)
    o = run(_flow(s).view(cid))["ballot_outcome"]
    assert (o["reason"], o["share_for"], o["pass_percent"]) == ("rejected", 33.3, 50.0)
    assert o["sentence"] == "the members decided against it: 33.3 percent in favour, 50 percent needed to pass"


def test_a_passed_ballot_says_it_met_its_quorum_and_its_share_and_when():
    s = BootStore(real=27)
    cid = _balloted(s)
    _tallied(s, status="PASSED", met=True, for_=400.0, against=0.0)
    out = run(_flow(s).view(cid))
    o = out["ballot_outcome"]
    assert out["state"] == "passed" and o["reason"] == "passed" and o["tallied_at"] == cc._iso(AT)
    assert o["sentence"] == "passed: 100 percent in favour of 400 members' points cast, the quorum of 330.6 met"


def test_voting_power_is_the_unit_of_a_registry_that_counts_locks():
    s = BootStore(real=27)
    cid = _balloted(s)
    _tallied(s, mode="lock")
    o = run(_flow(s).view(cid))["ballot_outcome"]
    assert o["unit"] == "lock" and "330.6 voting power required" in o["sentence"]


def test_a_tally_that_kept_no_numbers_claims_no_reason_and_no_tally_time():
    s = BootStore(real=27)
    cid = _balloted(s)
    s.proposals[1].update(status="FAILED", tallied_at=None, tally_quorum_met=None)
    s.clock = T0 + dt.timedelta(days=2)
    o = run(_flow(s).view(cid))["ballot_outcome"]
    assert o["reason"] == "unknown" and o["tallied_at"] is None
    assert o["ended_at"] == cc._iso(s.proposals[1]["end_timestamp"])
    assert o["sentence"] == "the tally kept no reason (it ran before the registry stored one)"


def test_an_open_ballot_and_a_change_without_one_carry_no_outcome():
    s = BootStore(real=27)
    cid = _balloted(s)
    assert "ballot_outcome" not in run(_flow(s).view(cid)), "still voting"
    s2 = BootStore(real=27)
    from tests.test_code_changes_flow_v0663 import _accepted
    c2 = _accepted(s2)
    assert "ballot_outcome" not in run(_flow(s2).view(c2)), "no ballot yet: the record reads as before"


def test_a_cancelled_ballot_carries_no_outcome():
    s = BootStore(real=27)
    cid = _balloted(s)
    s.proposals[1]["status"] = "CANCELLED"
    assert "ballot_outcome" not in run(_flow(s).view(cid))


def test_the_maintainers_go_keeps_the_ballots_own_outcome_beside_it():
    s = BootStore(real=3)
    cid = _balloted(s)
    _tallied(s)
    out = run(_flow(s).go(ADMIN, cid))
    assert out["state"] == "passed" and out["bootstrap"]
    assert out["ballot_outcome"]["reason"] == "quorum_not_met" and out["ballot_outcome"]["tallied_at"] == cc._iso(AT)


def test_a_passed_change_moves_its_record_time_too():
    s = BootStore(real=27)
    cid = _balloted(s)
    _tallied(s, status="PASSED", met=True, for_=400.0)
    out = run(_flow(s).view(cid))
    assert out["updated_at"] == cc._iso(s.clock)


# --- a line's own ballot: the same shape, from the result its close wrote (ballot_result) ---------------------------------

def test_a_lines_ballot_below_its_quorum_names_the_deciders_that_voted_and_the_deciders_required():
    s = lines.LineStore()
    cid = lines._balloting(s)
    run(cd.CodeDistributionFlow(s).update({"developer_id": 2}, "lyceum", {"quorum_percent": 100}))
    lines._vote(s, cid, 2)                              # 1 of 3: below the snapshotted 50 percent
    s.clock += dt.timedelta(days=cc.ballot_days(), seconds=1)
    out = run(lines._flow(s).view(cid))
    o, res = out["ballot_outcome"], out["line_ballot"]["result"]
    assert (o["reason"], o["unit"], o["took_part"], o["required"], o["quorum_percent"]) == ("quorum_not_met", "deciders", 1, 2, 50)
    assert o["tallied_at"] == res["closed_at"] and o["sentence"] == res["sentence"]


def test_a_lines_ballot_the_deciders_rejected_names_the_pass_rule():
    s = lines.LineStore()
    cid = lines._balloting(s)
    for d, v in ((2, False), (3, False), (4, True)):
        lines._vote(s, cid, d, v)
    o = run(lines._flow(s).view(cid))["ballot_outcome"]
    assert (o["reason"], o["for"], o["against"], o["share_for"], o["pass_rule"]) == ("rejected", 1, 2, 33.3, "simple")


def test_a_line_with_no_deciders_at_the_close_says_so():
    s = lines.LineStore()
    cid = lines._balloting(s)
    s.teams[lines.TEAM]["is_active"] = False
    s.clock += dt.timedelta(days=cc.ballot_days(), seconds=1)
    o = run(lines._flow(s).view(cid))["ballot_outcome"]
    assert o["reason"] == "no_deciders" and o["required"] is None and "deciding team is gone" in o["sentence"]


def test_a_lines_passed_ballot_says_so():
    s = lines.LineStore()
    cid = lines._passed(s)
    o = run(lines._flow(s).view(cid))["ballot_outcome"]
    assert o["reason"] == "passed" and o["tallied_at"]


def test_the_outcome_is_one_pure_rule_per_kind_of_ballot():
    assert cc.ballot_outcome(None) is None and cc.ballot_outcome({"status": "VOTING"}) is None
    assert cc.line_ballot_outcome(None) is None and cc.line_ballot_outcome({"status": "OPEN"}) is None
    o = cc.ballot_outcome({"status": "FAILED", "tally_quorum_met": False, "votes_for": 0, "votes_against": 0,
                           "tally_quorum_required": None, "tally_weight_mode": "member", "quorum_percent": 10.0})
    assert o["reason"] == "quorum_not_met" and o["share_for"] is None and o["required"] is None
