"""V0662 (OurChat lane, the batch's item 11): agent status in a room (the session board). The pure rules; the writes are
services/chat_service.py::report_agent_status / read_agent_status.

The money question this answers is "who is spending": a session that is woken a lot spends a lot. The room's DESK knows each
session's pause and armed state and every wake it relays, and reports them about every 60 seconds; the registry keeps the last
report per session and shows it to the organization's owner and admins.

The page never guesses (a probe may report what it observed, never why): a session whose row the desk has not refreshed in
STALE_AFTER_S seconds reads `unknown`, not `active`; a state the desk could not tell is `unknown`, not a cause. A wake is not a
read (no read receipts): the board counts relays, it says nothing about what anyone read.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

#: what the desk may report
STATES = ("active", "paused", "unreachable")
WAKE_MODES = ("listen", "on-call", "off")
#: a row not refreshed for this long reads "unknown"
STALE_AFTER_S = 300
#: one report carries at most this many sessions
MAX_ENTRIES = 60
WAKES_MAX = 100_000


def _utc(ts: datetime.datetime) -> datetime.datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)


def effective_state(state: Optional[str], reported_at: Optional[datetime.datetime], now: datetime.datetime) -> str:
    """What the board says: the reported state while the report is fresh, else `unknown`."""
    if state not in STATES or reported_at is None:
        return "unknown"
    if (_utc(now) - _utc(reported_at)).total_seconds() > STALE_AFTER_S:
        return "unknown"
    return str(state)


def clean_entry(e: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """One reported session, checked: ({key, name, state, wake_mode, last_wake_at, wakes_24h}, None) or (None, why)."""
    if not isinstance(e, dict):
        return None, "an entry is an object"
    key = str(e.get("key") or "").strip()
    if not (key.startswith("agt:") or key.startswith("dev:")) or len(key) > 320:
        return None, "key is the member sheet's (agt:<did> or dev:<id>)"
    state = e.get("state")
    if state not in STATES:
        return None, f"state is one of {', '.join(STATES)}"
    mode = e.get("wake_mode")
    if mode is not None and mode not in WAKE_MODES:
        return None, f"wake_mode is one of {', '.join(WAKE_MODES)}"
    last = e.get("last_wake_at")
    when: Optional[datetime.datetime] = None
    if last not in (None, ""):
        try:
            when = _utc(datetime.datetime.fromisoformat(str(last)))
        except ValueError:
            return None, "last_wake_at is an ISO time"
    try:
        n = int(e.get("wakes_24h") or 0)
    except (TypeError, ValueError):
        return None, "wakes_24h is a count"
    if n < 0 or n > WAKES_MAX:
        return None, f"wakes_24h is 0 to {WAKES_MAX}"
    name = " ".join(str(e.get("name") or "").split())[:120] or None
    return {"key": key, "name": name, "state": state, "wake_mode": mode, "last_wake_at": when, "wakes_24h": n}, None


def clean_report(entries: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """A whole report, checked: (the good entries, a reason for each refused one). A report of more than MAX_ENTRIES is cut."""
    if not isinstance(entries, list):
        return [], ["entries is a list"]
    good, bad, seen = [], [], set()
    for i, e in enumerate(entries[:MAX_ENTRIES]):
        c, why = clean_entry(e)
        if c is None:
            bad.append(f"entry {i}: {why}")
        elif c["key"] in seen:
            bad.append(f"entry {i}: {c['key']} twice")
        else:
            seen.add(c["key"])
            good.append(c)
    if len(entries) > MAX_ENTRIES:
        bad.append(f"{len(entries) - MAX_ENTRIES} entries past the {MAX_ENTRIES} a report takes were dropped")
    return good, bad
