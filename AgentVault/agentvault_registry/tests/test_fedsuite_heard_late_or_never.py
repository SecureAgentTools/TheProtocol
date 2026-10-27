"""§MCPTEST30 (2026-10-06): a chat leg that asks whether an owner was told, and heard nothing in its window, is asked
once more before the flow deletes its hook, so the evidence can tell LATE from STILL NOTHING from UNREADABLE.

Fed run 556a8afd: control_w_to_n_reaches_ns_owner heard nothing in 45 s while the message had reached the host on time
(host seq 3, 10:35:14Z); the dispatcher's record went with the hook, so nothing was left to tell late from never.
"""
from __future__ import annotations

import asyncio

from agentvault_registry.api_tests.federation_suite.tests import test_chat_g1_federation as G1


def _seq(*answers):
    it = iter(answers)
    calls = []

    async def told():
        calls.append(1)
        return next(it)
    return told, calls


def test_a_missed_leg_is_reread_once_and_says_what_it_saw_then():
    legs = G1._Legs(["late", "never", "unreadable", "raised", "heard"])
    late, _ = _seq([], [{"conversation_id": "c"}])
    never, _ = _seq([], [])
    unreadable, _ = _seq([], None)

    async def raised_after_first():
        if raised_after_first.n:
            raise RuntimeError("boom")
        raised_after_first.n += 1
        return []
    raised_after_first.n = 0
    heard, heard_calls = _seq([{"conversation_id": "c"}])

    async def go():
        for name, fn in (("late", late), ("never", never), ("unreadable", unreadable), ("raised", raised_after_first),
                         ("heard", heard)):
            await legs.heard(name, fn, 0.0)
        await legs.reread_misses()
    asyncio.run(go())

    ev = legs.evidence
    assert ev["late"]["at_cleanup"] == "heard late, after the window" and ev["late"]["late"] == [{"conversation_id": "c"}]
    assert ev["never"]["at_cleanup"] == "still nothing" and ev["never"]["late"] == []
    assert ev["unreadable"]["at_cleanup"] == "the record could not be read" and ev["unreadable"]["late"] is None
    assert ev["raised"]["at_cleanup"].startswith("the record could not be read: RuntimeError")
    assert ev["late"]["deliveries"] == [], "the window's own answer is kept beside the re-read"
    assert ev["heard"] == {"deliveries": [{"conversation_id": "c"}]} and len(heard_calls) == 1, \
        "a leg that heard is never asked again"
    res = legs.result("d", 0.0)
    assert res.passed is False
    assert {k for k, ok in legs.got.items() if not ok} == {"late", "never", "unreadable", "raised"}, \
        "a late answer is still a miss of the window"


def test_the_flow_rereads_before_it_deletes_the_hooks(monkeypatch):
    order = []

    async def cleanup(_rig, _made, _hooks):
        order.append("cleanup")
        return []

    monkeypatch.setattr(G1, "_cleanup", cleanup)

    async def body(legs, made, hooks):
        async def told():
            order.append("told")
            return []
        await legs.heard("control", told, 0.0)

    res = asyncio.run(G1._run(object(), ["control"], "d", body))
    assert order == ["told", "told", "cleanup"], order
    assert res.passed is False
    assert res.last_state["evidence"]["control"]["at_cleanup"] == "still nothing"
