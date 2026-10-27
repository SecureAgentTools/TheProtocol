"""OAuth Federation RS256 keystore — RA2 (2026-07-24).

Before this module, cross-registry OAuth federation had no signing key at all:

* ``GET /oauth/.well-known/jwks.json`` generated a **brand-new random RSA keypair
  on every single request** and published the public half. Nothing a peer ever
  fetched could verify anything, and two consecutive fetches disagreed.
* Exchange tokens were meanwhile signed **HS256 with the registry master
  SECRET_KEY** (via ``security.create_access_token``), i.e. the same secret that
  signs developer and agent JWTs was being handed to a cross-registry surface.

The live consumer is the TEG's multi-issuer verifier
(``teg_core_service/core/oauth/multi_issuer_jwt.py``), which fetches the issuer's
``jwks_uri`` and verifies with ``algorithms=["RS256"]``. So federation gets its
own durable **RS256** keypair (not EdDSA like the registry cards) and exchange
tokens are signed with it — the master HS256 secret never leaves the local
token layer again.

Storage reuses ``models.RegistrySigningKey`` (the registry-card keystore table):
same rotation-history shape, same AES-GCM at-rest encryption helpers, keyed by a
``oauth-federation:`` purpose prefix so the two key families cannot collide.
Rotation keeps the previous public key published until it expires, so tokens
minted just before a rotation still verify.
"""
import base64
import datetime
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import jwt  # PyJWT — this module signs/verifies RS256 (security.py's HS256 is PyJWT too since §DEPS)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
# Reuse the card keystore's at-rest encryption verbatim: one passphrase, one
# derivation, one fail-closed policy for every private key this registry holds.
from .registry_card_keystore import _decrypt_pem, _encrypt_pem

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"
_PURPOSE_PREFIX = "oauth-federation:"
_KEY_SIZE = 2048


def purpose_id(issuer: str) -> str:
    """Storage key for this registry's federation keypair.

    Namespaced so a card key and a federation key for the same registry are
    different rows rather than one overwriting the other.
    """
    return f"{_PURPOSE_PREFIX}{issuer}"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _int_b64u(value: int) -> str:
    if value == 0:
        return _b64u(b"\x00")
    return _b64u(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def _thumbprint(n_b64: str, e_b64: str) -> str:
    """RFC 7638 JWK thumbprint — a stable, content-derived `kid`.

    Stable matters: the TEG caches JWKS per issuer and selects by kid, so the kid
    must not change unless the key does.
    """
    canonical = json.dumps({"e": e_b64, "kty": "RSA", "n": n_b64}, separators=(",", ":"), sort_keys=True)
    return _b64u(hashlib.sha256(canonical.encode("utf-8")).digest())


def _generate_rsa() -> Tuple[str, Dict[str, Any]]:
    """Return (private_pem, public_jwk) for a fresh RS256 keypair."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    numbers = priv.public_key().public_numbers()
    n_b64 = _int_b64u(numbers.n)
    e_b64 = _int_b64u(numbers.e)
    public_jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": ALGORITHM,
        "kid": _thumbprint(n_b64, e_b64),
        "n": n_b64,
        "e": e_b64,
    }
    return private_pem, public_jwk


async def _current_row(db: AsyncSession, issuer: str) -> Optional[models.RegistrySigningKey]:
    stmt = (
        select(models.RegistrySigningKey)
        .where(
            models.RegistrySigningKey.registry_spiffe_id == purpose_id(issuer),
            models.RegistrySigningKey.expires_at.is_(None),
        )
        .order_by(models.RegistrySigningKey.rotation_seq.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_or_mint_key(db: AsyncSession, issuer: str) -> models.RegistrySigningKey:
    """Return the current federation key, minting one on first use.

    Auto-mint mirrors the card keystore: a registry that has never federated
    still serves a valid, stable JWKS the moment someone asks.
    """
    existing = await _current_row(db, issuer)
    if existing is not None:
        return existing

    private_pem, public_jwk = _generate_rsa()
    row = models.RegistrySigningKey(
        registry_spiffe_id=purpose_id(issuer),
        rotation_seq=1,
        public_jwk=public_jwk,
        private_pem_encrypted=_encrypt_pem(private_pem),
        algorithm=ALGORITHM,
        expires_at=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info(
        "[OAuthKeystore] minted initial federation key issuer=%s kid=%s",
        issuer, public_jwk["kid"],
    )
    return row


async def rotate_key(
    db: AsyncSession,
    issuer: str,
    *,
    grace_days: int = 7,
) -> models.RegistrySigningKey:
    """Mint a new key; the old public key stays published for `grace_days`."""
    max_seq = (await db.execute(
        select(func.coalesce(func.max(models.RegistrySigningKey.rotation_seq), 0))
        .where(models.RegistrySigningKey.registry_spiffe_id == purpose_id(issuer))
    )).scalar() or 0

    now = datetime.datetime.now(datetime.timezone.utc)
    existing = await _current_row(db, issuer)
    if existing is not None:
        existing.expires_at = now + datetime.timedelta(days=grace_days)

    private_pem, public_jwk = _generate_rsa()
    new_row = models.RegistrySigningKey(
        registry_spiffe_id=purpose_id(issuer),
        rotation_seq=int(max_seq) + 1,
        public_jwk=public_jwk,
        private_pem_encrypted=_encrypt_pem(private_pem),
        algorithm=ALGORITHM,
        expires_at=None,
    )
    db.add(new_row)
    await db.commit()
    await db.refresh(new_row)
    logger.info(
        "[OAuthKeystore] rotated federation key issuer=%s new_kid=%s grace_until=%s",
        issuer, public_jwk["kid"],
        existing.expires_at.isoformat() if existing is not None and existing.expires_at else "(no prior)",
    )
    return new_row


async def public_jwks(db: AsyncSession, issuer: str) -> Dict[str, List[Dict[str, Any]]]:
    """The JWKS document: current key plus any rotated key still inside its grace window."""
    current = await get_or_mint_key(db, issuer)

    now = datetime.datetime.now(datetime.timezone.utc)
    stmt = (
        select(models.RegistrySigningKey)
        .where(
            models.RegistrySigningKey.registry_spiffe_id == purpose_id(issuer),
            models.RegistrySigningKey.expires_at.is_not(None),
            models.RegistrySigningKey.expires_at > now,
        )
        .order_by(models.RegistrySigningKey.rotation_seq.desc())
    )
    grace_rows = (await db.execute(stmt)).scalars().all()

    keys = [current.public_jwk] + [row.public_jwk for row in grace_rows]
    # Defensive: never publish a row that predates this module (EdDSA card keys
    # are a different purpose_id, but a hand-inserted row should not break peers).
    return {"keys": [k for k in keys if isinstance(k, dict) and k.get("kty") == "RSA"]}


def load_private_pem(row: models.RegistrySigningKey) -> str:
    return _decrypt_pem(row.private_pem_encrypted)


def load_private_key(row: models.RegistrySigningKey) -> RSAPrivateKey:
    return serialization.load_pem_private_key(load_private_pem(row).encode("utf-8"), password=None)


def sign(payload: Dict[str, Any], row: models.RegistrySigningKey) -> str:
    """Sign a federation token RS256 with this registry's federation key.

    The `kid` header is what lets a peer (and the TEG) pick the right key out of
    the published JWKS instead of trying them all.
    """
    kid = (row.public_jwk or {}).get("kid")
    return jwt.encode(
        payload,
        load_private_pem(row),
        algorithm=ALGORITHM,
        headers={"kid": kid} if kid else None,
    )


def verify_self_signed(token: str, jwks: Dict[str, Any], *, audience: Any = None, issuer: Optional[str] = None) -> Dict[str, Any]:
    """Verify a token this registry issued, against its own published JWKS.

    Used by introspection so the answer is derived from the real signature rather
    than from the HS256 master secret (which no longer signs these tokens).
    """
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    candidates = [k for k in jwks.get("keys", []) if not kid or k.get("kid") == kid] or jwks.get("keys", [])

    last_error: Optional[Exception] = None
    for jwk_dict in candidates:
        try:
            key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk_dict))
            return jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=audience,
                issuer=issuer,
                options={"verify_aud": audience is not None},
            )
        except Exception as exc:  # noqa: BLE001 — try every candidate key before giving up
            last_error = exc
    raise last_error or ValueError("no verification key available")
