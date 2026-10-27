"""POCKET FRAME — push notification fan-out helpers (f-mobile, 2026-07-07).

Shared by the reactor_push_notify reactors. Rails:
  - ntfy  → LIVE: HTTP POST to the (self-hosted) ntfy server, one topic per device.
  - fcm   → STUB: accepted at registration, logged+skipped until Firebase creds exist.
  - apns  → STUB: accepted at registration, logged+skipped until Apple creds exist.

Δ-irrelevant: read-side only. Failures are swallowed per-device (a dead phone
must never affect the flow that triggered the notification — it already committed).
"""
import logging
from typing import Iterable, List, Optional

import httpx
from sqlalchemy import text

from agentvault_registry.config import settings
from agentvault_registry.es_ssl_helper import get_httpx_verify
from agentvault_registry.database import AsyncSessionLocal
from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 5.0


async def resolve_developer_ids_for_dids(dids: Iterable[str]) -> List[int]:
    """Map agent DIDs → owning developer ids (dedup'd). Unknown DIDs are ignored."""
    dids = [d for d in {d for d in dids if d}]
    if not dids:
        return []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text("SELECT DISTINCT creator_developer_id FROM agents "
                 "WHERE did = ANY(:dids) AND creator_developer_id IS NOT NULL"),
            {"dids": dids},
        )).all()
    return [r[0] for r in rows]


# The 3 events every registered device receives unless it sets an explicit allowlist.
DELEGATION_DEFAULT_EVENTS = {
    "AgentDelegationGranted", "AgentCapabilityRevoked",
    # AgentCapabilityIssued REMOVED from the default set (2026-07-25): routine issuance is
    # high-volume — a spawn spree buries every notification that actually needs a human. Revocation
    # stays (that is a security event). Opt back in per-device via prefs.event_types.
    # COCKPIT CARD (2026-07-25): a liability confirmation is the ONE push a human must never
    # miss — it is the thing they are being asked to sign. It ships in the default allowlist
    # because a device with default prefs was silently dropping every confirmation, which made
    # the whole phone-approval rail dead on arrival for anyone who had not hand-edited prefs.
    "LiabilityChallenge",
    # A sign-in approval is the other push a human must never miss — without it they cannot log in.
    "LoginApproval",
}


def _device_wants(prefs, event_type: Optional[str], amount: Optional[float]) -> bool:
    """P2-1 per-device gate. Pure function (unit-tested)."""
    prefs = prefs or {}
    if ledger_names.same(event_type or "", "TokensTransferred"):
        raw = prefs.get("min_transfer_avt")
        if raw is None:
            return False  # transfer pushes are strictly opt-in
        try:
            return amount is not None and float(amount) >= float(raw)
        except (TypeError, ValueError):
            return False
    allow = prefs.get("event_types")
    if allow is None:
        return event_type is None or event_type in DELEGATION_DEFAULT_EVENTS
    return event_type in allow


async def any_transfer_subscribers() -> bool:
    """Cheap pre-gate for the TokensTransferred reactor: does ANY enabled device
    opt into transfer pushes at all? Result cached ~30s (module TTL) so sim-volume
    event streams cost one indexed query per half-minute, not one per event."""
    import time
    now = time.monotonic()
    cached = _XFER_SUB_CACHE.get("v")
    if cached is not None and now - _XFER_SUB_CACHE.get("t", 0) < 30:
        return cached
    val = False
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(text(
                "SELECT 1 FROM device_push_registrations "
                "WHERE enabled AND prefs ? 'min_transfer_avt' LIMIT 1"
            ))).first()
            val = row is not None
            # §NOTIFV2: under v2, a developer can opt into money.received via a prefs ROW
            # with no device-level min_transfer_avt at all — the legacy-only probe would
            # early-exit past them. Same 30s cache amortises the extra EXISTS.
            if not val and str(getattr(settings, "NOTIFY_V2_MODE", "off")).lower() == "on":
                row2 = (await db.execute(text(
                    "SELECT 1 FROM developer_notification_prefs "
                    "WHERE type_key = 'money.received' AND enabled LIMIT 1"
                ))).first()
                val = row2 is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PUSH] transfer-subscriber probe failed: %s", exc)
    _XFER_SUB_CACHE["v"] = val
    _XFER_SUB_CACHE["t"] = now
    return val


_XFER_SUB_CACHE: dict = {}


def _ascii_header(value: str) -> str:
    """HTTP headers are latin-1 at best and ntfy reads Title/Tags as ASCII, so a single em-dash
    or umlaut in a title raised UnicodeEncodeError and killed the ENTIRE notification — body and
    all. Fold to ASCII: map the typographic characters we actually emit, then strip accents.
    The message BODY is sent as UTF-8 content and keeps every character."""
    if value.isascii():
        return value
    for bad, good in (("\u2014", "-"), ("\u2013", "-"), ("\u2018", "'"), ("\u2019", "'"),
                      ("\u201c", '"'), ("\u201d", '"'), ("\u2026", "..."), ("\u00a0", " ")):
        value = value.replace(bad, good)
    if value.isascii():
        return value
    import unicodedata
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii") or "Notification"


def _topic_hint(target: str) -> str:
    """Anyone who holds a device's ntfy topic can read and publish its notifications, so a log line carries a hint of the
    topic, the way the webpush lines log the row id rather than the endpoint."""
    t = target or ""
    return f"{t[:4]}...({len(t)})"


async def _send_ntfy(target: str, title: str, message: str, tags: str, priority: str,
                     click: Optional[str] = None) -> bool:
    base = (settings.PUSH_NTFY_URL or "").rstrip("/")
    if not base:
        return False
    try:
        # §MTLSHOPS V0378: TLS by scheme (a T2 frame's ntfy lane requires the registry's SVID; http ignores the context)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, verify=get_httpx_verify()) as client:
            resp = await client.post(
                f"{base}/{target}",
                content=message.encode("utf-8"),
                headers={"Title": _ascii_header(title), "Tags": _ascii_header(tags),
                         "Priority": priority,
                         # COCKPIT CARD: tapping the notification must land ON the thing it is
                         # asking about. ntfy owns the delivery rail (our app is a web app with
                         # no push channel of its own), so the deep link is what makes the two
                         # feel like one product instead of two.
                         **({"Click": click} if click else {})},
            )
        if resp.status_code >= 300:
            # agentvault2-b5's V0378 lab: nginx-ntfy answers 400 to a caller without the registry's certificate, and a refused
            # publish left no trace here because only an exception was logged
            logger.warning("[PUSH] ntfy refused target=%s status=%s", _topic_hint(target), resp.status_code)
        return resp.status_code < 300
    except Exception as exc:  # noqa: BLE001 — per-device best-effort by design
        logger.warning("[PUSH] ntfy send failed target=%s: %s", _topic_hint(target), exc)
        return False


async def _send_webpush(row, title: str, message: str, click: Optional[str]) -> bool:
    """Deliver one Web Push. Runs the blocking crypto/HTTP in a thread so the event loop keeps
    moving, and PRUNES the subscription when the browser says it is permanently gone (404/410) —
    otherwise a reinstalled phone leaves a dead row we retry forever."""
    if not (row.target and row.p256dh and row.auth):
        return False
    try:
        import asyncio as _asyncio
        from agentvault_registry.services import webpush as _wp
        async with AsyncSessionLocal() as db:
            key_row = await _wp.get_or_mint_key(db)
            vapid_key = _wp.vapid_private_raw(key_row)
        subject = str(getattr(settings, "PUSH_APP_BASE_URL", "") or getattr(settings, "BASE_URL", "") or "https://theprotocol.cloud").rstrip("/")
        payload = {"title": title, "body": message, "url": click or f"{subject}/ui/#/pocket/approvals"}
        ok, status = await _asyncio.to_thread(
            _wp.send_webpush, endpoint=row.target, p256dh=row.p256dh, auth=row.auth,
            payload=payload, vapid_key=vapid_key, subject="mailto:admin@theprotocol.cloud",
        )
        if status in (404, 410):
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(text("DELETE FROM device_push_registrations WHERE id = :i"), {"i": row.id})
                    await db.commit()
                logger.info("[PUSH] pruned dead webpush subscription id=%s", row.id)
            except Exception:  # noqa: BLE001
                logger.debug("[PUSH] prune failed id=%s", row.id, exc_info=True)
        return ok
    except Exception as exc:  # noqa: BLE001 — per-device best-effort by design
        logger.warning("[PUSH] webpush failed id=%s: %s", getattr(row, "id", "?"), exc)
        return False


async def notify_developers(
    developer_ids: Iterable[int],
    *,
    title: str,
    message: str,
    tags: str = "key",
    priority: str = "default",
    event_type: Optional[str] = None,
    amount: Optional[float] = None,
    click: Optional[str] = None,
) -> int:
    """Fan a notification out to every enabled device of the given developers,
    honoring per-device prefs (P2-1):

      prefs.event_types      — allowlist; ABSENT ⇒ default = the 3 delegation events
      prefs.min_transfer_avt — presence OPTS INTO TokensTransferred pushes for
                               amounts ≥ the value (absent ⇒ transfer pushes off)

    Returns the number of successful sends. Never raises.
    """
    dev_ids = [d for d in {d for d in developer_ids if d is not None}]
    if not dev_ids or not settings.PUSH_NOTIFY_ENABLED:
        return 0
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text("""
                SELECT id, developer_id, rail, target, prefs, p256dh, auth
                FROM device_push_registrations
                WHERE enabled AND developer_id = ANY(:devs)
            """), {"devs": dev_ids})).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PUSH] device lookup failed: %s", exc)
        return 0

    sent = 0
    for row in rows:
        if not _device_wants(getattr(row, "prefs", None), event_type, amount):
            continue
        rail = row.rail
        if rail == "ntfy":
            ok = await _send_ntfy(row.target, title, message, tags, priority, click=click)
            sent += 1 if ok else 0
        elif rail == "webpush":
            # The app's OWN channel (RFC 8291/8292) — no second app, no vendor account.
            ok = await _send_webpush(row, title, message, click)
            sent += 1 if ok else 0
        elif rail == "fcm":
            if settings.PUSH_FCM_ENABLED:
                logger.warning("[PUSH] FCM enabled but adapter not implemented — device id=%s skipped", row.id)
            else:
                logger.debug("[PUSH] FCM stub — device id=%s skipped", row.id)
        elif rail == "apns":
            if settings.PUSH_APNS_ENABLED:
                logger.warning("[PUSH] APNs enabled but adapter not implemented — device id=%s skipped", row.id)
            else:
                logger.debug("[PUSH] APNs stub — device id=%s skipped", row.id)
    if rows:
        logger.info("[PUSH] %s → %d device(s), %d delivered", event_type or title, len(rows), sent)
    return sent


# ═══════════════════════════════════════════════════════════════════════════
# §NOTIFV2 (2026-07-26) — catalog-validated send path
#
# notify() is the ONE way to send a typed notification. It refuses nothing in
# production (never break a sender), but an unregistered type is an ERROR log +
# a counter + a raise UNDER PYTEST — converting the silent-drop class that
# killed LiabilityChallenge and LoginApproval on arrival into noise you cannot
# miss. Mode routing (settings.NOTIFY_V2_MODE):
#   off    → verdicts come from the LEGACY _device_wants path, byte-identical
#            to before this change (new catalog-only types therefore stay
#            silent — dark by default).
#   shadow → legacy verdict DECIDES; the v2 resolver runs alongside and every
#            disagreement increments notify_prefs_shadow_mismatch_total.
#   on     → the v2 resolver decides (catalog defaults ∘ developer rows ∘
#            legacy enablers ∘ device narrowing ∘ thresholds ∘ quiet hours ∘
#            coalescing; mandatory bypasses everything).
# ═══════════════════════════════════════════════════════════════════════════

try:  # metrics are best-effort everywhere in this module
    from prometheus_client import Counter as _NCounter

    NOTIFICATION_SENT_TOTAL = _NCounter(
        "notification_sent_total",
        "Typed notifications delivered, by catalog type/channel/outcome",
        labelnames=["type", "channel", "outcome"],
    )
    NOTIFICATION_SUPPRESSED_TOTAL = _NCounter(
        "notification_suppressed_total",
        "Typed notifications suppressed before delivery, by reason",
        labelnames=["type", "channel", "reason"],
    )
    NOTIFICATION_UNREGISTERED_TOTAL = _NCounter(
        "notification_unregistered_type_total",
        "notify() calls whose type_key is not in the catalog (a bug, by definition)",
        labelnames=["type"],
    )
    NOTIFY_SHADOW_MISMATCH_TOTAL = _NCounter(
        "notify_prefs_shadow_mismatch_total",
        "shadow mode: legacy and v2 verdicts disagreed",
        labelnames=["type", "channel", "direction"],
    )
except Exception:  # pragma: no cover
    NOTIFICATION_SENT_TOTAL = None  # type: ignore[assignment]
    NOTIFICATION_SUPPRESSED_TOTAL = None  # type: ignore[assignment]
    NOTIFICATION_UNREGISTERED_TOTAL = None  # type: ignore[assignment]
    NOTIFY_SHADOW_MISMATCH_TOTAL = None  # type: ignore[assignment]


def _cnt(counter, **labels):
    if counter is None:
        return
    try:
        counter.labels(**labels).inc()
    except Exception:  # noqa: BLE001
        pass


def _under_pytest() -> bool:
    import sys
    return "pytest" in sys.modules


async def _deliver_to_row(row, title: str, message: str, tags: str, priority: str,
                          click: Optional[str]) -> bool:
    """One device, one delivery attempt. Shared by legacy and v2 paths."""
    rail = row.rail
    if rail == "ntfy":
        return await _send_ntfy(row.target, title, message, tags, priority, click=click)
    if rail == "webpush":
        return await _send_webpush(row, title, message, click)
    if rail in ("fcm", "apns"):
        logger.debug("[PUSH] %s stub — device id=%s skipped", rail, row.id)
    return False


async def _write_notification_log(rows: list) -> None:
    """Persist the per-device decisions of ONE notify() call. Best effort, never raises.

    A notification log that can break a notification is worse than no log at all, so every
    failure here is a warning and nothing more. Written after the fan-out, in one statement,
    so the delivery path pays a single round trip regardless of device count.
    """
    if not rows or not getattr(settings, "NOTIFICATION_LOG_ENABLED", True):
        return
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("""
                INSERT INTO notification_log
                    (developer_id, type_key, category, severity, channel, outcome,
                     reason, mode, device_id, title, message)
                VALUES
                    (:developer_id, :type_key, :category, :severity, :channel, :outcome,
                     :reason, :mode, :device_id, :title, :message)
            """), rows)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NOTIFY-LOG] write failed (%d row(s)): %s", len(rows), exc)


async def _deliver_non_device_channels(entry, dev_ids: list, ctxs: dict, mode: str,
                                       title: str, message: str, click, amount,
                                       rec) -> None:
    """Serve the `inapp` and `email` channels — the two the catalog has always declared and the
    delivery loop never served.

    The resolver was channel-generic from day one (`decide(entry, channel, ...)`, and its quiet-
    hours step is explicitly push-only), so nothing here re-implements policy: it asks the SAME
    decide() and then delivers. `device_prefs=None` on purpose — device narrowing is a property
    of a phone, and these two channels do not have one.

    ONLY in mode='on'. In shadow the v2 path must not create delivery that the legacy path would
    not have produced, or "shadow" would stop meaning "observe without acting".
    Best effort throughout: a notification rail must never take down its caller.
    """
    if mode != "on" or not dev_ids:
        return
    from agentvault_registry.services import notification_prefs as np

    want_inapp, want_email = [], []
    for dev_id in dev_ids:
        ctx = ctxs.get(dev_id) or np.DevCtx(dev_id=dev_id)
        for channel, bucket in (("inapp", want_inapp), ("email", want_email)):
            send, reason, _thr = np.decide(entry, channel, ctx=ctx, device_prefs=None, amount=amount)
            if send:
                bucket.append(dev_id)
            else:
                _cnt(NOTIFICATION_SUPPRESSED_TOTAL, type=entry.key, channel=channel, reason=reason)
                rec(dev_id, channel, "suppressed", reason, None, message)

    # ── inapp: one row per developer in the generic feed (mig 0139) ──
    if want_inapp:
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(text("""
                    INSERT INTO notification_feed
                        (developer_id, type_key, category, severity, title, body, click)
                    VALUES (:d, :k, :c, :s, :t, :b, :u)
                """), [{"d": d, "k": entry.key, "c": entry.category, "s": entry.severity,
                        "t": title[:500], "b": message[:2000],
                        "u": (click or None) and str(click)[:500]} for d in want_inapp])
                await db.commit()
            for d in want_inapp:
                _cnt(NOTIFICATION_SENT_TOTAL, type=entry.key, channel="inapp", outcome="delivered")
                rec(d, "inapp", "delivered", None, None, message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[NOTIFY] inapp feed write failed for %s: %s", entry.key, exc)
            for d in want_inapp:
                rec(d, "inapp", "failed", "feed_write_error", None, message)

    # ── email: reuse the proven themed sender + the generic broadcast template ──
    if want_email:
        try:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(text(
                    "SELECT id, email FROM developers "
                    "WHERE id = ANY(:devs) AND is_verified = TRUE AND email IS NOT NULL"
                ), {"devs": want_email})).all()
            addressed = {r.id: r.email for r in rows}
            # An unverified address is not a delivery target — same rule the broadcast path uses.
            for d in want_email:
                if d not in addressed:
                    _cnt(NOTIFICATION_SUPPRESSED_TOTAL, type=entry.key, channel="email",
                         reason="unverified_email")
                    rec(d, "email", "suppressed", "unverified_email", None, message)
            if addressed:
                from agentvault_registry.email_utils import send_themed_email
                # sovereign = the red SecurityAlerts@ identity; neural = cyan noreply@.
                theme = "sovereign" if (entry.severity == "critical" or entry.category == "security") \
                    else "neural"
                ok = await send_themed_email(
                    subject=f"[TheProtocol] {title}",
                    recipients=list(addressed.values()),
                    template="broadcast_notification",
                    context={"title": title, "body": message,
                             "broadcast_type": entry.category,
                             "type_label": entry.severity.upper(),
                             "cta_url": click or None, "cta_label": "Open" if click else None},
                    theme=theme,
                )
                for d in addressed:
                    _cnt(NOTIFICATION_SENT_TOTAL, type=entry.key, channel="email",
                         outcome="delivered" if ok else "failed")
                    rec(d, "email", "delivered" if ok else "failed",
                        None if ok else "email_send_failed", None, message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[NOTIFY] email send failed for %s: %s", entry.key, exc)
            for d in want_email:
                rec(d, "email", "failed", "email_send_error", None, message)


async def notify(
    type_key: str,
    developer_ids: Iterable[int],
    *,
    title: str,
    message: str,
    tags: str = "key",
    priority: str = "default",
    amount: Optional[float] = None,
    click: Optional[str] = None,
) -> int:
    """Catalog-validated notification fan-out. Never raises in production."""
    from agentvault_registry.services import notification_prefs as np
    from agentvault_registry.services.notification_catalog import get_type

    entry = get_type(type_key)
    if entry is None:
        logger.error(
            "[NOTIFY] UNREGISTERED notification type %r — add it to "
            "services/notification_catalog.py. Dropping (fail-loud, never fail-silent).",
            type_key,
        )
        _cnt(NOTIFICATION_UNREGISTERED_TOTAL, type=type_key[:64])
        if _under_pytest():
            raise KeyError(f"unregistered notification type: {type_key}")
        return 0

    mode = str(getattr(settings, "NOTIFY_V2_MODE", "off") or "off").lower()
    legacy_event_type = entry.es_event_types[0] if entry.es_event_types else entry.key

    if mode == "off":
        # Byte-identical to the pre-catalog behaviour (validation + metrics only).
        sent = await notify_developers(
            developer_ids, title=title, message=message, tags=tags,
            priority=priority, event_type=legacy_event_type, amount=amount, click=click,
        )
        _cnt(NOTIFICATION_SENT_TOTAL, type=entry.key, channel="legacy",
             outcome="delivered" if sent else "none")
        return sent

    dev_ids = [d for d in {d for d in developer_ids if d is not None}]
    if not dev_ids or not settings.PUSH_NOTIFY_ENABLED:
        return 0

    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text("""
                SELECT id, developer_id, rail, target, prefs, p256dh, auth
                FROM device_push_registrations
                WHERE enabled AND developer_id = ANY(:devs)
            """), {"devs": dev_ids})).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PUSH] device lookup failed: %s", exc)
        rows = []
    # NO early return on an empty device list any more: inapp and email are NOT device channels,
    # and returning here is exactly why a developer without a phone got nothing and logged nothing.

    ctxs = await np.load_context(dev_ids, entry.key)
    sent = 0
    log_rows: list = []

    def _rec(dev_id: int, channel: str, outcome: str, reason, device_id, msg: str) -> None:
        """Stage one decision for the history table (flushed once, after the fan-out)."""
        log_rows.append({
            "developer_id": dev_id, "type_key": entry.key, "category": entry.category,
            "severity": entry.severity, "channel": channel, "outcome": outcome,
            "reason": reason, "mode": mode, "device_id": device_id,
            "title": title[:500], "message": msg[:2000],
        })

    for row in rows:
        channel = np.RAIL_TO_CHANNEL.get(row.rail)
        if channel is None:  # rail='local' signing rows etc. — never a push target
            continue
        device_prefs = getattr(row, "prefs", None)
        ctx = ctxs.get(row.developer_id) or np.DevCtx(dev_id=row.developer_id)
        v2_send, reason, _thr = np.decide(
            entry, channel, ctx=ctx, device_prefs=device_prefs, amount=amount,
        )
        legacy_send = _device_wants(device_prefs, legacy_event_type, amount)

        if mode == "shadow":
            if v2_send != legacy_send:
                _cnt(NOTIFY_SHADOW_MISMATCH_TOTAL, type=entry.key, channel=channel,
                     direction="v2_more" if v2_send else "v2_less")
                logger.debug(
                    "[NOTIFY-SHADOW] %s dev=%s dev_row=%s channel=%s legacy=%s v2=%s reason=%s",
                    entry.key, row.developer_id, row.id, channel, legacy_send, v2_send, reason,
                )
            decided = legacy_send
        else:  # on
            decided = v2_send

        if not decided:
            supp_reason = reason if mode == "on" else "legacy_pref"
            _cnt(NOTIFICATION_SUPPRESSED_TOTAL, type=entry.key, channel=channel,
                 reason=supp_reason)
            _rec(row.developer_id, channel, "suppressed", supp_reason, row.id, message)
            continue

        final_title, final_message = title, message
        if mode == "on" and not entry.mandatory and entry.coalesce_window_s > 0:
            allow, carried = await np.coalesce_gate(
                row.developer_id, entry.key, channel, entry.coalesce_window_s,
            )
            if not allow:
                _cnt(NOTIFICATION_SUPPRESSED_TOTAL, type=entry.key, channel=channel,
                     reason="coalesced")
                _rec(row.developer_id, channel, "suppressed", "coalesced", row.id, message)
                continue
            if carried:
                final_message = f"{message} (+{carried} more since the last one)"

        ok = await _deliver_to_row(row, final_title, final_message, tags, priority, click)
        _cnt(NOTIFICATION_SENT_TOTAL, type=entry.key, channel=channel,
             outcome="delivered" if ok else "failed")
        _rec(row.developer_id, channel, "delivered" if ok else "failed",
             None if ok else "rail_error", row.id, final_message)
        sent += 1 if ok else 0

    # inapp + email (mig 0139 feed / the themed email pipeline). Placed AFTER the device loop so
    # a slow SMTP hop can never delay a push, and inside the same log flush so one notify() writes
    # its history once.
    try:
        await _deliver_non_device_channels(
            entry, dev_ids, ctxs, mode, title, message, click, amount, _rec,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NOTIFY] non-device channels failed for %s: %s", entry.key, exc)

    await _write_notification_log(log_rows)
    logger.info("[NOTIFY] %s mode=%s → %d device(s), %d delivered",
                entry.key, mode, len(rows), sent)
    return sent


async def notify_agent_owners(type_key: str, dids: Iterable[str], **kw) -> int:
    """Convenience for the reactor pattern: resolve agent DIDs → owning developers → notify()."""
    dev_ids = await resolve_developer_ids_for_dids(dids)
    if not dev_ids:
        return 0
    return await notify(type_key, dev_ids, **kw)


async def resolve_audience_developer_ids(audience: str) -> List[int]:
    """CANDIDATE recipients for an 'operator'/'admin' audience type.

    The catalog shipped four ops types with `audience=` set and no emitter, with the note that
    "recipients resolution lands with their emitters" — this is that resolution. It is deliberately
    only a candidate set: `notification_prefs.decide()` re-checks the audience gate per developer
    (step 1), so a widened query here can never grant delivery to someone the gate would refuse.
    Soft-deleted developers are excluded (they are not people who should be paged).
    """
    audience = (audience or "").lower()
    if audience == "admin":
        where = "is_admin"
    elif audience == "operator":
        where = "(is_admin OR is_federation_operator)"
    else:
        return []
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text(
                f"SELECT id FROM developers WHERE {where} AND deleted_at IS NULL"
            ))).all()
        return [r[0] for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NOTIFY] audience resolve failed (%s): %s", audience, exc)
        return []


async def notify_audience(type_key: str, **kw) -> int:
    """Notify the catalog-declared audience of an ops/admin type. No-op if the type is unknown
    or carries no audience — the fail-loud path in notify() still reports an unregistered key."""
    from agentvault_registry.services.notification_catalog import get_type
    entry = get_type(type_key)
    if entry is None:
        return await notify(type_key, [], **kw)   # fail-loud on the unregistered key
    dev_ids = await resolve_audience_developer_ids(entry.audience)
    if not dev_ids:
        return 0
    return await notify(type_key, dev_ids, **kw)
