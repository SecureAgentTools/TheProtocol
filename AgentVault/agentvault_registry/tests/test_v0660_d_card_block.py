"""V0660 (d): the registry card and the public registry-config carry a derived `quantum_workloads` block.

The block says whether this frame hosts quantum workloads (status shadow or on) and what a job settled here gets: the job
receipt format, the acceptance tests a verdict can settle through (the Guild's verify step, a contract milestone, each
only where its own switch is on), the metering circuit the attestation rail verifies, and a summary of the frame's
allocation profile when it declares one. It is read from the registry's own switches on every build, never from an
operator's card edit, and the card signs it as a whole block.

While QUANTUM_WORKLOADS_MODE is off (the source default) nothing changes: no block on the card or in the registry-config,
the same entity tag, the same signed path list. The signature and the tag cover the block only when it is there.

RED on 4b79322d7 (origin/v0658/cut): no card or registry-config carries the block, the tag and the signed paths ignore
the switch, the receiver accepts any block, and the schema refuses one (it allows no unknown top-level key). The tests
named "off" are the byte-inert guard: they pass on the base and must keep passing.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import pathlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jsonschema import Draft202012Validator, FormatChecker

from agentvault_registry.crud import crud_enforcement
from agentvault_registry.routers import registry_card as rc
from agentvault_registry.services import jurisdiction
from agentvault_registry.services import registry_card_builder as rcb
from agentvault_registry.services import registry_card_signer as signer
from agentvault_registry.services import registry_card_validator as validator
from agentvault_registry.services import regulatory_auth

SRC = pathlib.Path(rc.__file__).resolve().parents[1]
PUBLISHED = SRC / "static" / "new_registry_frontend" / "src" / "assets" / "docs" / "specs" / "registry-card-v0.6.schema.json"

_SWITCHES = ("QUANTUM_WORKLOADS_MODE", "QUANTUM_ALLOCATION_PROFILE", "GUILD_ENABLED", "CONTRACTS_V2_ENABLED",
             "ZKP_ACCEPT_V1_CIRCUITS", "FRAME_CURRENCY")
_PROFILE = {"name": "Example consortium, 2026 call", "version": 2, "unit": "QPU",
            "allocations": [{"id": "proj-017", "holder": "did:theprotocol:eu.example:0b0e7c1a-5a0e-4c39-9d43-1f0d6d2b7c01",
                             "cap": "5000"},
                            {"id": "proj-018", "holder": "did:theprotocol:eu.example:6c1f0e0a-1f2b-4a55-8c3d-2a9e4d1b0f02",
                             "cap": 1200}]}


class _Rows:
    def scalar_one_or_none(self):
        return None

    def scalar(self):
        return 0

    def all(self):
        return []

    def first(self):
        return None

    def scalars(self):
        return self


class _Db:
    async def execute(self, *_a, **_k):
        return _Rows()


@pytest.fixture(autouse=True)
def _quiet_card(monkeypatch):
    async def _empty(*_a, **_k):
        return {}

    async def _none(*_a, **_k):
        return None

    async def _no_auths(db):
        return []

    monkeypatch.setattr(rcb, "_fetch_supply_audit", _empty)
    monkeypatch.setattr(rcb, "_fetch_fee_config", _empty)
    monkeypatch.setattr(rcb, "_build_stats_block", _empty)
    monkeypatch.setattr(rcb, "_FOUNDED_AT_CACHE", None)
    monkeypatch.setattr(crud_enforcement, "get_active_policy", _none)
    monkeypatch.setattr(jurisdiction, "get_profile", _none)
    monkeypatch.setattr(regulatory_auth, "active_card_authorizations", _no_auths)
    for k in ("EXCHANGE_ENABLED", "EXCHANGE_SOLVENCY_CARD_ENABLED", "RC_PUBLISH_PEER_ROSTER", "SPIRE_BUNDLE_ENDPOINT",
              *_SWITCHES):
        monkeypatch.delenv(k, raising=False)
    persona = rcb.operator_persona
    monkeypatch.setattr(rcb, "operator_persona", lambda stored, admin: {**persona(stored, admin),
                                                                        "display_name": "Example Frame"})


async def _card(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    card = json.loads(json.dumps(await rcb.build_registry_card(_Db(), sign=False), default=str))   # as served
    for k in env:
        monkeypatch.delenv(k, raising=False)
    return card


def _without_clock(card):
    out = copy.deepcopy(card)
    out["lifecycle"].pop("served_at", None)
    out["lifecycle"].pop("next_card_refresh", None)
    return out


# ── off: nothing changes ──────────────────────────────────────────────────────────────────────────────────────────────

async def test_off_publishes_no_block_and_the_same_card_as_an_unset_switch(monkeypatch):
    unset = await _card(monkeypatch)
    off = await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="off")
    typo = await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="enable", QUANTUM_ALLOCATION_PROFILE=json.dumps(_PROFILE))
    assert "quantum_workloads" not in unset
    # a declared allocation profile publishes nothing while the switch is off (a typo reads as off)
    assert _without_clock(off) == _without_clock(unset) == _without_clock(typo)
    assert off["lifecycle"]["card_etag"] == unset["lifecycle"]["card_etag"] == typo["lifecycle"]["card_etag"]


def test_off_signs_the_same_paths_it_always_did():
    card = {"registry_card_version": "0.6", "identity": {"spiffe_id": "spiffe://x/registry/y"}}
    paths = getattr(signer, "signed_paths_for", lambda c: signer.SIGNED_CANONICAL_PATHS)(card)
    assert list(paths) == list(signer.SIGNED_CANONICAL_PATHS)
    assert len(signer.SIGNED_CANONICAL_PATHS) == 28
    assert "quantum_workloads" not in signer.extract_canonical_payload(card)


async def test_off_registry_config_is_unchanged(monkeypatch):
    unset = await _registry_config(monkeypatch)
    off = await _registry_config(monkeypatch, QUANTUM_WORKLOADS_MODE="off")
    typo = await _registry_config(monkeypatch, QUANTUM_WORKLOADS_MODE="yes")
    assert "quantum_workloads" not in unset
    assert json.dumps(unset, sort_keys=True) == json.dumps(off, sort_keys=True) == json.dumps(typo, sort_keys=True)


# ── shadow and on: the block ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["shadow", "on"])
async def test_shadow_and_on_publish_the_block_with_their_status(monkeypatch, mode):
    off = await _card(monkeypatch)
    card = await _card(monkeypatch, QUANTUM_WORKLOADS_MODE=mode)
    block = card["quantum_workloads"]
    assert block["status"] == mode
    assert set(card) - set(off) == {"quantum_workloads"}
    assert list(card)[-1] == "quantum_workloads"      # after compliance, the signature is added after it


async def test_the_block_offers_only_what_the_rails_here_run(monkeypatch):
    nothing = (await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="on"))["quantum_workloads"]
    assert nothing["acceptance_tests"] == {"rungs": [], "settled_through": []}
    guild = (await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="on", GUILD_ENABLED="true"))["quantum_workloads"]
    assert guild["acceptance_tests"] == {"rungs": [1, 2], "settled_through": ["guild_work_order"]}
    both = (await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="on", GUILD_ENABLED="true",
                        CONTRACTS_V2_ENABLED="true"))["quantum_workloads"]
    assert both["acceptance_tests"]["settled_through"] == ["guild_work_order", "contract_milestone"]
    assert both["metering_circuit"] == "accurateResourceUsagePolicy/v2.0.0"
    # V0660 (b): the algorithm is named as the agent card extension names it (services/quantum_receipts.py, the one
    # home of the receipt constants), so the card block and an agent's extension can never disagree
    assert both["receipt_schema"] == {"version": "1.0", "signature_algorithms": ["Ed25519"]}
    assert "allocation_profile" not in both            # no profile declared, no summary


async def test_the_block_summarises_a_declared_allocation_profile(monkeypatch):
    from agentvault_registry.services.quantum_workloads import profile_hash
    block = (await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="shadow", FRAME_CURRENCY="QPU",
                         QUANTUM_ALLOCATION_PROFILE=json.dumps(_PROFILE)))["quantum_workloads"]
    assert block["allocation_profile"] == {"state": "declared", "name": "Example consortium, 2026 call", "version": 2,
                                           "allocation_count": 2, "profile_hash": profile_hash(_PROFILE)}
    # holders and caps stay off the card: a long list would pass the card's size limit (validator.MAX_CARD_BYTES)
    assert "allocations" not in block["allocation_profile"]
    broken = (await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="shadow", QUANTUM_ALLOCATION_PROFILE="{not json"))
    assert broken["quantum_workloads"]["allocation_profile"] == {"state": "invalid"}


async def test_a_card_with_the_block_validates_against_what_the_route_serves(monkeypatch):
    monkeypatch.setattr(rc, "_SCHEMA_V06_BODY", None)
    schema = json.loads((await rc.get_well_known_registry_card_schema()).body)
    assert schema == json.loads(PUBLISHED.read_text(encoding="utf-8"))
    check = Draft202012Validator(schema, format_checker=FormatChecker())
    for env in ({"QUANTUM_WORKLOADS_MODE": "on", "GUILD_ENABLED": "true", "CONTRACTS_V2_ENABLED": "true"},
                {"QUANTUM_WORKLOADS_MODE": "shadow", "FRAME_CURRENCY": "QPU",
                 "QUANTUM_ALLOCATION_PROFILE": json.dumps(_PROFILE)},
                {"QUANTUM_WORKLOADS_MODE": "shadow", "QUANTUM_ALLOCATION_PROFILE": "[]"}):
        card = await _card(monkeypatch, **env)
        assert "quantum_workloads" in card
        errors = [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in check.iter_errors(card)]
        assert errors == [], env
    bad = await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="on")
    bad["quantum_workloads"]["status"] = "off"           # an off frame publishes no block at all
    assert any("quantum_workloads" in list(map(str, e.absolute_path)) for e in check.iter_errors(bad))


# ── the entity tag ────────────────────────────────────────────────────────────────────────────────────────────────────

def _basis(monkeypatch, **env):
    """The ETag basis _etag_from_basis hashes (captured from its own json.dumps call)."""
    seen = []

    class _Json:
        def __getattr__(self, name):
            return getattr(json, name)

        @staticmethod
        def dumps(obj, *a, **k):
            seen.append(obj)
            return json.dumps(obj, *a, **k)

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(rcb, "json", _Json())
    tag = rcb._etag_from_basis({}, rcb._id_subset({}), None)
    monkeypatch.setattr(rcb, "json", json)
    for k in env:
        monkeypatch.delenv(k, raising=False)
    return tag, seen[-1]


def test_off_keeps_the_tag_basis(monkeypatch):
    tag_unset, basis_unset = _basis(monkeypatch)
    tag_off, basis_off = _basis(monkeypatch, QUANTUM_WORKLOADS_MODE="off")
    assert "quantum" not in basis_unset and basis_off == basis_unset and tag_off == tag_unset


def test_the_tag_turns_with_the_mode_and_with_what_the_block_says(monkeypatch):
    tag_off, basis_off = _basis(monkeypatch)
    tag_shadow, basis_shadow = _basis(monkeypatch, QUANTUM_WORKLOADS_MODE="shadow")
    tag_on, _ = _basis(monkeypatch, QUANTUM_WORKLOADS_MODE="on")
    tag_on_guild, _ = _basis(monkeypatch, QUANTUM_WORKLOADS_MODE="on", GUILD_ENABLED="true")
    assert set(basis_shadow) - set(basis_off) == {"quantum"}
    assert len({tag_off, tag_shadow, tag_on, tag_on_guild}) == 4


async def test_the_304_path_and_the_full_build_agree_with_the_block(monkeypatch):
    monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", "on")
    monkeypatch.setenv("GUILD_ENABLED", "true")
    card = await rcb.build_registry_card(_Db(), sign=False)
    assert "quantum_workloads" in card
    assert card["lifecycle"]["card_etag"] == await rcb.compute_serve_etag(_Db())


# ── the signature ─────────────────────────────────────────────────────────────────────────────────────────────────────

async def _signed(monkeypatch, card):
    from types import SimpleNamespace
    from agentvault_registry.services import registry_card_keystore, registry_card_signer_impl
    key = Ed25519PrivateKey.generate()

    async def _key(db, spiffe_id):
        return SimpleNamespace(rotation_seq=1)

    def _sign(payload, key_row):
        return base64.urlsafe_b64encode(key.sign(registry_card_signer_impl._canonical_bytes(payload))).rstrip(b"=").decode()

    monkeypatch.setattr(registry_card_keystore, "get_or_mint_signing_key", _key)
    monkeypatch.setattr(registry_card_signer_impl, "sign_with_keypair", _sign)
    card["signature"] = await signer.sign_registry_card(card, db=None)
    jwk = {"kty": "OKP", "crv": "Ed25519",
           "x": base64.urlsafe_b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).rstrip(b"=").decode()}
    return card, jwk


def _peer_verifies(card, jwk):
    """What a receiving peer does (background_tasks/federation_sync): the card's OWN declared list, plus the window."""
    from agentvault_registry.services.registry_card_signer_impl import verify_with_jwk
    sig = card["signature"]
    payload = signer.extract_paths(card, sig["signed_canonical"])
    payload["_signed_at"], payload["_expires_at"] = sig["signed_at"], sig["expires_at"]
    return verify_with_jwk(payload, sig["value"], jwk)


async def test_the_card_signs_the_block_whole_only_when_it_carries_it(monkeypatch):
    off, jwk_off = await _signed(monkeypatch, await _card(monkeypatch))
    assert off["signature"]["signed_canonical"] == list(signer.SIGNED_CANONICAL_PATHS)
    assert _peer_verifies(off, jwk_off)
    on, jwk = await _signed(monkeypatch, await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="on", GUILD_ENABLED="true"))
    assert on["signature"]["signed_canonical"] == [*signer.SIGNED_CANONICAL_PATHS, "quantum_workloads"]
    assert _peer_verifies(on, jwk)
    edited = copy.deepcopy(on)
    edited["quantum_workloads"]["acceptance_tests"]["rungs"] = [1]
    assert not _peer_verifies(edited, jwk)                 # an edited block breaks the signature
    dropped = copy.deepcopy(on)
    del dropped["quantum_workloads"]
    assert not _peer_verifies(dropped, jwk)                # and so does a block removed from a card that declared it


# ── the receiver ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _peer_card(block):
    card = {"registry_card_version": "0.6", "identity": {"spiffe_id": "spiffe://peer.example/registry/peer"}}
    if block is not ...:
        card["quantum_workloads"] = block
    return card


def test_the_receiver_keeps_a_card_with_a_good_block_or_none():
    assert validator.validate_payload(_peer_card(...), 200) is None
    for status in ("shadow", "on"):
        assert validator.validate_payload(_peer_card({"status": status}), 200) is None


@pytest.mark.parametrize("status", ["enforce", "off", "on-v2"])
def test_the_receiver_keeps_a_card_whose_block_names_a_status_it_does_not_know(status):
    # review round: a later release may add a mode; refusing the block would freeze the peer's whole card at the last
    # copy this receiver accepted, so an unknown status is kept (a reader treats it as not hosting quantum workloads)
    assert validator.validate_payload(_peer_card({"status": status}), 200) is None


@pytest.mark.parametrize("block", [["on"], "on", None, {}, {"status": 1}, {"status": ""}, {"status": "x" * 33}])
def test_the_receiver_refuses_a_malformed_block(block):
    err = validator.validate_payload(_peer_card(block), 200)
    assert err is not None and "quantum_workloads" in err


# ── the registry-config ───────────────────────────────────────────────────────────────────────────────────────────────

async def _registry_config(monkeypatch, **env):
    os.makedirs("/tmp/prom_multiproc_reg", exist_ok=True)
    from agentvault_registry.core import auth_tiers, federation_view
    from agentvault_registry.main import app

    async def _no_manifest():
        return None

    monkeypatch.setattr(federation_view, "manifest_now", _no_manifest)
    endpoint = next(r.endpoint for r in auth_tiers.api_routes(app) if r.path == "/api/v1/public/registry-config")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    out = await endpoint()
    for k in env:
        monkeypatch.delenv(k, raising=False)
    return json.loads(json.dumps(out, default=str))


async def test_registry_config_carries_the_same_block_as_the_card(monkeypatch):
    off = await _registry_config(monkeypatch)
    cfg = await _registry_config(monkeypatch, QUANTUM_WORKLOADS_MODE="shadow", CONTRACTS_V2_ENABLED="true")
    assert set(cfg) - set(off) == {"quantum_workloads"}
    card = await _card(monkeypatch, QUANTUM_WORKLOADS_MODE="shadow", CONTRACTS_V2_ENABLED="true")
    assert cfg["quantum_workloads"] == card["quantum_workloads"]
    assert cfg["quantum_workloads"]["status"] == "shadow"
