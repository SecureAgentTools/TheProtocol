"""V0663 fixes (order gwo_3b9568ce2782ea55437bcdbc): the governed-code findings of session-tester's independent read
(sessionlogs2026/SECURITY_READ_2026-11-14_GOVERNED_CODE_V0663.md, room seq 3567), each reproduced first.

  F1  sensitivity follows the paths the accepted COMMIT touches (read by the server), not the declared ones: declaring an
      open directory above a sensitive file no longer skips the second reviewer and the policy_change pair
  F2  the server builds the acceptance itself: the CI state of that commit, the paths it touches against the release line
      and a secret scan of their text, all read from the repository; a caller's record is ignored; neither the
      proposer's nor the worker's developer may ask for the check of their own change; no repository reader, no check
      (V0664, gwo_af5b8c950682b9318a347e39: the host checker reads the repository and signs the record; the frame holds
      only its public key and verifies it, so no key, no check)
  F3  go and veto are the maintainer's alone (CODE_CHANGES_MAINTAINER, an email or a developer id), not any platform
      admin's; with no maintainer named, nobody goes, vetoes or records a merge
  F4  withdraw returns a bounty only while its order is open (as the Guild's cancel), or when its worker is the
      proposer's own (the own-bounty case the guard sends to withdraw)
  F5  a failing check of a later commit voids the earlier acceptance and an open ballot (the proposal CANCELLED, the
      change back to proposed); a ballot opens only on an acceptance that holds for the commit
  F6  the own-bounty guard refuses a payee of the proposer's too (a treasury agent of theirs, an organization they own)
  F8  a recorded merge names a release branch (CODE_CHANGES_RELEASE_BRANCHES) that the repository says contains the voted
      commit
(F7, the automatic settle's durable claim, is in tests/test_guild_settle_return_helpers_v0663.py.)
Red on 4ba00b7b6.
"""
from __future__ import annotations

import datetime as dt

import pytest

from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import (ADMIN, CHECKER_PUB_B64, CONSOLE, PROPOSER, REPO, SHA, SHA2, T0, FakeStore,
                                                _accept, _deliver, _mb, _propose, _refused, _review, acceptance_record,
                                                run)

MAINTAINER = {"developer_id": 50, "admin": True, "email": "maintainer@example.org"}
OTHER_ADMIN = {"developer_id": 51, "admin": True, "email": "someone@example.org"}
OPEN_DIR = CONSOLE.rstrip("/")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CODE_CHANGES_MAINTAINER", "maintainer@example.org")
    monkeypatch.setenv("CODE_CHANGES_RELEASE_BRANCHES", "v0663/cut")
    monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", CHECKER_PUB_B64)


def _flow(s):
    return cc.CodeChangeFlow(s)


def _balloting(s, **over):
    cid = _propose(s, **over)["id"]
    _deliver(s, "gwo_1")
    _accept(s, cid)
    _review(s, cid, 7)
    run(_flow(s).open_ballot(PROPOSER, cid))
    return cid


def _passed(s, cid):
    p = s.proposals[s.rows[cid]["proposal_id"]]
    p.update(status="PASSED", tallied_at=s.clock)
    run(_flow(s).view(cid))


# --- F1 -----------------------------------------------------------------------------------------------------------------

def test_f1_a_declared_directory_above_sensitive_files_is_sensitive_once_the_commit_touches_them():
    s = FakeStore()
    s.policy = {"governance.policy_change_quorum_percent": 25.0, "governance.policy_change_pass_percent": 70.0}
    cid = _propose(s, paths=[OPEN_DIR])["id"]
    assert s.rows[cid]["sensitive"] is False, "declared: nothing sensitive by name"
    _deliver(s, "gwo_1")
    out = _accept(s, cid, touched=[CONSOLE + "router/index.ts", CONSOLE + "services/api/client.ts"])
    assert out["state"] == "accepted" and out["sensitive"] is True and out["reviews_needed"] == 2
    _review(s, cid, 7)
    _refused(_flow(s).open_ballot(PROPOSER, cid), 409, "reviews_short")
    _review(s, cid, 8)
    run(_flow(s).open_ballot(PROPOSER, cid))
    assert (s.proposals[1]["quorum_percent"], s.proposals[1]["pass_percent"]) == (25.0, 70.0)


# --- F2 -----------------------------------------------------------------------------------------------------------------

def test_f2_a_callers_record_is_ignored_the_repository_decides():
    """V0664: a caller's own record is not even read: only the host checker's signed record counts, and its facts decide."""
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    claimed = {"commit": SHA, "ci": {"status": "success"}, "suite": {"passed": 1, "failed": 0},
               "touched": [CONSOLE + "views/GuildBoard.vue"], "secret_findings": 0}
    _refused(_flow(s).record_acceptance(ADMIN, cid, claimed), 422, "unsigned")
    s.repo.ci[SHA], s.repo.touched[SHA] = "failure", [CONSOLE + "views/GuildBoard.vue"]
    out = run(_flow(s).record_acceptance(ADMIN, cid, {**claimed, "signed": acceptance_record(s, cid, SHA)}))
    assert out["acceptance"]["ok"] is False and out["state"] == "proposed"
    assert any("CI is not green" in r for r in out["acceptance"]["reasons"])


@pytest.mark.parametrize("setup,why", [
    (dict(ci="pending"), "CI is not green"),
    (dict(touched=[CONSOLE + "stores/auth.ts"]), "outside the declared"),
    (dict(touched=[CONSOLE + ".env"]), "forbidden"),
    (dict(secret=True), "secret scan"),
    (dict(touched=[]), "touched"),
])
def test_f2_what_the_repository_says_decides(setup, why):
    s = FakeStore()
    cid = _propose(s, paths=[CONSOLE + "views/"])["id"]
    _deliver(s, "gwo_1")
    out = _accept(s, cid, **setup)
    assert out["acceptance"]["ok"] is False and any(why in r for r in out["acceptance"]["reasons"]), out["acceptance"]


def test_f2_the_secret_scan_names_the_file_never_the_secret():
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    out = _accept(s, cid, secret=True)
    rec = out["acceptance"]["record"]
    assert rec["secret_findings"] == 1 and rec["secret_paths"] == [CONSOLE + "views/GuildBoard.vue"]
    assert "avreg_" not in str(out)


def test_f2_neither_the_proposer_nor_the_worker_asks_for_their_own_check():
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    for dev in (1, 2):   # the proposer's developer, the worker's developer, each holding the admin flag
        _refused(_flow(s).record_acceptance({"developer_id": dev, "admin": True}, cid, {"commit": SHA}), 403,
                 "not_independent")
    assert s.rows[cid]["acceptance"] is None


def test_f2_no_checker_key_no_check(monkeypatch):
    """V0664: the frame reads no repository; with no checker public key configured, nothing is checked."""
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    signed = acceptance_record(s, cid, SHA)
    monkeypatch.delenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", raising=False)
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"signed": signed}), 503, "no_checker")
    assert s.rows[cid]["acceptance"] is None


# --- F3 -----------------------------------------------------------------------------------------------------------------

def test_f3_only_the_maintainer_goes_or_vetoes(monkeypatch):
    s = FakeStore()
    cid = _balloting(s)
    _passed(s, cid)
    _refused(_flow(s).go(OTHER_ADMIN, cid), 403, "not_maintainer")
    _refused(_flow(s).veto(OTHER_ADMIN, cid, {"reason": "x"}), 403, "not_maintainer")
    assert run(_flow(s).go(MAINTAINER, cid))["go"]["by"] == 50
    by_id = dict(MAINTAINER, email=None)
    monkeypatch.setenv("CODE_CHANGES_MAINTAINER", "50")
    assert run(_flow(s).veto(by_id, cid, {"reason": "not now"}))["state"] == "vetoed"


def test_f3_no_maintainer_named_no_go_no_veto_no_merge(monkeypatch):
    monkeypatch.delenv("CODE_CHANGES_MAINTAINER", raising=False)
    s = FakeStore()
    cid = _balloting(s)
    _passed(s, cid)
    _refused(_flow(s).go(MAINTAINER, cid), 403, "no_maintainer")
    _refused(_flow(s).veto(MAINTAINER, cid, {}), 403, "no_maintainer")
    s.clock = T0 + dt.timedelta(hours=cc.veto_window_hours() + 1)
    s.repo.contained.add(("v0663/cut", SHA))
    _refused(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")), 409, "no_maintainer")


# --- F4 -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["awarded", "submitted"])
def test_f4_withdraw_is_refused_once_another_developers_worker_holds_the_order(status):
    s = FakeStore()
    cid = _propose(s)["id"]
    s.orders["gwo_1"].update(status=status, worker_did="did:a:worker")
    _refused(_flow(s).withdraw(PROPOSER, cid, {}), 409, "work_taken")
    _refused(_flow(s).withdraw(ADMIN, cid, {}), 409, "work_taken")
    assert s.orders["gwo_1"]["status"] == status


def test_f4_an_open_order_and_the_own_bounty_case_still_withdraw():
    s = FakeStore()
    cid = _propose(s)["id"]
    assert run(_flow(s).withdraw(PROPOSER, cid, {}))["state"] == "withdrawn"
    s2 = FakeStore()
    s2.agents["did:a:proposer2"] = 1
    cid2 = _propose(s2)["id"]
    s2.orders["gwo_1"].update(status="submitted", worker_did="did:a:proposer2",
                              deliverable={"commits": [{"repo": REPO, "commit": SHA}]})
    assert run(_flow(s2).withdraw(PROPOSER, cid2, {}))["state"] == "withdrawn"
    assert s2.orders["gwo_1"]["status"] == "cancelled"


# --- F5 -----------------------------------------------------------------------------------------------------------------

def test_f5_a_failing_later_check_voids_the_acceptance():
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    s.orders["gwo_1"]["deliverable"] = {"commits": [{"repo": REPO, "commit": SHA}, {"repo": REPO, "commit": SHA2}]}
    assert _accept(s, cid)["state"] == "accepted"
    out = _accept(s, cid, commit=SHA2, ci="failure")
    assert out["state"] == "proposed" and out["acceptance"]["ok"] is False
    _refused(_flow(s).open_ballot(PROPOSER, cid), 409, "wrong_state")


def test_f5_a_failing_check_during_the_ballot_cancels_it():
    s = FakeStore()
    cid = _balloting(s)
    pid = s.rows[cid]["proposal_id"]
    out = _accept(s, cid, secret=True)
    assert out["state"] == "proposed" and s.voided == [pid] and s.proposals[pid]["status"] == "CANCELLED"
    assert out["proposal_id"] is None


def test_f5_the_ballot_opens_only_on_an_acceptance_that_holds_for_the_commit():
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    _accept(s, cid)
    _review(s, cid, 7)
    s.rows[cid]["acceptance"] = {**s.rows[cid]["acceptance"], "ok": False}   # a record that no longer holds
    _refused(_flow(s).open_ballot(PROPOSER, cid), 409, "acceptance")


# --- F6 -----------------------------------------------------------------------------------------------------------------

def test_f6_a_payee_of_the_proposers_is_their_own_bounty():
    s = FakeStore()
    s.agents["did:a:treasury"] = 1                       # a treasury agent the proposer's developer made
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    s.orders["gwo_1"]["payee_did"] = "did:a:treasury"
    s.repo.touched[SHA] = [CONSOLE + "views/GuildBoard.vue"]
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"signed": acceptance_record(s, cid, SHA)}), 409, "own_bounty")
    s2 = FakeStore()
    cid2 = _propose(s2)["id"]
    _deliver(s2, "gwo_1")
    s2.orders["gwo_1"]["payee_org_id"] = "org-1"
    s2.org_owners["org-1"] = 1                            # an organization the proposer owns
    _refused(_flow(s2).record_acceptance(ADMIN, cid2, {"signed": acceptance_record(s2, cid2, SHA)}), 409, "own_bounty")


# --- F8 -----------------------------------------------------------------------------------------------------------------

def _ready_to_merge(s):
    cid = _balloting(s)
    _passed(s, cid)
    s.clock = T0 + dt.timedelta(hours=cc.veto_window_hours() + 1)
    return cid


def test_f8_the_merge_names_a_release_branch_that_contains_the_voted_commit():
    s = FakeStore()
    cid = _ready_to_merge(s)
    _refused(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "feature/x")), 409, "not_release_line")
    _refused(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")), 409, "not_on_release_line")
    s.repo.contained.add(("v0663/cut", SHA))
    assert run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))["state"] == "merged"
