"""Tests for Registry Card v0.3 EdDSA verification (card_verify).

The signer half is rebuilt here from the documented contract (extract the
declared canonical paths, re-inject the signature block's freshness window as
``_signed_at``/``_expires_at``, canonicalize with sort_keys/compact
separators, sign with Ed25519) so the verifier is exercised against payloads
it did not build itself. Negative cases assert False, so a verifier that
always returns True fails this suite.
"""
import base64
import json
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from theprotocol.registry.card_verify import extract_paths, verify_registry_card
from theprotocol.registry.cost_composition import SIGNED_CANONICAL_PATHS

DECLARED = ["identity.registry_name", "identity.trust_domain", "fees.hosting.enabled"]


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _base_card() -> dict:
    return {
        "registry_card_version": "0.5",
        "identity": {
            "registry_name": "Registry-A",
            "trust_domain": "agentvault.com",
            "spiffe_id": "spiffe://agentvault.com/registry",
            "tier": "sovereign",
        },
        "federation": {"is_genesis_registry": True, "is_sovereign_frame": True},
        "fees": {"hosting": {"enabled": False}},
        "lifecycle": {"card_etag": "etag-1"},
        "unsigned_extra": {"note": "not part of any canonical path"},
    }


def _sign_card(card, *, kid="test-key-1", declared=DECLARED, signed_at=None,
               expires_at=None, jwks_kid=None, sig_bytes_override=None):
    """Return (card_with_signature, jwks) signed per the documented contract."""
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    payload = extract_paths(card, declared if declared is not None else SIGNED_CANONICAL_PATHS)
    if signed_at is not None:
        payload["_signed_at"] = signed_at
    if expires_at is not None:
        payload["_expires_at"] = expires_at
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    signature = sig_bytes_override if sig_bytes_override is not None else priv.sign(blob)

    card = dict(card)
    sig_block = {"algorithm": "EdDSA", "kid": kid, "value": _b64url(signature)}
    if declared is not None:
        sig_block["signed_canonical"] = declared
    if signed_at is not None:
        sig_block["signed_at"] = signed_at
    if expires_at is not None:
        sig_block["expires_at"] = expires_at
    card["signature"] = sig_block

    jwks = {"keys": [{"kty": "OKP", "crv": "Ed25519",
                      "kid": jwks_kid or kid, "x": _b64url(pub_raw)}]}
    return card, jwks


def test_valid_card_verifies():
    card, jwks = _sign_card(_base_card())
    assert verify_registry_card(card, jwks) is True


def test_default_canonical_paths_when_none_declared():
    # No signed_canonical in the block -> verifier must fall back to the 13 spec paths.
    card, jwks = _sign_card(_base_card(), declared=None)
    assert "signed_canonical" not in card["signature"]
    assert verify_registry_card(card, jwks) is True


def test_tampered_signed_field_fails():
    card, jwks = _sign_card(_base_card())
    card["identity"]["registry_name"] = "Registry-EVIL"
    assert verify_registry_card(card, jwks) is False


def test_unsigned_field_change_still_verifies():
    # Fields outside the declared paths are not covered by the signature.
    card, jwks = _sign_card(_base_card())
    card["unsigned_extra"]["note"] = "mutated after signing"
    assert verify_registry_card(card, jwks) is True


def test_expired_signature_fails():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    card, jwks = _sign_card(_base_card(), expires_at=past)
    assert verify_registry_card(card, jwks) is False


def test_unexpired_signature_passes_and_now_override_expires_it():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    card, jwks = _sign_card(_base_card(), signed_at=datetime.now(timezone.utc).isoformat(),
                            expires_at=future)
    assert verify_registry_card(card, jwks) is True
    beyond = datetime.now(timezone.utc) + timedelta(hours=2)
    assert verify_registry_card(card, jwks, now=beyond) is False


def test_freshness_window_is_covered_by_signature():
    # expires_at rides the signed payload: moving it after signing must fail
    # even while the new window is still in the future.
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    card, jwks = _sign_card(_base_card(), expires_at=future)
    card["signature"]["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(days=365)
    ).isoformat()
    assert verify_registry_card(card, jwks) is False


def test_newer_card_with_longer_declared_list_verifies():
    # Cards newer than the v0.3 baseline declare MORE paths (prod v0.5 declares
    # 23), including blocks the baseline never knew about. The verifier must
    # follow the card's declared list, and a declared path is tamper-covered.
    card = _base_card()
    card["identity"]["public_url"] = "https://api.example.test"
    card["compliance"] = {"jurisdiction_profile": {"name": "no-fiat-baseline"}}
    declared = SIGNED_CANONICAL_PATHS + [
        "identity.public_url",
        "compliance.jurisdiction_profile.name",
    ]
    signed, jwks = _sign_card(card, declared=declared)
    assert verify_registry_card(signed, jwks) is True
    signed["compliance"]["jurisdiction_profile"]["name"] = "evil-profile"
    assert verify_registry_card(signed, jwks) is False


def test_kid_mismatch_fails():
    card, jwks = _sign_card(_base_card(), jwks_kid="some-other-key")
    assert verify_registry_card(card, jwks) is False


def test_garbage_signature_fails():
    card, jwks = _sign_card(_base_card(), sig_bytes_override=b"\x00" * 64)
    assert verify_registry_card(card, jwks) is False


def test_missing_signature_block_or_malformed_inputs_return_false():
    card, jwks = _sign_card(_base_card())
    unsigned = {k: v for k, v in card.items() if k != "signature"}
    assert verify_registry_card(unsigned, jwks) is False
    assert verify_registry_card(card, {}) is False
    assert verify_registry_card("not-a-dict", jwks) is False
    broken = dict(card)
    broken["signature"] = {**card["signature"], "value": "%%%not-base64%%%"}
    assert verify_registry_card(broken, jwks) is False


def test_extract_paths_order_and_missing_resolve_to_none():
    card = _base_card()
    paths = ["fees.hosting.enabled", "identity.registry_name", "no.such.path"]
    out = extract_paths(card, paths)
    assert list(out.keys()) == paths
    assert out["fees.hosting.enabled"] is False
    assert out["identity.registry_name"] == "Registry-A"
    assert out["no.such.path"] is None
    assert extract_paths(card, None) == {}
