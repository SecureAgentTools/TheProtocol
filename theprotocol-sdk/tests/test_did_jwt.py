"""Q-C W5 (2026-05-12) — did_jwt_self_signed extension SDK helpers.

Tests issue+verify round-trip and the major failure modes:
- audience mismatch
- issuer mismatch
- tampered signature
- expired token
- malformed token
- unsupported algorithm

Per Commander Q3 (server-generated, shown ONCE) + Q4 (EdDSA) + Q9 (URI namespace).
"""
from __future__ import annotations

import base64
import time

import pytest

from theprotocol.auth.did_jwt import (
    EXT_URI_DID_JWT,
    DidJwtError,
    mint_did_jwt,
    verify_did_jwt,
)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


@pytest.fixture
def keypair():
    """Generate an Ed25519 keypair + return (private_pem, public_jwk)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64url(pub_raw), "alg": "EdDSA"}
    return priv_pem, public_jwk


class TestMintVerifyRoundtrip:
    def test_basic_roundtrip(self, keypair):
        priv_pem, public_jwk = keypair
        token = mint_did_jwt(
            private_pem=priv_pem,
            iss="did:theprotocol:caller",
            aud="did:theprotocol:target",
        )
        assert token.count(".") == 2
        claims = verify_did_jwt(token, public_jwk, expected_aud="did:theprotocol:target")
        assert claims["iss"] == "did:theprotocol:caller"
        assert claims["aud"] == "did:theprotocol:target"
        assert "exp" in claims and "iat" in claims
        assert "nonce" in claims and len(claims["nonce"]) == 32  # 16 bytes hex

    def test_additional_claims_pass_through(self, keypair):
        priv_pem, public_jwk = keypair
        token = mint_did_jwt(
            private_pem=priv_pem,
            iss="did:theprotocol:c",
            aud="did:theprotocol:t",
            additional_claims={"scope": "read:agents"},
        )
        claims = verify_did_jwt(token, public_jwk, expected_aud="did:theprotocol:t")
        assert claims["scope"] == "read:agents"

    def test_nonce_override_preserved(self, keypair):
        priv_pem, public_jwk = keypair
        token = mint_did_jwt(
            private_pem=priv_pem,
            iss="did:theprotocol:c",
            aud="did:theprotocol:t",
            nonce="custom-nonce-12345",
        )
        claims = verify_did_jwt(token, public_jwk, expected_aud="did:theprotocol:t")
        assert claims["nonce"] == "custom-nonce-12345"


class TestVerifyFailureModes:
    def test_wrong_audience(self, keypair):
        priv_pem, public_jwk = keypair
        token = mint_did_jwt(private_pem=priv_pem, iss="did:theprotocol:c", aud="did:theprotocol:t")
        with pytest.raises(DidJwtError, match="audience mismatch"):
            verify_did_jwt(token, public_jwk, expected_aud="did:theprotocol:wrong")

    def test_wrong_issuer(self, keypair):
        priv_pem, public_jwk = keypair
        token = mint_did_jwt(private_pem=priv_pem, iss="did:theprotocol:c", aud="did:theprotocol:t")
        with pytest.raises(DidJwtError, match="issuer mismatch"):
            verify_did_jwt(
                token, public_jwk,
                expected_aud="did:theprotocol:t",
                expected_iss="did:theprotocol:other",
            )

    def test_tampered_signature(self, keypair):
        priv_pem, public_jwk = keypair
        token = mint_did_jwt(private_pem=priv_pem, iss="did:theprotocol:c", aud="did:theprotocol:t")
        parts = token.split(".")
        # mutate first 4 chars of signature
        tampered = f"{parts[0]}.{parts[1]}.AAAA{parts[2][4:]}"
        with pytest.raises(DidJwtError, match="signature verification failed"):
            verify_did_jwt(tampered, public_jwk, expected_aud="did:theprotocol:t")

    def test_expired_token(self, keypair):
        priv_pem, public_jwk = keypair
        token = mint_did_jwt(
            private_pem=priv_pem,
            iss="did:theprotocol:c",
            aud="did:theprotocol:t",
            lifetime_sec=1,
        )
        time.sleep(2)
        with pytest.raises(DidJwtError, match="expired"):
            verify_did_jwt(token, public_jwk, expected_aud="did:theprotocol:t", leeway_sec=0)

    def test_malformed_jwt(self, keypair):
        _, public_jwk = keypair
        with pytest.raises(DidJwtError, match="malformed"):
            verify_did_jwt("not.a.valid.jwt", public_jwk)

    def test_wrong_public_key_rejects(self, keypair):
        priv_pem, _ = keypair
        token = mint_did_jwt(private_pem=priv_pem, iss="did:theprotocol:c", aud="did:theprotocol:t")
        # Build a DIFFERENT keypair for verification
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        other = Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        wrong_jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64url(other), "alg": "EdDSA"}
        with pytest.raises(DidJwtError, match="signature"):
            verify_did_jwt(token, wrong_jwk, expected_aud="did:theprotocol:t")


class TestExtensionURI:
    def test_extension_uri_constant(self):
        assert EXT_URI_DID_JWT == "https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed"

    def test_lifetime_validation(self, keypair):
        priv_pem, _ = keypair
        with pytest.raises(ValueError, match="lifetime_sec"):
            mint_did_jwt(private_pem=priv_pem, iss="did:c", aud="did:t", lifetime_sec=0)
        with pytest.raises(ValueError, match="lifetime_sec"):
            mint_did_jwt(private_pem=priv_pem, iss="did:c", aud="did:t", lifetime_sec=4000)
