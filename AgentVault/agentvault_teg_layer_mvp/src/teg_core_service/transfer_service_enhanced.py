"""
Enhanced TransferService with Event Store integration
This module patches the TransferService to emit events after successful operations
"""

import os
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
import asyncio
import logging

from .database.models import TEGTransaction, TransactionStatus
from .database.crud import TransferService as OriginalTransferService, TransactionCRUD, AgentCRUD, SystemConfigCRUD
from .event_emitter import EventEmitter
from .core.config import get_settings

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Prometheus instrumentation (added 2026-04-30 — for Grafana TEG dashboard)
# ----------------------------------------------------------------------
try:
    from prometheus_client import Counter, Histogram

    TEG_TRANSFERS_TOTAL = Counter(
        "teg_transfers_total",
        "TEG token transfer attempts by result + kind",
        labelnames=["kind", "result"],  # kind: transfer|issuance ; result: success|failed
    )
    TEG_TRANSFER_AMOUNT = Histogram(
        "teg_transfer_amount_avt",
        "Distribution of transfer amounts in AVT",
        buckets=(0.1, 1, 10, 100, 1000, 10000, 100000, 1000000),
    )
    TEG_FEES_COLLECTED_AVT_TOTAL = Counter(
        "teg_fees_collected_avt_total",
        "Cumulative AVT fees collected by the TEG fee_collector account",
    )
    TEG_ISSUED_AVT_TOTAL = Counter(
        "teg_issued_avt_total",
        "Cumulative AVT minted via /admin/token/issue (lifetime, resets on container restart)",
    )
    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False
    TEG_TRANSFERS_TOTAL = None  # type: ignore[assignment]
    TEG_TRANSFER_AMOUNT = None  # type: ignore[assignment]
    TEG_FEES_COLLECTED_AVT_TOTAL = None  # type: ignore[assignment]
    TEG_ISSUED_AVT_TOTAL = None  # type: ignore[assignment]


def _teg_id() -> str:
    return os.getenv("TEG_ID", "teg")

# Initialize Event Emitter
settings = get_settings()
event_emitter = EventEmitter(
    event_store_url=settings.event_store_url if hasattr(settings, 'event_store_url') else "http://localhost:8200",
    internal_api_key=settings.event_store_api_key if hasattr(settings, 'event_store_api_key') else "",
    source_service="teg"
)


class EnhancedTransferService(OriginalTransferService):
    """Enhanced TransferService that emits events to the Event Store"""
    
    @staticmethod
    def execute_transfer(
        db: Session,
        sender_id: str,
        receiver_id: str,
        amount: Decimal,
        fee_amount: Optional[Decimal] = None,
        attached_message: Optional[str] = None,
        entry_type: Optional[str] = "transfer"   # §MONEY-R18: was None -> kind='unknown'
    ) -> TEGTransaction:
        """
        Execute atomic token transfer with validation and event emission.
        
        This enhanced version:
        1. Executes the original transfer logic
        2. Emits a TokensTransferred event to the Event Store
        """
        # Execute the original transfer
        transaction = OriginalTransferService.execute_transfer(
            db=db,
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount=amount,
            fee_amount=fee_amount,
            attached_message=attached_message,
            entry_type=entry_type   # §2026-06-18 Part C — propagate to the base so the journal entry_type stamps
        )
        
        # Emit event if transfer was successful
        if transaction.status == TransactionStatus.COMPLETED:
            if _PROM_AVAILABLE:
                TEG_TRANSFERS_TOTAL.labels(kind="transfer", result="success").inc()
                try:
                    TEG_TRANSFER_AMOUNT.observe(float(amount))
                    if fee_amount and fee_amount > 0:
                        TEG_FEES_COLLECTED_AVT_TOTAL.inc(float(fee_amount))
                except (TypeError, ValueError):
                    pass
            try:
                # Run event emission in a fire-and-forget manner
                asyncio.create_task(_emit_transfer_event(
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    amount=str(amount),
                    transaction_id=transaction.transaction_id,
                    memo=attached_message
                ))
                logger.info(f"Scheduled TokensTransferred event emission for transaction {transaction.transaction_id}")
            except Exception as e:
                # Don't fail the transfer if event emission fails
                logger.error(f"Failed to schedule event emission: {e}")
        elif _PROM_AVAILABLE:
            TEG_TRANSFERS_TOTAL.labels(kind="transfer", result="failed").inc()

        return transaction
    
    @staticmethod
    def execute_issuance(
        db: Session,
        receiver_id: str,
        amount: Decimal
    ) -> TEGTransaction:
        """Execute token issuance (minting) with event emission"""
        # Execute the original issuance
        transaction = OriginalTransferService.execute_issuance(
            db=db,
            receiver_id=receiver_id,
            amount=amount
        )
        
        # Emit event if issuance was successful
        if transaction.status == TransactionStatus.COMPLETED:
            if _PROM_AVAILABLE:
                TEG_TRANSFERS_TOTAL.labels(kind="issuance", result="success").inc()
                try:
                    TEG_ISSUED_AVT_TOTAL.inc(float(amount))
                except (TypeError, ValueError):
                    pass
            try:
                # Run event emission in a fire-and-forget manner
                asyncio.create_task(_emit_issuance_event(
                    agent_did=receiver_id,
                    amount=str(amount),
                    transaction_id=transaction.transaction_id,
                    issued_by="admin",
                    reason="admin_issuance"
                ))
                logger.info(f"Scheduled TokensIssued event emission for transaction {transaction.transaction_id}")
            except Exception as e:
                # Don't fail the issuance if event emission fails
                logger.error(f"Failed to schedule event emission: {e}")
        elif _PROM_AVAILABLE:
            TEG_TRANSFERS_TOTAL.labels(kind="issuance", result="failed").inc()

        return transaction


async def _emit_transfer_event(
    sender_id: str,
    receiver_id: str,
    amount: str,
    transaction_id: str,
    memo: Optional[str] = None
):
    """Helper function to emit transfer event asynchronously"""
    try:
        success = await event_emitter.emit_tokens_transferred(
            from_agent=sender_id,
            to_agent=receiver_id,
            amount=amount,
            transaction_id=transaction_id,
            memo=memo
        )
        if success:
            logger.info(f"Successfully emitted TokensTransferred event for transaction {transaction_id}")
        else:
            logger.error(f"Failed to emit TokensTransferred event for transaction {transaction_id}")
    except Exception as e:
        logger.error(f"Error emitting transfer event: {e}")


async def _emit_issuance_event(
    agent_did: str,
    amount: str,
    transaction_id: str,
    issued_by: str,
    reason: str
):
    """Helper function to emit issuance event asynchronously"""
    try:
        success = await event_emitter.emit_tokens_issued(
            agent_did=agent_did,
            amount=amount,
            transaction_id=transaction_id,
            issued_by=issued_by,
            reason=reason
        )
        if success:
            logger.info(f"Successfully emitted TokensIssued event for transaction {transaction_id}")
        else:
            logger.error(f"Failed to emit TokensIssued event for transaction {transaction_id}")
    except Exception as e:
        logger.error(f"Error emitting issuance event: {e}")


# Monkey patch the original TransferService with our enhanced version
def patch_transfer_service():
    """Replace the original TransferService with the enhanced version"""
    import sys
    from . import database
    
    # Replace in the crud module
    database.crud.TransferService = EnhancedTransferService
    
    # Also update any already imported references
    for name, module in sys.modules.items():
        if hasattr(module, 'TransferService'):
            if getattr(module, 'TransferService') == OriginalTransferService:
                setattr(module, 'TransferService', EnhancedTransferService)
    
    logger.info("TransferService patched with Event Store integration")
