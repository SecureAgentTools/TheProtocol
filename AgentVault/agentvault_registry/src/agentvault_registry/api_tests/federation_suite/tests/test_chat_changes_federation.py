"""Changes to a message across frames (V0663, order gwo_9dce94d939aff2fa8ea4f91c): an edit, a take-back, a reaction, a pin, and a
room's archive or close, in a cross-frame room (services/chat_fed_events.py). The host alone decides and tells every frame; a member on
the other frame asks it. These flows drive both frames' admin developers through the routes the console uses, over a room sandbox-A
hosts and sandbox-B's developer joins by address (test_chat_rooms_federation's door):

  * chat_changes_edit_and_take_back: B edits its own line (A's copy and B's follow the host), the host cannot edit B's line, A edits
    its own line (B's copy follows), B takes its line back (A's copy shows the tombstone);
  * chat_changes_reactions_and_pins: B reacts to A's line and takes the reaction off (both copies' counts follow), B cannot pin in A's
    room, A pins and unpins (B's pin list follows);
  * chat_changes_archive_and_close: A archives the room (B's copy says archived, B's post is refused, unarchived it speaks again), and
    A closes an empty second room (B's copy of it is gone).

Not carried, on the record: state from before a registry joined (earlier reactions and pins on lines it never saw): the events are live.

⚠ Writes: three rooms on sandbox-A (a closed one goes; the others keep their history), a handful of messages, both frames' admin
developers seated in them. No money moves.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig, AssertionResult
from agentvault_registry.api_tests.federation_suite.tests.test_chat_g1_federation import (
    _A, _B, _REQUIRES, _Legs, _frames, _read, _run, _send, _until,
)
from agentvault_registry.api_tests.federation_suite.tests.test_chat_rooms_federation import _api, _open

_TAG = "fedsuite-changes"
_SEEN_SEC = 40.0


async def _joined(rig, legs: _Legs, rule: str = "anyone"):
    """Open a room on A and have B's developer join it; returns (host conversation, B's mirror) or None."""
    room = await _open(rig, legs, rule)
    if not room:
        return None
    st, joined = await _api(rig, _B, "POST", "/api/v1/chat/rooms/join", {"address": room["address"]})
    mirror = joined.get("conversation_id") if isinstance(joined, dict) else None
    if not legs.check("the_outsider_joins_by_address",
                      st == 200 and isinstance(joined, dict) and joined.get("state") == "active" and bool(mirror),
                      {"status": st, "answer": joined}):
        return None
    return room["conversation_id"], mirror


async def _line(rig, label: str, conv: str, body: str) -> Optional[Dict[str, Any]]:
    """The message of this thread, on this frame, whose body is `body` (None while it has not arrived)."""
    page, _ = await _read(rig, label, None, conv)
    for m in (page.get("messages") if isinstance(page, dict) else None) or []:
        if isinstance(m, dict) and m.get("body") == body:
            return m
    return None


async def _by_id(rig, label: str, conv: str, mid: str) -> Optional[Dict[str, Any]]:
    page, _ = await _read(rig, label, None, conv)
    for m in (page.get("messages") if isinstance(page, dict) else None) or []:
        if isinstance(m, dict) and m.get("id") == mid:
            return m
    return None


async def _arrives(rig, label: str, conv: str, body: str) -> Optional[Dict[str, Any]]:
    async def look():
        return await _line(rig, label, conv, body)
    return await _until(look, _SEEN_SEC, every=1.0)


async def _becomes(rig, label: str, conv: str, mid: str, check) -> Optional[Dict[str, Any]]:
    async def look():
        m = await _by_id(rig, label, conv, mid)
        return m if m is not None and check(m) else None
    return await _until(look, _SEEN_SEC, every=1.0)


def _count(m: Optional[Dict[str, Any]], word: str) -> int:
    for r in (m or {}).get("reactions") or []:
        if isinstance(r, dict) and r.get("key") == word:
            return int(r.get("count") or 0)
    return 0


@federation_test(
    name="chat_changes_edit_and_take_back",
    category="chat_federation",
    budget_sec=300.0,
    severity="high",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "rooms", "cross_frame", "v0663"],
)
async def test_changes_edit_and_take_back(rig: FederationTestRig) -> AssertionResult:
    """An edit and a take-back cross the frames both ways, under the host's rules (the module docstring has the whole story)."""
    legs_planned = ["the_room_opens_on_a", "the_outsider_joins_by_address", "an_outsiders_edit_reaches_both_copies",
                    "the_host_cannot_edit_the_outsiders_line", "a_hosts_edit_reaches_the_outsider",
                    "an_outsiders_take_back_reaches_the_host"]

    async def body(legs: _Legs, made, hooks) -> None:
        await _frames(rig)
        pair = await _joined(rig, legs)
        if not pair:
            return
        host_conv, mirror = pair
        said = f"{_TAG} first {uuid.uuid4().hex[:6]}"
        await _send(rig, _B, None, said, conversation_id=mirror)
        on_b = await _arrives(rig, _B, mirror, said)
        on_a = await _arrives(rig, _A, host_conv, said)
        if not (on_a and on_b):
            legs.check("an_outsiders_edit_reaches_both_copies", False, {"seen_on_a": bool(on_a), "seen_on_b": bool(on_b)})
            return
        newer = f"{_TAG} edited {uuid.uuid4().hex[:6]}"
        st, _ = await _api(rig, _B, "PUT", f"/api/v1/chat/conversations/{mirror}/messages/{on_b['id']}", {"body": newer})
        a_edited = await _becomes(rig, _A, host_conv, on_a["id"], lambda m: m.get("body") == newer and bool(m.get("edited_at")))
        b_edited = await _becomes(rig, _B, mirror, on_b["id"], lambda m: m.get("body") == newer and bool(m.get("edited_at")))
        legs.check("an_outsiders_edit_reaches_both_copies", st == 200 and bool(a_edited) and bool(b_edited),
                   {"status": st, "host_copy": bool(a_edited), "own_copy": bool(b_edited)})
        st_h, ans = await _api(rig, _A, "PUT", f"/api/v1/chat/conversations/{host_conv}/messages/{on_a['id']}",
                               {"body": f"{_TAG} not mine"})
        legs.check("the_host_cannot_edit_the_outsiders_line", st_h in (403, 409), {"status": st_h, "answer": ans})
        host_line = f"{_TAG} host {uuid.uuid4().hex[:6]}"
        await _send(rig, _A, None, host_line, conversation_id=host_conv)
        h_on_a = await _arrives(rig, _A, host_conv, host_line)
        h_on_b = await _arrives(rig, _B, mirror, host_line)
        hosts_new = f"{_TAG} host edited {uuid.uuid4().hex[:6]}"
        st_e = -1
        if h_on_a and h_on_b:
            st_e, _ = await _api(rig, _A, "PUT", f"/api/v1/chat/conversations/{host_conv}/messages/{h_on_a['id']}", {"body": hosts_new})
        seen = await _becomes(rig, _B, mirror, h_on_b["id"], lambda m: m.get("body") == hosts_new) if h_on_b else None
        legs.check("a_hosts_edit_reaches_the_outsider", st_e == 200 and bool(seen), {"status": st_e, "seen_on_b": bool(seen)})
        st_d, _ = await _api(rig, _B, "DELETE", f"/api/v1/chat/conversations/{mirror}/messages/{on_b['id']}")
        gone = await _becomes(rig, _A, host_conv, on_a["id"], lambda m: bool(m.get("deleted")))
        legs.check("an_outsiders_take_back_reaches_the_host", st_d == 200 and bool(gone), {"status": st_d, "tombstone_on_a": bool(gone)})

    return await _run(rig, legs_planned, "an edit and a take-back cross the frames both ways under the host's rules", body)


@federation_test(
    name="chat_changes_reactions_and_pins",
    category="chat_federation",
    budget_sec=300.0,
    severity="high",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "rooms", "cross_frame", "v0663"],
)
async def test_changes_reactions_and_pins(rig: FederationTestRig) -> AssertionResult:
    """A reaction and a pin cross the frames; a member pins nowhere in a room it does not moderate."""
    legs_planned = ["the_room_opens_on_a", "the_outsider_joins_by_address", "an_outsiders_reaction_reaches_the_host",
                    "a_taken_off_reaction_leaves_both_copies", "an_outsider_cannot_pin_in_the_hosts_room",
                    "the_hosts_pin_reaches_the_outsider", "an_unpin_reaches_the_outsider"]

    async def body(legs: _Legs, made, hooks) -> None:
        await _frames(rig)
        pair = await _joined(rig, legs)
        if not pair:
            return
        host_conv, mirror = pair
        said = f"{_TAG} react {uuid.uuid4().hex[:6]}"
        await _send(rig, _A, None, said, conversation_id=host_conv)
        on_a = await _arrives(rig, _A, host_conv, said)
        on_b = await _arrives(rig, _B, mirror, said)
        if not (on_a and on_b):
            legs.check("an_outsiders_reaction_reaches_the_host", False, {"seen_on_a": bool(on_a), "seen_on_b": bool(on_b)})
            return
        st, _ = await _api(rig, _B, "PUT", f"/api/v1/chat/conversations/{mirror}/messages/{on_b['id']}/reactions/ack")
        on_host = await _becomes(rig, _A, host_conv, on_a["id"], lambda m: _count(m, "ack") == 1)
        legs.check("an_outsiders_reaction_reaches_the_host", st == 200 and bool(on_host), {"status": st, "host_count": _count(on_host, "ack")})
        st_r, _ = await _api(rig, _B, "DELETE", f"/api/v1/chat/conversations/{mirror}/messages/{on_b['id']}/reactions/ack")
        back_a = await _becomes(rig, _A, host_conv, on_a["id"], lambda m: _count(m, "ack") == 0)
        back_b = await _becomes(rig, _B, mirror, on_b["id"], lambda m: _count(m, "ack") == 0)
        legs.check("a_taken_off_reaction_leaves_both_copies", st_r == 200 and bool(back_a) and bool(back_b),
                   {"status": st_r, "host_copy": bool(back_a), "own_copy": bool(back_b)})
        st_p, ans = await _api(rig, _B, "PUT", f"/api/v1/chat/conversations/{mirror}/messages/{on_b['id']}/pin")
        legs.check("an_outsider_cannot_pin_in_the_hosts_room", st_p in (403, 409) and "owner and moderators" in str(ans),
                   {"status": st_p, "answer": ans})
        st_a, _ = await _api(rig, _A, "PUT", f"/api/v1/chat/conversations/{host_conv}/messages/{on_a['id']}/pin")

        async def pinned(want: bool):
            async def look():
                s, p = await _api(rig, _B, "GET", f"/api/v1/chat/conversations/{mirror}/pins")
                ids = [x.get("message", {}).get("id") for x in (p.get("pins") if isinstance(p, dict) else None) or []]
                return True if (on_b["id"] in ids) == want else None
            return await _until(look, _SEEN_SEC, every=1.0)
        legs.check("the_hosts_pin_reaches_the_outsider", st_a == 200 and bool(await pinned(True)), {"status": st_a})
        st_u, _ = await _api(rig, _A, "DELETE", f"/api/v1/chat/conversations/{host_conv}/messages/{on_a['id']}/pin")
        legs.check("an_unpin_reaches_the_outsider", st_u == 200 and bool(await pinned(False)), {"status": st_u})

    return await _run(rig, legs_planned, "a reaction and a pin cross the frames under the host's rules", body)


@federation_test(
    name="chat_changes_archive_and_close",
    category="chat_federation",
    budget_sec=300.0,
    severity="high",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "rooms", "cross_frame", "v0663"],
)
async def test_changes_archive_and_close(rig: FederationTestRig) -> AssertionResult:
    """An archive follows to the other frame's copy (read, not posted in), and a close of an empty room removes it there."""
    legs_planned = ["the_room_opens_on_a", "the_outsider_joins_by_address", "an_archive_reaches_the_outsiders_copy",
                    "an_archived_room_takes_no_post_from_the_outsider", "an_unarchived_room_speaks_again",
                    "a_close_of_an_empty_room_removes_the_outsiders_copy"]

    async def body(legs: _Legs, made, hooks) -> None:
        await _frames(rig)
        pair = await _joined(rig, legs)
        if not pair:
            return
        host_conv, mirror = pair

        async def archived(want: bool):
            async def look():
                s, info = await _api(rig, _B, "GET", f"/api/v1/chat/rooms/{mirror}")
                return True if s == 200 and isinstance(info, dict) and bool(info.get("archived")) == want else None
            return await _until(look, _SEEN_SEC, every=1.0)
        st, _ = await _api(rig, _A, "POST", f"/api/v1/chat/rooms/{host_conv}/act", {"action": "archive"})
        legs.check("an_archive_reaches_the_outsiders_copy", st == 200 and bool(await archived(True)), {"status": st})
        _, refused = await _send(rig, _B, None, f"{_TAG} into the archive", conversation_id=mirror)
        legs.check("an_archived_room_takes_no_post_from_the_outsider", bool(refused) and "archived" in str(refused), {"refused": refused})
        st_u, _ = await _api(rig, _A, "POST", f"/api/v1/chat/rooms/{host_conv}/act", {"action": "unarchive"})
        again = f"{_TAG} back {uuid.uuid4().hex[:6]}"
        ok_unarch = st_u == 200 and bool(await archived(False))
        _, refused = await _send(rig, _B, None, again, conversation_id=mirror) if ok_unarch else (None, "unarchive did not reach b")
        legs.check("an_unarchived_room_speaks_again", ok_unarch and not refused and bool(await _arrives(rig, _A, host_conv, again)),
                   {"unarchive": st_u, "refused": refused})
        second = await _open(rig, legs, "anyone")
        if not second:
            return
        st_j, joined = await _api(rig, _B, "POST", "/api/v1/chat/rooms/join", {"address": second["address"]})
        m2 = joined.get("conversation_id") if isinstance(joined, dict) else None
        st_c, ans = await _api(rig, _A, "POST", f"/api/v1/chat/rooms/{second['conversation_id']}/close")

        async def gone():
            async def look():
                s, _info = await _api(rig, _B, "GET", f"/api/v1/chat/rooms/{m2}")
                return True if s in (403, 404) else None
            return await _until(look, _SEEN_SEC, every=1.0)
        legs.check("a_close_of_an_empty_room_removes_the_outsiders_copy", st_j == 200 and bool(m2) and st_c == 200 and bool(await gone()),
                   {"join": st_j, "close": st_c, "answer": ans})

    return await _run(rig, legs_planned, "an archive follows to the other frame's copy and a close of an empty room removes it there", body)
