"""V0662 (OurChat lane): pinned messages. The pure rules; the writes are services/chat_service.py::pin_message / unpin_message.

A pin keeps a line where the thread can find it again (the decision, the link, the schedule). It is the conversation's, not
a person's: everyone who reads the thread sees the same pins. Who may pin follows who may speak for the thread: in a
direct or group thread any member who can post; in an organization room its owners and admins; in a cross-frame room its
owner and moderators. A thread keeps at most MAX_PINS: the eleventh asks for an older one to be taken off first. A support
thread has no pins. A line taken back loses its pin.
"""
from __future__ import annotations

from typing import Optional

MAX_PINS = 10
#: conversation kinds that take pins
PINNABLE_KINDS = ("dm", "agent_service", "group", "org", "room")


def refusal(conv_kind: str, msg_kind: str, *, deleted: bool, pins_now: int, already: bool) -> Optional[str]:
    """Why a message may not be pinned now, or None."""
    if conv_kind not in PINNABLE_KINDS:
        return "this kind of thread keeps no pins"
    if deleted:
        return "this message was taken back"
    if msg_kind == "system":
        return "a system line is not pinned"
    if not already and pins_now >= MAX_PINS:
        return f"a thread keeps {MAX_PINS} pins: take one off first"
    return None
