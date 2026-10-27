"""NOTIFICATION PREFERENCES — resolution + rate control for the v2 send path (§NOTIFV2).

The resolution order is a contract. It is documented here, unit-tested case by case, and must
never be reordered casually — step 7's "narrow, never widen" is what makes a stale phone unable
to re-enable something the developer switched off, and step 1's short-circuit is what makes
`mandatory` a security boundary instead of a suggestion.

    1. audience gate            (operator/admin types never reach plain developers)
    2. MANDATORY                → send. Skips prefs, mutes, thresholds, quiet hours, coalescing.
    3. explicit row             (developer_id, type_key, channel)
    4. wildcard row             (developer_id, '*', channel)   — the channel master switch
    5. no v2 rows → LEGACY SIGNALS AS ENABLERS (no-regression rule: the phone-configured
       allowlist / min_transfer_avt must keep WORKING, not merely narrowing, until the
       developer writes v2 rows — otherwise flipping the mode silently kills opt-ins)
    6. catalog default_enabled[channel]
    then, only if still sending:
    7. device narrowing         (allowlist may drop; min_transfer may RAISE the threshold)
    8. amount threshold
    9. quiet hours              (push channels only; UTC with midnight wrap — the EXACT
                                 semantics of routers/websocket.py so the two gates can never
                                 disagree about what "22 to 6" means)
   10. coalescing               (leading-edge send + suppression window + carried count;
                                 the COUNT lives in its OWN key with a LONGER TTL than the
                                 window — §STREAKFIX: a counter packed into the key whose
                                 expiry triggers the next event always reads zero)

This module never raises into a caller and never imports push_notify (push_notify imports us).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy import text

from agentvault_registry.database import AsyncSessionLocal
from agentvault_registry.services.notification_catalog import (
    NotificationType, PUSH_CHANNELS, get_type,
)

logger = logging.getLogger(__name__)

RAIL_TO_CHANNEL = {
    "ntfy": "push_mobile", "fcm": "push_mobile", "apns": "push_mobile",
    "webpush": "push_desktop",
    # rail='local' is a desktop WebAuthn SIGNING row, not a push target — no channel.
}

_COALESCE_SUPPRESS = "registry:notify:coalesce:"     # value "1", TTL = window
_COALESCE_COUNT = "registry:notify:coalesce_count:"  # OWN key, TTL = max(4*window, 900)


@dataclass
class DevCtx:
    dev_id: int
    notification_prefs: dict = field(default_factory=dict)
    is_admin: bool = False
    is_operator: bool = False
    # (type_key_or_star, channel) -> (enabled, threshold_num)
    rows: Dict[Tuple[str, str], Tuple[bool, Optional[float]]] = field(default_factory=dict)


async def load_context(dev_ids: Iterable[int], type_key: str) -> Dict[int, DevCtx]:
    """One pass: developer meta + the v2 rows relevant to THIS type (explicit + wildcard).
    Never raises — an empty context resolves to catalog defaults, which is the safe answer."""
    ids = [d for d in {d for d in dev_ids if d is not None}]
    out: Dict[int, DevCtx] = {i: DevCtx(dev_id=i) for i in ids}
    if not ids:
        return out
    try:
        async with AsyncSessionLocal() as db:
            devs = (await db.execute(text(
                "SELECT id, notification_prefs, is_admin, is_federation_operator "
                "FROM developers WHERE id = ANY(:ids)"), {"ids": ids})).all()
            for r in devs:
                c = out[r.id]
                c.notification_prefs = r.notification_prefs or {}
                c.is_admin = bool(r.is_admin)
                c.is_operator = bool(r.is_federation_operator)
            rows = (await db.execute(text(
                "SELECT developer_id, type_key, channel, enabled, threshold_num "
                "FROM developer_notification_prefs "
                "WHERE developer_id = ANY(:ids) AND type_key IN (:k, '*')"),
                {"ids": ids, "k": type_key})).all()
            for r in rows:
                out[r.developer_id].rows[(r.type_key, r.channel)] = (
                    bool(r.enabled), float(r.threshold_num) if r.threshold_num is not None else None,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NOTIFY-PREFS] context load failed (defaults apply): %s", exc)
    return out


def _in_quiet_hours(prefs: dict, now_hour: Optional[int] = None) -> bool:
    """EXACT mirror of routers/websocket.py: UTC hours, window crosses midnight if start > end."""
    qh_start = prefs.get("quiet_hours_start")
    qh_end = prefs.get("quiet_hours_end")
    if qh_start is None or qh_end is None:
        return False
    try:
        qh_start = int(qh_start)
        qh_end = int(qh_end)
        nh = datetime.now(timezone.utc).hour if now_hour is None else now_hour
        return (qh_start <= nh < qh_end) if qh_start < qh_end else (nh >= qh_start or nh < qh_end)
    except Exception:  # noqa: BLE001
        return False


def _device_allowlist_hit(device_prefs: dict, entry: NotificationType) -> Optional[bool]:
    """None = device has no allowlist. True/False = allowlist present and (does/not) name this
    type — under EITHER spelling, because phones historically stored the CamelCase ES names."""
    allow = (device_prefs or {}).get("event_types")
    if allow is None:
        return None
    names = {entry.key, *entry.es_event_types}
    return any(a in names for a in allow)


def decide(
    entry: NotificationType,
    channel: str,
    *,
    ctx: DevCtx,
    device_prefs: Optional[dict],
    amount: Optional[float],
    now_hour: Optional[int] = None,
) -> Tuple[bool, str, Optional[float]]:
    """Pure verdict for one (developer, device-channel). Returns (send, reason, threshold_used).
    Reasons are the metric label set — keep them SMALL and FIXED (log_metrics doctrine)."""
    device_prefs = device_prefs or {}

    # 1 — audience
    if entry.audience == "operator" and not (ctx.is_operator or ctx.is_admin):
        return False, "audience", None
    if entry.audience == "admin" and not ctx.is_admin:
        return False, "audience", None

    # 2 — mandatory short-circuits EVERYTHING below (security boundary)
    if entry.mandatory:
        return True, "mandatory", None

    base: Optional[bool] = None
    reason = ""
    threshold: Optional[float] = entry.threshold_default
    have_v2_row = False

    # 3 — explicit row
    row = ctx.rows.get((entry.key, channel))
    if row is not None:
        have_v2_row = True
        base, row_thr = row
        reason = "row"
        if row_thr is not None:
            threshold = row_thr
    else:
        # 4 — wildcard channel master
        wc = ctx.rows.get(("*", channel))
        if wc is not None:
            have_v2_row = True
            base = wc[0]
            reason = "wildcard"

    if base is None:
        # 5 — legacy signals as ENABLERS (only when the developer has expressed nothing in v2)
        if entry.key == "money.received":
            raw = device_prefs.get("min_transfer_avt")
            if raw is not None:
                try:
                    return_thr = float(raw)
                except (TypeError, ValueError):
                    return False, "threshold", None
                if amount is None or float(amount) < return_thr:
                    return False, "threshold", return_thr
                if channel in PUSH_CHANNELS and _in_quiet_hours(ctx.notification_prefs, now_hour):
                    return False, "quiet", return_thr
                return True, "legacy_enable", return_thr
        # §9 (2026-07-27) — broadcast + cicd legacy signals. These 6 types left `legacy_managed`
        # when inapp/email became real rails, but the pre-v2 keys are STILL the surface a
        # developer edits (the Settings basics strip writes `delivery_*` / `mute_*`, and
        # websocket.py's live in-app gate reads them). Honouring them here is what keeps the two
        # from diverging: an explicit v2 row still wins (we only reach this branch when there is
        # none), so mig 0140's backfill and any future v2 write both take precedence.
        lp = ctx.notification_prefs or {}
        if entry.key.startswith("broadcast.") and channel in ("inapp", "email"):
            master = lp.get("delivery_in_app" if channel == "inapp" else "delivery_email", True)
            severity_key = "mute_" + entry.key.split(".", 1)[1]   # mute_info / mute_warning / ...
            if master is False or lp.get(severity_key, False) is True:
                return False, "legacy_pref", None
        elif entry.key.startswith("cicd.") and channel == "inapp":
            if lp.get("mute_cicd_my_agents", False) is True:
                return False, "legacy_pref", None

        hit = _device_allowlist_hit(device_prefs, entry)
        if hit is True:
            base, reason = True, "legacy_enable"
        elif hit is False:
            # allowlist present and this type not on it — the device replaced the defaults,
            # exactly as _device_wants has always treated it.
            return False, "narrowed", None
        else:
            # 6 — catalog default
            base = bool(entry.default_enabled.get(channel, False))
            reason = "default" if base else "default_off"

    if not base:
        return False, reason if reason.endswith("_off") else reason + "_off", None

    # 7 — device narrowing on top of a v2-row/default enable
    if have_v2_row or reason == "default":
        hit = _device_allowlist_hit(device_prefs, entry)
        if hit is False:
            return False, "narrowed", threshold
        if entry.key == "money.received":
            raw = device_prefs.get("min_transfer_avt")
            if raw is not None:
                try:
                    dv = float(raw)
                    threshold = dv if threshold is None else max(threshold, dv)
                except (TypeError, ValueError):
                    pass

    # 8 — amount threshold
    if entry.threshold_kind == "amount" and threshold is not None:
        if amount is None or float(amount) < float(threshold):
            return False, "threshold", threshold

    # 9 — quiet hours (push only; mandatory already exempted at step 2)
    if channel in PUSH_CHANNELS and _in_quiet_hours(ctx.notification_prefs, now_hour):
        return False, "quiet", threshold

    return True, reason, threshold


async def coalesce_gate(dev_id: int, type_key: str, channel: str, window_s: int) -> Tuple[bool, int]:
    """Leading-edge coalescing. (allow, carried_count). Fail-OPEN: a broken Redis must never
    stop notifications. The count key OUTLIVES the suppression window (§STREAKFIX)."""
    if window_s <= 0:
        return True, 0
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return True, 0
        sk = f"{_COALESCE_SUPPRESS}{dev_id}:{type_key}:{channel}"
        ck = f"{_COALESCE_COUNT}{dev_id}:{type_key}:{channel}"
        if await r.get(sk):
            # window open → swallow, count in the SEPARATE longer-lived key
            pipe_ttl = max(4 * window_s, 900)
            n = await r.incr(ck)
            if n == 1:
                await r.expire(ck, pipe_ttl)
            return False, 0
        await r.set(sk, "1", ex=window_s)
        carried = 0
        raw = await r.get(ck)
        if raw:
            try:
                carried = int(raw)
            except (TypeError, ValueError):
                carried = 0
            await r.delete(ck)
        return True, carried
    except Exception as exc:  # noqa: BLE001
        logger.debug("[NOTIFY-PREFS] coalesce gate failed open: %s", exc)
        return True, 0


def get_entry_or_none(type_key: str) -> Optional[NotificationType]:
    return get_type(type_key)
