"""V0667 D4, upstream (order gwo_b12f07e4c5adaa1f5bf4d115; sessionlogs2026/DESIGN_2026-11-15_DISTRIBUTIONS.md section 4): a change merged in an
organization's release line is proposed to the main code, with its history. Driven through services/code_changes against an in-memory store
(DbStore's half and the real route are tests/test_code_upstream_v0667_db.py, on a real Postgres).

  the action     ONE: "propose upstream" on a MERGED line change. It creates a normal Code change on the main line for the SAME commit
  who            the line's deciders (D1's one rule), through one of their agents; never a member, a guest or a stranger
  provenance     kept on the new change and shown: the line, its ballot and result, its reviews, the checker's record; NOTHING is dropped
  from there     an ordinary change: the checker signs the commit again, the reviews, the frame's ballot or his go, the merge record
  once merged    the line's own copy says "upstream since <change>" (D6 reads that mark); until then it says the proposal and its state
  refusals       a main-line change, an unmerged line change, a stranger, a second proposal, a path no longer open: each with its sentence
  the room       a line card posts one line when the change goes upstream and one when it lands
Red before: CodeChangeFlow has no propose_upstream.
"""
from __future__ import annotations

import copy
import datetime as dt

import pytest

from agentvault_registry.services import chat_live_cards as lc
from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import REPO, SHA, T0, acceptance_record, release_line_record
from tests.test_code_distributions_v0666 import (ADMIN, DOC, ORG, OPEN, PROPOSER, LineStore, _call, _flow, _line, _merge,
                                                 _passed, _refused, run)
from tests.test_code_distributions_v0666 import _env  # noqa: F401  (the autouse switches)

DECIDER = {"did": "did:a:2", "developer_id": 2}          # the organization's owner
MEMBER = {"did": "did:a:6", "developer_id": 6}           # a member who does not decide
STRANGER = {"did": "did:a:8", "developer_id": 8}         # not in the organization
BRANCH = "distribution/V0666_lyceum"


def _store():
    s = LineStore()
    s.members = {6, 8}                                    # the FRAME's members: the main line's reviewers and voters
    return s


def _merged_line_change():
    s = _store()
    cid = _passed(s)
    run(_flow(s).go(ADMIN, cid))                          # the maintainer's go ends the veto window
    run(_merge(s, cid))
    assert s.rows[cid]["state"] == "merged"
    return s, cid


def _upstream(s, cid, actor=DECIDER):
    return run(_flow(s).propose_upstream(actor, cid))


# --- the action ---------------------------------------------------------------------------------------------------------------

def test_a_merged_line_change_is_proposed_upstream_as_a_main_line_change_for_the_same_commit():
    s, cid = _merged_line_change()
    out = _upstream(s, cid)
    line = s.rows[cid]
    assert out["id"] != cid and out["state"] == "proposed"
    assert out["commit"] == line["merged"]["commit"] == SHA and out["repository"] == line["repository"]
    assert out["paths"] == line["paths"] and out["title"] == line["title"]
    assert out["upstream_of"] == cid
    assert "code_distribution" not in out and "line_ballot" not in out            # a main-line change reads as one
    assert out["proposer_developer_id"] == DECIDER["developer_id"] and s.rows[out["id"]].get("code_distribution_id") is None


def test_the_provenance_travels_unchanged_and_fails_if_any_field_is_dropped():
    s, cid = _merged_line_change()
    out = _upstream(s, cid)
    line, dist = s.rows[cid], s.dists[s.rows[cid]["code_distribution_id"]]
    want = {
        "line": {"id": dist["id"], "slug": dist["slug"], "title": dist["title"], "base_release": dist["base_release"],
                 "organization_id": dist["organization_id"], "organization_name": s.org_names[ORG], "branch": BRANCH},
        "line_change": {"id": cid, "title": line["title"], "problem": line["problem"], "branch": line["branch"],
                        "commit": line["commit"], "paths": line["paths"], "proposer_did": line["proposer_did"],
                        "proposer_developer_id": line["proposer_developer_id"], "merged": line["merged"]},
        "ballot": {"rule": line["ballot_rule"], "ends": cc._iso(line["ballot_ends"]), "result": line["ballot_result"],
                   "org_go": line.get("org_go")},
        "reviews": [{k: r.get(k) for k in ("reviewer_developer_id", "verdict", "commit", "findings", "at")}
                    for r in s.revs if r["code_change_id"] == cid],
        "checker": line["acceptance"],
    }
    got = s.rows[out["id"]]["provenance"]
    assert got == want
    assert got["reviews"] and got["checker"]["record"]["commit"] == SHA and got["ballot"]["result"]["status"] == "PASSED"
    for top in want:                                             # the control: a dropped field is a difference
        dropped = copy.deepcopy(got)
        dropped.pop(top)
        assert dropped != want
    assert out["provenance"] == got                              # and the public view carries all of it


def test_a_line_change_that_is_not_proposed_upstream_carries_none_of_the_three_fields():
    s, cid = _merged_line_change()
    v = run(_flow(s).view(cid))
    assert v["upstream"] is None and "upstream_of" not in v and "provenance" not in v and "upstream_since" not in v
    main = _store()
    main_id = run(_flow(main).propose({"did": "did:a:6", "developer_id": 6}, {
        "repository": REPO, "paths": [DOC], "title": "T", "problem": "P", "branch": "b", "commit": SHA}))["id"]
    mv = run(_flow(main).view(main_id))
    assert not ({"upstream", "upstream_of", "provenance", "upstream_since"} & set(mv))      # a main-line change reads as it always did


# --- who, and when ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("actor", [MEMBER, STRANGER, PROPOSER])
def test_only_the_lines_deciders_propose_upstream(actor):
    s, cid = _merged_line_change()
    e = _refused(_flow(s).propose_upstream(actor, cid), 403, "not_a_decider")
    assert "decider" in e.sentence and not any(r.get("upstream_of") for r in s.rows.values())


def test_a_decider_of_another_organizations_line_does_not_propose_this_ones_change_upstream():
    s, cid = _merged_line_change()
    s.members_of["org-other"] = {8: "owner"}
    s.orgs.add("org-other")
    _refused(_flow(s).propose_upstream({"did": "did:a:8", "developer_id": 8}, cid), 403, "not_a_decider")


def test_a_main_line_change_is_refused_with_its_sentence():
    s = _store()
    main_id = run(_flow(s).propose({"did": "did:a:6", "developer_id": 6}, {
        "repository": REPO, "paths": [DOC], "title": "T", "problem": "P", "branch": "b", "commit": SHA}))["id"]
    e = _refused(_flow(s).propose_upstream(DECIDER, main_id), 409, "main_line")
    assert "release line" in e.sentence


@pytest.mark.parametrize("state", ["proposed", "accepted", "balloting", "passed", "failed", "vetoed", "withdrawn"])
def test_a_line_change_that_is_not_merged_is_refused_with_its_sentence(state):
    s, cid = _merged_line_change()
    s.rows[cid]["state"] = state
    e = _refused(_flow(s).propose_upstream(DECIDER, cid), 409, "not_merged")
    assert state in e.sentence and "merged" in e.sentence


def test_a_second_proposal_of_the_same_change_is_refused_and_names_the_first():
    s, cid = _merged_line_change()
    first = _upstream(s, cid)
    e = _refused(_flow(s).propose_upstream(DECIDER, cid), 409, "already_upstream")
    assert first["id"] in e.sentence


def test_a_path_the_main_code_no_longer_opens_is_refused():
    s, cid = _merged_line_change()
    s.rows[cid]["paths"] = [CONSOLE_KEYS]
    _refused(_flow(s).propose_upstream(DECIDER, cid), 422, "path_refused")


CONSOLE_KEYS = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/package.json"


def test_a_line_that_is_paused_still_proposes_its_merged_change_upstream():
    """A pause stops a line's own work; what it already merged is the main code's to look at."""
    s, cid = _merged_line_change()
    s.dists[s.rows[cid]["code_distribution_id"]].update(state="paused", paused_reason="r", paused_by_developer_id=99)
    assert _upstream(s, cid)["upstream_of"] == cid


# --- from there it is an ordinary change; once merged the line's copy says so ---------------------------------------------

def _land(s, ucid):
    """The upstream change through the main line's own steps: the checker's record, a review by a frame member, the frame's ballot, the
    merge. (Nothing here is special to upstream: that is the point.)"""
    s.repo.touched[SHA] = [DOC]
    run(_flow(s).record_acceptance(ADMIN, ucid, {"signed": acceptance_record(s, ucid, SHA)}))
    run(_flow(s).review({"developer_id": 6}, ucid, {"verdict": "approve", "commit": SHA, "findings": "read"}))
    run(_flow(s).open_ballot(DECIDER, ucid))
    s.proposals[1].update(status="PASSED", tallied_at=T0)
    s.clock = T0 + dt.timedelta(hours=30)
    s.repo.contained.add(("v0663/cut", SHA))
    return run(_flow(s).record_merge(ADMIN, ucid, {"commit": SHA, "into": "v0663/cut",
                                                   "signed": release_line_record(s, ucid, SHA, "v0663/cut")}))


def test_the_upstream_change_runs_the_main_lines_own_steps_and_the_checker_signs_the_commit_again():
    s, cid = _merged_line_change()
    ucid = _upstream(s, cid)["id"]
    assert s.rows[ucid]["acceptance"] is None                    # nothing is carried over: the checker reads it again
    out = _land(s, ucid)
    assert out["state"] == "merged" and out["merged"]["into"] == "v0663/cut"
    assert s.rows[ucid]["acceptance"]["record"]["read_from"] == "checker"


def test_until_it_lands_the_lines_own_copy_says_the_proposal_and_its_state():
    s, cid = _merged_line_change()
    ucid = _upstream(s, cid)["id"]
    v = run(_flow(s).view(cid))
    assert v["upstream"] == {"change_id": ucid, "state": "proposed", "since": None}
    assert "upstream_since" not in v or v["upstream_since"] is None


def test_once_merged_upstream_the_lines_own_copy_is_marked_upstream_since_that_change():
    s, cid = _merged_line_change()
    ucid = _upstream(s, cid)["id"]
    _land(s, ucid)
    mark = s.rows[cid]["upstream_since"]
    assert mark["change_id"] == ucid and mark["at"]
    v = run(_flow(s).view(cid))
    assert v["upstream"] == {"change_id": ucid, "state": "merged", "since": mark["at"]}
    assert v["upstream_since"]["change_id"] == ucid                # the mark D6 reads, on the line's own row


def test_a_change_that_never_lands_upstream_leaves_the_lines_copy_unmarked():
    s, cid = _merged_line_change()
    ucid = _upstream(s, cid)["id"]
    run(_flow(s).withdraw({"did": "did:a:2", "developer_id": 2}, ucid, {"reason": "not now"}))
    assert s.rows[ucid]["state"] == "withdrawn" and s.rows[cid].get("upstream_since") is None
    assert run(_flow(s).view(cid))["upstream"]["state"] == "withdrawn"


# --- the room's card says when a line's change went upstream ------------------------------------------------------------------

def test_the_rooms_state_word_follows_the_upstream_and_its_lines_say_so():
    view = {"id": "cc_x", "title": "A clearer page", "state": "merged", "code_distribution": {"release_name": "V0666_lyceum",
                                                                                           "branch": BRANCH}}
    assert lc.room_state(view) == "merged"
    assert lc.room_state({**view, "upstream": {"change_id": "cc_u", "state": "proposed", "since": None}}) == "upstreaming"
    assert lc.room_state({**view, "upstream": {"change_id": "cc_u", "state": "withdrawn", "since": None}}) == "merged"
    assert lc.room_state({**view, "upstream": {"change_id": "cc_u", "state": "merged", "since": "2026-11-20T10:00:00+00:00"}}) == "upstream"
    assert lc.room_state({**view, "state": "balloting", "upstream": None}) == "balloting"
    up = {**view, "upstream": {"change_id": "cc_u", "state": "proposed", "since": None}}
    assert "proposed upstream" in lc.code_change_state_line("merged", up)
    done = {**view, "upstream": {"change_id": "cc_u", "state": "merged", "since": "2026-11-20T10:00:00+00:00"}}
    said = lc.code_change_state_line("upstreaming", done)
    assert "upstream since" in said and "cc_u" in said
    assert lc.code_change_state_line("upstream", done) is None          # once


def test_the_card_names_the_upstream_and_validates():
    view = {"id": "cc_x", "title": "T", "state": "merged", "code_distribution": {"slug": "lyceum", "title": "L"},
            "upstream": {"change_id": "cc_u", "state": "proposed", "since": None}}
    card = lc.code_change_card(view)
    assert card["data"]["upstream"] == {"change_id": "cc_u", "state": "proposed", "since": None}
    assert lc.validate_code_change_live(card["data"]) is None
    assert "upstream" not in lc.code_change_card({**view, "upstream": None})["data"]


# --- the routes ---------------------------------------------------------------------------------------------------------------

class _DeciderAgent:
    did, creator_developer_id = "did:a:2", 2


def _route_app(monkeypatch, store, agent=_DeciderAgent):
    from tests.test_code_distributions_v0666 import _app
    from agentvault_registry.routers import code_changes as cc_route
    from agentvault_registry.routers.utils import get_current_agent
    from agentvault_registry.services import repo_accounts

    async def linked(self, developer_id):
        return None
    monkeypatch.setattr(repo_accounts.RepoAccounts, "require_linked", linked)
    app = _app(monkeypatch, store)
    app.dependency_overrides[get_current_agent] = lambda: agent()
    return app


def test_switched_off_the_upstream_route_answers_404(monkeypatch):
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "false")
    r = _call(_route_app(monkeypatch, _store()), "POST", "/api/v1/code-changes/cc_x/upstream")
    assert r.status_code == 404


def test_the_upstream_route_proposes_and_answers_201_with_the_provenance(monkeypatch):
    s, cid = _merged_line_change()
    r = _call(_route_app(monkeypatch, s), "POST", f"/api/v1/code-changes/{cid}/upstream")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["upstream_of"] == cid and body["provenance"]["line"]["slug"] == "lyceum"
    again = _call(_route_app(monkeypatch, s), "POST", f"/api/v1/code-changes/{cid}/upstream")
    assert again.status_code == 409 and again.json()["code"] == "already_upstream"


def test_the_upstream_route_refuses_a_stranger_with_its_sentence(monkeypatch):
    class Stranger:
        did, creator_developer_id = "did:a:8", 8
    s, cid = _merged_line_change()
    r = _call(_route_app(monkeypatch, s, Stranger), "POST", f"/api/v1/code-changes/{cid}/upstream")
    assert r.status_code == 403 and r.json()["code"] == "not_a_decider"


def test_the_list_names_the_upstream_proposals_and_their_fate(monkeypatch):
    s, cid = _merged_line_change()
    ucid = _upstream(s, cid)["id"]
    app = _route_app(monkeypatch, s)
    got = _call(app, "GET", "/api/v1/code-changes?upstream=true").json()["code_changes"]
    assert [c["id"] for c in got] == [ucid] and got[0]["state"] == "proposed" and got[0]["upstream_of"] == cid
    assert got[0]["provenance"]["line"]["slug"] == "lyceum"
    everything = _call(app, "GET", "/api/v1/code-changes").json()["code_changes"]
    assert ucid in [c["id"] for c in everything]
