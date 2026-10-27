"""
Reactor: AgentCardJWSVerifyFailed → throttled flag emission
==========================================================
§pass47 A6 (2026-05-19).

Subscribes to `AgentCardJWSVerifyFailed` events. Maintains a sliding 1h
window per agent (Redis sorted-set if available, in-memory fallback) and on
the Nth consecutive failure (default 3) emits a single `AgentFlaggedForJWSFailures`
audit event so operators can review the agent without auto-suspension.

Why throttled: a single JWS failure is noise (key rotation race, transient
SDK hiccup). Three in an hour is signal — either persistent key/agent
misconfiguration or a substitution attack. The audit event is the trigger
for manual review via /admin/events — no automated state change.

Env vars:
  REACTOR_JWS_VERIFY_FAILED_ENABLED        (default true)
  REACTOR_JWS_VERIFY_FAILED_THRESHOLD      (default 3)
  REACTOR_JWS_VERIFY_FAILED_WINDOW_SECONDS (default 3600)

The flag event is emitted at most once per (agent_did, hour) — re-flagging
the same agent inside the same window is suppressed via a 1h dedup key.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _threshold() -> int:
    try:
        return max(1, int(os.getenv("REACTOR_JWS_VERIFY_FAILED_THRESHOLD", "3")))
    except ValueError:
        return 3


def _window_seconds() -> int:
    try:
        return max(60, int(os.getenv("REACTOR_JWS_VERIFY_FAILED_WINDOW_SECONDS", "3600")))
    except ValueError:
        return 3600


class JWSVerifyFailedThrottleReactor(EventStoreReactor):
    event_type = "AgentCardJWSVerifyFailed"
    leader_key = "reactor_jws_verify_failed"
    name = "JWSVerifyFailedThrottle"

    def __init__(self) -> None:
        super().__init__()
        # Per-agent ring of failure timestamps (monotonic seconds). In-memory
        # is OK because this reactor is leader-elected (one worker handles all
        # events). On leader change the window resets, which is conservative
        # (under-flags briefly, never over-flags).
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        # Dedup: agent_did → unix timestamp of last AgentFlaggedForJWSFailures
        # emission. Within window we suppress duplicate flag events.
        self._last_flagged: Dict[str, float] = {}

    async def handle_event(self, event_data: dict) -> None:
        agent_did = event_data.get("agent_did") or event_data.get("aggregate_id") or ""
        if not agent_did:
            return

        window = _window_seconds()
        threshold = _threshold()
        now = time.time()

        # Append + evict outside-window entries.
        q = self._failures[agent_did]
        q.append(now)
        while q and (now - q[0]) > window:
            q.popleft()

        if len(q) < threshold:
            logger.debug(
                f"[Reactor:{self.name}] {agent_did}: {len(q)}/{threshold} "
                f"failures within {window}s"
            )
            return

        # Threshold reached — emit AgentFlaggedForJWSFailures once per window.
        last = self._last_flagged.get(agent_did, 0.0)
        if last and (now - last) < window:
            logger.debug(
                f"[Reactor:{self.name}] {agent_did}: already flagged "
                f"{int(now - last)}s ago — suppressing duplicate"
            )
            return

        self._last_flagged[agent_did] = now

        try:
            from ..event_emitter import get_event_emitter
            evt_result = await get_event_emitter().emit(
                event_type="AgentFlaggedForJWSFailures",
                aggregate_id=agent_did,
                data={
                    "agent_did": agent_did,
                    "failure_count": len(q),
                    "threshold": threshold,
                    "window_seconds": window,
                    "last_reason": event_data.get("reason"),
                    "last_source": event_data.get("source"),
                    "review_action": "manual_review_required",
                },
            )
            logger.warning(
                f"[Reactor:{self.name}] FLAGGED {agent_did} — "
                f"{len(q)} JWS failures in {window}s (reason={event_data.get('reason')})"
            )
            # §pass49 B1 — persist flag row alongside EventStore emit.
            await _persist_flag_row(
                agent_did=agent_did,
                flag_type="jws_verify_threshold",
                event_id=str(evt_result.get("event_id") if isinstance(evt_result, dict) else "") or None,
                reason=event_data.get("reason"),
                source=event_data.get("source"),
                details={"failure_count": len(q), "threshold": threshold, "window_seconds": window},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Reactor:{self.name}] flag emit failed for {agent_did}: {e}")


async def _persist_flag_row(
    *,
    agent_did: str,
    flag_type: str,
    event_id: Optional[str],
    reason: Optional[str],
    source: Optional[str],
    details: Optional[dict],
) -> None:
    """§pass49 B1 — INSERT an unacknowledged agent_flags row.

    Skips if an unacknowledged row of the same (did, type) already exists
    within the reactor's window — the in-memory dedup is the primary guard,
    this DB-side check is belt-and-suspenders.
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from .. import models
    try:
        async with AsyncSessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=_window_seconds())
            existing = await db.execute(
                select(models.AgentFlag.id).where(
                    models.AgentFlag.agent_did == agent_did,
                    models.AgentFlag.flag_type == flag_type,
                    models.AgentFlag.acknowledged_at.is_(None),
                    models.AgentFlag.raised_at > cutoff,
                ).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                logger.debug(
                    f"[Reactor:JWSVerifyFailedThrottle] skip persist — active flag exists for {agent_did}"
                )
                return
            row = models.AgentFlag(
                agent_did=agent_did,
                flag_type=flag_type,
                raised_by_event_id=event_id,
                reason=reason,
                source=source,
                details=details,
            )
            db.add(row)
            await db.commit()
            logger.info(f"[AgentFlag] persisted {flag_type} for {agent_did}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[AgentFlag] persist failed for {agent_did}/{flag_type}: {e}")


# ----------------------------------------------------------------------- module API

_instance: Optional[JWSVerifyFailedThrottleReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = JWSVerifyFailedThrottleReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
