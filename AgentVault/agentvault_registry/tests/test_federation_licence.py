"""§FEDLICENCE (2026-09-28): the signed federation licence. His word: a licence hash on every card, "a derived field also
so it cant be tricked". These pin the property that makes that true: a verdict comes from the ISSUER's signature and the
issuer's signed list, never from what the showing frame says about itself.

Pure functions only (no database, no network); the per-cycle refresh runs against in-memory stand-ins for its storage."""
import asyncio
import datetime as dt
import types

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentvault_registry.services import federation_licence as fl

GTD = "genesis.example.org"
FTD = "frame.example.org"
OTHER = "stranger.example.org"
NOW = 1_800_000_000


def _key():
    priv = Ed25519PrivateKey.generate()
    jwk = fl.public_jwk_of(priv)
    return priv, jwk, fl.jwk_thumbprint(jwk)


def _genesis(priv, jwk, kid, td=GTD):
    p = fl.build_payload(type_="genesis", sub={"trust_domain": td, "name": "EU", "url": "https://eu.example.org"},
                         iss={"trust_domain": td, "name": "EU", "kid": kid, "licence": None}, plan="genesis",
                         network=td, key=jwk, now=dt.datetime.fromtimestamp(NOW - 1000, dt.timezone.utc))
    return fl.sign_jws(p, priv, kid=kid)


def _frame(gpriv, gkid, root_hash, fjwk, *, td=FTD, plan="research", days=None, iat=NOW - 500):
    p = fl.build_payload(type_="frame", sub={"trust_domain": td, "name": "ASIA", "url": "https://asia.example.org"},
                         iss={"trust_domain": GTD, "name": "EU", "kid": gkid, "licence": root_hash}, plan=plan,
                         network=GTD, key=fjwk, days=days, now=dt.datetime.fromtimestamp(iat, dt.timezone.utc))
    return fl.sign_jws(p, gpriv, kid=gkid)


@pytest.fixture
def net():
    gpriv, gjwk, gkid = _key()
    root = _genesis(gpriv, gjwk, gkid)
    fpriv, fjwk, fkid = _key()
    frame = _frame(gpriv, gkid, fl.licence_hash(root), fjwk)
    return types.SimpleNamespace(gpriv=gpriv, gjwk=gjwk, gkid=gkid, root=root, fpriv=fpriv, fjwk=fjwk, fkid=fkid,
                                 frame=frame)


def _lists(*pairs, fetched=NOW - 10, issuer=GTD):
    return {issuer: {"fetched_at": fetched, "states": dict(pairs)}}


# --- the JWS primitives ---------------------------------------------------------------------------------------------

def test_a_signed_certificate_verifies_and_a_tampered_one_does_not(net):
    assert fl.verify_jws(net.root, net.gjwk)
    h, p, s = net.frame.split(".")
    tampered_payload = fl._b64u(fl.canonical({**fl.parse_jws(net.frame)[1], "plan": "enterprise"}))
    assert not fl.verify_jws(".".join((h, tampered_payload, s)), net.gjwk)
    assert not fl.verify_jws(net.frame, net.fjwk)  # the frame's own key did not sign its licence


def test_a_certificate_stays_under_the_card_validators_string_cap():
    # peers' validators refuse a WHOLE card holding any string over 2048 characters; long names must still fit
    gpriv, gjwk, gkid = _key()
    fpriv, fjwk, _ = _key()
    long_td = "a-very-long-frame-name-that-someone-chose.region-west.enterprise-customer.example.org"
    p = fl.build_payload(type_="frame", sub={"trust_domain": long_td, "name": "N" * 120,
                                             "url": "https://" + long_td + "/some/long/public/path",
                                             "spiffe": "spiffe://" + long_td + "/operator/x" * 3},
                         iss={"trust_domain": GTD, "name": "E" * 120, "kid": gkid, "licence": "f" * 64},
                         plan="enterprise", network=GTD, key=fjwk, days=365)
    jws = fl.sign_jws(p, gpriv, kid=gkid)
    assert len(jws) < fl.MAX_JWS_LEN < 2048


# --- the root -------------------------------------------------------------------------------------------------------

def test_the_root_must_be_a_self_signed_genesis_of_the_configured_network(net):
    root, why = fl.verify_root(net.root, genesis_td=GTD)
    assert root is not None and why == ""
    assert fl.verify_root(net.root, genesis_td=OTHER)[0] is None          # another network's genesis
    assert fl.verify_root(net.frame, genesis_td=GTD)[0] is None            # a frame certificate is not a root
    assert fl.verify_root(net.root, genesis_td=GTD, pin="0" * 64)[0] is None  # the pin decides when set
    assert fl.verify_root(net.root, genesis_td=GTD, pin=fl.licence_hash(net.root))[0] is not None
    assert fl.verify_root(None, genesis_td=GTD)[0] is None


# --- network verdicts -----------------------------------------------------------------------------------------------

def _eval(net, cert=None, *, td=FTD, lists=None, now=NOW, root=None, pin=""):
    return fl.evaluate(cert if cert is not None else net.frame, [net.root], expect_trust_domain=td,
                       root_jws=(root if root is not None else net.root), genesis_td=GTD, pin=pin,
                       lists=lists if lists is not None else _lists((fl.licence_hash(net.frame), "active")), now_ts=now)


def test_a_genesis_signed_frame_licence_on_the_genesis_list_is_licensed(net):
    v = _eval(net)
    assert v.state == "licensed" and v.passes and v.hash == fl.licence_hash(net.frame) and v.plan == "research"


def test_the_genesis_list_decides_revocation_and_suspension(net):
    h = fl.licence_hash(net.frame)
    assert _eval(net, lists=_lists((h, "revoked"))).state == "revoked"
    assert _eval(net, lists=_lists((h, "suspended"))).state == "suspended"


def test_no_fresh_list_is_unverified_never_licensed(net):
    h = fl.licence_hash(net.frame)
    assert _eval(net, lists={}).state == "unverified"
    stale = _lists((h, "active"), fetched=NOW - 2 * 86400)
    v = _eval(net, lists=stale)
    assert v.state == "unverified" and "old" in v.reason
    assert _eval(net, lists=_lists(("0" * 64, "active"))).state == "unverified"  # the list does not name it


def test_a_copied_certificate_fails_on_another_trust_domain(net):
    v = _eval(net, td=OTHER)
    assert v.state == "invalid" and "names" in v.reason


def test_a_licence_signed_by_anyone_but_the_genesis_is_invalid(net):
    rogue_priv, _rj, rogue_kid = _key()
    forged = _frame(rogue_priv, rogue_kid, fl.licence_hash(net.root), net.fjwk)
    assert _eval(net, forged, lists=_lists((fl.licence_hash(forged), "active"))).state == "invalid"


def test_a_second_genesis_is_not_the_network_root(net):
    other_priv, other_jwk, other_kid = _key()
    rival = _genesis(other_priv, other_jwk, other_kid)  # another self-signed genesis for the SAME trust domain
    v = fl.evaluate(rival, [], expect_trust_domain=GTD, root_jws=net.root, genesis_td=GTD, lists={}, now_ts=NOW)
    assert v.state == "invalid"
    assert fl.evaluate(net.root, [], expect_trust_domain=GTD, root_jws=net.root, genesis_td=GTD, lists={},
                       now_ts=NOW).state == "genesis"


def test_an_enterprise_licence_expires_after_its_year(net):
    ent = _frame(net.gpriv, net.gkid, fl.licence_hash(net.root), net.fjwk, plan="enterprise",
                 days=fl.NETWORK_PLANS["enterprise"])
    lists = _lists((fl.licence_hash(ent), "active"))
    assert _eval(net, ent, lists=lists).state == "licensed"
    assert _eval(net, ent, lists=lists, now=NOW + 366 * 86400).state == "expired"
    # his plans: research, private, non-profit and founding never expire
    assert all(fl.NETWORK_PLANS[p] is None for p in ("research", "private", "non-profit", "founding"))


def test_no_certificate_is_unlicensed_and_junk_is_invalid(net):
    assert fl.evaluate(None, [], expect_trust_domain=FTD, root_jws=net.root, genesis_td=GTD).state == "unlicensed"
    assert fl.evaluate("not.a.jws", [], expect_trust_domain=FTD, root_jws=net.root, genesis_td=GTD).state == "invalid"


def test_without_a_known_root_nothing_passes(net):
    v = fl.evaluate(net.frame, [net.root], expect_trust_domain=FTD, root_jws=None, genesis_td=GTD,
                    lists=_lists((fl.licence_hash(net.frame), "active")), now_ts=NOW)
    assert v.state == "unverified" and not v.passes


# --- operator licences (issued by the frame under its own policy) ---------------------------------------------------

def _operator(fpriv, fkid, frame_hash, *, td=FTD):
    p = fl.build_payload(type_="operator", sub={"trust_domain": td, "name": "shenzhen", "spiffe": f"spiffe://{td}/operator/shenzhen/registry"},
                         iss={"trust_domain": td, "name": "ASIA", "kid": fkid, "licence": frame_hash},
                         plan="operator-free", network=GTD)
    return fl.sign_jws(p, fpriv, kid=fkid)


def test_an_operator_licence_is_the_frames_signature_and_the_frames_list(net):
    op = _operator(net.fpriv, net.fkid, fl.licence_hash(net.frame))
    ok = fl.evaluate_operator(op, frame_cert_jws=net.frame, frame_td=FTD,
                              lists={FTD: {"fetched_at": NOW, "states": {fl.licence_hash(op): "active"}}}, now_ts=NOW)
    assert ok.state == "licensed" and ok.plan == "operator-free"
    revoked = fl.evaluate_operator(op, frame_cert_jws=net.frame, frame_td=FTD,
                                   lists={FTD: {"fetched_at": NOW, "states": {fl.licence_hash(op): "revoked"}}}, now_ts=NOW)
    assert revoked.state == "revoked"
    other_priv, _oj, other_kid = _key()
    forged = _operator(other_priv, other_kid, fl.licence_hash(net.frame))
    assert fl.evaluate_operator(forged, frame_cert_jws=net.frame, frame_td=FTD, lists={}, now_ts=NOW).state == "invalid"
    # a standalone frame (no network certificate carrying its key): nobody outside can check, so unverified
    assert fl.evaluate_operator(op, frame_cert_jws=None, frame_td=FTD, lists={}, now_ts=NOW).state == "unverified"


def test_the_operator_policy_is_the_frames_own_and_free_by_default(monkeypatch):
    monkeypatch.delenv("FEDERATION_OPERATOR_LICENCE_PLAN", raising=False)
    monkeypatch.delenv("FEDERATION_OPERATOR_LICENCE_DAYS", raising=False)
    assert fl.operator_policy() == {"plan": "operator-free", "days": None}
    monkeypatch.setenv("FEDERATION_OPERATOR_LICENCE_PLAN", "operator-pro")
    monkeypatch.setenv("FEDERATION_OPERATOR_LICENCE_DAYS", "30")
    assert fl.operator_policy() == {"plan": "operator-pro", "days": 30}


# --- lists ----------------------------------------------------------------------------------------------------------

def test_a_list_verifies_only_under_its_issuers_key(net):
    payload = {"kind": fl.LIST_KIND, "issuer": {"trust_domain": GTD, "name": "EU", "kid": net.gkid},
               "generated_at": NOW, "licences": [{"hash": fl.licence_hash(net.frame), "state": "active"}]}
    jws = fl.sign_jws(payload, net.gpriv, kid=net.gkid, typ=fl.LIST_TYP)
    got, why = fl.verify_list(jws, net.gjwk, issuer_td=GTD)
    assert got is not None and fl.list_states(got) == {fl.licence_hash(net.frame): "active"}
    assert fl.verify_list(jws, net.fjwk, issuer_td=GTD)[0] is None          # another key
    assert fl.verify_list(jws, net.gjwk, issuer_td=OTHER)[0] is None        # another issuer named


# --- the card's share of the ETag -----------------------------------------------------------------------------------

def test_the_etag_token_moves_with_state_and_hashes():
    a = fl.etag_token({"state": "licensed", "hash": "a" * 64})
    assert a != fl.etag_token({"state": "revoked", "hash": "a" * 64})
    assert a != fl.etag_token({"state": "licensed", "hash": "b" * 64})
    assert a != fl.etag_token({"state": "licensed", "hash": "a" * 64, "operator": {"state": "licensed", "hash": "c" * 64}})
    assert fl.etag_token(None) == fl.etag_token({})


def test_the_licence_leaves_are_signed_on_every_card():
    from agentvault_registry.services.registry_card_signer import SIGNED_CANONICAL_PATHS, extract_paths
    for leaf in ("federation.licence.state", "federation.licence.hash", "federation.licence.operator.hash"):
        assert leaf in SIGNED_CANONICAL_PATHS
    # an older card without the block extracts None for every new leaf (older signatures keep verifying)
    got = extract_paths({"federation": {"policy_hash": "x"}}, ["federation.licence.state", "federation.licence.hash"])
    assert got == {"federation.licence.state": None, "federation.licence.hash": None}


def test_the_admin_card_put_cannot_carry_a_licence():
    from pydantic import ValidationError
    from agentvault_registry.schemas import RegistryCardOperatorPut
    with pytest.raises(ValidationError):
        RegistryCardOperatorPut(**{"federation": {"licence": {"state": "genesis", "hash": "f" * 64}}})


# --- the trust check (observe counts, enforce refuses) -------------------------------------------------------------

@pytest.fixture
def trust(monkeypatch):
    from agentvault_registry.core import mtls_auth as m
    monkeypatch.setattr(m, "TRUSTED_SPIFFE_DOMAINS", ["own.example.org"])
    monkeypatch.setattr(m, "_PEER_TRUST_DOMAINS", frozenset({"peer.example.org", "bad.example.org"}))
    monkeypatch.setattr(m, "_PEER_TRUST_READ_AT", 0.0)
    monkeypatch.setattr(m, "_LICENCE_STATE_BY_TD", {"peer.example.org": "licensed", "bad.example.org": "revoked"})
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "own.example.org")
    return m


def test_off_changes_nothing(trust, monkeypatch):
    monkeypatch.delenv("FEDERATION_LICENCE_MODE", raising=False)
    assert trust.is_trusted_spiffe_id("spiffe://bad.example.org/service/registry")


def test_observe_refuses_nothing(trust, monkeypatch):
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "observe")
    assert trust.is_trusted_spiffe_id("spiffe://bad.example.org/service/registry")
    assert trust.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")


def test_enforce_refuses_a_failing_licence_and_never_the_own_domain(trust, monkeypatch):
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "enforce")
    assert not trust.is_trusted_spiffe_id("spiffe://bad.example.org/service/registry")
    assert trust.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")
    assert trust.is_trusted_spiffe_id("spiffe://own.example.org/operator/shenzhen/registry")
    # a peer never evaluated, or unverified (the genesis unreachable), is not refused: no partition by outage
    trust._LICENCE_STATE_BY_TD["peer.example.org"] = "unverified"
    assert trust.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")
    trust._LICENCE_STATE_BY_TD.pop("peer.example.org")
    assert trust.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")


def test_the_trust_rows_accept_the_licence_column_and_the_old_three(trust):
    rows4 = [("frame", "ACTIVE", "peer.example.org", "licensed"), ("frame", "ACTIVE", "bad.example.org", "revoked"),
             ("cloud_operator", "ACTIVE", "bad.example.org", "licensed"), ("frame", "INACTIVE", "gone.example.org", "revoked")]
    assert trust.domains_from_peer_rows(rows4) == frozenset({"peer.example.org", "bad.example.org"})
    assert trust.licence_states_from_peer_rows(rows4) == {"peer.example.org": "licensed", "bad.example.org": "revoked"}
    rows3 = [("frame", "ACTIVE", "peer.example.org")]
    assert trust.domains_from_peer_rows(rows3) == frozenset({"peer.example.org"})
    assert trust.licence_states_from_peer_rows(rows3) == {}


# --- the per-cycle refresh (storage replaced by in-memory stand-ins) ------------------------------------------------

class _Row(types.SimpleNamespace):
    pass


def _store_for(monkeypatch, rows):
    async def get_certs(db, role):
        return [r for r in rows if r.role == role]

    async def get_cert(db, role):
        live = [r for r in rows if r.role == role and r.state not in ("revoked", "replaced")]
        return live[-1] if live else None

    async def store_cert(db, cert, *, role, chain=None, state="active", created_by=None):
        for r in rows:
            if r.hash == cert.hash and r.role == role:
                return r
        r = _Row(hash=cert.hash, role=role, jws=cert.jws, chain=list(chain or []), type=cert.type, state=state,
                 state_reason=None, checked_at=None, sub_trust_domain=cert.sub_td, sub_name=cert.sub_name,
                 iss_trust_domain=cert.iss_td, network=None, plan=cert.plan,
                 expires_at=(dt.datetime.fromtimestamp(cert.exp, dt.timezone.utc) if cert.exp else None),
                 updated_at=None)
        rows.append(r)
        return r

    monkeypatch.setattr(fl, "get_certs", get_certs)
    monkeypatch.setattr(fl, "get_cert", get_cert)
    monkeypatch.setattr(fl, "store_cert", store_cert)
    monkeypatch.setattr(fl, "_LISTS", {})
    # the fixtures are dated around NOW; the cycle reads the clock through _now()
    monkeypatch.setattr(fl, "_now", lambda: dt.datetime.fromtimestamp(NOW, dt.timezone.utc))


class _DB:
    async def flush(self):
        return None


def _peer(name, td, card=None, verified=True, peer_type="frame"):
    return _Row(name=name, trust_domain=td, peer_type=peer_type, cached_registry_card=card,
                card_signature_verified=verified, licence_state=None, licence_reason=None, licence_hash=None,
                licence_checked_at=None)


def test_a_licensed_frames_cycle_reads_the_root_and_the_list_and_judges_every_peer(net, monkeypatch):
    monkeypatch.setenv("FEDERATION_GENESIS_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", FTD)
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "observe")
    monkeypatch.delenv("FEDERATION_GENESIS_CERT_HASH", raising=False)
    held = _Row(hash=fl.licence_hash(net.frame), role="held", jws=net.frame, chain=[net.root], type="frame",
                state="unverified", state_reason=None, checked_at=None)
    rows = [held]
    _store_for(monkeypatch, rows)
    list_payload = {"kind": fl.LIST_KIND, "issuer": {"trust_domain": GTD, "name": "EU", "kid": net.gkid},
                    "generated_at": NOW, "licences": [{"hash": fl.licence_hash(net.frame), "state": "active"}]}
    list_jws = fl.sign_jws(list_payload, net.gpriv, kid=net.gkid, typ=fl.LIST_TYP)

    async def fetch_json(peer, path):
        if path == fl.FED_OWN_PATH:
            return 200, {"state": "genesis", "certificate": net.root}
        return 200, {"jws": list_jws}

    genesis_peer = _peer("eu", GTD, card={"federation": {"licence": {"certificate": net.root, "chain": []}}})
    unlicensed = _peer("hansa", OTHER, card={"federation": {"licence": {"state": "unlicensed"}}})
    unsigned = _peer("mystery", "mystery.example.org", card={"federation": {}}, verified=False)
    own_op = _peer("shenzhen", FTD, peer_type="cloud_operator")
    summary = asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[genesis_peer, unlicensed, unsigned, own_op],
                                                 fetch_json=fetch_json))
    assert summary["self"]["state"] == "licensed", summary
    assert held.state == "licensed"
    assert any(r.role == "root" and r.hash == fl.licence_hash(net.root) for r in rows)
    assert genesis_peer.licence_state == "genesis"
    assert unlicensed.licence_state == "unlicensed"
    assert unsigned.licence_state == "unverified"
    assert own_op.licence_state == "same-domain"
    assert summary["would_refuse"] == ["hansa"]


def test_a_cycle_keeps_the_trusted_root_when_the_genesis_offers_another(net, monkeypatch):
    monkeypatch.setenv("FEDERATION_GENESIS_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", FTD)
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "observe")
    monkeypatch.delenv("FEDERATION_GENESIS_CERT_HASH", raising=False)
    trusted = _Row(hash=fl.licence_hash(net.root), role="root", jws=net.root, chain=[], type="genesis", state="active")
    rows = [trusted]
    _store_for(monkeypatch, rows)
    other_priv, other_jwk, other_kid = _key()
    rival = _genesis(other_priv, other_jwk, other_kid)

    async def fetch_json(peer, path):
        if path == fl.FED_OWN_PATH:
            return 200, {"state": "genesis", "certificate": rival}
        return 404, None

    summary = asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[_peer("eu", GTD)], fetch_json=fetch_json))
    assert [r.hash for r in rows if r.role == "root"] == [fl.licence_hash(net.root)]
    assert any("kept the old one" in n for n in summary["notes"])


def test_with_no_network_configured_the_cycle_checks_nothing(monkeypatch):
    monkeypatch.delenv("FEDERATION_GENESIS_TRUST_DOMAIN", raising=False)

    async def boom(*a, **k):  # pragma: no cover — must not be called
        raise AssertionError("no fetch without a network")

    summary = asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[_peer("x", OTHER)], fetch_json=boom))
    assert summary["peers"] == {} and "unset" in summary["notes"][0]


def test_an_operator_slug_is_read_only_from_this_frames_own_domain(monkeypatch):
    assert fl._operator_slug_from_spiffe("spiffe://frame.example.org/operator/shenzhen/registry", FTD) == "shenzhen"
    assert fl._operator_slug_from_spiffe("spiffe://stranger.example.org/operator/shenzhen/registry", FTD) is None
    assert fl._operator_slug_from_spiffe("spiffe://frame.example.org/service/registry", FTD) is None


# --- agentvault2-41's review: a delivered chain never introduces a root; the verdict fallback is narrow and loud -----

def _install_env(monkeypatch, net, rows, *, pin=None):
    monkeypatch.setenv("FEDERATION_GENESIS_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", FTD)
    if pin:
        monkeypatch.setenv("FEDERATION_GENESIS_CERT_HASH", pin)
    else:
        monkeypatch.delenv("FEDERATION_GENESIS_CERT_HASH", raising=False)
    _store_for(monkeypatch, rows)

    async def own_key(db):
        return net.fjwk

    monkeypatch.setattr(fl, "active_key_jwk", own_key)


def test_a_delivered_chain_does_not_introduce_a_root(net, monkeypatch):
    rows = []
    _install_env(monkeypatch, net, rows)
    row, v = asyncio.run(fl.install_network_licence(_DB(), net.frame, [net.root]))
    assert v.state == "unverified" and "not trusted here yet" in v.reason
    assert [r.role for r in rows] == ["held"]  # the licence is held, the root is NOT trusted from a finalize


def test_the_pin_or_an_already_trusted_root_lets_the_install_verify(net, monkeypatch):
    rows = []
    _install_env(monkeypatch, net, rows, pin=fl.licence_hash(net.root))
    monkeypatch.setattr(fl, "_LISTS", {GTD: {"fetched_at": NOW, "states": {fl.licence_hash(net.frame): "active"}}})
    row, v = asyncio.run(fl.install_network_licence(_DB(), net.frame, [net.root]))
    assert v.state == "licensed"
    assert sorted(r.role for r in rows) == ["held", "root"]


def test_a_chain_naming_another_root_than_the_trusted_one_is_refused(net, monkeypatch):
    other_priv, other_jwk, other_kid = _key()
    trusted = _Row(hash="a" * 64, role="root", jws=_genesis(other_priv, other_jwk, other_kid), chain=[], type="genesis",
                   state="active")
    rows = [trusted]
    _install_env(monkeypatch, net, rows)
    with pytest.raises(ValueError, match="differs from the root"):
        asyncio.run(fl.install_network_licence(_DB(), net.frame, [net.root]))


def test_a_licence_for_another_key_is_refused_at_install(net, monkeypatch):
    rows = []
    _install_env(monkeypatch, net, rows)
    _p, other_jwk, _k = _key()

    async def other_key(db):
        return other_jwk

    monkeypatch.setattr(fl, "active_key_jwk", other_key)
    with pytest.raises(ValueError, match="licence-signing key"):
        asyncio.run(fl.install_network_licence(_DB(), net.frame, [net.root]))


class _FakeDBCtx:
    def __init__(self, first_exc):
        self.first_exc, self.calls = first_exc, 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        self.calls += 1
        if self.calls == 1 and self.first_exc is not None:
            raise self.first_exc

        class _Res:
            def all(self_inner):
                return [("frame", "ACTIVE", "peer.example.org")]
        return _Res()

    async def rollback(self):
        return None


def test_the_trust_rows_fall_back_only_for_the_missing_column(monkeypatch):
    from agentvault_registry.core import mtls_auth as m
    from agentvault_registry import database
    ctx = _FakeDBCtx(RuntimeError('column "licence_state" does not exist'))
    monkeypatch.setattr(database, "get_db_context", lambda: ctx)
    rows = asyncio.run(m._fetch_peer_rows())
    assert rows == [("frame", "ACTIVE", "peer.example.org")] and m._LICENCE_VERDICTS_AVAILABLE is False
    other = _FakeDBCtx(RuntimeError("connection reset by peer"))
    monkeypatch.setattr(database, "get_db_context", lambda: other)
    with pytest.raises(RuntimeError, match="connection reset"):
        asyncio.run(m._fetch_peer_rows())


def test_an_unconfigured_frame_carries_no_licence_block_on_its_card(net, monkeypatch):
    # before a network's genesis ceremony, a frame on this image must not read "standalone" on its card
    monkeypatch.delenv("FEDERATION_GENESIS_TRUST_DOMAIN", raising=False)
    monkeypatch.delenv("FEDERATION_LICENCE_MODE", raising=False)
    rows = []
    _store_for(monkeypatch, rows)

    async def no_key(db):
        return None

    monkeypatch.setattr(fl, "active_key_jwk", no_key)
    assert asyncio.run(fl.card_block(_DB(), is_operator=False, for_card=True)) is None
    public = asyncio.run(fl.card_block(_DB(), is_operator=False))
    assert public["state"] == "unlicensed"  # the public route always answers
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "observe")
    assert asyncio.run(fl.card_block(_DB(), is_operator=False, for_card=True))["state"] == "unlicensed"


# --- agentvault2-41's second review ---------------------------------------------------------------------------------

def _issuer_env(monkeypatch, net, rows):
    """This registry IS the genesis (GTD), holding its root; issue() signs with the genesis key."""
    monkeypatch.setenv("FEDERATION_GENESIS_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", GTD)
    monkeypatch.delenv("FEDERATION_GENESIS_CERT_HASH", raising=False)
    root_row = _Row(hash=fl.licence_hash(net.root), role="root", jws=net.root, chain=[], type="genesis",
                    state="active", sub_trust_domain=GTD, sub_name="EU", iss_trust_domain=GTD, expires_at=None)
    rows.append(root_row)
    _store_for(monkeypatch, rows)

    async def key(db):
        return types.SimpleNamespace(kid=net.gkid, public_jwk=net.gjwk), net.gpriv

    monkeypatch.setattr(fl, "get_or_create_key", key)


def test_1_a_revoke_is_per_subject_so_an_older_certificate_does_not_keep_the_frame_licensed(net, monkeypatch):
    rows = []
    _issuer_env(monkeypatch, net, rows)
    sub = {"trust_domain": FTD, "name": "ASIA", "key": net.fjwk}
    _ra, cert_a = asyncio.run(fl.issue(_DB(), type_="frame", sub=sub, plan="research", days=None, public_name="EU"))
    _rb, cert_b = asyncio.run(fl.issue(_DB(), type_="frame", sub=sub, plan="enterprise", days=None, public_name="EU"))
    issued = {r.hash: r for r in rows if r.role == "issued"}
    assert issued[cert_a.hash].state == "superseded"      # a new licence retires the subject's older one
    asyncio.run(fl.set_issued_state(_DB(), cert_b.hash, "revoked", "test"))
    states = asyncio.run(fl.own_issued_states(_DB()))
    lists = {GTD: {"fetched_at": NOW, "states": states}}
    for c in (cert_a, cert_b):
        v = fl.evaluate(c.jws, [net.root], expect_trust_domain=FTD, root_jws=net.root, genesis_td=GTD,
                        lists=lists, now_ts=int(dt.datetime.now(dt.timezone.utc).timestamp()))
        assert v.state in fl.REFUSED_STATES, (c.plan, v.state, v.reason)


def test_1_the_list_states_map_explicitly_and_nothing_unknown_passes(net):
    h = fl.licence_hash(net.frame)
    assert _eval(net, lists=_lists((h, "expired"))).state == "expired"
    assert _eval(net, lists=_lists((h, "superseded"))).state == "revoked"
    v = _eval(net, lists=_lists((h, "weird")))
    assert v.state == "unverified" and not v.passes


def test_2_an_unverified_card_signature_does_not_hide_a_revoked_licence(net, monkeypatch):
    monkeypatch.setenv("FEDERATION_GENESIS_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "observe")
    rows = [_Row(hash=fl.licence_hash(net.root), role="root", jws=net.root, chain=[], type="genesis", state="active",
                 sub_trust_domain=GTD, sub_name="EU", iss_trust_domain=GTD, expires_at=None)]
    _store_for(monkeypatch, rows)
    revoked = _Row(hash=fl.licence_hash(net.frame), role="issued", jws=net.frame, chain=[], type="frame",
                   state="revoked", sub_trust_domain=FTD, sub_name="ASIA", iss_trust_domain=GTD, expires_at=None)
    rows.append(revoked)
    card = {"federation": {"licence": {"certificate": net.frame, "chain": [net.root], "hash": fl.licence_hash(net.frame)}}}
    peer = _peer("asia", FTD, card=card, verified=False)

    async def no_fetch(p, path):  # pragma: no cover — the genesis reads its own list
        return 404, None

    asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[peer], fetch_json=no_fetch))
    assert peer.licence_state == "revoked" and "card signature" in peer.licence_reason


def test_3_two_frame_rows_for_one_trust_domain_read_the_most_restrictive_verdict(trust):
    td = "twice.example.org"
    for rows in ([("frame", "ACTIVE", td, "licensed"), ("frame", "ACTIVE", td, "revoked")],
                 [("frame", "ACTIVE", td, "revoked"), ("frame", "ACTIVE", td, "licensed")]):
        assert trust.licence_states_from_peer_rows(rows)[td] == "revoked"
    for rows in ([("frame", "ACTIVE", td, "unverified"), ("frame", "ACTIVE", td, "licensed")],
                 [("frame", "ACTIVE", td, "licensed"), ("frame", "ACTIVE", td, "unverified")]):
        assert trust.licence_states_from_peer_rows(rows)[td] == "licensed"


def test_4_a_signed_hash_that_does_not_match_the_certificate_is_invalid(net, monkeypatch):
    monkeypatch.setenv("FEDERATION_GENESIS_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "observe")
    rows = [_Row(hash=fl.licence_hash(net.root), role="root", jws=net.root, chain=[], type="genesis", state="active",
                 sub_trust_domain=GTD, sub_name="EU", iss_trust_domain=GTD, expires_at=None),
            _Row(hash=fl.licence_hash(net.frame), role="issued", jws=net.frame, chain=[], type="frame", state="active",
                 sub_trust_domain=FTD, sub_name="ASIA", iss_trust_domain=GTD, expires_at=None)]
    _store_for(monkeypatch, rows)
    card = {"federation": {"licence": {"certificate": net.frame, "chain": [net.root], "hash": "0" * 64}}}
    peer = _peer("asia", FTD, card=card, verified=True)

    async def no_fetch(p, path):  # pragma: no cover
        return 404, None

    asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[peer], fetch_json=no_fetch))
    assert peer.licence_state == "invalid" and "hash" in peer.licence_reason


def test_a_long_licence_list_still_verifies_and_an_oversized_one_says_too_long(net):
    # agentvault2-41, measured: the list inherited the certificate cap (16384) and stopped verifying at 39 licences, so
    # revocation failed open across the network from then on
    items = [{"hash": ("%064x" % i), "lid": "00000000-0000-4000-8000-%012d" % i, "type": "frame",
              "sub_trust_domain": f"frame-{i}.example.org", "sub_name": f"Frame {i}", "plan": "research",
              "iat": NOW, "exp": None, "state": "active", "updated_at": NOW} for i in range(1000)]
    payload = {"kind": fl.LIST_KIND, "issuer": {"trust_domain": GTD, "name": "EU", "kid": net.gkid},
               "generated_at": NOW, "licences": items}
    jws = fl.sign_jws(payload, net.gpriv, kid=net.gkid, typ=fl.LIST_TYP)
    assert len(jws) > 16384
    got, why = fl.verify_list(jws, net.gjwk, issuer_td=GTD)
    assert got is not None and len(fl.list_states(got)) == 1000, why
    with pytest.raises(ValueError, match="too long"):
        fl.parse_jws("a" * 20000 + ".b.c")          # a certificate-sized parse names the size, not "malformed"


def test_the_worker_reads_the_licence_over_paths_the_federation_proxy_serves():
    # a frame's nginx-federation serves /api/v1/federation/ and three named well-known files only (measured in the
    # frame template, 2026-09-28): a /.well-known/federation-licence(s).json read over that lane would 404
    assert fl.FED_OWN_PATH.startswith("/api/v1/federation/") and fl.FED_LIST_PATH.startswith("/api/v1/federation/")
    from agentvault_registry.routers.federation_licence import router
    paths = {r.path for r in router.routes}
    assert {fl.FED_OWN_PATH, fl.FED_LIST_PATH, "/.well-known/federation-licence.json",
            "/.well-known/federation-licences.json"} <= paths


def test_the_licence_fetch_dials_the_authenticated_lane_first(monkeypatch):
    # measured on V0478: the card pull's rewrite (_to_registry_dialable_url) put both sandbox operators' asks for their
    # licence on the parent's public console, where no client certificate reaches the registry: 401 every cycle
    from agentvault_registry.background_tasks import federation_sync as fs
    from agentvault_registry.routers import teg_integration as ti
    seen = []

    async def fake_get(url):
        seen.append(url)
        return (0, {"error": "unreachable"}) if len(seen) == 1 else (200, {"ok": True})

    monkeypatch.setattr(fs, "_peer_get_json", fake_get)
    monkeypatch.setattr(ti, "_to_internal_mtls_url", lambda u: u + "#mtls")
    monkeypatch.setattr(ti, "_to_registry_dialable_url", lambda u: u + "#card")
    peer = types.SimpleNamespace(base_url="https://parent.example.org:8443/")
    st, _ = asyncio.run(fs.peer_fetch_json(peer, "/api/v1/federation/licence/mine"))
    assert seen == ["https://parent.example.org:8443#mtls/api/v1/federation/licence/mine",
                    "https://parent.example.org:8443#card/api/v1/federation/licence/mine"] and st == 200
    seen.clear()

    async def answers_401(url):
        seen.append(url)
        return 401, {"detail": "no identity"}

    monkeypatch.setattr(fs, "_peer_get_json", answers_401)
    st, _ = asyncio.run(fs.peer_fetch_json(peer, "/x"))
    assert st == 401 and len(seen) == 1  # an ANSWER from the mTLS lane is final; only "no request made" falls back


# --- the report resolves a trust domain the way the crossing check does (the V0478 sandbox proof) -------------------

def _genesis_view(net, monkeypatch, mode="observe", extra_issued=()):
    """A cycle run on the genesis itself (it reads its own list), with `net.frame` issued and active."""
    monkeypatch.setenv("FEDERATION_GENESIS_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", GTD)
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", mode)
    monkeypatch.delenv("FEDERATION_GENESIS_CERT_HASH", raising=False)
    rows = [_Row(hash=fl.licence_hash(net.root), role="root", jws=net.root, chain=[], type="genesis", state="active",
                 sub_trust_domain=GTD, sub_name="EU", iss_trust_domain=GTD, expires_at=None),
            _Row(hash=fl.licence_hash(net.frame), role="issued", jws=net.frame, chain=[], type="frame", state="active",
                 sub_trust_domain=FTD, sub_name="ASIA", iss_trust_domain=GTD, expires_at=None)]
    rows.extend(extra_issued)
    _store_for(monkeypatch, rows)
    return rows


def _card_with(cert, root):
    return {"federation": {"licence": {"certificate": cert, "chain": [root], "hash": fl.licence_hash(cert)}}}


async def _no_fetch(p, path):  # pragma: no cover — the genesis reads its own list
    return 404, None


def _as_the_crossing_check_resolves(peers):
    from agentvault_registry.core import mtls_auth as m
    return m.licence_states_from_peer_rows([(p.peer_type, "ACTIVE", p.trust_domain, p.licence_state) for p in peers])


@pytest.mark.parametrize("mode", ["observe", "enforce"])
def test_5_an_operator_without_its_own_licence_rides_its_frame_and_is_not_named_refused(net, monkeypatch, mode):
    # measured on V0478: sbx-alpha read sbxbetaop `unlicensed` and named it in would_refuse, while the crossing check
    # resolved sandbox-b from its frame row (licensed) and allowed every crossing
    _genesis_view(net, monkeypatch, mode=mode)
    frame = _peer("asia", FTD, card=_card_with(net.frame, net.root))
    op = _peer("shenzhen", FTD, card={"federation": {}}, peer_type="discovered")
    summary = asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[frame, op], fetch_json=_no_fetch))
    assert frame.licence_state == "licensed"
    assert op.licence_state == "licensed" and "rides its frame asia" in op.licence_reason
    assert op.licence_hash == frame.licence_hash
    assert summary["would_refuse" if mode == "observe" else "refused"] == []
    assert summary["domains"] == {FTD: "licensed"} == _as_the_crossing_check_resolves([frame, op])


def test_5_an_operator_whose_domain_has_no_frame_row_here_is_still_judged_alone(net, monkeypatch):
    _genesis_view(net, monkeypatch)
    lone = _peer("lone-op", OTHER, card={"federation": {}}, peer_type="discovered")
    summary = asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[lone], fetch_json=_no_fetch))
    assert lone.licence_state == "unlicensed"
    assert summary["would_refuse"] == ["lone-op"] and summary["domains"] == {OTHER: "unlicensed"}


def test_5_a_stale_operator_card_keeps_its_own_verdict_but_does_not_refuse_its_licensed_frame(net, monkeypatch):
    # an operator's cached card still carries the frame's PREVIOUS licence (superseded at a reissue); the frame row
    # carries the live one. The row says what its card shows; the trust domain, as the crossing check resolves it, is
    # licensed, so nothing is named refused.
    older = _frame(net.gpriv, net.gkid, fl.licence_hash(net.root), net.fjwk, iat=NOW - 900)
    superseded = _Row(hash=fl.licence_hash(older), role="issued", jws=older, chain=[], type="frame", state="superseded",
                      sub_trust_domain=FTD, sub_name="ASIA", iss_trust_domain=GTD, expires_at=None)
    _genesis_view(net, monkeypatch, extra_issued=[superseded])
    frame = _peer("asia", FTD, card=_card_with(net.frame, net.root))
    stale = _peer("hochiminh", FTD, card=_card_with(older, net.root), peer_type="discovered")
    summary = asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[frame, stale], fetch_json=_no_fetch))
    assert frame.licence_state == "licensed" and stale.licence_state == "revoked"
    assert summary["would_refuse"] == [] and summary["domains"] == {FTD: "licensed"}
    # control: the frame itself refused names every row of its domain, the operator's included
    frame2 = _peer("asia", FTD, card={"federation": {"licence": {"state": "unlicensed"}}})
    op2 = _peer("shenzhen", FTD, card={"federation": {}}, peer_type="discovered")
    summary2 = asyncio.run(fl.refresh_frame_cycle(_DB(), peers=[frame2, op2], fetch_json=_no_fetch))
    assert frame2.licence_state == "unlicensed" and op2.licence_state == "unlicensed"
    assert summary2["would_refuse"] == ["asia", "shenzhen"]


def test_one_category_list_educational_is_perpetual_and_government_takes_the_enterprise_year(net):
    # his words 2026-09-28: "free license for educational, research and non profits. but enterprise and goverment orgs will
    # not have the same privilige" -- the form, the site and the legal text name this same list
    assert all(fl.NETWORK_PLANS[p] is None for p in ("private", "educational", "research", "non-profit"))
    assert fl.NETWORK_PLANS["enterprise"] == fl.NETWORK_PLANS["government"] == 365
    gov = _frame(net.gpriv, net.gkid, fl.licence_hash(net.root), net.fjwk, plan="government", days=365)
    edu = _frame(net.gpriv, net.gkid, fl.licence_hash(net.root), net.fjwk, plan="educational")
    g, e = fl.load_cert(gov), fl.load_cert(edu)
    assert g.plan == "government" and g.exp and g.exp - g.iat == 365 * 86400
    assert e.plan == "educational" and not e.exp


def test_the_frame_request_form_asks_the_category_list_the_licence_issues():
    """His words 2026-09-28 (the frame-commander form): the form's categories are NETWORK_PLANS without the network's
    own two plans, so a request always names a plan a frame licence can be issued under."""
    from typing import get_args

    import pydantic
    from agentvault_registry.routers.operator_self_service import FrameAnswersNetwork
    from agentvault_registry.services.federation_licence import NETWORK_PLANS

    ann = FrameAnswersNetwork.model_fields["licence_category"].annotation
    asked = {v for arg in get_args(ann) for v in get_args(arg)}
    assert asked == set(NETWORK_PLANS) - {"genesis", "founding"}
    assert FrameAnswersNetwork(licence_category="educational").licence_category == "educational"
    # control: the network's own plans and a made-up word are refused, never stored
    for word in ("founding", "genesis", "startup"):
        with pytest.raises(pydantic.ValidationError):
            FrameAnswersNetwork(licence_category=word)


# ── the legacy licence lane honours the network licence (found preparing the kit dry run, 2026-09-28) ─────────────────
# get_federation_identity's Mode 1 swallows the mTLS lane's licence refusal (a 403) and falls through to Mode 3, and
# federation_sync sends X-Federation-License beside its client certificate: a revoked frame kept every crossing.

def _verdicts(monkeypatch, mode, states):
    from agentvault_registry.core import mtls_auth
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", mode)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.example")
    monkeypatch.setattr(mtls_auth, "_LICENCE_STATE_BY_TD", dict(states))


def test_a_frame_key_is_refused_with_its_frames_refused_licence(monkeypatch):
    from agentvault_registry.core.federation_auth import frame_licence_refusal
    _verdicts(monkeypatch, "enforce", {"kit.example": "revoked", "ok.example": "licensed"})
    assert "federation licence required: kit.example" in (frame_licence_refusal("spiffe://kit.example") or "")
    # controls: a licensed frame, this frame's own domain, a DID that names no trust domain, observe mode
    assert frame_licence_refusal("spiffe://ok.example") is None
    assert frame_licence_refusal("spiffe://sandbox-a.example") is None
    assert frame_licence_refusal("did:theprotocol:op-1") is None
    _verdicts(monkeypatch, "observe", {"kit.example": "revoked"})
    assert frame_licence_refusal("spiffe://kit.example") is None


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self.row, self.commits = row, 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        return _FakeResult(self.row)

    async def commit(self):
        self.commits += 1


def _licence_row(licensee_type, did):
    return types.SimpleNamespace(licensee_type=licensee_type, operator_did=did, operator_name="kit",
                                 last_seen_at=None, event_count=0)


@pytest.mark.asyncio
async def test_the_legacy_lane_refuses_a_frame_whose_network_licence_is_revoked(monkeypatch):
    from fastapi import HTTPException
    from agentvault_registry import database
    from agentvault_registry.core import federation_auth, mtls_auth

    async def _no_refresh(**_kw):
        return frozenset()

    monkeypatch.setattr(mtls_auth, "refresh_peer_trust_domains", _no_refresh)
    _verdicts(monkeypatch, "enforce", {"kit.example": "revoked"})
    frame = _FakeSession(_licence_row("frame", "spiffe://kit.example"))
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: frame)
    with pytest.raises(HTTPException) as exc:
        await federation_auth._verify_license_key("tp_fed_x", None)
    assert exc.value.status_code == 403 and "kit.example" in str(exc.value.detail)
    assert frame.commits == 0   # a refused call is not counted as seen
    # control: an operator's key (a login to its own parent) is not a crossing and still authenticates
    op = _FakeSession(_licence_row("operator", "spiffe://kit.example"))
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: op)
    assert (await federation_auth._verify_license_key("tp_fed_y", None)).startswith("spiffe://theprotocol.cloud/")
    # control: the same frame key authenticates once the frame is licensed again
    _verdicts(monkeypatch, "enforce", {"kit.example": "licensed"})
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSession(_licence_row("frame", "spiffe://kit.example")))
    assert (await federation_auth._verify_license_key("tp_fed_x", None)).startswith("spiffe://theprotocol.cloud/")
