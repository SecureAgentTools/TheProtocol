"""V0663, governed code, first slice (order gwo_58327a76b7e3ecf63140eb79): the flow of a code change, driven through
services/code_changes.CodeChangeFlow against an in-memory store (the routes are thin; DbStore is the same interface on
the database).

  propose   a member's agent; the paths must be open (D5); a bounty posts a normal Guild order through the existing
            escrow, a branch names its commit; a registry without members cannot vote, so it takes no proposal
  accept    a checker's record per commit; a bounty's commit must be one the worker delivered on a submitted order;
            the verdict is kept whatever it says; a passing record moves the change to accepted
  review    members other than the proposer's developer and the worker's; on the accepted commit
  ballot    opens only on an accepted commit with enough independent approvals; a governance proposal of type
            code_change with the frame policy's thresholds (the policy_change pair when sensitive) and the record in
            its diff; the proposer's agent or a platform admin opens it, once
  result    the record follows its ballot (PASSED, FAILED); the veto window runs 24 h from the tally (his go ends it)
  veto/go   his, while the window is open and before the merge
  merge     a session records the merge of the voted commit only, after the window or his go, never after a veto
Red on 37dd10e91: CodeChangeFlow does not exist.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentvault_registry.services import code_changes as cc

REPO = cc.REPOSITORY
CONSOLE = cc.CONSOLE_PREFIX
SHA, SHA2 = "a" * 40, "b" * 40
T0 = dt.datetime(2026, 11, 14, 1, tzinfo=dt.timezone.utc)

# V0664 (gwo_af5b8c950682b9318a347e39): the host checker's signed records. The test signs on its own, in the format agreed
# with session-release (room seq 3670-3671; core/release_channel's shape): the record without its "signature", keys
# sorted, separators "," and ":", UTF-8, Ed25519; the signature {"alg", "kid" (16 hex of sha256 of the raw public key),
# "sig" (base64)}. The registry holds only the public key (CODE_CHANGES_CHECKER_PUBLIC_KEY, base64 of the raw 32 bytes).
CHECK_SCHEMA = "theprotocol.code-change-check/1"
CHECKER_KEY = Ed25519PrivateKey.generate()


def _raw_pub(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


CHECKER_PUB_B64 = base64.b64encode(_raw_pub(CHECKER_KEY)).decode()


def sign_record(record, key=None):
    key = key or CHECKER_KEY
    body = {k: v for k, v in record.items() if k != "signature"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {**body, "signature": {"alg": "Ed25519", "kid": hashlib.sha256(_raw_pub(key)).hexdigest()[:16],
                                  "sig": base64.b64encode(key.sign(raw)).decode()}}


def _issued(store, issued):
    """Each record a moment later than the last (the registry takes no record older than the one it holds)."""
    store.checks = getattr(store, "checks", 0) + 1
    t = issued or (store.clock + dt.timedelta(seconds=store.checks))
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def acceptance_record(store, cid, commit=SHA, *, issued=None, key=None, **over):
    """What the host checker signs for `commit`, read from the repository the fake holds (store.repo)."""
    repo = store.repo
    touched = list(repo.touched.get(commit, []))
    secret_paths = [p for p in touched if "avreg_" in repo.files.get((p, commit), "")]
    rec = {"schema": CHECK_SCHEMA, "kind": "acceptance", "repository": REPO, "change_id": cid, "commit": commit,
           "issued_at": _issued(store, issued), "ci_state": repo.ci.get(commit, "success"), "base": "v0663/cut",
           "touched": touched, "secret_findings": len(secret_paths), "secret_paths": secret_paths,
           "too_many_touched": len(touched) >= 100}
    rec.update(over)
    return sign_record(rec, key)


def release_line_record(store, cid, commit=SHA, branch="v0663/cut", *, issued=None, key=None, **over):
    """What the host checker signs about whether `branch` holds `commit`."""
    rec = {"schema": CHECK_SCHEMA, "kind": "release_line", "repository": REPO, "change_id": cid, "commit": commit,
           "issued_at": _issued(store, issued), "branch": branch, "contains": (branch, commit) in store.repo.contained}
    rec.update(over)
    return sign_record(rec, key)


def _mb(store, cid, commit, into):
    """A merge body: the voted commit, the branch, and the checker's signed word that the branch holds it."""
    return {"commit": commit, "into": into, "signed": release_line_record(store, cid, commit, into)}


class FakeRepo:
    """V0663 fixes (F1, F2, F8) and V0664 (the signed checker): what the HOST CHECKER reads from the repository: the CI state
    of a commit (default success), the paths it touches against the release line, a file's text at the commit, and whether
    a branch contains a commit. The registry never reads it; it verifies what the checker signed from it."""

    def __init__(self):
        self.ci, self.touched, self.files, self.contained = {}, {}, {}, set()

    async def ci_state(self, sha):
        return self.ci.get(sha, "success")

    async def changed_files(self, sha):
        return [(p, "modified") for p in self.touched.get(sha, [])]

    async def file_text(self, path, sha):
        return self.files.get((path, sha), "")

    async def contains(self, branch, sha):
        return (branch, sha) in self.contained


class FakeStore:
    """The store interface in memory. Developers: 1 the proposer, 2 the worker, 7 and 8 reviewers, 9 not a member."""

    def __init__(self, *, members=(1, 2, 7, 8), member_mode=True):
        self.members, self._member_mode = set(members), member_mode
        self.rows, self.revs, self.orders, self.proposals = {}, [], {}, {}
        self.agents = {"did:a:proposer": 1, "did:a:worker": 2, "did:a:r7": 7, "did:a:r8": 8, "did:a:out": 9}
        self.policy = {}
        self.clock = T0
        self.posted = []
        self.repo, self.org_owners, self.voided = FakeRepo(), {}, []

    async def member_mode(self):
        return self._member_mode

    async def is_member(self, developer_id):
        return developer_id in self.members

    async def developer_of_agent(self, did):
        return self.agents.get(did)

    async def post_bounty_order(self, agent, *, title, spec, bounty, currency):
        oid = f"gwo_{len(self.orders) + 1}"
        self.orders[oid] = {"id": oid, "status": "open", "worker_did": None, "deliverable": None, "bounty": bounty,
                            "payee_did": None, "payee_org_id": None}
        self.posted.append({"agent": agent, "title": title, "spec": spec, "bounty": bounty, "currency": currency})
        return oid

    async def order(self, oid):
        return self.orders.get(oid)

    async def org_owner(self, org_id):
        return self.org_owners.get(org_id)

    async def void_proposal(self, pid):
        self.voided.append(pid)
        self.proposals[pid]["status"] = "CANCELLED"

    # slice 2 (gwo_dd68911fe7e83b64bc611258): the store's two Guild calls, moving the order as the Guild does
    async def settle_order(self, oid, *, actor):
        o = self.orders[oid]
        if o["status"] != "submitted":
            return {"ok": False, "why": f"Order is {o['status']}, not submitted"}
        o["status"] = "settled"
        return {"ok": True, "status": "settled"}

    async def return_order(self, oid, *, actor, reason):
        o = self.orders[oid]
        if o["status"] not in ("open", "awarded", "submitted"):
            return {"ok": False, "why": f"Order is {o['status']}: no bounty held to return"}
        o["status"] = "cancelled"
        return {"ok": True, "status": "cancelled"}

    async def ended(self):
        return [dict(r) for r in self.rows.values() if r.get("order_id")]

    async def insert(self, row):
        self.rows[row["id"]] = dict(row)

    async def get(self, cid):
        r = self.rows.get(cid)
        return dict(r) if r else None

    async def update(self, cid, **fields):
        self.rows[cid].update(fields)

    async def reviews(self, cid):
        return [dict(r) for r in self.revs if r["code_change_id"] == cid]

    async def add_review(self, row):
        self.revs.append(dict(row))

    async def frame_policy(self):
        return self.policy

    async def create_proposal(self, *, title, description, diff, quorum, pass_percent, ends):
        pid = len(self.proposals) + 1
        self.proposals[pid] = {"id": pid, "status": "VOTING", "title": title, "description": description,
                               "policy_diff": diff, "quorum_percent": quorum, "pass_percent": pass_percent,
                               "end_timestamp": ends, "tallied_at": None}
        return pid

    async def proposal(self, pid):
        return self.proposals.get(pid)

    def now(self):
        return self.clock


def run(c):
    return asyncio.run(c)


@pytest.fixture(autouse=True)
def _maintainer_and_release_line(monkeypatch):
    """V0663 fixes (F3, F8): go and veto are the maintainer's (ADMIN, developer 99, in these tests) and a merge names a
    release branch."""
    monkeypatch.setenv("CODE_CHANGES_MAINTAINER", "99")
    monkeypatch.setenv("CODE_CHANGES_RELEASE_BRANCHES", "v0663/cut")
    monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", CHECKER_PUB_B64)
    # V0666 (order gwo_e086b25f868da7ec9fce9fd2): these tests drive the rail on the registry that GOVERNS code (the production store refuses elsewhere)
    from agentvault_registry.services import code_authority
    monkeypatch.setenv(code_authority.ENV, "eu")
    monkeypatch.setattr(code_authority, "own_name", lambda: "eu")


PROPOSER = {"did": "did:a:proposer", "developer_id": 1}
ADMIN = {"developer_id": 99, "admin": True}


def _flow(store):
    return cc.CodeChangeFlow(store)


def _propose(store, **over):
    body = {"repository": REPO, "paths": [CONSOLE + "views/GuildBoard.vue"], "title": "A clearer order page",
            "problem": "The order page hides who is paid.", "bounty": 50.0, "currency": "ECU"}
    body.update(over)
    return run(_flow(store).propose(PROPOSER, body))


def _deliver(store, oid, commit=SHA, worker="did:a:worker"):
    store.orders[oid].update(status="submitted", worker_did=worker,
                             deliverable={"commits": [{"repo": REPO, "commit": commit}]})


def _accept(store, cid, commit=SHA, *, ci="success", touched=None, secret=False, actor=None):
    """V0663 fixes (F2), V0664: sets what the repository says about `commit` (its CI state, the paths it touches, a secret
    in its first touched file) and posts what the host checker signs from it."""
    store.repo.ci[commit] = ci
    store.repo.touched[commit] = list(touched if touched is not None else [CONSOLE + "views/GuildBoard.vue"])
    if secret and store.repo.touched[commit]:
        store.repo.files[(store.repo.touched[commit][0], commit)] = "token = 'avreg" + "_" + "A" * 40 + "'"
    return run(_flow(store).record_acceptance(actor or ADMIN, cid, {"signed": acceptance_record(store, cid, commit)}))


def _review(store, cid, dev, verdict="approve", commit=SHA):
    return run(_flow(store).review({"developer_id": dev}, cid, {"verdict": verdict, "commit": commit,
                                                                "findings": "read the diff"}))


def _refused(coro, status, code):
    with pytest.raises(cc.CodeChangeRefusal) as e:
        run(coro)
    assert (e.value.status, e.value.code) == (status, code), (e.value.status, e.value.code, e.value.sentence)
    return e.value


# --- propose -----------------------------------------------------------------------------------------------------

def test_a_bounty_posts_a_normal_guild_order_and_names_it():
    s = FakeStore()
    out = _propose(s)
    assert out["state"] == "proposed" and out["mode"] == "bounty" and out["order_id"] == "gwo_1"
    post = s.posted[0]
    assert post["bounty"] == 50.0 and post["currency"] == "ECU" and post["agent"] == PROPOSER
    assert post["title"].startswith("Code change: ") and REPO in post["spec"] and CONSOLE + "views/GuildBoard.vue" in post["spec"]
    assert "the members' ballot" in post["spec"], "the order says how it settles"


def test_a_branch_names_its_commit_and_posts_no_order():
    s = FakeStore()
    out = _propose(s, bounty=None, currency=None, branch="docs/clearer-guild", commit=SHA)
    assert out["mode"] == "branch" and out["order_id"] is None and out["commit"] == SHA and s.posted == []


@pytest.mark.parametrize("over,status,code", [
    ({"paths": ["agentvault_registry/src/agentvault_registry/routers/guild.py"]}, 422, "path_refused"),
    ({"paths": [CONSOLE + ".env"]}, 422, "path_refused"),
    ({"bounty": None, "currency": None}, 422, "bounty_or_branch"),
    ({"branch": "x", "commit": SHA}, 422, "bounty_or_branch"),
    ({"bounty": None, "currency": None, "branch": "x", "commit": "abc"}, 422, "bad_commit"),
    ({"title": ""}, 422, "title"),
    ({"problem": "  "}, 422, "problem"),
])
def test_a_proposal_that_breaks_a_rule_is_refused_with_its_reason(over, status, code):
    s = FakeStore()
    _refused(_flow(s).propose(PROPOSER, {"repository": REPO, "paths": [CONSOLE + "views/A.vue"], "title": "T",
                                         "problem": "P", "bounty": 5.0, "currency": "ECU", **over}), status, code)
    assert s.posted == [], "no order posted for a refused proposal"


def test_only_a_member_proposes_and_only_where_members_vote():
    _refused(_flow(FakeStore(members=(2, 7))).propose(PROPOSER, {"repository": REPO, "paths": [CONSOLE + "a.vue"],
             "title": "T", "problem": "P", "bounty": 5.0, "currency": "ECU"}), 403, "not_a_member")
    _refused(_flow(FakeStore(member_mode=False)).propose(PROPOSER, {"repository": REPO, "paths": [CONSOLE + "a.vue"],
             "title": "T", "problem": "P", "bounty": 5.0, "currency": "ECU"}), 409, "no_members")


def test_a_sensitive_path_marks_the_change():
    out = _propose(FakeStore(), paths=[CONSOLE + "stores/auth.ts"])
    assert out["sensitive"] is True and out["reviews_needed"] == 2


# --- accept ------------------------------------------------------------------------------------------------------

def test_a_bounty_is_accepted_on_a_commit_the_worker_delivered():
    s = FakeStore()
    cid = _propose(s)["id"]
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"signed": acceptance_record(s, cid, SHA)}), 409, "not_delivered")
    _deliver(s, "gwo_1")
    out = _accept(s, cid, commit=SHA2)
    assert out["acceptance"]["ok"] is False and "not one the worker delivered" in " ".join(out["acceptance"]["reasons"])
    assert out["state"] == "proposed"
    out = _accept(s, cid)
    assert out["state"] == "accepted" and out["commit"] == SHA and out["acceptance"]["ok"] is True


def test_a_failing_record_is_kept_and_says_why():
    s = FakeStore()
    cid = _propose(s, bounty=None, currency=None, branch="b", commit=SHA)["id"]
    out = _accept(s, cid, ci="failure")
    assert out["state"] == "proposed" and out["acceptance"]["ok"] is False
    assert any("CI is not green" in r for r in out["acceptance"]["reasons"])


# --- review and ballot ---------------------------------------------------------------------------------------------

def _accepted(s, **over):
    cid = _propose(s, **over)["id"]
    _deliver(s, "gwo_1")
    _accept(s, cid)
    return cid


def test_the_proposer_and_the_worker_cannot_review_and_a_non_member_cannot_either():
    s = FakeStore()
    cid = _accepted(s)
    _refused(_flow(s).review({"developer_id": 1}, cid, {"verdict": "approve", "commit": SHA}), 403, "not_independent")
    _refused(_flow(s).review({"developer_id": 2}, cid, {"verdict": "approve", "commit": SHA}), 403, "not_independent")
    _refused(_flow(s).review({"developer_id": 9}, cid, {"verdict": "approve", "commit": SHA}), 403, "not_a_member")
    _refused(_flow(s).review({"developer_id": 7}, cid, {"verdict": "approve", "commit": SHA2}), 409, "not_the_accepted_commit")
    _refused(_flow(s).review({"developer_id": 7}, cid, {"verdict": "maybe", "commit": SHA}), 422, "verdict")


def test_the_ballot_opens_on_an_accepted_commit_with_its_approvals_once():
    s = FakeStore()
    cid = _accepted(s)
    _refused(_flow(s).open_ballot(PROPOSER, cid), 409, "reviews_short")
    _review(s, cid, 7)
    out = run(_flow(s).open_ballot(PROPOSER, cid))
    assert out["state"] == "balloting" and out["proposal_id"] == 1
    p = s.proposals[1]
    assert (p["quorum_percent"], p["pass_percent"]) == (10.0, 50.0)
    assert p["policy_diff"]["code_change_id"] == cid and p["policy_diff"]["commit"] == SHA
    assert p["title"].startswith("Code change: ")
    _refused(_flow(s).open_ballot(PROPOSER, cid), 409, "wrong_state")


def test_a_sensitive_change_is_voted_on_the_policy_change_pair_after_two_approvals():
    s = FakeStore()
    s.policy = {"governance.policy_change_quorum_percent": 25.0, "governance.policy_change_pass_percent": 70.0}
    cid = _accepted(s, paths=[CONSOLE + "stores/auth.ts"])
    s.orders["gwo_1"]["deliverable"] = {"commits": [{"repo": REPO, "commit": SHA}]}
    # the touched path must sit inside the declared one
    _accept(s, cid, touched=[CONSOLE + "stores/auth.ts"])
    _review(s, cid, 7)
    _refused(_flow(s).open_ballot(PROPOSER, cid), 409, "reviews_short")
    _review(s, cid, 8)
    run(_flow(s).open_ballot(PROPOSER, cid))
    assert (s.proposals[1]["quorum_percent"], s.proposals[1]["pass_percent"]) == (25.0, 70.0)


def test_only_the_proposer_or_a_platform_admin_opens_the_ballot():
    s = FakeStore()
    cid = _accepted(s)
    _review(s, cid, 7)
    _refused(_flow(s).open_ballot({"did": "did:a:r7", "developer_id": 7}, cid), 403, "not_yours")
    assert run(_flow(s).open_ballot(ADMIN, cid))["state"] == "balloting"


# --- result, veto, go, merge -------------------------------------------------------------------------------------

def _balloted(s):
    cid = _accepted(s)
    _review(s, cid, 7)
    run(_flow(s).open_ballot(PROPOSER, cid))
    s.repo.contained.add(("v0663/cut", SHA))          # F8: the release line holds the voted commit once merged
    return cid


def test_the_record_follows_its_ballot_and_shows_the_veto_window():
    s = FakeStore()
    cid = _balloted(s)
    assert run(_flow(s).view(cid))["state"] == "balloting"
    s.proposals[1].update(status="PASSED", tallied_at=T0)
    v = run(_flow(s).view(cid))
    assert v["state"] == "passed" and v["veto_window_closes_at"] == (T0 + dt.timedelta(hours=24)).isoformat()
    s2 = FakeStore()
    c2 = _balloted(s2)
    s2.proposals[1].update(status="FAILED", tallied_at=T0)
    assert run(_flow(s2).view(c2))["state"] == "failed"


def test_inside_the_window_a_merge_waits_for_his_go_and_his_veto_ends_it():
    s = FakeStore()
    cid = _balloted(s)
    s.proposals[1].update(status="PASSED", tallied_at=T0)
    s.clock = T0 + dt.timedelta(hours=2)
    _refused(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")), 409, "merge_refused")
    run(_flow(s).go(ADMIN, cid))
    out = run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))
    assert out["state"] == "merged" and out["merged"]["commit"] == SHA and out["merged"]["into"] == "v0663/cut"
    _refused(_flow(s).veto(ADMIN, cid, {"reason": "too late"}), 409, "wrong_state")

    s2 = FakeStore()
    c2 = _balloted(s2)
    s2.proposals[1].update(status="PASSED", tallied_at=T0)
    s2.clock = T0 + dt.timedelta(hours=2)
    out = run(_flow(s2).veto(ADMIN, c2, {"reason": "not now"}))
    assert out["state"] == "vetoed" and out["veto"]["reason"] == "not now"
    s2.clock = T0 + dt.timedelta(hours=30)
    _refused(_flow(s2).record_merge(ADMIN, c2, _mb(s2, c2, SHA, "v0663/cut")), 409, "merge_refused")


def test_after_the_window_the_voted_commit_merges_and_no_other():
    s = FakeStore()
    cid = _balloted(s)
    s.proposals[1].update(status="PASSED", tallied_at=T0)
    s.clock = T0 + dt.timedelta(hours=25)
    _refused(_flow(s).veto(ADMIN, cid, {"reason": "late"}), 409, "window_closed")
    _refused(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA2, "v0663/cut")), 409, "merge_refused")
    assert run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))["state"] == "merged"


def test_veto_go_and_merge_are_a_platform_admins():
    s = FakeStore()
    cid = _balloted(s)
    s.proposals[1].update(status="PASSED", tallied_at=T0)
    for call in (_flow(s).veto(PROPOSER, cid, {"reason": "x"}), _flow(s).go(PROPOSER, cid),
                 _flow(s).record_merge(PROPOSER, cid, _mb(s, cid, SHA, "x")),
                 _flow(s).record_acceptance(PROPOSER, cid, {"signed": acceptance_record(s, cid, SHA)})):
        _refused(call, 403, "admin_only")


def test_an_unknown_change_is_a_404():
    _refused(_flow(FakeStore()).view("cc_none"), 404, "not_found")
