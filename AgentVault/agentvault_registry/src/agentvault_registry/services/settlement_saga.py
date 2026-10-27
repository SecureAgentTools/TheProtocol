"""
TITANIUM VAULT D3: Settlement Saga — Cross-Registry Dispute Compensation

Saga coordinator for cross-registry dispute settlements. Wraps the existing
slash-request/confirmation flow with state tracking, timeout detection,
and compensating events on failure.

State Machine:
    INITIATED
      → SLASH_REQUESTED (request sent to defendant's registry)
        → SLASH_CONFIRMED (defendant confirmed slash)
          → COMPENSATION_MINTED (complainant credited)
            → FINALIZED (complete)
        → SLASH_FAILED (defendant rejected or error)
          → ROLLED_BACK
      → TIMED_OUT (72h deadline passed)
        → ROLLED_BACK

Compensating Events:
    - SLASH_REQUESTED → timeout: No funds locked, mark TIMED_OUT + admin notification
    - SLASH_CONFIRMED → callback fails: NOT a rollback (slash happened), origin polls
    - Any state → admin manual override available

Spec reference: Economic Engine §8.2
Pattern precedent: vetoken_calculator.py, dynamic_apy_engine.py
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CrossRegistrySettlement
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

# Saga timeout: 72 hours per spec
SAGA_TIMEOUT_HOURS = 72

# Valid state transitions
VALID_TRANSITIONS = {
    "INITIATED": ["SLASH_REQUESTED", "SLASH_FAILED", "TIMED_OUT", "ROLLED_BACK"],
    "SLASH_REQUESTED": ["SLASH_CONFIRMED", "SLASH_FAILED", "TIMED_OUT", "ROLLED_BACK"],
    "SLASH_CONFIRMED": ["COMPENSATION_MINTED", "TIMED_OUT"],
    "COMPENSATION_MINTED": ["FINALIZED"],
    "SLASH_FAILED": ["ROLLED_BACK"],
    "TIMED_OUT": ["ROLLED_BACK"],
    # Terminal states — no further transitions
    "FINALIZED": [],
    "ROLLED_BACK": [],
    "LEGACY": ["INITIATED", "SLASH_REQUESTED", "FINALIZED"],  # Upgrade path for pre-saga records
}


class SagaStateError(Exception):
    """Invalid saga state transition."""
    pass


class SettlementSaga:
    """
    Saga coordinator for cross-registry dispute settlements.
    
    Wraps the existing slash-request/confirmation flow with:
    - State tracking on CrossRegistrySettlement.saga_state
    - Timeout detection (72h deadline)
    - Compensating events on failure
    - Admin notification for manual resolution
    """
    
    def __init__(self):
        self.event_emitter = get_event_emitter()
    
    def _validate_transition(self, current_state: str, new_state: str) -> None:
        """Validate that a state transition is allowed."""
        allowed = VALID_TRANSITIONS.get(current_state, [])
        if new_state not in allowed:
            raise SagaStateError(
                f"Invalid saga transition: {current_state} → {new_state}. "
                f"Allowed: {allowed}"
            )
    
    async def _transition(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement,
        new_state: str,
        commit: bool = True
    ) -> None:
        """Apply a state transition with validation and timestamp."""
        self._validate_transition(settlement.saga_state, new_state)
        old_state = settlement.saga_state
        settlement.saga_state = new_state
        settlement.saga_last_step_at = datetime.now(timezone.utc)
        
        if commit:
            await db.commit()
        
        logger.info(
            f"[Saga] Settlement {settlement.id}: {old_state} → {new_state}"
        )
    
    async def initiate(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement
    ) -> CrossRegistrySettlement:
        """
        Step 1: Mark saga as initiated, set 72h timeout deadline.
        Called when a new cross-registry settlement is created.
        """
        settlement.saga_state = "INITIATED"
        settlement.saga_timeout_at = datetime.now(timezone.utc) + timedelta(hours=SAGA_TIMEOUT_HOURS)
        settlement.saga_last_step_at = datetime.now(timezone.utc)
        settlement.saga_retry_count = 0
        
        await db.commit()
        
        logger.info(
            f"[Saga] Settlement {settlement.id} INITIATED. "
            f"Timeout at {settlement.saga_timeout_at.isoformat()}"
        )
        
        await self.event_emitter.emit(
            event_type="SettlementSagaInitiated",
            aggregate_id=settlement.complainant_did,
            aggregate_type="Settlement",
            data={
                "settlement_id": settlement.id,
                "dispute_id": settlement.dispute_id,
                "amount": settlement.requested_amount,
                "defendant_did": settlement.defendant_did,
                "defendant_registry": settlement.defendant_registry_url,
                "timeout_at": settlement.saga_timeout_at.isoformat()
            },
            idempotency_key=f"saga_init:{settlement.id}"
        )
        
        return settlement
    
    async def record_slash_requested(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement
    ) -> None:
        """Step 2: Mark that slash-request was sent to defendant's registry."""
        await self._transition(db, settlement, "SLASH_REQUESTED")
        
        await self.event_emitter.emit(
            event_type="SettlementSlashRequested",
            aggregate_id=settlement.defendant_did,
            aggregate_type="Settlement",
            data={
                "settlement_id": settlement.id,
                "dispute_id": settlement.dispute_id,
                "amount": settlement.requested_amount,
                "defendant_registry": settlement.defendant_registry_url
            },
            idempotency_key=f"saga_slash_req:{settlement.id}"
        )
    
    async def record_slash_confirmed(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement,
        slash_event_id: str = "",
        slash_tx_id: str = "",
        slashed_amount: int = 0
    ) -> None:
        """Step 3: Defendant's registry confirmed the slash."""
        settlement.slash_event_id = slash_event_id
        settlement.slash_tx_id = slash_tx_id
        settlement.slashed_amount = slashed_amount
        settlement.slashed_at = datetime.now(timezone.utc)
        
        await self._transition(db, settlement, "SLASH_CONFIRMED")
        
        await self.event_emitter.emit(
            event_type="SettlementSlashConfirmed",
            aggregate_id=settlement.defendant_did,
            aggregate_type="Settlement",
            data={
                "settlement_id": settlement.id,
                "dispute_id": settlement.dispute_id,
                "slashed_amount": slashed_amount,
                "slash_event_id": slash_event_id,
                "slash_tx_id": slash_tx_id
            },
            idempotency_key=f"saga_slash_conf:{settlement.id}"
        )
    
    async def record_compensation_minted(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement,
        mint_event_id: str = "",
        mint_tx_id: str = "",
        minted_amount: int = 0
    ) -> None:
        """Step 4: Complainant's registry minted compensation."""
        settlement.mint_event_id = mint_event_id
        settlement.mint_tx_id = mint_tx_id
        settlement.minted_amount = minted_amount
        
        await self._transition(db, settlement, "COMPENSATION_MINTED")
        
        await self.event_emitter.emit(
            event_type="SettlementCompensationMinted",
            aggregate_id=settlement.complainant_did,
            aggregate_type="Settlement",
            data={
                "settlement_id": settlement.id,
                "dispute_id": settlement.dispute_id,
                "minted_amount": minted_amount,
                "mint_event_id": mint_event_id,
                "mint_tx_id": mint_tx_id
            },
            idempotency_key=f"saga_mint:{settlement.id}"
        )
    
    async def finalize(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement
    ) -> None:
        """Step 5: Mark settlement as complete. Terminal state."""
        settlement.settled_at = datetime.now(timezone.utc)
        settlement.status = "SETTLED"
        
        await self._transition(db, settlement, "FINALIZED")
        
        await self.event_emitter.emit(
            event_type="SettlementFinalized",
            aggregate_id=settlement.complainant_did,
            aggregate_type="Settlement",
            data={
                "settlement_id": settlement.id,
                "dispute_id": settlement.dispute_id,
                "slashed_amount": settlement.slashed_amount,
                "minted_amount": settlement.minted_amount,
                "completed_at": settlement.settled_at.isoformat()
            },
            idempotency_key=f"saga_final:{settlement.id}"
        )
    
    async def record_slash_failed(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement,
        error_message: str = ""
    ) -> None:
        """Mark that the slash request failed (defendant rejected or error)."""
        settlement.error_message = error_message
        settlement.status = "FAILED"
        
        await self._transition(db, settlement, "SLASH_FAILED")
        
        await self.event_emitter.emit(
            event_type="SettlementSlashFailed",
            aggregate_id=settlement.defendant_did,
            aggregate_type="Settlement",
            data={
                "settlement_id": settlement.id,
                "dispute_id": settlement.dispute_id,
                "error": error_message
            },
            idempotency_key=f"saga_slash_fail:{settlement.id}"
        )
    
    async def rollback(
        self,
        db: AsyncSession,
        settlement: CrossRegistrySettlement,
        reason: str = ""
    ) -> None:
        """
        Compensating action: roll back the settlement.
        
        In the current architecture, the most dangerous case is
        SLASH_REQUESTED → timeout. If the defendant DID slash but confirmation
        never arrived, we have an asymmetric state. The saga marks this for
        admin reconciliation — it cannot auto-reverse a remote slash.
        """
        settlement.status = "FAILED"
        settlement.error_message = f"Saga rollback: {reason}"
        
        await self._transition(db, settlement, "ROLLED_BACK")
        
        await self.event_emitter.emit(
            event_type="SettlementRolledBack",
            aggregate_id=settlement.complainant_did,
            aggregate_type="Settlement",
            data={
                "settlement_id": settlement.id,
                "dispute_id": settlement.dispute_id,
                "previous_state": settlement.saga_state,
                "reason": reason,
                "amount": settlement.requested_amount,
                "requires_admin_review": True
            },
            idempotency_key=f"saga_rollback:{settlement.id}"
        )
        
        logger.warning(
            f"[Saga] Settlement {settlement.id} ROLLED BACK: {reason}. "
            f"Admin review required."
        )
    
    async def check_timeouts(self, db: AsyncSession) -> List[str]:
        """
        Background task: find settlements that have exceeded the 72h deadline
        and trigger compensating events.
        
        Should be called every 5 minutes by a periodic background task.
        
        Returns:
            List of settlement IDs that were timed out
        """
        now = datetime.now(timezone.utc)
        
        # Find stale settlements in non-terminal saga states
        result = await db.execute(
            select(CrossRegistrySettlement).where(
                and_(
                    CrossRegistrySettlement.saga_state.in_([
                        "INITIATED",
                        "SLASH_REQUESTED"
                    ]),
                    CrossRegistrySettlement.saga_timeout_at.isnot(None),
                    CrossRegistrySettlement.saga_timeout_at < now
                )
            )
        )
        stale_settlements = result.scalars().all()
        
        timed_out_ids = []
        for settlement in stale_settlements:
            try:
                previous_state = settlement.saga_state
                
                # Transition to TIMED_OUT
                settlement.saga_state = "TIMED_OUT"
                settlement.saga_last_step_at = now
                settlement.status = "EXPIRED"
                settlement.error_message = (
                    f"Saga timeout after {SAGA_TIMEOUT_HOURS}h in state {previous_state}"
                )
                
                await db.commit()
                
                # Emit timeout event
                await self.event_emitter.emit(
                    event_type="SettlementTimeout",
                    aggregate_id=settlement.complainant_did,
                    aggregate_type="Settlement",
                    data={
                        "settlement_id": settlement.id,
                        "dispute_id": settlement.dispute_id,
                        "amount": settlement.requested_amount,
                        "timed_out_in_state": previous_state,
                        "defendant_did": settlement.defendant_did,
                        "defendant_registry": settlement.defendant_registry_url,
                        "requires_admin_review": True,
                        "timeout_hours": SAGA_TIMEOUT_HOURS
                    },
                    idempotency_key=f"saga_timeout:{settlement.id}"
                )
                
                timed_out_ids.append(settlement.id)
                
                logger.warning(
                    f"[Saga] Settlement {settlement.id} TIMED OUT "
                    f"(was in {previous_state} for >{SAGA_TIMEOUT_HOURS}h). "
                    f"Admin review required for dispute {settlement.dispute_id}."
                )
                
            except Exception as e:
                logger.error(
                    f"[Saga] Error processing timeout for settlement {settlement.id}: {e}"
                )
                await db.rollback()
        
        if timed_out_ids:
            logger.info(
                f"[Saga] Timeout check complete: {len(timed_out_ids)} settlements timed out"
            )
        
        return timed_out_ids
    
    async def get_saga_status(
        self,
        db: AsyncSession,
        settlement_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get current saga status for a settlement."""
        result = await db.execute(
            select(CrossRegistrySettlement).where(
                CrossRegistrySettlement.id == settlement_id
            )
        )
        settlement = result.scalar_one_or_none()
        
        if not settlement:
            return None
        
        return {
            "settlement_id": settlement.id,
            "dispute_id": settlement.dispute_id,
            "saga_state": settlement.saga_state,
            "saga_timeout_at": (
                settlement.saga_timeout_at.isoformat()
                if settlement.saga_timeout_at else None
            ),
            "saga_last_step_at": (
                settlement.saga_last_step_at.isoformat()
                if settlement.saga_last_step_at else None
            ),
            "saga_retry_count": settlement.saga_retry_count,
            "status": settlement.status,
            "requested_amount": settlement.requested_amount,
            "slashed_amount": settlement.slashed_amount,
            "minted_amount": settlement.minted_amount,
            "error_message": settlement.error_message,
            "complainant_did": settlement.complainant_did,
            "defendant_did": settlement.defendant_did
        }


# ── Module-level singleton ──────────────────────────────────────────
_settlement_saga: Optional[SettlementSaga] = None


def get_settlement_saga() -> SettlementSaga:
    """Get or create the singleton SettlementSaga instance."""
    global _settlement_saga
    if _settlement_saga is None:
        _settlement_saga = SettlementSaga()
    return _settlement_saga
