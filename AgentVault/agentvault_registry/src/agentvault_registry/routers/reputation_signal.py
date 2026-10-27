"""
Reputation Signal endpoint for transaction feedback with Event Store integration.

This module implements the low-friction justice system that allows agents
to provide immediate feedback on transactions, affecting reputation scores.
"""
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Path, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta, timezone
import logging
import asyncio

from ..database import get_db
from ..models import Agent
from ..schemas_enhanced import ReputationSignalRequest
from .utils import get_current_agent
from ..teg_client import get_teg_client
from ..event_emitter import EventEmitter
from ..config import settings

logger = logging.getLogger(__name__)

# Initialize Event Emitter
event_emitter = EventEmitter(
    event_store_url=getattr(settings, 'EVENT_STORE_URL', "http://localhost:8200"),
    internal_api_key=getattr(settings, 'EVENT_STORE_API_KEY', ""),
    source_service="registry"
)

router = APIRouter()


async def _emit_reputation_changed_event(
    agent_did: str,
    old_score: int,
    new_score: int,
    reason: str
):
    """Helper function to emit reputation changed event asynchronously"""
    try:
        success = await event_emitter.emit_reputation_changed(
            agent_did=agent_did,
            old_score=old_score,
            new_score=new_score,
            reason=reason
        )
        if success:
            logger.info(f"Successfully emitted ReputationChanged event for {agent_did}")
        else:
            logger.error(f"Failed to emit ReputationChanged event for {agent_did}")
    except Exception as e:
        logger.error(f"Error emitting reputation changed event: {e}")


@router.post("/token/{transaction_id}/reputation-signal", 
             summary="Signal satisfaction with a transaction",
             description="Provide reputation feedback (+1 or -1) for a completed transaction")
async def submit_reputation_signal(
    transaction_id: Annotated[str, Path(description="TEG transaction ID")],
    signal_request: ReputationSignalRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> dict:
    """
    Submit a reputation signal for a completed transaction.
    
    This is the low-friction justice system that allows transaction participants
    to provide immediate feedback. Only the sender of a transaction can signal,
    and they can only signal once per transaction.
    
    Signals affect the recipient's reputation score:
    - +1 signal: Increases reputation
    - -1 signal: Decreases reputation
    
    Rules:
    - Only transaction sender can signal
    - One signal per transaction
    - Signal value must be +1 or -1
    - Can only signal completed transactions
    - Signals must be submitted within 30 days
    
    Args:
        transaction_id: The TEG Layer transaction ID
        signal_request: The signal value and optional reason
        db: Database session
        current_agent: The authenticated agent submitting the signal
        
    Returns:
        Confirmation of signal submission
        
    Raises:
        HTTPException 400: Invalid signal value
        HTTPException 403: Not authorized to signal this transaction
        HTTPException 404: Transaction not found
        HTTPException 409: Already signaled this transaction
    """
    # Validate signal value
    if signal_request.signal_value not in [-1, 1]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signal value must be +1 or -1"
        )
    
    try:
        # Get TEG client
        teg_client = get_teg_client()
        
        # Submit the reputation signal to TEG Layer
        result = await teg_client.submit_reputation_signal(
            transaction_id=transaction_id,
            signal_value=signal_request.signal_value,
            agent_did=current_agent.did,
            reason=signal_request.reason
        )
        
        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            
            # Map TEG errors to appropriate HTTP status codes
            if "not found" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transaction not found"
                )
            elif "not authorized" in error_msg.lower() or "not sender" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the transaction sender can submit signals"
                )
            elif "already signaled" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You have already signaled this transaction"
                )
            elif "expired" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Signal period has expired (30 days)"
                )
            elif "not completed" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Can only signal completed transactions"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_msg
                )
        
        # Update local reputation cache if needed
        if result.get("affected_agent_did"):
            affected_did = result["affected_agent_did"]
            new_reputation = result.get("new_reputation_score")
            
            if new_reputation is not None:
                # Update cached reputation in Registry
                stmt = select(Agent).where(Agent.did == affected_did)
                affected_result = await db.execute(stmt)
                affected_agent = affected_result.scalar_one_or_none()
                
                if affected_agent:
                    old_reputation = affected_agent.reputation_score
                    affected_agent.reputation_score = new_reputation
                    await db.commit()
                    logger.info(
                        f"Updated reputation for {affected_did}: "
                        f"{old_reputation} -> {new_reputation} after signal from {current_agent.did}"
                    )
                    
                    # Emit ReputationChanged event
                    try:
                        reason_text = f"reputation_signal:{signal_request.signal_value}"
                        if signal_request.reason:
                            reason_text += f":{signal_request.reason}"
                            
                        asyncio.create_task(_emit_reputation_changed_event(
                            agent_did=affected_did,
                            old_score=old_reputation,
                            new_score=new_reputation,
                            reason=reason_text
                        ))
                        logger.info(f"Scheduled ReputationChanged event emission for {affected_did}")
                    except Exception as e:
                        # Don't fail the reputation update if event emission fails
                        logger.error(f"Failed to schedule event emission: {e}")
        
        # Return success response
        return {
            "success": True,
            "transaction_id": transaction_id,
            "signal_value": signal_request.signal_value,
            "signal_timestamp": datetime.now(timezone.utc).isoformat(),
            "affected_agent": result.get("affected_agent_did"),
            "new_reputation_score": result.get("new_reputation_score"),
            "message": f"Reputation signal submitted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting reputation signal: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG Layer temporarily unavailable"
        )


@router.get("/token/{transaction_id}/reputation-signal",
            summary="Check if transaction has been signaled",
            description="Check if the current agent has already signaled a transaction")
async def check_reputation_signal(
    transaction_id: Annotated[str, Path(description="TEG transaction ID")],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> dict:
    """
    Check if the current agent has already submitted a reputation signal for a transaction.
    
    This endpoint helps prevent duplicate signal attempts by checking if a signal
    has already been submitted.
    
    Returns:
        Dictionary with signal status and details if signaled
    """
    try:
        teg_client = get_teg_client()
        
        # Check signal status
        result = await teg_client.check_reputation_signal(
            transaction_id=transaction_id,
            agent_did=current_agent.did
        )
        
        if result.get("error"):
            if "not found" in result["error"].lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transaction not found"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result["error"]
                )
        
        return {
            "transaction_id": transaction_id,
            "has_signaled": result.get("has_signaled", False),
            "signal_value": result.get("signal_value"),
            "signal_timestamp": result.get("signal_timestamp"),
            "can_signal": result.get("can_signal", False),
            "reason": result.get("reason", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking reputation signal: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG Layer temporarily unavailable"
        )
