"""
Background Task: Compliance Poller (Phase 2a — D-FED-4, CONSUL — 2026-04-19)

Polls each ACTIVE federated peer's policy-compliance endpoint every 6 hours.
Only starts when IS_CENTRAL_REGISTRY=True (gated in main.py startup).

CONSUL kill-switch (2026-04-19):
  RegistryOperatingState.compliance_enforcement_mode controls per-cycle behavior:
    'off'        — cycle short-circuits; no peer is polled
    'dry_run'    — peers are polled, drift is detected, ComplianceDryRunDrift events
                   are emitted, but trigger_quarantine is NEVER called
    'enforcing'  — drift triggers quarantine IF settings.FEDERATION_ENFORCEMENT_ACTIVE
                   is also True (two stacked kill switches for safety)

Algorithm per peer:
  1. GET {peer.base_url}/api/v1/admin/federation/policy-compliance
  2. Compare returned policy_hash against stored admission hash
  3. On mismatch (or 3 consecutive failures): apply action matrix per mode

Feature flags (independent, both required for live enforcement):
  IS_CENTRAL_REGISTRY            — starts the poller at all (main.py)
  FEDERATION_ENFORCEMENT_ACTIVE  — env-level kill switch, required for quarantine
  compliance_enforcement_mode    — DB-level runtime kill switch (CONSUL)
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import select

from ..database import get_db_context
from ..identity import svid_client
from ..models import (
    FederatedRegistryCompliance,
    PeerRegistry,
    RegistryOperatingState,
    REGISTRY_STATE_SINGLETON_ID,
)
from ..config import settings
from ..core.base_network_params import DriftSeverity, GRACE_PERIOD_HOURS
from ..services.federation_compliance_monitor import get_federation_compliance_monitor
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 6 * 3600  # 6 hours

# Valid enforcement modes (matches RegistryOperatingState.compliance_enforcement_mode)
MODE_OFF = "off"
MODE_DRY_RUN = "dry_run"
MODE_ENFORCING = "enforcing"
VALID_MODES = (MODE_OFF, MODE_DRY_RUN, MODE_ENFORCING)

# §TRUSTCHAIN (2026-09-12): the provenance a first-sight baseline carries in `admitted_by`
# (the admission pipeline writes the admitting admin's email there instead).
BASELINE_FIRST_SIGHT = "compliance_poller:first_sight"


def baseline_from_payload(
    peer_id: int, data: Dict[str, Any], *, now: Optional[datetime] = None
) -> Optional[FederatedRegistryCompliance]:
    """Build the first-sight baseline row from a peer's policy-compliance payload.

    Pure (no I/O) so it is unit-testable; returns None when the payload carries no usable
    `policy_hash`, because a baseline of "" would make every later hash a drift.
    """
    if not isinstance(data, dict):
        return None
    policy_hash = data.get("policy_hash")
    if not isinstance(policy_hash, str) or not policy_hash.strip():
        return None
    now = now or datetime.now(timezone.utc)
    try:
        policy_version = int(data.get("policy_version") or 0)
    except (TypeError, ValueError):
        policy_version = 0
    return FederatedRegistryCompliance(
        peer_registry_id=peer_id,
        policy_json={
            "baseline_source": BASELINE_FIRST_SIGHT,
            "policy_hash": policy_hash,
            "policy_version": policy_version,
            "policy_source": data.get("policy_source"),
            "registry_did": data.get("registry_did"),
            "observed_at": now.isoformat(),
        },
        policy_hash=policy_hash,
        policy_version=policy_version,
        federation_status="federated",
        compliance_score=100.0,
        drift_events_count=0,
        consecutive_poll_failures=0,
        admitted_at=now,
        admitted_by=BASELINE_FIRST_SIGHT,
    )


async def read_enforcement_mode(db) -> str:
    """
    Read the CONSUL enforcement mode from the singleton RegistryOperatingState.
    Returns 'off' if the row is missing (fail-closed default).
    """
    result = await db.execute(
        select(RegistryOperatingState).where(
            RegistryOperatingState.id == REGISTRY_STATE_SINGLETON_ID
        )
    )
    state = result.scalar_one_or_none()
    if state is None:
        logger.error(
            "[CompliancePoller] RegistryOperatingState singleton missing — "
            "defaulting to 'off' (fail-closed). Run migration 0007."
        )
        return MODE_OFF
    mode = state.compliance_enforcement_mode or MODE_OFF
    if mode not in VALID_MODES:
        logger.warning(
            f"[CompliancePoller] Unknown mode '{mode}' in DB — coercing to 'off'."
        )
        return MODE_OFF
    return mode


def _mode_allows_enforcement(mode: str) -> bool:
    """Enforcement fires only when DB mode is 'enforcing' AND env flag is True."""
    return mode == MODE_ENFORCING and settings.FEDERATION_ENFORCEMENT_ACTIVE


class CompliancePoller:
    """
    Polls all active federated peers for policy hash compliance.
    Only instantiated + started when IS_CENTRAL_REGISTRY=True.
    """

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self._monitor = get_federation_compliance_monitor()

    async def _poll_cycle(self) -> None:
        """Single poll cycle — check all ACTIVE peers with compliance records."""
        cycle_started_at = datetime.now(timezone.utc)

        async with get_db_context() as db:
            # CONSUL: mode check at cycle boundary
            mode = await read_enforcement_mode(db)

            if mode == MODE_OFF:
                logger.info(
                    "[CompliancePoller] Mode='off' — skipping cycle (CONSUL kill switch engaged)."
                )
                await self._emit_cycle_summary(
                    cycle_started_at, mode, peers_polled=0,
                    drifts=0, would_quarantine=0, failures=0, skipped="mode_off"
                )
                return

            peers_result = await db.execute(
                select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
            )
            peers = peers_result.scalars().all()

            if not peers:
                logger.info("[CompliancePoller] No active peers to poll.")
                await self._emit_cycle_summary(
                    cycle_started_at, mode, peers_polled=0,
                    drifts=0, would_quarantine=0, failures=0, skipped=None
                )
                return

            enforcement_live = _mode_allows_enforcement(mode)
            logger.info(
                f"[CompliancePoller] Polling {len(peers)} active peer(s) "
                f"in mode='{mode}' (enforcement_live={enforcement_live})..."
            )

            peers_polled = 0
            drifts = 0
            would_quarantine = 0
            failures = 0

            for peer in peers:
                compliance_result = await db.execute(
                    select(FederatedRegistryCompliance).where(
                        FederatedRegistryCompliance.peer_registry_id == peer.id
                    )
                )
                compliance = compliance_result.scalar_one_or_none()

                if compliance is None:
                    # §TRUSTCHAIN (2026-09-12): this used to be `continue` ("peer pre-dates the
                    # Phase 2 admission pipeline"). Every peer admitted through the bilateral
                    # invitation rail pre-dates it, so EU and ASIA held ZERO baseline rows and
                    # this cycle polled nothing while the card claimed a drift monitor. First
                    # sight is the baseline now: fetch the peer's hash once, store it, and
                    # compare from the next cycle on.
                    compliance = await self._record_baseline(db, peer, mode)
                    if compliance is None:
                        failures += 1
                        continue
                if compliance.federation_status == "blacklisted":
                    continue  # Permanently blacklisted — no polling

                peers_polled += 1
                had_drift, queued_quarantine, had_failure = await self._poll_peer(
                    db, peer, compliance, mode
                )
                if had_drift:
                    drifts += 1
                if queued_quarantine:
                    would_quarantine += 1
                if had_failure:
                    failures += 1

            await self._emit_cycle_summary(
                cycle_started_at, mode,
                peers_polled=peers_polled,
                drifts=drifts,
                would_quarantine=would_quarantine,
                failures=failures,
                skipped=None,
            )

    async def _poll_peer(
        self,
        db,
        peer: PeerRegistry,
        compliance: FederatedRegistryCompliance,
        mode: str,
    ) -> Tuple[bool, bool, bool]:
        """
        Poll a single peer's compliance endpoint.
        Returns (had_drift, queued_quarantine_in_enforce_mode, had_failure).

        Phase 9 (2026-04-27): authenticated peer call. HTTPS peers use SPIFFE
        mTLS via svid_client.get_client_cert_config (matches federation_helper
        and federation_sync auth pattern). HTTP peers (Docker dev network) use
        FEDERATION_INTERNAL_SECRET + X-Federation-SPIFFE-ID headers (Mode 2
        fallback).

        Endpoint: /api/v1/federation/policy-compliance (federation namespace,
        require_peer_registry_identity-gated, mTLS-aware). The legacy
        /api/v1/admin/federation/policy-compliance is admin-JWT-only and is
        kept for self-check use cases.
        """
        try:
            data, fetch_error = await self._fetch_policy_compliance(peer)
            if fetch_error is not None:
                if fetch_error.startswith("Empty policy_hash"):
                    logger.warning(
                        f"[CompliancePoller] Empty policy_hash from {peer.name}"
                    )
                await self._handle_poll_failure(db, peer, compliance, mode, reason=fetch_error)
                return (False, False, True)
            fetched_hash = data["policy_hash"]

            # Success — reset failure counter and update poll timestamp
            compliance.consecutive_poll_failures = 0
            compliance.last_poll_at = datetime.now(timezone.utc)
            await db.commit()

            # Check hash
            check = await self._monitor.check_policy_hash(db, peer.id, fetched_hash)

            if not check.mismatch:
                return (False, False, False)

            # Drift detected — pick action based on mode + federation_status
            if compliance.federation_status == "federated":
                if not compliance.in_grace_period():
                    grace = GRACE_PERIOD_HOURS[DriftSeverity.HIGH]
                    reason = (
                        f"Policy hash mismatch detected by compliance poller. "
                        f"Stored={check.stored_hash[:16]}... "
                        f"Fetched={check.fetched_hash[:16]}..."
                    )
                    if _mode_allows_enforcement(mode):
                        await self._monitor.trigger_quarantine(
                            db=db,
                            peer_id=peer.id,
                            reason=reason,
                            severity=DriftSeverity.HIGH,
                            grace_hours=grace,
                        )
                        return (True, True, False)
                    else:
                        # dry_run, or enforcing-but-env-flag-off
                        await self._emit_dry_run_drift(
                            peer=peer,
                            compliance=compliance,
                            check=check,
                            severity=DriftSeverity.HIGH,
                            grace_hours=grace,
                            mode=mode,
                            trigger="hash_mismatch",
                            fetched=data,
                        )
                        return (True, False, False)
                else:
                    # Already in grace period — just mark the drift, no action
                    return (True, False, False)

            elif compliance.grace_expired():
                logger.warning(
                    f"[CompliancePoller] Grace period elapsed for {peer.name} — "
                    f"quarantine is now hard (peer remains quarantined, "
                    f"no corrected policy submitted)"
                )
                return (True, False, False)

            return (True, False, False)

        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
            await self._handle_poll_failure(db, peer, compliance, mode, reason=str(exc))
            return (False, False, True)

    async def _fetch_policy_compliance(
        self, peer: PeerRegistry
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """GET the peer's /api/v1/federation/policy-compliance with the poller's auth
        (SPIFFE mTLS for https peers, the internal secret headers for http ones).

        Returns (data, None) on a 200 carrying a policy_hash, else (None, reason). The reason
        strings are the ones _poll_peer has always passed to _handle_poll_failure, so the
        failure accounting is byte-identical; the fetch is separate only so the baseline path
        (§TRUSTCHAIN) reads a peer the same way the drift path does — one dial, two readers.
        Raises httpx transport errors to the caller, which classifies them.
        """
        base_url = peer.base_url.rstrip("/")
        url = f"{base_url}/api/v1/federation/policy-compliance"

        client_config: Dict[str, Any] = {"timeout": 10.0}
        extra_headers: Dict[str, str] = {}

        if base_url.startswith("https://"):
            cert_config = svid_client.get_client_cert_config(target_url=url)
            if cert_config:
                client_config.update(cert_config)
            else:
                logger.warning(
                    f"[CompliancePoller] No mTLS certs available for HTTPS peer "
                    f"{peer.name} — poll will likely 401/403"
                )
        else:
            our_spiffe_id = svid_client.get_spiffe_id() or ""
            fed_secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
            extra_headers = {
                "X-Federation-Secret": fed_secret,
                "X-Federation-SPIFFE-ID": our_spiffe_id,
            }
        if extra_headers:
            client_config["headers"] = extra_headers

        async with httpx.AsyncClient(**client_config) as client:
            response = await client.get(url)

        if response.status_code != 200:
            return None, f"HTTP {response.status_code}"
        data = response.json()
        if not isinstance(data, dict) or not data.get("policy_hash"):
            return None, "Empty policy_hash in response"
        return data, None

    async def _record_baseline(
        self, db, peer: PeerRegistry, mode: str
    ) -> Optional[FederatedRegistryCompliance]:
        """§TRUSTCHAIN (2026-09-12) — FIRST SIGHT IS THE BASELINE.

        The compliance row used to be written by exactly one path, the Phase 2 admission
        pipeline (`routers/federation_admission.py`), which the bilateral invitation rail never
        runs. So the live cluster held zero rows, every cycle skipped every peer, and journal
        45's "drift monitors compare one field on a schedule" compared nothing. A peer with no
        row now gets one from the first hash it publishes, marked `admitted_by =
        "compliance_poller:first_sight"` so a reader can tell an OBSERVED baseline from an
        ADMITTED one (the admission pipeline writes the admin's email there). The stored
        policy_json is the observation record, not a policy document: the endpoint publishes
        the hash, the version and the source, never the document.

        Returns the new row, or None when the peer did not answer (logged, retried next cycle;
        no row means no failure counter to move, and inventing one would be a claim).
        """
        try:
            data, fetch_error = await self._fetch_policy_compliance(peer)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
            data, fetch_error = None, str(exc)
        if data is None:
            logger.warning(
                f"[CompliancePoller] No baseline for '{peer.name}' yet ({fetch_error}); "
                f"the next cycle tries again"
            )
            return None
        row = baseline_from_payload(peer.id, data)
        if row is None:
            logger.warning(f"[CompliancePoller] '{peer.name}' answered without a usable policy_hash")
            return None
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info(
            f"[CompliancePoller] Baseline recorded for '{peer.name}' from first sight: "
            f"hash={row.policy_hash[:16]}... version={row.policy_version} mode={mode}"
        )
        try:
            emitter = get_event_emitter()
            await emitter.emit(
                event_type="ComplianceBaselineRecorded",
                aggregate_id=str(peer.id),
                aggregate_type="FederatedRegistry",
                data={
                    "peer_registry_id": peer.id,
                    "peer_name": peer.name,
                    "peer_url": peer.base_url,
                    "policy_hash": row.policy_hash,
                    "policy_version": row.policy_version,
                    "policy_source": (row.policy_json or {}).get("policy_source"),
                    "baseline_source": BASELINE_FIRST_SIGHT,
                    "mode_at_recording": mode,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[CompliancePoller] Failed to emit ComplianceBaselineRecorded (non-fatal): {exc}"
            )
        return row

    async def _handle_poll_failure(
        self,
        db,
        peer: PeerRegistry,
        compliance: FederatedRegistryCompliance,
        mode: str,
        reason: str,
    ) -> None:
        """
        Track consecutive poll failures.
        Quarantine the peer at 3 consecutive failures in enforcing mode;
        emit dry-run event in dry_run mode.
        """
        compliance.consecutive_poll_failures = (
            compliance.consecutive_poll_failures or 0
        ) + 1
        compliance.last_poll_at = datetime.now(timezone.utc)
        await db.commit()

        logger.warning(
            f"[CompliancePoller] Peer '{peer.name}' unreachable "
            f"({compliance.consecutive_poll_failures}/3): {reason}"
        )

        if (
            compliance.consecutive_poll_failures >= 3
            and compliance.federation_status == "federated"
        ):
            full_reason = f"3 consecutive poll failures: {reason}"
            grace = GRACE_PERIOD_HOURS[DriftSeverity.HIGH]
            if _mode_allows_enforcement(mode):
                await self._monitor.trigger_quarantine(
                    db=db,
                    peer_id=peer.id,
                    reason=full_reason,
                    severity=DriftSeverity.HIGH,
                    grace_hours=grace,
                )
            else:
                await self._emit_dry_run_drift(
                    peer=peer,
                    compliance=compliance,
                    check=None,
                    severity=DriftSeverity.HIGH,
                    grace_hours=grace,
                    mode=mode,
                    trigger="unreachable_3x",
                    extra_reason=full_reason,
                )

    async def _emit_dry_run_drift(
        self,
        peer: PeerRegistry,
        compliance: FederatedRegistryCompliance,
        check,
        severity: DriftSeverity,
        grace_hours: int,
        mode: str,
        trigger: str,
        extra_reason: Optional[str] = None,
        fetched: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a ComplianceDryRunDrift event — no state change, audit only."""
        payload = {
            "peer_registry_id": peer.id,
            "peer_name": peer.name,
            "peer_url": peer.base_url,
            "trigger": trigger,
            "severity": severity.value,
            "what_would_happen": f"quarantine_with_{grace_hours}h_grace",
            "would_fire_in_enforcing_mode": True,
            "mode_at_detection": mode,
            "enforcement_env_flag": settings.FEDERATION_ENFORCEMENT_ACTIVE,
        }
        if check is not None:
            payload["stored_hash"] = check.stored_hash
            payload["fetched_hash"] = check.fetched_hash
        if isinstance(fetched, dict):
            # §MCPTEST30 (V0561): what the peer says about the two documents, so a reader can tell a governance change
            # (the version moved) from a release that changed a shipped default (same version, same source, new hash:
            # measured on the sandbox 2026-10-03, Sandbox Beta at factory-default version 0 on both sides). The
            # versions are the peer's own counters, reported, never trusted to excuse a drift.
            payload["stored_version"] = compliance.policy_version
            payload["stored_source"] = (compliance.policy_json or {}).get("policy_source") if isinstance(compliance.policy_json, dict) else None
            payload["fetched_version"] = fetched.get("policy_version")
            payload["fetched_source"] = fetched.get("policy_source")
        if extra_reason:
            payload["reason"] = extra_reason

        try:
            emitter = get_event_emitter()
            await emitter.emit(
                event_type="ComplianceDryRunDrift",
                aggregate_id=str(peer.id),
                aggregate_type="FederatedRegistry",
                data=payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[CompliancePoller] Failed to emit ComplianceDryRunDrift "
                f"(non-fatal): {exc}"
            )

        logger.warning(
            f"[CompliancePoller] DRY-RUN drift for peer '{peer.name}' "
            f"(trigger={trigger}, severity={severity.value}) — "
            f"would quarantine with {grace_hours}h grace in enforcing mode."
        )

    async def _emit_cycle_summary(
        self,
        started_at: datetime,
        mode: str,
        peers_polled: int,
        drifts: int,
        would_quarantine: int,
        failures: int,
        skipped: Optional[str],
    ) -> None:
        """Emit CompliancePollCycleCompleted for audit + UI feed."""
        now = datetime.now(timezone.utc)
        payload = {
            "started_at": started_at.isoformat(),
            "completed_at": now.isoformat(),
            "duration_ms": int((now - started_at).total_seconds() * 1000),
            "mode": mode,
            "enforcement_env_flag": settings.FEDERATION_ENFORCEMENT_ACTIVE,
            "peers_polled": peers_polled,
            "drifts_detected": drifts,
            "would_quarantine_count": would_quarantine,
            "poll_failures": failures,
            "skipped_reason": skipped,
        }
        try:
            emitter = get_event_emitter()
            await emitter.emit(
                event_type="CompliancePollCycleCompleted",
                aggregate_id="system",
                aggregate_type="Registry",
                data=payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"[CompliancePoller] Failed to emit CompliancePollCycleCompleted "
                f"(non-fatal): {exc}"
            )

    async def force_single_peer_poll(self, peer_id: int, dry_run_only: bool = False) -> dict:
        """
        Force a poll cycle for one peer — used by the CONSUL admin endpoint
        POST /api/v1/admin/federation/compliance/peers/{id}/poll-now.

        If dry_run_only=True, the cycle runs with MODE_DRY_RUN regardless of
        the stored DB mode, so the admin can preview behavior without risk.
        """
        async with get_db_context() as db:
            effective_mode = MODE_DRY_RUN if dry_run_only else await read_enforcement_mode(db)

            peer_result = await db.execute(select(PeerRegistry).where(PeerRegistry.id == peer_id))
            peer = peer_result.scalar_one_or_none()
            if peer is None:
                return {"status": "error", "detail": f"peer_id={peer_id} not found"}

            if peer.status != "ACTIVE":
                return {"status": "skipped", "detail": f"peer status={peer.status}"}

            compliance_result = await db.execute(
                select(FederatedRegistryCompliance).where(
                    FederatedRegistryCompliance.peer_registry_id == peer_id
                )
            )
            compliance = compliance_result.scalar_one_or_none()
            baseline_recorded = False
            if compliance is None:
                # §TRUSTCHAIN (2026-09-12): first sight is the baseline (see _poll_cycle).
                compliance = await self._record_baseline(db, peer, effective_mode)
                if compliance is None:
                    return {
                        "status": "failed",
                        "peer_id": peer_id,
                        "peer_name": peer.name,
                        "detail": "no baseline yet: the peer's policy-compliance endpoint did not answer",
                        "baseline_recorded": False,
                    }
                baseline_recorded = True
            if compliance.federation_status == "blacklisted":
                return {"status": "skipped", "detail": "peer is blacklisted"}

            had_drift, queued_quarantine, had_failure = await self._poll_peer(
                db, peer, compliance, effective_mode
            )

            return {
                "status": "completed",
                "peer_id": peer_id,
                "peer_name": peer.name,
                "mode_used": effective_mode,
                "baseline_recorded": baseline_recorded,
                "baseline_hash": compliance.policy_hash,
                "baseline_source": compliance.admitted_by,
                "drift_detected": had_drift,
                "quarantine_triggered": queued_quarantine,
                "poll_failure": had_failure,
            }

    async def record_baseline_for_peer(self, peer_id: int) -> dict:
        """§TRUSTCHAIN — the approve rails call this (best effort, in the background) so a
        peer has its baseline the moment it is admitted rather than at the next 6-hour cycle.
        Idempotent: an existing row is left alone. Mode-independent: recording what a peer
        publishes is observation, and the CONSUL kill switch governs ACTING on it."""
        async with get_db_context() as db:
            peer = (await db.execute(select(PeerRegistry).where(PeerRegistry.id == peer_id))).scalar_one_or_none()
            if peer is None or peer.status != "ACTIVE":
                return {"status": "skipped", "detail": "peer missing or not ACTIVE"}
            existing = (await db.execute(
                select(FederatedRegistryCompliance).where(
                    FederatedRegistryCompliance.peer_registry_id == peer_id
                )
            )).scalar_one_or_none()
            if existing is not None:
                return {"status": "exists", "baseline_hash": existing.policy_hash,
                        "baseline_source": existing.admitted_by}
            row = await self._record_baseline(db, peer, await read_enforcement_mode(db))
            if row is None:
                return {"status": "failed", "detail": "peer did not answer its policy-compliance endpoint"}
            return {"status": "recorded", "baseline_hash": row.policy_hash, "baseline_source": row.admitted_by}

    async def run_forever(self) -> None:
        """Run poll cycles every POLL_INTERVAL_SECONDS."""
        logger.info(
            f"[CompliancePoller] Started. "
            f"Poll interval: {POLL_INTERVAL_SECONDS // 3600}h. "
            f"Enforcement env flag: {settings.FEDERATION_ENFORCEMENT_ACTIVE}. "
            f"Effective mode is read per-cycle from RegistryOperatingState."
        )
        self.running = True

        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        await _vitals.register("compliance_poller", module=__name__, pattern="hand-rolled",
                               interval_sec=POLL_INTERVAL_SECONDS, enabled=True)
        while self.running:
            try:
                if not await try_acquire_leadership("compliance_poller"):
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                async with _vitals.cycle("compliance_poller"):
                    await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    f"[CompliancePoller] Unexpected error in poll cycle: {exc}",
                    exc_info=True,
                )

            try:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

        logger.info("[CompliancePoller] Stopped.")

    async def start(self) -> None:
        """Start the background task."""
        if self.task and not self.task.done():
            logger.warning("[CompliancePoller] Already running.")
            return
        self.task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        """Stop the background task gracefully."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("[CompliancePoller] Task cancelled.")


# ── Module-level singleton ────────────────────────────────────────────────────

_poller: Optional[CompliancePoller] = None


def get_compliance_poller() -> CompliancePoller:
    global _poller
    if _poller is None:
        _poller = CompliancePoller()
    return _poller


async def start_compliance_poller() -> None:
    """Called from main.py startup (IS_CENTRAL_REGISTRY=True only)."""
    await get_compliance_poller().start()


async def stop_compliance_poller() -> None:
    """Called from main.py shutdown."""
    await get_compliance_poller().stop()
