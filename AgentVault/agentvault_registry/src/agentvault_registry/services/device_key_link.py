"""§POCKETPAIR (2026-10-15): a paired phone's push device and the API key it was paired with.

POCKET FRAME's "Pair this phone" mints an API key and shows it once in a QR; the phone stores it and registers its push
device with it (POST /api/v1/devices/register, Bearer avreg_...). Before this, nothing tied the two together: removing
the phone left its key live, and revoking the key left the phone's push rows enabled. The device row now carries the
id of the key that registered it (in its prefs, under PREFS_KEY, written by the server only), and:

  - removing the device (DELETE /api/v1/devices/{id}) revokes that key, in the same transaction;
  - revoking the key (DELETE /api/v1/auth/api-keys/{id} or /api/v1/developers/me/apikeys/{id}) disables the devices
    it registered.

Rows registered with a JWT (the console's own ntfy form, web push) carry no key and are not affected. Both actions are
scoped to the caller's own developer id, so a stray id can never reach another account's key or device.
Δ-irrelevant: no money path.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PREFS_KEY = "paired_api_key_id"


def paired_key_id(prefs: Any) -> Optional[int]:
    """The key id a device row was registered with, or None (no key, or a value that is not a positive integer)."""
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except ValueError:
            return None
    if not isinstance(prefs, dict):
        return None
    v = prefs.get(PREFS_KEY)
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        return None
    try:
        k = int(v)
    except (TypeError, ValueError):
        return None
    return k if k > 0 else None


def client_prefs(prefs: Any) -> dict:
    """A client's prefs without the server-authored link (a client never names the key its device revokes)."""
    if not isinstance(prefs, dict):
        return {}
    return {k: v for k, v in prefs.items() if k != PREFS_KEY}


async def revoke_paired_key(db: AsyncSession, developer_id: int, key_id: Optional[int]) -> bool:
    """Revoke the caller's own key `key_id` if it is still active; True when this call revoked it. No commit."""
    if key_id is None:
        return False
    res = await db.execute(text(
        "UPDATE developer_api_keys SET is_active = FALSE "
        "WHERE id = :k AND developer_id = :dev AND is_active RETURNING id"
    ), {"k": int(key_id), "dev": int(developer_id)})
    return res.first() is not None


async def disable_devices_for_key(db: AsyncSession, developer_id: int, key_id: int) -> int:
    """Disable the caller's enabled push devices that key `key_id` registered; returns how many. No commit."""
    res = await db.execute(text(
        "UPDATE device_push_registrations SET enabled = FALSE "
        "WHERE developer_id = :dev AND enabled AND prefs ->> 'paired_api_key_id' = :kid RETURNING id"
    ), {"dev": int(developer_id), "kid": str(int(key_id))})
    return len(res.fetchall())
