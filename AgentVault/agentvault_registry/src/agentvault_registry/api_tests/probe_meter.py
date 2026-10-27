"""Per-test probe meter — the counter behind the `vacuous` verdict (U1).

WHY THIS EXISTS. Three times in one night a test reported PASS while measuring
nothing: a bond suite whose fake emitter accepted every call (the emits were
throwing); a mirror-convergence test that passed against the pre-fix image; an
API-tester step that 404'd on card lookup before reaching the gate it named. In
each case the green was real and meant nothing.

A test cannot have learned anything about the system without talking to it, and
in this suite every probe — MCP call, REST via adminRequest, psql, raw docker
exec — funnels through `multiframe_helpers.exec_in_container`. Metering that one
function counts every way a test can reach the tier, with no per-test
cooperation and no way for a new test to opt out by forgetting something.

⚠ WHY A MUTABLE COUNTER AND NOT A PLAIN ContextVar[int].
The first version stored an int and did `_PROBES.set(get() + 1)`. Its self-test
passed and it counted NOTHING in anger, because `MCPClient.call` reaches docker
through `asyncio.to_thread(exec_in_container, ...)`: `to_thread` COPIES the
context into the worker thread, so a `.set()` there rebinds the copy and is
discarded when the thread ends. Measured: a real MCP round trip that came back
HTTP 404 from the server — unambiguous proof the wire was crossed — still read
`probes=0`, which would have marked every genuinely-working test `vacuous`.

Holding a mutable object fixes it: the copied context carries the same OBJECT
reference, so mutating it is visible to the parent. The var is only ever
REBOUND in `reset_probes()`, which runs in the test's own Task before any worker
thread exists.

⚠ A ZERO HERE IS A CLAIM ABOUT THE METER until the meter has returned non-zero,
and that claim has to be tested on the path probes actually take.
`self_probe_ok()` counts once inline AND once across a thread — the leg that was
broken. A self-test that checked only the inline path is exactly what let the
first version look healthy while measuring nothing.
"""
from __future__ import annotations

import threading
from contextvars import ContextVar


class _Counter:
    """A probe tally that survives being carried into a worker thread."""

    __slots__ = ("_n", "_lock")

    def __init__(self) -> None:
        self._n = 0
        self._lock = threading.Lock()

    def bump(self) -> None:
        with self._lock:
            self._n += 1

    @property
    def value(self) -> int:
        return self._n


_PROBES: ContextVar[_Counter] = ContextVar("federation_probe_count")
# §MCPSWEEP 2026-09-28: answers the transport LOST during this test (an exec that came back rc 0 with no HTTP status
# marker: curl prints its -w marker even when it cannot connect, so a missing one can only be the transport). Same
# mutable-counter shape as the probe tally, for the same reason (asyncio.to_thread copies the context).
_LOST: ContextVar[_Counter] = ContextVar("federation_transport_lost")


def _counter() -> _Counter:
    try:
        return _PROBES.get()
    except LookupError:
        c = _Counter()
        _PROBES.set(c)
        return c


def record_probe() -> None:
    """Count one round trip to the system under test. Never raises."""
    try:
        _counter().bump()
    except Exception:                                   # pragma: no cover
        pass                                            # a meter must never break a test


def reset_probes() -> None:
    """Install a fresh counter for the test about to run (call in its Task)."""
    _PROBES.set(_Counter())
    _LOST.set(_Counter())


def _lost_counter() -> _Counter:
    try:
        return _LOST.get()
    except LookupError:
        c = _Counter()
        _LOST.set(c)
        return c


def record_transport_lost() -> None:
    """Count one answer the transport lost during the current test. Never raises."""
    try:
        _lost_counter().bump()
    except Exception:                                   # pragma: no cover
        pass


def transport_lost_count() -> int:
    try:
        return _lost_counter().value
    except Exception:                                   # pragma: no cover
        return 0


def probe_count() -> int:
    try:
        return _counter().value
    except Exception:                                   # pragma: no cover
        return 0


def self_probe_ok() -> bool:
    """Prove the meter counts on BOTH paths a probe actually travels.

    Inline is the easy half. The half that matters is the worker thread, which
    is how every MCP call and every psql query reaches docker, and which the
    first version of this meter silently lost. True only if both legs move the
    counter. Restores the caller's counter either way.
    """
    import concurrent.futures
    import contextvars

    try:
        prev = _PROBES.get()
    except LookupError:
        prev = None
    try:
        _PROBES.set(_Counter())
        record_probe()
        if probe_count() != 1:
            return False
        # The cross-thread leg, run EXACTLY as asyncio.to_thread runs it:
        # `copy_context().run(fn)` in the worker. Getting this wrong is not
        # academic — a first draft used a bare `submit(record_probe)`, whose
        # thread gets a FRESH empty context rather than a copy, so it reported
        # the meter broken when the meter was fine. A self-test that does not
        # travel the real road measures itself.
        ctx = contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(ctx.run, record_probe).result()
        return probe_count() == 2
    finally:
        if prev is not None:
            _PROBES.set(prev)
