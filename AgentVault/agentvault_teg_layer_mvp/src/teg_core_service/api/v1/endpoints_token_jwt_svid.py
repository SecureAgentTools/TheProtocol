"""Enhanced token-related API endpoints with JWT-SVID authentication

Part of REQ-INT-V1AUTH-001 implementation: JWT-SVID validation for agent authentication.
"""
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

# Import JWT-SVID verification instead of simple token verification
from ...core.jwt_svid import verify_jwt_svid
from ...core.config import get_settings
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
    ErrorResponse
)

router = APIRouter(prefix="/token", tags=["token"])
settings = get_settings()


@router.get(
    "/balance",
    response_model=TokenBalanceResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid JWT-SVID"},
    }
)
async def get_balance(
    agent_id: Annotated[str, Security(verify_jwt_svid)],
    db: Session = Depends(get_db)
):
    """
    Get token balance for authenticated agent.
    
    Requires agent authentication via JWT-SVID Bearer token.
    The JWT-SVID must be issued by SPIRE with the TEG Core Service
    as the intended audience.
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
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid JWT-SVID"},
        404: {"model": ErrorResponse, "description": "Receiver not found"},
    }
)
async def transfer_tokens(
    request: TokenTransferRequest,
    sender_id: Annotated[str, Security(verify_jwt_svid)],
    db: Session = Depends(get_db)
):
    """
    Transfer tokens from authenticated agent to another agent.
    
    Requires JWT-SVID authentication representing the sending agent.
    The sender is identified from the JWT-SVID's subject claim.
    
    Validates:
    - Sender has sufficient balance
    - Amount is positive
    - Receiver exists (will be created if not)
    
    The transfer is atomic - either completes fully or rolls back.
    """
    # Validate amount meets minimum
    if request.amount < Decimal(str(settings.min_transfer_amount)):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Amount must be at least {settings.min_transfer_amount}"
        )
    
    # Validate amount doesn't exceed maximum (if set)
    if settings.max_transfer_amount and request.amount > Decimal(str(settings.max_transfer_amount)):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Amount exceeds maximum transfer limit of {settings.max_transfer_amount}"
        )
    
    # Prevent self-transfer
    if sender_id == request.receiver_agent_id:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Cannot transfer tokens to yourself"
        )
    
    try:
        # Execute transfer with transaction safety
        transaction = TransferService.execute_transfer(
            db=db,
            sender_id=sender_id,
            receiver_id=request.receiver_agent_id,
            amount=request.amount,
            attached_message=request.message
        )
        
        # Get updated sender balance
        new_sender_balance = AgentCRUD.get_balance(db, sender_id)
        
        return TokenTransferResponse(
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
        
    except ValueError as e:
        if "Insufficient balance" in str(e):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Insufficient balance for transfer"
            )
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Log error in production
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Transfer failed. Please try again."
        )


@router.post(
    "/system-transfer",
    response_model=TokenSystemTransferResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid JWT-SVID"},
    }
)
async def transfer_to_system(
    request: TokenSystemTransferRequest,
    sender_id: Annotated[str, Security(verify_jwt_svid)],
    db: Session = Depends(get_db)
):
    """
    Transfer tokens from authenticated agent to system treasury.
    
    Requires JWT-SVID authentication representing the sending agent.
    
    This endpoint enables agents to pay system fees or make other
    system-level transfers. The destination is the TEG system treasury.
    
    Validates:
    - Sender has sufficient balance
    - Amount is positive and meets minimum requirements
    
    The transfer is atomic - either completes fully or rolls back.
    """
    # Validate amount meets minimum
    if request.amount < Decimal(str(settings.min_transfer_amount)):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Amount must be at least {settings.min_transfer_amount}"
        )
    
    # Validate amount doesn't exceed maximum (if set)
    if settings.max_transfer_amount and request.amount > Decimal(str(settings.max_transfer_amount)):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Amount exceeds maximum transfer limit of {settings.max_transfer_amount}"
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
            amount=request.amount,
            purpose=request.purpose or "system_fee",
            new_sender_balance=new_sender_balance,
            timestamp=transaction.timestamp
        )
        
    except ValueError as e:
        if "Insufficient balance" in str(e):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Insufficient balance for system transfer"
            )
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Log error in production
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="System transfer failed. Please try again."
        )


@router.get(
    "/history",
    response_model=TransactionHistoryResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid JWT-SVID"},
    }
)
async def get_transaction_history(
    agent_id: Annotated[str, Security(verify_jwt_svid)],
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Get transaction history for authenticated agent.
    
    Requires JWT-SVID authentication. Returns transactions where
    the authenticated agent was either sender or receiver.
    
    Returns paginated list of transactions ordered by timestamp (newest first).
    
    Parameters:
    - limit: Maximum number of transactions to return (default: 100)
    - offset: Number of transactions to skip for pagination (default: 0)
    """
    # Get transactions
    transactions = TransactionCRUD.get_agent_transactions(
        db=db,
        agent_id=agent_id,
        limit=limit,
        offset=offset
    )
    
    # Get total count
    total = TransactionCRUD.count_agent_transactions(db, agent_id)
    
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
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid JWT-SVID"},
        404: {"model": ErrorResponse, "description": "Transaction not found"},
    }
)
async def apply_reputation_signal(
    transaction_id: str,
    request: ReputationSignalRequest,
    agent_id: Annotated[str, Security(verify_jwt_svid)],
    db: Session = Depends(get_db)
):
    """
    Apply a reputation signal to a completed transaction.
    
    Requires JWT-SVID authentication. Only the sender of a transaction
    can apply a reputation signal.
    
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
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    # Validate sender is the one making the signal
    if transaction.sender_agent_id != agent_id:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Only the sender can apply reputation signal"
        )
    
    # Validate transaction is eligible
    if transaction.transaction_type != "transfer":
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Only transfer transactions can receive reputation signals"
        )
    
    if transaction.status != TransactionStatus.COMPLETED:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Only completed transactions can receive reputation signals"
        )
    
    if transaction.reputation_signal_applied:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Reputation signal already applied to this transaction"
        )
    
    # §TRUSTCHAIN (2026-09-12): ONE implementation, ReputationService.apply_signal — the claim
    # and the increment in one database transaction, RETURNING as the answer (see endpoints_token).
    receiver_agent_id = transaction.receiver_agent_id
    try:
        new_score = ReputationService.apply_signal(
            db, transaction_id, receiver_agent_id, request.signal_value
        )
    except ReputationSignalAlreadyApplied:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Reputation signal already applied to this transaction"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to apply reputation signal: {str(e)}"
        )

    return ReputationSignalResponse(
        transaction_id=transaction_id,
        sender_agent_id=agent_id,
        receiver_agent_id=receiver_agent_id,
        signal_value=request.signal_value,
        new_receiver_reputation=new_score,
        status="applied"
    )


@router.get(
    "/fee-config",
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
    
    Note: This endpoint does not require JWT-SVID authentication as the
    fee configuration is public information.
    """
    try:
        transfer_fee = SystemConfigCRUD.get_transfer_fee(db)
        fee_collection_address = SystemConfigCRUD.get_fee_collection_address(db)
        
        return FeeConfigResponse(
            transfer_fee_amount=transfer_fee,
            fee_collection_address=fee_collection_address
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve fee configuration: {str(e)}"
        )
