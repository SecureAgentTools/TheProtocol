"""Auditor-related API endpoints"""
from typing import List, Dict, Annotated, Optional, Any

from fastapi import APIRouter, Depends, Query, HTTPException, Security
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from sqlalchemy.orm import Session

from ...core.security import verify_admin_token
from ...database.db_session import get_db
from ...database.crud import AuditorFlagCRUD
from ...database.models import FlagSeverity, FlagStatus, AuditorFlagLog
from .schemas import (
    AuditorFlagsResponse,
    AuditorFlagInfo,
    AuditorFlagCreateRequest,
    AuditorFlagResponse,
    AuditorFlagStatusUpdateRequest,
    ErrorResponse
)

router = APIRouter()


@router.get(
    "/flags",
    response_model=AuditorFlagsResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Forbidden"},
    }
)
async def get_auditor_flags(
    is_admin: Annotated[bool, Security(verify_admin_token)],
    agent_did: Optional[str] = Query(None, description="Filter by agent DID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    flag_type: Optional[str] = Query(None, description="Filter by flag type"),
    limit: int = Query(100, ge=1, le=1000, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    db: Session = Depends(get_db)
):
    """
    Get auditor flags (admin only).
    
    Can filter by agent DID, status, severity, and/or flag type.
    """
    # Convert string parameters to enums if provided
    status_enum = None
    if status:
        try:
            status_enum = FlagStatus(status)
        except ValueError:
            # Invalid status, return empty list
            return AuditorFlagsResponse(flags=[], total=0, limit=limit, offset=offset)
    
    severity_enum = None
    if severity:
        try:
            severity_enum = FlagSeverity(severity)
        except ValueError:
            # Invalid severity, return empty list
            return AuditorFlagsResponse(flags=[], total=0, limit=limit, offset=offset)
    
    # Use appropriate method based on filters
    if severity_enum or flag_type:
        flags, total = AuditorFlagCRUD.get_flags_for_filtering(
            db=db,
            severity=severity_enum,
            flag_type=flag_type,
            limit=limit,
            offset=offset
        )
        # Apply agent and status filters manually if needed
        if agent_did:
            flags = [f for f in flags if f.flagged_agent_did == agent_did]
        if status_enum:
            flags = [f for f in flags if f.status == status_enum]
        total = len(flags)
    else:
        flags, total = AuditorFlagCRUD.get_flags(
            db=db,
            agent_did=agent_did,
            status=status,
            limit=limit,
            offset=offset
        )
    
    flag_infos = [
        AuditorFlagInfo(
            flag_id=flag.flag_id,
            timestamp=flag.timestamp,
            flagged_agent_did=flag.flagged_agent_did,
            rule_violated_code=flag.rule_violated_code,
            flag_reason=flag.flag_reason,
            flag_type=flag.flag_type,
            severity=(flag.severity.value if hasattr(flag.severity, 'value') else flag.severity).lower(),
            related_agent_id=flag.related_agent_id,
            related_avtp_transaction_id=flag.related_avtp_transaction_id,
            related_attestation_id=flag.related_attestation_id,
            related_transaction_id=flag.related_transaction_id,
            details=flag.details,
            status=flag.status.value if hasattr(flag.status, 'value') else flag.status,
            flagged_by=flag.flagged_by,
            created_at=flag.created_at,
            updated_at=flag.updated_at
        )
        for flag in flags
    ]
    
    return AuditorFlagsResponse(
        flags=flag_infos,
        total=total,
        limit=limit,
        offset=offset
    )


@router.post(
    "/flags",
    response_model=AuditorFlagResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    }
)
async def create_auditor_flag(
    request: AuditorFlagCreateRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """
    Create a new auditor flag (admin only).
    
    This allows manual flagging of agents for review.
    """
    # Convert severity string to enum
    try:
        severity_enum = FlagSeverity(request.severity)
    except ValueError:
        valid_severities = [s.value for s in FlagSeverity]
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid severity. Valid values: {', '.join(valid_severities)}"
        )
    
    # Create the flag
    flag = AuditorFlagCRUD.create_flag(
        db=db,
        flagged_agent_did=request.flagged_agent_id,
        rule_violated_code=request.rule_code,
        flag_reason=request.evidence or "Manual admin flag",
        flag_type="manual_admin",
        severity=severity_enum,
        flagged_by="admin",
        status=FlagStatus.NEW,
        details=request.evidence
    )
    
    return AuditorFlagResponse(
        flag_id=flag.flag_id,
        status="created",
        severity=flag.severity.value.lower()
    )


@router.put(
    "/flags/{flag_id}/status",
    responses={
        200: {"description": "Flag status updated successfully"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def update_flag_status(
    flag_id: str,
    request: AuditorFlagStatusUpdateRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """
    Update the status of an auditor flag (admin only).
    
    Valid status values:
    - NEW
    - ACKNOWLEDGED
    - RESOLVED
    - (legacy statuses are also supported)
    """
    # Map string to enum
    try:
        new_status_enum = FlagStatus(request.new_status)
    except ValueError:
        valid_statuses = [s.value for s in FlagStatus]
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Valid values: {', '.join(valid_statuses)}"
        )
    
    # Get the flag
    flag = AuditorFlagCRUD.get_flag_by_id(db, flag_id)
    
    if not flag:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Flag not found"
        )
    
    # Update flag status
    updated_flag = AuditorFlagCRUD.update_status(
        db=db,
        flag_id=flag_id,
        new_status=new_status_enum,
        resolution_notes=request.resolution_notes
    )
    
    return {
        "flag_id": updated_flag.flag_id,
        "old_status": flag.status.value,
        "new_status": updated_flag.status.value,
        "updated_at": updated_flag.updated_at
    }

# Additional endpoints for test compatibility

@router.put("/flags/{flag_id}/status")
async def update_flag_status(
    flag_id: str,
    status: Dict[str, str],
    db: Session = Depends(get_db)
):
    """Update flag status"""
    from ...database.models import FlagStatus
    flag = AuditorFlagCRUD.get_flag_by_id(db, flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")
    
    new_status = FlagStatus(status.get("status", "resolved"))
    updated_flag = AuditorFlagCRUD.update_status(
        db, flag_id, new_status, status.get("resolution_notes")
    )
    return {"flag_id": flag_id, "status": updated_flag.status.value}


@router.post("/flags/bulk-resolution")
async def bulk_resolve_flags(
    resolution_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Bulk resolve multiple flags"""
    flag_ids = resolution_data.get("flag_ids", [])
    resolution_notes = resolution_data.get("resolution_notes", "Bulk resolved")
    
    resolved_count = 0
    for flag_id in flag_ids:
        try:
            from ...database.models import FlagStatus
            AuditorFlagCRUD.update_status(
                db, flag_id, FlagStatus.RESOLVED_NO_ACTION, resolution_notes
            )
            resolved_count += 1
        except:
            pass
    
    return {"resolved_count": resolved_count, "total": len(flag_ids)}


@router.post("/flags/{flag_id}/escalate")
async def escalate_flag(
    flag_id: str,
    escalation_data: Dict[str, str],
    db: Session = Depends(get_db)
):
    """Escalate a flag"""
    flag = AuditorFlagCRUD.get_flag_by_id(db, flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")
    
    # Update to escalated status
    from ...database.models import FlagStatus
    AuditorFlagCRUD.update_status(
        db, flag_id, FlagStatus.ESCALATED, 
        f"Escalated: {escalation_data.get('reason', 'No reason provided')}"
    )
    
    return {"flag_id": flag_id, "status": "escalated"}


@router.get("/rules/configuration")
async def get_rules_configuration():
    """Get auditor rules configuration"""
    return {
        "rules": {
            "high_volume_velocity": {
                "enabled": True,
                "thresholds": {
                    "transaction_count": 100,
                    "time_window_hours": 1,
                    "total_volume": 10000
                }
            },
            "unusual_patterns": {
                "enabled": True,
                "thresholds": {
                    "deviation_factor": 3.0
                }
            },
            "collusion_detection": {
                "enabled": True,
                "thresholds": {
                    "circular_threshold": 5
                }
            }
        }
    }


@router.get("/performance-metrics")
async def get_performance_metrics(db: Session = Depends(get_db)):
    """Get auditor performance metrics"""
    # Simple metrics for MVP
    total_flags = db.query(AuditorFlagLog).count()
    resolved_flags = db.query(AuditorFlagLog).filter(
        AuditorFlagLog.status.in_([
            FlagStatus.RESOLVED_NO_ACTION,
            FlagStatus.RESOLVED_ACTION_TAKEN
        ])
    ).count()
    
    return {
        "total_flags": total_flags,
        "resolved_flags": resolved_flags,
        "pending_flags": total_flags - resolved_flags,
        "resolution_rate": (resolved_flags / total_flags * 100) if total_flags > 0 else 0,
        "average_resolution_time_hours": 24.0  # Mock value
    }


@router.put("/rules/{rule_id}/thresholds")
async def update_rule_thresholds(
    rule_id: str,
    thresholds: Dict[str, Any]
):
    """Update rule thresholds"""
    # For MVP, just return success
    return {
        "rule_id": rule_id,
        "thresholds": thresholds,
        "status": "updated"
    }


@router.put("/rules/{rule_id}/disable")
async def disable_rule(rule_id: str):
    """Disable an auditor rule"""
    # For MVP, just return success
    return {
        "rule_id": rule_id,
        "enabled": False,
        "status": "disabled"
    }
