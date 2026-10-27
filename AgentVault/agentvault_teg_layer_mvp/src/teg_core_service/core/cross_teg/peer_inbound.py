"""§SECFIX-12 (2026-09-25) — a daily bound on what a FOREIGN trust domain can credit on this TEG through the 2PC legs.

The receiving TEG credits the amount a caller's prepare states (protocol.accept_transfer mints it at commit); nothing
checks the source debited it, and a federated peer frame is a legitimate caller of /prepare and /commit. Until a
cross-frame reconciler compares each credit with the source's own record, this caps what one peer domain can mint here
per UTC day, counted at /prepare, before anything is credited.

    CROSS_TEG_PEER_INBOUND_LIMIT_MODE   off | observe | enforce   (default observe: count, log, refuse nothing)
    CROSS_TEG_PEER_INBOUND_DAILY_LIMIT  per foreign trust domain per UTC day, in this TEG's unit (default 10000)

Measured 2026-09-25 (EU, ASIA, the sandbox pair): every COMPLETED 2PC credit came from the TEG's own trust domain (its
frame or its operators; the busiest day 182,220 on sbx-beta from its own operator, the sim), and no cross-domain 2PC
transfer ever completed. Own-domain callers are therefore not counted: the bound is about a peer frame. Counted in
Redis (`teg:xteg:peer_inbound:<teg>:<domain>:<yyyymmdd>`, 3-day TTL), atomically: the amount is added first and taken
back when it crosses the limit. Redis unreachable: observe skips; enforce refuses (a money bound that cannot count
fails closed).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from ..internal_auth import trust_domain_of

logger = logging.getLogger(__name__)

MODES = ("off", "observe", "enforce")
DEFAULT_LIMIT = Decimal("10000")

try:
    from prometheus_client import Counter as _C

    PEER_INBOUND_OVER_LIMIT_TOTAL = _C(
        "teg_cross_teg_peer_inbound_over_limit_total",
        "2PC prepares from a foreign trust domain that crossed its daily inbound limit (observe: served; enforce: refused)",
        ["mode"],
    )
except Exception:  # pragma: no cover
    PEER_INBOUND_OVER_LIMIT_TOTAL = None


def mode() -> str:
    m = (os.environ.get("CROSS_TEG_PEER_INBOUND_LIMIT_MODE") or "observe").strip().lower()
    if m not in MODES:
        logger.error("[CrossTEG/peer-inbound] CROSS_TEG_PEER_INBOUND_LIMIT_MODE=%r is not one of %s; serving as observe",
                     m[:40], MODES)
        return "observe"
    return m


def daily_limit() -> Decimal:
    raw = (os.environ.get("CROSS_TEG_PEER_INBOUND_DAILY_LIMIT") or "").strip()
    if not raw:
        return DEFAULT_LIMIT
    try:
        v = Decimal(raw)
        return v if v >= 0 else DEFAULT_LIMIT
    except InvalidOperation:
        logger.error("[CrossTEG/peer-inbound] CROSS_TEG_PEER_INBOUND_DAILY_LIMIT=%r is not a number; using %s",
                     raw[:40], DEFAULT_LIMIT)
        return DEFAULT_LIMIT


def is_foreign(caller: Optional[str]) -> bool:
    """True when the caller's trust domain is not this TEG's own (an unidentified caller counts as foreign)."""
    own = (os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip()
    domain = trust_domain_of(caller)
    return not (domain and own and domain == own)


def _key(domain: str) -> str:
    teg = (os.getenv("TEG_ID") or os.getenv("TEG_NAME") or "default").lower().replace(" ", "-")
    return f"teg:xteg:peer_inbound:{teg}:{domain}:{datetime.now(timezone.utc):%Y%m%d}"


async def admit(caller: Optional[str], amount_raw, transfer_id: str) -> Tuple[bool, str]:
    """(allowed, detail) for a 2PC prepare. Own-domain callers and mode off are always allowed and never counted."""
    m = mode()
    if m == "off" or not is_foreign(caller):
        return True, "not counted"
    try:
        amount = Decimal(str(amount_raw))
    except (InvalidOperation, TypeError):
        return (m != "enforce"), "unparseable amount"
    domain = trust_domain_of(caller) or "unidentified"
    limit = daily_limit()
    try:
        from ...redis_client import get_redis
        r = await get_redis()
    except Exception:
        r = None
    if r is None:
        logger.warning("[CrossTEG/peer-inbound] cannot count (no Redis) domain=%s transfer=%s mode=%s", domain, transfer_id, m)
        return (m != "enforce"), "not counted: Redis unreachable"
    key = _key(domain)
    try:
        total = Decimal(str(await r.incrbyfloat(key, float(amount))))
        await r.expire(key, 3 * 86400)
    except Exception as e:
        logger.warning("[CrossTEG/peer-inbound] count failed domain=%s transfer=%s: %s", domain, transfer_id, e)
        return (m != "enforce"), "not counted: Redis error"
    if total <= limit:
        return True, f"{total} of {limit} today"
    if PEER_INBOUND_OVER_LIMIT_TOTAL is not None:
        try:
            PEER_INBOUND_OVER_LIMIT_TOTAL.labels(mode=m).inc()
        except Exception:  # pragma: no cover
            pass
    logger.warning("[CrossTEG/peer-inbound] %s: domain=%s transfer=%s amount=%s would bring today's inbound to %s over %s",
                   "REFUSED" if m == "enforce" else "OVER LIMIT (observe)", domain, transfer_id, amount, total, limit)
    if m != "enforce":
        return True, f"over the limit (observe): {total} of {limit}"
    try:
        await r.incrbyfloat(key, -float(amount))
    except Exception:
        pass
    return False, f"peer_inbound_limit: {domain} would reach {total} of {limit} today"
