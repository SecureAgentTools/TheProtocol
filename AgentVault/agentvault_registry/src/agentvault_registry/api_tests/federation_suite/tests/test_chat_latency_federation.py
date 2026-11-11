"""The cross-frame chat latency guardrail (V0658 (m); the Commander's word in the sessions' room, seq 1780; the limits,
session-lead's seq 1786).

His ask: a sandbox test that fails when cross-frame chat does not arrive within a set time, under simulated traffic.
A message is timed from just before its send to its first appearance in the OTHER frame's copy of the thread, read
every 200 ms by the reader's own agent:

  * a thread opens between an agent on each frame (a knock, accepted by the reply);
  * 3 bursts of 10 messages at 5 a second, alternating direction: the host's member to the other frame's, then back
    through the relay, then out again;
  * a fresh outsider from the other frame knocks the host's member (its first message: the knock) and sends 5.

It FAILS when any message takes over CHAT_LATENCY_MAX_S, when the 95th percentile is over CHAT_LATENCY_P95_S, or when
any message is not seen within CHAT_LATENCY_LOST_S (lost). V0658 (m) set them to hold the measure of its day (the
host's queue delivered in about 0.9 s, 1.4 s at the 95th percentile, 1.8 s at worst: session-lead, seq 1784) and to
catch any slide back toward the old 20-40 s. V0659's speed work (g) tightened them to a 95th percentile of 1.0 s and a maximum of 2.0 s, which
the measure below (taken before (g)) fails at the 95th percentile.

What a figure includes: the reader's poll (up to 200 ms) and one MCP read's own time, so a figure is an upper bound on
the delivery. The owners' hooks (chat.message.received) are read once at the end and kept beside the figures as
evidence; they do not decide the verdict (D6-826's hook legs are chat_g1's). That count is a floor: a hook to an
`.invalid` host fails every delivery and the dispatcher disables it after 10 failures, so a side reads at most 10.

Measured on the sandbox pair, 2026-11-07 21:48Z (V0657's third recut 9087116da363): 36 of 36 seen, none lost; p50
0.955 s, p95 1.554 s, max 1.628 s; A to B p50 about 1.1 s, B to A (through the relay) 0.46 s, the outsider's knock
0.665 s and its five messages max 1.554 s.

⚠ Writes: throwaway agents `fedsuite-lat-*` (two on sandbox-B, one on sandbox-A), retired at the end; two threads (no
delete-thread rail); about 40 messages. No money moves.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig, AssertionResult
from agentvault_registry.api_tests.federation_suite.tests.test_chat_g1_federation import (
    _A, _B, _REQUIRES, _Legs, _agent, _frames, _hook, _key, _mirror_of, _posted, _read, _run, _send, _told, _until,
)

# ── the limits (V0659 (g): 2.0 s and 1.0 s, tightened from V0658 (m)'s 6.0 s and 2.5 s) ────────────────────────────
CHAT_LATENCY_MAX_S = 2.0      # any one message over this fails the test
CHAT_LATENCY_P95_S = 1.0      # the 95th percentile over this fails the test
CHAT_LATENCY_LOST_S = 30.0    # a message not seen within this is lost, and fails the test

BURSTS = 3                    # alternating direction: A to B, B to A, A to B
PER_BURST = 10
RATE_PER_S = 5.0
OUTSIDER_MESSAGES = 5
POLL_S = 0.2

logger = logging.getLogger(__name__)

_TAG = "fedsuite-lat"
_OPEN_SEC = 45.0              # the thread's own opening (a knock and its accept), not a timed message


def percentile(values: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile of `values` (None for no values)."""
    if not values:
        return None
    s = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(s)))
    return s[rank - 1]


def judge(samples: List[Dict[str, Any]], max_s: float = CHAT_LATENCY_MAX_S, p95_s: float = CHAT_LATENCY_P95_S,
          lost_s: float = CHAT_LATENCY_LOST_S) -> Dict[str, Any]:
    """The verdict over every timed message. A sample is {"dir", "i", "latency_s" (None: not seen), "refused"}.
    A refused send is never a fast message: it counts as lost (the guardrail is about arriving)."""
    seen = [s["latency_s"] for s in samples if s.get("latency_s") is not None and not s.get("refused")]
    lost = [s for s in samples if s.get("refused") or s.get("latency_s") is None or s["latency_s"] > lost_s]
    over = [s for s in samples if s.get("latency_s") is not None and max_s < s["latency_s"] <= lost_s]
    p95 = percentile(seen, 95)
    by_dir: Dict[str, Dict[str, Any]] = {}
    for d in sorted({s["dir"] for s in samples}):
        vals = [s["latency_s"] for s in samples if s["dir"] == d and s.get("latency_s") is not None]
        by_dir[d] = {"n": sum(1 for s in samples if s["dir"] == d), "seen": len(vals),
                     "p50": percentile(vals, 50), "p95": percentile(vals, 95), "max": max(vals) if vals else None}
    return {
        "n": len(samples), "seen": len(seen), "lost": len(lost), "over_max": len(over),
        "p50": percentile(seen, 50), "p95": p95, "max": max(seen) if seen else None,
        "no_message_lost": not lost and bool(samples),
        "no_message_over_max": not over and bool(samples),
        "p95_within_limit": p95 is not None and p95 <= p95_s,
        "limits": {"max_s": max_s, "p95_s": p95_s, "lost_s": lost_s},
        "by_direction": by_dir,
        "lost_messages": [{k: s.get(k) for k in ("dir", "i", "refused")} for s in lost][:20],
        "slowest": sorted((s for s in samples if s.get("latency_s") is not None),
                          key=lambda s: -s["latency_s"])[:5],
    }


async def _timed(rig, direction: str, sends: List[Tuple[str, Dict[str, Any], str]], reader_label: str,
                 reader: Dict[str, str], reader_conv: Optional[str] = None,
                 find_conv=None) -> List[Dict[str, Any]]:
    """Send each (label, speaker, conversation) message on a 1/RATE_PER_S schedule, each timed from just before its
    send; one poller reads `reader`'s copy every POLL_S and stamps a body the first time it shows. `find_conv`, for a
    thread the reader does not hold yet (the outsider's knock), is asked until it names the reader's copy."""
    bodies = [f"{_TAG} {direction} {i} {uuid.uuid4().hex[:8]}" for i in range(len(sends))]
    sent_at: Dict[str, float] = {}
    seen_at: Dict[str, float] = {}
    refused: Dict[str, str] = {}
    answered: Dict[str, Any] = {}
    conv = {"id": reader_conv}
    done = asyncio.Event()

    async def one(i: int, label: str, speaker: Dict[str, str], target: Dict[str, Any]) -> None:
        b = bodies[i]
        sent_at[b] = time.monotonic()
        r, ref = await _send(rig, label, speaker, b, **target)
        if ref:
            refused[b] = str(ref)[:160]
        elif isinstance(r, dict):
            answered[b] = r.get("conversation_id")

    async def poll() -> None:
        while not done.is_set():
            if conv["id"] is None and find_conv is not None:
                conv["id"] = await find_conv()
            if conv["id"] is not None:
                page, _ = await _read(rig, reader_label, reader, conv["id"])
                now = time.monotonic()
                if isinstance(page, dict):
                    for m in page.get("messages") or []:
                        b = (m or {}).get("body") if isinstance(m, dict) else None
                        if b in sent_at and b not in seen_at:
                            seen_at[b] = now
            if len(sent_at) == len(bodies):
                if all(b in seen_at or b in refused for b in bodies):
                    return
                if time.monotonic() - max(sent_at.values()) > CHAT_LATENCY_LOST_S:
                    return
            await asyncio.sleep(POLL_S)

    poller = asyncio.create_task(poll())
    start = time.monotonic()
    tasks = []
    for i, (label, speaker, target) in enumerate(sends):
        wait = start + i / RATE_PER_S - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        tasks.append(asyncio.create_task(one(i, label, speaker, target)))
    await asyncio.gather(*tasks)
    try:
        await asyncio.wait_for(poller, CHAT_LATENCY_LOST_S + 15)
    except asyncio.TimeoutError:
        done.set()
        poller.cancel()
    done.set()
    return [{"dir": direction, "i": i, "body": b,
             "latency_s": round(seen_at[b] - sent_at[b], 3) if b in seen_at and b in sent_at else None,
             "refused": refused.get(b), "conversation_id": answered.get(b)} for i, b in enumerate(bodies)]


@federation_test(
    name="chat_latency_cross_frame_under_traffic",
    category="chat_federation",
    budget_sec=360.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "latency", "cross_frame", "guardrail"],
)
async def test_chat_latency(rig: FederationTestRig) -> AssertionResult:
    """Cross-frame chat arrives within the limits under simulated traffic (the module docstring has the numbers)."""
    async def body(legs: _Legs, made, hooks) -> None:
        base = await _frames(rig)
        n = await _agent(rig, _A, "lat-n", made)
        w = await _agent(rig, _B, "lat-w", made)
        n_key, w_key = _key(n["did"], base[_A]), _key(w["did"], base[_B])
        hook_a = await _hook(rig, _A, ["chat.message.received"], hooks)
        hook_b = await _hook(rig, _B, ["chat.message.received"], hooks)

        # the thread: N (sandbox-A, the host) knocks W (sandbox-B); W's reply accepts it
        r, refused = await _send(rig, _A, n, f"{_TAG} knock", target_remote_key=w_key)
        host_conv = r.get("conversation_id") if isinstance(r, dict) and not refused else None
        mirror = await _until(lambda: _mirror_of(rig, w, n_key, "requests"), _OPEN_SEC) if host_conv else None
        acc, aref = (await _send(rig, _B, w, f"{_TAG} accept", conversation_id=mirror)) if mirror else (None, "no mirror")
        opened = bool(host_conv and mirror and not aref and (_posted(acc) or {}).get("relayed") is True)
        if not legs.check("the_thread_opens", opened, {"host_conv": host_conv, "mirror": mirror,
                                                       "knock_refused": refused, "accept_refused": aref}):
            return

        samples: List[Dict[str, Any]] = []
        for b in range(BURSTS):
            if b % 2 == 0:   # the host's member to the other frame's
                sends = [(_A, n, {"conversation_id": host_conv})] * PER_BURST
                samples += await _timed(rig, f"burst{b + 1}:A->B", sends, _B, w, mirror)
            else:            # back through the relay
                sends = [(_B, w, {"conversation_id": mirror})] * PER_BURST
                samples += await _timed(rig, f"burst{b + 1}:B->A", sends, _A, n, host_conv)

        # the outsider: a fresh agent on sandbox-B, its first message the knock, then five
        o = await _agent(rig, _B, "lat-o", made)
        o_key = _key(o["did"], base[_B])
        knock = await _timed(rig, "outsider:knock", [(_B, o, {"target_remote_key": n_key})], _A, n,
                             find_conv=lambda: _mirror_of(rig, n, o_key, "requests"))
        samples += knock
        o_conv = knock[0].get("conversation_id")          # the outsider's own thread, as its knock answered it
        n_mirror = await _mirror_of(rig, n, o_key, "requests")
        if n_mirror:
            await _send(rig, _A, n, f"{_TAG} welcome", conversation_id=n_mirror)   # the accept, as above
        if legs.check("the_outsider_reaches_the_host_member", bool(n_mirror and o_conv),
                      {"o_conv_on_b": o_conv, "n_mirror_on_a": n_mirror}):
            sends = [(_B, o, {"conversation_id": o_conv})] * OUTSIDER_MESSAGES
            samples += await _timed(rig, "outsider:B->A", sends, _A, n, n_mirror)

        verdict = judge(samples)
        # beside the figures, not deciding them: how many of the timed messages the owners' hooks were told about
        told: Dict[str, Any] = {}
        for label, hook, conv in ((_B, hook_b, mirror), (_A, hook_a, host_conv)):
            got = await _told(rig, label, hook, "chat.message.received", conv)
            told[label] = None if got is None else sum(
                1 for d in got if str(((d.get("message") or {}).get("body")) or "").startswith(f"{_TAG} burst"))
        evidence = {k: verdict[k] for k in ("n", "seen", "lost", "over_max", "p50", "p95", "max", "limits",
                                            "by_direction", "lost_messages", "slowest")}
        evidence["owners_hooks_told"] = told
        # the figures on every run, a pass included (a passing outcome keeps its legs, not their evidence): counts and
        # seconds as scalars (the tester's log gate, test_tester_logs_v0653: no whole value in a log line)
        directions = " ".join(f"{d}:n={v['n']},seen={v['seen']},p50={v['p50']},p95={v['p95']},max={v['max']}"
                              for d, v in verdict["by_direction"].items())
        logger.info("[FederationSuite] chat latency: n=%s seen=%s lost=%s over_max=%s p50=%s p95=%s max=%s "
                    "hooks_told_a=%s hooks_told_b=%s %s", verdict["n"], verdict["seen"], verdict["lost"],
                    verdict["over_max"], verdict["p50"], verdict["p95"], verdict["max"], told.get(_A), told.get(_B),
                    directions)
        legs.check("no_message_lost", verdict["no_message_lost"], evidence)
        legs.check("no_message_over_max", verdict["no_message_over_max"], {"over_max": verdict["over_max"],
                                                                           "slowest": verdict["slowest"]})
        legs.check("p95_within_limit", verdict["p95_within_limit"], {"p95": verdict["p95"],
                                                                     "limit": CHAT_LATENCY_P95_S})

    return await _run(rig, ["the_thread_opens", "the_outsider_reaches_the_host_member", "no_message_lost",
                            "no_message_over_max", "p95_within_limit"],
                      "cross-frame chat arrives within the latency limits under simulated traffic", body)
