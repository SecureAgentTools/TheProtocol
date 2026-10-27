"""
Background Task: Auto-Tally Expired Governance Proposals

Runs every AUTO_TALLY_INTERVAL_SECONDS (default 60) seconds.
Finds proposals where status='VOTING' AND end_timestamp < now(),
then tallies them using the same logic as the manual tally endpoint.

Configurable via environment variables:
  AUTO_TALLY_ENABLED=true|false  (default true)
  AUTO_TALLY_INTERVAL_SECONDS=60 (default 60)
and at runtime through PUT /api/v1/governance/auto-tally/config (kept in Redis, read every turn).
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_

from ..database import get_db_context
from ..models import GovernanceProposal
from ..crud.crud_governance import tally_votes
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

# Runtime overrides (set via admin API, take precedence over env vars).
# §DOCSFIX D6-567 / CB-239 (2026-10-16): the overrides live in Redis (_CONFIG_KEY), where every worker process reads
# them. Module globals reached only the gunicorn worker that answered the PUT, while the loop runs in whichever
# worker holds the leader lock (and read its interval once, at start). The globals below are the fallback of a
# registry without Redis: there an override holds in the answering process only, and get_config says so.
_CONFIG_KEY = "registry:auto_tally:config"
_runtime_enabled: Optional[bool] = None
_runtime_interval: Optional[int] = None


async def _redis():
    from .leader import get_redis
    try:
        return await get_redis()
    except Exception:  # noqa: BLE001 — no Redis is the documented fallback, never an error here
        return None


def _compose(enabled: Optional[bool], interval: Optional[int], store: str) -> dict:
    env_enabled = os.getenv("AUTO_TALLY_ENABLED", "true").lower() in ("true", "1", "yes")
    try:
        env_interval = int(os.getenv("AUTO_TALLY_INTERVAL_SECONDS", "60"))
    except (ValueError, TypeError):
        env_interval = 60
    return {
        "enabled": enabled if enabled is not None else env_enabled,
        "interval_seconds": interval if interval is not None else env_interval,
        "source": "runtime" if (enabled is not None or interval is not None) else "env",
        # shared: every worker reads it (Redis); process: this worker only (no Redis on this registry)
        "store": store,
    }


async def get_config() -> dict:
    """Get current auto-tally configuration: the runtime overrides over the env, from Redis when it answers."""
    r = await _redis()
    if r is not None:
        try:
            raw = await r.hgetall(_CONFIG_KEY)
            enabled = {"true": True, "false": False}.get(raw.get("enabled"))
            interval = int(raw["interval_seconds"]) if raw.get("interval_seconds") else None
            return _compose(enabled, interval, "shared")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[AutoTally] shared config read failed, using this process's: {e}")
    return _compose(_runtime_enabled, _runtime_interval, "process")


async def set_config(enabled: Optional[bool] = None, interval_seconds: Optional[int] = None) -> dict:
    """Update auto-tally configuration at runtime (every worker reads it on its next turn)."""
    global _runtime_enabled, _runtime_interval
    if interval_seconds is not None:
        interval_seconds = min(max(int(interval_seconds), 10), 3600)
    fields = {}
    if enabled is not None:
        fields["enabled"] = "true" if enabled else "false"
    if interval_seconds is not None:
        fields["interval_seconds"] = str(interval_seconds)
    if not fields:
        return await get_config()
    r = await _redis()
    if r is not None:
        try:
            await r.hset(_CONFIG_KEY, mapping=fields)
            cfg = await get_config()
            logger.info(f"[AutoTally] Config updated (shared): {cfg}")
            return cfg
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[AutoTally] shared config write failed, holding it in this process only: {e}")
    if enabled is not None:
        _runtime_enabled = enabled
    if interval_seconds is not None:
        _runtime_interval = interval_seconds
    cfg = _compose(_runtime_enabled, _runtime_interval, "process")
    logger.info(f"[AutoTally] Config updated (this process only): {cfg}")
    return cfg


class AutoTallyWorker:
    """Automatically tallies expired governance proposals."""

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def _find_expired_proposals(self, db) -> list:
        """Find proposals that are VOTING but past their end_timestamp."""
        stmt = select(GovernanceProposal).where(
            and_(
                GovernanceProposal.status == "VOTING",
                GovernanceProposal.end_timestamp < datetime.now(timezone.utc),
            )
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def _refresh_active_gauge(self, db) -> None:
        """Refresh `governance_proposals_active{status,registry}` gauge.

        Counts current proposals grouped by status. Cheap query (one COUNT).
        Runs alongside auto-tally cycle so the dashboard stays current."""
        try:
            from ..routers.governance import (
                _GOV_PROM_AVAILABLE,
                GOVERNANCE_PROPOSALS_ACTIVE,
                _gov_registry_label,
            )
        except ImportError:
            return
        if not _GOV_PROM_AVAILABLE or GOVERNANCE_PROPOSALS_ACTIVE is None:
            return
        try:
            from sqlalchemy import func
            stmt = select(GovernanceProposal.status, func.count(GovernanceProposal.id)).group_by(
                GovernanceProposal.status
            )
            result = await db.execute(stmt)
            counts = dict(result.all())
            registry = _gov_registry_label()
            # Set gauges; explicit zero for known statuses we didn't see
            for status_label in ("VOTING", "PASSED", "FAILED"):
                GOVERNANCE_PROPOSALS_ACTIVE.labels(
                    status=status_label.lower(), registry=registry
                ).set(int(counts.get(status_label, 0)))
        except Exception as e:
            logger.debug(f"[AutoTally] active-gauge refresh failed: {e}")

    async def _tally_cycle(self) -> None:
        """Single auto-tally cycle: find and tally all expired proposals (the loop checks `enabled`)."""
        try:
            async with get_db_context() as db:
                # Refresh dashboard gauge regardless of whether we tally anything
                await self._refresh_active_gauge(db)

                expired = await self._find_expired_proposals(db)
                if not expired:
                    return

                logger.info(f"[AutoTally] Found {len(expired)} expired proposal(s) to tally")
                emitter = get_event_emitter()

                for proposal in expired:
                    try:
                        tally_result = await tally_votes(db, proposal.id)
                        logger.info(
                            f"[AutoTally] Proposal #{proposal.id} '{proposal.title}' "
                            f"tallied -> {tally_result['status']} "
                            f"(for={tally_result['votes_for']}, against={tally_result['votes_against']}, "
                            f"quorum_met={tally_result['quorum_met']}, pass_rate={tally_result['pass_rate']}%)"
                        )

                        # Emit event (fire-and-forget). We emit BOTH:
                        #   - ProposalAutoTallied (informational, kept for back-compat)
                        #   - ProposalTallied   (canonical outcome event for reactor #17)
                        # The reactor subscribes to ProposalTallied so manual tally
                        # (governance.py:tally) and auto-tally fan out identically.
                        common_payload = {
                            "proposal_id": tally_result["proposal_id"],
                            "proposer_did": proposal.proposer_did,
                            "title": proposal.title,
                            "votes_for": tally_result["votes_for"],
                            "votes_against": tally_result["votes_against"],
                            "total_votes": tally_result["total_votes"],
                            "quorum_met": tally_result["quorum_met"],
                            "pass_rate": tally_result["pass_rate"],
                            "result": tally_result["status"],
                            "auto_tallied": True,
                        }
                        asyncio.create_task(emitter.emit(
                            event_type="ProposalAutoTallied",
                            aggregate_id=f"proposal_{proposal.id}",
                            aggregate_type="Governance",
                            data=common_payload,
                        ))
                        asyncio.create_task(emitter.emit(
                            event_type="ProposalTallied",
                            aggregate_id=f"proposal_{proposal.id}",
                            aggregate_type="Governance",
                            data=common_payload,
                            idempotency_key=f"proposal_tallied:{proposal.id}",
                        ))
                    except ValueError as e:
                        # e.g. "has not ended yet" — race condition, skip
                        logger.debug(f"[AutoTally] Skipping proposal #{proposal.id}: {e}")
                    except Exception as e:
                        logger.error(
                            f"[AutoTally] Failed to tally proposal #{proposal.id}: {e}",
                            exc_info=True,
                        )

        except Exception as exc:
            logger.error(f"[AutoTally] Cycle error: {exc}", exc_info=True)

    async def _federation_cycle(self) -> None:
        """GV2 (2026-07-24): drive federation proposals to their terminal state.

        VOTING past end_timestamp → ES tally (weight-based quorum);
        PASSED past veto_deadline → ES apply, which emits the real
        FederationPolicyUpdated ledger event. Before this, federation
        proposals rotted in VOTING forever — nothing ever called the ES
        tally/apply endpoints. Central registries only (cloud-ops have no ES,
        and the ES gates these routes to internal auth). The veto window is
        honored by construction: apply only fires once veto_deadline passed.
        """
        if os.getenv("IS_CENTRAL_REGISTRY", "false").lower() != "true":
            return
        try:
            import httpx
            from ..routers.governance import (
                _get_es_url, _get_es_headers, _get_es_client_kwargs,
            )
            es_url = _get_es_url()
            now = datetime.now(timezone.utc)
            async with httpx.AsyncClient(**_get_es_client_kwargs()) as client:
                resp = await client.get(
                    f"{es_url}/api/v1/federation-governance/proposals",
                    headers=_get_es_headers(),
                )
                if resp.status_code != 200:
                    logger.debug(f"[AutoTally] federation list → {resp.status_code}")
                    return
                payload = resp.json()
                proposals = payload if isinstance(payload, list) else payload.get("proposals", [])
                for p in proposals:
                    try:
                        pid = p.get("id")
                        st = p.get("status")
                        if not pid:
                            continue
                        if st == "VOTING" and p.get("end_timestamp"):
                            end_at = datetime.fromisoformat(
                                str(p["end_timestamp"]).replace("Z", "+00:00")
                            )
                            if end_at <= now:
                                body = None
                                if p.get("ballot_mode"):
                                    # §MEMBERSHIP D2: a ballot proposal is tallied with the registries eligible NOW
                                    from ..services import federation_ballot as _fb
                                    async with get_db_context() as db:
                                        body = await _fb.tally_body(db, p)
                                r = await client.post(
                                    f"{es_url}/api/v1/federation-governance/proposals/{pid}/tally",
                                    headers=_get_es_headers(), json=body,
                                )
                                logger.info(f"[AutoTally] federation tally {pid} → {r.status_code}")
                        elif st == "PASSED" and p.get("veto_deadline"):
                            veto_at = datetime.fromisoformat(
                                str(p["veto_deadline"]).replace("Z", "+00:00")
                            )
                            if veto_at <= now:
                                r = await client.post(
                                    f"{es_url}/api/v1/federation-governance/proposals/{pid}/apply",
                                    headers=_get_es_headers(),
                                )
                                logger.info(f"[AutoTally] federation apply {pid} → {r.status_code}")
                    except Exception as pe:  # noqa: BLE001 — isolate per proposal
                        logger.warning(f"[AutoTally] federation sweep item failed: {pe}")
        except Exception as e:  # noqa: BLE001 — the sweep must never kill the worker
            logger.debug(f"[AutoTally] federation sweep skipped: {e}")

    async def run_forever(self) -> None:
        cfg = await get_config()
        interval = cfg["interval_seconds"]
        enabled = cfg["enabled"]
        logger.info(
            f"[AutoTally] Started (interval={interval}s, enabled={enabled})"
        )
        self.running = True

        from .leader import try_acquire_leadership
        from . import vitals as _vitals

        await _vitals.register(
            "auto_tally", module=__name__, pattern="hand-rolled",
            interval_sec=interval, enabled=enabled,
        )

        while self.running:
            # §DOCSFIX D6-567 / CB-239: the configuration is read on every turn (a change reaches the running
            # loop), and `enabled` covers both sweeps (the federation sweep ran on regardless).
            cfg = await get_config()
            interval = cfg["interval_seconds"]
            try:
                if not await try_acquire_leadership("auto_tally"):
                    await asyncio.sleep(interval)
                    continue
                # Neither cycle catches at its top level, so anything that goes
                # wrong reaches the stamp on its own — no ctx.fail() needed here.
                async with _vitals.cycle("auto_tally"):
                    if cfg["enabled"]:
                        await self._tally_cycle()
                        await self._federation_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[AutoTally] Unexpected error: {exc}", exc_info=True)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

        logger.info("[AutoTally] Stopped.")

    async def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None


# ── Module-level singleton ────────────────────────────────────────────────────

_worker: Optional[AutoTallyWorker] = None


def get_auto_tally_worker() -> AutoTallyWorker:
    global _worker
    if _worker is None:
        _worker = AutoTallyWorker()
    return _worker


async def start_auto_tally() -> None:
    """Called from main.py startup."""
    await get_auto_tally_worker().start()


async def stop_auto_tally() -> None:
    """Called from main.py shutdown."""
    await get_auto_tally_worker().stop()
