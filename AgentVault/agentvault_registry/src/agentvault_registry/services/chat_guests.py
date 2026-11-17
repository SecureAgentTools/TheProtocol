"""V0662 (OurChat lane, the organizations package's item 8): a guest seat in an organization's room.

The case: the sessions' own room is an organization's room, and a session of another organization (TheProtocol Quantum's) could
not join it without leaving its own. A GUEST SEAT is an explicit participant row, seated by the room's owner or an admin of the
organization, for ONE named principal (an agent by its DID, or a developer by id). A guest reads and posts in that one room and
gains nothing else of the organization: no organization data, no work-order door, no other room, no admin sheet.

The §ORGLEAK rule holds (CLAUDE.md PART 1): a seat is never derived from a membership and a membership is never derived from a
seat. The live organization table still decides a MEMBER's role on every touch; the seat is a flag on the participant row that
decides only whether a seat remains when there is no live membership. So: an organization's membership sync neither drops
a guest row nor turns it into a member; removing a member does not touch a guest, and a removed member who is also a guest
keeps only the guest seat; a guest may leave at any time (the seat ends); the owner or an admin may remove a guest at any time.

This module is the pure rules (who may seat whom); the writes are services/chat_service.py::seat_guest / remove_guest.
"""
from __future__ import annotations

from typing import Optional

#: guests one room holds (a seat is a decision per person; a room that wants more is a membership)
MAX_GUESTS = 20
#: who may seat and remove guests: the organization's owner and admins (the room's operators)
SEATING_ROLES = ("owner", "admin")


def seating_refusal(*, actor_org_role: Optional[str], is_org_room: bool, target_is_live_member: bool, target_is_self: bool,
                    already_guest: bool, guests_now: int) -> Optional[str]:
    """Why a guest may not be seated now, or None. One sentence a person can act on."""
    if not is_org_room:
        return "guests sit in an organization's room"
    if actor_org_role not in SEATING_ROLES:
        return "only the organization's owners and admins seat a guest"
    if target_is_self:
        return "you do not need a guest seat in your own organization's room"
    if target_is_live_member:
        return "they are already a member of this organization: the room is theirs"
    if not already_guest and guests_now >= MAX_GUESTS:
        return f"a room holds {MAX_GUESTS} guests at most: remove one first"
    return None
