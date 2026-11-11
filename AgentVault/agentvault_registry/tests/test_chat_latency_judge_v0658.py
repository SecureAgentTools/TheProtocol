"""V0658 (m): the cross-frame chat latency guardrail's verdict (api_tests/federation_suite/tests/
test_chat_latency_federation.py, judge and percentile). The flow itself runs against the sandbox pair; this pins the
rule it applies: FAIL on any message over CHAT_LATENCY_MAX_S, on a 95th percentile over CHAT_LATENCY_P95_S, or on any
message lost (not seen within CHAT_LATENCY_LOST_S, or refused at its send). New in V0658: red on the cut, which has no
such test.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.tests import test_chat_latency_federation as lat


def s(latency, d="burst1:A->B", i=0, refused=None):
    return {"dir": d, "i": i, "latency_s": latency, "refused": refused}


def test_the_limits_are_the_agreed_ones():
    # V0659 (g): tightened from V0658 (m)'s 6.0 s and 2.5 s to a maximum of 2 s and a 95th percentile of 1 s
    assert (lat.CHAT_LATENCY_MAX_S, lat.CHAT_LATENCY_P95_S, lat.CHAT_LATENCY_LOST_S) == (2.0, 1.0, 30.0)
    assert (lat.BURSTS, lat.PER_BURST, lat.RATE_PER_S, lat.OUTSIDER_MESSAGES, lat.POLL_S) == (3, 10, 5.0, 5, 0.2)


def test_percentile_is_nearest_rank():
    vals = [float(x) for x in range(1, 21)]          # 1..20
    assert lat.percentile(vals, 95) == 19.0
    assert lat.percentile(vals, 50) == 10.0
    assert lat.percentile([], 95) is None


def test_a_measure_within_the_limits_passes():
    v = lat.judge([s(0.6, i=i) for i in range(18)] + [s(0.9), s(1.8)])
    assert v["no_message_lost"] and v["no_message_over_max"] and v["p95_within_limit"]


def test_v0657s_measure_fails_the_tightened_95th_percentile():
    """The pair before (g), V0657's third recut (21:48Z): p95 1.554 s, max 1.628 s. (g)'s limits catch that speed."""
    v = lat.judge([s(0.955, i=i) for i in range(33)] + [s(1.4), s(1.554), s(1.628)])
    assert not v["p95_within_limit"] and v["p95"] == 1.554
    assert v["no_message_over_max"] and v["no_message_lost"]


def test_one_slow_message_fails_the_max():
    v = lat.judge([s(0.8, i=i) for i in range(39)] + [s(2.5)])
    assert not v["no_message_over_max"] and v["over_max"] == 1
    assert v["p95_within_limit"]                      # one in forty: the 95th percentile still holds


def test_a_slow_tail_fails_the_95th_percentile():
    v = lat.judge([s(0.8, i=i) for i in range(17)] + [s(1.5), s(1.5), s(1.5)])
    assert not v["p95_within_limit"] and v["p95"] == 1.5
    assert v["no_message_over_max"]


def test_a_message_never_seen_or_refused_is_lost_never_fast():
    for lost in (s(None), s(0.2, refused="HTTP 429"), s(31.0)):
        v = lat.judge([s(1.0, i=i) for i in range(10)] + [lost])
        assert not v["no_message_lost"] and v["lost"] == 1, lost


def test_no_samples_is_never_a_pass():
    v = lat.judge([])
    assert not v["no_message_lost"] and not v["no_message_over_max"] and not v["p95_within_limit"]


def test_the_figures_are_kept_by_direction():
    v = lat.judge([s(0.5, "burst1:A->B"), s(1.5, "burst2:B->A"), s(None, "outsider:knock")])
    assert v["by_direction"]["burst2:B->A"]["max"] == 1.5
    assert v["by_direction"]["outsider:knock"] == {"n": 1, "seen": 0, "p50": None, "p95": None, "max": None}
