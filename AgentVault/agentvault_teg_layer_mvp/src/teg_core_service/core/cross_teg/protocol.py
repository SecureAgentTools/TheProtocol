"""
Cross-TEG Transfer Protocol Implementation.

Handles the distributed transfer logic between separated TEG layers.
"""

import asyncio
import logging
from contextlib import contextmanager
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, and_, text

from ...database import get_db
from ...database.models import AgentTEGProfile, TEGTransaction, TransactionType, TransactionStatus, CrossTEGTransfer, CrossTEGTransferStatus
from ...database.crud import SystemConfigCRUD, AgentCRUD
from ..cross_teg_security import cross_teg_security_monitor
from .messages import (
    CrossTEGTransferRequest,
    CrossTEGTransferResponse,
    TransferStatus,
    TransferLockRequest,
    TransferLockResponse,
    TransferAcceptRequest,
    TransferAcceptResponse,
    CompensationRequest,
    CompensationResponse
)

logger = logging.getLogger(__name__)


class TransferState(str, Enum):
    """Internal state machine for cross-TEG transfers."""
    INITIATED = "initiated"
    FUNDS_LOCKED = "funds_locked"
    TRANSFER_SENT = "transfer_sent"
    TRANSFER_ACCEPTED = "transfer_accepted"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class CrossTEGTransferProtocol:
    """
    Implements the AVTP cross-TEG transfer protocol.
    
    This protocol ensures ACID properties across distributed TEG layers:
    - Atomicity: Two-phase commit with compensation
    - Consistency: State machine enforcement
    - Isolation: Transfer locking mechanism
    - Durability: Persistent state tracking
    """
    
    def __init__(self, teg_id: str, db_session_factory):
        self.teg_id = teg_id
        self.db_session_factory = db_session_factory
        self.active_transfers: Dict[str, TransferState] = {}
        self.transfer_locks: Dict[str, datetime] = {}
        # Per-agent ordered locks: prevents DB deadlocks when concurrent
        # transfers involve the same agent. Lock by sorted DID order.
        self._agent_locks: Dict[str, asyncio.Lock] = {}
        self._agent_locks_mutex = asyncio.Lock()

    async def _acquire_agent_lock(self, agent_id: str) -> asyncio.Lock:
        """Get or create a per-agent asyncio.Lock."""
        async with self._agent_locks_mutex:
            if agent_id not in self._agent_locks:
                self._agent_locks[agent_id] = asyncio.Lock()
            return self._agent_locks[agent_id]

    @contextmanager
    def _get_session(self):
        """OWL-BRIDGE: Wrap sync generator db_session_factory into a context manager."""
        db_gen = self.db_session_factory()
        session = next(db_gen)
        try:
            yield session
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
        
    async def initiate_transfer(
        self,
        request: CrossTEGTransferRequest
    ) -> CrossTEGTransferResponse:
        """
        Initiate a cross-TEG transfer as the source TEG.
        
        Steps:
        1. Validate the request
        2. Lock funds in source account
        3. Send transfer to target TEG
        4. Wait for acceptance
        5. Complete or compensate
        """
        logger.info(
            f"Initiating cross-TEG transfer {request.transfer_id} "
            f"from {request.source_agent_id} to {request.target_agent_id}"
        )
        
        # Check if this is a duplicate request
        if request.transfer_id in self.active_transfers:
            logger.warning(f"Duplicate transfer request: {request.transfer_id}")
            return CrossTEGTransferResponse(
                transfer_id=request.transfer_id,
                correlation_id=request.correlation_id,
                status=TransferStatus.FAILED,
                processing_teg_id=self.teg_id,
                success=False,
                message="Duplicate transfer request",
                error_code="DUPLICATE_REQUEST"
            )
        
        # Initialize transfer state
        self.active_transfers[request.transfer_id] = TransferState.INITIATED
        
        # Security monitoring
        if cross_teg_security_monitor:
            with self._get_session() as monitor_db:
                monitoring_result = await cross_teg_security_monitor.monitor_transfer(
                    db=monitor_db,
                    transfer_id=request.transfer_id,
                    source_agent=request.source_agent_id,
                    target_agent=request.target_agent_id,
                    amount=request.amount,
                    source_teg=self.teg_id,
                    target_teg=request.target_teg_id
                )
            
            # Check risk score
            if monitoring_result["risk_score"] > 0.8:
                logger.error(
                    f"Transfer {request.transfer_id} blocked due to high risk score: "
                    f"{monitoring_result['risk_score']}"
                )
                return CrossTEGTransferResponse(
                    transfer_id=request.transfer_id,
                    correlation_id=request.correlation_id,
                    status=TransferStatus.FAILED,
                    processing_teg_id=self.teg_id,
                    success=False,
                    message="Transfer blocked due to security concerns",
                    error_code="SECURITY_BLOCK"
                )
        
        try:
            # Step 1: Lock funds
            lock_result = await self._lock_funds(
                transfer_id=request.transfer_id,
                agent_id=request.source_agent_id,
                amount=request.amount,
                expires_at=request.expires_at
            )
            
            if not lock_result.locked:
                raise Exception(f"Failed to lock funds: {lock_result.error}")
            
            self.active_transfers[request.transfer_id] = TransferState.FUNDS_LOCKED
            
            # Step 2: Send to target TEG (this would be an actual network call)
            # For now, we'll simulate this
            logger.info(
                f"Sending transfer {request.transfer_id} to target TEG {request.target_teg_id}"
            )
            
            # In production, this would be an async HTTP/gRPC call to the target TEG
            # For testing, we'll need to implement a mock or use a message queue
            
            # Simulate successful acceptance for now
            self.active_transfers[request.transfer_id] = TransferState.TRANSFER_ACCEPTED
            
            # Step 3: Complete the transfer
            await self._complete_transfer(request)
            
            return CrossTEGTransferResponse(
                transfer_id=request.transfer_id,
                correlation_id=request.correlation_id,
                status=TransferStatus.COMPLETED,
                processing_teg_id=self.teg_id,
                success=True,
                message="Transfer completed successfully",
                transaction_hash=f"mock_tx_hash_{request.transfer_id}"
            )
            
        except Exception as e:
            logger.error(f"Transfer {request.transfer_id} failed: {str(e)}")
            
            # Compensate if funds were locked
            if self.active_transfers.get(request.transfer_id) in [
                TransferState.FUNDS_LOCKED,
                TransferState.TRANSFER_SENT
            ]:
                await self._compensate_transfer(
                    transfer_id=request.transfer_id,
                    agent_id=request.source_agent_id,
                    amount=request.amount,
                    reason=str(e)
                )
            
            return CrossTEGTransferResponse(
                transfer_id=request.transfer_id,
                correlation_id=request.correlation_id,
                status=TransferStatus.FAILED,
                processing_teg_id=self.teg_id,
                success=False,
                message=str(e),
                error_code="TRANSFER_FAILED"
            )
        
        finally:
            # Clean up transfer state after completion
            if request.transfer_id in self.active_transfers:
                del self.active_transfers[request.transfer_id]
            if request.transfer_id in self.transfer_locks:
                del self.transfer_locks[request.transfer_id]
    
    async def accept_transfer(
        self,
        request: TransferAcceptRequest
    ) -> TransferAcceptResponse:
        """
        Accept an incoming cross-TEG transfer as the target TEG.
        
        Steps:
        1. Validate the authorization token
        2. Credit the recipient account
        3. Return acceptance confirmation
        """
        logger.info(
            f"Accepting cross-TEG transfer {request.transfer_id} "
            f"for recipient {request.recipient_agent_id}"
        )
        
        try:
            # In production, validate the authorization token here
            # For now, we'll assume it's valid

            with self._get_session() as session:
                # §P2 (2026-06-09): idempotent — if this transfer was already accepted (its credit
                # leg TEGTransaction exists), return success WITHOUT re-crediting. A re-driven commit
                # (cross-worker replay, or the new connection-drop retry) must not double-credit.
                _prior = session.execute(
                    select(TEGTransaction).where(TEGTransaction.transaction_id == request.transfer_id)
                ).scalar_one_or_none()
                if _prior is not None:
                    _fee = (request.amount * Decimal('0.5') / Decimal('100')).quantize(Decimal('0.000001'))
                    logger.info(f"[ACCEPT] idempotent replay — transfer {request.transfer_id} already accepted")
                    return TransferAcceptResponse(
                        transfer_id=request.transfer_id, accepted=True,
                        transaction_hash=request.transfer_id, fee_amount=_fee,
                        credited_amount=request.amount - _fee,
                    )
                # §P3-T2 (2026-06-09): lock-ordering. This credit leg mutates the recipient
                # AND the shared @fee_collector row. Acquire BOTH up front in deterministic
                # agent_id order (mirror TransferService.execute_transfer, crud.py:708-711) so
                # concurrent FX-route credit legs can't deadlock-cycle on @fee_collector.
                # Δ-neutral — locking/ordering only; amounts unchanged.
                fee_collector_address = SystemConfigCRUD.get_fee_collection_address(session)

                # Ensure the recipient row exists (preserve the W2 cross-frame home guard).
                recipient_exists = session.execute(
                    select(AgentTEGProfile.agent_id).where(
                        AgentTEGProfile.agent_id == request.recipient_agent_id
                    )
                ).scalar_one_or_none()
                if recipient_exists is None:
                    # W2 guard (2026-05-05): refuse cross-frame profile creation for agents
                    # whose home is not this TEG's frame. Defense-in-depth on the legacy 2pc path.
                    from ...database.home_frame_resolver import check_home_or_raise
                    check_home_or_raise(request.recipient_agent_id)
                    session.add(AgentTEGProfile(
                        agent_id=request.recipient_agent_id,
                        token_balance=Decimal('0'),
                        locked_balance=Decimal('0'),
                        audited_balance=Decimal('0'),
                    ))
                # Ensure the fee_collector row exists, then flush so both rows are visible
                # to the FOR UPDATE select below.
                AgentCRUD.get_or_create(session, fee_collector_address)
                session.flush()

                _lock_ids = sorted({request.recipient_agent_id, fee_collector_address})
                _locked = session.execute(
                    select(AgentTEGProfile)
                    .where(AgentTEGProfile.agent_id.in_(_lock_ids))
                    .order_by(AgentTEGProfile.agent_id)
                    .with_for_update()
                ).scalars().all()
                _by_id = {p.agent_id: p for p in _locked}
                profile = _by_id[request.recipient_agent_id]
                fee_collector_profile = _by_id[fee_collector_address]

                # Calculate cross-registry fee (0.5% base rate)
                cross_reg_fee_rate = Decimal('0.5')  # percent
                fee_amount = (request.amount * cross_reg_fee_rate / Decimal('100')).quantize(Decimal('0.000001'))
                credited_amount = request.amount - fee_amount

                # Credit receiver (net) + fee_collector (fee) from the locked rows. If
                # recipient == fee_collector the set dedupes to one row → both adds land on it
                # (== full amount), matching the prior get_or_create identity-map behavior.
                # §MONEY-R18 (cross-TEG credit, 2026-09-04): the 2PC RECEIVER side wrote the
                # recipient credit and its 0.5% fee with entry_type unstamped, so both landed in
                # the 'unknown' default bucket and were filed under transit_net. Found by driving
                # a real registry-a -> op-berlin transfer and reading the receiving TEG's journal:
                # the async leg showed 'cross_teg_credit' and the 2PC leg still showed 'unknown'.
                # Mirrors this file's own cross_teg_escrow_lock stamping a few lines below.
                session.execute(text(
                    "SELECT set_config('teg.entry_type','cross_teg_credit',true),"
                    " set_config('teg.entry_ref',:r,true)"
                ), {"r": str(getattr(request, 'transfer_id', ''))[:160]})
                profile.token_balance += credited_amount
                profile.audited_balance = profile.token_balance  # cross-TEG credit is legitimate
                fee_collector_profile.token_balance += fee_amount
                fee_collector_profile.audited_balance = fee_collector_profile.token_balance

                # Record the credit transaction (net amount to receiver)
                transaction = TEGTransaction(
                    transaction_id=request.transfer_id,  # §PlanB-②: align leg id with ES TokensTransferred.data.transaction_id
                    sender_agent_id=request.recipient_agent_id,  # OWL-BRIDGE R4: self-ref for cross-TEG receive
                    receiver_agent_id=request.recipient_agent_id,
                    amount=credited_amount,
                    fee_amount=fee_amount,
                    transaction_type=TransactionType.CROSS_TEG_RECEIVE.value,
                    status=TransactionStatus.COMPLETED
                )
                session.add(transaction)

                # Track cross-TEG transfer (merge to handle existing row from prepare phase)
                cross_teg_record = CrossTEGTransfer(
                    transfer_id=request.transfer_id,
                    correlation_id=request.correlation_id,
                    source_teg_id=request.source_teg_id,
                    source_registry_id="unknown",  # Will be in token claims
                    source_agent_id="unknown",
                    target_teg_id=self.teg_id,
                    target_registry_id="unknown",
                    target_agent_id=request.recipient_agent_id,
                    amount=request.amount,
                    status=CrossTEGTransferStatus.COMPLETED,
                    role="target",
                    credit_transaction_id=transaction.transaction_id,
                    completed_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
                )
                session.merge(cross_teg_record)

                session.commit()

                logger.info(
                    f"Successfully credited {credited_amount} to {request.recipient_agent_id} "
                    f"(fee: {fee_amount} → {fee_collector_address}) "
                    f"for transfer {request.transfer_id}"
                )

                return TransferAcceptResponse(
                    transfer_id=request.transfer_id,
                    accepted=True,
                    transaction_hash=f"rx_tx_hash_{request.transfer_id}",
                    fee_amount=fee_amount,
                    credited_amount=credited_amount,
                )
                
        except Exception as e:
            logger.error(f"Failed to accept transfer {request.transfer_id}: {str(e)}")
            return TransferAcceptResponse(
                transfer_id=request.transfer_id,
                accepted=False,
                error=str(e)
            )
    
    async def _lock_funds(
        self,
        transfer_id: str,
        agent_id: str,
        amount: Decimal,
        expires_at: datetime
    ) -> TransferLockResponse:
        """Lock funds for a cross-TEG transfer.
        Uses per-agent asyncio.Lock to serialize concurrent transfers
        for the same agent, preventing DB-level SELECT FOR UPDATE contention."""
        agent_lock = await self._acquire_agent_lock(agent_id)
        async with agent_lock:
            return await self._lock_funds_inner(transfer_id, agent_id, amount, expires_at)

    async def _lock_funds_inner(
        self,
        transfer_id: str,
        agent_id: str,
        amount: Decimal,
        expires_at: datetime
    ) -> TransferLockResponse:
        """Inner lock_funds — called under per-agent lock."""
        try:
            with self._get_session() as session:
                # §P1a (2026-06-02) — IDEMPOTENT LOCK GUARD (orphan-lock root-cause fix).
                # A retried/duplicate coordinate_transfer re-runs _prepare_local→_lock_funds
                # for the SAME transfer_id; without this guard each call did an unconditional
                # `locked_balance += amount` while the single release only subtracts once →
                # the extra lock is orphaned forever (proven: canary s2 had 4,401 excess
                # re-locks → 644 net orphans = 322 phantom AVT). Mirrors the async path's
                # existing dedup (cross_teg_router.lock-async). Reuses the existing (until now
                # unused) cross_teg_transfers.lock_transaction_id column as the "already-locked"
                # marker — NO migration. FOR UPDATE on the coordination row serializes
                # concurrent cross-worker retries; we lock the coordination row BEFORE the
                # profile row to match _compensate_transfer's lock order (deadlock-safe).
                xfer = session.execute(
                    select(CrossTEGTransfer).where(
                        CrossTEGTransfer.transfer_id == transfer_id,
                        CrossTEGTransfer.role == "source",
                    ).with_for_update()
                ).scalar_one_or_none()
                if xfer is not None and xfer.lock_transaction_id is not None:
                    logger.info(
                        f"[_lock_funds] {transfer_id} already locked "
                        f"(lock_transaction_id={xfer.lock_transaction_id}) — idempotent skip"
                    )
                    return TransferLockResponse(
                        transfer_id=transfer_id,
                        locked=True,
                        lock_transaction_hash=str(xfer.lock_transaction_id),
                    )

                # Get agent profile
                result = session.execute(
                    select(AgentTEGProfile).where(
                        AgentTEGProfile.agent_id == agent_id
                    ).with_for_update()  # Lock the row
                )
                profile = result.scalar_one_or_none()
                
                if not profile:
                    return TransferLockResponse(
                        transfer_id=transfer_id,
                        locked=False,
                        error="Agent profile not found"
                    )
                
                # Check available balance.
                # Use token_balance directly — locked_balance accumulates staking
                # locks and must not gate cross-TEG transfers. Staked tokens are
                # not liquid, but the lock accounting lives separately from the
                # 2PC in-flight escrow. The _complete_transfer step will debit
                # token_balance atomically; staking locks are unaffected.
                available = profile.token_balance
                if available < amount:
                    return TransferLockResponse(
                        transfer_id=transfer_id,
                        locked=False,
                        error=f"Insufficient balance. Available: {available}, Required: {amount}"
                    )
                
                # §pass77 Phase B: tag this journal row so the cross-TEG 2PC escrow
                # lock is distinguishable from a staking lock (both share locked_balance)
                # and visible to the supply auditor instead of masked as 'unknown'→transit_net.
                session.execute(text(
                    "SELECT set_config('teg.entry_type','cross_teg_escrow_lock',true),"
                    " set_config('teg.entry_ref',:r,true)"
                ), {"r": str(transfer_id)})
                # Lock the funds
                profile.locked_balance += amount
                
                # Record the lock transaction
                lock_transaction = TEGTransaction(
                    sender_agent_id=agent_id,
                    receiver_agent_id=agent_id,  # Same agent for lock
                    amount=Decimal('0'),  # No actual transfer, just lock
                    transaction_type=TransactionType.LOCK.value,
                    status=TransactionStatus.COMPLETED
                )
                session.add(lock_transaction)

                # §P1a: stamp the coordination row so a concurrent/subsequent retry's
                # _lock_funds takes the idempotent-skip branch above (no double-lock).
                if xfer is not None:
                    xfer.lock_transaction_id = str(transfer_id)

                session.commit()

                # Track the lock expiration
                self.transfer_locks[transfer_id] = expires_at
                
                logger.info(f"Locked {amount} for transfer {transfer_id}")
                
                return TransferLockResponse(
                    transfer_id=transfer_id,
                    locked=True,
                    lock_transaction_hash=f"lock_tx_{transfer_id}"
                )
                
        except Exception as e:
            logger.error(f"Failed to lock funds for transfer {transfer_id}: {str(e)}")
            return TransferLockResponse(
                transfer_id=transfer_id,
                locked=False,
                error=str(e)
            )
    
    async def _complete_transfer(self, request: CrossTEGTransferRequest):
        """Complete a cross-TEG transfer by debiting the locked funds.
        Uses per-agent lock to prevent contention on the sender's row."""
        agent_lock = await self._acquire_agent_lock(request.source_agent_id)
        async with agent_lock:
            await self._complete_transfer_inner(request)

    async def _complete_transfer_inner(self, request: CrossTEGTransferRequest):
        """Inner complete — called under per-agent lock."""
        with self._get_session() as session:
            # §P2 (2026-06-09): idempotent — if the debit leg was already recorded (re-driven
            # commit / connection-drop retry), skip the debit + lock-release; don't double-debit.
            _prior = session.execute(
                select(TEGTransaction).where(TEGTransaction.transaction_id == request.transfer_id)
            ).scalar_one_or_none()
            if _prior is not None:
                logger.info(f"[COMPLETE] idempotent skip — debit for {request.transfer_id} already recorded")
                return
            # Get agent profile
            result = session.execute(
                select(AgentTEGProfile).where(
                    AgentTEGProfile.agent_id == request.source_agent_id
                ).with_for_update()
            )
            profile = result.scalar_one()
            
            # §pass77 Phase B: tag the release leg (token debit + lock release).
            session.execute(text(
                "SELECT set_config('teg.entry_type','cross_teg_escrow_release',true),"
                " set_config('teg.entry_ref',:r,true)"
            ), {"r": str(request.transfer_id)})
            # Debit the amount and unlock. §V0045 F1 floor-guard on the lock release
            # (the token debit itself is unchanged): never underflow locked_balance.
            profile.token_balance -= request.amount
            _cur_locked = Decimal(str(profile.locked_balance or 0))
            if _cur_locked - request.amount < 0:
                logger.warning(
                    f"[LOCKED-FLOOR] complete {request.transfer_id}: releasing {request.amount} "
                    f"would underflow locked_balance {_cur_locked} for {request.source_agent_id} "
                    f"— clamped to 0 (double-release guard)."
                )
                profile.locked_balance = Decimal("0")
            else:
                profile.locked_balance = _cur_locked - request.amount
            # Keep audited_balance in sync (cross-TEG debit is legitimate)
            profile.audited_balance = profile.token_balance
            
            # Record the debit transaction
            debit_transaction = TEGTransaction(
                transaction_id=request.transfer_id,  # §PlanB-②: align leg id with ES TokensTransferred.data.transaction_id
                sender_agent_id=request.source_agent_id,
                receiver_agent_id=request.target_agent_id,  # OWL-BRIDGE R4: target agent on remote TEG
                amount=request.amount,
                transaction_type=TransactionType.CROSS_TEG_SEND.value,
                status=TransactionStatus.COMPLETED
            )
            session.add(debit_transaction)
            
            # Update cross-TEG transfer record
            cross_teg_record = CrossTEGTransfer(
                transfer_id=request.transfer_id,
                correlation_id=request.correlation_id,
                source_teg_id=self.teg_id,
                source_registry_id=request.source_registry_id,
                source_agent_id=request.source_agent_id,
                target_teg_id=request.target_teg_id,
                target_registry_id=request.target_registry_id,
                target_agent_id=request.target_agent_id,
                amount=request.amount,
                status=CrossTEGTransferStatus.COMPLETED,
                role="source",
                debit_transaction_id=debit_transaction.transaction_id,
                completed_at=datetime.now(timezone.utc),
                expires_at=request.expires_at
            )
            session.merge(cross_teg_record)  # Update existing record
            
            session.commit()
            
            logger.info(
                f"Completed transfer {request.transfer_id}: "
                f"Debited {request.amount} from {request.source_agent_id}"
            )
        # §V0045 F1 hygiene: drop this worker's in-memory expiry entry so a completed
        # transfer never enters cleanup_expired_locks. (Per-worker only — the DB-status
        # guard in _compensate_transfer_inner is the cross-worker fix.)
        self.transfer_locks.pop(request.transfer_id, None)
        self.active_transfers.pop(request.transfer_id, None)
    
    async def _compensate_transfer(
        self,
        transfer_id: str,
        agent_id: str,
        amount: Decimal,
        reason: str
    ):
        """Compensate (rollback) a failed transfer by unlocking funds."""
        agent_lock = await self._acquire_agent_lock(agent_id)
        async with agent_lock:
            await self._compensate_transfer_inner(transfer_id, agent_id, amount, reason)

    async def _compensate_transfer_inner(
        self,
        transfer_id: str,
        agent_id: str,
        amount: Decimal,
        reason: str
    ):
        """Inner compensate — called under per-agent lock.

        §pass48 F1 (2026-05-19) — idempotency guard. Re-fetch the row INSIDE
        the per-agent lock + skip if already COMPENSATED. Without this guard,
        two concurrent callers (e.g. cleanup_expired_locks + sweeper) both
        passing the outer status check would BOTH subtract `amount` from
        `profile.locked_balance` → double-decrement → underflow.

        The per-agent lock serializes the two callers but the existing code
        never rechecked status under the lock, so the first caller's UPDATE
        was effectively invisible to the second. Now we re-fetch the row
        under the lock; if it's already COMPENSATED the second caller
        returns early without mutating the balance.
        """
        try:
            with self._get_session() as session:
                # §pass48 F1 — idempotency check.
                pre_check = session.execute(
                    select(CrossTEGTransfer).where(
                        CrossTEGTransfer.transfer_id == transfer_id
                    ).with_for_update()
                )
                pre_row = pre_check.scalar_one_or_none()
                if pre_row is not None:
                    status_val = pre_row.status.value if hasattr(pre_row.status, "value") else str(pre_row.status)
                    _sv = status_val.lower()
                    if _sv.endswith("compensated"):
                        logger.info(
                            f"Compensate skipped for {transfer_id}: row already "
                            f"COMPENSATED (idempotent guard, §pass48 F1)"
                        )
                        self.transfer_locks.pop(transfer_id, None)
                        return
                    # §V0045 F1 — a COMPLETED transfer already released its lock in the
                    # debit leg (_complete_transfer_inner). transfer_locks is PER-WORKER
                    # memory: the worker that locked may never see the completion handled
                    # by a sibling worker, so its expiry sweep (cleanup_expired_locks)
                    # would compensate a finished transfer → locked_balance double-release
                    # → negative lock (the −0.5 canary signature). COMPLETED is terminal
                    # for the lock: skip, never re-release.
                    if _sv.endswith("completed"):
                        logger.warning(
                            f"[F1-GUARD] compensate skipped for {transfer_id}: row already "
                            f"COMPLETED — lock was released by the debit leg; an expiry/"
                            f"cleanup caller raced a finished transfer (double-release prevented)."
                        )
                        self.transfer_locks.pop(transfer_id, None)
                        return

                # Get agent profile
                result = session.execute(
                    select(AgentTEGProfile).where(
                        AgentTEGProfile.agent_id == agent_id
                    ).with_for_update()
                )
                profile = result.scalar_one()

                # §pass77 Phase B: tag the compensation (lock release on abort/timeout).
                session.execute(text(
                    "SELECT set_config('teg.entry_type','cross_teg_escrow_compensate',true),"
                    " set_config('teg.entry_ref',:r,true)"
                ), {"r": str(transfer_id)})
                # Unlock the funds — §V0045 F1 floor-guard: a release racing another
                # release path must NEVER drive locked_balance below zero. The clamp is
                # Δ-neutral (locked_balance is escrow bookkeeping, not supply).
                _cur_locked = Decimal(str(profile.locked_balance or 0))
                if _cur_locked - amount < 0:
                    logger.warning(
                        f"[LOCKED-FLOOR] compensate {transfer_id}: releasing {amount} would "
                        f"underflow locked_balance {_cur_locked} for {agent_id} — clamped to 0 "
                        f"(double-release guard)."
                    )
                    profile.locked_balance = Decimal("0")
                else:
                    profile.locked_balance = _cur_locked - amount

                # Record the compensation transaction
                compensation_transaction = TEGTransaction(
                    sender_agent_id=agent_id,
                    receiver_agent_id=agent_id,  # Same agent for unlock
                    amount=Decimal('0'),  # No actual transfer, just unlock
                    transaction_type=TransactionType.UNLOCK.value,
                    status=TransactionStatus.COMPLETED
                )
                session.add(compensation_transaction)

                # Update cross-TEG transfer record (use the locked row from above).
                cross_teg_record = pre_row
                if cross_teg_record is not None:
                    cross_teg_record.status = CrossTEGTransferStatus.COMPENSATED
                    cross_teg_record.error_message = reason
                    cross_teg_record.compensation_transaction_id = compensation_transaction.transaction_id

                session.commit()

                logger.info(
                    f"Compensated transfer {transfer_id}: "
                    f"Unlocked {amount} for {agent_id}"
                )
                
        except Exception as e:
            logger.error(
                f"Failed to compensate transfer {transfer_id}: {str(e)}"
            )
            # In production, this would trigger an alert as manual intervention
            # might be needed to unlock the funds
    
    async def cleanup_expired_locks(self):
        """Periodic task to clean up expired transfer locks.

        §pass47 C3 (2026-05-19) — was a TODO stub that only mutated in-memory
        dicts. The DB row for an INITIATED-past-expires_at transfer would
        stay forever and sender's `locked_balance` was never released —
        documented as the 36-day / 34.49 AVT leak on Frame-A TEG. Memory:
        `project_lock_leak_teg_metadata_class`.

        Fix: look up the cross_teg_transfers DB row by transfer_id to obtain
        the (source_agent_id, amount) tuple that `_compensate_transfer`
        requires, then call it to release `locked_balance` + flip the row to
        COMPENSATED. Errors are logged per-row but never raised — the
        cleanup loop must not crash on a single bad row.

        The §pass26 durable sweeper (`core/cross_teg/sweeper.py`) covers the
        same class of expired-source-side coordinations via a DB-queried path;
        this method still runs against the in-memory `transfer_locks` dict
        (populated when this process orchestrated a PREPARE that never
        committed). Both paths converge on `_compensate_transfer`, which is
        idempotent — a row already COMPENSATED won't be double-released.
        """
        current_time = datetime.now(timezone.utc)
        expired_transfers = [
            tid for tid, exp in self.transfer_locks.items() if current_time > exp
        ]

        for transfer_id in expired_transfers:
            logger.warning(
                f"Transfer {transfer_id} expired, compensating + cleaning up"
            )
            try:
                # Look up the row to obtain agent_id + amount.
                with self._get_session() as session:
                    result = session.execute(
                        select(CrossTEGTransfer).where(
                            CrossTEGTransfer.transfer_id == transfer_id
                        )
                    )
                    row = result.scalar_one_or_none()
                if row is None:
                    logger.info(
                        f"  no cross_teg_transfers row for {transfer_id} — "
                        f"clearing in-memory state only"
                    )
                elif row.status in (CrossTEGTransferStatus.COMPENSATED.value, CrossTEGTransferStatus.COMPENSATED,
                                    CrossTEGTransferStatus.COMPLETED.value, CrossTEGTransferStatus.COMPLETED):
                    # §V0045 F1: COMPLETED added — its lock was already released by the
                    # debit leg; compensating it would double-release (negative lock).
                    logger.info(
                        f"  {transfer_id} already terminal ({row.status}) — clearing in-memory state only"
                    )
                else:
                    await self._compensate_transfer(
                        transfer_id=transfer_id,
                        agent_id=row.source_agent_id,
                        amount=row.amount,
                        reason="cleanup_expired_locks_pass47_C3",
                    )
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"Compensation failed for expired transfer {transfer_id}: {e}"
                )
            # Always clear in-memory state, regardless of compensation outcome.
            self.transfer_locks.pop(transfer_id, None)
            self.active_transfers.pop(transfer_id, None)
