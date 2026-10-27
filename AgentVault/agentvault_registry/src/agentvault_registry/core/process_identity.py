"""Identity of the PROCESS/CONTAINER currently running, for staleness checks.

§EVTYPES 2026-09-05. Two single-flight guards in this codebase hand a lock to a
process and release it in a `finally`. A `finally` does not run when the process
is killed -- a container recreate mid-run leaves the lock held by nobody:

  * `admin_api_test.acquire_heavy_run_slot` -- Redis key, ex=3600, so a recreate
    during a suite blocks EVERY api-test run for the next hour;
  * `mcp_tester`'s per-flow guard -- a run stuck in `running` blocks its flow for
    the 90-minute sweep TTL.

Measured today: a sync-triggered restart landed mid-federation-suite and the next
three launches were refused 409 by a lock whose owner had died minutes earlier.

A wall-clock TTL cannot tell "still working" from "died holding it". The owner's
BOOT can: a lock stamped with a container boot epoch different from the current
one provably belongs to a dead process. Same shape as the pgbouncer
`backend_start` recycle -- compare against the OWNER's start, not a clock.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_cached: Optional[float] = None
_probed = False


def container_boot_epoch() -> Optional[float]:
    """Epoch seconds at which THIS container's PID 1 started, or None.

    /proc/1/stat field 22 is PID 1's start time in clock ticks since the host
    booted; /proc/uptime is the host's uptime. Both are readable inside the
    container, so the pair gives PID 1's wall-clock start.

    PID 1 -- not the worker. Every gunicorn worker shares it, so a worker
    respawned by max-requests must not make a live sibling's lock look dead.
    Returns None on any surprise, and callers must treat None as "cannot know"
    and keep the conservative behaviour -- an unreadable /proc must never be
    read as "the holder is dead".
    """
    global _cached, _probed
    if _probed:
        return _cached
    _probed = True
    try:
        with open("/proc/uptime") as f:
            host_up = float(f.read().split()[0])
        with open("/proc/1/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = float(fields[19])                    # field 22, 0-based after comm
        hz = os.sysconf("SC_CLK_TCK") or 100
        _cached = (time.time() - host_up) + (ticks / hz)
    except Exception as e:                            # noqa: BLE001
        logger.warning("[process_identity] container boot epoch unreadable (%r) — "
                       "staleness checks will stay conservative", e)
        _cached = None
    return _cached


def boot_tag() -> str:
    """Short stable string identifying this container's process generation."""
    b = container_boot_epoch()
    return ("boot=%d" % int(b)) if b else "boot=unknown"
