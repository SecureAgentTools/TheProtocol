from sqlalchemy import select, desc
"""Attestation-related API endpoints"""
import json
from decimal import Decimal
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, Response, Security
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_409_CONFLICT

from ...core.security import verify_agent_token
from ...core.config import get_settings
from ...core.zkp_verifier import get_zkp_verifier
from ...core.error_handling import TEGException, ErrorCode
from ...database.db_session import get_db
from ...database.crud import AttestationCRUD, AgentCRUD, TransferService, SystemConfigCRUD, PolicyCRUD
from ...database.models import TEGAttestationLog
from .schemas import (
    AttestationSubmissionRequest,
    AttestationSubmissionResponse,
    AttestationInfo,
    ErrorResponse
)

router = APIRouter()
settings = get_settings()


@router.post(
    "/submit",
    response_model=AttestationSubmissionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        409: {"model": ErrorResponse, "description": "Duplicate submission"},
    }
)
async def submit_attestation(
    request: AttestationSubmissionRequest,
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """
    Submit an attestation for logging.
    
    Validates uniqueness based on agent_did, attestation_type, and attestation_hash.
    """
    # Ensure agent exists
    AgentCRUD.get_or_create(db, agent_id)
    
    # Check if this is a ZKP attestation
    zkp_circuit_id = None
    zkp_public_inputs_json = None
    zkp_proof_value = None
    zkp_verified = False
    
    if request.zkp_payload:
        # This is a ZKP attestation
        zkp_circuit_id = request.zkp_payload.circuit_id
        zkp_public_inputs_json = json.dumps(request.zkp_payload.public_inputs)
        zkp_proof_value = request.zkp_payload.proof_value
        
        # Update attestation type to indicate ZKP version
        if request.attestation_type == "ProofOfFairMarkup":
            request.attestation_type = "ProofOfFairMarkup_ZKP_v1"
        elif request.attestation_type == "ProofOfAccurateResourceUsage":
            request.attestation_type = "ProofOfAccurateResourceUsage_ZKP_v1"
    
    # Determine governing policy based on attestation type
    policy_id = None
    policy = None
    
    # For ZKP attestations, first try to find a policy matching the circuit_id
    if request.zkp_payload and zkp_circuit_id:
        policy = PolicyCRUD.get_policy_by_circuit_identifier(db, zkp_circuit_id)
        if policy and policy.is_active:
            policy_id = policy.policy_id
    
    # If no circuit-specific policy found, check attestation type
    if not policy_id:
        # Check if this is a proof of positive balance attestation
        if "ProofOfPositiveBalance" in request.attestation_type:
            policy_id = SystemConfigCRUD.get_proof_of_positive_balance_policy_id(db)
        else:
            # General attestation reward policy
            policy_id = SystemConfigCRUD.get_attestation_policy_id(db)
    
    # Fetch policy if we have a policy_id but not the policy object
    if policy_id and not policy:
        policy = PolicyCRUD.get_policy_by_id(db, policy_id)
    
    # Check if policy is active - if not, fail early
    if policy_id and (not policy or not policy.is_active):
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Associated policy is not active or does not exist",
            metadata={"policy_id": policy_id}
        )
    
    try:
        # Create attestation submission with policy linkage
        submission = AttestationCRUD.create_submission(
            db=db,
            agent_did=request.agent_did,
            attestation_type=request.attestation_type,
            attestation_hash=request.attestation_hash,
            storage_pointer=request.storage_pointer,
            submitted_at=request.submitted_at,
            circuit_id=zkp_circuit_id,
            zkp_public_inputs_json=zkp_public_inputs_json,
            zkp_proof_value=zkp_proof_value,
            policy_id=policy_id
        )
        
        # Store submission ID for later use
        submission_id = submission.submission_id
        submission_status = submission.status
        
        # Verify ZKP if present
        if request.zkp_payload:
            verifier = get_zkp_verifier()
            zkp_verified = verifier.verify_proof(
                circuit_id=zkp_circuit_id,
                public_inputs=request.zkp_payload.public_inputs,
                proof_value=zkp_proof_value
            )
            
            # Update submission status based on verification
            if zkp_verified:
                submission.status = "zkp_verified_true"
            else:
                submission.status = "zkp_verified_false"
            submission_status = submission.status
            db.commit()
            db.refresh(submission)
        
        # §ATTESTREWARD (agentvault2-45, 2026-10-13; agentvault2-90's §ZKV2 finding): a reward is paid only for a proof
        # a REAL verifier accepted. This used to start True, so a submission without a proof was paid too; the
        # registry's POST /api/v1/teg/attestations/submit forwards none, so an agent holding reputation.signal (the
        # service-provider role, which an owner may give its agent) drew the default 10 from the treasury per call, its
        # arbitrary attestation_data making every call unique. And core/zkp_verifier.py only simulates (any 32+ char
        # proof starting "VALID_"). So nothing is paid until verification is real; the submission is still logged.
        verifier_is_real = bool(request.zkp_payload) and not getattr(get_zkp_verifier(), "SIMULATED", True)
        should_issue_reward = bool(request.zkp_payload) and zkp_verified and verifier_is_real
            
        if should_issue_reward:
            try:
                # Get treasury DID and reward amount from system config
                treasury_did = SystemConfigCRUD.get_treasury_did(db)
                
                # Get reward amount from the policy if linked, otherwise use system default
                if policy and policy.reward_amount is not None:
                    reward_amount = policy.reward_amount
                else:
                    reward_amount = SystemConfigCRUD.get_attestation_reward_amount(db)
                
                # Ensure treasury account exists with sufficient balance
                treasury = AgentCRUD.get_or_create(db, treasury_did)
                
                # Check if treasury has sufficient balance
                if treasury.token_balance < reward_amount:
                    # §MONEY-R31 (2026-09-04): this is a PRE-WARNING, not a decision.
                    # It used to be followed by two lines claiming the reward was
                    # issued regardless for MVP purposes. That stopped being true when
                    # §MONEY-R24 landed, and it is exactly the kind of stale comment
                    # that makes a reader conclude the TEG still over-issues.
                    #
                    # (Deliberately paraphrased, not quoted: the absence gate in
                    # tests/test_retired_rails_and_stubs.py searches for the old wording,
                    # and quoting it here would make the gate match this explanation
                    # instead of the code — the "matched documentation, not code" trap.)
                    #
                    # What actually happens: execute_transfer below raises
                    # ValueError("Insufficient balance"), the handler DEFERS, and no
                    # issuance row is written. The warning here is the early notice; the
                    # refusal is real and lives in the except clause.
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Treasury has insufficient balance for reward. Treasury balance: {treasury.token_balance}, Required: {reward_amount}")
                
                # Execute reward transfer using TransferService for proper atomicity
                try:
                    # Use TransferService to ensure atomic transaction
                    reward_tx = TransferService.execute_transfer(
                        db=db,
                        sender_id=treasury_did,
                        receiver_id=agent_id,
                        amount=reward_amount,
                        fee_amount=Decimal("0")  # No fees on rewards
                    )
                    # Override transaction type to reward (as expected by tests)
                    reward_tx.transaction_type = "reward"
                    db.commit()
                    
                    # Update attestation with reward transaction ID
                    # Reload submission to ensure it's attached to the session
                    submission = db.query(AttestationCRUD.model).filter_by(submission_id=submission_id).first()
                    if submission:
                        submission.reward_issued_tx_id = reward_tx.transaction_id
                        db.commit()
                except ValueError as ve:
                    # §MONEY-R24 / D9 (2026-09-04): DEFER, NEVER ISSUE.
                    #
                    # This used to read "For MVP/testing, issue tokens directly":
                    # on an insufficient-treasury ValueError it rolled back and did
                    # `agent.token_balance += reward_amount` — a direct ORM credit
                    # creating supply from nothing (the ⚠M3 untagged-mover class).
                    #
                    # ⚠ It did NOT breach Δ, and saying so would be wrong: the credit
                    # is single-sided and untagged, so the outbox emits it as an
                    # unknown/transfer kind and materialized_balances.sql adds it to
                    # transit_net while total_circulating rises by the same amount.
                    # The invariant stays 0.0. That is precisely the R18 blind spot
                    # being exercised: money appears, and the prime-directive check
                    # cannot see it.
                    #
                    # A treasury that cannot pay a reward is an operator decision.
                    # The reward is simply not paid: reward_issued_tx_id stays NULL,
                    # which IS the "deferred, no issuance row" state the plan asks for.
                    if "Insufficient balance" in str(ve):
                        db.rollback()
                        import logging as _lg
                        _lg.getLogger(__name__).warning(
                            "[ATTEST-REWARD] DEFERRED for agent=%s submission=%s: treasury "
                            "cannot cover %s. No issuance — top the treasury up and re-run.",
                            agent_id, submission_id, reward_amount,
                        )
                    else:
                        raise
            except Exception as e:
                # Don't fail attestation submission if reward fails
                # Just log the error (in production)
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to issue attestation reward: {str(e)}", exc_info=True)
                # Ensure we don't have a half-committed state
                db.rollback()
        
        # Run automated auditor checks for attestation patterns
        try:
            from ...core.automated_auditor import AutomatedAuditorRules
            AutomatedAuditorRules.run_attestation_checks(
                db, agent_id, submission_id
            )
        except Exception:
            # Don't fail attestation if auditor checks fail
            pass
        
        # Reload submission to get the latest state
        submission = db.query(AttestationCRUD.model).filter_by(submission_id=submission_id).first()
        if not submission:
            # If we can't reload, use what we have
            submission = AttestationCRUD.model(
                submission_id=submission_id,
                agent_did=request.agent_did,
                attestation_type=request.attestation_type,
                status=submission_status
            )
        
        return AttestationSubmissionResponse(
            submission_id=submission.submission_id,
            agent_did=submission.agent_did,
            attestation_type=submission.attestation_type,
            status=submission.status,
            policy_id=policy_id,
            policy_name=policy.policy_name if policy else None
        )
        
    except ValueError as e:
        if "Duplicate attestation" in str(e):
            raise TEGException(
                status_code=HTTP_409_CONFLICT,
                error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                message="Attestation already submitted",
                detail="This attestation has already been submitted by this agent"
            )
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=str(e)
        )
    except Exception as e:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Failed to submit attestation",
            detail=str(e) if settings.debug else None
        )


@router.get(
    "",
    response_model=List[AttestationInfo],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def get_attestations(
    agent_id: Annotated[str, Security(verify_agent_token)],
    response: Response,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of attestations to return"),
    offset: int = Query(0, ge=0, description="Number of attestations to skip"),
    attestation_type: Optional[str] = Query(None, description="Filter by attestation type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: Session = Depends(get_db)
):
    """
    Get attestations submitted by the authenticated agent.
    
    Returns a list of attestations with optional filtering by type and status.
    Results are ordered by submission date (newest first).
    """
    # Build query
    query = db.query(TEGAttestationLog).filter(
        TEGAttestationLog.agent_did == agent_id
    )
    
    # Apply filters
    if attestation_type:
        query = query.filter(TEGAttestationLog.attestation_type == attestation_type)
    if status:
        query = query.filter(TEGAttestationLog.status == status)
    
    # Get total count for pagination
    total_count = query.count()
    
    # Get attestations with pagination
    attestations = query.order_by(
        desc(TEGAttestationLog.submitted_at)
    ).limit(limit).offset(offset).all()
    
    # Format response
    result = []
    for att in attestations:
        # Get associated policy info if available
        policy_name = None
        reward_amount = None
        if att.policy_id and att.policy:
            policy_name = att.policy.policy_name
            reward_amount = att.policy.reward_amount
        
        result.append(AttestationInfo(
            submission_id=att.submission_id,
            agent_did=att.agent_did,
            attestation_type=att.attestation_type,
            attestation_hash=att.attestation_hash,
            storage_pointer=att.storage_pointer,
            submitted_at=att.submitted_at,
            status=att.status,
            reward_issued_tx_id=att.reward_issued_tx_id,
            circuit_id=att.circuit_id,
            zkp_public_inputs_json=att.zkp_public_inputs_json,
            zkp_proof_value=att.zkp_proof_value,
            policy_id=att.policy_id,
            policy_name=policy_name,
            reward_amount=str(reward_amount) if reward_amount else None
        ))
    
    # Add pagination headers
    response.headers["X-Total-Count"] = str(total_count)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    
    return result
