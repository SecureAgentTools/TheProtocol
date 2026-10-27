"""§MEMBERSHIP phase D2 (2026-10-02) — federal ballots against a REAL Postgres: who the caller is, who may cast, what
the members decided, and the host's whole receive path with the network replaced by recorders.

Skipped unless MEMBERSHIP_TEST_DB names a throwaway database it may WIPE.
"""
from __future__ import annotations

import base64
import datetime as dt
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DB = os.environ.get("MEMBERSHIP_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
PID = "5f1c0b9e-0000-4000-8000-0000000000d2"


@pytest.fixture(autouse=True)
def _knobs(monkeypatch):
    from agentvault_registry.core import network_profile as np_
    for k in ("FEDERATION_BALLOT_MODE", "FEDERATION_BALLOT_TRACK_RECORD", "GOVERNANCE_WEIGHT_MODE", "NETWORK_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "a.test")
    monkeypatch.setenv("PUBLIC_URL", "https://alpha.example")
    np_.reset_cache()
    yield
    np_.reset_cache()


@pytest.fixture
async def session():
    from agentvault_registry.models import Base
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _peers(s):
    from agentvault_registry.models import Developer, PeerRegistry
    d = Developer(name="admin", email="admin@test.local", hashed_password="x", is_verified=True)
    s.add(d)
    await s.flush()

    def row(name, base, td, kind, status="ACTIVE", licence="licensed", host=None):
        return PeerRegistry(owner_developer_id=d.id, name=name, base_url=base, admin_contact_email="ops@test.local",
                            status=status, discovery_auth_info={}, peer_type=kind, trust_domain=td,
                            licence_state=licence,
                            cached_registry_card={"identity": {"public_url": f"https://{host or name.lower()}.example",
                                                               "trust_domain": td}})
    s.add_all([row("Beta", "https://beta.example:8443", "b.test", "frame", host="beta"),
               row("opa", "https://opa.example:31143", "a.test", "cloud_operator", host="opa"),
               row("Gone", "https://gone.example", "g.test", "frame", status="INACTIVE"),
               row("Revoked", "https://rev.example", "r.test", "frame", licence="revoked", host="rev"),
               row("Twin1", "https://t1.example", "t.test", "frame"), row("Twin2", "https://t2.example", "t.test", "frame")])
    await s.commit()


async def test_the_caller_binds_to_one_active_row(session):
    from agentvault_registry.services import federation_ballot as fb
    await _peers(session)
    assert (await fb.caller_row(session, "spiffe://b.test/service/beta-registry")).name == "Beta"
    assert (await fb.caller_row(session, "spiffe://a.test/operator/opa/registry")).name == "opa"
    assert await fb.caller_row(session, "spiffe://b.test/operator/opa/registry") is None, "an operator of another domain"
    assert await fb.caller_row(session, "spiffe://g.test/service/registry") is None, "an INACTIVE row binds nothing"
    assert await fb.caller_row(session, "spiffe://t.test/service/registry") is None, "two frames of one domain: ambiguous"
    assert await fb.caller_row(session, "not-spiffe") is None


async def test_eligibility_is_this_host_and_its_licensed_frames_and_operators(session, monkeypatch):
    from agentvault_registry.config import settings
    from agentvault_registry.services import federation_ballot as fb
    monkeypatch.setattr(settings, "REGISTRY_NAME", "Alpha")
    await _peers(session)
    tracks = {"alpha.example": {"score": 97.0, "provisional": False}, "beta.example": {"score": 88.0, "provisional": False},
              "opa.example": {"score": 91.0, "provisional": True}}
    got = {e["name"]: e for e in await fb.eligibility(session, tracks=tracks)}
    assert set(got) == {"Alpha", "Beta", "opa", "Revoked", "Twin1", "Twin2"}, "INACTIVE rows are not in the electorate"
    assert got["Alpha"]["eligible"] and got["Alpha"]["id"] == "registry:a.test/alpha"
    assert got["Beta"]["eligible"] and not got["opa"]["eligible"] and got["opa"]["reasons"] == ["a provisional track record"]
    assert not got["Revoked"]["eligible"] and got["Revoked"]["reasons"][0] == "licence revoked"
    monkeypatch.setenv("FEDERATION_BALLOT_TRACK_RECORD", "observe")
    fb._np.reset_cache()
    got = {e["name"]: e for e in await fb.eligibility(session, tracks=tracks)}
    assert got["opa"]["eligible"] and not got["Revoked"]["eligible"]


async def test_the_members_decide_and_a_tie_abstains(session):
    from agentvault_registry.models import GovernanceProposal, Vote
    from agentvault_registry.services import federation_ballot as fb
    ref = fb.federation_ref("a.test", PID)
    assert await fb.member_basis(session, ref) is None
    p = GovernanceProposal(proposer_did="registry:a.test/Alpha", title="Federation ballot: x", description="d",
                           status="VOTING", proposal_type="federation_ballot", end_timestamp=NOW + dt.timedelta(hours=1),
                           federation_ref=ref)
    session.add(p)
    await session.commit()
    with pytest.raises(fb.BallotRefusal) as e:
        await fb.member_basis(session, ref)
    assert e.value.error == "local_vote_open"
    session.add_all([Vote(proposal_id=p.id, voter_did="did:m1", vote=True, voting_power=150),
                     Vote(proposal_id=p.id, voter_did="did:m2", vote=False, voting_power=120)])
    await session.execute(text("UPDATE governance_proposals SET end_timestamp = now() - interval '1 minute' WHERE id = :i"),
                          {"i": p.id})
    await session.commit()
    basis = await fb.member_basis(session, ref)
    assert basis["choice"] == "for" and basis["points_for"] == 150 and basis["voters"] == 2
    session.add(Vote(proposal_id=p.id, voter_did="did:m3", vote=False, voting_power=30))
    await session.commit()
    assert (await fb.member_basis(session, ref))["choice"] == "abstain", "150 against 150: a tie abstains"


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


async def test_the_host_receives_only_a_verified_eligible_ballot(session, monkeypatch):
    from agentvault_registry.config import settings
    from agentvault_registry.services import federation_ballot as fb
    from agentvault_registry.services.registry_card_signer_impl import _canonical_bytes
    monkeypatch.setattr(settings, "REGISTRY_NAME", "Alpha")
    await _peers(session)
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    kid = "spiffe://b.test/registry/Beta#1"
    jwks = {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": _b64u(pub), "kid": kid}]}

    def envelope(**over):
        b = fb.build_ballot(proposal_id=PID, host={"trust_domain": "a.test", "name": "Alpha"},
                            voter={"trust_domain": "b.test", "name": "Beta"}, choice="for", basis={"mode": "operator"})
        b.update(over)
        return {"ballot": b, "alg": "EdDSA", "kid": kid, "signature": _b64u(key.sign(_canonical_bytes(b)))}

    async def jwks_of(row):
        assert row.name == "Beta", "the key set comes from the CALLER's own row"
        return jwks

    async def proposal(pid):
        return {"id": pid, "ballot_mode": True, "status": "VOTING",
                "end_timestamp": (NOW + dt.timedelta(days=1)).isoformat()}
    recorded = []

    async def record(pid, env, voter):
        recorded.append((pid, env["ballot"]["choice"], voter["id"], voter["licence_state"]))
        return {"registry_id": voter["id"]}

    async def tracks(force=False):
        return {"beta.example": {"score": 90.0, "provisional": False}}
    monkeypatch.setattr(fb, "fetch_peer_jwks", jwks_of)
    monkeypatch.setattr(fb, "host_proposal", proposal)
    monkeypatch.setattr(fb, "record_ballot", record)
    monkeypatch.setattr(fb, "track_records_by_host", tracks)

    beta = "spiffe://b.test/service/beta-registry"
    out = await fb.receive_ballot(session, beta, envelope())
    assert out["recorded"] and recorded == [(PID, "for", "registry:b.test/beta", "licensed")]

    async def refused(caller, env):
        with pytest.raises(fb.BallotRefusal) as e:
            await fb.receive_ballot(session, caller, env)
        return e.value.error
    assert await refused("spiffe://x.test/service/registry", envelope()) == "unknown_caller"
    assert await refused(beta, envelope(host={"trust_domain": "c.test", "name": "C"})) == "wrong_host"
    assert await refused(beta, envelope(registry={"trust_domain": "a.test", "name": "Beta"})) == "registry_mismatch"
    forged = envelope()
    forged["ballot"] = {**forged["ballot"], "choice": "against"}
    assert await refused(beta, forged) == "bad_signature"
    assert await refused(beta, envelope(cast_at=(NOW + dt.timedelta(hours=1)).isoformat())) == "cast_in_future"
    for broken in ({"cast_at": None}, {"cast_at": "2026-10-02T12:00:00"}, {"choice": "maybe"}, {"proposal_id": None}):
        assert await refused(beta, envelope(**broken)) == "not_a_ballot", broken

    async def closed(pid):
        return {"id": pid, "ballot_mode": True, "status": "PASSED", "end_timestamp": NOW.isoformat()}
    monkeypatch.setattr(fb, "host_proposal", closed)
    assert await refused(beta, envelope()) == "proposal_closed"
    monkeypatch.setattr(fb, "host_proposal", proposal)

    async def no_tracks(force=False):
        return {}
    monkeypatch.setattr(fb, "track_records_by_host", no_tracks)
    assert await refused(beta, envelope()) == "not_eligible", "no track record, required by default"
    assert len(recorded) == 1, "nothing refused was written"


async def test_a_name_with_a_space_or_another_case_is_one_registry(session, monkeypatch):
    """agentvault2-09's first FINISH run (2026-10-03): the host recorded the peer's ballot under the id it derives from
    ITS row ('Sandbox Alpha' kept its space, and the store refused it), and a voter compares the host's list with an id
    it derives from its own REGISTRY_NAME. Both now give the same slug, whatever the spaces and the case."""
    from agentvault_registry.config import settings
    from agentvault_registry.models import Developer, PeerRegistry
    from agentvault_registry.services import federation_ballot as fb
    monkeypatch.setattr(settings, "REGISTRY_NAME", "Sandbox Alpha")
    d = Developer(name="admin", email="admin@test.local", hashed_password="x", is_verified=True)
    session.add(d)
    await session.flush()
    session.add(PeerRegistry(owner_developer_id=d.id, name="sandbox beta", base_url="https://beta.example:8443",
                             admin_contact_email="ops@test.local", status="ACTIVE", discovery_auth_info={},
                             peer_type="frame", trust_domain="b.test", licence_state="licensed",
                             cached_registry_card={"identity": {"public_url": "https://beta.example", "trust_domain": "b.test"}}))
    await session.commit()
    monkeypatch.setenv("FEDERATION_BALLOT_TRACK_RECORD", "observe")
    fb._np.reset_cache()
    got = {e["name"]: e["id"] for e in await fb.eligibility(session, tracks={})}
    assert got == {"Sandbox Alpha": "registry:a.test/sandbox-alpha", "sandbox beta": "registry:b.test/sandbox-beta"}, got
    assert fb.own_identity()["id"] == "registry:a.test/sandbox-alpha"
    # the voter calling itself 'Sandbox Beta' is the host row 'sandbox beta': one registry, one id
    assert fb.registry_id("b.test", "Sandbox Beta") == got["sandbox beta"]

