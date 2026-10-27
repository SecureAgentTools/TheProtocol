"""AVTP-related API endpoints"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_409_CONFLICT

# §pass54 PR-3-expansion: APIKeyHeader spec marker for X-AVTP-System-Key.
# Runtime validation unchanged (still checks settings.avtp_system_api_key);
# this only annotates the OpenAPI surface.
_avtp_system_key_header = APIKeyHeader(
    name="X-AVTP-System-Key",
    scheme_name="AVTPSystemKey",
    description="AVTP system API key — required on all /avtp/* mutators.",
    auto_error=False,
)

from ...core.config import get_settings
from ...database.db_session import get_db
from ...database.crud import AVTPLogCRUD, AgentCRUD
from .schemas import (
    AVTPTransactionSummaryCreate,
    AVTPTransactionSummaryResponse,
    ErrorResponse
)

router = APIRouter()
settings = get_settings()


def verify_avtp_system_key(x_avtp_system_key: Optional[str] = Security(_avtp_system_key_header)) -> bool:
    """
    Verify AVTP system API key.
    
    Returns:
        bool: True if authenticated
    
    Raises:
        HTTPException: If authentication fails
    """
    if x_avtp_system_key is None:
        raise HTTPException(
            status_code=422,
            detail="X-AVTP-System-Key header is required"
        )
    # Constant-time, and closed when no key is configured (an empty header used to match an empty
    # setting). 2026-09-25.
    import hmac as _hmac
    _expected = str(settings.avtp_system_api_key or "")
    if not _expected or not _hmac.compare_digest(str(x_avtp_system_key), _expected):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid AVTP system key"
        )
    return True


@router.post(
    "/log_transaction_summary",
    response_model=AVTPTransactionSummaryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        409: {"model": ErrorResponse, "description": "Duplicate transaction"},
    }
)
async def log_avtp_transaction_summary(
    request: AVTPTransactionSummaryCreate,
    is_authorized: Annotated[bool, Security(verify_avtp_system_key)],
    db: Session = Depends(get_db)
):
    """
    Log an AVTP transaction summary.
    
    Requires X-AVTP-System-Key header for authentication.
    Both initiating and responding agents must exist in the system.
    """
    # Verify both agents exist (strict mode - no auto-creation)
    from ...database.models import AgentTEGProfile
    
    initiating_agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == request.initiating_agent_did
    ).first()
    
    if not initiating_agent:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Initiating agent {request.initiating_agent_did} not found"
        )
    
    responding_agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == request.responding_agent_did
    ).first()
    
    if not responding_agent:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Responding agent {request.responding_agent_did} not found"
        )
    
    try:
        # Create AVTP log entry
        # Default agent_did to responding_agent_did if not provided
        agent_did = request.agent_did or request.responding_agent_did
        
        log = AVTPLogCRUD.create_log(
            db=db,
            avtp_transaction_id=request.avtp_transaction_id,
            timestamp=request.timestamp,
            agent_did=agent_did,
            initiating_agent_did=request.initiating_agent_did,
            responding_agent_did=request.responding_agent_did,
            service_identifier=request.service_identifier,
            price_avt=request.price_avt,
            transaction_value=request.transaction_value,
            currency_type=request.currency_type,
            outcome_status=request.outcome_status,
            sla_identifier_referenced=request.sla_identifier_referenced,
            raw_log_pointer=request.raw_log_pointer
        )
        
        return AVTPTransactionSummaryResponse(
            log_id=log.log_id,
            status="logged"
        )
        
    except ValueError as e:
        if "already exists" in str(e):
            raise HTTPException(
                status_code=HTTP_409_CONFLICT,
                detail="AVTP transaction already logged"
            )
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Failed to log AVTP transaction"
        )
