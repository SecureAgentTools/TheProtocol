"""
Reactor: AgentCardPulled (drift=true) → persistent-drift flag
============================================================
§pass47 B5 (2026-05-19).

Subscribes to `AgentCardPulled` events. When the same agent_did drifts on
the same field across N consecutive pulls within a window, emit a single
`AgentCardPersistentDrift` event so operators can investigate (the agent
keeps changing its card mid-flight, or there's a JSON serialization gap, or
the registry's merge logic + agent's source are out of sync).

No automated state change — this is observability, like the JWS throttle
reactor (A6). Manual review via /admin/events.

Env:
  REACTOR_AGENT_CARD_DRIFT_ENABLED              (default true)
  REACTOR_AGENT_CARD_DRIFT_THRESHOLD            (default 3)
  REACTOR_AGENT_CARD_DRIFT_WINDOW_SECONDS       (default 86400 — 24h, covers
                                                 4 pull-sync cycles at 6h cadence)

In-memory per-agent ring buffer of (timestamp, field) tuples. Leader-elected
via base class.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _threshold() -> int:
    try:
        return max(2, int(os.getenv("REACTOR_AGENT_CARD_DRIFT_THRESHOLD", "3")))
    except ValueError:
        return 3


def _window_seconds() -> int:
    try:
        return max(3600, int(os.getenv("REACTOR_AGENT_CARD_DRIFT_WINDOW_SECONDS", "86400")))
    except ValueError:
        return 86400


class AgentCardDriftReactor(EventStoreReactor):
    event_type = "AgentCardPulled"
    leader_key = "reactor_agent_card_drift"
    name = "AgentCardDriftFlag"

    def __init__(self) -> None:
        super().__init__()
        # (agent_did, field) → ring of timestamps
        self._counts: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        # dedup (agent_did, field) → ts of last flag emission
        self._last_flagged: Dict[Tuple[str, str], float] = {}

    async def handle_event(self, event_data: dict) -> None:
        # Only act on drift events. Non-drift AgentCardPulled (304/no-change)
        # aren't emitted today — guard anyway in case shape changes later.
        if not event_data.get("drift"):
            return
        agent_did = event_data.get("agent_did") or event_data.get("aggregate_id") or ""
        fields = event_data.get("drifted_fields") or []
        if not agent_did or not fields:
            return

        now = time.time()
        window = _window_seconds()
        threshold = _threshold()

        for raw_field in fields:
            # Normalize the `:removed` suffix used by drift detector so we
            # count "description" and "description:removed" together.
            field = raw_field.split(":", 1)[0]
            key = (agent_did, field)
            q = self._counts[key]
            q.append(now)
            while q and (now - q[0]) > window:
                q.popleft()

            if len(q) < threshold:
                continue

            last = self._last_flagged.get(key, 0.0)
            if last and (now - last) < window:
                continue  # dedup: already flagged this (agent, field) within window

            self._last_flagged[key] = now
            try:
                from ..event_emitter import get_event_emitter
                evt_result = await get_event_emitter().emit(
                    event_type="AgentCardPersistentDrift",
                    aggregate_id=agent_did,
                    data={
                        "agent_did": agent_did,
                        "field": field,
                        "count_in_window": len(q),
                        "threshold": threshold,
                        "window_seconds": window,
                        "review_action": "manual_review_required",
                    },
                )
                logger.warning(
                    f"[Reactor:{self.name}] FLAGGED persistent drift for {agent_did} "
                    f"field={field} count={len(q)}"
                )
                # §pass49 B1 — persist flag row.
                await _persist_drift_flag_row(
                    agent_did=agent_did,
                    field=field,
                    event_id=str(evt_result.get("event_id") if isinstance(evt_result, dict) else "") or None,
                    count=len(q),
                    threshold=threshold,
                    window=window,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[Reactor:{self.name}] flag emit failed for {agent_did}/{field}: {e}"
                )


async def _persist_drift_flag_row(
    *,
    agent_did: str,
    field: str,
    event_id: Optional[str],
    count: int,
    threshold: int,
    window: int,
) -> None:
    """§pass49 B1 — INSERT an unacknowledged agent_flags row for drift.

    Skips if an unacknowledged flag for (did, type='persistent_drift', field)
    already exists within window.
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from .. import models
    try:
        async with AsyncSessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=window)
            # Dedup on (did, type) — note field is in details, not the type.
            existing = await db.execute(
                select(models.AgentFlag.id).where(
                    models.AgentFlag.agent_did == agent_did,
                    models.AgentFlag.flag_type == "persistent_drift",
                    models.AgentFlag.acknowledged_at.is_(None),
                    models.AgentFlag.raised_at > cutoff,
                ).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                return
            row = models.AgentFlag(
                agent_did=agent_did,
                flag_type="persistent_drift",
                raised_by_event_id=event_id,
                reason=f"persistent_drift_on_{field}",
                source="reactor_agent_card_drift",
                details={"field": field, "count_in_window": count, "threshold": threshold, "window_seconds": window},
            )
            db.add(row)
            await db.commit()
            logger.info(f"[AgentFlag] persisted persistent_drift({field}) for {agent_did}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[AgentFlag] drift persist failed for {agent_did}/{field}: {e}")


# ----------------------------------------------------------------------- module API

_instance: Optional[AgentCardDriftReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = AgentCardDriftReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
