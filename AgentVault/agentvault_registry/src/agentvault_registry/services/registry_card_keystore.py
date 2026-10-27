"""Registry Card v0.3 — EdDSA keystore.

Mirrors AgentSigningKey rotation pattern (routers/agent_signing_keys_admin.py)
at the registry tier. Each registry has its OWN signing-key history keyed by
SPIFFE ID. Auto-mints on first card serve; rotates on demand via admin
endpoint.

At-rest encryption: AES-GCM with a key derived from
REGISTRY_SIGNING_KEY_PASSPHRASE env (HKDF over the passphrase). Sandbox-A
falls back to plaintext storage when the env is absent — with a clear log
warning so the gap is visible.

NB: do NOT add `from __future__ import annotations` here.
"""
import base64
import datetime
import hashlib
import logging
import os
from typing import Optional, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

logger = logging.getLogger(__name__)


_PLAINTEXT_PREFIX = "plain:"
_AESGCM_PREFIX = "aesgcm:"


def _aesgcm_key() -> Optional[bytes]:
    """Derive a 32-byte AES-GCM key from env passphrase, or None if unset."""
    passphrase = os.environ.get("REGISTRY_SIGNING_KEY_PASSPHRASE", "").strip()
    if not passphrase:
        return None
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"theprotocol-registry-card-v03",
        info=b"signing-key-at-rest",
    )
    return hkdf.derive(passphrase.encode("utf-8"))


def _encrypt_pem(private_pem: str) -> str:
    """Encrypt PEM blob; return storage-safe string."""
    key = _aesgcm_key()
    if key is None:
        # AUDIT cross-cutting #5: a missing passphrase silently stored the Ed25519
        # PRIVATE signing key in plaintext (extractable from any DB read / backup
        # dump → forge any card). Fail-CLOSED when REGISTRY_SIGNING_KEY_REQUIRE_ENCRYPTION
        # is on (set in prod) so a misconfigured registry REFUSES to persist a
        # plaintext key rather than doing it quietly. Default-off keeps air-gapped
        # sandbox / L3-Pi deploys working without a passphrase.
        if (os.getenv("REGISTRY_SIGNING_KEY_REQUIRE_ENCRYPTION", "") or "").strip().lower() in ("1", "true", "yes", "on"):
            raise RuntimeError(
                "REGISTRY_SIGNING_KEY_PASSPHRASE is unset but "
                "REGISTRY_SIGNING_KEY_REQUIRE_ENCRYPTION is on — refusing to store "
                "the registry signing key in plaintext (set the passphrase)."
            )
        logger.warning(
            "[RegistryCardKeystore] REGISTRY_SIGNING_KEY_PASSPHRASE unset — "
            "storing signing key in PLAINTEXT (sandbox only; set the env in prod)."
        )
        return _PLAINTEXT_PREFIX + private_pem
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, private_pem.encode("utf-8"), None)
    blob = base64.b64encode(nonce + ct).decode("ascii")
    return _AESGCM_PREFIX + blob


def _decrypt_pem(stored: str) -> str:
    if stored.startswith(_PLAINTEXT_PREFIX):
        return stored[len(_PLAINTEXT_PREFIX):]
    if stored.startswith(_AESGCM_PREFIX):
        key = _aesgcm_key()
        if key is None:
            raise RuntimeError(
                "AES-GCM-stored signing key found but REGISTRY_SIGNING_KEY_PASSPHRASE is unset."
            )
        raw = base64.b64decode(stored[len(_AESGCM_PREFIX):])
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
    # Legacy / raw PEM — treat as plaintext.
    return stored


def _generate_eddsa() -> Tuple[str, dict]:
    """Return (private_pem, public_jwk) for a fresh Ed25519 keypair."""
    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode("ascii"),
        "alg": "EdDSA",
    }
    return private_pem, public_jwk


async def _current_key_row(
    db: AsyncSession,
    spiffe_id: str,
) -> Optional[models.RegistrySigningKey]:
    """Return the currently-active row (expires_at IS NULL with max rotation_seq)."""
    stmt = (
        select(models.RegistrySigningKey)
        .where(
            models.RegistrySigningKey.registry_spiffe_id == spiffe_id,
            models.RegistrySigningKey.expires_at.is_(None),
        )
        .order_by(models.RegistrySigningKey.rotation_seq.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_or_mint_signing_key(
    db: AsyncSession,
    spiffe_id: str,
) -> models.RegistrySigningKey:
    """Return current key row; mint a brand-new (rotation_seq=1) one if none exist."""
    existing = await _current_key_row(db, spiffe_id)
    if existing is not None:
        return existing

    private_pem, public_jwk = _generate_eddsa()
    encrypted = _encrypt_pem(private_pem)
    row = models.RegistrySigningKey(
        registry_spiffe_id=spiffe_id,
        rotation_seq=1,
        public_jwk=public_jwk,
        private_pem_encrypted=encrypted,
        algorithm="EdDSA",
        expires_at=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info(
        "[RegistryCardKeystore] minted initial signing key for spiffe=%s rotation_seq=1",
        spiffe_id,
    )
    return row


async def rotate_signing_key(
    db: AsyncSession,
    spiffe_id: str,
    *,
    grace_days: int = 7,
) -> models.RegistrySigningKey:
    """Mint a new key, mark the prior current row expired NOW + grace_days."""
    max_seq = (await db.execute(
        select(func.coalesce(func.max(models.RegistrySigningKey.rotation_seq), 0))
        .where(models.RegistrySigningKey.registry_spiffe_id == spiffe_id)
    )).scalar() or 0
    new_seq = int(max_seq) + 1

    # Expire current row.
    existing = await _current_key_row(db, spiffe_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    if existing is not None:
        existing.expires_at = now + datetime.timedelta(days=grace_days)

    private_pem, public_jwk = _generate_eddsa()
    encrypted = _encrypt_pem(private_pem)
    new_row = models.RegistrySigningKey(
        registry_spiffe_id=spiffe_id,
        rotation_seq=new_seq,
        public_jwk=public_jwk,
        private_pem_encrypted=encrypted,
        algorithm="EdDSA",
        expires_at=None,
    )
    db.add(new_row)
    await db.flush()
    await db.refresh(new_row)
    logger.info(
        "[RegistryCardKeystore] rotated key for spiffe=%s new_seq=%d grace_until=%s",
        spiffe_id, new_seq,
        (existing.expires_at.isoformat() if existing and existing.expires_at else "(no prior)"),
    )
    return new_row


def load_private_key(row: models.RegistrySigningKey) -> Ed25519PrivateKey:
    pem = _decrypt_pem(row.private_pem_encrypted)
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


__all__ = [
    "get_or_mint_signing_key",
    "rotate_signing_key",
    "load_private_key",
]
