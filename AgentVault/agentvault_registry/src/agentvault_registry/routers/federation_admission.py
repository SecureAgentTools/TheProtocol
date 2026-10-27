"""
routers/federation_admission.py — Federation Policy Admission Pipeline

Endpoints:
  POST /api/v1/admin/federation/validate-policy          (dry-run, no DB side-effects)
  POST /api/v1/admin/federation/request-admission        (creates PeerRegistry + compliance record)
  POST /api/v1/admin/federation/complete-admission/{id}  (Commander approves pending)
  GET  /api/v1/admin/federation/admission-status/{id}    (status poll)
  POST /api/v1/admin/federation/policy-update-request    (bounded-param changes, auto-approved)

Auth: All endpoints require Admin JWT (is_admin=True).

Author: OWL-23 / Phase 1 Implementation
Date: 2026-03-12
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Security
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import FederatedRegistryCompliance, PeerRegistry
from .. import security
from ..services.federation_policy_validator import FederationPolicyValidator, ValidationResult

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/federation",
    tags=["Federation Admission"],
)

_validator = FederationPolicyValidator()


# ── Request/Response Schemas ──────────────────────────────────────────────────

class ValidatePolicyRequest(BaseModel):
    policy_json: Dict[str, Any] = Field(
        ..., description="Full policy JSON blob to validate against base network params"
    )


class AdmissionRequest(BaseModel):
    registry_name: str = Field(..., description="Human-readable registry name")
    registry_operator_did: str = Field(..., description="DID of the registry operator")
    registry_public_url: str = Field(..., description="Base URL of the peer registry")
    admin_contact_email: str = Field(..., description="Admin contact email for the peer")
    operator_identity_proof: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional identity proof material (reserved for Phase 3 ED25519)"
    )
    policy_json: Dict[str, Any] = Field(
        ..., description="Full policy JSON of the joining registry"
    )


class PolicyUpdateRequest(BaseModel):
    peer_did: str
    proposed_policy_json: Dict[str, Any]
    change_summary: str = ""
    effective_date: Optional[str] = None


class ViolationOut(BaseModel):
    path: str
    required: Any
    submitted: Any
    bounds: Optional[dict]
    violation_type: str
    severity: str


class ValidationResponse(BaseModel):
    valid: bool
    violations: List[ViolationOut]
    warnings: List[str]
    policy_hash: str


class AdmissionResponse(BaseModel):
    admission_id: str
    peer_registry_id: int
    status: str
    policy_hash: str
    violations: List[ViolationOut]
    warnings: List[str]
    message: str


class AdmissionStatusResponse(BaseModel):
    admission_id: str
    peer_registry_id: Optional[int]
    peer_name: Optional[str]
    federation_status: str
    policy_hash: str
    admitted_at: Optional[str]
    admitted_by: Optional[str]
    quarantine_reason: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _violations_out(result: ValidationResult) -> List[ViolationOut]:
    return [
        ViolationOut(
            path=v.path,
            required=v.required,
            submitted=v.submitted,
            bounds=v.bounds,
            violation_type=v.violation_type,
            severity=v.severity.value,
        )
        for v in result.violations
    ]


async def _get_compliance_by_admission_id(
    db: AsyncSession, admission_id: str
) -> FederatedRegistryCompliance:
    """Fetch compliance record by UUID (used as admission_id)."""
    try:
        uid = uuid.UUID(admission_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid admission_id format")

    result = await db.execute(
        select(FederatedRegistryCompliance).where(FederatedRegistryCompliance.id == uid)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Admission record not found")
    return record


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/validate-policy",
    response_model=ValidationResponse,
    summary="Dry-run policy validation (no DB side-effects)",
)
async def validate_policy(
    request: ValidatePolicyRequest,
    _admin=Security(security.require_admin_flag("admin_federation")),
):
    """
    Validate a submitted policy JSON against the Base Network Parameters.
    No DB writes. Operators can call this before requesting admission.
    """
    result = _validator.validate(request.policy_json)
    return ValidationResponse(
        valid=result.valid,
        violations=_violations_out(result),
        warnings=result.warnings,
        policy_hash=result.submitted_hash,
    )


@router.post(
    "/request-admission",
    response_model=AdmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a registry for federation admission",
)
async def request_admission(
    request: AdmissionRequest,
    db: AsyncSession = Depends(get_db),
    admin=Security(security.require_admin_flag("admin_federation")),
):
    """
    Validate the submitted policy and, if valid, create a PeerRegistry record
    in PENDING_APPROVAL state along with a FederatedRegistryCompliance record.

    Returns 422 if any policy violation is found — no partial acceptance.
    """
    # Step 1: Validate policy
    result = _validator.validate(request.policy_json)

    if not result.valid:
        logger.warning(
            f"[FederationAdmission] Admission rejected for {request.registry_operator_did} "
            f"— {len(result.violations)} violation(s)"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Policy validation failed — admission denied",
                "violations": [v.to_dict() for v in result.violations],
                "warnings": result.warnings,
                "policy_hash": result.submitted_hash,
            },
        )

    # Step 2: Check if a peer with this URL or name already exists
    existing = await db.execute(
        select(PeerRegistry).where(
            (PeerRegistry.base_url == request.registry_public_url) |
            (PeerRegistry.name == request.registry_name)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A peer registry with this URL or name already exists.",
        )

    # Step 3: Create PeerRegistry (PENDING_APPROVAL)
    peer = PeerRegistry(
        owner_developer_id=admin.id,
        name=request.registry_name,
        description=f"Registry operated by {request.registry_operator_did}",
        base_url=request.registry_public_url,
        admin_contact_email=request.admin_contact_email,
        status="PENDING_APPROVAL",
        discovery_auth_info={"operator_did": request.registry_operator_did},
        interaction_auth_info=request.operator_identity_proof or {},
    )
    db.add(peer)
    await db.flush()   # get peer.id before compliance record

    # Step 4: Create FederatedRegistryCompliance record
    compliance = FederatedRegistryCompliance(
        peer_registry_id=peer.id,
        policy_json=request.policy_json,
        policy_hash=result.submitted_hash,
        policy_version=1,
        federation_status="pending",
    )
    db.add(compliance)
    await db.commit()
    await db.refresh(compliance)

    logger.info(
        f"[FederationAdmission] Admission request created — peer_id={peer.id}, "
        f"admission_id={compliance.id}, hash={result.submitted_hash[:16]}..."
    )

    return AdmissionResponse(
        admission_id=str(compliance.id),
        peer_registry_id=peer.id,
        status="pending_approval",
        policy_hash=result.submitted_hash,
        violations=[],
        warnings=result.warnings,
        message=(
            "Admission request created. Commander must call POST "
            f"/complete-admission/{compliance.id} to activate federation."
        ),
    )


@router.post(
    "/complete-admission/{admission_id}",
    summary="Commander approves a pending admission (Step 4 of D-FED-1)",
)
async def complete_admission(
    admission_id: str,
    db: AsyncSession = Depends(get_db),
    admin=Security(security.require_admin_flag("admin_federation")),
):
    """
    Activate a previously submitted and policy-valid admission.
    Sets PeerRegistry.status = ACTIVE and FederatedRegistryCompliance.federation_status = 'federated'.
    Emits RegistryFederated event to EventStore.
    """
    compliance = await _get_compliance_by_admission_id(db, admission_id)

    if compliance.federation_status not in ("pending",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot complete admission in current state: {compliance.federation_status}",
        )

    # Fetch peer
    peer_result = await db.execute(
        select(PeerRegistry).where(PeerRegistry.id == compliance.peer_registry_id)
    )
    peer = peer_result.scalar_one_or_none()
    if not peer:
        raise HTTPException(status_code=404, detail="Peer registry record not found")

    now = datetime.now(timezone.utc)

    # Activate peer
    peer.status = "ACTIVE"
    peer.approved_at = now
    peer.approved_by_developer_id = admin.id

    # Mark compliance as federated
    compliance.federation_status = "federated"
    compliance.admitted_at = now
    compliance.admitted_by = admin.email

    await db.commit()

    # Emit RegistryFederated event (best-effort — don't fail admission if emitter is down)
    try:
        from ..event_emitter import get_event_emitter
        emitter = get_event_emitter()
        await emitter.emit_event(
            aggregate_id=str(peer.id),
            event_type="RegistryFederated",
            event_data={
                "peer_registry_id": peer.id,
                "peer_name": peer.name,
                "peer_url": peer.base_url,
                "policy_hash": compliance.policy_hash,
                "admitted_by": admin.email,
                "admitted_at": now.isoformat(),
            },
        )
    except Exception as e:
        logger.warning(f"[FederationAdmission] EventStore emit failed (non-fatal): {e}")

    logger.info(
        f"[FederationAdmission] Federation ACTIVE — peer={peer.name} "
        f"(id={peer.id}), admitted_by={admin.email}"
    )

    return {
        "peer_registry_id": peer.id,
        "peer_name": peer.name,
        "status": "federated",
        "effective_at": now.isoformat(),
        "policy_hash": compliance.policy_hash,
    }


@router.get(
    "/admission-status/{admission_id}",
    response_model=AdmissionStatusResponse,
    summary="Poll the status of a pending admission",
)
async def get_admission_status(
    admission_id: str,
    db: AsyncSession = Depends(get_db),
    _admin=Security(security.require_admin_flag("admin_federation")),
):
    compliance = await _get_compliance_by_admission_id(db, admission_id)
    peer_result = await db.execute(
        select(PeerRegistry).where(PeerRegistry.id == compliance.peer_registry_id)
    )
    peer = peer_result.scalar_one_or_none()

    return AdmissionStatusResponse(
        admission_id=str(compliance.id),
        peer_registry_id=compliance.peer_registry_id,
        peer_name=peer.name if peer else None,
        federation_status=compliance.federation_status,
        policy_hash=compliance.policy_hash,
        admitted_at=compliance.admitted_at.isoformat() if compliance.admitted_at else None,
        admitted_by=compliance.admitted_by,
        quarantine_reason=compliance.quarantine_reason,
    )


@router.post(
    "/policy-update-request",
    summary="Operator requests a bounded-param policy change (auto-approved if compliant)",
)
async def policy_update_request(
    request: PolicyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin=Security(security.require_admin_flag("admin_federation")),
):
    """
    D-FED-5: Operator-zone changes (bounded params only) are auto-approved.
    Any modification to a LOCKED param returns 422.

    Steps:
      1. Find the peer's compliance record by DID
      2. Validate proposed policy — must pass all locked param checks
      3. Check no locked params changed vs stored snapshot
      4. Update compliance record policy_hash
      5. Emit PolicyUpdated event
    """
    from ..core.base_network_params import LOCKED_PARAMS
    from ..services.federation_policy_validator import deep_get

    # Find peer by operator DID stored in discovery_auth_info
    peers_result = await db.execute(select(PeerRegistry))
    peers = peers_result.scalars().all()
    peer = next(
        (p for p in peers if p.discovery_auth_info.get("operator_did") == request.peer_did),
        None,
    )
    if not peer:
        raise HTTPException(status_code=404, detail="No peer registry found for that DID")

    comp_result = await db.execute(
        select(FederatedRegistryCompliance).where(
            FederatedRegistryCompliance.peer_registry_id == peer.id
        )
    )
    compliance = comp_result.scalar_one_or_none()
    if not compliance:
        raise HTTPException(status_code=404, detail="No compliance record found for peer")

    if compliance.federation_status not in ("federated", "soft_quarantined"):
        raise HTTPException(
            status_code=409,
            detail=f"Policy updates not allowed in state: {compliance.federation_status}",
        )

    # Validate new policy
    result = _validator.validate(request.proposed_policy_json)
    if not result.valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Proposed policy failed validation",
                "violations": [v.to_dict() for v in result.violations],
            },
        )

    # Verify no locked param changed from the stored snapshot
    locked_changes = []
    for path, required_value in LOCKED_PARAMS.items():
        old_val = deep_get(compliance.policy_json, path)
        new_val = deep_get(request.proposed_policy_json, path)
        if old_val != new_val:
            locked_changes.append({"path": path, "old": old_val, "new": new_val})

    if locked_changes:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot modify locked parameters via policy-update-request",
                "locked_changes": locked_changes,
            },
        )

    # Auto-approve: update compliance record
    import json as _json
    compliance.policy_json = request.proposed_policy_json
    compliance.policy_hash = result.submitted_hash
    compliance.policy_version += 1
    compliance.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Emit PolicyUpdated event (best-effort)
    try:
        from ..event_emitter import get_event_emitter
        emitter = get_event_emitter()
        await emitter.emit_event(
            aggregate_id=str(peer.id),
            event_type="FederationPolicyUpdated",
            event_data={
                "peer_registry_id": peer.id,
                "peer_did": request.peer_did,
                "new_policy_hash": result.submitted_hash,
                "policy_version": compliance.policy_version,
                "change_summary": request.change_summary,
                "approved_by": admin.email,
            },
        )
    except Exception as e:
        logger.warning(f"[FederationAdmission] EventStore emit failed (non-fatal): {e}")

    return {
        "status": "auto_approved",
        "peer_did": request.peer_did,
        "new_policy_hash": result.submitted_hash,
        "policy_version": compliance.policy_version,
        "effective_at": datetime.now(timezone.utc).isoformat(),
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# Option D-light Phase D4 (2026-04-21): manual drift-scan trigger.
# The background license_drift_monitor runs hourly only when
# IS_CENTRAL_REGISTRY=True. This endpoint lets Commander invoke a single
# scan on demand, regardless of the gate, so detection can be tested
# without flipping the flag.
# ---------------------------------------------------------------------------

@router.post(
    "/drift-scan",
    # §pass56 PR-5: tags= dropped; APIRouter tag "Federation Admission" applies
    summary="Manually trigger a license/operator/peer state drift scan",
)
async def trigger_drift_scan(
    current_admin=Security(security.require_admin_flag("admin_federation")),
):
    """
    Runs one cycle of the license_drift_monitor detection logic.

    Emits `FederationStateDriftDetected` to EventStore per offender
    (deduplicated per-day via idempotency key). Returns per-type drift
    counts so the caller can spot-check without querying EventStore.

    Use to validate drift detection after:
      - Manual license/operator state changes
      - Cascade fixes that should close outstanding drift
      - Incident investigation ("is anything inconsistent right now?")
    """
    from ..background_tasks.license_drift_monitor import run_once

    total, counts = await run_once()
    return {
        "status": "completed",
        "total_drifts": total,
        "by_drift_type": counts,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "note": "Events emitted with per-day idempotency_key — repeat scans same day are no-ops in EventStore.",
    }
