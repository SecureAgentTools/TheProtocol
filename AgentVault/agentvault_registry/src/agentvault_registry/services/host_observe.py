"""§F6 WP6.2 slice 2 (2026-09-26, his words "continue with wp6.2 slice 2 on the sandbox pair"): the registry's reads of
its own containers, and of its cloud operators', through the frame runner's read-only ops (`containers_census`,
`container_stats`, tools/frame-runner/frame_runner.py OBSERVATION_OPS) instead of the host Docker socket.

  CONTAINER_OBSERVE_VIA   local (default: the socket reads as today, byte for byte) | runner

The runner answers ONLY for the caller's own compose project or one of its operators (it binds both from the containers,
never from the request). So on the runner route a frame's stats view shows the frame's own containers; on the socket route
it keeps today's host-wide filter on the substring 'agentvault', which on the live frames matches the legacy Frame A
containers and none of the frame's own. A frame set to runner fails closed: no socket, no answer or a refusal raises
ObserveUnavailable with the runner's sentence, and nothing falls back to the socket this flag exists to take away.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from agentvault_registry.services import spire_ops_client as _soc

OBSERVE_VIA_ENV = "CONTAINER_OBSERVE_VIA"


class ObserveUnavailable(RuntimeError):
    """The runner could not answer the read: no socket, no answer, a refusal, or a flag value this code does not know."""


def observe_via() -> str:
    """ "local" or "runner"; any other value raises (a flag this code does not understand is refused, never guessed)."""
    v = (os.getenv(OBSERVE_VIA_ENV) or "local").strip().lower()
    if v not in ("local", "runner"):
        raise ObserveUnavailable(f"{OBSERVE_VIA_ENV}={v!r} is neither 'local' nor 'runner'")
    return v


def _call(op: str, timeout: float, operator: Optional[str]) -> Dict[str, Any]:
    fields = {"operator": operator} if operator else {}
    try:
        return _soc.call(op, timeout=timeout, **fields)
    except _soc.SpireOpsUnavailable as exc:
        raise ObserveUnavailable(f"through the frame runner: {exc}") from exc


def census(operator: Optional[str] = None, timeout: float = 30.0) -> Dict[str, Any]:
    """{frame, project, operator, containers: [{id, name, service, state, status, image}], count, truncated}."""
    return _call("containers_census", timeout, operator)


def stats(operator: Optional[str] = None, timeout: float = 90.0) -> Dict[str, Any]:
    """{frame, project, operator, containers: [{id, name, service, state, status, image, stats | error}], count}."""
    return _call("container_stats", timeout, operator)


class RunnerContainer:
    """What the stats views read from a docker SDK container (name, short_id, status, stats()), filled from one
    container_stats row, so each view's own arithmetic runs unchanged on either route. `status` is the container STATE
    ("running"), as the SDK's is; a row the runner could not sample raises from stats(), as a failed SDK call does."""

    def __init__(self, row: Dict[str, Any]):
        self.name = row.get("name") or ""
        self.short_id = (row.get("id") or "")[:10]
        self.status = row.get("state") or ""
        self._stats = row.get("stats")
        self._error = row.get("error")

    def stats(self, stream: bool = False) -> Dict[str, Any]:
        if self._stats is None:
            raise RuntimeError(self._error or "the frame runner returned no stats for this container")
        return self._stats
