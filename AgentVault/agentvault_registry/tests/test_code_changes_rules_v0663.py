"""V0663, governed code, first slice (order gwo_58327a76b7e3ecf63140eb79; DESIGN_2026-11-13_GOVERNED_CODE.md with his
decisions D1 to D8, room seq 3108): the rules of a code change, as pure functions (services/code_changes).

  - Paths (D5): a change names its repository and paths; only the open prefixes are open in this slice (the console,
    whose doc folder is the documentation's one source), never a secret, a key, a build or dependency file; a path
    on auth, admin, money or federation trust is SENSITIVE.
  - Acceptance (mechanical): one record per commit: CI green on that tip, the whole suite with 0 failed (and some
    passed), every touched path inside the declared paths and open, no secret shapes.
  - Review: independent members (not the proposer's developer, not the worker's) approve or ask for changes on THAT
    commit; a sensitive change needs two approvals; a reviewer's latest word counts, and one asking for changes holds
    the ballot.
  - Ballot thresholds (D3): the frame policy's standard quorum and threshold, the policy_change pair (66) when sensitive.
  - Merge (D4, D6): only the commit that was accepted, reviewed and voted, only after a PASSED ballot, never after his
    veto, and only once his veto window has closed or he said go.
Red on b27f2ebaf: services/code_changes does not exist.
"""
from __future__ import annotations

import datetime as dt

import pytest

try:     # red as one failure per test, not a collection error that stops the suite
    from agentvault_registry.services import code_changes as cc
except ImportError:
    cc = None

REPO = "theprotocol/AgentVault"
CONSOLE = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/"
SHA = "a" * 40
SHA2 = "b" * 40


def test_the_module_exists():
    from agentvault_registry.services import code_changes
    assert code_changes.REPOSITORY == REPO


# --- paths -------------------------------------------------------------------------------------------------------

def test_a_console_path_is_open_and_plain():
    r = cc.check_paths(REPO, [CONSOLE + "views/GuildBoard.vue", CONSOLE + "assets/docs/26-guild.md"])
    assert r.ok and not r.sensitive and r.reason is None


@pytest.mark.parametrize("path", [
    CONSOLE + "services/api/client.ts",
    CONSOLE + "services/api/adminGuard.ts",
    CONSOLE + "stores/auth.ts",
    CONSOLE + "views/AdminFiatOps.vue",
    CONSOLE + "components/wallet/Send.vue",
    CONSOLE + "views/Federation.vue",
    CONSOLE + "router/index.ts",
])
def test_auth_admin_money_and_federation_paths_are_sensitive(path):
    r = cc.check_paths(REPO, [path])
    assert r.ok and r.sensitive, path


@pytest.mark.parametrize("repo,paths,why", [
    ("theprotocol/Agentvault2", [CONSOLE + "views/A.vue"], "repository"),
    (REPO, ["agentvault_registry/src/agentvault_registry/routers/guild.py"], "not open"),
    (REPO, [CONSOLE + ".env"], "forbidden"),
    (REPO, [CONSOLE + "assets/secret-config.ts"], "forbidden"),
    (REPO, [CONSOLE + "certs/server.pem"], "forbidden"),
    (REPO, ["agentvault_registry/src/agentvault_registry/static/new_registry_frontend/package.json"], "forbidden"),
    (REPO, [CONSOLE + "../package-lock.json"], "malformed"),
    (REPO, ["/" + CONSOLE + "views/A.vue"], "malformed"),
    (REPO, [CONSOLE + "views\\A.vue"], "malformed"),
    (REPO, [], "no paths"),
    (REPO, [CONSOLE + "views/A.vue"] * 2, "twice"),
])
def test_a_path_outside_the_open_set_is_refused_with_its_reason(repo, paths, why):
    r = cc.check_paths(repo, paths)
    assert not r.ok and why in r.reason, (r.reason, why)


def test_the_open_prefixes_come_from_the_environment_when_set(monkeypatch):
    monkeypatch.setenv("CODE_CHANGE_OPEN_PATHS", '{"theprotocol/AgentVault": ["docs-only/"]}')
    assert cc.check_paths(REPO, ["docs-only/a.md"]).ok
    assert not cc.check_paths(REPO, [CONSOLE + "views/A.vue"]).ok


def test_a_touched_path_is_inside_a_declared_file_or_directory():
    assert cc.path_inside(CONSOLE + "views/A.vue", [CONSOLE + "views/"])
    assert cc.path_inside(CONSOLE + "views/A.vue", [CONSOLE + "views"])
    assert cc.path_inside(CONSOLE + "views/A.vue", [CONSOLE + "views/A.vue"])
    assert not cc.path_inside(CONSOLE + "views/AB.vue", [CONSOLE + "views/A"])
    assert not cc.path_inside(CONSOLE + "stores/auth.ts", [CONSOLE + "views/"])


# --- acceptance --------------------------------------------------------------------------------------------------

def _record(**over):
    r = {"commit": SHA, "ci": {"status": "success", "run": "https://git.example.org/runs/1"},
         "suite": {"passed": 12500, "failed": 0}, "touched": [CONSOLE + "views/A.vue"], "secret_findings": 0}
    r.update(over)
    return r


def test_a_green_record_inside_the_declared_paths_is_accepted():
    assert cc.acceptance_verdict(REPO, _record(), [CONSOLE + "views/"]) == (True, [])


@pytest.mark.parametrize("over,why", [
    ({"commit": "abc"}, "commit"),
    ({"ci": {"status": "failure"}}, "CI"),
    ({"ci": {}}, "CI"),
    ({"touched": []}, "touched"),
    ({"touched": [CONSOLE + "stores/auth.ts"]}, "outside the declared"),
    ({"touched": [CONSOLE + ".env"]}, "forbidden"),
    ({"secret_findings": 1}, "secret"),
    ({"secret_findings": None}, "secret"),
])
def test_anything_short_of_that_is_refused_and_named(over, why):
    ok, reasons = cc.acceptance_verdict(REPO, _record(**over), [CONSOLE + "views/"])
    assert not ok and any(why in r for r in reasons), reasons


def test_the_record_is_what_the_server_reads_with_no_suite_in_it():
    """V0663 fixes (F2): the server builds the record from the repository (CI state, touched paths, secret scan); a
    suite figure was only ever a caller's claim and is no longer asked for."""
    rec = {k: v for k, v in _record().items() if k != "suite"}
    assert cc.acceptance_verdict(REPO, rec, [CONSOLE + "views/"]) == (True, [])


# --- review ------------------------------------------------------------------------------------------------------

def _rev(dev, verdict, commit=SHA, at=1):
    return {"reviewer_developer_id": dev, "verdict": verdict, "commit": commit, "at": at}


def test_one_independent_approval_on_the_commit_opens_a_plain_change():
    v = cc.reviews_verdict([_rev(7, "approve")], SHA, sensitive=False, excluded={1, 2})
    assert v.ok and v.approvals == 1 and v.needed == 1


def test_a_sensitive_change_needs_two():
    one = cc.reviews_verdict([_rev(7, "approve")], SHA, sensitive=True, excluded=set())
    assert not one.ok and one.needed == 2
    two = cc.reviews_verdict([_rev(7, "approve"), _rev(8, "approve")], SHA, sensitive=True, excluded=set())
    assert two.ok


def test_the_proposer_and_the_worker_do_not_count_nor_another_commit():
    v = cc.reviews_verdict([_rev(1, "approve"), _rev(2, "approve"), _rev(7, "approve", commit=SHA2)], SHA,
                           sensitive=False, excluded={1, 2})
    assert not v.ok and v.approvals == 0


def test_a_reviewers_latest_word_counts_and_changes_hold_the_ballot():
    held = cc.reviews_verdict([_rev(7, "approve", at=1), _rev(8, "approve", at=1), _rev(8, "changes", at=2)], SHA,
                              sensitive=False, excluded=set())
    assert not held.ok and held.blockers == [8]
    cleared = cc.reviews_verdict([_rev(7, "approve", at=1), _rev(7, "changes", at=2), _rev(7, "approve", at=3)], SHA,
                                 sensitive=False, excluded=set())
    assert cleared.ok and cleared.blockers == []


# --- ballot thresholds -------------------------------------------------------------------------------------------

def test_the_ballot_takes_the_frame_policys_pairs():
    policy = {"governance.standard_quorum_percent": 12.0, "governance.standard_pass_percent": 55.0,
              "governance.policy_change_quorum_percent": 25.0, "governance.policy_change_pass_percent": 70.0}
    assert cc.thresholds(policy, sensitive=False) == (12.0, 55.0)
    assert cc.thresholds(policy, sensitive=True) == (25.0, 70.0)
    assert cc.thresholds({}, sensitive=True) == (20.0, 66.0)
    assert cc.thresholds({}, sensitive=False) == (10.0, 50.0)


# --- merge -------------------------------------------------------------------------------------------------------

NOW = dt.datetime(2026, 11, 20, 12, tzinfo=dt.timezone.utc)


def _merge(**over):
    args = dict(state="passed", proposal_status="PASSED", passed_at=NOW - dt.timedelta(hours=30), now=NOW,
                vetoed=False, go=False, voted_commit=SHA, merge_commit=SHA, window_hours=24)
    args.update(over)
    return cc.merge_allowed(**args)


def test_a_passed_change_merges_once_the_window_closed():
    assert _merge() == (True, None)


def test_inside_the_window_only_his_go_lets_it_merge():
    early = dict(passed_at=NOW - dt.timedelta(hours=10))
    ok, why = _merge(**early)
    assert not ok and "veto window" in why
    assert _merge(go=True, **early) == (True, None)


@pytest.mark.parametrize("over,why", [
    ({"vetoed": True}, "vetoed"),
    ({"proposal_status": "FAILED", "state": "failed"}, "did not pass"),
    ({"proposal_status": "VOTING", "state": "balloting"}, "did not pass"),
    ({"merge_commit": SHA2}, "the commit that was voted"),
    ({"state": "merged"}, "already merged"),
])
def test_no_merge_without_a_pass_or_after_a_veto_or_of_another_tree(over, why):
    ok, reason = _merge(**over)
    assert not ok and why in reason, reason


def test_the_veto_window_comes_from_the_environment(monkeypatch):
    """24 h by default (session-lead, room seq 3407)."""
    assert cc.veto_window_hours() == 24
    monkeypatch.setenv("CODE_CHANGE_VETO_HOURS", "48")
    assert cc.veto_window_hours() == 48
    monkeypatch.setenv("CODE_CHANGE_VETO_HOURS", "nonsense")
    assert cc.veto_window_hours() == 24
