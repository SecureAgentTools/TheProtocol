"""V0666 D1, code distributions (order gwo_f1c05b131b9208a94074beae; the design note
sessionlogs2026/DESIGN_2026-11-15_D1_DISTRIBUTIONS_MODEL_NOTE.md, session-lead's answers room seq 4629 and 4637): an
organization's release line, driven through services/code_distributions and the Code changes flow against an in-memory
store (DbStore's half is tests/test_code_distributions_v0666_db.py, on a real Postgres).

  the line    an owner or admin creates it; its paths are a subset of the platform's (never a forbidden or core path);
              quorum 50-100; the deciding team is the organization's own; a pause needs a reason (admin_platform)
  propose     a member of the organization (never a guest), the line active, the paths inside the line's
  review      another developer of the organization, never the proposer's own
  ballot      the line's OWN: no governance proposal is opened; the rule is snapshotted at the open
  deciders    owners and admins plus the deciding team's leads, each a current non-guest member in good standing (one
              function); a role taken away takes its vote with it; a team that is gone is said, never a fall back
  close       early once EVERY current decider has voted, else at its end; no deciders is FAILED with a sentence
  go / veto   the organization owner vetoes, and records a go that never shortens the window; only the platform
              maintainer's go closes it early; the maintainer's go never overrides a line's ballot
  merge       into the line's branch, on the checker's record, the paths checked again, never while paused
  main line   a change without a line reads exactly as before; the governance tally is not touched
  switch      CODE_DISTRIBUTIONS_ENABLED off: every new route answers 404
Red on 2200f0c46: services/code_distributions does not exist.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import pathlib

import httpx
import pytest

from agentvault_registry.services import code_changes as cc
from agentvault_registry.services import code_distributions as cd
from tests.test_code_changes_flow_v0663 import (CHECKER_PUB_B64, CONSOLE, REPO, SHA, FakeStore, acceptance_record,
                                                release_line_record)

ORG, TEAM = "org-lyceum", "team-core"
OPEN = [CONSOLE + "assets/docs/"]
DOC = CONSOLE + "assets/docs/lyceum.md"
# developers: 1 the proposer (a member), 2 owner, 3 admin, 4 a team lead (member), 5 a team lead (guest), 6 a member,
# 7 a guest, 8 not in the organization; 99 the platform maintainer
ROLES = {1: "member", 2: "owner", 3: "admin", 4: "member", 5: "guest", 6: "member", 7: "guest"}
PROPOSER = {"did": "did:a:proposer", "developer_id": 1}
ADMIN = {"developer_id": 99, "admin": True}


class LineStore(FakeStore):
    """FakeStore plus the line's half of the store: the lines, the organization's members, its teams, the developers in
    good standing, the votes."""

    def __init__(self, **kw):
        super().__init__(members=kw.pop("members", ()), **kw)
        self.dists, self.votes = {}, []
        self.members_of = {ORG: dict(ROLES)}
        self.teams = {TEAM: {"organization_id": ORG, "is_active": True}}
        self.leads = {TEAM: {4, 5}}
        self.good = {1, 2, 3, 4, 5, 6, 7, 8, 99}
        self.orgs = {ORG}
        self.org_owners = {ORG: 2}
        self.org_names = {ORG: "Lyceum Labs"}
        self.agents.update({f"did:a:{d}": d for d in range(2, 9)})

    async def distribution(self, did):
        return dict(self.dists[did]) if did in self.dists else None

    async def distribution_by_slug(self, slug):
        return next((dict(d) for d in self.dists.values() if d["slug"] == slug), None)

    async def distributions(self, org_id):
        return [dict(d) for d in self.dists.values() if org_id is None or d["organization_id"] == org_id]

    async def insert_distribution(self, row):
        self.dists[row["id"]] = dict(row)

    async def update_distribution(self, did, **fields):
        self.dists[did].update(fields)

    async def organization(self, org_id):
        return org_id in self.orgs

    async def list(self, state, limit, code_distribution_id=None, upstream=False):
        rows = [dict(r) for r in self.rows.values() if r.get("code_distribution_id") == code_distribution_id
                and (state is None or r["state"] == state) and (not upstream or r.get("upstream_of"))]
        return rows[:limit]

    async def upstream_for(self, cid):         # V0667 D4: the main-line change that carries this line change upstream
        return next((dict(r) for r in self.rows.values() if r.get("upstream_of") == cid), None)

    async def prefetch(self, rows):
        return None

    async def organization_names(self, ids):
        return {i: self.org_names[i] for i in ids if i in self.org_names}

    async def org_members(self, org_id):
        return dict(self.members_of.get(org_id, {}))

    async def team(self, team_id):
        return dict(self.teams[team_id]) if team_id in self.teams else None

    async def team_leads(self, team_id):
        return set(self.leads.get(team_id, set()))

    async def developers_in_good_standing(self, ids):
        return {i for i in ids if i in self.good}

    async def distribution_votes(self, cid):
        return [dict(v) for v in self.votes if v["code_change_id"] == cid]

    async def add_distribution_vote(self, row):
        self.votes.append(dict(row))


def run(c):
    return asyncio.run(c)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    monkeypatch.setenv("CODE_CHANGES_MAINTAINER", "99")
    monkeypatch.setenv("CODE_CHANGES_RELEASE_BRANCHES", "v0663/cut")
    monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", CHECKER_PUB_B64)


def _refused(coro, status, code):
    with pytest.raises(cc.CodeChangeRefusal) as e:
        run(coro)
    assert (e.value.status, e.value.code) == (status, code), (e.value.status, e.value.code, e.value.sentence)
    return e.value


def _line(s, **over):
    body = {"organization_id": ORG, "slug": "lyceum", "title": "Lyceum's line", "base_release": "V0666",
            "open_paths": OPEN, "decider_team_id": TEAM, "quorum_percent": 50}
    body.update(over)
    return run(cd.CodeDistributionFlow(s).create({"developer_id": 2}, body))


def _flow(s):
    return cc.CodeChangeFlow(s)


def _proposed(s, actor=PROPOSER, **over):
    body = {"repository": REPO, "paths": [DOC], "title": "A clearer page", "problem": "The page says too little.",
            "branch": "lyceum/clearer", "commit": SHA, "code_distribution": "lyceum"}
    body.update(over)
    return run(_flow(s).propose(actor, body))


def _balloting(s, reviewers=(6,)):
    """A line, a change, its checker record and review, its ballot open."""
    _line(s)
    cid = _proposed(s)["id"]
    s.repo.touched[SHA] = [DOC]
    run(_flow(s).record_acceptance(ADMIN, cid, {"signed": acceptance_record(s, cid, SHA, base="distribution/V0666_lyceum")}))
    for r in reviewers:
        run(_flow(s).review({"developer_id": r}, cid, {"verdict": "approve", "commit": SHA, "findings": "read"}))
    run(_flow(s).open_ballot(PROPOSER, cid))
    return cid


def _vote(s, cid, dev, vote=True):
    return run(_flow(s).line_vote({"did": f"did:a:{dev}", "developer_id": dev}, cid, {"vote": vote}))


# --- the line --------------------------------------------------------------------------------------------------------

def test_an_owner_creates_a_line_named_for_its_release():
    s = LineStore()
    out = _line(s)
    assert out["release_name"] == "V0666_lyceum" and out["branch"] == "distribution/V0666_lyceum"
    assert out["state"] == "active" and out["quorum_percent"] == 50 and "not an AGORA payout" in out["what"]


@pytest.mark.parametrize("over,status,code", [
    ({"slug": "Lyceum"}, 422, "slug"),
    ({"base_release": "v666"}, 422, "base_release"),
    ({"quorum_percent": 49}, 422, "quorum_percent"),
    ({"quorum_percent": 101}, 422, "quorum_percent"),
    ({"pass_rule": "two_thirds"}, 422, "pass_rule"),            # later, with its own CHECK (seq 4629)
    ({"open_paths": ["agentvault_registry/src/agentvault_registry/routers/teg_integration.py"]}, 422, "open_paths"),
    ({"open_paths": [CONSOLE + ".env"]}, 422, "open_paths"),     # a forbidden path stays closed
    ({"open_paths": []}, 422, "open_paths"),
    ({"decider_team_id": "team-elsewhere"}, 422, "decider_team"),
    ({"organization_id": "org-none"}, 404, "no_organization"),
])
def test_a_line_outside_the_bounds_is_refused(over, status, code):
    s = LineStore()
    s.teams["team-elsewhere"] = {"organization_id": "org-other", "is_active": True}
    body = {"organization_id": ORG, "slug": "lyceum", "title": "T", "base_release": "V0666", "open_paths": OPEN,
            "decider_team_id": TEAM, **over}
    _refused(cd.CodeDistributionFlow(s).create({"developer_id": 2}, body), status, code)
    assert s.dists == {}


def test_only_an_owner_or_admin_creates_or_changes_a_line_and_a_name_is_the_frames_once():
    s = LineStore()
    for dev in (1, 4, 7, 8):
        _refused(cd.CodeDistributionFlow(s).create({"developer_id": dev}, {"organization_id": ORG, "slug": "x1",
                 "title": "T", "base_release": "V0666", "open_paths": OPEN}), 403, "not_owner_or_admin")
    _line(s)
    _refused(cd.CodeDistributionFlow(s).create({"developer_id": 3}, {"organization_id": ORG, "slug": "lyceum",
             "title": "T", "base_release": "V0666", "open_paths": OPEN}), 409, "slug_taken")
    _refused(cd.CodeDistributionFlow(s).update({"developer_id": 1}, "lyceum", {"title": "x"}), 403, "not_owner_or_admin")
    _refused(cd.CodeDistributionFlow(s).update({"developer_id": 2}, "lyceum", {"slug": "other"}), 422, "fixed")


def test_the_platform_pauses_a_line_with_a_reason_and_a_paused_line_takes_nothing():
    s = LineStore()
    cid = _balloting(s)
    _refused(cd.CodeDistributionFlow(s).pause({"developer_id": 2}, "lyceum", "no"), 403, "admin_only")
    _refused(cd.CodeDistributionFlow(s).pause(ADMIN, "lyceum", "  "), 422, "reason")
    out = run(cd.CodeDistributionFlow(s).pause(ADMIN, "lyceum", "a review of the line"))
    assert out["state"] == "paused" and out["paused_reason"] == "a review of the line" and out["paused_by_developer_id"] == 99
    _refused(_flow(s).propose(PROPOSER, {"repository": REPO, "paths": [DOC], "title": "T", "problem": "P",
             "branch": "b", "commit": SHA, "code_distribution": "lyceum"}), 409, "line_paused")
    e = _refused(_flow(s).line_vote({"did": "did:a:2", "developer_id": 2}, cid, {"vote": True}), 409, "line_paused")
    assert "a review of the line" in e.sentence
    run(cd.CodeDistributionFlow(s).resume(ADMIN, "lyceum"))
    assert _vote(s, cid, 2)["line_ballot"]["votes"] == 1


# --- propose and review ----------------------------------------------------------------------------------------------

def test_a_member_of_the_organization_proposes_into_its_line_without_being_a_frame_member():
    s = LineStore()                                   # members=(): nobody is a member of the FRAME
    _line(s)
    out = _proposed(s)
    assert out["state"] == "proposed" and out["code_distribution"]["release_name"] == "V0666_lyceum"
    assert out["code_distribution_id"] and out["line_ballot"]["votes"] == 0


@pytest.mark.parametrize("dev,status,code", [(7, 403, "not_org_member"), (8, 403, "not_org_member")])
def test_a_guest_or_an_outsider_does_not_propose(dev, status, code):
    s = LineStore()
    _line(s)
    _refused(_flow(s).propose({"did": f"did:a:{dev}", "developer_id": dev}, {"repository": REPO, "paths": [DOC],
             "title": "T", "problem": "P", "branch": "b", "commit": SHA, "code_distribution": "lyceum"}), status, code)


def test_a_path_outside_the_line_is_refused_though_the_platform_opens_it():
    s = LineStore()
    _line(s)
    e = _refused(_flow(s).propose(PROPOSER, {"repository": REPO, "paths": [CONSOLE + "views/GuildBoard.vue"],
                 "title": "T", "problem": "P", "branch": "b", "commit": SHA, "code_distribution": "lyceum"}),
                 422, "path_refused")
    assert "not open in this line" in e.sentence


def test_reviews_are_another_developer_of_the_organization():
    s = LineStore(members=(8,))                       # 8 is a member of the FRAME, not of the organization
    _line(s)
    cid = _proposed(s)["id"]
    s.repo.touched[SHA] = [DOC]
    run(_flow(s).record_acceptance(ADMIN, cid, {"signed": acceptance_record(s, cid, SHA, base="distribution/V0666_lyceum")}))
    body = {"verdict": "approve", "commit": SHA, "findings": "read"}
    _refused(_flow(s).review({"developer_id": 1}, cid, body), 403, "not_independent")
    _refused(_flow(s).review({"developer_id": 8}, cid, body), 403, "not_org_member")
    _refused(_flow(s).review({"developer_id": 7}, cid, body), 403, "not_org_member")
    assert run(_flow(s).review({"developer_id": 6}, cid, body))["review_verdict"]["ok"] is True


# --- the line's own ballot -------------------------------------------------------------------------------------------

def test_the_ballot_is_the_lines_own_and_its_rule_is_snapshotted_at_the_open():
    s = LineStore()
    cid = _balloting(s)
    row = s.rows[cid]
    assert row["state"] == "balloting" and row["proposal_id"] is None and s.proposals == {}, "no governance proposal"
    assert row["ballot_rule"] == {"quorum_percent": 50, "pass_rule": "simple", "decider_team_id": TEAM}
    run(cd.CodeDistributionFlow(s).update({"developer_id": 2}, "lyceum", {"quorum_percent": 100}))
    assert s.rows[cid]["ballot_rule"]["quorum_percent"] == 50, "a PATCH changes later ballots only"


def test_the_deciders_are_owners_admins_and_the_teams_non_guest_leads_in_good_standing():
    s = LineStore()
    _line(s)
    who, why = run(cd.deciders(s, s.dists[next(iter(s.dists))]))
    assert who == {2, 3, 4} and why is None, "the guest lead (5) does not decide"
    s.good.discard(3)                                 # suspended, unverified or pending deletion
    assert run(cd.deciders(s, s.dists[next(iter(s.dists))]))[0] == {2, 4}


def test_only_a_decider_votes_once_and_every_decider_voting_closes_it_early():
    s = LineStore()
    cid = _balloting(s)
    _refused(_flow(s).line_vote({"did": "did:a:6", "developer_id": 6}, cid, {"vote": True}), 403, "not_a_decider")
    _refused(_flow(s).line_vote({"did": "did:a:5", "developer_id": 5}, cid, {"vote": True}), 403, "not_a_decider")
    _vote(s, cid, 2)
    _refused(_flow(s).line_vote({"did": "did:a:2", "developer_id": 2}, cid, {"vote": False}), 409, "already_voted")
    assert _vote(s, cid, 3, False)["state"] == "balloting", "not every decider has voted"
    out = _vote(s, cid, 4)
    assert out["state"] == "passed" and out["line_ballot"]["result"]["early"] is True
    res = out["line_ballot"]["result"]
    assert (res["for"], res["against"], res["deciders"], res["status"]) == (2, 1, 3, "PASSED")


def test_at_its_end_a_ballot_below_its_quorum_fails_and_says_why():
    s = LineStore()
    cid = _balloting(s)
    run(cd.CodeDistributionFlow(s).update({"developer_id": 2}, "lyceum", {"quorum_percent": 100}))
    _vote(s, cid, 2)                                  # 1 of 3: below the snapshotted 50 percent
    s.clock += dt.timedelta(days=cc.ballot_days(), seconds=1)
    out = run(_flow(s).view(cid))
    res = out["line_ballot"]["result"]
    assert out["state"] == "failed" and res["quorum_met"] is False and res["early"] is False
    assert "below the quorum of 50 percent" in res["sentence"]


def test_a_role_taken_away_takes_its_vote_with_it():
    s = LineStore()
    cid = _balloting(s)
    _vote(s, cid, 2)
    _vote(s, cid, 3)
    s.members_of[ORG][3] = "member"                    # no longer an admin
    s.clock += dt.timedelta(days=cc.ballot_days(), seconds=1)
    res = run(_flow(s).view(cid))["line_ballot"]["result"]
    assert (res["deciders"], res["counted"], res["cast"], res["for"]) == (2, 1, 2, 1)


def test_no_deciders_at_the_close_fails_with_a_sentence_never_a_division_by_zero():
    s = LineStore()
    cid = _balloting(s)
    s.teams[TEAM]["is_active"] = False                # the deciding team is gone: never a fall back
    s.clock += dt.timedelta(days=cc.ballot_days(), seconds=1)
    out = run(_flow(s).view(cid))
    res = out["line_ballot"]["result"]
    assert out["state"] == "failed" and res["deciders"] == 0 and "deciding team is gone" in res["sentence"]
    assert cd.tally({"quorum_percent": 50, "pass_rule": "simple"}, [], set())["status"] == "FAILED"


# --- go, veto, merge -------------------------------------------------------------------------------------------------

def _passed(s):
    cid = _balloting(s)
    for d in (2, 3, 4):
        _vote(s, cid, d)
    assert s.rows[cid]["state"] == "passed"
    return cid


def _merge(s, cid, into="distribution/V0666_lyceum"):
    s.repo.contained.add((into, SHA))
    return _flow(s).record_merge(ADMIN, cid, {"commit": SHA, "into": into,
                                              "signed": release_line_record(s, cid, SHA, into)})


def test_the_owners_go_is_recorded_and_never_shortens_the_window():
    s = LineStore()
    cid = _passed(s)
    _refused(_flow(s).line_owner_go({"developer_id": 3}, cid), 403, "not_org_owner")
    out = run(_flow(s).line_owner_go({"developer_id": 2}, cid))
    assert out["org_go"]["by"] == 2 and out["go"] is None
    _refused(_merge(s, cid), 409, "merge_refused")    # the platform's window is still open
    run(_flow(s).go(ADMIN, cid))                       # the platform maintainer's go closes it
    assert run(_merge(s, cid))["state"] == "merged"


def test_the_owner_vetoes_inside_the_window():
    s = LineStore()
    cid = _passed(s)
    out = run(_flow(s).line_owner_veto({"developer_id": 2}, cid, {"reason": "not for us"}))
    assert out["state"] == "vetoed" and out["veto"]["as"] == "organization_owner"


def test_the_maintainers_go_never_overrides_a_lines_ballot():
    s = LineStore()
    cid = _balloting(s)
    for d, v in ((2, False), (3, False), (4, True)):
        _vote(s, cid, d, v)
    assert s.rows[cid]["state"] == "failed"
    _refused(_flow(s).go(ADMIN, cid), 409, "rejected_by_vote")


def test_a_merge_goes_into_the_lines_branch_with_its_paths_checked_again_and_never_while_paused():
    s = LineStore()
    cid = _passed(s)
    run(_flow(s).go(ADMIN, cid))
    _refused(_merge(s, cid, into="v0663/cut"), 409, "not_release_line")
    run(cd.CodeDistributionFlow(s).update({"developer_id": 2}, "lyceum", {"open_paths": [CONSOLE + "views/"]}))
    _refused(_merge(s, cid), 409, "path_refused")      # the line narrowed since the propose
    run(cd.CodeDistributionFlow(s).update({"developer_id": 2}, "lyceum", {"open_paths": OPEN}))
    run(cd.CodeDistributionFlow(s).pause(ADMIN, "lyceum", "a review"))
    _refused(_merge(s, cid), 409, "line_paused")
    run(cd.CodeDistributionFlow(s).resume(ADMIN, "lyceum"))
    out = run(_merge(s, cid))
    assert out["state"] == "merged" and out["merged"]["into"] == "distribution/V0666_lyceum"


# --- the main line and the governance tally, unchanged -----------------------------------------------------------------

def test_a_main_line_change_reads_exactly_as_before():
    s = LineStore(members=(1,))
    out = run(_flow(s).propose(PROPOSER, {"repository": REPO, "paths": [CONSOLE + "views/GuildBoard.vue"], "title": "T",
                                          "problem": "P", "branch": "b", "commit": SHA}))
    for k in cc._LINE_FIELDS + ("code_distribution", "line_ballot"):
        assert k not in out, k
    assert "code_distribution_id" not in s.rows[out["id"]], "the main line's row is written as before"


def test_the_governance_tally_is_not_touched():
    import agentvault_registry.crud.crud_governance as gov
    import ast
    tree = ast.parse(pathlib.Path(cd.__file__).read_text())      # on the code, never the text: the docstring names them
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names} | {
        n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not ({"GovernanceProposal", "Vote", "tally_votes"} & names), names & {"GovernanceProposal", "Vote", "tally_votes"}
    assert not any("crud_governance" in m or "governance" == m.split(".")[-1] for m in imported), imported
    assert "distribution" not in inspect.getsource(gov.tally_votes)
    # the line's ballot opens no proposal (test_the_ballot_is_the_lines_own...); the main line's still does
    s = FakeStore(members=(1, 6))
    out = run(cc.CodeChangeFlow(s).propose(PROPOSER, {"repository": REPO, "paths": [CONSOLE + "views/A.vue"], "title": "T",
                                                      "problem": "P", "branch": "b", "commit": SHA}))
    s.repo.touched[SHA] = [CONSOLE + "views/A.vue"]
    run(cc.CodeChangeFlow(s).record_acceptance(ADMIN, out["id"], {"signed": acceptance_record(s, out["id"], SHA)}))
    run(cc.CodeChangeFlow(s).review({"developer_id": 6}, out["id"], {"verdict": "approve", "commit": SHA, "findings": "r"}))
    run(cc.CodeChangeFlow(s).open_ballot(PROPOSER, out["id"]))
    assert len(s.proposals) == 1 and s.rows[out["id"]]["proposal_id"] == 1


# --- the switch --------------------------------------------------------------------------------------------------------

class _Agent:
    did, creator_developer_id = "did:a:proposer", 1


class _Dev:
    id, is_admin, admin_platform, must_change_password = 2, False, False, False


def _app(monkeypatch, store):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import code_changes as cc_route
    from agentvault_registry.routers import code_distributions as cd_route
    from agentvault_registry.routers.utils import get_current_agent
    from agentvault_registry.security import get_current_developer

    monkeypatch.setattr(cc, "store_for", lambda db, agent=None: store)
    app = FastAPI()
    app.include_router(cc_route.router)
    app.include_router(cd_route.router)

    async def get_db():
        yield None
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[get_current_agent] = lambda: _Agent()
    app.dependency_overrides[get_current_developer] = lambda: _Dev()
    app.dependency_overrides[cd_route._ADMIN] = lambda: _Dev()
    return app


def _call(app, method, path, body=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.request(method, path, json=body)
    return asyncio.run(go())


ROUTES = [("POST", "/api/v1/code-distributions", {"organization_id": ORG, "slug": "lyceum", "title": "T",
                                                  "base_release": "V0666", "open_paths": OPEN}),
          ("GET", "/api/v1/code-distributions/lyceum", None),
          ("PATCH", "/api/v1/code-distributions/lyceum", {"title": "x"}),
          ("GET", f"/api/v1/organizations/{ORG}/code-distributions", None),
          ("GET", "/api/v1/admin/code-distributions", None),
          ("POST", "/api/v1/admin/code-distributions/lyceum/pause", {"reason": "r"}),
          ("POST", "/api/v1/admin/code-distributions/lyceum/resume", None),
          ("POST", "/api/v1/code-changes/cc_x/code-distribution-vote", {"vote": True}),
          ("POST", "/api/v1/code-changes/cc_x/code-distribution-veto", {"reason": "r"}),
          ("POST", "/api/v1/code-changes/cc_x/code-distribution-go", None),
          ("GET", "/api/v1/code-changes?code_distribution=lyceum", None),
          ("POST", "/api/v1/code-changes", {"repository": REPO, "paths": [DOC], "title": "T", "problem": "P",
                                            "branch": "b", "commit": SHA, "code_distribution": "lyceum"})]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_switched_off_every_new_route_answers_404(monkeypatch, method, path, body):
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "false")
    app = _app(monkeypatch, LineStore())
    r = _call(app, method, path, body)
    assert r.status_code == 404, (method, path, r.status_code, r.text[:200])


def test_switched_on_a_line_is_created_and_read_through_the_routes(monkeypatch):
    store = LineStore()
    app = _app(monkeypatch, store)
    r = _call(app, "POST", "/api/v1/code-distributions", {"organization_id": ORG, "slug": "lyceum", "title": "T",
                                                         "base_release": "V0666", "open_paths": OPEN})
    assert r.status_code == 201 and r.json()["release_name"] == "V0666_lyceum", r.text
    r = _call(app, "GET", "/api/v1/code-distributions/lyceum")
    assert r.status_code == 200 and r.json()["deciders"] == 2 and r.json()["what"].endswith("not an AGORA payout")
    r = _call(app, "GET", "/api/v1/code-distributions/nosuch")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


# --- D2's two fields (session-lead, room seq 4803): the organization's name wherever a line shows its organization, and
# the reader's own vote on a line's change (FOR, AGAINST or none) -----------------------------------------------------

def test_every_answer_about_a_line_names_its_organization_never_a_bare_id():
    s = LineStore()
    created = _line(s)
    assert created["organization_name"] == "Lyceum Labs"
    f = cd.CodeDistributionFlow(s)
    owner = {"developer_id": 2}
    assert run(f.read(owner, "lyceum"))["organization_name"] == "Lyceum Labs"
    assert [d["organization_name"] for d in run(f.list_for_org(owner, ORG))["items"]] == ["Lyceum Labs"]
    assert [d["organization_name"] for d in run(f.list_all(ADMIN))["items"]] == ["Lyceum Labs"]
    assert run(f.update(owner, "lyceum", {"title": "T2"}))["organization_name"] == "Lyceum Labs"
    assert run(f.pause(ADMIN, "lyceum", "a review"))["organization_name"] == "Lyceum Labs"
    assert run(f.resume(ADMIN, "lyceum"))["organization_name"] == "Lyceum Labs"
    cid = _proposed(s)["id"]
    assert run(_flow(s).view(cid))["code_distribution"]["organization_name"] == "Lyceum Labs"
    s.org_names = {}                                     # a name the store cannot read is said as none, never the id
    assert run(f.read(owner, "lyceum"))["organization_name"] is None


def test_the_reader_sees_their_own_vote_on_a_lines_change_and_nobody_elses():
    s = LineStore()
    cid = _balloting(s)
    f = _flow(s)
    assert run(f.view(cid, reader_developer_id=2))["line_ballot"]["my_vote"] is None
    out = _vote(s, cid, 2)
    assert out["line_ballot"]["my_vote"] == "FOR", "the vote's own answer says what was cast"
    assert run(f.view(cid, reader_developer_id=2))["line_ballot"]["my_vote"] == "FOR"
    assert run(f.view(cid, reader_developer_id=3))["line_ballot"]["my_vote"] is None, "another decider's vote is not theirs"
    assert run(f.view(cid))["line_ballot"]["my_vote"] is None, "an anonymous reader has no vote"
    out = run(f.line_vote({"did": "did:a:3", "developer_id": 3}, cid, {"vote": False}))
    assert out["line_ballot"]["my_vote"] == "AGAINST"


def test_a_main_line_change_carries_neither_field():
    s = LineStore(members=(1,))
    cid = run(_flow(s).propose(PROPOSER, {"repository": REPO, "paths": [CONSOLE + "views/GuildBoard.vue"], "title": "T",
                                          "problem": "P", "branch": "b", "commit": SHA}))["id"]
    out = run(_flow(s).view(cid, reader_developer_id=1))
    assert "line_ballot" not in out and "code_distribution" not in out and "my_vote" not in out


def test_the_public_reads_pass_the_signed_in_reader_and_stay_open_to_anyone(monkeypatch):
    from agentvault_registry.security import get_current_developer_optional
    s = LineStore()
    cid = _balloting(s)
    _vote(s, cid, 2)
    app = _app(monkeypatch, s)
    app.dependency_overrides[get_current_developer_optional] = lambda: _Dev()          # developer 2, who voted for
    r = _call(app, "GET", f"/api/v1/code-changes/{cid}")
    assert r.status_code == 200 and r.json()["line_ballot"]["my_vote"] == "FOR", r.text[:300]
    r = _call(app, "GET", "/api/v1/code-changes?code_distribution=lyceum")
    assert r.status_code == 200 and r.json()["code_changes"][0]["line_ballot"]["my_vote"] == "FOR"
    assert r.json()["code_changes"][0]["code_distribution"]["organization_name"] == "Lyceum Labs"
    app.dependency_overrides[get_current_developer_optional] = lambda: None            # a visitor
    r = _call(app, "GET", f"/api/v1/code-changes/{cid}")
    assert r.status_code == 200 and r.json()["line_ballot"]["my_vote"] is None
