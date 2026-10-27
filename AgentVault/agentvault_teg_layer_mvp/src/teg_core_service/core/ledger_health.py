"""§LEDGERGATE (2026-10-11) — the ledger's health, measured where it is made.

His ask 2026-10-11: "we also have to make actions fail that have event emissions while cqrs outbox to evenstore is
unhealthy". The outbox leader (core/balance_outbox.py) is the one process that knows whether the event store is taking
this TEG's balance changes. Every cycle it hands a HealthTracker what it saw; the tracker turns that into one verdict for
the whole TEG and publishes it in Redis (`teg:<teg_id>:ledger_health`, alive for three cycles). The gate
(core/ledger_gate.py) reads it before a request that starts a value movement.

The states:
  ok         the store takes the journal's rows promptly
  degraded   behind (a row waiting over 10 s, more than 500 waiting, a failed cycle), or a group the store keeps
             rejecting while it takes the others: counted and said, nothing refused
  unhealthy  the store has not taken a row for three cycles running, or more than 5,000 rows wait, or a row has waited
             over 30 s: the gate refuses new value movements

A group the store REJECTS (413, 415 or 422: the event itself is malformed) is told apart from a group it could not be
reached for (no answer, a timeout, 5xx, 401/403, 404/405, a 400 from the store's proxy): one bad event retried every
cycle must not hold every transfer of the TEG behind it. Its rows are "stuck" and counted on their own (degraded, an
alert), never in the waiting age or the backlog that decide unhealthy. A failure is never a rejection by default: an
unknown status counts as unreachable.

A cycle with nothing to emit tests nothing and leaves the failed-cycle count alone, unless nothing waits at all (then
nothing is failing, and the count is reset: a gate must never stay shut with nothing left to retry).

The verdict comes down only below half of each threshold, for two cycles running, so it does not flap. Every threshold
is an environment number, read when the tracker is made; the drill on a fresh pair replaces the starting values with
measured ones.

    TEG_LEDGER_UNHEALTHY_AGE_S         30      a waiting row older than this: unhealthy
    TEG_LEDGER_UNHEALTHY_BACKLOG       5000    more waiting rows than this: unhealthy
    TEG_LEDGER_UNHEALTHY_FAILED_CYCLES 3       this many cycles running in which the store took nothing: unhealthy
    TEG_LEDGER_DEGRADED_AGE_S          10
    TEG_LEDGER_DEGRADED_BACKLOG        500
    TEG_LEDGER_RECOVERY_CYCLES         2
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

OK = "ok"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"
_RANK = {OK: 0, DEGRADED: 1, UNHEALTHY: 2}

KEY_PREFIX = "teg"
KEY_SUFFIX = "ledger_health"

# The statuses that mean "this event is malformed": the store read it and refused its content. Everything else that
# is not a success means the store could not be reached or would not take anything from this TEG.
REJECTED_STATUSES = frozenset({413, 415, 422})


def health_key(teg_id: str) -> str:
    return f"{KEY_PREFIX}:{teg_id}:{KEY_SUFFIX}"


def key_ttl_s(interval_s: float) -> int:
    """Three cycles, at least 15 s: a leader that stops publishing is read as gone within that."""
    return int(max(15, math.ceil(3 * float(interval_s))))


def classify_failure(status: Optional[int]) -> str:
    """'rejected' for a status that says the event itself is malformed, 'unreachable' for anything else (no answer,
    a timeout, 5xx, 401/403, 404/405, a 400 from a proxy, an unknown code)."""
    if isinstance(status, int) and status in REJECTED_STATUSES:
        return "rejected"
    return "unreachable"


def _env_num(env, name: str, default: float, cast=float):
    raw = (env.get(name) or "").strip()
    if not raw:
        return cast(default)
    try:
        v = cast(raw)
    except ValueError:
        logger.error("[LedgerHealth] %s=%r is not a number; using %s", name, raw[:40], default)
        return cast(default)
    if v <= 0:
        logger.error("[LedgerHealth] %s=%r must be above 0; using %s", name, raw[:40], default)
        return cast(default)
    return v


@dataclass(frozen=True)
class Thresholds:
    unhealthy_age_s: float = 30.0
    unhealthy_backlog: int = 5000
    unhealthy_failed_cycles: int = 3
    degraded_age_s: float = 10.0
    degraded_backlog: int = 500
    recovery_cycles: int = 2

    @classmethod
    def from_env(cls, env=os.environ) -> "Thresholds":
        return cls(
            unhealthy_age_s=_env_num(env, "TEG_LEDGER_UNHEALTHY_AGE_S", 30.0),
            unhealthy_backlog=_env_num(env, "TEG_LEDGER_UNHEALTHY_BACKLOG", 5000, int),
            unhealthy_failed_cycles=_env_num(env, "TEG_LEDGER_UNHEALTHY_FAILED_CYCLES", 3, int),
            degraded_age_s=_env_num(env, "TEG_LEDGER_DEGRADED_AGE_S", 10.0),
            degraded_backlog=_env_num(env, "TEG_LEDGER_DEGRADED_BACKLOG", 500, int),
            recovery_cycles=_env_num(env, "TEG_LEDGER_RECOVERY_CYCLES", 2, int),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "unhealthy_age_s": self.unhealthy_age_s, "unhealthy_backlog": self.unhealthy_backlog,
            "unhealthy_failed_cycles": self.unhealthy_failed_cycles, "degraded_age_s": self.degraded_age_s,
            "degraded_backlog": self.degraded_backlog, "recovery_cycles": self.recovery_cycles,
        }


@dataclass
class Observation:
    """What one outbox cycle saw, measured after it emitted.

    waiting_rows / oldest_waiting_age_s: the unemitted rows outside the groups the store rejected (the work the store
    has not taken yet). stuck_rows / oldest_stuck_age_s: the rows of the groups it rejected this cycle.
    attempted / emitted / rejected / unreachable: groups, this cycle."""
    waiting_rows: int = 0
    oldest_waiting_age_s: Optional[float] = None
    stuck_rows: int = 0
    oldest_stuck_age_s: Optional[float] = None
    attempted: int = 0
    emitted: int = 0
    emitted_rows: int = 0
    rejected: int = 0
    unreachable: int = 0
    cycle_ms: int = 0

    @property
    def failed_cycle(self) -> bool:
        """The store took nothing, and at least one group could not reach it. A cycle whose every group was
        rejected reached the store; one with nothing to emit tested nothing."""
        return self.attempted > 0 and self.emitted == 0 and self.unreachable > 0


@dataclass
class HealthTracker:
    thresholds: Thresholds = field(default_factory=Thresholds.from_env)
    interval_s: float = 5.0
    clock: Any = time.time
    state: str = OK
    reason: str = "ok"
    failed_cycles: int = 0
    clear_cycles: int = 0
    since: float = 0.0
    last_good_emit: Optional[float] = None
    last: Optional[Observation] = None

    def __post_init__(self):
        if not self.since:
            self.since = self.clock()

    # ------------------------------------------------------------------ the rules
    def _raw(self, obs: Observation) -> Tuple[str, str]:
        t = self.thresholds
        age = obs.oldest_waiting_age_s or 0.0
        if self.failed_cycles >= t.unhealthy_failed_cycles:
            return UNHEALTHY, "store_unreachable"
        if obs.waiting_rows > t.unhealthy_backlog:
            return UNHEALTHY, "backlog"
        if age > t.unhealthy_age_s:
            return UNHEALTHY, "waiting"
        if self.failed_cycles > 0:
            return DEGRADED, "store_failing"
        if obs.waiting_rows > t.degraded_backlog:
            return DEGRADED, "backlog"
        if age > t.degraded_age_s:
            return DEGRADED, "waiting"
        if obs.stuck_rows > 0:
            return DEGRADED, "rejected_group"
        return OK, "ok"

    def _clear_of(self, state: str, obs: Observation) -> bool:
        """Below half of each threshold that would hold `state`, with no failed cycle and (to leave degraded) no
        stuck group."""
        t = self.thresholds
        age = obs.oldest_waiting_age_s or 0.0
        if self.failed_cycles:
            return False
        if state == UNHEALTHY:
            return obs.waiting_rows <= t.unhealthy_backlog / 2 and age <= t.unhealthy_age_s / 2
        if state == DEGRADED:
            return (obs.waiting_rows <= t.degraded_backlog / 2 and age <= t.degraded_age_s / 2
                    and obs.stuck_rows == 0)
        return True

    def observe(self, obs: Observation) -> Dict[str, Any]:
        now = self.clock()
        if obs.failed_cycle:
            self.failed_cycles += 1
        elif obs.attempted > 0:
            self.failed_cycles = 0  # the store answered this cycle (took a group, or read and rejected one)
        elif obs.waiting_rows == 0 and obs.stuck_rows == 0:
            # nothing waits, so nothing is failing: a count that outlived its rows (a seeded verdict, a journal
            # edited by hand) must not hold the gate shut with nothing left to retry
            self.failed_cycles = 0
        if obs.emitted > 0:
            self.last_good_emit = now
        self.last = obs

        raw, raw_reason = self._raw(obs)
        if _RANK[raw] >= _RANK[self.state]:
            # worse or the same: take it at once (the reason may change within a state)
            if raw != self.state:
                self.since = now
            self.state, self.reason = raw, raw_reason
            self.clear_cycles = 0
        else:
            # better: only after `recovery_cycles` cycles clear of the current state
            if self._clear_of(self.state, obs):
                self.clear_cycles += 1
            else:
                self.clear_cycles = 0
            if self.clear_cycles >= self.thresholds.recovery_cycles:
                self.state, self.reason, self.since = raw, raw_reason, now
                self.clear_cycles = 0
        return self.snapshot()

    # ------------------------------------------------------------------ the verdict
    def retry_after_s(self) -> int:
        """When a refused caller should try again: the time the waiting rows need at the rate the last cycle drained
        them, at least 10 s, at most 120; 30 s when nothing drains (the store is out of reach)."""
        obs = self.last
        if obs is None or obs.emitted <= 0 or (self.state == UNHEALTHY and self.reason == "store_unreachable"):
            return 30
        per_s = (obs.emitted_rows or obs.emitted) / max(self.interval_s, 1e-3)   # rows drained per second
        need = obs.waiting_rows / max(per_s, 1e-3)
        return int(min(120, max(10, math.ceil(need))))

    def snapshot(self) -> Dict[str, Any]:
        obs = self.last or Observation()
        return {
            "state": self.state,
            "reason": self.reason,
            "since": round(self.since, 3),
            "updated_at": round(self.clock(), 3),
            "waiting_rows": obs.waiting_rows,
            "oldest_waiting_age_s": None if obs.oldest_waiting_age_s is None else round(obs.oldest_waiting_age_s, 3),
            "stuck_rows": obs.stuck_rows,
            "oldest_stuck_age_s": None if obs.oldest_stuck_age_s is None else round(obs.oldest_stuck_age_s, 3),
            "failed_cycles": self.failed_cycles,
            "last_good_emit": None if self.last_good_emit is None else round(self.last_good_emit, 3),
            "cycle": {"attempted": obs.attempted, "emitted": obs.emitted, "emitted_rows": obs.emitted_rows,
                      "rejected": obs.rejected, "unreachable": obs.unreachable, "ms": obs.cycle_ms},
            "interval_s": self.interval_s,
            "retry_after_s": self.retry_after_s(),
        }


# ---------------------------------------------------------------------- the journal, measured
WAITING_SQL = """
    SELECT count(*) FILTER (WHERE NOT (COALESCE(txid, -1) = ANY(CAST(:stuck AS bigint[])))),
           EXTRACT(EPOCH FROM now() - min(changed_at) FILTER (WHERE NOT (COALESCE(txid, -1) = ANY(CAST(:stuck AS bigint[]))))),
           count(*) FILTER (WHERE COALESCE(txid, -1) = ANY(CAST(:stuck AS bigint[]))),
           EXTRACT(EPOCH FROM now() - min(changed_at) FILTER (WHERE COALESCE(txid, -1) = ANY(CAST(:stuck AS bigint[]))))
    FROM balance_ledger_journal
    WHERE emitted_at IS NULL
"""


def stuck_param(stuck_txids: Iterable[Optional[int]]) -> list:
    """The rejected groups' txids as the bigint array WAITING_SQL takes (a legacy NULL txid is -1 there)."""
    return sorted({(-1 if t is None else int(t)) for t in stuck_txids})


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return None


def waiting_from_row(row) -> Tuple[int, Optional[float], int, Optional[float]]:
    waiting, w_age, stuck, s_age = (tuple(row) + (None, None, None, None))[:4]
    return int(waiting or 0), _num(w_age), int(stuck or 0), _num(s_age)


# ---------------------------------------------------------------------- Redis
def encode(snapshot: Dict[str, Any], teg_id: str, worker: str) -> str:
    body = dict(snapshot)
    body["teg_id"] = teg_id
    body["worker"] = worker
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def decode(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("state") not in _RANK:
        return None
    return body


async def publish(redis, teg_id: str, snapshot: Dict[str, Any], worker: str, interval_s: float) -> bool:
    if redis is None:
        return False
    try:
        await redis.set(health_key(teg_id), encode(snapshot, teg_id, worker), ex=key_ttl_s(interval_s))
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("[LedgerHealth] publish failed: %s", e)
        return False


async def read(redis, teg_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(the published verdict or None, why it is None)."""
    if redis is None:
        return None, "redis_unavailable"
    try:
        raw = await redis.get(health_key(teg_id))
    except Exception as e:  # noqa: BLE001
        return None, f"redis_error:{type(e).__name__}"
    body = decode(raw)
    if body is None:
        return None, "missing" if not raw else "unreadable"
    return body, None


# ---------------------------------------------------------------------- Prometheus
try:
    from prometheus_client import Gauge as _G

    LEDGER_HEALTH_STATE = _G("teg_ledger_health_state",
                             "The ledger's health as the outbox leader measured it: 0 ok, 1 degraded, 2 unhealthy",
                             ["teg_id"], multiprocess_mode="max")
    LEDGER_WAITING_AGE = _G("teg_ledger_oldest_waiting_seconds",
                            "Age of the oldest journal row the store has not taken (rejected groups excluded)",
                            ["teg_id"], multiprocess_mode="max")
    LEDGER_STUCK_ROWS = _G("teg_ledger_rejected_rows",
                           "Journal rows of groups the event store rejected as malformed (413/415/422), retried each cycle",
                           ["teg_id"], multiprocess_mode="max")
    _METRICS = True
except Exception:  # pragma: no cover
    _METRICS = False


def set_gauges(teg_id: str, snapshot: Dict[str, Any]) -> None:
    if not _METRICS:
        return
    try:
        LEDGER_HEALTH_STATE.labels(teg_id=teg_id).set(float(_RANK.get(snapshot.get("state"), 2)))
        LEDGER_WAITING_AGE.labels(teg_id=teg_id).set(float(snapshot.get("oldest_waiting_age_s") or 0.0))
        LEDGER_STUCK_ROWS.labels(teg_id=teg_id).set(float(snapshot.get("stuck_rows") or 0))
    except Exception:  # pragma: no cover
        pass
