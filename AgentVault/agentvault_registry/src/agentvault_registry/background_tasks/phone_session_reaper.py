"""PHONE FABRIC — session reaper (2026-07-07).

Leader-elected worker that auto-ends phone sessions whose TTL elapsed or whose capability
token was revoked/exhausted (defense in depth behind the per-request live check). Releases
the leased pool instance. Δ-irrelevant (status-only + audit). Gated PHONE_FABRIC_ENABLED.
"""
import asyncio
import logging
import os

from sqlalchemy import text

from agentvault_registry.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
_task = None
_stop = False
_INTERVAL = int(os.getenv("PHONE_REAPER_INTERVAL_SECONDS", "30"))


def _emit_ended(row, status_: str, end_reason: str) -> None:
    """§DOCSFIX D6-527 (2026-10-16): a session the sweep ends is ended on the ledger too (PhoneSessionEnded, the
    payload the session routes write). Best-effort, after the commit."""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(event_type="PhoneSessionEnded", aggregate_id=row.agent_did, data={
            "session_id": row.id, "status": status_, "end_reason": end_reason, "actions": row.actions_used,
            "budget_spent": float(row.budget_spent) if row.budget_spent is not None else None})
    except Exception:  # noqa: BLE001
        logger.debug("[PHONE-REAPER] emit PhoneSessionEnded skipped for %s", getattr(row, "id", "?"), exc_info=True)


async def _sweep_once() -> int:
    async with AsyncSessionLocal() as db:
        # TTL expired
        expired = (await db.execute(text(
            "UPDATE phone_sessions SET status='expired', ended_at=now(), end_reason='ttl' "
            "WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= now() "
            "RETURNING id, agent_did, actions_used, budget_spent"
        ))).fetchall()
        # capability token no longer active (revoked_subtree / exhausted / expired)
        dead = (await db.execute(text(
            "UPDATE phone_sessions s SET status='revoked', ended_at=now(), end_reason='token_dead' "
            "FROM agent_capability_tokens t "
            "WHERE s.status='active' AND s.capability_token_id = t.id "
            "AND (t.status NOT IN ('issued','active') OR (t.expires_at IS NOT NULL AND t.expires_at <= now())) "
            "RETURNING s.id, s.agent_did, s.actions_used, s.budget_spent"
        ))).fetchall()
        # release instances whose session is no longer active
        await db.execute(text(
            "UPDATE phone_pool_instances p SET status='idle', leased_by=NULL "
            "WHERE p.status='leased' AND (p.leased_by IS NULL OR NOT EXISTS "
            "(SELECT 1 FROM phone_sessions s WHERE s.id = p.leased_by AND s.status='active'))"
        ))
        await db.commit()
        for row in expired:
            _emit_ended(row, "expired", "ttl")
        for row in dead:
            _emit_ended(row, "revoked", "token_dead")
        return len(expired) + len(dead)


async def _loop():
    global _stop
    from .leader import try_acquire_leadership
    from . import vitals as _vitals
    await _vitals.register("phone_session_reaper", module=__name__, pattern="hand-rolled",
                           interval_sec=_INTERVAL, enabled=True)
    while not _stop:
        try:
            if await try_acquire_leadership("phone_session_reaper"):
                async with _vitals.cycle("phone_session_reaper") as _ctx:
                    n = await _sweep_once()
                    _ctx.note(ended=n)
                if n:
                    logger.info("[PHONE-REAPER] auto-ended %s stale session(s)", n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PHONE-REAPER] sweep error: %s", exc)
        await asyncio.sleep(_INTERVAL)


async def start_phone_session_reaper():
    global _task, _stop
    _stop = False
    if _task is None:
        _task = asyncio.create_task(_loop())


async def stop_phone_session_reaper():
    global _task, _stop
    _stop = True
    if _task:
        _task.cancel()
        _task = None
