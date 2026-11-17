"""V0662 (OurChat lane): editing and deleting a message within a window. The pure rules; the writes are
services/chat_service.py::edit_message / delete_message.

A text message its sender wrote can be changed or taken back for a short while (CHAT_EDIT_WINDOW_S, 15 minutes unless the
registry says otherwise). The change is marked (`edited_at`; a deleted message shows the thread's tombstone) and the
ORIGINAL is KEPT for the record: every body the message held before a change is a row in chat_message_edits, readable by
the thread's members through the history route. Nothing else about a message changes: its seq, its place, its sender and
its mentions stay as posted (an edit wakes no one: a name added by an edit is not notified).

What may be changed: a `text` message, by its own sender, inside the window, in a thread this registry hosts alone (a
thread another registry hosts or reaches keeps its copy of the old text, so it is refused until the federation carries
the change; the same refusal as a card update). A card, a system line, a service result and a mirrored message are never
changed.
"""
from __future__ import annotations

import datetime
import os
from typing import Optional

WINDOW_DEFAULT_S = 900
WINDOW_MIN_S = 60
WINDOW_MAX_S = 86400
#: a message takes at most this many edits (each keeps the body before it)
EDIT_REV_MAX = 20


def window_seconds() -> int:
    """CHAT_EDIT_WINDOW_S, clamped to [1 minute, 1 day]; anything unreadable is the default."""
    try:
        v = int(os.getenv("CHAT_EDIT_WINDOW_S", str(WINDOW_DEFAULT_S)))
    except (TypeError, ValueError):
        return WINDOW_DEFAULT_S
    return max(WINDOW_MIN_S, min(WINDOW_MAX_S, v))


def _utc(ts: datetime.datetime) -> datetime.datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)


def editable_until(created_at: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """When a message posted at `created_at` stops taking changes (None when it has no time)."""
    if created_at is None:
        return None
    return _utc(created_at) + datetime.timedelta(seconds=window_seconds())


def in_window(created_at: Optional[datetime.datetime], now: datetime.datetime) -> bool:
    until = editable_until(created_at)
    return until is not None and _utc(now) <= until


def refusal(kind: str, *, deleted: bool, mirrored: bool, mine: bool, created_at: Optional[datetime.datetime],
            now: datetime.datetime, revs: int = 0, editing: bool = True) -> Optional[str]:
    """Why a message may not be changed now, or None when it may. One sentence a person can act on."""
    if deleted:
        return "this message was taken back"
    if mirrored:
        return "this message came from another registry: it is changed there"
    if not mine:
        return "only whoever wrote a message changes it"
    if kind != "text":
        return "only a text message is changed: a card stays as it was posted"
    if not in_window(created_at, now):
        mins = window_seconds() // 60
        return f"a message takes changes for {mins} minutes after it is posted"
    if editing and revs >= EDIT_REV_MAX:
        return f"a message takes {EDIT_REV_MAX} edits: post a new one"
    return None
