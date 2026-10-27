"""§MEMBERSHIP phase D2 (2026-10-02) — federal ballots, the parts that need no database: the signed document, the
host's verification (exact kid, the caller's trust domain, the /registry/ path, no fallback to any key), the
eligibility judgement, and the per-agent vote refused where registries cast ballots. Every refusal has a control.
"""
from __future__ import annotations

import asyncio
import base64
import pathlib
import re
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "src"


@pytest.fixture(scope="module")
def fb():
    sys.path.insert(0, str(SRC))
    from agentvault_registry.services import federation_ballot as mod
    return mod


@pytest.fixture(autouse=True)
def _clean(monkeypatch, fb):
    for k in ("FEDERATION_BALLOT_MODE", "FEDERATION_BALLOT_TRACK_RECORD", "NETWORK_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    fb._np.reset_cache()
    yield
    fb._np.reset_cache()


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _signed(fb, ballot, kid):
    from agentvault_registry.services.registry_card_signer_impl import _canonical_bytes
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    env = {"ballot": ballot, "alg": "EdDSA", "kid": kid, "signature": _b64u(key.sign(_canonical_bytes(ballot)))}
    jwks = {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": _b64u(pub), "kid": kid, "alg": "EdDSA", "use": "sig"},
                     {"kty": "OKP", "crv": "Ed25519", "x": _b64u(pub), "kid": "spiffe://b.test/dev/42#1"}]}
    return env, jwks


def _ballot(fb, choice="for"):
    return fb.build_ballot(proposal_id="5f1c0b9e-0000-4000-8000-000000000001",
                           host={"trust_domain": "a.test", "name": "Alpha"},
                           voter={"trust_domain": "b.test", "name": "Beta"}, choice=choice, basis={"mode": "operator"})


def test_switches_default_off_and_required(fb, monkeypatch):
    assert fb.ballot_mode() is False and fb.track_record_rule() == "required"
    monkeypatch.setenv("FEDERATION_BALLOT_MODE", "on")
    monkeypatch.setenv("FEDERATION_BALLOT_TRACK_RECORD", "observe")
    fb._np.reset_cache()
    assert fb.ballot_mode() is True and fb.track_record_rule() == "observe"
    monkeypatch.setenv("FEDERATION_BALLOT_TRACK_RECORD", "whatever")
    fb._np.reset_cache()
    assert fb.track_record_rule() == "required", "a typo enforces, never relaxes"


def test_the_document_and_its_choices(fb):
    b = _ballot(fb)
    assert b["kind"] == fb.KIND and b["registry"] == {"trust_domain": "b.test", "name": "Beta"} and b["choice"] == "for"
    with pytest.raises(fb.BallotRefusal) as e:
        _ballot(fb, choice="maybe")
    assert e.value.error == "bad_choice"
    assert fb.registry_id("B.Test", " Beta ") == "registry:b.test/beta"



# the store's RegistryBallotCreate.registry_id (agentvault-event-store/src/routers/federation_governance.py)
_STORE_REGISTRY_ID = re.compile(r"^registry:[^/\s]+/[^\s]+$")


def test_every_registry_id_is_one_the_store_accepts_and_case_never_splits_one(fb):
    """agentvault2-09's first FINISH run (2026-10-03): 'Sandbox Alpha' made 'registry:<td>/Sandbox Alpha' and the store
    refused every ballot of a registry whose name has a space (422 string_pattern_mismatch). The id's name part is a
    slug, and the same on both sides: a host derives a voter's id from its peer row ('eu'), the voter from its
    REGISTRY_NAME ('EU')."""
    assert fb.registry_id("sandbox-a.theprotocol.cloud", "Sandbox Alpha") == "registry:sandbox-a.theprotocol.cloud/sandbox-alpha"
    assert fb.registry_id("eu.theprotocol.cloud", "EU") == fb.registry_id("EU.theprotocol.cloud", "eu") == "registry:eu.theprotocol.cloud/eu"
    assert fb.registry_id("t.test", "Zürich Ops") == "registry:t.test/zurich-ops"
    for name in ("Sandbox Alpha", "EU", "a/b c", "Zürich Ops", "日本", "", "  ", "x" * 300, "tab\tname", "new\nline", "--a--"):
        rid = fb.registry_id("sandbox-b.theprotocol.cloud", name)
        assert _STORE_REGISTRY_ID.match(rid) and 12 <= len(rid) <= 255, (name, rid)


def test_a_ballot_verifies_only_under_its_exact_registry_key(fb):
    kid = "spiffe://b.test/registry/Beta#1"
    env, jwks = _signed(fb, _ballot(fb), kid)
    assert fb.verify_envelope(env, jwks, caller_td="b.test") == (True, "verified")
    tampered = {**env, "ballot": {**env["ballot"], "choice": "against"}}
    assert fb.verify_envelope(tampered, jwks, caller_td="b.test") == (False, "the signature does not verify")
    assert fb.verify_envelope(env, jwks, caller_td="c.test")[1].startswith("the kid is not a registry card key")
    dev = {**env, "kid": "spiffe://b.test/dev/42#1"}
    assert fb.verify_envelope(dev, jwks, caller_td="b.test")[1].startswith("the kid is not a registry card key"), \
        "a developer-card key in the same key set never signs a ballot"
    other = {**env, "kid": "spiffe://b.test/registry/Beta#2"}
    assert fb.verify_envelope(other, jwks, caller_td="b.test") == (False, "the caller's key set does not carry this kid"), \
        "no fallback to any key the set happens to carry"
    assert fb.verify_envelope({**env, "alg": "none"}, jwks, caller_td="b.test")[0] is False


def test_eligibility_judges_licence_and_track_record(fb):
    tracks = {"b.example": {"score": 92.0, "provisional": False}, "p.example": {"score": 99.0, "provisional": True}}

    def entry(host, licence_ok=True):
        return {"id": "registry:x/y", "public_host": host, "licence_state": "licensed" if licence_ok else "revoked",
                "licence_ok": licence_ok}
    ok = fb._judge(entry("b.example"), tracks, "required")
    assert ok["eligible"] and ok["reasons"] == [] and ok["track_record"]["score"] == 92.0
    prov = fb._judge(entry("p.example"), tracks, "required")
    assert not prov["eligible"] and prov["reasons"] == ["a provisional track record"]
    observed = fb._judge(entry("p.example"), tracks, "observe")
    assert observed["eligible"] and "observed, not enforced" in observed["reasons"][0]
    assert not fb._judge(entry("b.example", licence_ok=False), tracks, "observe")["eligible"], "the licence always binds"
    unread = fb._judge(entry("b.example"), None, "required")
    assert not unread["eligible"] and unread["reasons"] == ["the track records could not be read"]


def test_an_agents_federation_vote_is_refused_where_registries_cast_ballots(fb, monkeypatch):
    from agentvault_registry.routers import governance as g
    monkeypatch.setenv("FEDERATION_BALLOT_MODE", "on")
    fb._np.reset_cache()
    resp = asyncio.run(g.federation_vote(proposal_id="x", body=g.FederationVoteRequest(vote_in_favor=True),
                                         agent=None, db=None))
    assert resp.status_code == 409 and b"registry_ballots" in resp.body


def test_split_spiffe(fb):
    assert fb.split_spiffe("spiffe://A.test/operator/op1/registry") == ("a.test", ["operator", "op1", "registry"])
    assert fb.split_spiffe("not-a-spiffe") == ("", [])


def test_the_members_decide_and_the_operator_cannot_override_them(fb, monkeypatch):
    """The cast route, with every network and store call replaced: with members, the ballot is their result and an
    operator's different choice is refused; without members, the operator's choice is the ballot."""
    from agentvault_registry.routers import federation_ballots as rb
    from agentvault_registry.services import membership as ms
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "a.test")
    recorded = []

    async def open_here(db, host, pid):
        return {"id": pid, "ballot_mode": True, "status": "VOTING"}

    async def sign(db, ballot):
        return {"ballot": ballot, "alg": "EdDSA", "kid": "spiffe://a.test/registry/Alpha#1", "signature": "sig"}

    async def eligible(db, **_):
        return [{"kind": "self", "id": "registry:a.test/Alpha", "eligible": True, "reasons": []}]

    async def record(pid, env, voter):
        recorded.append((env["ballot"]["choice"], env["ballot"]["basis"]["mode"]))
        return {"ok": True}
    monkeypatch.setattr(rb, "_host_open_proposal", open_here)
    monkeypatch.setattr(fb, "sign_ballot", sign)
    monkeypatch.setattr(fb, "eligibility", eligible)
    monkeypatch.setattr(fb, "record_ballot", record)

    def members(n, basis):
        async def points(db, now=None):
            return n

        async def mb(db, ref):
            return dict(basis) if basis else None
        monkeypatch.setattr(ms, "member_mode", lambda: True)
        monkeypatch.setattr(ms, "network_points", points)
        monkeypatch.setattr(fb, "member_basis", mb)

    def cast(choice=None):
        return asyncio.run(rb.federation_ballot_cast(rb.CastIn(proposal_id="5f1c0b9e-0000-4000", choice=choice),
                                                     admin=None, db=None))
    decided = {"mode": "members", "local_proposal_id": 7, "points_for": 300.0, "points_against": 100.0, "voters": 3,
               "choice": "for"}
    members(400, decided)
    resp = cast("against")
    assert resp.status_code == 409 and b"members_decided" in resp.body
    assert cast()["choice"] == "for" and recorded[-1] == ("for", "members")
    members(400, None)
    assert b"members_must_vote" in cast("for").body
    members(0, None)
    assert b"choice_required" in cast().body
    assert cast("against")["choice"] == "against" and recorded[-1] == ("against", "operator")
    assert len(recorded) == 2
