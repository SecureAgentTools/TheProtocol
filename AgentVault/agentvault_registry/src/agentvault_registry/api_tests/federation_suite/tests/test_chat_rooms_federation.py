"""Cross-frame rooms (V0659 (f); the Commander's question at seq 1789: what happens when someone from another frame is
invited to, or joins, an open chat; the design: sessionlogs2026/DESIGN_2026-11-07_XFRAME_ROOMS.md).

A room is hosted for life by the registry it was opened on; a member on the other frame joins it by its address
through its OWN registry, which keeps a copy of the room and relays the member's messages to the host. The host alone
moderates. These flows drive both frames' admin developers through the routes the console uses:

  * chat_rooms_an_outsider_joins_posts_is_muted_and_removed: sandbox-A opens an 'anyone' room; sandbox-B's developer
    joins it by address; each side's message reaches the other's copy; the host mutes B's member and B's next message
    is refused; unmuted, it speaks again; removed, it is refused for good;
  * chat_rooms_a_request_waits_for_the_owner: a 'request' room seats B's join pending until A's owner accepts it, and
    B's copy then reads active.

The binding rule (a registry joins only its own residents) needs a peer that lies about its residents; the registry's
own tests hold it (tests/test_chat_rooms_host_v0659.py).

⚠ Writes: two rooms on sandbox-A (there is no delete rail for a thread; they keep their history), a handful of
messages, both frames' admin developers seated in them. No money moves.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig, AssertionResult
from agentvault_registry.api_tests.federation_suite.tests.test_chat_g1_federation import (
    _A, _ADMIN, _B, _REQUIRES, _Legs, _frames, _read, _run, _send, _until,
)

_TAG = "fedsuite-rooms"
_SEEN_SEC = 30.0


async def _api(rig, label: str, method: str, endpoint: str, body: Optional[Dict[str, Any]] = None
               ) -> Tuple[int, Any]:
    """One REST call as the frame's admin developer (adminRequest) -> (status, body)."""
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    try:
        r = await rig.mcp(_ADMIN[label]).call("adminRequest", args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


def _has(page: Any, body: str) -> bool:
    return isinstance(page, dict) and any(isinstance(m, dict) and m.get("body") == body
                                          for m in page.get("messages") or [])


async def _sees(rig, label: str, conv: str, body: str) -> bool:
    async def look():
        page, _ = await _read(rig, label, None, conv)
        return _has(page, body)
    return bool(await _until(look, _SEEN_SEC, every=1.0))


async def _open(rig, legs: _Legs, rule: str) -> Optional[Dict[str, Any]]:
    st, room = await _api(rig, _A, "POST", "/api/v1/chat/rooms",
                          {"title": f"{_TAG} {rule} {uuid.uuid4().hex[:6]}", "join_rule": rule})
    ok = st == 201 and isinstance(room, dict) and str(room.get("address") or "").startswith("room:")
    legs.check("the_room_opens_on_a", ok, {"status": st, "answer": room})
    return room if ok else None


async def _b_member_key(rig, conv: str) -> Optional[str]:
    st, info = await _api(rig, _A, "GET", f"/api/v1/chat/rooms/{conv}")
    if st != 200 or not isinstance(info, dict):
        return None
    remote = [m for m in info.get("members") or [] if m.get("remote")]
    return remote[0]["key"] if len(remote) == 1 else None


@federation_test(
    name="chat_rooms_an_outsider_joins_posts_is_muted_and_removed",
    category="chat_federation",
    budget_sec=300.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "rooms", "cross_frame", "v0659"],
)
async def test_rooms_outsider(rig: FederationTestRig) -> AssertionResult:
    """sandbox-B's developer joins sandbox-A's 'anyone' room by its address, speaks both ways, is muted, unmuted and
    removed by the host (the module docstring has the whole story)."""
    async def body(legs: _Legs, made, hooks) -> None:
        await _frames(rig)
        room = await _open(rig, legs, "anyone")
        if not room:
            return
        host_conv = room["conversation_id"]
        st, joined = await _api(rig, _B, "POST", "/api/v1/chat/rooms/join", {"address": room["address"]})
        mirror = joined.get("conversation_id") if isinstance(joined, dict) else None
        if not legs.check("the_outsider_joins_by_address",
                          st == 200 and isinstance(joined, dict) and joined.get("state") == "active"
                          and joined.get("local") is False and bool(mirror), {"status": st, "answer": joined}):
            return
        said_b = f"{_TAG} from b {uuid.uuid4().hex[:6]}"
        _, refused = await _send(rig, _B, None, said_b, conversation_id=mirror)
        legs.check("the_outsiders_message_reaches_the_host", not refused and await _sees(rig, _A, host_conv, said_b),
                   {"refused": refused})
        said_a = f"{_TAG} from a {uuid.uuid4().hex[:6]}"
        _, refused = await _send(rig, _A, None, said_a, conversation_id=host_conv)
        legs.check("the_hosts_message_reaches_the_outsider", not refused and await _sees(rig, _B, mirror, said_a),
                   {"refused": refused})
        key = await _b_member_key(rig, host_conv)
        if not legs.check("the_host_lists_the_outsider", bool(key), {"key": key}):
            return
        st_m, _ = await _api(rig, _A, "POST", f"/api/v1/chat/rooms/{host_conv}/act", {"action": "mute", "member": key})
        _, refused = await _send(rig, _B, None, f"{_TAG} while muted", conversation_id=mirror)
        legs.check("a_muted_outsider_is_refused", st_m == 200 and bool(refused) and "muted" in str(refused),
                   {"mute": st_m, "refused": refused})
        st_u, _ = await _api(rig, _A, "POST", f"/api/v1/chat/rooms/{host_conv}/act", {"action": "unmute", "member": key})
        again = f"{_TAG} unmuted {uuid.uuid4().hex[:6]}"
        _, refused = await _send(rig, _B, None, again, conversation_id=mirror)
        legs.check("unmuted_it_speaks_again", st_u == 200 and not refused and await _sees(rig, _A, host_conv, again),
                   {"unmute": st_u, "refused": refused})
        st_r, _ = await _api(rig, _A, "POST", f"/api/v1/chat/rooms/{host_conv}/act", {"action": "remove", "member": key})
        _, refused = await _send(rig, _B, None, f"{_TAG} after removal", conversation_id=mirror)
        legs.check("a_removed_outsider_is_refused", st_r == 200 and bool(refused), {"remove": st_r, "refused": refused})

    return await _run(rig, ["the_room_opens_on_a", "the_outsider_joins_by_address",
                            "the_outsiders_message_reaches_the_host", "the_hosts_message_reaches_the_outsider",
                            "the_host_lists_the_outsider", "a_muted_outsider_is_refused", "unmuted_it_speaks_again",
                            "a_removed_outsider_is_refused"],
                      "a member on another frame joins a room by address, speaks both ways, and the host moderates",
                      body)


@federation_test(
    name="chat_rooms_a_request_waits_for_the_owner",
    category="chat_federation",
    budget_sec=180.0,
    severity="high",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "rooms", "cross_frame", "v0659"],
)
async def test_rooms_request(rig: FederationTestRig) -> AssertionResult:
    """A 'request' room seats a join from the other frame pending until the host's owner accepts it."""
    async def body(legs: _Legs, made, hooks) -> None:
        await _frames(rig)
        room = await _open(rig, legs, "request")
        if not room:
            return
        host_conv = room["conversation_id"]
        st, joined = await _api(rig, _B, "POST", "/api/v1/chat/rooms/join", {"address": room["address"]})
        mirror = joined.get("conversation_id") if isinstance(joined, dict) else None
        if not legs.check("the_join_waits_pending", st == 200 and isinstance(joined, dict)
                          and joined.get("state") == "pending" and bool(mirror), {"status": st, "answer": joined}):
            return
        key = await _b_member_key(rig, host_conv)
        st_a, _ = await _api(rig, _A, "POST", f"/api/v1/chat/rooms/{host_conv}/act", {"action": "accept", "member": key})
        t0 = time.monotonic()

        async def seated():
            s, info = await _api(rig, _B, "GET", f"/api/v1/chat/rooms/{mirror}")
            return s == 200 and isinstance(info, dict) and info.get("my_state") == "active"
        ok = bool(await _until(seated, _SEEN_SEC, every=1.0))
        legs.check("the_owners_accept_seats_it_on_its_own_frame", st_a == 200 and ok,
                   {"accept": st_a, "key": key, "within_s": round(time.monotonic() - t0, 1)})

    return await _run(rig, ["the_room_opens_on_a", "the_join_waits_pending",
                            "the_owners_accept_seats_it_on_its_own_frame"],
                      "a join from another frame waits for the room owner's accept", body)
