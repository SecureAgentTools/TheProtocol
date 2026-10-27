"""
Enhanced Disputes router with Beta Strike Package compliance.

This module adds the /log endpoint for dispute creation as specified
in the Beta Strike Package, while maintaining backward compatibility.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Security
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

# OWL20-PREP: Event Store integration
event_emitter = get_event_emitter()

from ..crud import crud_disputes
from ..models import Agent, Dispute
from .utils import get_current_agent
from ..schemas_enhanced import DisputeCreate as EnhancedDisputeCreate, DisputeRead
from ..core.path_segment import seg  # §MCPTEST30 V0526: a value in a store/TEG URL path is one encoded segment (round 9: a malformed id read as an outage)
# from .disputes import router as existing_disputes_router  # Include later when fixing full integration

# Create a new router that extends the existing one
router = APIRouter()

# Include all existing dispute endpoints
# router.include_router(existing_disputes_router)  # Uncomment when fixing full integration


@router.post("/log", 
             response_model=DisputeRead, 
             status_code=status.HTTP_201_CREATED,
             summary="File a formal dispute",
             description="File a dispute against another agent (Beta Strike Package endpoint)")
async def log_dispute(
    dispute_data: EnhancedDisputeCreate,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent)
) -> DisputeRead:
    """
    File a formal dispute against another agent.
    
    This is the Beta Strike Package compliant endpoint for dispute creation.
    It provides enhanced functionality including:
    - AVTP transaction reference
    - Standardized reason codes
    - Evidence pointer (IPFS hash)
    - Automatic event emission
    
    Args:
        dispute_data: Enhanced dispute creation data
        db: Database session
        current_agent: The authenticated agent filing the dispute
        
    Returns:
        DisputeRead: The created dispute with all details
        
    Raises:
        HTTPException 400: Invalid dispute data
        HTTPException 403: Cannot dispute yourself
        HTTPException 404: Referenced transaction not found
    """
    # Validate that complainant and defendant are different
    if dispute_data.defendant_agent_id == current_agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot file a dispute against yourself"
        )

    # §DIDWIDEN-1's guard, as POST /disputes/ applies it (routers/disputes.defendant_known): the defendant must be an
    # agent this registry knows, a native row or a mirrored card. This door filed a dispute against any well-formed DID
    # (found 2026-10-24 earning logEnhancedDispute's success path for the MCP tester).
    from .disputes import defendant_known
    if not await defendant_known(db, dispute_data.defendant_agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"Defendant {dispute_data.defendant_agent_id} is not known to this registry: no agent row and no "
                    f"mirrored card"),
        )
    
    # ROD4 (2026-07-24): validate the referenced transaction against the ledger.
    # The docstring has promised 404-on-missing since day one; this makes it true.
    if dispute_data.avtp_transaction_id:
        from .teg_transactions import _es_get
        _tx_events = await _es_get(
            f"/api/v1/events/by-transaction/{seg(dispute_data.avtp_transaction_id)}"
        )
        if isinstance(_tx_events, dict):
            _tx_events = _tx_events.get("items", _tx_events.get("events", []))
        if _tx_events is None:
            # Event Store unreachable — fail open: a metadata reference must not
            # block dispute filing, but say so in the log.
            logger.warning(
                f"[Disputes] Could not validate avtp_transaction_id "
                f"{dispute_data.avtp_transaction_id} (Event Store unreachable) — "
                f"accepting dispute unvalidated"
            )
        elif not _tx_events:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Referenced transaction not found in the ledger: "
                       f"{dispute_data.avtp_transaction_id}",
            )
        else:
            _blob = str(_tx_events)
            if current_agent.did not in _blob or dispute_data.defendant_agent_id not in _blob:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced transaction does not involve both dispute parties",
                )
    
    # TODO: Validate reason code against allowed codes
    allowed_reason_codes = [
        "UNFAIR_FEE",
        "SERVICE_NOT_DELIVERED", 
        "POOR_QUALITY",
        "MISREPRESENTATION",
        "CONTRACT_VIOLATION",
        "UNAUTHORIZED_USE",
        "OTHER"
    ]
    
    if dispute_data.reason_code not in allowed_reason_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid reason code. Allowed codes: {', '.join(allowed_reason_codes)}"
        )
    
    try:
        # Create the dispute with enhanced data
        dispute = await crud_disputes.create_dispute(
            db=db,
            complainant_did=current_agent.did,
            defendant_did=dispute_data.defendant_agent_id
        )
        
        # Store additional metadata as evidence
        metadata = {
            "reason_code": dispute_data.reason_code,
            "brief_description": dispute_data.brief_description,
            "avtp_transaction_id": dispute_data.avtp_transaction_id,
            "evidence_pointer": dispute_data.evidence_pointer,
            "filed_via": "beta_strike_endpoint"
        }
        
        # Add initial evidence with the dispute details
        await crud_disputes.add_evidence_to_dispute(
            db=db,
            dispute_id=dispute.id,
            submitter_did=current_agent.did,
            evidence_data=metadata
        )
        
        # OWL20-PREP: Emit DisputeFiled to Event Store (replaces TODO)
        import asyncio
        asyncio.create_task(event_emitter.emit(
            event_type="DisputeFiled",
            aggregate_id=current_agent.did,
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute.id,
                "complainant_did": current_agent.did,
                "defendant_did": dispute_data.defendant_agent_id,
                "reason_code": dispute_data.reason_code,
                "brief_description": dispute_data.brief_description[:200],
                "avtp_transaction_id": dispute_data.avtp_transaction_id,
                "status": dispute.status,
                "source": "beta_strike_endpoint"
            }
        ))
        
        # Refresh to get the evidence
        await db.refresh(dispute)
        
        # Convert to enhanced response format
        return DisputeRead(
            id=str(dispute.id),
            claimant_id=dispute.complainant_did,
            defendant_id=dispute.defendant_did,
            status=dispute.status,
            reason_code=dispute_data.reason_code,
            brief_description=dispute_data.brief_description,
            created_at=dispute.created_at,
            resolution=None
        )
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create dispute: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to file dispute"
        )
