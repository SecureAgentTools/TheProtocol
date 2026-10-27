"""WEB PUSH (2026-07-25) — the Protocol app's OWN push channel. No second app, no vendor account.

W3C Web Push: RFC 8291 (payload encryption, aes128gcm) + RFC 8292 (VAPID). This is a standard,
not a product. We generate our own P-256 application-server keypair; the browser hands us an
endpoint URL and two keys, and we POST an encrypted payload to that URL. There is no SDK, no
registration, no fee, and nothing to sign up for.

The endpoint host is chosen by the BROWSER, not by us (Chrome → Google's push service, Firefox →
Mozilla's, Safari → Apple's). That is unavoidable for any web push on any site and costs nothing;
we hold no account with any of them and can be pointed anywhere the standard allows.

Key persistence deliberately reuses the EXISTING `registry_signing_keys` table under its own
purpose prefix — same pattern as the card keystore and the OAuth federation keystore, so the
VAPID key inherits encryption at rest and rotation without inventing a third key home.

Honest limits: iOS requires the PWA be installed to the Home Screen (Safari 16.4+); a force-killed
browser or aggressive battery policy can still drop delivery. ntfy remains available as the
stubborn-foreground-service alternative for anyone who wants it.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from .registry_card_keystore import _decrypt_pem, _encrypt_pem

logger = logging.getLogger(__name__)

ALGORITHM = "ES256"
_PURPOSE = "webpush-vapid:self"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _generate() -> Tuple[str, Dict[str, Any]]:
    """A P-256 application-server key. The public half is published to the browser as the raw
    uncompressed point (what `applicationServerKey` expects), plus a JWK for our own records."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    nums = priv.public_key().public_numbers()
    raw_point = b"\x04" + nums.x.to_bytes(32, "big") + nums.y.to_bytes(32, "big")
    public_jwk = {
        "kty": "EC", "crv": "P-256", "alg": ALGORITHM, "use": "sig",
        "x": _b64u(nums.x.to_bytes(32, "big")),
        "y": _b64u(nums.y.to_bytes(32, "big")),
        # what the frontend passes to pushManager.subscribe()
        "application_server_key": _b64u(raw_point),
    }
    return pem, public_jwk


async def get_or_mint_key(db: AsyncSession) -> models.RegistrySigningKey:
    """Current VAPID key, minted on first use so a registry that has never pushed still answers."""
    stmt = (
        select(models.RegistrySigningKey)
        .where(
            models.RegistrySigningKey.registry_spiffe_id == _PURPOSE,
            models.RegistrySigningKey.expires_at.is_(None),
        )
        .order_by(models.RegistrySigningKey.rotation_seq.desc())
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    pem, public_jwk = _generate()
    row = models.RegistrySigningKey(
        registry_spiffe_id=_PURPOSE,
        rotation_seq=1,
        public_jwk=public_jwk,
        private_pem_encrypted=_encrypt_pem(pem),
        algorithm=ALGORITHM,
        expires_at=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("[WebPush] minted VAPID key")
    return row


async def public_application_server_key(db: AsyncSession) -> str:
    row = await get_or_mint_key(db)
    return (row.public_jwk or {}).get("application_server_key", "")


def _vapid_private_pem(row: models.RegistrySigningKey) -> str:
    return _decrypt_pem(row.private_pem_encrypted)


def vapid_private_raw(row: models.RegistrySigningKey) -> str:
    """The private scalar as url-safe base64 — the ONE format py_vapid parses unambiguously.

    We store a PKCS8 PEM ("BEGIN PRIVATE KEY"); py_vapid's PEM path expects SEC1
    ("BEGIN EC PRIVATE KEY") and falls through to a DER parse that fails with "header too long".
    Handing it the raw 32-byte scalar sidesteps the format guessing entirely.
    """
    priv = serialization.load_pem_private_key(_decrypt_pem(row.private_pem_encrypted).encode(), password=None)
    return _b64u(priv.private_numbers().private_value.to_bytes(32, "big"))


def send_webpush(*, endpoint: str, p256dh: str, auth: str, payload: Dict[str, Any],
                 vapid_key: str, subject: str, ttl: int = 120) -> Tuple[bool, Optional[int]]:
    """Encrypt + deliver one notification. Returns (ok, http_status).

    A 404/410 means the browser has permanently discarded that subscription — the caller should
    prune the row rather than retry it forever.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:  # pragma: no cover - dependency is pinned in the image
        logger.warning("[WebPush] pywebpush not installed — web push disabled")
        return False, None
    try:
        webpush(
            subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            data=json.dumps(payload),
            vapid_private_key=vapid_key,
            vapid_claims={"sub": subject},
            ttl=ttl,
        )
        return True, 201
    except WebPushException as exc:  # noqa: BLE001 — per-device best effort
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            logger.info("[WebPush] subscription gone (%s) — prune endpoint", status)
        else:
            logger.warning("[WebPush] send failed status=%s: %s", status, exc)
        return False, status
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WebPush] send error: %s", exc)
        return False, None
