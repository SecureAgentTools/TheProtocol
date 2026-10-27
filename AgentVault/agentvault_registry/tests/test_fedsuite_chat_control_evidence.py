"""§MCPTEST30 V0641 (agentvault2-aa, 2026-10-25, agentvault2-d6's D6-826): a chat control leg keeps what the send it
waits on answered, and a miss reads the host's thread once.

chat_g1_block_is_silent_on_both_legs' control_w_to_n_reaches_ns_owner heard nothing in 4 of the last 60 runs (nt261025
on V0638: "deliveries [], still nothing, late []"). The flow threw away the answer of the very send the leg waited on,
so a relay the host refused (relay-send's rate caps 429, 403, 404, 409, or 503 "could not be queued") and a message the
host stored but never dispatched read identically in the archive. Now the leg's evidence carries the send's answer
(_sent_view) and, on a miss, the host thread's answer (_on_host: the message there, and at which seq).
"""
from __future__ import annotations

import asyncio
import inspect

from agentvault_registry.api_tests.federation_suite.tests import test_chat_g1_federation as G1


def test_a_missed_leg_keeps_its_send_and_reads_the_host_once():
    legs = G1._Legs(["missed", "heard"])
    looked = []

    async def never():
        return []

    async def heard():
        return [{"conversation_id": "c"}]

    async def host():
        looked.append(1)
        return {"present": True, "seq": 7}

    async def go():
        await legs.heard("missed", never, 0.0, sent={"relayed": True, "host_seq": 7}, on_host=host)
        await legs.heard("heard", heard, 0.0, sent={"seq": 3}, on_host=host)
        await legs.reread_misses()
    asyncio.run(go())
    ev = legs.evidence
    assert ev["missed"]["send"] == {"relayed": True, "host_seq": 7}, "the send's answer survives the re-read"
    assert ev["missed"]["on_host"] == {"present": True, "seq": 7} and ev["missed"]["at_cleanup"] == "still nothing"
    assert ev["heard"] == {"deliveries": [{"conversation_id": "c"}], "send": {"seq": 3}}
    assert looked == [1], "the host is read once, and only for the leg that missed"


def test_a_host_read_that_raises_is_said_never_a_crash():
    legs = G1._Legs(["missed"])

    async def never():
        return []

    async def host():
        raise RuntimeError("boom")

    async def go():
        await legs.heard("missed", never, 0.0, on_host=host)
        await legs.reread_misses()
    asyncio.run(go())
    assert legs.evidence["missed"]["on_host"] == {"unread": "RuntimeError"}
    assert "send" not in legs.evidence["missed"], "no send given, none invented"


def test_the_send_view_names_a_refusal_or_the_receipt():
    assert G1._sent_view(None, "wrapped HTTP 429: too many relays") == {"refused": "wrapped HTTP 429: too many relays"}
    mirror = {"message": {"relayed": True, "host_seq": 3, "duplicate": False, "body": "x"}, "my_state": "active"}
    assert G1._sent_view(mirror, None) == {"relayed": True, "host_seq": 3, "duplicate": False}
    assert G1._sent_view({"message": {"seq": 4, "body": "x"}}, None) == {"seq": 4}
    assert G1._sent_view("odd", None) == {"answer": "odd"}


def test_the_host_read_finds_the_message_and_its_seq(monkeypatch):
    pages = {"ok": ({"messages": [{"body": "a", "seq": 1}, {"body": "the control", "seq": 5}]}, None),
             "absent": ({"messages": [{"body": "a", "seq": 1}]}, None),
             "refused": (None, "wrapped HTTP 403: not a participant")}
    which = {}

    async def read(_rig, label, agent, conv, join=False):
        which["call"] = (label, agent["did"], conv)
        return pages[which["case"]]
    monkeypatch.setattr(G1, "_read", read)
    for case, want in (("ok", {"present": True, "seq": 5}), ("absent", {"present": False, "seq": None}),
                       ("refused", {"unread": "wrapped HTTP 403: not a participant"})):
        which["case"] = case
        got = asyncio.run(G1._on_host(object(), "sandbox-A", {"did": "did:n"}, "host-conv", "the control")())
        assert got == want, (case, got)
    assert which["call"] == ("sandbox-A", "did:n", "host-conv"), "read as the host's own agent, on the host thread"


def test_the_block_flow_keeps_both_control_sends():
    src = inspect.getsource(G1.test_g1_blocks)
    for leg, var, body in (("control_n_to_w_reaches_ws_owner", "r1, ref1", "c1"),
                           ("control_w_to_n_reaches_ns_owner", "r2, ref2", "c2")):
        assert f"{var} = await _send(" in src, f"{leg}: the send's answer is kept"
        assert f"sent=_sent_view({var})" in src, f"{leg}: the send's answer is in the leg's evidence"
        assert f"on_host=_on_host(rig, _A, n, host_conv, {body})" in src, f"{leg}: a miss reads the host's thread"
    assert "        await _send(rig, _A, n, c1," not in src and "        await _send(rig, _B, w, c2," not in src, \
        "no control send whose answer is thrown away"
