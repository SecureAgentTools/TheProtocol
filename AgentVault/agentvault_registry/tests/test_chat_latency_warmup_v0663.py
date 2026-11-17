"""V0663 (gwo_e9f20345d264d17b38c084c5, session-tester): the cross-frame chat latency guardrail warms up before it times.

The V0662 pair proof's run 1 (nt261114x1) failed the guardrail on its 95th percentile alone, 1.042 s against 1.0 s,
with every message seen and the slowest at 1.084 s; its leg ran 33 s after the pair was ready. Run 3, on a pair with
nothing beside it, passed. A fresh pair's first deliveries are slower than its settled ones (the first relays, the
first outbox drains, cold connections), so the flow now sends untimed warm-up rounds through the opened thread, each way,
until a round is seen whole within the 95th-percentile limit, and only then times its bursts. The limits stay.

Offline: the flow's steps are scripted (no rig): `_timed` answers from a script in call order, so a pair whose first
two deliveries rounds are slow is played. RED on v0663/cut ededff4bf (the flow times the slow first minute).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from agentvault_registry.api_tests.federation_suite.tests import test_chat_g1_federation as G1
from agentvault_registry.api_tests.federation_suite.tests import test_chat_latency_federation as LAT

SLOW, FAST = 1.6, 0.4


def _samples(direction: str, n: int, latency: float) -> List[Dict[str, Any]]:
    return [{"dir": direction, "i": i, "body": f"{direction} {i}", "latency_s": latency, "refused": None,
             "conversation_id": "conv-o" if direction == "outsider:knock" else None} for i in range(n)]


class _Script:
    """`_timed` in call order: the first `cold` calls are slow (a fresh pair's first deliveries), the rest fast."""

    def __init__(self, cold: int):
        self.cold, self.calls = cold, []

    async def timed(self, rig, direction, sends, reader_label, reader, reader_conv=None, find_conv=None):
        self.calls.append(direction)
        slow = len(self.calls) <= self.cold
        return _samples(direction, len(sends), SLOW if slow else FAST)


@pytest.fixture
def scripted(monkeypatch):
    def install(cold: int) -> _Script:
        sc = _Script(cold)

        async def frames(_rig):
            return {G1._A: "https://a.example", G1._B: "https://b.example"}

        async def owner(_rig, label, mine):
            return label

        async def agent(_rig, label, tag, made):
            return {"did": f"did:{tag}", "jwt": f"jwt:{tag}", "name": tag, "label": label}

        async def hook(_rig, label, events, hooks):
            return f"hook-{label}"

        async def send(_rig, label, speaker, body, **target):
            if "target_remote_key" in target:
                return {"conversation_id": "conv-host", "federated": True, "created": True}, None
            return {"message": {"relayed": True, "host_seq": 2}}, None

        async def until(fn, budget, every=3.0):
            return await fn()

        async def mirror_of(_rig, speaker, key, lane):
            return "conv-mirror"

        async def told(*_a, **_k):
            return []

        async def cleanup(*_a, **_k):
            return []
        for mod, name, fn in ((LAT, "_frames", frames), (G1, "_owner", owner), (LAT, "_agent", agent),
                              (LAT, "_hook", hook), (LAT, "_send", send), (LAT, "_until", until),
                              (LAT, "_mirror_of", mirror_of), (LAT, "_told", told), (G1, "_cleanup", cleanup),
                              (LAT, "_timed", sc.timed)):
            monkeypatch.setattr(mod, name, fn)
        return sc
    return install


def _legs(res) -> Dict[str, bool]:
    return res.last_state["legs"]


def test_a_slow_first_minute_does_not_fail_the_guardrail(scripted):
    sc = scripted(cold=2)          # the first two delivery rounds are slow, as a fresh pair's are
    res = asyncio.run(LAT.test_chat_latency(object()))
    legs = _legs(res)
    assert legs["p95_within_limit"] and legs["no_message_over_max"] and legs["no_message_lost"], res.failure_detail
    warm = [c for c in sc.calls if c.startswith("warmup")]
    timed = [c for c in sc.calls if not c.startswith("warmup")]
    assert warm and sc.calls.index(timed[0]) > sc.calls.index(warm[-1]), "every warm-up round comes before the timing"
    ev = res.last_state["evidence"]["p95_within_limit"]
    assert ev["warm_up"]["settled"] is True and ev["warm_up"]["rounds"] >= 2


def test_the_warm_up_is_bounded_and_said_when_it_never_settles(scripted):
    sc = scripted(cold=99)         # a pair that never gets fast: the warm-up stops at its bound, the timing judges
    res = asyncio.run(LAT.test_chat_latency(object()))
    assert not _legs(res)["p95_within_limit"], "the limits stay: a slow pair still fails"
    warm = [c for c in sc.calls if c.startswith("warmup")]
    assert len(warm) == LAT.WARMUP_ROUNDS, "the rounds are bounded"
    ev = res.last_state["evidence"]["p95_within_limit"]
    assert ev["warm_up"]["settled"] is False and "within" in ev["warm_up"]["why"]


def test_the_warm_up_is_never_counted_and_the_limits_stay():
    assert (LAT.CHAT_LATENCY_MAX_S, LAT.CHAT_LATENCY_P95_S, LAT.CHAT_LATENCY_LOST_S) == (2.0, 1.0, 30.0)
    assert LAT.WARMUP_ROUNDS >= 1 and LAT.WARMUP_PER_ROUND >= 1


def test_the_warm_up_never_relays_from_the_mirror(scripted):
    # the live check on nt261114x4 (06:43Z): a B->A warm-up put the mirror's agent past its 12 relays a thread a minute
    # (FED_RL relay_agent_thread) and the timed burst lost 2 of 10 in each of 3 runs; the warm-up sends from the host
    sc = scripted(cold=99)
    asyncio.run(LAT.test_chat_latency(object()))
    warm = [c for c in sc.calls if c.startswith("warmup")]
    assert warm and all(c.endswith(":A->B") for c in warm), warm
    assert 1 + LAT.PER_BURST <= 12, "the accept and one timed B->A burst stay inside the mirror's relay cap"
