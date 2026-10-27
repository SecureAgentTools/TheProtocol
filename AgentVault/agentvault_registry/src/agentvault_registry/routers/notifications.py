"""§NOTIFV2 — notification catalog + per-developer preference matrix API.

Three endpoints, one contract: the SETTINGS UI is driven entirely by the catalog, so adding a
notification type to `services/notification_catalog.py` makes it appear here — and therefore in
the panel — with zero frontend work. That property is the whole point.

  GET /api/v1/notifications/catalog          the audience-filtered catalog (static per build)
  GET /api/v1/notifications/prefs/effective  catalog ⊕ wildcard ⊕ rows ⊕ legacy = the matrix
  PUT /api/v1/notifications/prefs            bulk sparse upsert (per-row; NEVER a blob RMW)

Writes are per-row upserts keyed on (developer, type, channel): two devices saving at once
interleave safely instead of last-write-wins-ing each other's whole blob.

Mandatory types (security.login_approval, security.liability_challenge, …) are not writable —
the resolver would ignore the row anyway, but refusing the write keeps the UI honest.
legacy_managed types (broadcast.*, cicd.*) are not writable HERE — their toggles still live on
the pre-v2 store (PATCH /developers/me/notification-prefs) so broadcast delivery keeps working
untouched; the panel simply renders both stores as one surface.
"""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.config import settings
from agentvault_registry.database import get_db
from agentvault_registry.services.notification_catalog import (
    CATEGORIES, CHANNELS, catalog_for_audience, get_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])

_WRITABLE_CHANNELS = set(CHANNELS)


def _type_public(t) -> dict:
    return {
        "key": t.key,
        "category": t.category,
        "severity": t.severity,
        "mandatory": t.mandatory,
        "audience": t.audience,
        "legacy_managed": t.legacy_managed,
        "emitter": t.emitter,
        "threshold_kind": t.threshold_kind,
        "threshold_default": t.threshold_default,
        "coalesce_window_s": t.coalesce_window_s,
        "default_enabled": {c: bool(t.default_enabled.get(c, False)) for c in CHANNELS},
        "label_key": t.label_key,
        "desc_key": t.desc_key,
    }


@router.get("/catalog", summary="The notification type catalog (filtered to your audience)")
async def get_catalog(
    current_dev: models.Developer = Depends(security.get_current_developer),
):
    types = catalog_for_audience(
        is_operator=bool(getattr(current_dev, "is_federation_operator", False)),
        is_admin=security.admin_credential(current_dev),   # D6-821: admin kinds follow the credential
    )
    return {
        "mode": str(getattr(settings, "NOTIFY_V2_MODE", "off")),
        "channels": list(CHANNELS),
        "categories": list(CATEGORIES),
        "types": [_type_public(t) for t in types],
    }


# Legacy keys the panel still needs, surfaced verbatim so it binds ONE response.
_LEGACY_KEYS = (
    "mute_info", "mute_warning", "mute_maintenance",
    "delivery_in_app", "delivery_email",
    "quiet_hours_start", "quiet_hours_end",
    "mute_cicd_my_agents", "mute_cicd_org_agents",
)

_LEGACY_TYPE_TO_MUTE = {
    "broadcast.info": "mute_info",
    "broadcast.warning": "mute_warning",
    "broadcast.maintenance": "mute_maintenance",
}


@router.get("/prefs/effective",
            summary="The developer's full effective notification matrix")
async def get_effective_prefs(
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Developer-level effective state (device narrowing intentionally NOT applied here:
    the panel is the developer's intent; the phone can only narrow it further)."""
    types = catalog_for_audience(
        is_operator=bool(getattr(current_dev, "is_federation_operator", False)),
        is_admin=security.admin_credential(current_dev),   # D6-821: admin kinds follow the credential
    )
    rows = (await db.execute(text(
        "SELECT type_key, channel, enabled, threshold_num "
        "FROM developer_notification_prefs WHERE developer_id = :d"),
        {"d": current_dev.id})).all()
    by_pair: Dict[tuple, tuple] = {
        (r.type_key, r.channel): (bool(r.enabled), r.threshold_num) for r in rows
    }
    legacy = current_dev.notification_prefs or {}

    out_types: List[dict] = []
    for t in types:
        eff: Dict[str, dict] = {}
        for ch in CHANNELS:
            if t.mandatory:
                eff[ch] = {"enabled": bool(t.default_enabled.get(ch, False) or ch in ("push_desktop", "push_mobile")),
                           "source": "mandatory", "threshold": None}
                continue
            if t.legacy_managed:
                mute_key = _LEGACY_TYPE_TO_MUTE.get(t.key)
                if mute_key is not None and ch in ("inapp", "email"):
                    ch_master = legacy.get("delivery_in_app" if ch == "inapp" else "delivery_email", True)
                    enabled = bool(ch_master) and not bool(legacy.get(mute_key, False))
                elif t.key.startswith("cicd."):
                    enabled = not bool(legacy.get("mute_cicd_my_agents", False)) if ch == "inapp" \
                        else bool(t.default_enabled.get(ch, False))
                else:
                    enabled = bool(t.default_enabled.get(ch, False))
                eff[ch] = {"enabled": enabled, "source": "legacy", "threshold": None}
                continue
            pair = by_pair.get((t.key, ch))
            if pair is not None:
                eff[ch] = {"enabled": pair[0], "source": "row",
                           "threshold": pair[1] if pair[1] is not None else t.threshold_default}
                continue
            wc = by_pair.get(("*", ch))
            if wc is not None:
                eff[ch] = {"enabled": wc[0], "source": "wildcard", "threshold": t.threshold_default}
                continue
            eff[ch] = {"enabled": bool(t.default_enabled.get(ch, False)),
                       "source": "default", "threshold": t.threshold_default}
        d = _type_public(t)
        d["effective"] = eff
        out_types.append(d)

    return {
        "mode": str(getattr(settings, "NOTIFY_V2_MODE", "off")),
        "channels": list(CHANNELS),
        "categories": list(CATEGORIES),
        "types": out_types,
        "wildcard": {ch: (by_pair.get(("*", ch))[0] if ("*", ch) in by_pair else None)
                     for ch in CHANNELS},
        "legacy": {k: legacy.get(k) for k in _LEGACY_KEYS},
    }


class PrefRowIn(BaseModel):
    type_key: str = Field(max_length=80)
    channel: str = Field(max_length=16)
    enabled: Optional[bool] = None
    threshold_num: Optional[float] = Field(default=None, ge=0)
    reset: bool = False  # True → delete the row (back to catalog default)


class PrefsPutIn(BaseModel):
    rows: List[PrefRowIn] = Field(max_length=400)


@router.put("/prefs", summary="Bulk sparse upsert of notification preferences")
async def put_prefs(
    payload: PrefsPutIn,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    is_op = bool(getattr(current_dev, "is_federation_operator", False))
    is_admin = security.admin_credential(current_dev)   # D6-821: admin kinds follow the credential
    applied = deleted = 0
    for r in payload.rows:
        if r.channel not in _WRITABLE_CHANNELS:
            raise HTTPException(status_code=422, detail=f"unknown channel {r.channel!r}")
        if r.type_key != "*":
            entry = get_type(r.type_key)
            if entry is None or entry.key != r.type_key:
                raise HTTPException(status_code=422, detail=f"unknown type {r.type_key!r}")
            if entry.mandatory:
                raise HTTPException(status_code=422,
                                    detail=f"{r.type_key} is mandatory and cannot be changed")
            if entry.legacy_managed:
                raise HTTPException(status_code=422,
                                    detail=f"{r.type_key} is managed via /developers/me/notification-prefs")
            if entry.audience == "operator" and not (is_op or is_admin):
                raise HTTPException(status_code=403, detail="operator-audience type")
            if entry.audience == "admin" and not is_admin:
                raise HTTPException(status_code=403, detail="admin-audience type")
            if r.threshold_num is not None and entry.threshold_kind == "none":
                raise HTTPException(status_code=422,
                                    detail=f"{r.type_key} does not take a threshold")
        if r.reset:
            res = await db.execute(text(
                "DELETE FROM developer_notification_prefs "
                "WHERE developer_id=:d AND type_key=:k AND channel=:c"),
                {"d": current_dev.id, "k": r.type_key, "c": r.channel})
            deleted += res.rowcount or 0
            continue
        if r.enabled is None:
            raise HTTPException(status_code=422,
                                detail="row needs enabled=<bool> or reset=true")
        await db.execute(text("""
            INSERT INTO developer_notification_prefs
                (developer_id, type_key, channel, enabled, threshold_num, updated_at)
            VALUES (:d, :k, :c, :e, :t, now())
            ON CONFLICT (developer_id, type_key, channel)
            DO UPDATE SET enabled = EXCLUDED.enabled,
                          threshold_num = EXCLUDED.threshold_num,
                          updated_at = now()
        """), {"d": current_dev.id, "k": r.type_key, "c": r.channel,
               "e": r.enabled, "t": r.threshold_num})
        applied += 1
    await db.commit()
    return {"applied": applied, "deleted": deleted}


@router.get("/unread-count", summary="The notification feed's unread count, on its own")
async def get_notification_unread_count(
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    The number the notification badge shows, without the feed itself. It counts the feed only, not the broadcasts:
    the badge sits on the feed, so a merged number would disagree with the list it sits on.

    \f
    The number the bell/Protocol-row badge shows, without shipping the feed.

    🔴 WHY THIS EXISTS AT ALL (measured 2026-08-30): the Pocket/desktop OurChat
    list has called `/notifications/unread-count` since §OURSTATE-1 and nothing
    ever answered it. `admin_broadcast` owns `/notifications/{broadcast_id}`
    (int) and FastAPI matches in REGISTRATION order, so the call fell through to
    that route and returned **422 "unable to parse string as an integer"** on
    every mount — behind `if (r.ok)`, so the badge silently stayed 0 forever and
    only the console knew. Same class as the §NOTIFV2 `/catalog` trap; the cure
    is the same: this router is included BEFORE admin_broadcast (main.py), so a
    literal declared HERE wins.

    Deliberately the FEED count only, not feed+broadcasts: the caller badges the
    Protocol row, which IS the feed. Merging the two stores behind one number
    would make the badge disagree with the list it sits on.
    """
    try:
        unread = int((await db.execute(text(
            "SELECT COUNT(*) FROM notification_feed WHERE developer_id = :d AND read_at IS NULL"
        ), {"d": current_dev.id})).scalar() or 0)
    except Exception as exc:  # noqa: BLE001 — table absent on an un-migrated node
        logger.warning("[NOTIFY-UNREAD] read failed: %s", exc)
        return {"available": False, "count": 0, "unread_count": 0}
    # `count` is what the caller reads; `unread_count` matches /feed's key so the
    # two endpoints can never be read as different quantities.
    return {"available": True, "count": unread, "unread_count": unread}


@router.get("/feed", summary="The in-app notification feed")
async def get_notification_feed(
    limit: int = 50,
    unread_only: bool = False,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """The in-app rail for NON-broadcast types.

    Deliberately separate from `/notifications/unread` (admin broadcasts): that endpoint is
    broadcast-shaped (org targeting, 90-day horizon, is_active) and this one is per-developer
    delivery. The bell shows both; merging them server-side would force one set of semantics
    onto the other.
    """
    limit = max(1, min(int(limit or 50), 200))
    where = ["developer_id = :d"] + (["read_at IS NULL"] if unread_only else [])
    try:
        rows = (await db.execute(text(f"""
            SELECT id, type_key, category, severity, title, body, click, created_at, read_at
            FROM notification_feed
            WHERE {' AND '.join(where)}
            ORDER BY id DESC
            LIMIT :lim
        """), {"d": current_dev.id, "lim": limit})).mappings().all()
        unread = int((await db.execute(text(
            "SELECT COUNT(*) FROM notification_feed WHERE developer_id = :d AND read_at IS NULL"
        ), {"d": current_dev.id})).scalar() or 0)
    except Exception as exc:  # noqa: BLE001 — table absent on a node that has not migrated yet
        logger.warning("[NOTIFY-FEED] read failed: %s", exc)
        return {"available": False, "entries": [], "unread_count": 0}

    return {
        "available": True,
        "unread_count": unread,
        "entries": [
            {"id": r["id"], "type_key": r["type_key"], "category": r["category"],
             "severity": r["severity"], "title": r["title"], "body": r["body"],
             "click": r["click"],
             "created_at": r["created_at"].isoformat() if r["created_at"] else None,
             "read": r["read_at"] is not None}
            for r in rows
        ],
    }


@router.post("/feed/{entry_id}/read", summary="Mark one feed entry read")
async def mark_feed_entry_read(
    entry_id: int,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    # developer_id in the WHERE is the authorization: you can only ever mark your own.
    res = await db.execute(text(
        "UPDATE notification_feed SET read_at = now() "
        "WHERE id = :i AND developer_id = :d AND read_at IS NULL"
    ), {"i": entry_id, "d": current_dev.id})
    await db.commit()
    return {"ok": True, "updated": res.rowcount or 0}


@router.post("/feed/read-all", summary="Mark the whole feed read")
async def mark_feed_all_read(
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(text(
        "UPDATE notification_feed SET read_at = now() "
        "WHERE developer_id = :d AND read_at IS NULL"
    ), {"d": current_dev.id})
    await db.commit()
    return {"ok": True, "updated": res.rowcount or 0}


_HISTORY_OUTCOMES = ("delivered", "failed", "suppressed")


@router.get("/history", summary="Per-decision notification history")
async def get_notification_history(
    limit: int = 50,
    before_id: Optional[int] = None,
    outcome: Optional[str] = None,
    type_key: Optional[str] = None,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Own-history only: every row is scoped to the authenticated developer.

    The `summary` block is the reason this endpoint exists. A list answers "what happened";
    the 24h breakdown by reason answers "why am I not getting these", which is the actual
    question when a deliberately-quiet notification system looks broken.
    """
    limit = max(1, min(int(limit or 50), 200))
    if outcome is not None and outcome not in _HISTORY_OUTCOMES:
        raise HTTPException(status_code=422, detail=f"outcome must be one of {_HISTORY_OUTCOMES}")

    where = ["developer_id = :d"]
    params: Dict[str, object] = {"d": current_dev.id, "lim": limit}
    if before_id:
        where.append("id < :bid")
        params["bid"] = int(before_id)
    if outcome:
        where.append("outcome = :o")
        params["o"] = outcome
    if type_key:
        where.append("type_key = :tk")
        params["tk"] = type_key[:80]

    try:
        rows = (await db.execute(text(f"""
            SELECT id, type_key, category, severity, channel, outcome, reason, mode,
                   device_id, title, message, created_at
            FROM notification_log
            WHERE {' AND '.join(where)}
            ORDER BY id DESC
            LIMIT :lim
        """), params)).mappings().all()

        # Window summary is deliberately INDEPENDENT of the filters above: it must keep
        # telling the truth about the last 24h even while you are staring at one filtered slice.
        summary = (await db.execute(text("""
            SELECT outcome, COALESCE(reason, '') AS reason, COUNT(*) AS n
            FROM notification_log
            WHERE developer_id = :d AND created_at > now() - interval '24 hours'
            GROUP BY 1, 2
            ORDER BY n DESC
        """), {"d": current_dev.id})).mappings().all()
    except Exception as exc:  # noqa: BLE001 — table absent on a node that has not migrated yet
        logger.warning("[NOTIFY-LOG] history read failed: %s", exc)
        return {"enabled": False, "entries": [], "summary": [], "totals": {},
                "note": "notification history unavailable on this registry"}

    totals: Dict[str, int] = {}
    for s in summary:
        totals[s["outcome"]] = totals.get(s["outcome"], 0) + int(s["n"])

    # notify() returns at `if not rows` BEFORE the per-device loop, so a developer with no
    # registered device produces NO history rows at all. Without this count an empty list is
    # ambiguous between "nothing was raised" and "everything was raised and had nowhere to go".
    try:
        device_count = int((await db.execute(text(
            "SELECT COUNT(*) FROM device_push_registrations WHERE enabled AND developer_id = :d"
        ), {"d": current_dev.id})).scalar() or 0)
    except Exception:  # noqa: BLE001
        device_count = -1  # unknown beats a confident zero

    return {
        "enabled": bool(getattr(settings, "NOTIFICATION_LOG_ENABLED", True)),
        "device_count": device_count,
        "mode": str(getattr(settings, "NOTIFY_V2_MODE", "off")),
        "retention_days": int(getattr(settings, "NOTIFICATION_LOG_RETENTION_DAYS", 14)),
        "entries": [
            {
                "id": r["id"], "type_key": r["type_key"], "category": r["category"],
                "severity": r["severity"], "channel": r["channel"], "outcome": r["outcome"],
                "reason": r["reason"], "mode": r["mode"], "device_id": r["device_id"],
                "title": r["title"], "message": r["message"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "summary": [
            {"outcome": s["outcome"], "reason": s["reason"] or None, "count": int(s["n"])}
            for s in summary
        ],
        "totals": totals,
    }
