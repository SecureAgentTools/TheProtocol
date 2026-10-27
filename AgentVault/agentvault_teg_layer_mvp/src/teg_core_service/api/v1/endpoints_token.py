"""Token-related API endpoints"""
from decimal import Decimal
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Header, Security
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from ...api.auth import get_current_agent, verify_admin_key
from ...core.config import get_settings
from ...core.error_handling import TEGException, ErrorCode, insufficient_balance_error, transaction_not_found_error, validation_error
from ...database.db_session import get_db
from ...database.crud import AgentCRUD, TransferService, TransactionCRUD, ReputationService, SystemConfigCRUD, ReputationSignalAlreadyApplied
from ...database.models import TransactionStatus
from .schemas import (
    TokenBalanceResponse,
    FeeConfigResponse,
    TokenTransferRequest,
    TokenTransferResponse,
    TokenSystemTransferRequest,
    TokenSystemTransferResponse,
    TransactionInfo,
    TransactionHistoryResponse,
    ReputationSignalRequest,
    ReputationSignalResponse,
    ErrorResponse,
    TestFaucetRequest,
    TestFaucetResponse,
    BulkTransferRequest,
    BulkTransferResult,
    BulkTransferResponse,
)

router = APIRouter()
settings = get_settings()


def _testing_faucet_enabled() -> bool:
    """§MONEY-M3a (R33): the test faucet is OFF unless TEG_TESTING_FAUCET_ENABLED is true."""
    import os
    return os.environ.get("TEG_TESTING_FAUCET_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


@router.get(
    "/balance",
    response_model=TokenBalanceResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def get_balance(
    agent_id: Annotated[str, Security(get_current_agent)],
    db: Session = Depends(get_db)
):
    """
    Get token balance for authenticated agent.
    
    Requires agent authentication via Bearer token.
    """
    balance = AgentCRUD.get_balance(db, agent_id)
    
    return TokenBalanceResponse(
        agent_id=agent_id,
        balance=balance
    )


@router.post(
    "/transfer",
    response_model=TokenTransferResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Receiver not found"},
    }
)
async def transfer_tokens(
    request: TokenTransferRequest,
    sender_id: Annotated[str, Security(get_current_agent)],
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    """
    Transfer tokens from authenticated agent to another agent.
    
    Validates:
    - Sender has sufficient balance
    - Amount is positive
    - Receiver exists (will be created if not)
    - Sender is not suspended
    
    The transfer is atomic - either completes fully or rolls back.
    """
    # Check for idempotency key
    if idempotency_key:
        # Check if this key has been used before
        import json
        from datetime import timedelta
        idempotency_key_name = f"idempotency_{sender_id}_{idempotency_key}"
        existing_result = SystemConfigCRUD.get_value(db, idempotency_key_name)
        
        if existing_result:
            # Check if key is expired (24 hours)
            try:
                result_data = json.loads(existing_result)
                created_at = datetime.fromisoformat(result_data["created_at"])
                if datetime.now(timezone.utc) - created_at < timedelta(hours=24):
                    # Return cached response
                    return TokenTransferResponse(**result_data["response"])
            except Exception:
                pass  # If parsing fails, continue with new transfer
    
    # Check if sender is suspended
    is_suspended, suspension_data = AgentCRUD.is_agent_suspended(db, sender_id)
    if is_suspended:
        suspension_reason = suspension_data.get("reason", "Unknown reason") if suspension_data else "Unknown reason"
        raise TEGException(
            status_code=403,
            error_code=ErrorCode.AUTH_AGENT_SUSPENDED,
            message=f"Your account is suspended and cannot perform transfers",
            detail=f"Reason: {suspension_reason}"
        )
    
    # Validate amount meets minimum
    if request.amount < Decimal(str(settings.min_transfer_amount)):
        raise validation_error(
            "amount", 
            str(request.amount), 
            f"Must be at least {settings.min_transfer_amount}"
        )
    
    # Validate amount doesn't exceed maximum (if set)
    if settings.max_transfer_amount and request.amount > Decimal(str(settings.max_transfer_amount)):
        raise validation_error(
            "amount", 
            str(request.amount), 
            f"Must not exceed {settings.max_transfer_amount}"
        )
    
    # Prevent self-transfer
    if sender_id == request.receiver_agent_id:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.BIZ_SELF_TRANSFER,
            message="Cannot transfer tokens to yourself"
        )

    # Durable idempotency claim (teg_idempotency_records) — upgrades the legacy
    # SystemConfig check-then-act above (kept as a read-only fallback for records
    # written pre-upgrade). Sender-scoped so one agent can never replay another's
    # cached result; claimed BEFORE any money moves; concurrent same-key → 409.
    from .endpoints_treasury import _idem_claim, _idem_complete, _idem_fail
    _idem_scoped = None
    if idempotency_key:
        _idem_scoped = f"xfer:{sender_id}:{idempotency_key}"
        if len(_idem_scoped) > 255:
            import hashlib as _hl
            _idem_scoped = "xfer:" + _hl.sha256(_idem_scoped.encode()).hexdigest()
    _moved = False
    _cached = _idem_claim(db, _idem_scoped, "token_transfer",
                          {"sender": sender_id, "receiver": request.receiver_agent_id,
                           "amount": str(request.amount)})
    if _cached is not None:
        return TokenTransferResponse(**_cached)

    # --- Phase 1 scaling: batch writer path ---
    from ...database.batch_writer import get_batch_writer
    batch_writer = get_batch_writer()
    if batch_writer is not None:
        try:
            result = await batch_writer.submit_transfer(
                sender_id=sender_id,
                receiver_id=request.receiver_agent_id,
                amount=request.amount,
                fee_amount=request.fee_amount if request.fee_amount is not None else Decimal("0"),
                message=request.message,
            )
            _moved = True
            # Build response from batch result.
            # The batch writer returns a plain dict; we need to read the updated
            # sender balance from the DB (the batch may have already committed).
            new_sender_balance = AgentCRUD.get_balance(db, sender_id)
            response = TokenTransferResponse(
                transaction_id=result["transaction_id"],
                status=result["status"],
                sender_agent_id=sender_id,
                receiver_agent_id=request.receiver_agent_id,
                amount=request.amount,
                fee_amount=Decimal(result["fee_amount"]),
                new_sender_balance=new_sender_balance,
                timestamp=datetime.now(timezone.utc),
                attached_message=result.get("attached_message"),
            )
            _idem_complete(db, _idem_scoped, response.model_dump(mode="json"))
            return response
        except ValueError as e:
            if not _moved:
                _idem_fail(db, _idem_scoped, {"error": str(e)})
            if "Insufficient balance" in str(e):
                current_balance = AgentCRUD.get_balance(db, sender_id)
                raise insufficient_balance_error(
                    current_balance=current_balance,
                    required_amount=request.amount,
                    fee_amount=request.fee_amount,
                )
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.BIZ_TRANSFER_FAILED,
                message=str(e)
            )

    try:
        # Execute transfer with transaction safety
        # fee_amount: use registry-provided value if present, otherwise TEG reads system_config
        transaction = TransferService.execute_transfer(
            db=db,
            sender_id=sender_id,
            receiver_id=request.receiver_agent_id,
            amount=request.amount,
            fee_amount=request.fee_amount,   # Bug 2 fix: registry fee passed here; TEG handles atomically
            attached_message=request.message
        )
        _moved = True

        # Get updated sender balance
        new_sender_balance = AgentCRUD.get_balance(db, sender_id)
        
        response = TokenTransferResponse(
            transaction_id=transaction.transaction_id,
            status=transaction.status.value,
            sender_agent_id=sender_id,
            receiver_agent_id=request.receiver_agent_id,
            amount=request.amount,
            fee_amount=transaction.fee_amount,
            new_sender_balance=new_sender_balance,
            timestamp=transaction.timestamp,
            attached_message=transaction.attached_message
        )
        
        _idem_complete(db, _idem_scoped, response.model_dump(mode="json"))
        return response

    except ValueError as e:
        if not _moved:
            _idem_fail(db, _idem_scoped, {"error": str(e)})
        if "Insufficient balance" in str(e):
            # Get current balance for better error message
            current_balance = AgentCRUD.get_balance(db, sender_id)
            raise insufficient_balance_error(
                str(current_balance),
                str(request.amount),
                str(TransferService.get_transfer_fee(db)) if hasattr(TransferService, 'get_transfer_fee') else None
            )
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=str(e)
        )
    except TEGException:
        raise
    except Exception as e:
        if not _moved:
            _idem_fail(db, _idem_scoped, {"error": str(e)})
        # Log error in production
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Transfer failed",
            detail="Please try again later" if not settings.debug else str(e)
        )


@router.post(
    "/transfer/to-system",
    response_model=TokenSystemTransferResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def transfer_to_system(
    request: TokenSystemTransferRequest,
    sender_id: Annotated[str, Security(get_current_agent)],
    db: Session = Depends(get_db)
):
    """
    Transfer tokens from authenticated agent to system treasury.
    
    This endpoint enables agents to pay system fees or make other
    system-level transfers. The destination is the TEG system treasury.
    
    Validates:
    - Sender has sufficient balance
    - Amount is positive and meets minimum requirements
    - System account type is valid
    
    The transfer is atomic - either completes fully or rolls back.
    """
    # Validate system account type
    if request.system_account_type != "treasury":
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Invalid system_account_type. Only 'treasury' is supported"
        )
    
    # Validate amount meets minimum
    if request.amount < Decimal(str(settings.min_transfer_amount)):
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=f"Amount must be at least {settings.min_transfer_amount}"
        )
    
    # Validate amount doesn't exceed maximum (if set)
    if settings.max_transfer_amount and request.amount > Decimal(str(settings.max_transfer_amount)):
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=f"Amount exceeds maximum transfer limit of {settings.max_transfer_amount}"
        )
    
    try:
        # Execute transfer to system treasury
        transaction = TransferService.execute_transfer(
            db=db,
            sender_id=sender_id,
            receiver_id=settings.teg_system_treasury_did,
            amount=request.amount,
            fee_amount=Decimal("0")  # No additional fees for system transfers
        )
        
        # Get updated sender balance
        new_sender_balance = AgentCRUD.get_balance(db, sender_id)
        
        return TokenSystemTransferResponse(
            transaction_id=transaction.transaction_id,
            status=transaction.status.value,
            sender_agent_id=sender_id,
            system_receiver_id=settings.teg_system_treasury_did,
            system_account_type=request.system_account_type,
            amount=request.amount,
            purpose=request.purpose or "system_fee",
            new_sender_balance=new_sender_balance,
            timestamp=transaction.timestamp
        )
        
    except ValueError as e:
        if "Insufficient balance" in str(e):
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                message="Insufficient balance for system transfer"
            )
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=str(e)
        )
    except Exception as e:
        # Log error in production
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="System transfer failed. Please try again."
        )


@router.get(
    "/transactions",
    response_model=TransactionHistoryResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def get_transaction_history(
    agent_id: Annotated[str, Security(get_current_agent)],
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    transaction_type: Optional[str] = Query(None, description="Filter by transaction type"),
    start_date: Optional[datetime] = Query(None, description="Filter by start date"),
    end_date: Optional[datetime] = Query(None, description="Filter by end date"),
    db: Session = Depends(get_db)
):
    """
    Get transaction history for authenticated agent.
    
    Returns paginated list of transactions where the agent was
    either sender or receiver, ordered by timestamp (newest first).
    
    Parameters:
    - limit: Maximum number of transactions to return (default: 100)
    - offset: Number of transactions to skip for pagination (default: 0)
    """
    # Get transactions with filtering
    transactions = TransactionCRUD.get_agent_transactions(
        db=db,
        agent_id=agent_id,
        limit=limit,
        offset=offset,
        transaction_type=transaction_type,
        start_date=start_date,
        end_date=end_date
    )
    
    # Get total count with same filters
    total = TransactionCRUD.count_agent_transactions(
        db=db,
        agent_id=agent_id,
        transaction_type=transaction_type,
        start_date=start_date,
        end_date=end_date
    )
    
    # Convert to response models
    transaction_infos = [
        TransactionInfo(
            transaction_id=tx.transaction_id,
            sender_agent_id=tx.sender_agent_id,
            receiver_agent_id=tx.receiver_agent_id,
            amount=tx.amount,
            fee_amount=tx.fee_amount,
            status=tx.status.value,
            transaction_type=tx.transaction_type,
            timestamp=tx.timestamp,
            error_message=tx.error_message,
            attached_message=tx.attached_message
        )
        for tx in transactions
    ]
    
    return TransactionHistoryResponse(
        transactions=transaction_infos,
        total=total,
        limit=limit,
        offset=offset
    )


@router.post(
    "/{transaction_id}/reputation-signal",
    response_model=ReputationSignalResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Transaction not found"},
    }
)
async def apply_reputation_signal(
    transaction_id: str,
    request: ReputationSignalRequest,
    agent_id: Annotated[str, Security(get_current_agent)],
    db: Session = Depends(get_db)
):
    """
    Apply a reputation signal to a completed transaction.
    
    Allows the sender of a successful A2A token transfer to signal
    about the receiver's performance. Each transaction can only
    receive one reputation signal.
    
    Rules:
    - Only sender can signal for their own transactions
    - Only completed transfer transactions are eligible
    - Signal can only be applied once per transaction
    - Signal value must be +1 or -1
    """
    # Get the transaction
    transaction = TransactionCRUD.get_by_id(db, transaction_id)
    
    if not transaction:
        raise TEGException(
            status_code=HTTP_404_NOT_FOUND,
            error_code=ErrorCode.BIZ_TRANSACTION_NOT_FOUND,
            message="Transaction not found"
        )
    
    # Validate sender is the one making the signal
    if transaction.sender_agent_id != agent_id:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Only the sender can apply reputation signal"
        )
    
    # Validate transaction is eligible
    if transaction.transaction_type != "transfer":
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Only transfer transactions can receive reputation signals"
        )
    
    if transaction.status != TransactionStatus.COMPLETED:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Only completed transactions can receive reputation signals"
        )
    
    if transaction.reputation_signal_applied:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Reputation signal already applied to this transaction"
        )
    
    # §TRUSTCHAIN (2026-09-12): the claim and the increment are ONE database transaction in
    # ReputationService.apply_signal — no score is read into Python and written back. The
    # `reputation_signal_applied` check above is the fast path; the claim inside is the truth.
    receiver_agent_id = transaction.receiver_agent_id
    try:
        actual_new_score = ReputationService.apply_signal(
            db, transaction_id, receiver_agent_id, request.signal_value
        )
    except ReputationSignalAlreadyApplied:
        db.rollback()
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Reputation signal already applied to this transaction"
        )
    except Exception as e:
        db.rollback()
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=f"Failed to apply reputation signal: {str(e)}"
        )

    import logging
    logging.getLogger(__name__).info(
        f"Reputation signal {request.signal_value:+d} applied for {receiver_agent_id}: now {actual_new_score}"
    )

    return ReputationSignalResponse(
        transaction_id=transaction_id,
        sender_agent_id=agent_id,
        receiver_agent_id=receiver_agent_id,
        signal_value=request.signal_value,
        new_receiver_reputation=actual_new_score,  # RETURNING: this caller's own increment
        status="applied"
    )


@router.get(
    "/fees/config",
    response_model=FeeConfigResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    }
)
async def get_fee_configuration(
    db: Session = Depends(get_db)
):
    """
    Get current fee configuration.
    
    Returns the current transfer fee amount and the address where fees are collected.
    This endpoint is public as agents need to know the fee before initiating transfers.
    """
    try:
        transfer_fee = SystemConfigCRUD.get_transfer_fee(db)
        fee_collection_address = SystemConfigCRUD.get_fee_collection_address(db)
        
        # Convert to expected response format
        fee_active = transfer_fee > 0
        # For a fixed fee model, the percentage would be based on the transfer amount
        # But since we don't have a specific amount, we'll return 0 for percentage-based display
        fee_percentage = 0.0  # Fixed fee model, not percentage-based
        
        return FeeConfigResponse(
            fee_active=fee_active,
            fee_percentage=fee_percentage,
            min_fee_amount=transfer_fee,  # Fixed fee model
            max_fee_amount=transfer_fee,  # Fixed fee model
            fee_recipient=fee_collection_address,
            transfer_fee_amount=transfer_fee,
            fee_collection_address=fee_collection_address
        )
        
    except Exception as e:
        raise TEGException(
            status_code=500,
            message=f"Failed to retrieve fee configuration: {str(e)}"
        )


@router.get(
    "/fees/calculate",
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
    }
)
async def calculate_fee(
    amount: Decimal = Query(..., description="Amount to calculate fee for"),
    db: Session = Depends(get_db)
):
    """
    Calculate the fee for a given transfer amount.
    
    Returns the calculated fee amount and total amount including fee.
    This endpoint helps agents understand the cost before initiating a transfer.
    """
    try:
        # Validate amount
        if amount <= 0:
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                message="Amount must be positive"
            )
        
        # Get current fee configuration
        transfer_fee = SystemConfigCRUD.get_transfer_fee(db)
        fee_active = transfer_fee > 0
        fee_amount = transfer_fee if fee_active else Decimal("0")
        total_amount = amount + fee_amount
        
        # Calculate fee percentage for display
        fee_percentage = (fee_amount / amount * 100) if amount > 0 and fee_active else Decimal("0")
        
        return {
            "amount": str(amount),
            "fee_amount": str(fee_amount),
            "total_amount": str(total_amount),
            "fee_active": fee_active,
            "fee_percentage": float(fee_percentage),
            "min_fee_amount": str(fee_amount),  # Fixed fee model
            "max_fee_amount": str(fee_amount)   # Fixed fee model
        }
        
    except TEGException:
        raise
    except Exception as e:
        raise TEGException(
            status_code=500,
            message=f"Failed to calculate fee: {str(e)}"
        )


@router.post(
    "/testing/faucet",
    response_model=TestFaucetResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden - Only available in non-production"},
        404: {"model": ErrorResponse, "description": "Agent not found"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    }
)
async def test_faucet(
    request: TestFaucetRequest,
    db: Session = Depends(get_db)
):
    """
    Test faucet for funding test accounts.
    
    This endpoint allows test accounts to receive an initial funding of 1000 AVT tokens
    from the system treasury. This is only available in non-production environments.
    
    Rules:
    - Only available in development/test environments
    - Each agent can only receive funding once per session
    - Fixed amount of 1000 AVT per request
    - All requests are logged as high-visibility "TESTING" events
    """
    # §MONEY-M3a (R33, 2026-09-03): FAIL-CLOSED. The old gate (`environment != "production"`)
    # was LIVE on 15 of 16 production TEGs — ENVIRONMENT is unset there and defaults to
    # "development" — and this route has no auth dependency and get_or_create()s its target,
    # so it was an unauthenticated 1000-unit treasury drain to any DID for any caller that
    # could reach the TEG port. A positive flag, off by default; the sandbox tier (the API
    # tester is the only faucet consumer) sets TEG_TESTING_FAUCET_ENABLED=true in its compose.
    if settings.environment == "production" or not _testing_faucet_enabled():
        raise TEGException(
            status_code=403,
            error_code=ErrorCode.AUTH_FORBIDDEN,
            message="Test faucet is disabled on this TEG (TEG_TESTING_FAUCET_ENABLED is not true)"
        )
    
    # Log the faucet request for monitoring
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"TESTING: Faucet request from agent {request.agent_did}")
    
    try:
        # Verify the agent exists in TEG database
        agent = AgentCRUD.get_or_create(db, request.agent_did)
        if not agent:
            raise TEGException(
                status_code=404,
                error_code=ErrorCode.BIZ_AGENT_NOT_FOUND,
                message=f"Agent {request.agent_did} not found in TEG system"
            )
        
        # Fixed funding amount
        funding_amount = Decimal("1000")
        
        # Check if agent already has sufficient balance (rate limiting)
        current_balance = AgentCRUD.get_balance(db, request.agent_did)
        if current_balance >= funding_amount:
            raise TEGException(
                status_code=400,
                error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                message=f"Agent already has sufficient balance ({current_balance} AVT)"
            )
        
        # Execute the funding transfer from system treasury
        transaction = TransferService.execute_transfer(
            db=db,
            sender_id=settings.teg_system_treasury_did,
            receiver_id=request.agent_did,
            amount=funding_amount,
            fee_amount=Decimal("0"),  # No fees for faucet transfers
            attached_message="TEST FAUCET: Initial funding for testing"
        )
        
        # Get the new balance
        new_balance = AgentCRUD.get_balance(db, request.agent_did)
        
        # Log successful funding
        logger.warning(
            f"TESTING: Faucet funded {request.agent_did} with {funding_amount} AVT. "
            f"Transaction: {transaction.transaction_id}"
        )
        
        return TestFaucetResponse(
            transaction_id=transaction.transaction_id,
            agent_did=request.agent_did,
            amount=funding_amount,
            new_balance=new_balance,
            timestamp=transaction.timestamp,
            message=f"Successfully funded {request.agent_did} with {funding_amount} AVT from test faucet"
        )
        
    except TEGException:
        raise
    except Exception as e:
        logger.error(f"TESTING: Faucet error for {request.agent_did}: {str(e)}")
        raise TEGException(
            status_code=500,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Test faucet failed",
            detail=str(e) if settings.debug else "Please try again later"
        )


@router.post(
    "/transfer/bulk",
    response_model=BulkTransferResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden — admin API key required"},
    }
)
async def bulk_transfer_tokens(
    request: BulkTransferRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db),
):
    """
    Process multiple transfers in a single request.

    Server-to-server only — called by the Registry's TEG proxy layer
    using the TEG Admin API Key.

    LIGHTNING-3 (2026-05-02): replaced the per-item-savepoint loop with a
    single locked SELECT + sequential in-memory delta application + a
    multi-row INSERT + ONE db.commit(). Reduces per-item commit cost from
    ~25ms to ~1ms; one fsync per batch instead of N. Lock-order safety via
    sorted IN (...) (mirrors crud.execute_transfer Round-3 fix).

    Per-item failure isolation preserved: validation runs per item, only
    items that pass all checks are included in the multi-row INSERT and
    have their balance deltas applied. Failed items return per-item
    `status="failed"` results without affecting the rest of the batch.
    """
    import logging
    import os
    from uuid import uuid4
    from sqlalchemy import insert as sa_insert, text as sa_text
    from ...database.models import AgentTEGProfile, TEGTransaction, TransactionStatus as TxStatus

    _bulk_logger = logging.getLogger(__name__)

    _min_amount = Decimal(str(settings.min_transfer_amount))
    _max_amount = (
        Decimal(str(settings.max_transfer_amount))
        if settings.max_transfer_amount else None
    )
    _audited_enabled = os.getenv('AUDITED_BALANCE_ENABLED', 'true').lower() == 'true'

    # ── Phase 1 — pre-flight validation (no balance checks yet) ──
    # Each entry tracks status: 'pending' (passed pre-flight), 'pre_failed'
    # (rejected before locking), 'ok' (committed), 'post_failed' (rejected
    # at integrity/balance check after locking).
    entries: list[dict] = []
    for item in request.transfers:
        entry: dict = {"item": item, "status": "pending"}
        try:
            amount = Decimal(item.amount)
            fee_amount = Decimal(item.fee_amount) if item.fee_amount else Decimal("0")
            total_deduction = amount + fee_amount

            if item.sender_agent_id == item.receiver_agent_id:
                raise ValueError("Cannot transfer tokens to yourself")
            if amount < _min_amount:
                raise ValueError(f"Amount {amount} below minimum {_min_amount}")
            if _max_amount is not None and amount > _max_amount:
                raise ValueError(f"Amount {amount} exceeds maximum {_max_amount}")

            try:
                _is_susp, _susp_data = AgentCRUD.is_agent_suspended(
                    db, item.sender_agent_id
                )
            except Exception:
                _is_susp, _susp_data = False, None
            if _is_susp:
                _reason = (_susp_data or {}).get("reason", "unknown") if _susp_data else "unknown"
                raise ValueError(f"Sender suspended: {_reason}")

            entry["amount"] = amount
            entry["fee_amount"] = fee_amount
            entry["total_deduction"] = total_deduction
        except ValueError as _err:
            entry["status"] = "pre_failed"
            entry["error"] = str(_err)
        entries.append(entry)

    # ── Phase 2 — bulk-load + lock all involved profiles (sorted = deadlock-safe) ──
    pending = [e for e in entries if e["status"] == "pending"]
    profile_by_id: dict[str, AgentTEGProfile] = {}
    fee_collector_id: Optional[str] = None
    if pending:
        any_fee = any(e["fee_amount"] > Decimal("0") for e in pending)
        if any_fee:
            fee_collector_id = SystemConfigCRUD.get_fee_collection_address(db)

        agent_ids: set[str] = set()
        for e in pending:
            agent_ids.add(e["item"].sender_agent_id)
            agent_ids.add(e["item"].receiver_agent_id)
        if fee_collector_id:
            agent_ids.add(fee_collector_id)

        ids_sorted = sorted(agent_ids)
        locked = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id.in_(ids_sorted)
        ).order_by(AgentTEGProfile.agent_id).with_for_update().all()
        profile_by_id = {p.agent_id: p for p in locked}

    def _ensure_profile(agent_id: str) -> AgentTEGProfile:
        prof = profile_by_id.get(agent_id)
        if prof is None:
            # W2 guard (2026-05-05): refuse cross-frame profile creation.
            from ...database.home_frame_resolver import check_home_or_raise
            check_home_or_raise(agent_id)
            prof = AgentTEGProfile(
                agent_id=agent_id,
                token_balance=Decimal("0"),
                audited_balance=Decimal("0"),
                reputation_score=0,
            )
            db.add(prof)
            profile_by_id[agent_id] = prof
        return prof

    # ── Phase 3 — sequential apply: integrity + balance + delta ──
    #
    # §MONEY-R18 (2026-09-04): TAG THE BATCH. This handler mutates
    # `token_balance` DIRECTLY on the ORM (the plan's ⚠M3 class) instead of going
    # through TransferService.execute_transfer, so it never stamped
    # `teg.entry_type` and the L1 journal trigger fell back to its 'unknown'
    # default — `COALESCE(NULLIF(current_setting('teg.entry_type', true), ''),
    # 'unknown')`. Because the registry's TEGBulkProxy is enabled on every node
    # (TEG_BULK_PROXY=true, batch=200, flush=10ms), THIS is the busiest money
    # path on the platform, which is why kind='unknown' is 4,661,352 events and
    # the single largest class in the EventStore.
    #
    # MEASURED THE HARD WAY: defaulting execute_transfer's entry_type twice did
    # nothing at all to live traffic, because the traffic never goes through it.
    #
    # One set_config for the whole batch is correct and sufficient: this handler
    # accumulates every mutation and issues ONE db.commit() below, and
    # `is_local=true` scopes the GUC to that transaction, so it cannot leak onto
    # a pooled connection and it covers every AFTER-trigger fire within the batch.
    #
    # Δ-NEUTRAL: materialized_balances.sql routes 'mint'/'dispute_comp' to
    # tokens_issued and 'slash'/'burn' to tokens_destroyed; 'unknown' and
    # 'transfer' alike fall to transit_net. Only the label changes.
    db.execute(sa_text("SELECT set_config('teg.entry_type', 'transfer', true)"))

    batch_now = datetime.now(timezone.utc)
    tx_inserts: list[dict] = []

    for entry in entries:
        if entry["status"] != "pending":
            continue
        item = entry["item"]
        amount = entry["amount"]
        fee_amount = entry["fee_amount"]
        total_deduction = entry["total_deduction"]

        try:
            sender = _ensure_profile(item.sender_agent_id)
            receiver = _ensure_profile(item.receiver_agent_id)

            if _audited_enabled:
                for _cid, _cp in [(item.sender_agent_id, sender), (item.receiver_agent_id, receiver)]:
                    if _cp.audited_balance is not None and _cp.token_balance != _cp.audited_balance:
                        raise ValueError(
                            f"Balance integrity check failed for {_cid}: "
                            f"token_balance={_cp.token_balance} != audited_balance={_cp.audited_balance}. "
                            f"This indicates unauthorized balance modification. Contact administrator."
                        )

            if sender.token_balance < total_deduction:
                raise ValueError(
                    f"Insufficient balance: have {sender.token_balance}, "
                    f"need {total_deduction}"
                )

            tx_id = str(uuid4())
            sender.token_balance -= total_deduction
            receiver.token_balance += amount

            fee_collector = None
            if fee_amount > Decimal("0") and fee_collector_id is not None:
                fee_collector = _ensure_profile(fee_collector_id)
                fee_collector.token_balance += fee_amount

            sender.audited_balance = sender.token_balance
            receiver.audited_balance = receiver.token_balance
            if fee_collector is not None:
                fee_collector.audited_balance = fee_collector.token_balance

            tx_inserts.append({
                "transaction_id": tx_id,
                "sender_agent_id": item.sender_agent_id,
                "receiver_agent_id": item.receiver_agent_id,
                "amount": amount,
                "fee_amount": fee_amount,
                "transaction_type": "transfer",
                "status": TxStatus.COMPLETED,
                "attached_message": item.message,
                "timestamp": batch_now,
            })

            entry["status"] = "ok"
            entry["tx_id"] = tx_id
            entry["new_sender_balance"] = sender.token_balance
        except ValueError as _err:
            entry["status"] = "post_failed"
            entry["error"] = str(_err)

    # ── Phase 4 — multi-row INSERT (single statement, single round-trip) ──
    catastrophic_error: Optional[str] = None
    if tx_inserts:
        try:
            db.execute(sa_insert(TEGTransaction.__table__).values(tx_inserts))
        except Exception as _exc:
            db.rollback()
            catastrophic_error = str(_exc)
            _bulk_logger.error(
                "[BulkTransfer] multi-row INSERT failed: %s — rolling back batch",
                _exc,
            )

    # ── Phase 5 — single COMMIT (one fsync for INSERT + balance UPDATEs) ──
    if catastrophic_error is None:
        try:
            db.commit()
        except Exception as _exc:
            db.rollback()
            catastrophic_error = str(_exc)
            _bulk_logger.error(
                "[BulkTransfer] commit failed: %s — rolling back batch", _exc,
            )

    # ── Phase 6 — build per-item results in input order ──
    results: list[BulkTransferResult] = []
    succeeded = 0
    failed = 0
    for entry in entries:
        item = entry["item"]
        if catastrophic_error and entry["status"] == "ok":
            failed += 1
            results.append(BulkTransferResult(
                status="failed",
                error=f"Bulk commit failed: {catastrophic_error}",
                sender_agent_id=item.sender_agent_id,
                receiver_agent_id=item.receiver_agent_id,
                amount=item.amount,
            ))
        elif entry["status"] == "ok":
            succeeded += 1
            results.append(BulkTransferResult(
                transaction_id=entry["tx_id"],
                status="completed",
                sender_agent_id=item.sender_agent_id,
                receiver_agent_id=item.receiver_agent_id,
                amount=item.amount,
                fee_amount=str(entry["fee_amount"]),
                new_sender_balance=str(entry["new_sender_balance"]),
                timestamp=batch_now.isoformat(),
                attached_message=item.message,
            ))
        else:
            failed += 1
            results.append(BulkTransferResult(
                status="failed",
                error=entry.get("error", "unknown error"),
                sender_agent_id=item.sender_agent_id,
                receiver_agent_id=item.receiver_agent_id,
                amount=item.amount,
            ))

    _bulk_logger.info(
        "[BulkTransfer] LIGHTNING-3: %d transfers (%d ok, %d fail) — single commit",
        len(request.transfers), succeeded, failed,
    )

    return BulkTransferResponse(
        total=len(request.transfers),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )
