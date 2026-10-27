"""Jittered reconnect backoff for Redis pub/sub subscribers (2026-07-26).

Every subscriber here already backed off exponentially, and every one of them backed off by the
SAME amount at the SAME instant. A registry runs 38 gunicorn workers, each holding three
subscriptions (TEG stream, cache invalidation, canary force-fire), and the fleet runs 16
registries. So one DNS hiccup on `redis` knocked out ~1800 subscribers, all of which slept
exactly 0.5s (or 1.0s, or a flat 10s) and then retried in lockstep — a self-sustaining query
storm that looked like Redis flapping and was actually us stampeding it. Observed after the
V0163 roll: 221 resolution failures in 32 minutes on registry-a alone, rate still climbing.

Full jitter (`sleep = random(0, min(cap, backoff))`) is the fix: the SAME total retry pressure,
spread across the window instead of arriving as a spike. It is the variant with the lowest
contention in AWS's published comparison, and unlike "equal jitter" it can retry almost
immediately, so a single unlucky subscriber does not sit out a long sleep for no reason.

Deliberately a plain function, not a class: the call sites keep their own backoff state and this
only decides how long to actually wait.
"""
import random

DEFAULT_CAP = 30.0


def jittered(backoff: float, cap: float = DEFAULT_CAP) -> float:
    """Full jitter: a random wait in [0, min(backoff, cap)].

    `backoff` is the caller's current exponential ceiling. Returns the duration to sleep, so a
    caller can log what it actually waited rather than what it intended to.
    """
    upper = max(0.0, min(float(backoff), float(cap)))
    return random.uniform(0.0, upper)


def spread(interval: float, frac: float = 0.25) -> float:
    """Decorrelate a STEADY poll interval without changing its mean.

    Full jitter is wrong for a healthy polling loop: `random(0, 5s)` averages 2.5s and would
    DOUBLE the poll rate — making the very load it is meant to relieve worse. What a poll needs
    is the same average cadence with the wakeups spread out, so N workers that started together
    stop arriving together.

    Returns a wait in [interval*(1-frac), interval*(1+frac)]. Mean is preserved exactly.
    """
    iv = max(0.0, float(interval))
    f = min(max(float(frac), 0.0), 0.9)
    return random.uniform(iv * (1.0 - f), iv * (1.0 + f))
