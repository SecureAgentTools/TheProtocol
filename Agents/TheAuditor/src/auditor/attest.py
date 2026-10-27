"""§GLOBALSTD Phase 1 (2026-08-22) — TPSA-1 signed supply attestations.

Every audit cycle on a prod frame emits an ATTESTATION: a canonical-JSON payload
carrying the invariant terms, the verdict, its own coverage limits (recon_basis)
and the digest of the previous attestation for the frame (a per-frame hash
chain), signed with a durable Ed25519 key. The signature makes a verdict
portable — verifiable offline against /.well-known/auditor-jwks.json — and the
chain makes history tamper-evident: rewriting a stored verdict breaks every
link after it.

Canonicalization (TPSA-1.0): json.dumps(obj, sort_keys=True (recursive by
construction), separators=(",", ":"), ensure_ascii=True). Numbers are IEEE-754
floats serialized by Python repr; the conformance verifier is Python, so
recompute is byte-identical (a decimal-string profile is the TPSA-2 upgrade
path). The BYTES stored in `payload` are exactly the bytes that were signed:
a verifier checks sha256(payload) == digest and Ed25519.verify(signature,
payload) WITHOUT re-canonicalizing anything.
"""
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

STANDARD = "TPSA-1.0"


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class AttestKey:
    def __init__(self, priv: Ed25519PrivateKey):
        self._priv = priv
        pub = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.pub_raw = pub
        self.kid = hashlib.sha256(pub).hexdigest()[:16]
        self.jwk = {
            "kty": "OKP", "crv": "Ed25519", "x": _b64u(pub),
            "kid": self.kid, "use": "sig", "alg": "EdDSA",
        }

    def sign(self, payload: str) -> str:
        return _b64u(self._priv.sign(payload.encode()))

    @staticmethod
    def digest(payload: str) -> str:
        return hashlib.sha256(payload.encode()).hexdigest()


def retired_jwks(data_dir: Path) -> list:
    """Retired verification keys, so every historic attestation stays verifiable.
    Rotation ceremony: cp attest_ed25519.pub attest_retired_<kid>.pub; rm
    attest_ed25519.key attest_ed25519.pub; restart. A new key generates and the
    JWKS serves current + retired."""
    out = []
    for p in sorted(data_dir.glob("attest_retired_*.pub")):
        raw = p.read_bytes()
        if len(raw) != 32:
            continue
        kid = hashlib.sha256(raw).hexdigest()[:16]
        out.append({"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw),
                    "kid": kid, "use": "sig", "alg": "EdDSA"})
    return out


def load_or_create(data_dir: Path) -> AttestKey:
    """The key lives on the durable ./data bind mount (§AGENTDISC lesson: a key on
    the container filesystem dies with every recreate and silently re-keys the
    chain). Created 0600 with O_EXCL; the raw public key is written beside it so
    the key can be inspected without touching the private half."""
    kp = data_dir / "attest_ed25519.key"
    if kp.exists():
        priv = Ed25519PrivateKey.from_private_bytes(kp.read_bytes())
    else:
        priv = Ed25519PrivateKey.generate()
        raw = priv.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        fd = os.open(str(kp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        (data_dir / "attest_ed25519.pub").write_bytes(
            priv.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        )
    return AttestKey(priv)
