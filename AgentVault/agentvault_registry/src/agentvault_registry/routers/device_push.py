"""POCKET FRAME — device push registration (f-mobile, 2026-07-07).

Developers register a push target per device so the push_notify reactors can
fan sensitive events (IRONKEY delegation/capability activity) out to their
phone. Rails: 'ntfy' (live — self-hosted, sovereign), 'fcm'/'apns' (stubs until
credentials exist; registrations accepted so devices can enroll early).

Δ-irrelevant: pure read-side notification plumbing — no money path.
Auth: developer JWT (same tier as webhooks). Endpoints:

    POST   /api/v1/devices/register     — upsert a device registration
    GET    /api/v1/devices/mine         — list my registrations
    DELETE /api/v1/devices/{device_id}  — remove one of mine
"""
import logging
import re
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, schemas
from agentvault_registry.config import settings
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_developer, presented_api_key_id
from agentvault_registry.services.device_key_link import (
    PREFS_KEY, client_prefs, paired_key_id, revoke_paired_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["Device Push"])

_ALLOWED_RAILS = ("ntfy", "fcm", "apns", "webpush")
_ALLOWED_PLATFORMS = ("android", "ios", "web")
# ntfy topics ride in a URL path segment — keep them boring.
_NTFY_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


@router.get("/config", summary="Public Pocket push config (ntfy public base for pairing)")
async def push_config():
    """Public (no auth): the Pocket FE reads this to build the device-subscribe
    QR / ntfy deep-link. Returns THIS frame's PUBLIC ntfy base, empty when the
    frame is not publicly exposed, so the FE degrades gracefully. Non-sensitive
    (a public hostname); Δ-irrelevant."""
    return {
        "ntfy_public_url": settings.PUSH_NTFY_PUBLIC_URL or "",
        "notify_enabled": settings.PUSH_NOTIFY_ENABLED,
    }


@router.get("/webpush/key", summary="Public VAPID application-server key")
async def webpush_key(db: AsyncSession = Depends(get_db)):
    """Public (no auth): the key the browser needs for pushManager.subscribe(). Created on first
    ask, so a registry that has never pushed still answers. Public by definition: it is the
    'application server key' every subscriber must know."""
    from agentvault_registry.services import webpush as _wp
    return {"application_server_key": await _wp.public_application_server_key(db),
            "enabled": settings.PUSH_NOTIFY_ENABLED}


class WebPushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=12, max_length=2000)
    keys: Dict[str, str]
    label: Optional[str] = Field(default=None, max_length=120)


@router.post("/webpush/subscribe", summary="Subscribe this browser/PWA for push")
async def webpush_subscribe(body: WebPushSubscribeIn,
                            dev: models.Developer = Depends(get_current_developer),
                            db: AsyncSession = Depends(get_db)):
    """Store a browser Web Push subscription as a device row (rail='webpush').

    Idempotent on the endpoint: browsers hand back the SAME endpoint for the same subscription,
    so re-subscribing refreshes the keys instead of accumulating duplicate rows.
    """
    p256dh = (body.keys or {}).get("p256dh")
    auth = (body.keys or {}).get("auth")
    if not p256dh or not auth:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="keys.p256dh and keys.auth are required")
    row = (await db.execute(text(
        "SELECT id FROM device_push_registrations WHERE developer_id=:d AND rail='webpush' AND target=:t"
    ), {"d": dev.id, "t": body.endpoint})).first()
    if row:
        await db.execute(text(
            "UPDATE device_push_registrations SET p256dh=:p, auth=:a, enabled=true, "
            "last_seen_at=now(), label=COALESCE(:l, label) WHERE id=:i"
        ), {"p": p256dh, "a": auth, "l": body.label, "i": row[0]})
        dev_id = row[0]
    else:
        res = await db.execute(text(
            "INSERT INTO device_push_registrations (developer_id, platform, rail, target, label, "
            "enabled, p256dh, auth) VALUES (:d, 'web', 'webpush', :t, :l, true, :p, :a) RETURNING id"
        ), {"d": dev.id, "t": body.endpoint, "l": body.label or "This device", "p": p256dh, "a": auth})
        dev_id = res.scalar()
    await db.commit()
    return {"ok": True, "id": dev_id, "rail": "webpush"}


@router.post("/webpush/unsubscribe", summary="Drop this browser's push subscription")
async def webpush_unsubscribe(body: WebPushSubscribeIn,
                              dev: models.Developer = Depends(get_current_developer),
                              db: AsyncSession = Depends(get_db)):
    await db.execute(text(
        "DELETE FROM device_push_registrations WHERE developer_id=:d AND rail='webpush' AND target=:t"
    ), {"d": dev.id, "t": body.endpoint})
    await db.commit()
    return {"ok": True}


@router.post("/register", summary="Register (or refresh) a push device")
async def register_device(
    body: schemas.DevicePushRegisterIn,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    rail = body.rail.lower().strip()
    platform = body.platform.lower().strip()
    target = body.target.strip()
    if rail not in _ALLOWED_RAILS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"rail must be one of {_ALLOWED_RAILS}")
    if platform not in _ALLOWED_PLATFORMS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"platform must be one of {_ALLOWED_PLATFORMS}")
    if not target:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="target is required")
    if rail == "ntfy" and not _NTFY_TOPIC_RE.match(target):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ntfy target must be a topic matching [A-Za-z0-9_-]{3,64}",
        )

    # §POCKETPAIR (2026-10-15): a phone registers with the key it was paired with; record that key's id (server-written,
    # never the client's) so removing the device revokes the key and revoking the key disables the device. A JWT
    # registration (the console's own form) records none. Re-registering under another key moves the link to it.
    kid = presented_api_key_id()
    prefs = client_prefs(body.prefs)
    if kid is not None:
        prefs[PREFS_KEY] = int(kid)
    row = (await db.execute(text("""
        INSERT INTO device_push_registrations (developer_id, platform, rail, target, label, enabled, prefs)
        VALUES (:dev, :plat, :rail, :tgt, :label, TRUE, CAST(:prefs AS JSONB))
        ON CONFLICT (developer_id, rail, target) DO UPDATE SET
            platform = EXCLUDED.platform,
            label = COALESCE(EXCLUDED.label, device_push_registrations.label),
            enabled = TRUE,
            last_seen_at = now(),
            prefs = CASE WHEN CAST(:kid AS INTEGER) IS NULL THEN device_push_registrations.prefs
                         ELSE jsonb_set(COALESCE(device_push_registrations.prefs, '{}'::jsonb), '{paired_api_key_id}',
                                        to_jsonb(CAST(:kid AS INTEGER))) END
        RETURNING id, created_at, last_seen_at
    """), {
        "dev": current.id, "plat": platform, "rail": rail, "tgt": target,
        "label": body.label,
        "prefs": __import__("json").dumps(prefs),
        "kid": int(kid) if kid is not None else None,
    })).first()
    await db.commit()
    logger.info("[DEVICE-PUSH] register dev=%s rail=%s platform=%s id=%s", current.id, rail, platform, row.id)
    # §NOTIFV2 — security.device_enrolled: tell the account's OTHER devices a new one joined.
    # Post-commit; the freshly-registered device itself will also receive it, which is fine —
    # "this phone was just added" is a legitimate confirmation on the phone that was added.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify
        _aio.create_task(notify(
            "security.device_enrolled", [current.id],
            title="New push device registered",
            message=f"{platform}/{rail}: {body.label or target[:24]}",
            tags="iphone", priority="high", click="/ui/#/settings"))
    except Exception:  # noqa: BLE001
        logger.debug("[DEVICE-PUSH] enrolled notify skipped", exc_info=True)
    return {"id": row.id, "rail": rail, "platform": platform, "target": target,
            "label": body.label, "enabled": True, "paired_key": kid is not None}


@router.get("/mine", summary="List my push device registrations")
async def list_my_devices(
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT d.id, d.platform, d.rail, d.target, d.label, d.enabled, d.created_at, d.last_seen_at,
               -- A revoked key is NOT enrolled. Reporting it as enrolled made the UI offer a
               -- fingerprint button for a credential the server would refuse.
               (d.webauthn_credential_id IS NOT NULL AND d.key_revoked_at IS NULL) AS webauthn_enrolled,
               d.webauthn_credential_id, d.key_revoked_at,
               -- §POCKETPAIR: the device was registered with a paired API key; removing it revokes that key.
               (d.prefs ->> 'paired_api_key_id') IS NOT NULL AS paired_key,
               COALESCE(k.is_active, FALSE) AS paired_key_active
        FROM device_push_registrations d
        LEFT JOIN developer_api_keys k
               ON k.developer_id = d.developer_id
              AND CAST(k.id AS TEXT) = (d.prefs ->> 'paired_api_key_id')
        WHERE d.developer_id = :dev ORDER BY d.id
    """), {"dev": current.id})).mappings().all()
    return {"devices": [dict(r) for r in rows], "total": len(rows)}


@router.delete("/{device_id}", summary="Remove one of my push devices")
async def unregister_device(
    device_id: int,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(text(
        "DELETE FROM device_push_registrations WHERE id = :i AND developer_id = :dev RETURNING id, prefs"
    ), {"i": device_id, "dev": current.id})
    row = res.first()
    if not row:
        await db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Device not found (or not yours)")
    # §POCKETPAIR (2026-10-15): a phone paired by POCKET FRAME registered with its own key; removing the phone revokes
    # that key in the same transaction, so a lost or retired phone stops being a credential the moment it is removed.
    revoked = await revoke_paired_key(db, current.id, paired_key_id(row.prefs))
    await db.commit()
    logger.info("[DEVICE-PUSH] unregister dev=%s id=%s paired_key_revoked=%s", current.id, device_id, revoked)
    return {"ok": True, "id": device_id, "paired_key_revoked": revoked}
