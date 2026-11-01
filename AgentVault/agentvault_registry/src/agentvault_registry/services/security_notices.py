"""V0652 (af) (order gwo_3b80091fe506da824c40f903, agentvault2-14, 2026-10-31): the account's own security notices.

Two the gaps file found missing (session-lead's NOTIFICATION_GAPS_2026-10-31.md, "Security"):
  - security.password_changed: the password of your account was changed, by whichever of the three routes (settings,
    a reset link, a recovery key). Said to the account after the change commits.
  - security.new_login: a sign-in from a device this account has not used. Every sign-in that issues a session (the
    password route, a 2FA code, a backup code, a phone's approval) records its device in security_audit_logs
    (`session.login`, target `device` = a key derived from the browser's user agent with its version numbers dropped,
    so an update is not a new device). A device seen on this account in the last 180 days says nothing; an unseen one
    is said once (the next sign-in from it finds its row). The first sign-in this registry records for an account says
    nothing: there is nothing yet to compare it with. The network address is named in the notice, not compared: a phone
    changes networks all day, and a notice on every change would be ignored.

Both are best effort and never raise: a notice must never break a sign-in or a password change.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

SEEN_DAYS = 180


def _spawn(coro) -> None:
    from agentvault_registry.background_tasks.push_notify import spawn_notice
    spawn_notice(coro)


def device_key(user_agent: Optional[str]) -> str:
    """The device a sign-in came from, as far as a browser says: its user agent, lowercased, without version numbers."""
    norm = re.sub(r"\d+", "", (user_agent or "").lower())
    norm = " ".join(norm.split())[:400] or "unknown"
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def device_label(user_agent: Optional[str]) -> str:
    """A person's words for the device ("Firefox on Linux"), or "an unknown browser"."""
    ua = user_agent or ""
    browser = next((name for needle, name in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("OPR/", "Opera"),
                                              ("Chrome/", "Chrome"), ("Safari/", "Safari")) if needle in ua), None)
    system = next((name for needle, name in (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iOS"),
                                             ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Linux", "Linux")) if needle in ua),
                  None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or "an unknown browser"


async def note_login(db, developer_id: int, ip: Optional[str], user_agent: Optional[str]) -> bool:
    """Record this sign-in's device and tell the account when the device is new to it. True when it told."""
    try:
        from agentvault_registry.services.admin_audit import log_session_action
        key = device_key(user_agent)
        # the column is TIMESTAMP WITHOUT TIME ZONE holding naive UTC (security_oauth/audit_logger.py, §pass47 C4)
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=SEEN_DAYS)
        rows = (await db.execute(text(
            "SELECT target_id FROM security_audit_logs WHERE action = 'session.login' AND actor_id = :d "
            "AND target_type = 'device' AND \"timestamp\" > :since"), {"d": str(developer_id), "since": since})).all()
        seen = {r[0] for r in rows}
        await log_session_action(db, action="login", actor_id=str(developer_id), actor_ip=ip, target_type="device",
                                 target_id=key, details={"device": device_label(user_agent)})
        await db.commit()
        if not seen or key in seen:
            return False
        from agentvault_registry.background_tasks.push_notify import notify
        where = f" from {ip}" if ip else ""
        _spawn(notify(
            "security.new_login", [int(developer_id)],
            title="New sign-in to your account",
            message=(f"A sign-in from {device_label(user_agent)}{where}, a device this account has not used before. "
                     "If it was not you, change your password: that signs out every session."),
            tags="key", click="/ui#/settings"))
        return True
    except Exception as e:  # noqa: BLE001 — never break a sign-in over its notice
        logger.warning("[SECURITY-NOTICE] new-login check failed for developer %s: %s", developer_id, e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def tell_password_changed(developer_id: int, how: str) -> None:
    """After a password change commits: the account hears it, and how it was changed."""
    try:
        from agentvault_registry.background_tasks.push_notify import notify
        _spawn(notify(
            "security.password_changed", [int(developer_id)],
            title="Your password was changed",
            message=f"The password of your account was changed {how}. If it was not you, reset it now.",
            tags="lock", click="/ui#/settings"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[SECURITY-NOTICE] password-change notice failed for developer %s: %s", developer_id, e)


# ── the daily pass (the account deletion worker's turn, once a day on its leader) ─────────────────────────────────────

API_KEY_NOTICE_DAYS = 14
_LEGAL_MARK = "registry:legal:noticed_version"


async def remind_api_keys(db, now: Optional[datetime] = None) -> int:
    """security.api_key_expiring: an active key that expires within 14 days, said to its owner once per key and expiry
    (a key whose expiry is moved is a new occasion). The key is named by its prefix and description, never by itself."""
    from agentvault_registry.background_tasks import push_notify
    now = now or datetime.now(timezone.utc)
    told = 0
    rows = (await db.execute(text(
        "SELECT id, developer_id, key_prefix, description, expires_at FROM developer_api_keys "
        "WHERE is_active AND expires_at IS NOT NULL AND expires_at > :now AND expires_at <= :soon"),
        {"now": now, "soon": now + timedelta(days=API_KEY_NOTICE_DAYS)})).all()
    for kid, dev, prefix, desc, exp in rows:
        when = exp.strftime("%Y-%m-%d") if hasattr(exp, "strftime") else str(exp)[:10]
        name = f"“{str(desc)[:60]}” ({prefix}…)" if desc else f"{prefix}…"
        if not await push_notify.claim_once(f"security.api_key_expiring:{kid}:{when}", 30 * 86400):
            continue
        await push_notify.notify(
            "security.api_key_expiring", [int(dev)], title="An API key expires soon",
            message=f"Your API key {name} expires on {when}. Create a new one in Settings and replace it where it is used.",
            tags="key", click="/ui#/settings")
        told += 1
    return told


async def tell_terms_updated(db) -> int:
    """legal.terms_updated, once per version of the legal set: every account that accepts the Terms again at its next
    sign-in hears what changes and when (core/legal_versions.py). The first pass this registry runs records the version
    it serves and says nothing (that version's change was announced when it was published)."""
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.background_tasks.leader import get_redis
    from agentvault_registry.core import legal_versions as lv
    from agentvault_registry.services.legal_acceptance import reconsent_required
    r = await get_redis()
    if r is None:
        return 0
    seen = await r.get(_LEGAL_MARK)
    seen = seen.decode() if isinstance(seen, (bytes, bytearray)) else seen
    if seen == lv.DOCUMENTS_VERSION:
        return 0
    await r.set(_LEGAL_MARK, lv.DOCUMENTS_VERSION)
    if seen is None:
        return 0   # the first pass: the version served now was announced when it was published
    rows = (await db.execute(text(
        "SELECT id, tos_accepted_version FROM developers WHERE deleted_at IS NULL AND NOT is_suspended"))).all()
    devs = [int(d) for d, v in rows if reconsent_required(v, lv.TOS_VERSION)]
    if not devs:
        return 0
    await push_notify.notify_once(
        f"legal.terms_updated:{lv.DOCUMENTS_VERSION}", "legal.terms_updated", devs, ttl_s=400 * 86400,
        title="The terms change",
        message=(f"Version {lv.DOCUMENTS_VERSION} of the terms takes effect on {lv.EFFECTIVE_LABEL}. Read what changes; "
                 "you accept it at your next sign-in."),
        tags="page_facing_up", click="/ui#/legal")
    return len(devs)


async def daily_pass(db) -> dict:
    """Both, each on its own: one failing never stops the other, and neither stops the worker that carries them."""
    out = {"api_keys_told": 0, "terms_told": 0}
    for name, fn in (("api_keys_told", remind_api_keys), ("terms_told", tell_terms_updated)):
        try:
            out[name] = await fn(db)
        except Exception as e:  # noqa: BLE001
            logger.warning("[SECURITY-NOTICE] daily %s failed: %s", name, e)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return out
