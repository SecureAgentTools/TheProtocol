"""Tests for sign_agent_card / verify_agent_card (Option C Phase 9.a)."""

import json
import pytest

cryptography = pytest.importorskip("cryptography")

from theprotocol.auth import sign_agent_card, verify_agent_card
from theprotocol.auth.jws_card import _canonical_payload_bytes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    import base64
    pub_jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode("ascii"),
        "alg": "EdDSA",
    }
    return priv_pem, pub_jwk


def _sample_card():
    return {
        "protocolVersion": "1.0",
        "humanReadableId": "veridian",
        "agentVersion": "1.0.0",
        "name": "VERIDIAN",
        "description": "Witness oracle",
        "supportedInterfaces": [{"url": "https://veridian.example/a2a", "protocolBinding": "REST", "protocolVersion": "1.0"}],
        "securitySchemes": {"agent_jwt": {"type": "http", "scheme": "bearer"}},
        "security": [{"agent_jwt": []}],
        "provider": {"name": "TheProtocol"},
        "capabilities": {"streaming": False},
    }


def test_sign_then_verify_roundtrip():
    priv_pem, pub_jwk = _make_keypair()
    signed = sign_agent_card(_sample_card(), private_pem=priv_pem, kid="did:test:abc#1")
    assert "signatures" in signed
    assert len(signed["signatures"]) == 1
    entry = signed["signatures"][0]
    assert "protected" in entry and "signature" in entry

    valid, reason = verify_agent_card(signed, pub_jwk)
    assert valid, f"unexpected fail: {reason}"


def test_verify_fails_when_card_tampered():
    priv_pem, pub_jwk = _make_keypair()
    signed = sign_agent_card(_sample_card(), private_pem=priv_pem, kid="did:test:abc#1")
    signed["name"] = "TAMPERED"
    valid, reason = verify_agent_card(signed, pub_jwk)
    assert not valid
    assert reason is not None


def test_verify_fails_with_wrong_public_key():
    priv_pem_a, _ = _make_keypair()
    _, pub_jwk_b = _make_keypair()
    signed = sign_agent_card(_sample_card(), private_pem=priv_pem_a, kid="did:test:abc#1")
    valid, _ = verify_agent_card(signed, pub_jwk_b)
    assert not valid


def test_verify_with_expected_kid():
    priv_pem, pub_jwk = _make_keypair()
    signed = sign_agent_card(_sample_card(), private_pem=priv_pem, kid="did:test:abc#3")
    valid_match, _ = verify_agent_card(signed, pub_jwk, expected_kid="did:test:abc#3")
    assert valid_match
    valid_mismatch, reason = verify_agent_card(signed, pub_jwk, expected_kid="did:test:abc#9")
    assert not valid_mismatch
    assert reason is not None


def test_re_signing_same_kid_replaces_entry():
    priv_pem, pub_jwk = _make_keypair()
    card = _sample_card()
    signed_v1 = sign_agent_card(card, private_pem=priv_pem, kid="did:test:abc#1")
    # Mutate description, re-sign with the same kid → still exactly one entry.
    signed_v2 = sign_agent_card(
        {**signed_v1, "description": "updated"},
        private_pem=priv_pem,
        kid="did:test:abc#1",
    )
    assert len(signed_v2["signatures"]) == 1


def test_multiple_kids_preserved():
    priv_a, jwk_a = _make_keypair()
    priv_b, jwk_b = _make_keypair()
    card = sign_agent_card(_sample_card(), private_pem=priv_a, kid="did:test:abc#1")
    card = sign_agent_card(card, private_pem=priv_b, kid="did:test:abc#2")
    assert len(card["signatures"]) == 2
    # Both verify against their respective public keys
    assert verify_agent_card(card, jwk_a, expected_kid="did:test:abc#1")[0]
    assert verify_agent_card(card, jwk_b, expected_kid="did:test:abc#2")[0]


def test_canonical_payload_excludes_signatures():
    card_with = sign_agent_card(
        _sample_card(),
        private_pem=_make_keypair()[0],
        kid="did:test:abc#1",
    )
    # The bytes used as signing input must NOT include the signatures field.
    bytes_with = _canonical_payload_bytes(card_with)
    bytes_without = _canonical_payload_bytes({k: v for k, v in card_with.items() if k != "signatures"})
    assert bytes_with == bytes_without
    parsed = json.loads(bytes_with.decode())
    assert "signatures" not in parsed


def test_verify_returns_reason_on_no_signatures_array():
    unsigned = _sample_card()
    _, pub_jwk = _make_keypair()
    valid, reason = verify_agent_card(unsigned, pub_jwk)
    assert not valid
    assert reason == "no signatures array"
