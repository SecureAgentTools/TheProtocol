"""Admin-related API endpoints"""
from decimal import Decimal
from datetime import datetime, timezone
from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlalchemy import func, desc
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from ...api.auth import verify_admin_key
from ...core.supply_guard import refuse_nonzero_opening_balance  # §MONEY-R35
from ...database.db_session import get_db
from ...database.crud import AgentCRUD, TransferService, DisputeCRUD, SystemConfigCRUD, PolicyCRUD
from ...database.models import AgentTEGProfile, TEGTransaction
from .schemas import (
    AdminTokenIssuanceRequest,
    AdminTokenIssuanceResponse,
    DisputeStatusUpdateRequest,
    DisputeStatusUpdateResponse,
    SystemMetricsResponse,
    ErrorResponse,
    PolicyCreateRequest,
    PolicyUpdateRequest,
    PolicyResponse,
    PolicyListResponse,
    TreasuryBalanceResponse,
    RewardConfigResponse,
    RewardConfigUpdateRequest
)

class BulkInitializeRequest(BaseModel):
    """Request schema for bulk agent initialization."""
    agent_ids: List[str] = Field(..., min_length=1, max_length=500, description="List of agent DIDs to initialize")
    initial_balance: str = Field(default="0", description="Initial token balance")
    initial_reputation: int = Field(default=0, ge=0, le=1000, description="Initial reputation score")


router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/token/issue",
    response_model=AdminTokenIssuanceResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    }
)
async def issue_tokens(
    request: AdminTokenIssuanceRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Issue (mint) new tokens to a target agent.
    
    This endpoint requires admin authentication and creates new tokens,
    increasing the total supply in the system.
    
    Only authorized administrators should have access to this endpoint.
    """
    try:
        # Execute token issuance
        transaction = TransferService.execute_issuance(
            db=db,
            receiver_id=request.target_agent_id,
            amount=request.amount
        )
        
        # Get updated target balance
        new_target_balance = AgentCRUD.get_balance(db, request.target_agent_id)
        
        return AdminTokenIssuanceResponse(
            transaction_id=transaction.transaction_id,
            status=transaction.status.value,
            target_agent_id=request.target_agent_id,
            amount=request.amount,
            new_target_balance=new_target_balance,
            timestamp=transaction.timestamp
        )
        
    except Exception as e:
        # Log error in production
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Token issuance failed: {str(e)}"
        )


@router.post(
    "/token/burn",
    responses={
        501: {"model": ErrorResponse, "description": "Not Implemented"},
    }
)
async def burn_tokens(
    is_admin: Annotated[bool, Security(verify_admin_key)],
):
    """
    Burn (destroy) tokens from the system.
    
    This endpoint is not implemented in the MVP.
    """
    raise HTTPException(
        status_code=501,
        detail="Token burning is not implemented in MVP"
    )


@router.post(
    "/agents/bulk-initialize",
    responses={
        200: {"description": "Bulk initialization result"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    }
)
async def bulk_initialize_agents(
    request: BulkInitializeRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Bulk initialize TEG accounts for multiple agents.

    This endpoint requires admin authentication and initializes
    TEG accounts for multiple agents at once.
    """
    agent_ids = request.agent_ids
    # §MONEY-R35: accounts are created at zero; funding has its own rail.
    initial_balance = refuse_nonzero_opening_balance(
        request.initial_balance, rail="admin/agents/bulk-initialize"
    )
    initial_reputation = request.initial_reputation
    
    successful = 0
    failed = 0
    results = []
    
    for agent_id in agent_ids:
        try:
            # Create or get agent
            agent = AgentCRUD.get_or_create(db, agent_id)
            
            # Set initial values if new
            if agent.token_balance == 0:
                agent.token_balance = initial_balance
                agent.audited_balance = initial_balance
                agent.reputation_score = initial_reputation
                db.commit()
                successful += 1
            else:
                # Already initialized
                successful += 1
            
            results.append({
                "agent_id": agent_id,
                "status": "success",
                "balance": str(agent.token_balance)
            })
            
        except Exception as e:
            failed += 1
            results.append({
                "agent_id": agent_id,
                "status": "failed",
                "error": str(e)
            })
    
    return {
        "total_processed": len(agent_ids),
        "successful": successful,
        "failed": failed,
        "details": results
    }


@router.get(
    "/metrics",
    response_model=SystemMetricsResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Forbidden"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    }
)
async def get_system_metrics(
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Get system-wide metrics and statistics.
    
    Returns basic metrics about the TEG system including:
    - Total number of agents with balances
    - Total number of transactions
    - Total tokens in circulation
    - Total fees collected
    - Current fee configuration
    """
    try:
        from sqlalchemy import func
        from ...database.models import AgentTEGProfile, TEGTransaction
        
        # Get total agents with positive balance
        total_agents = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.token_balance > 0
        ).count()
        
        # Get total transactions
        total_transactions = db.query(TEGTransaction).count()
        
        # Get total tokens in circulation (sum of all balances)
        total_circulation = db.query(
            func.sum(AgentTEGProfile.token_balance)
        ).scalar() or Decimal("0")
        
        # Get fee collection address balance (total fees collected)
        fee_collector_address = SystemConfigCRUD.get_fee_collection_address(db)
        fee_collector = AgentCRUD.get_or_create(db, fee_collector_address)
        total_fees_collected = fee_collector.token_balance
        
        # Get current fee configuration
        system_fee_amount = SystemConfigCRUD.get_transfer_fee(db)
        
        return SystemMetricsResponse(
            total_agents_with_balance=total_agents,
            total_transactions=total_transactions,
            total_tokens_in_circulation=total_circulation,
            total_fees_collected=total_fees_collected,
            system_fee_amount=system_fee_amount,
            fee_collection_address=fee_collector_address
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve system metrics: {str(e)}"
        )


@router.post(
    "/reputation/recalculate/{agent_id}",
    responses={
        200: {"description": "Reputation recalculated successfully"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Agent not found"},
    }
)
async def recalculate_agent_reputation(
    agent_id: str,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Manually recalculate reputation score for a specific agent.
    
    This endpoint requires admin authentication and triggers the
    reputation calculation algorithm for the specified agent.
    """
    # Check if agent exists
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )
    
    try:
        # Import here to avoid circular dependency
        from ...core.reputation_logic import calculate_and_update_reputation
        
        # Recalculate reputation
        new_score = calculate_and_update_reputation(agent_id, db)
        
        return {
            "agent_id": agent_id,
            "new_reputation_score": new_score,
            "status": "recalculated"
        }
        
    except ImportError:
        # If reputation_logic doesn't exist, use a simple implementation
        # For MVP, just return the current score
        return {
            "agent_id": agent_id,
            "new_reputation_score": agent.reputation_score,
            "status": "recalculated"
        }
    except Exception as e:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to recalculate reputation: {str(e)}"
        )


@router.post(
    "/disputes/{dispute_log_id}/update_status",
    response_model=DisputeStatusUpdateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def update_dispute_status(
    dispute_log_id: str,
    request: DisputeStatusUpdateRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Update the status of a dispute (Admin only).
    
    Valid status values for MVP:
    - under_manual_review
    - resolved_no_action
    - resolved_claimant_favored
    - resolved_defendant_favored
    - resolved_penalty_applied_claimant
    - resolved_penalty_applied_defendant
    """
    # Valid status transitions for MVP
    valid_statuses = [
        "under_manual_review",
        "resolved_no_action",
        "resolved_claimant_favored",
        "resolved_defendant_favored",
        "resolved_penalty_applied_claimant",
        "resolved_penalty_applied_defendant"
    ]
    
    if request.new_status not in valid_statuses:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Valid values: {', '.join(valid_statuses)}"
        )
    
    # Get the dispute
    dispute = DisputeCRUD.get_dispute_by_id(db, dispute_log_id)
    
    if not dispute:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Dispute not found"
        )
    
    try:
        # Update dispute status
        dispute.status = request.new_status
        if request.resolution_notes:
            dispute.resolution_notes = request.resolution_notes
        
        db.commit()
        db.refresh(dispute)
        
        return DisputeStatusUpdateResponse(
            dispute_log_id=dispute.dispute_log_id,
            old_status="logged",  # For MVP, assume previous status was logged
            new_status=dispute.status,
            resolution_notes=dispute.resolution_notes,
            updated_at=dispute.updated_at
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to update dispute status: {str(e)}"
        )


# Policy Management Endpoints

@router.post(
    "/policies",
    response_model=PolicyResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        409: {"model": ErrorResponse, "description": "Conflict"},
    }
)
async def create_policy(
    request: PolicyCreateRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Create a new governance policy.
    
    This endpoint requires admin authentication and creates a new policy
    that can be linked to attestations or other system behaviors.
    """
    try:
        # Check for duplicate policy code
        existing = PolicyCRUD.get_policy_by_code(db, request.policy_code)
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Policy code already exists"
            )
        
        policy = PolicyCRUD.create_policy(
            db=db,
            policy_code=request.policy_code,
            policy_name=request.policy_name,
            policy_type=request.policy_type,
            description=request.description,
            parameters=request.parameters,
            circuit_identifier=request.circuit_identifier,
            enforcement_level=request.enforcement_level,
            reward_amount=request.reward_amount,
            policy_version=request.policy_version or "1.0.0",
            rules_document_url=request.rules_document_url,
            is_active=request.is_active
        )
        
        import json
        return PolicyResponse(
            policy_id=policy.policy_id,
            policy_code=policy.policy_code,
            policy_name=policy.policy_name,
            policy_type=policy.policy_type,
            policy_version=policy.policy_version,
            description=policy.description,
            parameters=json.loads(policy.parameters) if policy.parameters else None,
            circuit_identifier=policy.circuit_identifier,
            enforcement_level=policy.enforcement_level,
            reward_amount=policy.reward_amount,
            rules_document_url=policy.rules_document_url,
            is_active=policy.is_active,
            created_at=policy.created_at,
            updated_at=policy.updated_at
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to create policy: {str(e)}"
        )


@router.put(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def update_policy(
    policy_id: str,
    request: PolicyUpdateRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Update an existing policy.
    
    This endpoint requires admin authentication and allows updating
    policy description, rules URL, and active status.
    """
    policy = PolicyCRUD.update_policy(
        db=db,
        policy_id=policy_id,
        policy_name=request.policy_name,
        description=request.description,
        parameters=request.parameters,
        enforcement_level=request.enforcement_level,
        reward_amount=request.reward_amount,
        rules_document_url=request.rules_document_url,
        is_active=request.is_active
    )
    
    if not policy:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Policy not found"
        )
    
    import json
    return PolicyResponse(
        policy_id=policy.policy_id,
        policy_code=policy.policy_code,
        policy_name=policy.policy_name,
        policy_type=policy.policy_type,
        policy_version=policy.policy_version,
        description=policy.description,
        parameters=json.loads(policy.parameters) if policy.parameters else None,
        circuit_identifier=policy.circuit_identifier,
        enforcement_level=policy.enforcement_level,
        reward_amount=policy.reward_amount,
        rules_document_url=policy.rules_document_url,
        is_active=policy.is_active,
        created_at=policy.created_at,
        updated_at=policy.updated_at
    )


@router.get(
    "/policies",
    responses={
        403: {"model": ErrorResponse, "description": "Forbidden"},
    }
)
async def list_policies(
    is_admin: Annotated[bool, Security(verify_admin_key)],
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    List all policies.
    
    This endpoint requires admin authentication and returns all policies,
    optionally filtering by active status.
    """
    policies = PolicyCRUD.get_all_policies(db, active_only=active_only)
    
    import json
    policy_responses = [
        PolicyResponse(
            policy_id=p.policy_id,
            policy_code=p.policy_code,
            policy_name=p.policy_name,
            policy_type=p.policy_type,
            policy_version=p.policy_version,
            description=p.description,
            parameters=json.loads(p.parameters) if p.parameters else None,
            circuit_identifier=p.circuit_identifier,
            enforcement_level=p.enforcement_level,
            reward_amount=p.reward_amount,
            rules_document_url=p.rules_document_url,
            is_active=p.is_active,
            created_at=p.created_at,
            updated_at=p.updated_at
        )
        for p in policies
    ]
    
    # Return as a list, not wrapped in PolicyListResponse
    return policy_responses


@router.get(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def get_policy(
    policy_id: str,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Get a specific policy by ID.
    
    This endpoint requires admin authentication.
    """
    policy = PolicyCRUD.get_policy_by_id(db, policy_id)
    
    if not policy:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Policy not found"
        )
    
    import json
    return PolicyResponse(
        policy_id=policy.policy_id,
        policy_code=policy.policy_code,
        policy_name=policy.policy_name,
        policy_type=policy.policy_type,
        policy_version=policy.policy_version,
        description=policy.description,
        parameters=json.loads(policy.parameters) if policy.parameters else None,
        circuit_identifier=policy.circuit_identifier,
        enforcement_level=policy.enforcement_level,
        reward_amount=policy.reward_amount,
        rules_document_url=policy.rules_document_url,
        is_active=policy.is_active,
        created_at=policy.created_at,
        updated_at=policy.updated_at
    )


@router.delete(
    "/policies/{policy_id}",
    responses={
        200: {"description": "Policy deleted successfully"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def delete_policy(
    policy_id: str,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Delete a policy (soft delete by deactivating).
    
    This endpoint requires admin authentication and deactivates the policy
    rather than physically deleting it from the database.
    """
    policy = PolicyCRUD.get_policy_by_id(db, policy_id)
    
    if not policy:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Policy not found"
        )
    
    # Soft delete by deactivating
    PolicyCRUD.update_policy(db, policy_id, is_active=False)
    
    return {"message": "Policy deactivated successfully"}


# Treasury and Rewards Management

@router.get(
    "/treasury/balance",
    response_model=TreasuryBalanceResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Forbidden"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    }
)
async def get_treasury_balance(
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Get the current treasury balance.
    
    This endpoint requires admin authentication and returns the
    current balance of the TEG system treasury.
    
    Treasury balance = Total Supply (10M) - Distributed tokens
    """
    try:
        from sqlalchemy import func
        
        # Sum all agent balances to get distributed amount
        total_distributed = db.query(
            func.sum(AgentTEGProfile.token_balance)
        ).scalar() or Decimal("0")
        
        # Treasury holds the inverse (10M - distributed)
        total_supply = Decimal("10000000")  # 10 million total supply
        treasury_balance = total_supply - total_distributed
        
        # Get treasury DID for reference
        treasury_did = SystemConfigCRUD.get_treasury_did(db)
        
        return TreasuryBalanceResponse(
            treasury_did=treasury_did,
            balance=treasury_balance,
            last_updated=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve treasury balance: {str(e)}"
        )


@router.get(
    "/rewards/config",
    response_model=RewardConfigResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Forbidden"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    }
)
async def get_reward_config(
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Get current reward configuration.
    
    This endpoint requires admin authentication and returns the
    current reward amounts and associated policies.
    """
    try:
        attestation_reward = SystemConfigCRUD.get_attestation_reward_amount(db)
        attestation_policy_id = SystemConfigCRUD.get_attestation_policy_id(db)
        proof_policy_id = SystemConfigCRUD.get_proof_of_positive_balance_policy_id(db)
        
        return RewardConfigResponse(
            attestation_submission_reward=attestation_reward,
            associated_policy_id=attestation_policy_id,
            proof_of_positive_balance_policy_id=proof_policy_id
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve payout configuration: {str(e)}"
        )


@router.put(
    "/rewards/config",
    response_model=RewardConfigResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    }
)
async def update_reward_config(
    request: RewardConfigUpdateRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Update reward configuration.
    
    This endpoint requires admin authentication and allows updating
    reward amounts and associated policy IDs.
    
    WARNING: Changes to reward amounts affect the system's token economics.
    """
    try:
        # Update configurations if provided
        if request.attestation_submission_reward is not None:
            SystemConfigCRUD.set_value(
                db, 
                "attestation_submission_reward", 
                str(request.attestation_submission_reward)
            )
        
        if request.associated_policy_id is not None:
            # Verify policy exists
            if request.associated_policy_id:
                policy = PolicyCRUD.get_policy_by_id(db, request.associated_policy_id)
                if not policy:
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"Policy ID {request.associated_policy_id} not found"
                    )
            SystemConfigCRUD.set_value(
                db,
                "attestation_reward_policy_id",
                request.associated_policy_id or ""
            )
        
        if request.proof_of_positive_balance_policy_id is not None:
            # Verify policy exists
            if request.proof_of_positive_balance_policy_id:
                policy = PolicyCRUD.get_policy_by_id(db, request.proof_of_positive_balance_policy_id)
                if not policy:
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"Policy ID {request.proof_of_positive_balance_policy_id} not found"
                    )
            SystemConfigCRUD.set_value(
                db,
                "proof_of_positive_balance_policy_id",
                request.proof_of_positive_balance_policy_id or ""
            )
        
        # Return updated configuration
        attestation_reward = SystemConfigCRUD.get_attestation_reward_amount(db)
        attestation_policy_id = SystemConfigCRUD.get_attestation_policy_id(db)
        proof_policy_id = SystemConfigCRUD.get_proof_of_positive_balance_policy_id(db)
        
        return RewardConfigResponse(
            attestation_submission_reward=attestation_reward,
            associated_policy_id=attestation_policy_id,
            proof_of_positive_balance_policy_id=proof_policy_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update payout configuration: {str(e)}"
        )


@router.get(
    "/dashboard/summary",
    responses={
        200: {"description": "Dashboard summary"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    }
)
async def get_dashboard_summary(
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Get admin dashboard summary statistics.
    
    Returns key metrics for TEG system monitoring including:
    - Total active agents
    - Total transactions
    - Open disputes count
    - Recent activity metrics
    """
    try:
        from datetime import timedelta
        from ...database.models import TEGDispute, TEGAttestation, AuditorFlagLog
        
        # Total active agents
        total_active_agents = db.query(AgentTEGProfile).count()
        
        # Total transactions
        total_transactions = db.query(TEGTransaction).count()
        
        # Open disputes
        open_disputes_count = db.query(TEGDispute).filter(
            TEGDispute.status == "logged"
        ).count()
        
        # Recent auditor flags (last 24h)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_flags = db.query(AuditorFlagLog).filter(
            AuditorFlagLog.timestamp >= cutoff_time
        ).count()
        
        # Recent attestations (last 24h)
        recent_attestations = db.query(TEGAttestation).filter(
            TEGAttestation.submitted_at >= cutoff_time
        ).count()
        
        # Total tokens in circulation
        total_tokens = db.query(
            func.sum(AgentTEGProfile.token_balance)
        ).scalar() or Decimal("0")
        
        return {
            "total_active_agents": total_active_agents,
            "total_transactions": total_transactions,
            "total_tokens_in_circulation": str(total_tokens),
            "open_disputes_count": open_disputes_count,
            "recent_auditor_flags_24h": recent_flags,
            "recent_attestations_24h": recent_attestations,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve dashboard summary: {str(e)}"
        )


# Attestation Management Endpoints
@router.get(
    "/attestations/pending",
    responses={
        200: {"description": "List of pending attestations"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    }
)
async def get_pending_attestations(
    is_admin: Annotated[bool, Security(verify_admin_key)],
    limit: int = 100,
    offset: int = 0,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get attestations pending review (Admin only).
    
    This endpoint allows administrators to review submitted attestations,
    particularly those with ZKP verification status or requiring manual review.
    """
    try:
        from ...database.models import TEGAttestationLog
        
        # Build base query
        query = db.query(TEGAttestationLog)
        
        # Apply status filter if provided
        if status_filter:
            query = query.filter(TEGAttestationLog.status == status_filter)
        else:
            # Default to showing all non-verified attestations
            query = query.filter(
                TEGAttestationLog.status.in_(["logged", "zkp_verified_false"])
            )
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        attestations = query.order_by(
            desc(TEGAttestationLog.submitted_at)
        ).limit(limit).offset(offset).all()
        
        # Format response
        result = []
        for att in attestations:
            # Get policy info if available
            policy_info = None
            if att.policy_id and att.policy:
                policy_info = {
                    "policy_id": att.policy.policy_id,
                    "policy_name": att.policy.policy_name,
                    "policy_type": att.policy.policy_type,
                    "reward_amount": str(att.policy.reward_amount)
                }
            
            # Get agent info
            agent = db.query(AgentTEGProfile).filter(
                AgentTEGProfile.agent_id == att.agent_did
            ).first()
            
            agent_info = {
                "agent_did": att.agent_did,
                "reputation_score": agent.reputation_score if agent else 0,
                "token_balance": str(agent.token_balance) if agent else "0"
            }
            
            result.append({
                "submission_id": att.submission_id,
                "agent_info": agent_info,
                "attestation_type": att.attestation_type,
                "attestation_hash": att.attestation_hash,
                "storage_pointer": att.storage_pointer,
                "submitted_at": att.submitted_at.isoformat(),
                "status": att.status,
                "reward_issued": bool(att.reward_issued_tx_id),
                "reward_tx_id": att.reward_issued_tx_id,
                "zkp_details": {
                    "circuit_id": att.circuit_id,
                    "has_zkp": bool(att.circuit_id),
                    "zkp_verified": att.status == "zkp_verified_true" if att.circuit_id else None
                } if att.circuit_id else None,
                "policy_info": policy_info
            })
        
        return {
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "attestations": result
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve pending attestations: {str(e)}"
        )


@router.post(
    "/attestations/{submission_id}/verify",
    responses={
        200: {"description": "Attestation verified"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def verify_attestation(
    submission_id: str,
    verification_data: dict,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """Manually verify an attestation (Admin only).
    
    This allows administrators to manually verify attestations that:
    - Failed automated ZKP verification
    - Require manual review
    - Need status updates
    """
    try:
        from ...database.models import TEGAttestationLog
        
        # Get the attestation
        attestation = db.query(TEGAttestationLog).filter(
            TEGAttestationLog.submission_id == submission_id
        ).first()
        
        if not attestation:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Attestation {submission_id} not found"
            )
        
        # Update status based on verification
        new_status = verification_data.get("status", "basic_validated")
        valid_statuses = ["logged", "basic_validated", "zkp_verified_true", "zkp_verified_false", "rejected"]
        
        if new_status not in valid_statuses:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )
        
        # Update attestation status
        old_status = attestation.status
        attestation.status = new_status
        
        # If manually verifying as true and no reward has been issued, issue reward
        if new_status in ["basic_validated", "zkp_verified_true"] and not attestation.reward_issued_tx_id:
            if attestation.policy_id:
                # Get policy to determine reward amount
                policy = PolicyCRUD.get_policy_by_id(db, attestation.policy_id)
                if policy and policy.reward_amount > 0:
                    try:
                        # Issue reward
                        treasury_did = SystemConfigCRUD.get_treasury_did(db)
                        reward_tx = TransferService.execute_transfer(
                            db=db,
                            sender_id=treasury_did,
                            receiver_id=attestation.agent_did,
                            amount=policy.reward_amount,
                            fee_amount=Decimal("0")
                        )
                        reward_tx.transaction_type = "reward"
                        attestation.reward_issued_tx_id = reward_tx.transaction_id
                        db.commit()
                    except Exception as e:
                        # Log but don't fail the verification
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"Failed to issue manual verification reward: {e}")
        
        db.commit()
        db.refresh(attestation)
        
        return {
            "submission_id": submission_id,
            "old_status": old_status,
            "new_status": new_status,
            "reward_issued": bool(attestation.reward_issued_tx_id),
            "verified_by": "admin",
            "verified_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify attestation: {str(e)}"
        )


# MVP implementation for agent reactivation
@router.post(
    "/agents/{agent_id}/reactivate",
    responses={
        200: {"description": "Agent reactivated"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def reactivate_agent(
    agent_id: str,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Reactivate agent account - MVP implementation.
    
    For MVP, this just verifies the agent exists and returns success.
    """
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # In a full implementation, we'd update the agent's status
    # For MVP, just return success
    return {
        "agent_id": agent_id,
        "status": "reactivated",
        "reactivated_at": datetime.now(timezone.utc).isoformat()
    }
