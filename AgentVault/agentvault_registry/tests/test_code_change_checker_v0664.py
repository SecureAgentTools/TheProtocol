"""V0664 (order gwo_af5b8c950682b9318a347e39, room seq 3638): governed code's acceptance comes from a signed HOST checker.

The checker runs on the host (session-release's side): it reads CI for the exact commit, computes the touched paths and
the secret scan from the repository, and signs the record with its own key. A frame holds only the checker's PUBLIC key
(CODE_CHANGES_CHECKER_PUBLIC_KEY) and verifies the record: no repository credential on any frame. The format, agreed in
the room (seq 3670-3671), is core/release_channel's shape (tests/test_code_changes_flow_v0663.sign_record signs it on
its own):
  every record   schema "theprotocol.code-change-check/1", kind, repository, change_id, commit, issued_at (UTC, Z),
                 signature {"alg": "Ed25519", "kid", "sig"} over the record without it (keys sorted, compact, UTF-8)
  acceptance     ci_state, base (a release branch), touched, secret_findings, secret_paths, too_many_touched
  release_line   branch, contains (the merge check, F8: the frame cannot read the repository to ask)
The registry takes a record only for its own change, repository and commit, no older than 24 h and not from the
future, and never one older than the last it took for that change (a replayed pass cannot undo a later fail). No key
configured: no check and no merge (fail closed).
Red on v0663/cut b7ca684e9: the module does not exist and the frame reads Forgejo itself.
"""
from __future__ import annotations

import base64
import datetime as dt
import pathlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import (ADMIN, CHECKER_PUB_B64, CHECK_SCHEMA, CONSOLE, PROPOSER, REPO, SHA, SHA2,
                                                T0, FakeStore, _accept, _deliver, _mb, _propose, _refused, _review,
                                                acceptance_record, release_line_record, run, sign_record)

try:     # red as one failure per test, not a collection error
    from agentvault_registry.services import code_change_checker as ck
except ImportError:
    ck = None

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CODE_CHANGES_MAINTAINER", "99")
    monkeypatch.setenv("CODE_CHANGES_RELEASE_BRANCHES", "v0663/cut")
    monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", CHECKER_PUB_B64)


def _flow(s):
    return cc.CodeChangeFlow(s)


def _verify(doc, **over):
    kw = dict(kind="acceptance", change_id="cc_1", repository=REPO, now=T0 + dt.timedelta(minutes=5))
    kw.update(over)
    return ck.verify_record(doc, **kw)


def _rec(**over):
    s = FakeStore()
    s.repo.touched[SHA] = [CONSOLE + "views/GuildBoard.vue"]
    return acceptance_record(s, "cc_1", SHA, **over)


# --- the verify ----------------------------------------------------------------------------------------------------

def test_a_record_the_checker_signed_verifies_and_comes_back_without_its_signature():
    rec, code, _ = _verify(_rec())
    assert code == "" and rec["commit"] == SHA and rec["touched"] == [CONSOLE + "views/GuildBoard.vue"]
    assert "signature" not in rec and ck.SCHEMA == CHECK_SCHEMA


@pytest.mark.parametrize("change,code", [
    (lambda d: {**d, "touched": []}, "signature"),                                   # tampered after signing
    (lambda d: {k: v for k, v in d.items() if k != "signature"}, "unsigned"),
    (lambda d: {**d, "signature": {**d["signature"], "alg": "RS256"}}, "unsigned"),
    (lambda d: sign_record(d, Ed25519PrivateKey.generate()), "key"),                  # another checker's key
    (lambda d: sign_record({**d, "schema": "theprotocol.code-change-check/0"}), "schema"),
    (lambda d: sign_record({**d, "kind": "release_line"}), "kind"),
    (lambda d: sign_record({**d, "change_id": "cc_2"}), "change_id"),
    (lambda d: sign_record({**d, "repository": "theprotocol/Other"}), "repository"),
    (lambda d: sign_record({**d, "commit": "abc"}), "commit"),
    (lambda d: sign_record({**d, "issued_at": "yesterday"}), "issued_at"),
    (lambda d: sign_record({**d, "issued_at": "2026-11-12T00:00:00Z"}), "stale"),     # older than 24 h
    (lambda d: sign_record({**d, "issued_at": "2026-11-14T02:00:00Z"}), "future"),
    (lambda d: "not a record", "unsigned"),
])
def test_anything_else_is_refused_and_named(change, code):
    rec, got, sentence = _verify(change(_rec()))
    assert rec is None and got == code and sentence, (got, sentence)


@pytest.mark.parametrize("value", [None, "", "not-base64!", base64.b64encode(b"short").decode()])
def test_no_usable_key_means_no_check(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", raising=False)
    else:
        monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", value)
    rec, code, _ = _verify(_rec())
    assert rec is None and code == "no_checker"


# --- the flow ------------------------------------------------------------------------------------------------------

def test_the_kept_record_says_who_signed_it_and_when():
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    out = _accept(s, cid)
    rec = out["acceptance"]["record"]
    assert out["state"] == "accepted" and rec["read_from"] == "checker"
    assert len(rec["checker_kid"]) == 16 and rec["issued_at"].endswith("Z")


def test_a_replayed_older_pass_cannot_undo_a_later_fail():
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    s.repo.touched[SHA] = [CONSOLE + "views/GuildBoard.vue"]
    passed = acceptance_record(s, cid, SHA)
    run(_flow(s).record_acceptance(ADMIN, cid, {"signed": passed}))
    assert s.rows[cid]["state"] == "accepted"
    s.repo.ci[SHA] = "failure"
    run(_flow(s).record_acceptance(ADMIN, cid, {"signed": acceptance_record(s, cid, SHA)}))
    assert s.rows[cid]["state"] == "proposed"
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"signed": passed}), 409, "stale_record")
    assert s.rows[cid]["state"] == "proposed"


def test_a_record_for_another_change_or_read_against_another_base_is_refused():
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"signed": acceptance_record(s, "cc_other", SHA)}), 409, "change_id")
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"signed": acceptance_record(s, cid, SHA, base="feature/x")}), 409,
             "base")
    assert s.rows[cid]["acceptance"] is None


def test_an_unsigned_body_or_no_key_checks_nothing(monkeypatch):
    s = FakeStore()
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"commit": SHA}), 422, "unsigned")
    signed = acceptance_record(s, cid, SHA)
    monkeypatch.delenv("CODE_CHANGES_CHECKER_PUBLIC_KEY")
    _refused(_flow(s).record_acceptance(ADMIN, cid, {"signed": signed}), 503, "no_checker")
    assert s.rows[cid]["acceptance"] is None


def _ready(s):
    cid = _propose(s)["id"]
    _deliver(s, "gwo_1")
    _accept(s, cid)
    _review(s, cid, 7)
    run(_flow(s).open_ballot(PROPOSER, cid))
    s.proposals[1].update(status="PASSED", tallied_at=T0)
    s.clock = T0 + dt.timedelta(hours=cc.veto_window_hours() + 1)
    s.repo.contained.add(("v0663/cut", SHA))
    return cid


def test_the_merge_needs_the_checkers_word_that_the_release_branch_holds_the_voted_commit(monkeypatch):
    s = FakeStore()
    cid = _ready(s)
    body = {"commit": SHA, "into": "v0663/cut"}
    _refused(_flow(s).record_merge(ADMIN, cid, body), 422, "unsigned")
    _refused(_flow(s).record_merge(ADMIN, cid, {**body, "signed": acceptance_record(s, cid, SHA)}), 409, "kind")
    _refused(_flow(s).record_merge(ADMIN, cid, {**body, "signed": release_line_record(s, cid, SHA, "main")}), 409,
             "branch")
    _refused(_flow(s).record_merge(ADMIN, cid, {**body, "signed": release_line_record(s, cid, SHA2, "v0663/cut")}), 409,
             "commit")
    signed = release_line_record(s, cid, SHA, "v0663/cut")
    monkeypatch.delenv("CODE_CHANGES_CHECKER_PUBLIC_KEY")
    _refused(_flow(s).record_merge(ADMIN, cid, {**body, "signed": signed}), 503, "no_checker")
    monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", CHECKER_PUB_B64)
    assert run(_flow(s).record_merge(ADMIN, cid, _mb(s, cid, SHA, "v0663/cut")))["state"] == "merged"


# --- no repository credential on any frame -----------------------------------------------------------------------

def test_the_frame_reads_no_repository():
    src = (SRC / "services" / "code_changes.py").read_text()
    assert not hasattr(cc, "RepoReader") and not hasattr(cc, "read_acceptance")
    assert "import httpx" not in src and "httpx." not in src
    hits = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if "CODE_CHANGES_FORGEJO" in p.read_text(errors="ignore")]
    assert hits == []
