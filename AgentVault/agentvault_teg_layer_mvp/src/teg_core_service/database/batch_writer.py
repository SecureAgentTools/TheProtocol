"""
TEG Batch Writer — Phase 1 Scaling
Buffers token transfers and commits them in batches for higher throughput.
Individual transfer atomicity is preserved via savepoints.

The TEG uses synchronous SQLAlchemy sessions. This module bridges async
callers (FastAPI endpoints) with sync DB operations by running the batch
flush in a thread via asyncio.to_thread.
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

BATCH_FLUSH_INTERVAL_MS = int(os.environ.get("TEG_BATCH_FLUSH_INTERVAL_MS", "10"))
BATCH_MAX_SIZE = int(os.environ.get("TEG_BATCH_MAX_SIZE", "50"))


@dataclass
class TransferRequest:
    """A single transfer request waiting to be batched."""
    sender_id: str
    receiver_id: str
    amount: Decimal
    fee_amount: Decimal
    message: Optional[str]
    future: asyncio.Future = field(default=None)
    loop: asyncio.AbstractEventLoop = field(default=None)

    def __post_init__(self):
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        if self.future is None:
            self.future = self.loop.create_future()


class BatchWriter:
    """
    Batches multiple transfer operations into single DB transactions.

    The buffer collects TransferRequest objects from async callers.
    A periodic asyncio task flushes the buffer every BATCH_FLUSH_INTERVAL_MS
    or when it reaches BATCH_MAX_SIZE items, whichever comes first.

    Because the TEG uses synchronous SQLAlchemy, the actual DB work runs
    in a thread via asyncio.to_thread so the event loop is never blocked.

    Usage:
        writer = BatchWriter(session_factory)
        await writer.start()
        result = await writer.submit_transfer(sender, receiver, amount, fee, msg)
        await writer.stop()
    """

    def __init__(self, session_factory):
        """
        Args:
            session_factory: Callable that returns a new SQLAlchemy Session
                             (e.g. database.db_session.SessionLocal)
        """
        self.session_factory = session_factory
        self._buffer: list[TransferRequest] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        self._flush_in_progress = False
        self._stats = {
            "batches_flushed": 0,
            "transfers_succeeded": 0,
            "transfers_failed": 0,
            "total_flush_time_ms": 0.0,
        }

    async def start(self):
        """Start the periodic flush loop."""
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(
            "[BatchWriter] Started (flush_interval=%dms, max_size=%d)",
            BATCH_FLUSH_INTERVAL_MS,
            BATCH_MAX_SIZE,
        )

    async def stop(self):
        """Stop the flush loop and drain remaining items."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final drain
        if self._buffer:
            await self._flush()
        logger.info("[BatchWriter] Stopped. Stats: %s", self._stats)

    async def submit_transfer(
        self,
        sender_id: str,
        receiver_id: str,
        amount: Decimal,
        fee_amount: Decimal = Decimal("0"),
        message: Optional[str] = None,
    ) -> dict:
        """
        Submit a transfer to be batched.

        Returns when the batch containing this transfer has been committed.

        Returns:
            dict with transaction result (transaction_id, status, etc.)
        Raises:
            ValueError: on insufficient balance or other validation errors
            Exception: on unexpected DB errors
        """
        loop = asyncio.get_running_loop()
        req = TransferRequest(
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount=amount,
            fee_amount=fee_amount,
            message=message,
            loop=loop,
        )

        should_flush = False
        async with self._lock:
            self._buffer.append(req)
            if len(self._buffer) >= BATCH_MAX_SIZE:
                should_flush = True

        # If buffer hit the cap, trigger an immediate flush (non-blocking)
        if should_flush:
            asyncio.ensure_future(self._flush())

        # Wait for this transfer's result
        return await req.future

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _periodic_flush(self):
        """Tick-based flush loop."""
        while self._running:
            await asyncio.sleep(BATCH_FLUSH_INTERVAL_MS / 1000.0)
            if self._buffer:
                await self._flush()

    async def _flush(self):
        """Swap out the buffer and process the batch in a thread."""
        async with self._lock:
            if not self._buffer or self._flush_in_progress:
                return
            batch = self._buffer.copy()
            self._buffer.clear()
            self._flush_in_progress = True

        try:
            # Run synchronous DB work off the event loop
            await asyncio.to_thread(self._flush_sync, batch)
        finally:
            self._flush_in_progress = False

    # ---- synchronous DB work (runs in thread) ----

    def _flush_sync(self, batch: list[TransferRequest]):
        """Execute all transfers in *batch* inside a single DB transaction.

        Each transfer gets its own savepoint so that a failure in transfer K
        does not roll back transfers 1..K-1.
        """
        from .crud import SystemConfigCRUD

        start_time = time.monotonic()
        succeeded = 0
        failed = 0

        db: Session = self.session_factory()
        committed = False
        try:
            for req in batch:
                try:
                    # Savepoint — nested transaction
                    nested = db.begin_nested()
                    try:
                        result = self._execute_single(db, req, None, SystemConfigCRUD)
                        nested.commit()
                        # Resolve the future on the caller's event loop
                        req.loop.call_soon_threadsafe(req.future.set_result, result)
                        succeeded += 1
                    except Exception as exc:
                        try:
                            nested.rollback()
                        except Exception:
                            pass
                        if not req.future.done():
                            req.loop.call_soon_threadsafe(req.future.set_exception, exc)
                        failed += 1
                except Exception as exc:
                    if not req.future.done():
                        req.loop.call_soon_threadsafe(req.future.set_exception, exc)
                    failed += 1

            # Commit the outer transaction (all successful savepoints)
            db.commit()
            committed = True

            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._stats["batches_flushed"] += 1
            self._stats["transfers_succeeded"] += succeeded
            self._stats["transfers_failed"] += failed
            self._stats["total_flush_time_ms"] += elapsed_ms

            if succeeded > 0 or failed > 0:
                logger.info(
                    "[BatchWriter] Flushed batch: %d ok, %d failed in %.1fms",
                    succeeded,
                    failed,
                    elapsed_ms,
                )

        except BaseException as exc:
            # Catch BaseException (not just Exception) so thread-termination,
            # asyncio.CancelledError propagation, and SystemExit all release the
            # DB connection cleanly. Without this, an outer commit interrupted
            # mid-flight could leave the underlying server connection in
            # `idle in transaction wait_event=ClientRead` state — which is what
            # caused the sandbox-A canary wedge on 2026-05-10
            # (feedback_lock_async_cancel_leak.md).
            try:
                db.rollback()
            except Exception:
                pass
            if isinstance(exc, Exception):
                for req in batch:
                    if not req.future.done():
                        req.loop.call_soon_threadsafe(req.future.set_exception, exc)
                logger.error("[BatchWriter] Batch commit failed: %s", exc)
            else:
                # Re-raise non-Exception (KeyboardInterrupt, SystemExit, etc.)
                # so the runtime still sees the termination signal.
                raise
        finally:
            # Belt-and-suspenders: explicit rollback if outer commit didn't run.
            # Pairs with PG-level statement_timeout/idle_in_transaction_session_timeout
            # for defense-in-depth against connection leaks.
            if not committed:
                try:
                    db.rollback()
                except Exception:
                    pass
            try:
                db.close()
            except Exception:
                pass

    @staticmethod
    def _get_or_create_profile(db: Session, agent_id: str):
        """Get or create an AgentTEGProfile WITHOUT committing.

        Unlike ``AgentCRUD.get_or_create`` this version only flushes (no
        commit) so it is safe to call inside a savepoint / nested
        transaction.

        W2 guard (2026-05-05): when TEG_HOME_FRAME_GUARD_ENABLED=true, raises
        AgentNotHomeError if the agent's home is a different frame. Caller's
        savepoint rolls back. System accounts bypass.
        """
        from .models import AgentTEGProfile
        from .home_frame_resolver import check_home_or_raise

        profile = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == agent_id
        ).first()
        if profile is None:
            check_home_or_raise(agent_id)
            profile = AgentTEGProfile(
                agent_id=agent_id,
                token_balance=Decimal("0"),
                audited_balance=Decimal("0"),
                reputation_score=0,
            )
            db.add(profile)
            db.flush()  # flush — NOT commit
        return profile

    @staticmethod
    def _execute_single(
        db: Session,
        req: TransferRequest,
        agent_crud,
        system_config_crud,
    ) -> dict:
        """Execute one transfer inside the current savepoint.

        Mirrors the logic of ``TransferService.execute_transfer`` but without
        committing (the caller controls the transaction boundary).  Uses
        ``_get_or_create_profile`` instead of ``AgentCRUD.get_or_create`` to
        avoid mid-savepoint commits.
        """
        from .models import TEGTransaction, TransactionStatus

        total_deduction = req.amount + req.fee_amount

        # Get or create sender / receiver profiles (flush-only, no commit)
        sender = BatchWriter._get_or_create_profile(db, req.sender_id)
        receiver = BatchWriter._get_or_create_profile(db, req.receiver_id)

        # Layer 0: Audited balance integrity check — ALL parties, not just sender
        import os
        if os.getenv('AUDITED_BALANCE_ENABLED', 'true').lower() == 'true':
            for _cid, _cp in [(req.sender_id, sender), (req.receiver_id, receiver)]:
                if _cp.audited_balance is not None and _cp.token_balance != _cp.audited_balance:
                    raise ValueError(
                        f"Balance integrity check failed for {_cid}: "
                        f"token_balance={_cp.token_balance} != audited_balance={_cp.audited_balance}. "
                        f"This indicates unauthorized balance modification. Contact administrator."
                    )

        # Balance check
        if sender.token_balance < total_deduction:
            raise ValueError(
                f"Insufficient balance: have {sender.token_balance}, "
                f"need {total_deduction}"
            )

        # Create transaction record
        tx_id = str(uuid4())
        transaction = TEGTransaction(
            transaction_id=tx_id,
            sender_agent_id=req.sender_id,
            receiver_agent_id=req.receiver_id,
            amount=req.amount,
            fee_amount=req.fee_amount,
            transaction_type="transfer",
            status=TransactionStatus.COMPLETED,
            attached_message=req.message,
        )
        db.add(transaction)

        # Update balances
        sender.token_balance -= total_deduction
        receiver.token_balance += req.amount

        # Fee collection
        fee_collector = None
        if req.fee_amount > Decimal("0"):
            fee_collector_id = system_config_crud.get_fee_collection_address(db)
            if fee_collector_id:
                fee_collector = BatchWriter._get_or_create_profile(db, fee_collector_id)
                fee_collector.token_balance += req.fee_amount

        # Update audited balances to match (transfer is legitimate)
        sender.audited_balance = sender.token_balance
        receiver.audited_balance = receiver.token_balance
        if fee_collector is not None:
            fee_collector.audited_balance = fee_collector.token_balance

        # Flush so the savepoint captures the writes (but don't commit)
        db.flush()

        return {
            "transaction_id": tx_id,
            "status": "completed",
            "sender_agent_id": req.sender_id,
            "receiver_agent_id": req.receiver_id,
            "amount": str(req.amount),
            "fee_amount": str(req.fee_amount),
            "attached_message": req.message,
        }

    def get_stats(self) -> dict:
        """Return a copy of internal statistics."""
        return dict(self._stats)


# ---- Global singleton ----

_batch_writer: Optional[BatchWriter] = None


def get_batch_writer() -> Optional[BatchWriter]:
    """Get the global batch writer instance (None when disabled)."""
    return _batch_writer


async def init_batch_writer(session_factory) -> BatchWriter:
    """Initialise and start the global batch writer.

    Called from TEG main.py lifespan on startup when TEG_BATCH_WRITES=true.
    Safe to call only once (lifespan is single-threaded).
    """
    global _batch_writer
    if _batch_writer is not None:
        return _batch_writer
    writer = BatchWriter(session_factory)
    await writer.start()
    _batch_writer = writer
    return _batch_writer


async def shutdown_batch_writer():
    """Stop the global batch writer and drain remaining items."""
    global _batch_writer
    if _batch_writer is not None:
        await _batch_writer.stop()
        _batch_writer = None
