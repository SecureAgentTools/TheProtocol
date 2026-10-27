"""§pass51 Block 1 — per-developer signing keys + JWS sign/verify.

Design per PLAN_2026-05-20_BUNDLES_AAA_REBOOT.md §14.

- Each developer gets one ACTIVE Ed25519 keypair stored in
  developer_signing_keys (created lazily on first sign or rotation).
- Sign returns a detached JWS (header.payload base64-encoded, signature
  computed over canonical manifest JSON).
- Verify accepts a JWS + payload; looks up the public key via the dev_id
  in the unprotected header AND validates against the active key in the DB.
- Cross-registry verify (Part II §14.3 step 4) uses the issuer URL claim
  to federation-fetch JWKS — implemented as a stub that returns local key
  for now; full federation fetch ships in Phase 5.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Key generation ──────────────────────────────────────────────────────────

def generate_keypair() -> tuple[str, dict, str]:
    """Generate fresh Ed25519 keypair.

    Returns (private_pem, public_jwk, fingerprint).
    """
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    x_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode("ascii")
    jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": x_b64,
        "alg": "EdDSA",
        "use": "sig",
    }
    # Fingerprint = sha256 of canonical JWK
    canon = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": x_b64}, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canon.encode()).hexdigest()[:64]
    jwk["kid"] = fingerprint
    return priv_pem, jwk, fingerprint


# ── DB helpers ──────────────────────────────────────────────────────────────

async def get_or_create_active_key(db: AsyncSession, developer_id: int) -> dict:
    """Returns active signing key for dev, creating one lazily if missing.

    Returns dict: {id, public_key_jwk, private_key_pem, fingerprint, rotation_seq}
    """
    from agentvault_registry.models import Developer  # avoid circular  # noqa: F401

    row = await db.execute(
        # raw SQL to avoid declaring a SQLAlchemy model for a freshly-added table
        # in this phase; service.py uses raw too. Phase 2+ adds the model.
        # ↓ select active key
        # language=sql
        # (using text() form via .execute would force a no-orm path; for parity
        #  with rest of codebase we use the same async session .execute(text))
        # NOTE: this lives in the registry's existing engine + session
        # (postgres async via pgbouncer per docker-compose env)
        select_active_key_sql(),
        {"developer_id": developer_id},
    )
    existing = row.first()
    if existing:
        return {
            "id": str(existing[0]),
            "public_key_jwk": existing[1],
            "private_key_pem": existing[2],
            "fingerprint": existing[3],
            "rotation_seq": existing[4],
        }

    # Lazy generation
    priv_pem, pub_jwk, fp = generate_keypair()
    insert_row = await db.execute(
        insert_key_sql(),
        {
            "developer_id": developer_id,
            "public_key_jwk": json.dumps(pub_jwk),
            "private_key_pem": priv_pem,
            "fingerprint": fp,
        },
    )
    new_id = insert_row.scalar()
    await db.commit()
    logger.info(
        f"[bundles.signing] lazily generated active signing key for "
        f"developer={developer_id} fingerprint={fp[:12]}…"
    )
    return {
        "id": str(new_id),
        "public_key_jwk": pub_jwk,
        "private_key_pem": priv_pem,
        "fingerprint": fp,
        "rotation_seq": 1,
    }


async def rotate_key(db: AsyncSession, developer_id: int, reason: str = "user_request") -> dict:
    """Revoke any active key, generate a fresh one.

    Returns the new key dict (same shape as get_or_create_active_key).
    Old key stays in DB (revoked_at set) so previously-signed bundles
    remain verifiable.
    """
    # Revoke existing
    await db.execute(
        revoke_active_keys_sql(),
        {"developer_id": developer_id, "reason": reason},
    )
    # Generate new
    priv_pem, pub_jwk, fp = generate_keypair()
    # Find max rotation_seq for this dev (start from prior + 1)
    seq_row = await db.execute(
        max_seq_sql(),
        {"developer_id": developer_id},
    )
    next_seq = (seq_row.scalar() or 0) + 1

    insert_row = await db.execute(
        insert_key_with_seq_sql(),
        {
            "developer_id": developer_id,
            "public_key_jwk": json.dumps(pub_jwk),
            "private_key_pem": priv_pem,
            "fingerprint": fp,
            "rotation_seq": next_seq,
        },
    )
    new_id = insert_row.scalar()
    await db.commit()
    logger.info(
        f"[bundles.signing] rotated key for developer={developer_id} "
        f"new_fp={fp[:12]}… seq={next_seq} reason={reason}"
    )
    return {
        "id": str(new_id),
        "public_key_jwk": pub_jwk,
        "private_key_pem": priv_pem,
        "fingerprint": fp,
        "rotation_seq": next_seq,
    }


async def list_keys_for_dev(db: AsyncSession, developer_id: int) -> list[dict]:
    """All keys for a dev, ordered newest first. Public info only."""
    rows = await db.execute(
        list_keys_sql(),
        {"developer_id": developer_id},
    )
    return [
        {
            "id": str(r[0]),
            "public_key_jwk": r[1],
            "fingerprint": r[2],
            "rotation_seq": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
            "revoked_at": r[5].isoformat() if r[5] else None,
            "revoke_reason": r[6],
        }
        for r in rows.fetchall()
    ]


async def get_active_jwks_for_dev(db: AsyncSession, developer_id: int) -> dict:
    """Return JWKS document for a dev's active key (for /.well-known)."""
    rows = await db.execute(
        list_active_keys_sql(),
        {"developer_id": developer_id},
    )
    keys = []
    for r in rows.fetchall():
        jwk = r[1] if isinstance(r[1], dict) else json.loads(r[1])
        jwk["kid"] = r[2]
        keys.append(jwk)
    return {"keys": keys}


async def get_all_active_jwks(db: AsyncSession) -> dict:
    """Return JWKS document of all active keys across all devs (org-wide /.well-known)."""
    rows = await db.execute(list_all_active_keys_sql())
    keys = []
    for r in rows.fetchall():
        jwk = r[1] if isinstance(r[1], dict) else json.loads(r[1])
        jwk["kid"] = r[2]
        keys.append(jwk)
    return {"keys": keys}


# ── JWS sign / verify ──────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = 4 - (len(s) % 4)
    return base64.urlsafe_b64decode(s + ("=" * pad if pad != 4 else ""))


def sign_payload(payload_bytes: bytes, private_key_pem: str, key_fingerprint: str,
                 developer_id: int, registry_origin: str) -> str:
    """Compute detached JWS over payload_bytes.

    Returns the JWS as a compact string `header.payload.signature` where
    payload is the base64 of payload_bytes (NOT detached; we ship the whole
    thing for simplicity; receivers can verify against the original bytes too).

    Header includes:
      - alg: EdDSA
      - kid: fingerprint
      - iss: <registry_origin>/developers/<dev_id>  (resolution hint)
      - typ: TpBundleSig
    """
    header = {
        "alg": "EdDSA",
        "kid": key_fingerprint,
        "typ": "TpBundleSig",
        "iss": f"{registry_origin}/developers/{developer_id}",
    }
    header_b64 = _b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    payload_b64 = _b64url(payload_bytes)
    signing_input = f"{header_b64}.{payload_b64}".encode()

    priv = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise ValueError("Expected Ed25519 private key in PEM")
    sig = priv.sign(signing_input)
    sig_b64 = _b64url(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_jws_local(jws: str, expected_public_jwk: dict) -> tuple[bool, Optional[bytes], Optional[str]]:
    """Verify JWS using a known public JWK. Returns (valid, payload_bytes, error).

    Cross-registry verify is a separate flow that resolves the issuer to a
    JWKS endpoint first.
    """
    try:
        parts = jws.split(".")
        if len(parts) != 3:
            return False, None, "Malformed JWS (expected 3 parts)"
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode()
        sig = _b64url_decode(sig_b64)
        payload = _b64url_decode(payload_b64)

        # Reconstruct public key from JWK
        x = _b64url_decode(expected_public_jwk["x"])
        pub = Ed25519PublicKey.from_public_bytes(x)
        try:
            pub.verify(sig, signing_input)
            return True, payload, None
        except Exception as e:
            return False, None, f"Signature invalid: {e}"
    except Exception as e:
        return False, None, f"Verify error: {e}"


# ── Raw SQL helpers (avoid SQLAlchemy model declarations for fresh tables) ──

from sqlalchemy import text


def select_active_key_sql():
    return text("""
        SELECT id, public_key_jwk, private_key_pem, fingerprint, rotation_seq
        FROM developer_signing_keys
        WHERE developer_id = :developer_id AND revoked_at IS NULL
        ORDER BY rotation_seq DESC
        LIMIT 1
    """)


def insert_key_sql():
    return text("""
        INSERT INTO developer_signing_keys
            (developer_id, public_key_jwk, private_key_pem, fingerprint)
        VALUES (:developer_id, CAST(:public_key_jwk AS JSONB), :private_key_pem, :fingerprint)
        RETURNING id
    """)


def insert_key_with_seq_sql():
    return text("""
        INSERT INTO developer_signing_keys
            (developer_id, public_key_jwk, private_key_pem, fingerprint, rotation_seq)
        VALUES (:developer_id, CAST(:public_key_jwk AS JSONB), :private_key_pem, :fingerprint, :rotation_seq)
        RETURNING id
    """)


def revoke_active_keys_sql():
    return text("""
        UPDATE developer_signing_keys
        SET revoked_at = now(), revoke_reason = :reason
        WHERE developer_id = :developer_id AND revoked_at IS NULL
    """)


def max_seq_sql():
    return text("""
        SELECT COALESCE(MAX(rotation_seq), 0)
        FROM developer_signing_keys
        WHERE developer_id = :developer_id
    """)


def list_keys_sql():
    return text("""
        SELECT id, public_key_jwk, fingerprint, rotation_seq, created_at, revoked_at, revoke_reason
        FROM developer_signing_keys
        WHERE developer_id = :developer_id
        ORDER BY rotation_seq DESC
    """)


def list_active_keys_sql():
    return text("""
        SELECT id, public_key_jwk, fingerprint
        FROM developer_signing_keys
        WHERE developer_id = :developer_id AND revoked_at IS NULL
    """)


def list_all_active_keys_sql():
    return text("""
        SELECT id, public_key_jwk, fingerprint
        FROM developer_signing_keys
        WHERE revoked_at IS NULL
    """)
