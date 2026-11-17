"""V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7): the signed per-release report of a line and the signed record of one change, through the REAL routes on a REAL Postgres.

  the report    names EVERY change of the line (code and content, in every state), who proposed, who reviewed, the ballot with each vote, our checker's record, what was applied or merged, and the
                protected-set verdict, which says plainly that it is NOT MEASURED until the builds (D6) exist: never a pass nobody measured. The content's text is not in it, its hash is.
  the signature EdDSA over {registry_spiffe_id, kind, subject, digest} with the registry's card key, the digest = sha256 of the report's canonical JSON; verified here OFFLINE with the registry's
                published public key and nothing else (the same steps as the SDK's verifier), and ONE changed byte anywhere in the report fails it
  the record    one change's own signed record (a content or a code change of the line), the same envelope
  who reads     the organization's members (not guests) and platform admins; anyone else sees nothing; the line must exist and be of this registry

Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os

import pytest

DB = os.environ.get("CODE_DISTRIBUTIONS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

from sqlalchemy import text  # noqa: E402

from tests.test_content_changes_v0667_db import deciders_vote_for, propose, vote_all, world  # noqa: E402,F401


def canonical(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def verify_offline(envelope: dict, jwks: dict):
    """The SDK verifier's steps, on the document and the registry's published keys alone: (ok, reason)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    body = envelope.get("report")
    if hashlib.sha256(canonical(body)).hexdigest() != envelope.get("digest"):
        return False, "digest"
    sig = envelope.get("signature") or {}
    jwk = next((k for k in (jwks.get("keys") or []) if k.get("kid") == sig.get("kid")), None)
    if jwk is None:
        return False, "no key"
    payload = {p: envelope.get(p) for p in sig.get("signed_canonical", [])}
    raw = base64.urlsafe_b64decode(jwk["x"] + "=" * (-len(jwk["x"]) % 4))
    value = sig["value"]
    try:
        Ed25519PublicKey.from_public_bytes(raw).verify(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), canonical(payload))
    except InvalidSignature:
        return False, "signature"
    return True, None


async def jwks_of(w) -> dict:
    """What /.well-known/registry-jwks.json publishes: every unexpired key, kid = spiffe#seq."""
    async with w.maker() as s:
        rows = (await s.execute(text("SELECT registry_spiffe_id, rotation_seq, public_jwk, algorithm FROM registry_signing_keys WHERE expires_at IS NULL"))).mappings().all()
    return {"keys": [{**dict(r["public_jwk"]), "kid": f"{r['registry_spiffe_id']}#{r['rotation_seq']}", "alg": r["algorithm"], "use": "sig"} for r in rows]}


async def code_change(w, cid="cc_line1", state="merged"):
    """A code change of the line with a review, two votes and a signed acceptance record, written as the rail writes them."""
    from agentvault_registry.models import CodeChange, CodeChangeReview, CodeDistributionVote
    async with w.maker() as s:
        s.add(CodeChange(id=cid, repository="theprotocol/AgentVault", paths=["a/x"], title="A code change", problem="p", mode="branch", branch="b", commit="a" * 40,
                         proposer_did="did:a:member", proposer_developer_id=w.devs["member"], sensitive=False, state=state, code_distribution_id=w.line_id,
                         acceptance={"ok": True, "commit": "a" * 40, "reasons": []}, merged={"into": "V0666_lyceum", "commit": "a" * 40},
                         ballot_rule={"quorum_percent": 50, "pass_rule": "simple", "decider_team_id": None},
                         ballot_result={"status": "PASSED", "for": 2, "against": 0, "sentence": "2 for, 0 against: passed"}))
        await s.flush()
        s.add(CodeChangeReview(code_change_id=cid, reviewer_developer_id=w.devs["admin"], verdict="approve", commit="a" * 40, findings="read it"))
        s.add(CodeDistributionVote(code_change_id=cid, developer_id=w.devs["owner"], vote=True, agent_did="did:a:owner"))
        s.add(CodeDistributionVote(code_change_id=cid, developer_id=w.devs["admin"], vote=True, agent_did="did:a:admin"))
        await s.commit()


async def a_line_with_history(w):
    """One content change applied, one not passed, one withdrawn, and one code change merged."""
    done = (await propose(w, "console_text", "landing.tagline", {"text": "Quiet releases."})).json()["id"]
    await vote_all(w, done, await deciders_vote_for(w))
    failed = (await propose(w, "console_text", "landing.body", {"text": "No."})).json()["id"]
    await vote_all(w, failed, [(n, False) for n, _ in await deciders_vote_for(w)])
    withdrawn = (await propose(w, "branding", "branding", {"tagline": "Hi"})).json()["id"]
    await w.call("POST", f"/api/v1/content-changes/{withdrawn}/withdraw", None, as_="member")
    await code_change(w)
    return {"applied": done, "failed": failed, "withdrawn": withdrawn, "code": "cc_line1"}


async def report(w, *, as_="owner", admin=False, slug="lyceum"):
    return await w.call("GET", f"/api/v1/code-distributions/{slug}/report", as_=as_, admin=admin)


async def test_the_report_names_every_change_of_the_release_with_who_proposed_reviewed_and_voted(world):
    w = world
    ids = await a_line_with_history(w)
    r = await report(w)
    assert r.status_code == 200, r.text
    env = r.json()
    body = env["report"]
    assert env["kind"] == "distribution.release.report" and env["subject"] == "V0666_lyceum" and body["release"] == "V0666_lyceum"
    assert {c["id"] for c in body["changes"]} == set(ids.values()), "every change of the release, in every state"
    by = {c["id"]: c for c in body["changes"]}
    assert by[ids["applied"]]["state"] == "applied" and by[ids["applied"]]["kind"] == "content" and by[ids["applied"]]["change_kind"] == "console_text"
    assert by[ids["failed"]]["state"] == "failed" and by[ids["withdrawn"]]["state"] == "withdrawn"
    assert by[ids["code"]]["kind"] == "code" and by[ids["code"]]["state"] == "merged"
    assert by[ids["applied"]]["proposer"]["developer_id"] == w.devs["member"]
    voters = {v["developer_id"] for v in by[ids["applied"]]["ballot"]["votes"]}
    assert voters == {d for _, d in [(n, w.devs[n]) for n, _ in await deciders_vote_for(w)]} and by[ids["applied"]]["ballot"]["result"]["status"] == "PASSED"
    assert by[ids["code"]]["reviews"] == [{"reviewer_developer_id": w.devs["admin"], "verdict": "approve", "commit": "a" * 40, "at": by[ids["code"]]["reviews"][0]["at"]}]
    assert {v["developer_id"] for v in by[ids["code"]]["ballot"]["votes"]} == {w.devs["owner"], w.devs["admin"]}
    assert by[ids["code"]]["checker"]["acceptance"]["ok"] is True and by[ids["applied"]]["checker"]["ok"] is True
    assert body["counts"]["changes"] == 4 and body["counts"]["code"] == 1 and body["counts"]["content"] == 3 and body["counts"]["by_state"]["applied"] == 1
    assert body["line"]["slug"] == "lyceum" and body["line"]["organization_name"] == "Lyceum" and body["deciders_now"] >= 2


async def test_the_protected_set_verdict_is_not_measured_and_says_so_never_a_pass(world):
    w = world
    await a_line_with_history(w)
    ps = (await report(w)).json()["report"]["protected_set"]
    assert ps["status"] == "not_measured" and "builds" in ps["reason"] and set(ps) == {"status", "reason"}, "no verdict field, no pass: nothing was measured"


async def test_the_content_text_is_not_in_the_report_its_hash_is(world):
    w = world
    ids = await a_line_with_history(w)
    raw = (await report(w)).text
    assert "Quiet releases." not in raw
    c = next(c for c in (await report(w)).json()["report"]["changes"] if c["id"] == ids["applied"])
    assert c["content_hash"] == hashlib.sha256(canonical({"text": "Quiet releases."})).hexdigest()


async def test_the_signature_verifies_offline_with_the_published_key_and_one_changed_byte_fails(world):
    w = world
    await a_line_with_history(w)
    env = (await report(w)).json()
    jwks = await jwks_of(w)
    assert env["signature"]["alg"] == "EdDSA" and env["signature"]["kid"].endswith("#1") and env["signature"]["jwks_url"] == "/.well-known/registry-jwks.json"
    assert env["signature"]["signed_canonical"] == ["registry_spiffe_id", "kind", "subject", "digest"]
    assert verify_offline(env, jwks) == (True, None)
    # one byte of the report, anywhere: a title, a vote, a count
    for path in (("report", "changes", 0, "title"), ("report", "counts", "changes"), ("report", "line", "title")):
        bad = copy.deepcopy(env)
        cur = bad
        for p in path[:-1]:
            cur = cur[p]
        cur[path[-1]] = (cur[path[-1]] + 1) if isinstance(cur[path[-1]], int) else cur[path[-1]][:-1] + chr(ord(cur[path[-1]][-1]) ^ 1)
        assert verify_offline(bad, jwks) == (False, "digest"), path
    # the digest and the signed fields cannot be re-pointed either
    for field, value in (("subject", "V0666_other"), ("kind", "distribution.change.record")):
        bad = copy.deepcopy(env)
        bad[field] = value
        assert verify_offline(bad, jwks)[0] is False, field
    bad = copy.deepcopy(env)
    bad["signature"]["value"] = bad["signature"]["value"][:-2] + ("AA" if not bad["signature"]["value"].endswith("AA") else "BB")
    assert verify_offline(bad, jwks) == (False, "signature")


async def test_a_change_has_its_own_signed_record_a_content_change_and_a_code_change_alike(world):
    w = world
    ids = await a_line_with_history(w)
    for cid, kind in ((ids["applied"], "content"), (ids["code"], "code")):
        r = await w.call("GET", f"/api/v1/code-distributions/lyceum/records/{cid}", as_="owner")
        assert r.status_code == 200, (cid, r.text)
        env = r.json()
        jwks = await jwks_of(w)                    # the key is minted by the first signature: the published set is read after it
        assert env["kind"] == "distribution.change.record" and env["subject"] == cid and env["report"]["change"]["id"] == cid and env["report"]["change"]["kind"] == kind
        assert env["report"]["release"] == "V0666_lyceum" and verify_offline(env, jwks) == (True, None)
        assert env["report"]["change"]["ballot"]["votes"], "the votes are in the record"
    assert (await w.call("GET", "/api/v1/code-distributions/lyceum/records/ct_nosuch", as_="owner")).status_code == 404
    assert (await w.call("GET", "/api/v1/code-distributions/lyceum/records/cc_other", as_="owner")).status_code == 404


async def test_a_record_of_another_lines_change_is_not_found_here(world):
    w = world
    from agentvault_registry.models import CodeChange
    async with w.maker() as s:
        await s.execute(text("INSERT INTO code_distributions (id, organization_id, slug, title, base_release, open_paths, quorum_percent, pass_rule, state, created_by_developer_id) "
                             "VALUES ('cdst_two', :o, 'second', 'Second', 'V0666', '[\"a/\"]'::jsonb, 50, 'simple', 'active', 1)"), {"o": w.org})
        s.add(CodeChange(id="cc_second1", repository="r", paths=["a/x"], title="t", problem="p", mode="branch", proposer_did="d", proposer_developer_id=w.devs["member"],
                         sensitive=False, state="proposed", code_distribution_id="cdst_two"))
        await s.commit()
    assert (await w.call("GET", "/api/v1/code-distributions/lyceum/records/cc_second1", as_="owner")).status_code == 404
    assert (await w.call("GET", "/api/v1/code-distributions/second/records/cc_second1", as_="owner")).status_code == 200


async def test_who_reads_the_members_not_guests_and_platform_admins_and_nobody_else(world):
    w = world
    await a_line_with_history(w)
    for who, status in (("owner", 200), ("admin", 200), ("member", 200), ("lead", 200), ("guestlead", 403), ("outsider", 404), ("other_owner", 404)):
        assert (await report(w, as_=who)).status_code == status, who
    assert (await report(w, as_="outsider", admin=True)).status_code == 200
    assert (await report(w, slug="nosuch")).status_code == 404


async def test_the_download_names_the_release_and_the_switch_off_answers_not_found(world, monkeypatch):
    w = world
    r = await w.call("GET", "/api/v1/code-distributions/lyceum/report?download=1", as_="owner")
    assert r.status_code == 200 and r.headers["content-disposition"] == 'attachment; filename="V0666_lyceum.report.json"'
    monkeypatch.delenv("CODE_DISTRIBUTIONS_ENABLED", raising=False)
    assert (await report(w)).status_code == 404


async def test_a_registry_that_does_not_govern_still_reads_the_report(world, monkeypatch):
    """Reads answer everywhere (the posture is for writes): a report is a read."""
    from agentvault_registry.services import code_authority as ca
    w = world
    monkeypatch.setattr(ca, "own_name", lambda: "asia")
    assert (await report(w)).status_code == 200


async def test_an_empty_line_has_a_report_that_says_there_is_no_change(world):
    w = world
    body = (await report(w)).json()["report"]
    assert body["changes"] == [] and body["counts"] == {"changes": 0, "code": 0, "content": 0, "by_state": {}}
