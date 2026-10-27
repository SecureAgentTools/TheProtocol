"""Ed25519-based bundle signer for ZKP attestations (Phase 4).

The registry holds a single Ed25519 keypair used to sign exportable
attestation bundles. Anyone with the public key can verify a bundle's
authenticity offline — no trust in the registry's HTTP API required.

Key lifecycle:
  - `BUNDLE_SIGNING_KEY_PATH` env var (default `/app/data/bundle_signing_ed25519.key`).
  - On first call to `get_signing_key()`, the file is loaded if it exists,
    otherwise a fresh keypair is generated and persisted.
  - The pubkey id is `sha256(pubkey_bytes)[:16]` (hex) — short enough to
    reference in a bundle, long enough to disambiguate across rotations.

Canonical signing format:
  - The bundle is built as a Python dict with the `signature` field set to
    the empty string.
  - It is serialized to JSON with `sort_keys=True, separators=(',',':')`.
  - The signing input is the UTF-8 encoded byte string.
  - The signature is base64-encoded and replaces the empty `signature`
    field in the final returned bundle.

Verification reverses the process: replace `signature` with empty string,
re-canonicalize, base64-decode the signature, ed25519 verify against
the registry's public key.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

_DEFAULT_KEY_PATH = "/app/data/bundle_signing_ed25519.key"
_KEY_CACHE: Dict[str, Any] = {}


def _key_path() -> Path:
    return Path(os.environ.get("BUNDLE_SIGNING_KEY_PATH", _DEFAULT_KEY_PATH))


def _load_or_generate_key() -> Ed25519PrivateKey:
    p = _key_path()
    if p.exists():
        try:
            raw = p.read_bytes()
            if len(raw) == 32:
                return Ed25519PrivateKey.from_private_bytes(raw)
        except Exception as exc:
            logger.warning(
                f"[BundleSigner] failed to load key at {p}: {exc} — regenerating"
            )
    # Generate + persist
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    except Exception as exc:
        logger.warning(
            f"[BundleSigner] could not persist signing key to {p}: {exc} "
            f"(in-memory only, key will rotate on restart)"
        )
    logger.info(f"[BundleSigner] generated fresh Ed25519 keypair at {p}")
    return key


def get_signing_key() -> Ed25519PrivateKey:
    if "private" not in _KEY_CACHE:
        _KEY_CACHE["private"] = _load_or_generate_key()
    return _KEY_CACHE["private"]


def get_pubkey_bytes() -> bytes:
    return get_signing_key().public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw,
    )


def get_pubkey_b64() -> str:
    return base64.b64encode(get_pubkey_bytes()).decode("ascii")


def get_pubkey_id() -> str:
    """Short hex id used to pin the signing key referenced by a bundle."""
    return hashlib.sha256(get_pubkey_bytes()).hexdigest()[:16]


def _canonical_bytes(bundle: Dict[str, Any]) -> bytes:
    """Canonicalize a bundle for signing or verification.

    The `signature` field is replaced with an empty string before
    serialization so the same bytes are produced before and after signing.
    Sorted keys + minimal separators give a unique deterministic encoding.
    """
    cleaned = dict(bundle)
    cleaned["signature"] = ""
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Add `signature_alg`, `signature_pubkey_id`, and `signature` fields
    to the bundle in-place. Returns the same dict for convenience."""
    bundle.setdefault("signature_alg", "Ed25519")
    bundle["signature_pubkey_id"] = get_pubkey_id()
    payload = _canonical_bytes(bundle)
    sig = get_signing_key().sign(payload)
    bundle["signature"] = base64.b64encode(sig).decode("ascii")
    return bundle


def verify_bundle_signature(
    bundle: Dict[str, Any],
    *,
    issuer_pubkey_b64: Optional[str] = None,
) -> Tuple[bool, str]:
    """Verify a bundle's signature.

    If `issuer_pubkey_b64` is provided, that key is used (offline
    verifier path). Otherwise the local registry's pubkey is used
    (server-side verify-bundle endpoint).

    Returns (True, "ok") on success or (False, reason) on failure.
    """
    sig_b64 = bundle.get("signature")
    if not sig_b64:
        return False, "missing signature field"
    if bundle.get("signature_alg") not in (None, "Ed25519"):
        return False, f"unsupported signature_alg: {bundle.get('signature_alg')!r}"

    try:
        sig = base64.b64decode(sig_b64)
    except Exception as exc:
        return False, f"signature b64 decode failed: {exc}"

    if issuer_pubkey_b64:
        try:
            pub_bytes = base64.b64decode(issuer_pubkey_b64)
        except Exception as exc:
            return False, f"pubkey b64 decode failed: {exc}"
        try:
            pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
        except Exception as exc:
            return False, f"pubkey load failed: {exc}"
    else:
        pub = get_signing_key().public_key()

    payload = _canonical_bytes(bundle)
    try:
        pub.verify(sig, payload)
    except InvalidSignature:
        return False, "signature does not match canonical payload"
    except Exception as exc:
        return False, f"verify failed: {exc}"
    return True, "ok"
