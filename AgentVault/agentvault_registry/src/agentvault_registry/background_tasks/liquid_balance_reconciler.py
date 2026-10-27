"""
Liquid Balance Reconciler — the BACKSTOP for `agents.liquid_balance`
===================================================================
§FRAMELIC (2026-09-07, findings row 165). `agents.liquid_balance` is a CACHE of a number the
TEG owns, and it is what every console, agent list and admin view reads. Row 164 fixed its
event-driven writer (it followed `TokensTransferred` alone while balances also move under
`LedgerBalanceChanged`); this is the thing that notices when that writer is wrong AGAIN.

It exists because the column had NO backstop. `balance_reconciliation_guard` sounds like one and
is not: it reconciles the EventStore's `materialized_balances` against the TEG — a different
projection, on the other side of the ledger. Nothing watched the column humans read, which is
why a 250-unit bond, a cross-frame debit and a cross-frame credit all sat wrong for an hour with
Δ=0.0 the whole time and every health signal green.

WHAT IT IS FOR — and it is not the healing
------------------------------------------
The heal is cheap and idempotent; the VALUE is the alarm. A backstop that quietly fixes the same
agent every sweep has found a broken real-time path and is hiding it, so a per-agent heal counter
escalates to a WARN naming the DID once an agent has needed healing more than
`LIQUID_BALANCE_RECONCILE_MAX_HEALS_PER_AGENT` times. `registry_liquid_balance_healed_total` is
the number that should sit at zero; if it climbs, the reactor is failing again and this worker is
carrying the frame.

WHY IT IS BOUNDED
-----------------
There is no batch balance rail — even `POST /developers/me/agents/balances` fans out to one TEG
call per agent — so a full sweep of a busy frame (registry-a holds 4,000+ agents) would be a
burst every cycle. Each cycle therefore walks a SLICE, ordered by `id` from a rolling cursor that
wraps, so a frame is covered over time at a flat, predictable cost. The frames it was written for
are covered in one cycle; the big ones converge across several.

WHY THERE IS NO CONVERGE-BEFORE-EMIT PASS
-----------------------------------------
`balance_reconciliation_guard` needs one because its correction is a projection resync with
supply consequences. This one's correction is `_sync_agent_from_teg` — the SAME function the
reactor calls, which re-reads the TEG and writes only on a difference. Healing a value the
reactor is about to write anyway is a no-op, not a fight, so a second cycle of hesitation would
buy nothing and delay the alarm.

ONE WRITER
----------
It does not UPDATE the column itself. It calls the reactor's own sync helper, so there is exactly
one piece of code that decides what this cache should contain — the lesson of the four defects
this batch that were one fact computed in two places.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List

from sqlalchemy import select

from ..database import get_db_context
from ..models import Agent
from ._worker_base import BackgroundWorker
from .eventstore_balance_sync import _is_system, _sync_agent_from_teg

logger = logging.getLogger(__name__)

INTERVAL_SEC = int(os.getenv("LIQUID_BALANCE_RECONCILE_INTERVAL_SEC", "300"))
BATCH_SIZE = int(os.getenv("LIQUID_BALANCE_RECONCILE_BATCH", "100"))
MAX_HEALS_PER_AGENT = int(os.getenv("LIQUID_BALANCE_RECONCILE_MAX_HEALS_PER_AGENT", "3"))

try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge

    RECONCILE_HEALED = _Counter(
        "registry_liquid_balance_healed_total",
        "agents.liquid_balance rows the BACKSTOP had to correct (should stay at 0 — a rising "
        "count means the event-driven sync is failing)",
        labelnames=["registry"],
    )
    RECONCILE_CHECKED = _Counter(
        "registry_liquid_balance_checked_total",
        "agents examined by the liquid-balance reconciler",
        labelnames=["registry"],
    )
    RECONCILE_ESCALATED = _Gauge(
        "registry_liquid_balance_escalated_agents",
        "agents that have needed healing more than the cap — the real-time path is broken for them",
        labelnames=["registry"],
    )
    _METRICS = True
except Exception:  # pragma: no cover - prometheus optional
    RECONCILE_HEALED = RECONCILE_CHECKED = RECONCILE_ESCALATED = None  # type: ignore[assignment]
    _METRICS = False


def _reg() -> str:
    return os.getenv("REGISTRY_NAME", "unknown")


class LiquidBalanceReconciler(BackgroundWorker):
    worker_id = "liquid_balance_reconciler"
    leader_key = "liquid_balance_reconciler"
    interval_sec = INTERVAL_SEC
    # Let the event-driven sync settle first: on a cold start it replays from its durable cursor,
    # and a reconciler that runs before that would "heal" rows the reactor is already fixing and
    # report drift that was never real.
    cold_start_delay_sec = 90

    def __init__(self) -> None:
        super().__init__()
        self._cursor_id: int = 0          # rolling slice cursor over agents.id
        self._heal_count: Dict[str, int] = {}
        self._escalated: set[str] = set()

    def _should_run(self) -> bool:
        return os.getenv("LIQUID_BALANCE_RECONCILE_ENABLED", "true").lower() in ("1", "true", "yes")

    async def _slice(self) -> List[tuple]:
        """The next BATCH agents by id from the rolling cursor, wrapping at the end."""
        async with get_db_context() as db:
            rows = (await db.execute(
                select(Agent.id, Agent.did, Agent.liquid_balance)
                .where(Agent.id > self._cursor_id)
                .order_by(Agent.id)
                .limit(BATCH_SIZE)
            )).all()
            if not rows:                      # wrapped — start again from the top
                self._cursor_id = 0
                rows = (await db.execute(
                    select(Agent.id, Agent.did, Agent.liquid_balance)
                    .order_by(Agent.id)
                    .limit(BATCH_SIZE)
                )).all()
        return list(rows)

    async def _cycle_once(self) -> None:
        rows = await self._slice()
        if not rows:
            self._stats = {"checked": 0, "healed": 0, "wrapped": True, "cursor": 0}
            return

        self._cursor_id = rows[-1][0]
        checked = healed = 0
        healed_dids: List[str] = []

        for _id, did, before in rows:
            if not did or _is_system(did):
                continue
            checked += 1
            # ONE writer: the reactor's own helper re-reads the TEG and writes only on a
            # difference, counting its own outcomes. We detect a heal by re-reading the row.
            await _sync_agent_from_teg(did)

        # Which rows actually moved? Ask the DB once rather than N times inside the loop.
        dids = [r[1] for r in rows if r[1] and not _is_system(r[1])]
        if dids:
            async with get_db_context() as db:
                after = {
                    d: b for d, b in (await db.execute(
                        select(Agent.did, Agent.liquid_balance).where(Agent.did.in_(dids))
                    )).all()
                }
            for _id, did, before in rows:
                if did in after and after[did] != before:
                    healed += 1
                    healed_dids.append(did)
                    n = self._heal_count.get(did, 0) + 1
                    self._heal_count[did] = n
                    if n > MAX_HEALS_PER_AGENT and did not in self._escalated:
                        self._escalated.add(did)
                        logger.warning(
                            "[LiquidBalanceReconcile] %s has needed healing %d times — the "
                            "event-driven balance sync is NOT working for it. This backstop is "
                            "carrying it; find the movement whose event never reached the sync.",
                            did, n,
                        )

        if _METRICS:
            try:
                RECONCILE_CHECKED.labels(registry=_reg()).inc(checked)
                if healed:
                    RECONCILE_HEALED.labels(registry=_reg()).inc(healed)
                RECONCILE_ESCALATED.labels(registry=_reg()).set(len(self._escalated))
            except Exception:
                pass

        if healed:
            # Not a routine info line: the real-time path was supposed to have done this.
            logger.warning(
                "[LiquidBalanceReconcile] corrected %d/%d cached balances the event sync missed: %s",
                healed, checked, [d[-12:] for d in healed_dids[:8]],
            )
        else:
            logger.info(
                "[LiquidBalanceReconcile] %d agents checked, cache matched the TEG on all of them",
                checked,
            )

        self._stats = {
            "checked": checked,
            "healed": healed,
            "healed_dids": [d[-12:] for d in healed_dids[:8]],
            "escalated_agents": len(self._escalated),
            "cursor": self._cursor_id,
            "batch_size": BATCH_SIZE,
        }


_instance: LiquidBalanceReconciler | None = None


def get_liquid_balance_reconciler() -> LiquidBalanceReconciler:
    global _instance
    if _instance is None:
        _instance = LiquidBalanceReconciler()
    return _instance


async def start_liquid_balance_reconciler() -> None:
    await get_liquid_balance_reconciler().start()


async def stop_liquid_balance_reconciler() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
