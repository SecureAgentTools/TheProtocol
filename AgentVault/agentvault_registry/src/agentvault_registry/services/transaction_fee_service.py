"""
TransactionFeeService — Economic Engine §4.8

Calculates and records dynamic transaction fees on agent-to-agent AVT transfers.

Fee model (the rates come from the active policy document's transaction_fees block):
  base_rate  = base_rate_percent (0.5% by default)
  velocity   = if the sender's velocity index > 0.7 the rate rises linearly to max_rate
  max_rate   = max_rate_percent (5% by default)

Integration point:
  Called from teg_integration.py in the /teg/transfer handler BEFORE the TEG
  proxy call. The fee moves to the registry's fee account through the TEG with the transfer,
  and a TransactionFeeRecord row is the audit trail.

Velocity index:
  background_tasks/velocity_snapshot.py writes one per sender per hour: 0 unless the hour had enough senders to
  compare with and this sender moved far more than the hour's median (velocity_indices). A sender without a row in
  the last 7 days reads 0: there is no estimate from ratings any more (an agent that moved nothing could reach the
  maximum rate through it).
"""
import logging
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..models import Agent, TransactionFeeRecord
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default fee constants (overridden by active RegistryEnforcementPolicy)
# ---------------------------------------------------------------------------
DEFAULT_BASE_RATE_PCT = 0.5         # 0.5% base fee (was 1.5%)
DEFAULT_MAX_RATE_PCT = 5.0          # 5% max under velocity scaling (was 7.5%)
VELOCITY_SCALE_THRESHOLD = 0.7     # velocity_index above this triggers dynamic scaling
FEE_FLOOR_AVT = 0                  # no minimum floor — pure percentage (was 1 AVT)


class TransactionFeeService:
    """
    Dynamic transaction fee calculator and recorder.

    Usage (inside a teg_integration.py transfer handler):

        fee_svc = get_transaction_fee_service()
        fee_avt, rate_applied, fee_record = await fee_svc.apply_fee(
            db=db,
            transaction_id=teg_tx_id,
            sender_did=sender_did,
            transfer_amount=amount,
        )
        if fee_avt > 0:
            # sender_balance has already been reduced — proceed with TEG call
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def calculate_fee(
        self,
        db: AsyncSession,
        amount: Decimal,
        velocity_index: float = 0.0,
    ) -> Tuple[Decimal, float]:
        """
        Calculate the fee amount for a given transfer using Decimal precision.

        Returns:
            (fee_avt: Decimal, rate_applied_pct: float)
        """
        base_rate, max_rate = await self._load_rates(db)

        if velocity_index > VELOCITY_SCALE_THRESHOLD:
            excess = (velocity_index - VELOCITY_SCALE_THRESHOLD) / (1.0 - VELOCITY_SCALE_THRESHOLD)
            rate_pct = base_rate + excess * (max_rate - base_rate)
        else:
            rate_pct = base_rate

        rate_pct = min(max_rate, rate_pct)
        # Decimal arithmetic — no int() truncation
        fee = (Decimal(str(amount)) * Decimal(str(rate_pct)) / Decimal("100")).quantize(Decimal("0.000001"))
        fee_floor = Decimal(str(FEE_FLOOR_AVT))
        fee = max(fee_floor, fee)
        return fee, rate_pct

    async def get_fee_for_transfer(
        self,
        db: AsyncSession,
        sender_did: str,
        transfer_amount: Decimal,
    ) -> Tuple[Decimal, float]:
        """
        Calculate the fee for a transfer without any DB writes.
        Uses Decimal precision throughout — no int() truncation.

        Returns:
            (fee_avt: Decimal, rate_applied_pct: float)  — (Decimal("0"), 0.0) if amount is 0.
        """
        if not isinstance(transfer_amount, Decimal):
            transfer_amount = Decimal(str(transfer_amount))
        if transfer_amount <= 0:
            return Decimal("0"), 0.0

        # Verify sender exists (fee makes no sense for unknown agents)
        result = await db.execute(select(Agent).where(Agent.did == sender_did))
        sender = result.scalar_one_or_none()
        if not sender:
            logger.warning(f"[FeeService] Sender {sender_did} not found; fee skipped")
            return 0, 0.0

        velocity_index = await self._get_velocity_index(db, sender_did)
        fee_avt, rate_pct = await self.calculate_fee(db, transfer_amount, velocity_index)
        return fee_avt, rate_pct

    async def apply_fee(
        self,
        db: AsyncSession,
        transaction_id: str,
        sender_did: str,
        transfer_amount: Decimal,
    ) -> Tuple[Decimal, float, Optional[TransactionFeeRecord]]:
        """
        Record the fee audit row after a TEG transfer. Uses Decimal precision.

        IMPORTANT — this method does NOT mutate any balances.  TEG handles the
        actual token movement atomically when fee_amount is passed to the TEG
        /token/transfer endpoint.  This method exists purely for the registry-side
        audit trail (TransactionFeeRecord row + EventStore event).

        Returns:
            (fee_avt: Decimal, rate_applied_pct, TransactionFeeRecord | None)
        """
        if not isinstance(transfer_amount, Decimal):
            transfer_amount = Decimal(str(transfer_amount))
        if transfer_amount <= 0:
            return Decimal("0"), 0.0, None

        # Re-derive fee values for the audit record (consistent with get_fee_for_transfer)
        result = await db.execute(select(Agent).where(Agent.did == sender_did))
        sender = result.scalar_one_or_none()
        if not sender:
            logger.warning(f"[FeeService] Sender {sender_did} not found; audit row skipped")
            return 0, 0.0, None

        velocity_index = await self._get_velocity_index(db, sender_did)
        fee_avt, rate_pct = await self.calculate_fee(db, transfer_amount, velocity_index)
        if fee_avt <= Decimal("0"):
            return Decimal("0"), rate_pct, None

        treasury_did = await self._get_treasury_did()

        # Write audit record — NO balance mutations; TEG owns the token movement
        record = TransactionFeeRecord(
            id=str(uuid.uuid4()),
            transaction_id=transaction_id,
            agent_did=sender_did,
            amount=fee_avt,                  # f029: column is 'amount'
            fee_rate_percent=rate_pct,       # f029: column is 'fee_rate_percent'
            destination='treasury_recycle',  # f029: default destination
            transfer_amount=transfer_amount,  # f030: extended audit
            velocity_index=velocity_index,    # f030: extended audit
            # created_at: server_default=func.now() — do not set manually
        )
        db.add(record)
        await db.commit()

        logger.info(
            f"[FeeService] Fee audit recorded: {fee_avt} AVT ({rate_pct:.2f}%) "
            f"from {sender_did} on tx {transaction_id} (token movement handled by TEG)"
        )

        # EventStore emission removed — teg_integration.py emits TransactionFeeCollected
        # with idempotency key (fee-{tx_id}) to prevent duplicates. Emitting here too
        # caused triple-count: once from teg_integration, once from apply_fee, once from TEG.

        return fee_avt, rate_pct, record

    async def get_current_rate(self, db: AsyncSession) -> Dict[str, Any]:
        """
        Return the effective current fee rate info (for the /fees/current-rate endpoint).
        """
        base_rate, max_rate = await self._load_rates(db)
        return {
            "rate_percent": base_rate,
            "base_rate_percent": base_rate,
            "max_rate_percent": max_rate,
            "velocity_index": 0.0,
            "note": "The rate a transfer pays depends on its sender's velocity index (0 for most senders): the base rate up to 0.7, rising to the maximum at 1.0.",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_rates(self, db: AsyncSession) -> Tuple[float, float]:
        """Return (base_rate_pct, max_rate_pct) from active policy or defaults."""
        try:
            from ..crud.crud_enforcement import get_active_policy, DEFAULT_POLICY_JSON
            row = await get_active_policy(db)
            pj = row.policy_json if row else DEFAULT_POLICY_JSON
            fees = pj.get("transaction_fees", {})
            base = float(fees.get("base_rate_percent", DEFAULT_BASE_RATE_PCT))
            mx = float(fees.get("max_rate_percent", DEFAULT_MAX_RATE_PCT))
            return base, mx
        except Exception:
            return DEFAULT_BASE_RATE_PCT, DEFAULT_MAX_RATE_PCT

    async def _get_velocity_index(self, db: AsyncSession, agent_did: str) -> float:
        """
        Return the velocity index of the sender's latest hourly row (0.0 to 1.0), written by
        background_tasks/velocity_snapshot.py; 0.0 when it has none or the read fails.
        """
        try:
            from ..models import VelocityMetrics
            result = await db.execute(
                select(VelocityMetrics.velocity_index)
                .where(VelocityMetrics.agent_did == agent_did)
                .order_by(VelocityMetrics.window_start.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return float(row) if row is not None else 0.0
        except Exception:
            return 0.0

    async def _get_treasury_did(self) -> Optional[str]:
        """Return treasury DID from config, or None."""
        try:
            from ..config import settings
            # TEG_SYSTEM_TREASURY_DID is the canonical name in config.py
            return getattr(settings, "TEG_SYSTEM_TREASURY_DID", None)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_transaction_fee_service: Optional[TransactionFeeService] = None


def get_transaction_fee_service() -> TransactionFeeService:
    global _transaction_fee_service
    if _transaction_fee_service is None:
        _transaction_fee_service = TransactionFeeService()
    return _transaction_fee_service
