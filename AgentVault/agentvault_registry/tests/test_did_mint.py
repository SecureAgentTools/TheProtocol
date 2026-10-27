"""§DIDWIDEN (2026-09-06) — fresh agent DIDs are a full uuid4; old DIDs stay valid.

What this pins, with a control each way:
  * the ONE generator (identifiers.generate_agent_did) mints did:<method>:<uuid4>
    (122 random bits, 52 chars under did:theprotocol:) and refuses an unknown method;
  * the legacy 8-4-4-4 shape every DID minted before this date carries is still
    classified as a valid agent DID (nothing in the tree may reject it);
  * mint_unique_agent_did re-mints when the candidate is held by agents.did OR by a
    MIRRORED agent_cards.agent_did (the cross-frame case), counts it, and refuses
    after max_attempts; a free candidate is returned untouched and uncounted;
  * federation_sync classifies the agent_did unique-index rollback as did_conflict
    and everything else as other; the envelope's DID is read from either place;
  * no file in the package builds a RANDOM agent DID by hand any more.

Run (in the image, from /w): python -m pytest tests/test_did_mint.py -q -o asyncio_mode=auto
"""
from __future__ import annotations

import pathlib
import re
import uuid

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import IntegrityError

from agentvault_registry import identifiers
from agentvault_registry.routers import onboarding
from agentvault_registry.background_tasks import federation_sync as fs


UUID4_FULL = re.compile(r"^did:(theprotocol|cos):[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
LIVE_LEGACY = "did:theprotocol:65f488a8-1d2e-3f40-5a6b"       # the 39-char shape on every node today
LIVE_LEGACY_COS = "did:cos:453d4a48-9c0b-1a2b-3c4d"            # the legacy method, same suffix shape


# ─── the generator ────────────────────────────────────────────────────────────

def test_fresh_did_is_a_full_uuid4_under_both_methods():
    for method, length in (("theprotocol", 52), ("cos", 44)):
        did = identifiers.generate_agent_did(method)
        assert UUID4_FULL.match(did), did
        assert len(did) == length, (did, len(did))
        assert uuid.UUID(did.rsplit(":", 1)[-1]).version == 4


def test_generator_refuses_an_unknown_method_with_the_message_the_400_depends_on():
    with pytest.raises(ValueError) as ei:
        identifiers.generate_agent_did("web")
    assert "Unsupported DID method: web" in str(ei.value)


def test_a_thousand_mints_are_distinct():
    assert len({identifiers.generate_agent_did("theprotocol") for _ in range(1000)}) == 1000


def test_onboarding_exports_the_same_generator_object():
    # ONE rule: routers import the name from onboarding, onboarding imports it from identifiers
    assert onboarding.generate_agent_did is identifiers.generate_agent_did


def test_legacy_and_uuid4_shapes_are_both_recognised():
    assert identifiers.agent_did_suffix_shape(LIVE_LEGACY) == "legacy"
    assert identifiers.agent_did_suffix_shape(LIVE_LEGACY_COS) == "legacy"
    assert identifiers.agent_did_suffix_shape(identifiers.generate_agent_did()) == "uuid4"
    # deterministic system DIDs are neither — and must not be mistaken for a mint
    assert identifiers.agent_did_suffix_shape("did:theprotocol:operator:op-berlin") == "other"
    assert identifiers.agent_did_suffix_shape("did:theprotocol:agora-gateway-avt") == "other"
    assert identifiers.agent_did_suffix_shape("") == "other"


# ─── the mint-time net ────────────────────────────────────────────────────────

class _Res:
    def __init__(self, hit: bool):
        self._hit = hit

    def first(self):
        return (1,) if self._hit else None


class _FakeDB:
    """Answers SELECTs by (table, did) membership and records what was asked."""

    def __init__(self, taken):
        self.taken = set(taken)
        self.asked = []

    async def execute(self, stmt):
        from sqlalchemy.sql import visitors
        from sqlalchemy.sql.elements import BindParameter
        table = stmt.column_descriptions[0]["entity"].__tablename__
        # the DID is the one bound string that looks like a DID, however many conditions the WHERE carries
        dids = [b.value for b in visitors.iterate(stmt.whereclause) if isinstance(b, BindParameter) and isinstance(b.value, str) and b.value.startswith("did:")]
        assert len(dids) == 1, dids
        did = dids[0]
        self.asked.append((table, did))
        return _Res((table, did) in self.taken)


def _remints(site: str) -> float:
    return REGISTRY.get_sample_value("registry_did_mint_remint_total", {"site": site}) or 0.0


def _seq(monkeypatch, values):
    # the net mints through generate_local_agent_did (item 1: under this registry's issuer); patch THAT name
    it = iter(values)
    monkeypatch.setattr(onboarding, "generate_local_agent_did", lambda method="theprotocol": next(it))


async def test_free_candidate_is_returned_first_time_and_not_counted(monkeypatch):
    _seq(monkeypatch, ["did:theprotocol:free-1"])
    db = _FakeDB(taken=[])
    before = _remints("t-free")
    assert await onboarding.mint_unique_agent_did(db, "theprotocol", site="t-free") == "did:theprotocol:free-1"
    assert db.asked == [("agents", "did:theprotocol:free-1"), ("agent_cards", "did:theprotocol:free-1")]
    assert _remints("t-free") == before


async def test_candidate_held_by_a_native_agent_is_re_minted_once_and_counted(monkeypatch):
    _seq(monkeypatch, ["did:theprotocol:taken-native", "did:theprotocol:free-2"])
    db = _FakeDB(taken=[("agents", "did:theprotocol:taken-native")])
    before = _remints("t-native")
    assert await onboarding.mint_unique_agent_did(db, site="t-native") == "did:theprotocol:free-2"
    assert _remints("t-native") == before + 1


async def test_candidate_held_only_by_a_mirrored_card_is_re_minted_too(monkeypatch):
    # the cross-frame case: a foreign agent's mirror occupies agent_cards.agent_did with NO agents row
    _seq(monkeypatch, ["did:theprotocol:taken-mirror", "did:theprotocol:free-3"])
    db = _FakeDB(taken=[("agent_cards", "did:theprotocol:taken-mirror")])
    before = _remints("t-mirror")
    assert await onboarding.mint_unique_agent_did(db, site="t-mirror") == "did:theprotocol:free-3"
    assert ("agent_cards", "did:theprotocol:taken-mirror") in db.asked
    assert _remints("t-mirror") == before + 1


async def test_exhausted_attempts_refuse_loudly(monkeypatch):
    _seq(monkeypatch, ["did:theprotocol:x", "did:theprotocol:x", "did:theprotocol:x"])
    db = _FakeDB(taken=[("agents", "did:theprotocol:x")])
    with pytest.raises(onboarding.DidMintCollision):
        await onboarding.mint_unique_agent_did(db, site="t-exhausted", max_attempts=3)


async def test_unknown_method_propagates_as_value_error_before_any_query():
    db = _FakeDB(taken=[])
    with pytest.raises(ValueError):
        await onboarding.mint_unique_agent_did(db, "web", site="t-method")
    assert db.asked == []


# ─── the federation-side classifier ───────────────────────────────────────────

def _integrity(msg: str) -> IntegrityError:
    return IntegrityError("INSERT INTO agent_cards ...", {}, Exception(msg))


def test_agent_did_unique_index_rollback_is_a_did_conflict():
    exc = _integrity('duplicate key value violates unique constraint "uix_agent_cards_agent_did"')
    assert fs.classify_card_skip(exc) == "did_conflict"


def test_other_integrity_errors_and_other_exceptions_stay_other():
    assert fs.classify_card_skip(_integrity('duplicate key value violates unique constraint "agent_cards_pkey"')) == "other"
    assert fs.classify_card_skip(ValueError("bad card")) == "other"


def test_incoming_card_did_reads_both_envelope_places():
    assert fs.incoming_card_did({"agent_did": "did:theprotocol:a"}) == "did:theprotocol:a"
    assert fs.incoming_card_did({"card_data": {"did": "did:theprotocol:b"}}) == "did:theprotocol:b"
    assert fs.incoming_card_did({"agent_did": "", "card_data": {"did": "did:theprotocol:c"}}) == "did:theprotocol:c"
    assert fs.incoming_card_did({"card_data": {}}) is None
    assert fs.incoming_card_did("not a dict") is None


# ─── the tree-wide gate: no hand-built RANDOM agent DIDs outside the generator ─

_HAND_BUILT = re.compile(r"did:(theprotocol|cos):\{[^}\n]*(uuid|token_hex|random|parts\[)")


def _package_root() -> pathlib.Path:
    return pathlib.Path(identifiers.__file__).resolve().parent


def test_gate_regex_catches_the_two_shapes_it_exists_for():
    # control: the gate must be RED on the exact lines this change removed
    assert _HAND_BUILT.search('new_did = f"did:theprotocol:{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"')
    assert _HAND_BUILT.search('new_did = f"did:cos:{uuid.uuid4().hex[:20]}"')
    assert _HAND_BUILT.search('return f"did:theprotocol:{did_suffix}"') is None  # a bare variable is not a mint
    # deterministic system DIDs are not mints
    assert _HAND_BUILT.search('return f"did:theprotocol:{email.replace(\'@\', \'_at_\')}"') is None
    assert _HAND_BUILT.search('f"did:theprotocol:operator:{safe_name}"') is None


def test_no_python_file_in_the_package_builds_a_random_agent_did_by_hand():
    root = _package_root()
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "identifiers.py" or "/tests/" in str(path) or "node_modules" in str(path):
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if _HAND_BUILT.search(line):
                offenders.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


def test_the_three_registry_mint_sites_use_the_net():
    root = _package_root()
    for rel, site in (
        ("routers/onboarding.py", 'site="create_agent"'),
        ("routers/agent_delegation_api.py", 'site="spawn"'),
        ("routers/fiat_onramp.py", 'site="fiat_onramp"'),
    ):
        text = (root / rel).read_text()
        assert "await mint_unique_agent_did(db" in text and site in text, rel


# ═══ item 1 (his approval 2026-09-06): the issuer segment + the guard ═══════════════════════════

ISSUER = "eu.theprotocol.cloud"
NAMESPACED = re.compile(r"^did:theprotocol:eu\.theprotocol\.cloud:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_namespaced_mint_and_parse():
    did = identifiers.generate_agent_did("theprotocol", issuer=ISSUER)
    assert NAMESPACED.match(did), did
    assert len(did) == 16 + len(ISSUER) + 1 + 36
    assert identifiers.agent_did_issuer(did) == ISSUER
    assert identifiers.agent_did_suffix_shape(did) == "namespaced"
    method, issuer, rest = identifiers.agent_did_parts(did)
    assert (method, issuer) == ("theprotocol", ISSUER) and uuid.UUID(rest).version == 4


def test_reserved_second_segments_are_never_an_issuer():
    # the deterministic system DIDs already have three segments; they must not parse as namespaced
    for did in ("did:theprotocol:operator:op-berlin", "did:theprotocol:cloud:amsterdam", "did:theprotocol:org-acme-treasury"):
        assert identifiers.agent_did_issuer(did) is None, did
        assert identifiers.agent_did_suffix_shape(did) == "other"
    with pytest.raises(ValueError):
        identifiers.generate_agent_did("theprotocol", issuer="operator")
    with pytest.raises(ValueError):
        identifiers.generate_agent_did("theprotocol", issuer="EU.Theprotocol.cloud")  # not lowercase


def test_two_and_three_segment_shapes_and_legacy_stay_valid_to_every_validator():
    from agentvault_registry.input_validators import DID_PATTERN, validate_did
    from agentvault_registry.routers.mcp_tester import _DID_RE
    good = [LIVE_LEGACY, identifiers.generate_agent_did(), identifiers.generate_agent_did(issuer=ISSUER),
            "did:theprotocol:teg_system_treasury", "did:cos:abc123"]
    for d in good:
        assert DID_PATTERN.match(d), d
        assert validate_did(d) == d
        assert identifiers.AGENT_DID_PATTERN.match(d), d
    for d in (identifiers.generate_agent_did(), identifiers.generate_agent_did(issuer=ISSUER), LIVE_LEGACY):
        assert _DID_RE.search(d), d
    # controls: the validators still refuse garbage
    for bad in ("did:theprotocol:", "did:web:x", "did:theprotocol:-bad:x", "theprotocol:abc", "did:theprotocol:a"):
        assert not DID_PATTERN.match(bad), bad


def test_spiffe_sanitize_round_trips_all_three_shapes():
    from agentvault_registry.services.agent_spire import sanitize_did_for_spiffe, unsanitize_did
    for d in (LIVE_LEGACY, identifiers.generate_agent_did(), identifiers.generate_agent_did(issuer=ISSUER),
              "did:theprotocol:teg_system_treasury"):
        san = sanitize_did_for_spiffe(d)
        assert ":" not in san
        assert unsanitize_did(san) == d, (d, san, unsanitize_did(san))


def test_registry_issuer_reads_env_and_refuses_a_bad_value(monkeypatch):
    monkeypatch.delenv(identifiers.DID_ISSUER_ENV, raising=False)
    assert identifiers.registry_issuer() is None
    assert identifiers.agent_did_issuer(identifiers.generate_local_agent_did()) is None
    monkeypatch.setenv(identifiers.DID_ISSUER_ENV, ISSUER)
    assert identifiers.registry_issuer() == ISSUER
    assert identifiers.agent_did_issuer(identifiers.generate_local_agent_did()) == ISSUER
    monkeypatch.setenv(identifiers.DID_ISSUER_ENV, "operator")
    with pytest.raises(ValueError):
        identifiers.registry_issuer()


def test_boot_check_g2_both_ways(monkeypatch):
    monkeypatch.delenv(identifiers.DID_ISSUER_ENV, raising=False)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", ISSUER)
    assert identifiers.assert_issuer_posture() is None                      # unset = byte-inert
    monkeypatch.setenv(identifiers.DID_ISSUER_ENV, ISSUER)
    assert identifiers.assert_issuer_posture() == ISSUER                    # equal = boots
    monkeypatch.setenv(identifiers.DID_ISSUER_ENV, "asia.theprotocol.cloud")
    with pytest.raises(RuntimeError):                                       # a namespace that is not ours = refuses
        identifiers.assert_issuer_posture()


def test_card_namespace_guard_g4_both_ways(monkeypatch):
    from agentvault_registry.services.registry_card_validator import check_card_namespace
    monkeypatch.setenv("DID_ISSUER_NAMESPACE", "asia.theprotocol.cloud"); monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "asia.theprotocol.cloud")
    ok = {"identity": {"trust_domain": ISSUER, "did_namespace": ISSUER}}
    assert check_card_namespace(ok, peer_trust_domain=ISSUER) is None
    assert check_card_namespace({"identity": {"trust_domain": ISSUER}}) is None            # no claim = nothing to check
    assert check_card_namespace({"identity": {"trust_domain": ISSUER, "did_namespace": "frame-x.example"}}) == "did_namespace_mismatch"
    assert check_card_namespace(ok, peer_trust_domain="other.example") == "did_namespace_mismatch"   # not the SVID-proven domain
    assert check_card_namespace({"identity": {"trust_domain": "asia.theprotocol.cloud", "did_namespace": "asia.theprotocol.cloud"}}) == "did_namespace_self"
    assert check_card_namespace({"identity": {"trust_domain": ISSUER, "did_namespace": "Operator"}}) == "did_namespace_invalid"


def test_validate_and_normalize_refuses_a_foreign_claim_and_keeps_a_clean_card(monkeypatch):
    # isolates the WIRING: the payload and sovereign checks are stubbed green, so the namespace decision alone decides
    from agentvault_registry.services import registry_card_validator as v
    monkeypatch.setattr(v, "validate_payload", lambda card, n: None)
    monkeypatch.setattr(v, "verify_sovereign_variant_claim", lambda card, svid: True)
    monkeypatch.setenv("DID_ISSUER_NAMESPACE", "asia.theprotocol.cloud"); monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "asia.theprotocol.cloud")
    base = {"identity": {"spiffe_id": f"spiffe://{ISSUER}/registry/EU", "registry_name": "EU", "trust_domain": ISSUER, "tier": "sovereign-mainframe"}}
    clean = {**base, "identity": {**base["identity"], "did_namespace": ISSUER}}
    assert v.validate_and_normalize(clean, 500, peer_svid="spiffe://eu.theprotocol.cloud/registry/EU", peer_trust_domain=ISSUER) is not None
    stolen = {**base, "identity": {**base["identity"], "did_namespace": "asia.theprotocol.cloud"}}
    assert v.validate_and_normalize(stolen, 500, peer_svid="spiffe://eu.theprotocol.cloud/registry/EU", peer_trust_domain=ISSUER) is None


def test_card_builder_emits_the_namespace_only_when_set(monkeypatch):
    from agentvault_registry.services import registry_card_builder as b
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", ISSUER)
    monkeypatch.delenv("DID_ISSUER_NAMESPACE", raising=False)
    assert "did_namespace" not in b._build_identity_block({})
    monkeypatch.setenv("DID_ISSUER_NAMESPACE", ISSUER)
    ident = b._build_identity_block({})
    assert ident["did_namespace"] == ISSUER and ident["trust_domain"] == ISSUER
    assert "did_namespace" in b._id_subset(ident)   # part of the ETag basis: peers re-pull when it appears


def test_invitation_guard_g3_both_ways(monkeypatch):
    from fastapi import HTTPException
    from agentvault_registry.routers.frame_invitations import _refuse_bad_namespace
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", ISSUER)
    _refuse_bad_namespace("asia.theprotocol.cloud", site="t")                 # a distinct, valid partner passes
    for bad, code in ((ISSUER, "did_namespace_taken"), ("operator", "did_namespace_invalid"), ("Bad Domain", "did_namespace_invalid")):
        with pytest.raises(HTTPException) as ei:
            _refuse_bad_namespace(bad, site="t")
        assert ei.value.status_code == 409 and str(ei.value.detail).startswith(code), bad


def test_provisioner_hands_the_namespace_to_operators():
    from agentvault_registry.services.cloud_provisioner import PARENT_POSTURE_KEYS
    assert "DID_ISSUER_NAMESPACE" in PARENT_POSTURE_KEYS


def test_g5_compares_the_issuer_with_the_origin_not_the_presenter():
    from agentvault_registry.crud.crud_peer_registry import did_issuer_vs_origin
    ns_did = f"did:theprotocol:{ISSUER}:{uuid.uuid4()}"
    relayed = {"card_data": {"did": ns_did, "federation_metadata": {"source_registry": f"spiffe://{ISSUER}/service/registry"}}}
    # an honest relay: an ASIA operator presents an EU-born card; the origin is EU ⇒ no mismatch
    assert did_issuer_vs_origin(relayed, "asia.theprotocol.cloud") == (ISSUER, ISSUER, ns_did)
    # a direct push from the origin (no metadata yet): the presenter IS the origin
    assert did_issuer_vs_origin({"card_data": {"did": ns_did}}, ISSUER) == (ISSUER, ISSUER, ns_did)
    # the class G5 exists for: a card whose issuer is not its origin
    forged = {"card_data": {"did": ns_did, "federation_metadata": {"source_registry": "spiffe://rogue.example/service/registry"}}}
    assert did_issuer_vs_origin(forged, "rogue.example") == (ISSUER, "rogue.example", ns_did)
    # a legacy / two-segment DID has no issuer ⇒ nothing to compare
    assert did_issuer_vs_origin({"card_data": {"did": LIVE_LEGACY}}, ISSUER)[0] is None


# ═══ the closer eb's measurement asked for: a dispute against a DID nobody knows is refused ═══════

async def test_dispute_defendant_must_be_a_known_agent_or_mirror():
    from agentvault_registry.routers import disputes as d
    known_native = _FakeDB(taken=[("agents", "did:theprotocol:native-1")])
    assert await d.defendant_known(known_native, "did:theprotocol:native-1") is True
    known_mirror = _FakeDB(taken=[("agent_cards", "did:theprotocol:mirror-1")])
    assert await d.defendant_known(known_mirror, "did:theprotocol:mirror-1") is True
    assert ("agent_cards", "did:theprotocol:mirror-1") in known_mirror.asked      # it asked the mirror table
    nobody = _FakeDB(taken=[])
    assert await d.defendant_known(nobody, "did:theprotocol:fabricated") is False
    assert [t for t, _ in nobody.asked] == ["agents", "agent_cards"]               # both tables, in that order


def test_create_dispute_refuses_before_writing_the_row():
    import inspect
    from agentvault_registry.routers import disputes as d
    src = inspect.getsource(d.create_dispute)
    assert src.index("defendant_known(db, dispute_data.defendant_did)") < src.index("crud_disputes.create_dispute(")
    assert "is not known to this registry: no agent row and no mirrored card" in src


def test_presenter_svid_comes_from_the_peer_row_and_the_flare_check_still_matches():
    from types import SimpleNamespace as NS
    from agentvault_registry.background_tasks.federation_sync import presenter_svid_for
    from agentvault_registry.services.spiffe_canonical import canonical_equals
    eu_op = NS(name="amsterdam", trust_domain="eu.theprotocol.cloud")
    assert presenter_svid_for(eu_op) == "spiffe://eu.theprotocol.cloud/registry/amsterdam"
    legacy_row = NS(name="Op Berlin", trust_domain=None)
    assert presenter_svid_for(legacy_row) == "spiffe://agentvault.com/ns/agentvault/sa/registry-op-berlin"
    spaced = NS(name="Sandbox Alpha", trust_domain="sandbox-a.theprotocol.cloud")
    assert presenter_svid_for(spaced) == "spiffe://sandbox-a.theprotocol.cloud/registry/sandbox-alpha"   # no space in a SPIFFE path
    # the flare-origin check compares canonical NAMES, so a flare stamped under either form of the same registry is accepted
    assert canonical_equals("spiffe://agentvault.com/ns/agentvault/sa/registry-amsterdam", presenter_svid_for(eu_op))
    assert not canonical_equals("spiffe://asia.theprotocol.cloud/registry/shenzhen", presenter_svid_for(eu_op))


def test_teg_dispute_log_refuses_an_unknown_defendant_before_forwarding():
    import inspect
    from agentvault_registry.routers import teg_integration as ti
    src = inspect.getsource(ti.log_dispute)
    assert src.index("_defendant_known(db, request.defendant_agent_did)") < src.index("get_teg_token_for_agent(")
    assert "is not known to this registry: no agent row and no mirrored card" in src


def test_the_namespace_claim_is_in_the_signed_set():
    from agentvault_registry.services.registry_card_signer import SIGNED_CANONICAL_PATHS
    assert "identity.did_namespace" in SIGNED_CANONICAL_PATHS
    assert "identity.trust_domain" in SIGNED_CANONICAL_PATHS      # the two halves of the guard are both signed
