"""§pass31 Phase 4 — IRONHAND mTLS revocation propagation drill.

Periodically revokes a dedicated "canary-revocation-target" agent, measures
the time until /api/v1/agent/revoked-identities reflects the revocation, then
re-enrols. Lag samples feed the existing Prom histogram
`canary_ironhand_revocation_propagation_seconds` (declared in canary_runner.py).

The killer feature: no other monitor catches a regression where the
revocation API succeeds but downstream consumers (SDK blocklists, peer
registries, EventStore broadcast) lag behind. Without this drill the
histogram stays empty.

Safety constraints:
  - Victim is dedicated (REVOCATION_DRILL_VICTIM_DID env), NOT a canary
    sender/receiver — so revoking it doesn't break any active canary path
  - Bounded poll window (60s)
  - Re-enrolment is automatic; if it fails, NEXT cycle re-enrols before
    revoking again
  - Leader-elected via Redis (only one drill globally)
  - Disabled by default; set REVOCATION_DRILL_ENABLED=true to activate

Env config:
  REVOCATION_DRILL_ENABLED=true|false       # global kill switch (default false)
  REVOCATION_DRILL_VICTIM_DID=did:...       # required when enabled
  REVOCATION_DRILL_INTERVAL_SEC=300         # 5 min default
  REVOCATION_DRILL_TIMEOUT_SEC=60           # max poll window per cycle
  REVOCATION_DRILL_POLL_INTERVAL_SEC=0.25   # poll granularity
  REVOCATION_DRILL_ENDPOINT=http://localhost:8000/api/v1/agent/revoked-identities
"""
import asyncio
import datetime
import logging
import os
import time
from typing import Optional

import httpx
from sqlalchemy import select

from .. import models
from ..database import get_db_context
from ..services.agent_spire import (
    delete_agent_spire_entry,
    register_agent_spire_entry,
    sanitize_did_for_spiffe,
)
from .leader import try_acquire_leadership
from . import vitals as _vitals

logger = logging.getLogger(__name__)

DRILL_ENABLED = os.environ.get("REVOCATION_DRILL_ENABLED", "false").lower() == "true"
VICTIM_DID = os.environ.get("REVOCATION_DRILL_VICTIM_DID", "")
CYCLE_INTERVAL_SEC = int(os.environ.get("REVOCATION_DRILL_INTERVAL_SEC", "300"))
POLL_TIMEOUT_SEC = float(os.environ.get("REVOCATION_DRILL_TIMEOUT_SEC", "60"))
POLL_INTERVAL_SEC = float(os.environ.get("REVOCATION_DRILL_POLL_INTERVAL_SEC", "0.25"))
ENDPOINT_URL = os.environ.get(
    "REVOCATION_DRILL_ENDPOINT",
    "http://localhost:8000/api/v1/agent/revoked-identities",
)

# Prom histogram declared by canary_runner — share the same metric.
try:
    from .canary_runner import canary_ironhand_revocation_propagation_seconds
except Exception:
    canary_ironhand_revocation_propagation_seconds = None

_runner_task: Optional[asyncio.Task] = None
_stop_requested = False


async def _check_endpoint_reflects_revocation(victim_did: str) -> bool:
    """Hit /api/v1/agent/revoked-identities and check if victim is in the list.

    Measures end-to-end propagation: DB write → endpoint serves new state.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(ENDPOINT_URL)
        if r.status_code != 200:
            return False
        data = r.json()
        # Endpoint may return {"revoked": [...]} or {"revoked_identities": [...]} —
        # be forgiving on shape.
        candidates = (
            data.get("revoked")
            or data.get("revoked_identities")
            or data.get("identities")
            or []
        )
        sanitized = sanitize_did_for_spiffe(victim_did)
        body = str(data)  # fallback: substring check
        if victim_did in body or sanitized in body:
            return True
        for item in candidates:
            s = str(item)
            if victim_did in s or sanitized in s:
                return True
        return False
    except Exception as e:
        logger.debug(f"[RevocationDrill] endpoint check failed: {e}")
        return False


async def _ensure_victim_enrolled(victim_did: str) -> bool:
    """If victim isn't currently enrolled, enrol it. Returns True if ready."""
    async with get_db_context() as db:
        result = await db.execute(select(models.Agent).where(models.Agent.did == victim_did))
        agent = result.scalar_one_or_none()
        if not agent:
            logger.warning(f"[RevocationDrill] victim {victim_did} not in agents table")
            return False
        if agent.mtls_enabled:
            return True
    # Re-enrol
    try:
        spiffe_id = register_agent_spire_entry(victim_did)
    except Exception as e:
        logger.error(f"[RevocationDrill] pre-cycle re-enrol failed: {e}")
        return False
    async with get_db_context() as db:
        result = await db.execute(select(models.Agent).where(models.Agent.did == victim_did))
        agent = result.scalar_one_or_none()
        if agent:
            agent.mtls_enabled = True
            agent.spiffe_id = spiffe_id
            agent.mtls_enrolled_at = datetime.datetime.now(datetime.timezone.utc)
            await db.commit()
    return True


async def _revoke_victim(victim_did: str) -> Optional[str]:
    """Revoke victim: delete SPIRE entry + flip DB flag. Returns old SPIFFE ID."""
    old_spiffe_id: Optional[str] = None
    try:
        delete_agent_spire_entry(victim_did)
    except Exception as e:
        logger.warning(f"[RevocationDrill] SPIRE deletion failed: {e}")
    async with get_db_context() as db:
        result = await db.execute(select(models.Agent).where(models.Agent.did == victim_did))
        agent = result.scalar_one_or_none()
        if agent:
            old_spiffe_id = agent.spiffe_id
            agent.mtls_enabled = False
            agent.spiffe_id = None
            await db.commit()
    # Best-effort event emission so SDK blocklists get notified (real-world prop path)
    try:
        from ..event_emitter import get_event_emitter

        if old_spiffe_id:
            await get_event_emitter().emit_agent_mtls_revoked(
                agent_did=victim_did,
                spiffe_id=old_spiffe_id,
                reason="revocation_drill",
                revoked_by="canary_revocation_drill_worker",
            )
    except Exception as e:
        logger.debug(f"[RevocationDrill] event emit failed (non-fatal): {e}")
    return old_spiffe_id


async def _run_drill() -> None:
    """One drill cycle: revoke → poll → re-enrol."""
    if not VICTIM_DID:
        logger.debug("[RevocationDrill] no VICTIM_DID set — skipping")
        return

    if not await _ensure_victim_enrolled(VICTIM_DID):
        logger.warning(f"[RevocationDrill] cannot enrol victim — abort cycle")
        return

    logger.info(f"[RevocationDrill] revoking {VICTIM_DID}")
    t0 = time.time()
    old_spiffe = await _revoke_victim(VICTIM_DID)

    deadline = t0 + POLL_TIMEOUT_SEC
    lag_sec: Optional[float] = None
    while time.time() < deadline:
        if await _check_endpoint_reflects_revocation(VICTIM_DID):
            lag_sec = time.time() - t0
            break
        await asyncio.sleep(POLL_INTERVAL_SEC)

    if lag_sec is not None:
        if canary_ironhand_revocation_propagation_seconds is not None:
            canary_ironhand_revocation_propagation_seconds.observe(lag_sec)
        # V0024 Phase 3b — also record the sample in a per-registry local Redis ring so the
        # IRONHAND Theatre can serve revocation-p95 WITHOUT Prometheus (decentralized). The
        # central Prom histogram stays only as a fleet aggregate / fallback.
        try:
            from .leader import get_redis
            _r = await get_redis()
            if _r is not None:
                await _r.lpush("canary:ironhand:revoc_lag_ms", int(lag_sec * 1000))
                await _r.ltrim("canary:ironhand:revoc_lag_ms", 0, 499)  # keep last 500 samples
        except Exception as _e:
            logger.debug(f"[RevocationDrill] local lag store failed: {_e}")
        logger.info(
            f"[RevocationDrill] propagation lag: {lag_sec*1000:.0f}ms "
            f"(old_spiffe={old_spiffe})"
        )
    else:
        logger.warning(
            f"[RevocationDrill] TIMEOUT after {POLL_TIMEOUT_SEC}s — endpoint did not "
            f"reflect revocation. Will re-enrol anyway."
        )

    # Re-enrol so the next cycle has something to revoke
    try:
        new_spiffe = register_agent_spire_entry(VICTIM_DID)
        async with get_db_context() as db:
            result = await db.execute(
                select(models.Agent).where(models.Agent.did == VICTIM_DID)
            )
            agent = result.scalar_one_or_none()
            if agent:
                agent.mtls_enabled = True
                agent.spiffe_id = new_spiffe
                agent.mtls_enrolled_at = datetime.datetime.now(datetime.timezone.utc)
                await db.commit()
        logger.info(f"[RevocationDrill] re-enrolled {VICTIM_DID} → {new_spiffe}")
    except Exception as e:
        logger.error(
            f"[RevocationDrill] re-enrol failed: {e}. "
            f"NEXT cycle will re-enrol before revoking."
        )


async def revocation_drill_loop() -> None:
    """Main loop. Leader-elected. Runs every CYCLE_INTERVAL_SEC."""
    logger.info(
        f"[RevocationDrill] loop started "
        f"(interval={CYCLE_INTERVAL_SEC}s, victim={VICTIM_DID or '(unset)'}, "
        f"endpoint={ENDPOINT_URL})"
    )
    await _vitals.register("revocation_drill", module=__name__, pattern="hand-rolled",
                           interval_sec=CYCLE_INTERVAL_SEC, enabled=True)
    while not _stop_requested:
        try:
            if await try_acquire_leadership("revocation_drill"):
                # No error-handling change: _run_drill's try guards a single late
                # re-enrol step, not the drill, so a real failure already escapes.
                async with _vitals.cycle("revocation_drill"):
                    await _run_drill()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[RevocationDrill] cycle error: {e}", exc_info=True)
        # Sleep in 5s slices so cancellation is responsive
        slept = 0
        while slept < CYCLE_INTERVAL_SEC and not _stop_requested:
            await asyncio.sleep(min(5, CYCLE_INTERVAL_SEC - slept))
            slept += 5


async def start_revocation_drill() -> None:
    """Lifespan-startup hook. Idempotent."""
    global _runner_task
    if not DRILL_ENABLED:
        logger.info("[RevocationDrill] disabled (REVOCATION_DRILL_ENABLED!=true) — skipping start")
        return
    if not VICTIM_DID:
        logger.warning("[RevocationDrill] VICTIM_DID not set — drill will skip every cycle")
    if _runner_task is None or _runner_task.done():
        _runner_task = asyncio.create_task(revocation_drill_loop())
        logger.info("[RevocationDrill] background task spawned")


async def stop_revocation_drill() -> None:
    """Lifespan-shutdown hook."""
    global _stop_requested, _runner_task
    _stop_requested = True
    if _runner_task is not None:
        _runner_task.cancel()
        try:
            await _runner_task
        except (asyncio.CancelledError, Exception):
            pass
        _runner_task = None
    logger.info("[RevocationDrill] stopped")
