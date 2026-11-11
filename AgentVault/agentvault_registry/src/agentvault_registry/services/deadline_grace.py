"""How long after its deadline a missed piece of work goes to a dispute: one rule for Guild orders and contracts.

V0658 (e), polish 18 of the disputes discovery: a Guild order went to a dispute 1 hour after its deadline
(guild_order_reaper, a literal) and a contract 24 hours after (CONTRACT_DEADLINE_GRACE_HOURS); the Commander chose one
rule, 24 hours (room seq 1617/1633). DEADLINE_GRACE_HOURS sets it for both; an operator who already set the contract's
old name keeps that value, now for both. A value that is not a positive whole number falls back, never to no grace.
"""
from __future__ import annotations

import os

DEFAULT_GRACE_HOURS = 24


def _hours(raw):
    try:
        h = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return h if h > 0 else None


def grace_hours() -> int:
    """Hours between a missed deadline and the dispute it opens, for a Guild order and a contract alike."""
    return (_hours(os.getenv("DEADLINE_GRACE_HOURS"))
            or _hours(os.getenv("CONTRACT_DEADLINE_GRACE_HOURS"))
            or DEFAULT_GRACE_HOURS)


def grace_words(hours: int | None = None) -> str:
    """The grace as the reminders say it: "a day", "an hour", "N hours"."""
    h = grace_hours() if hours is None else hours
    if h == 24:
        return "a day"
    if h == 1:
        return "an hour"
    if h % 24 == 0:
        return f"{h // 24} days"
    return f"{h} hours"
