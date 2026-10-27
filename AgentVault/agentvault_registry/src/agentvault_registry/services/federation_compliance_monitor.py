"""
Federation Compliance Monitor — Quarantine State Machine (Phase 2a)

Single point of truth for all federated registry state transitions.
Called by:
  - background_tasks/compliance_poller.py  (automated hash drift detection)
  - background_tasks/staking_distributor.py (treasury bankruptcy trigger)
  - routers/enforcement_admin.py            (manual admin quarantine/blacklist)

State transitions:
  FEDERATED → QUARANTINED  (drift detected, 3 poll failures, or 30-day treasury zero)
  QUARANTINED → FEDERATED  (operator corrects policy, admin lifts quarantine)
  ANY → BLACKLISTED        (permanent — admin-initiated or automated critical attack)
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from ..models import (
    FederatedRegistryCompliance,
    PeerRegistry,
    RegistryOperatingState,
    REGISTRY_STATE_SINGLETON_ID,
)
from ..event_emitter import get_event_emitter
from ..core.base_network_params import DriftSeverity, GRACE_PERIOD_HOURS

logger = logging.getLogger(__name__)


class NotQuarantined(ValueError):
    """lift_quarantine asked of a peer that is not quarantined: nothing to lift, nothing written (409)."""


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ComplianceCheckResult:
    mismatch: bool
    peer_id: int
    stored_hash: str
    fetched_hash: str
    highest_severity: DriftSeverity = DriftSeverity.LOW
    violations: List[str] = field(default_factory=list)


# ── Monitor ───────────────────────────────────────────────────────────────────

class FederationComplianceMonitor:
    """
    Quarantine state machine for federated registry peers.

    All public methods accept an open AsyncSession — callers are responsible
    for providing a session from their own context (poller, admin router, etc.).
    commit() is called inside each method after state changes.
    """

    # ── Hash Drift Detection ──────────────────────────────────────────────────

    async def check_policy_hash(
        self,
        db: AsyncSession,
        peer_id: int,
        fetched_hash: str,
    ) -> ComplianceCheckResult:
        """
        Compare fetched_hash against the admission hash stored in
        FederatedRegistryCompliance.  On mismatch: increment drift_events_count
        and update last_hash_mismatch_at.  Does NOT trigger quarantine —
        the caller (compliance_poller) decides based on grace period state.
        """
        result = await db.execute(
            select(FederatedRegistryCompliance).where(
                FederatedRegistryCompliance.peer_registry_id == peer_id
            )
        )
        compliance = result.scalar_one_or_none()

        if compliance is None:
            logger.warning(
                f"[ComplianceMonitor] No compliance record for peer_id={peer_id}"
            )
            return ComplianceCheckResult(
                mismatch=False,
                peer_id=peer_id,
                stored_hash="",
                fetched_hash=fetched_hash,
            )

        stored_hash = compliance.policy_hash or ""
        mismatch = stored_hash != fetched_hash

        if mismatch:
            compliance.drift_events_count = (compliance.drift_events_count or 0) + 1
            compliance.last_hash_mismatch_at = datetime.now(timezone.utc)
            await db.commit()
            logger.warning(
                f"[ComplianceMonitor] Hash mismatch for peer_id={peer_id}: "
                f"stored={stored_hash[:16]}... fetched={fetched_hash[:16]}..."
            )

        return ComplianceCheckResult(
            mismatch=mismatch,
            peer_id=peer_id,
            stored_hash=stored_hash,
            fetched_hash=fetched_hash,
            highest_severity=DriftSeverity.HIGH if mismatch else DriftSeverity.LOW,
        )

    # ── Quarantine ────────────────────────────────────────────────────────────

    async def trigger_quarantine(
        self,
        db: AsyncSession,
        peer_id: int,
        reason: str,
        severity: DriftSeverity,
        grace_hours: int = 0,
        admin_email: Optional[str] = None,
    ) -> None:
        """
        Transition peer to QUARANTINED state.
        grace_hours=0 means immediate effect (no grace period).
        Emits RegistryQuarantined event to EventStore.
        """
        result = await db.execute(
            select(FederatedRegistryCompliance).where(
                FederatedRegistryCompliance.peer_registry_id == peer_id
            )
        )
        compliance = result.scalar_one_or_none()
        if compliance is None:
            raise ValueError(f"No compliance record for peer_id={peer_id}")

        now = datetime.now(timezone.utc)
        grace_expires = (now + timedelta(hours=grace_hours)) if grace_hours > 0 else None

        compliance.federation_status = "quarantined"
        compliance.quarantine_reason = reason
        compliance.quarantine_since = now
        compliance.quarantine_grace_expires = grace_expires
        compliance.compliance_score = max(
            0.0, (compliance.compliance_score or 100.0) - 10.0
        )

        # Append to quarantine_events history
        event_record = {
            "timestamp": now.isoformat(),
            "reason": reason,
            "severity": severity.value,
            "grace_hours": grace_hours,
            "triggered_by": admin_email or "system",
        }
        existing_events = list(compliance.quarantine_events or [])
        existing_events.append(event_record)
        compliance.quarantine_events = existing_events

        await db.commit()

        # Look up peer name + derive teg_id so the reactor doesn't have to do
        # its own DB lookup. Best-effort: cloud operators follow `teg-{safe_name}`;
        # non-operator peers (e.g., sovereign frames) may have a different convention,
        # in which case the reactor's TEG call returns `not_found` and is a no-op.
        from agentvault_registry import models as registry_models
        from agentvault_registry.services.cloud_provisioner import _safe_name as _safe
        peer_record_result = await db.execute(
            select(registry_models.PeerRegistry).where(registry_models.PeerRegistry.id == peer_id)
        )
        peer_record = peer_record_result.scalar_one_or_none()
        peer_name = peer_record.name if peer_record else None
        derived_teg_id = f"teg-{_safe(peer_name)}" if peer_name else None

        # §NOTIFV2 registry.quarantined (audience=operator) — wired at the MONITOR, which is the
        # choke point for all three callers: the admin route (routers/enforcement_admin.py) and
        # the two automatic ones in background_tasks/compliance_poller.py. Quarantine is a
        # critical, rare, operator-facing event, so both push channels are on by default.
        try:
            import asyncio as _aio_n
            from agentvault_registry.background_tasks.push_notify import notify_audience
            _aio_n.create_task(notify_audience(
                "registry.quarantined",
                title="Registry quarantined",
                message=f"{peer_name or ('peer #' + str(peer_id))} quarantined: {reason}",
                tags="rotating_light", priority="high",
                click="/ui/#/admin/federation-compliance"))
        except Exception:  # noqa: BLE001
            logger.debug("[NOTIFY] registry.quarantined emit failed", exc_info=True)

        # Emit to EventStore
        emitter = get_event_emitter()
        await emitter.emit(
            event_type="RegistryQuarantined",
            aggregate_id=str(peer_id),
            aggregate_type="FederatedRegistry",
            data={
                "peer_registry_id": peer_id,
                "peer_name": peer_name,
                "teg_id": derived_teg_id,
                "reason": reason,
                "severity": severity.value,
                "grace_hours": grace_hours,
                "grace_expires": grace_expires.isoformat() if grace_expires else None,
                "triggered_by": admin_email or "system",
            },
        )

        logger.warning(
            f"[ComplianceMonitor] Peer {peer_id} QUARANTINED — "
            f"severity={severity.value}, grace={grace_hours}h, reason={reason}"
        )

    # ── Lift Quarantine ───────────────────────────────────────────────────────

    async def lift_quarantine(
        self,
        db: AsyncSession,
        peer_id: int,
        new_policy_hash: str,
        admin_email: str,
    ) -> None:
        """
        Lift quarantine after operator submits corrected policy.
        Updates policy_hash to the corrected value.
        Emits RegistryQuarantineLifted event.
        """
        result = await db.execute(
            select(FederatedRegistryCompliance).where(
                FederatedRegistryCompliance.peer_registry_id == peer_id
            )
        )
        compliance = result.scalar_one_or_none()
        if compliance is None:
            raise ValueError(f"No compliance record for peer_id={peer_id}")
        if compliance.federation_status == "blacklisted":
            raise ValueError(
                f"Peer {peer_id} is blacklisted — quarantine lift not applicable"
            )
        # §MCPTEST30 (V0638, agentvault2-aa): only a quarantine is lifted. On a federated peer this rewrote the admitted
        # policy hash with the caller's value and emitted a RegistryQuarantineLifted for a quarantine that never was: the
        # API tester's probe set sbx-alpha's operator peer's hash to "aaaa..." on 2026-10-18, and every compliance poll
        # since read a drift (363 drift events by 10-24).
        if compliance.federation_status != "quarantined":
            raise NotQuarantined(
                f"not_quarantined: peer {peer_id} is {compliance.federation_status}, not quarantined: there is nothing "
                f"to lift, and its admitted policy hash stays as it is"
            )

        compliance.federation_status = "federated"
        compliance.policy_hash = new_policy_hash
        compliance.quarantine_reason = None
        compliance.quarantine_since = None
        compliance.quarantine_grace_expires = None

        await db.commit()

        emitter = get_event_emitter()
        await emitter.emit(
            event_type="RegistryQuarantineLifted",
            aggregate_id=str(peer_id),
            aggregate_type="FederatedRegistry",
            data={
                "peer_registry_id": peer_id,
                "new_policy_hash": new_policy_hash,
                "lifted_by": admin_email,
            },
        )

        logger.info(
            f"[ComplianceMonitor] Quarantine lifted for peer {peer_id} by {admin_email}"
        )

        # The TEG partner rule (ledgergate3): the RegistryQuarantined reactor removed this peer from this frame's TEG
        # partners and no leg adds it back, so the peer's own legs into this frame stay refused until this frame next
        # sends to it. The lift registers it again (nothing moves; logged and non-fatal).
        try:
            from agentvault_registry.background_tasks.reactor_helpers import register_peer_partner_on_teg
            lifted = (await db.execute(select(PeerRegistry).where(PeerRegistry.id == peer_id))).scalar_one_or_none()
            if lifted is not None:
                await register_peer_partner_on_teg(db, lifted.name, source_label="quarantine-lift")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ComplianceMonitor] TEG partner re-registration for peer {peer_id} failed: {exc}")

    # ── Blacklist ─────────────────────────────────────────────────────────────

    async def trigger_blacklist(
        self,
        db: AsyncSession,
        peer_id: int,
        reason: str,
        admin_email: str,
        automated: bool = False,
    ) -> None:
        """
        Permanently blacklist a federated registry.
        Also sets PeerRegistry.status = 'REJECTED'.
        Emits RegistryBlacklisted event — immutable, no automated recovery.
        ⚠️ IRREVERSIBLE from API — requires direct DB intervention to undo.
        """
        result = await db.execute(
            select(FederatedRegistryCompliance).where(
                FederatedRegistryCompliance.peer_registry_id == peer_id
            )
        )
        compliance = result.scalar_one_or_none()
        if compliance is None:
            raise ValueError(f"No compliance record for peer_id={peer_id}")

        # Also mark the PeerRegistry row as REJECTED
        peer_result = await db.execute(
            select(PeerRegistry).where(PeerRegistry.id == peer_id)
        )
        peer = peer_result.scalar_one_or_none()
        peer_name = peer.name if peer else "unknown"
        if peer:
            peer.status = "REJECTED"

        compliance.federation_status = "blacklisted"
        compliance.blacklist_reason = reason
        compliance.compliance_score = 0.0
        # Clear quarantine fields
        compliance.quarantine_reason = None
        compliance.quarantine_since = None
        compliance.quarantine_grace_expires = None

        await db.commit()

        emitter = get_event_emitter()
        await emitter.emit(
            event_type="RegistryBlacklisted",
            aggregate_id=str(peer_id),
            aggregate_type="FederatedRegistry",
            data={
                "peer_registry_id": peer_id,
                "peer_name": peer_name,
                "reason": reason,
                "blacklisted_by": admin_email,
                "automated": automated,
            },
        )

        logger.critical(
            f"[ComplianceMonitor] ⛔ Peer {peer_id} ({peer_name}) BLACKLISTED "
            f"by {admin_email}: {reason}"
        )

    # ── Treasury Health (D-FED-10) ────────────────────────────────────────────

    async def check_and_update_treasury_health(
        self,
        db: AsyncSession,
        run_result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Called after each staking distribution run. Re-derives the D-FED-10 streak from the
        distribution LEDGER and records it in RegistryOperatingState.

        §FEELOCK (2026-09-11) — WHAT A ZERO DAY IS. The streak counts consecutive completed
        distribution days on which stakers were OWED a reward and the reward waterfall was
        EXHAUSTED (`staking_reward_records.status = 'partial'`). It used to count every run whose
        total was zero, which is also what a frame with nobody eligible produces: EU's policy floor
        excludes its five unscored stakers, so every run paid nobody and counted a "zero day" on a
        solvent frame, heading for a TREASURY BANKRUPTCY line on 2026-10-09. frame-b (98) and
        frame-c (86) had already fired it the same way. Measured on all thirteen registries: the
        one real streak was a sandbox operator owing 24 stakers a day from a dry waterfall.

          * nobody owed, or only transport failures (`failed`: the TEG never answered, no money
            moved) → no evidence either way; the day is skipped, the streak neither grows nor ends
          * anyone paid in full (`distributed`) → the treasury paid; the streak ends
          * a skipped, failed or repeated RUN cannot count at all: the streak is read from the
            completed distributions, one per date, never from the run that called this. That is
            also why a stored count from the old rule is corrected on the next evaluation, with no
            migration and no hand-edited row.

        At TREASURY_ZERO_DAY_THRESHOLD the two flags are RECORDED and the event is emitted, and
        both say what is true: no code path reads `treasury_max_fee_locked` or
        `treasury_quarantine_triggered`, so nothing is locked and nothing is quarantined.
        `run_result` is context for the log line only.
        """
        result = await db.execute(
            select(RegistryOperatingState).where(
                RegistryOperatingState.id == REGISTRY_STATE_SINGLETON_ID
            )
        )
        state = result.scalar_one_or_none()

        if state is None:
            logger.error(
                "[ComplianceMonitor] RegistryOperatingState singleton missing! "
                "Migration f036 may not have run."
            )
            return None

        rows = (await db.execute(_TREASURY_EVIDENCE_SQL,
                                 {"window": TREASURY_EVIDENCE_WINDOW})).all()
        tally = unfunded_streak(
            [(r[0], int(r[1] or 0), int(r[2] or 0), int(r[3] or 0)) for r in rows]
        )
        streak = tally["streak"]
        previous = int(state.treasury_zero_days or 0)
        was_triggered = bool(state.treasury_quarantine_triggered)
        now = datetime.now(timezone.utc)
        state.last_treasury_check_at = now
        state.treasury_zero_days = streak
        run_status = (run_result or {}).get("status")

        if streak != previous:
            logger.info(
                "[ComplianceMonitor] treasury streak re-derived %d -> %d from %d completed "
                "distribution day(s) (%d with nobody owed or only transport failures; "
                "last solvent day %s; this run: %s)",
                previous, streak, tally["days_read"], tally["neutral_days"],
                tally["last_solvent_date"], run_status,
            )
        if streak:
            logger.warning(
                "[ComplianceMonitor] the reward waterfall could not fund owed staking rewards "
                "on %d consecutive distribution day(s) (threshold %d)",
                streak, TREASURY_ZERO_DAY_THRESHOLD,
            )

        if streak >= TREASURY_ZERO_DAY_THRESHOLD and not was_triggered:
            state.treasury_max_fee_locked = True
            state.treasury_quarantine_triggered = True
            await db.commit()
            await get_event_emitter().emit(
                event_type="TreasuryBankruptcyQuarantineTriggered",
                aggregate_id="system",
                aggregate_type="Registry",
                idempotency_key=f"treasury-quarantine-triggered-{now.date().isoformat()}",  # §SILENT: once per day
                data={
                    "zero_days": streak,
                    "threshold": TREASURY_ZERO_DAY_THRESHOLD,
                    "basis": TREASURY_STREAK_BASIS,
                    "last_solvent_date": (str(tally["last_solvent_date"])
                                          if tally["last_solvent_date"] else None),
                    "action": "flags_recorded",
                    "enforced": False,
                    "triggered_at": now.isoformat(),
                },
            )
            logger.critical(
                "[ComplianceMonitor] TREASURY CANNOT FUND STAKING REWARDS: %d consecutive "
                "distribution days on which stakers were owed a reward and the reward waterfall "
                "was exhausted. The max-fee-lock and quarantine flags are RECORDED ONLY: no code "
                "path reads them, so nothing is locked or quarantined (D-FED-10 enforcement is "
                "not built).",
                streak,
            )
        elif was_triggered and streak < TREASURY_ZERO_DAY_THRESHOLD:
            reason = ("solvent_day" if streak == 0 and tally["last_solvent_date"] is not None
                      else "recount")
            state.treasury_max_fee_locked = False
            state.treasury_quarantine_triggered = False
            await db.commit()
            await get_event_emitter().emit(
                event_type="TreasuryQuarantineLifted",
                aggregate_id="system",
                aggregate_type="Registry",
                idempotency_key=f"treasury-quarantine-lifted-{now.date().isoformat()}",  # §SILENT: once per day
                data={
                    "lifted_at": now.isoformat(),
                    "reason": reason,
                    "zero_days_before": previous,
                    "zero_days_now": streak,
                    "basis": TREASURY_STREAK_BASIS,
                    "message": ("the payout waterfall paid a lock holder in full"
                                if reason == "solvent_day" else
                                "re-derived from the distribution ledger: the streak no longer "
                                "meets the threshold (the earlier count included days on which "
                                "nobody was owed a payout)"),
                },
            )
            logger.info(
                "[ComplianceMonitor] treasury flags cleared (%s): streak %d -> %d",
                reason, previous, streak,
            )
        else:
            await db.commit()
        return {"streak": streak, "previous": previous, **tally}


# ── Treasury streak (D-FED-10, §FEELOCK) ─────────────────────────────────────

TREASURY_ZERO_DAY_THRESHOLD = 30
# Completed distribution days read per evaluation. Twice the threshold, so a streak that could
# trigger is always inside the window even with some days on which nobody was owed.
TREASURY_EVIDENCE_WINDOW = 60
TREASURY_STREAK_BASIS = (
    "consecutive completed distribution days on which stakers were owed a reward and the reward "
    "waterfall was exhausted; days with nobody owed, or with only transport failures, are not "
    "counted, and a day on which any staker was paid in full ends the streak"
)

# One row per distribution DATE (grouped, so a second completed row for a date could never count
# twice): how many owed stakers were paid in full, hit an exhausted waterfall, or failed on transport.
_TREASURY_EVIDENCE_SQL = text(
    "SELECT d.distribution_date, "
    "count(r.id) FILTER (WHERE r.status = 'distributed') AS paid, "
    "count(r.id) FILTER (WHERE r.status = 'partial') AS exhausted, "
    "count(r.id) FILTER (WHERE r.status = 'failed') AS failed "
    "FROM staking_distributions d "
    "LEFT JOIN staking_reward_records r ON r.distribution_id = d.id "
    "WHERE d.status = 'completed' "
    "GROUP BY d.distribution_date "
    "ORDER BY d.distribution_date DESC "
    "LIMIT :window"
)


def unfunded_streak(days: Sequence[Tuple[Any, int, int, int]]) -> Dict[str, Any]:
    """The D-FED-10 streak from distribution days, NEWEST FIRST: (date, paid, exhausted, failed).

    Walks back from the newest day: a day with anyone paid in full ends the walk; a day with owed
    stakers and an exhausted waterfall adds one; any other day (nobody owed, or only transport
    failures) is no evidence and is stepped over.
    """
    streak = 0
    neutral = 0
    last_solvent = None
    for day, paid, exhausted, _failed in days:
        if paid > 0:
            last_solvent = day
            break
        if exhausted > 0:
            streak += 1
        else:
            neutral += 1
    return {
        "streak": streak,
        "neutral_days": neutral,
        "last_solvent_date": last_solvent,
        "days_read": len(days),
    }


# ── Module-level singleton ────────────────────────────────────────────────────

_monitor: Optional[FederationComplianceMonitor] = None


def get_federation_compliance_monitor() -> FederationComplianceMonitor:
    """Return the module-level singleton FederationComplianceMonitor."""
    global _monitor
    if _monitor is None:
        _monitor = FederationComplianceMonitor()
    return _monitor
