"""Attestation API endpoints for Zero-Knowledge Proof submissions with Event Store integration."""

from fastapi import APIRouter, HTTPException, Depends, Query, Security
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel
from typing import Dict, Any, List, Annotated, Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta
import base64
import hashlib
import json
import logging
import asyncio
import os
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import zkp_verifier as _zkp
from ..core.zkp_verifier import verify_proof_detailed
from ..core.reputation_manager import (
    record_attestation_success,
    record_attestation_revocation,
)
from ..database import get_db
from ..models import Agent, Attestation, Developer
from .utils import get_current_agent
from ..security import admin_credential, get_current_developer
from ..event_emitter import get_event_emitter
from ..crud import attestation as crud_attestation
import uuid

logger = logging.getLogger(__name__)

# OWL28: Use global event emitter factory (reads EVENT_STORE_URL from env, resolves correctly in Docker)
event_emitter = get_event_emitter()

# ─── ZKP attestation maturation — Phase 1+2 kill switches ─────────────────
# Default true so sandbox A picks them up automatically. Production registries
# explicitly set them to "false" in compose for defense-in-depth until
# Commander signs off on a dedicated rollout.
ZKP_PHASE_1_ENABLED = os.environ.get("ZKP_PHASE_1_ENABLED", "true").lower() == "true"
ZKP_PHASE_2_ENABLED = os.environ.get("ZKP_PHASE_2_ENABLED", "true").lower() == "true"
ZKP_PHASE_3_ENABLED = os.environ.get("ZKP_PHASE_3_ENABLED", "true").lower() == "true"
ZKP_PHASE_4_ENABLED = os.environ.get("ZKP_PHASE_4_ENABLED", "true").lower() == "true"
ZKP_PHASE_5_ENABLED = os.environ.get("ZKP_PHASE_5_ENABLED", "true").lower() == "true"
ZKP_BUNDLE_SIGNING_ENABLED = (
    os.environ.get("ZKP_BUNDLE_SIGNING_ENABLED", "true").lower() == "true"
)
try:
    ZKP_BUNDLE_VALID_DAYS = max(1, int(os.environ.get("ZKP_BUNDLE_VALID_DAYS", "90")))
except (TypeError, ValueError):
    ZKP_BUNDLE_VALID_DAYS = 90
try:
    ZKP_DEFAULT_EXPIRY_DAYS = max(1, int(os.environ.get("ZKP_DEFAULT_EXPIRY_DAYS", "90")))
except (TypeError, ValueError):
    ZKP_DEFAULT_EXPIRY_DAYS = 90

# Identifies which registry signed a bundle. Useful when peers exchange
# bundles cross-frame and a verifier needs to know who issued it.
ZKP_BUNDLE_ISSUER_REGISTRY = os.environ.get(
    "ZKP_BUNDLE_ISSUER_REGISTRY",
    os.environ.get("REGISTRY_NAME", os.environ.get("OAUTH_ISSUER", "unknown-registry")),
)

# ── Phase 3 — per-circuit EigenTrust + dispute-reduction tunables ────────
# Per-circuit EigenTrust edge weight contributed by one verified attestation.
# Override via env: ZKP_EIGENTRUST_WEIGHT_<UPPERCASE_CIRCUIT> if needed.
# proof_of_reputation gets a small positive weight so the test flow has a
# non-zero edge to assert on without invoking nargo/bb.
_DEFAULT_EIGENTRUST_WEIGHTS: Dict[str, float] = {
    "fairMarkupPolicy/v1.0.0": 0.05,
    "accurateResourceUsagePolicy/v1.0.0": 0.03,
    "proof_of_reputation/v1.0": 0.02,
    # ── ZKP Maturation Phase 5 (2026-04-28) — additive ────────────────
    "fairCrossRegistryFee/v1.0.0": 0.04,
    "contentSafetyAttestation/v1.0.0": 0.06,
    # v2.0.0 circuits bind their policy limits; same weights as v1.
    "fairMarkupPolicy/v2.0.0": 0.05,
    "accurateResourceUsagePolicy/v2.0.0": 0.03,
    "fairCrossRegistryFee/v2.0.0": 0.04,
    "contentSafetyAttestation/v2.0.0": 0.06,
}

try:
    ZKP_DISPUTE_SLASH_REDUCTION = max(0.0, min(0.5, float(
        os.environ.get("ZKP_DISPUTE_SLASH_REDUCTION", "0.1")
    )))
except (TypeError, ValueError):
    ZKP_DISPUTE_SLASH_REDUCTION = 0.1

# Cumulative cap on slash reduction across all referenced attestations.
ZKP_DISPUTE_SLASH_REDUCTION_CAP = 0.5

try:
    ZKP_GOVERNANCE_BONUS_MULTIPLIER = max(1.0, min(2.0, float(
        os.environ.get("ZKP_GOVERNANCE_BONUS_MULTIPLIER", "1.05")
    )))
except (TypeError, ValueError):
    ZKP_GOVERNANCE_BONUS_MULTIPLIER = 1.05

try:
    ZKP_GOVERNANCE_BONUS_THRESHOLD_DAYS = max(1, int(
        os.environ.get("ZKP_GOVERNANCE_BONUS_THRESHOLD_DAYS", "30")
    ))
except (TypeError, ValueError):
    ZKP_GOVERNANCE_BONUS_THRESHOLD_DAYS = 30

try:
    ZKP_GOVERNANCE_BONUS_THRESHOLD_COUNT = max(1, int(
        os.environ.get("ZKP_GOVERNANCE_BONUS_THRESHOLD_COUNT", "10")
    ))
except (TypeError, ValueError):
    ZKP_GOVERNANCE_BONUS_THRESHOLD_COUNT = 10


def get_eigentrust_weight(circuit_id: str) -> float:
    """Resolve the EigenTrust edge weight for a circuit. Default 0 (no edge).

    Override at runtime via env var
    `ZKP_EIGENTRUST_WEIGHT_<CIRCUIT_KEY>` where the key is uppercase ASCII
    + alphanumeric/underscore (`fairMarkupPolicy/v1.0.0` → `FAIRMARKUPPOLICY_V1_0_0`).
    """
    safe_key = "".join(
        ch.upper() if ch.isalnum() else "_" for ch in (circuit_id or "")
    )
    env_key = f"ZKP_EIGENTRUST_WEIGHT_{safe_key}"
    if env_key in os.environ:
        try:
            return float(os.environ[env_key])
        except (TypeError, ValueError):
            pass
    return float(_DEFAULT_EIGENTRUST_WEIGHTS.get(circuit_id, 0.0))


router = APIRouter(prefix="/api/v1/attestations", tags=["Attestations"])


class AttestationSubmission(BaseModel):
    """Model for attestation submission requests."""
    circuit_id: str
    proof_data: Dict[str, Any]
    public_inputs: Dict[str, Any]


class AttestationResponse(BaseModel):
    """Model for attestation verification responses."""
    status: str
    circuit_id: str
    message: str
    public_inputs: Dict[str, Any]
    attestation_id: Optional[str] = None
    reputation_delta: Optional[int] = None
    # What the proof carries (its public inputs and returned commitment, as
    # decimal strings) and, when it did not verify, why.
    proof_public_values: Optional[Dict[str, str]] = None
    reason: Optional[str] = None


# ─── Phase 1 read-side schemas ────────────────────────────────────────────
class AttestationRecord(BaseModel):
    """Public projection of an Attestation row."""
    id: str
    agent_did: str
    circuit_id: str
    circuit_version: str
    public_inputs: Dict[str, Any]
    proof_hash: str
    policy_parameters_hash: Optional[str] = None
    verified: bool
    failure_reason: Optional[str] = None
    submitted_at: datetime
    verified_at: Optional[datetime] = None
    event_id: Optional[str] = None
    # Phase 2 lifecycle fields (nullable on Phase-1 rows)
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revoked_reason: Optional[str] = None
    expired_emitted_at: Optional[datetime] = None

    @classmethod
    def from_orm_row(cls, row: Attestation) -> "AttestationRecord":
        return cls(
            id=str(row.id),
            agent_did=row.agent_did,
            circuit_id=row.circuit_id,
            circuit_version=row.circuit_version,
            public_inputs=row.public_inputs or {},
            proof_hash=row.proof_hash,
            policy_parameters_hash=row.policy_parameters_hash,
            verified=bool(row.verified),
            failure_reason=row.failure_reason,
            submitted_at=row.submitted_at,
            verified_at=row.verified_at,
            event_id=str(row.event_id) if row.event_id else None,
            expires_at=getattr(row, "expires_at", None),
            revoked_at=getattr(row, "revoked_at", None),
            revoked_by=getattr(row, "revoked_by", None),
            revoked_reason=getattr(row, "revoked_reason", None),
            expired_emitted_at=getattr(row, "expired_emitted_at", None),
        )


class RevokeAttestationRequest(BaseModel):
    """POST /attestations/{id}/revoke body."""
    reason: Optional[str] = None


class RevokeAttestationResponse(BaseModel):
    """Response from a revoke request."""
    attestation_id: str
    revoked_at: datetime
    revoked_by: str
    revoked_reason: Optional[str] = None
    already_revoked: bool = False


# ─── Phase 5 — schedule schemas ──────────────────────────────────────────
class CreateScheduleRequest(BaseModel):
    """POST /attestations/schedules body."""
    circuit_id: str
    interval_hours: int


class ScheduleRecord(BaseModel):
    """Public projection of an AttestationSchedule row."""
    id: str
    agent_did: str
    circuit_id: str
    interval_hours: int
    enabled: bool
    last_attestation_at: Optional[datetime] = None
    next_due_at: datetime
    last_reminder_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, row) -> "ScheduleRecord":
        return cls(
            id=str(row.id),
            agent_did=row.agent_did,
            circuit_id=row.circuit_id,
            interval_hours=row.interval_hours,
            enabled=bool(row.enabled),
            last_attestation_at=row.last_attestation_at,
            next_due_at=row.next_due_at,
            last_reminder_at=row.last_reminder_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ScheduleListResponse(BaseModel):
    items: List[ScheduleRecord]
    count: int


class AttestationListResponse(BaseModel):
    """Paginated list of attestation records."""
    items: List[AttestationRecord]
    count: int
    limit: int
    offset: int


class AttestationReverifyResponse(BaseModel):
    """Response from `/attestations/{id}/verify` re-run."""
    attestation_id: str
    circuit_id: str
    verified: bool
    re_verified_at: datetime
    public_inputs: Dict[str, Any]
    failure_reason: Optional[str] = None
    # Reserved for Phase 2 lifecycle — populated when those columns ship.
    revoked: bool = False
    expired: bool = False


@router.post("/submit", response_model=AttestationResponse)
async def submit_attestation(
    submission: AttestationSubmission,
    current_agent: Annotated[Agent, Security(get_current_agent)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> AttestationResponse:
    """Submit a Zero-Knowledge Proof attestation for verification.

    When `ZKP_PHASE_1_ENABLED` is true, every submission (success or
    failure) is persisted to `attestations`. The DB row's UUID becomes the
    canonical `attestation_id`. The EventStore emission uses an idempotency
    key tied to that UUID so re-runs don't double-count.
    """
    try:
        logger.info(
            f"Received attestation submission from {current_agent.did} "
            f"for circuit: {submission.circuit_id}"
        )

        # ── Verify the proof ────────────────────────────────────────────
        # Verification binds the stated public inputs to the proof, the
        # proof's policy limits to this registry's policy and, for v2
        # circuits, the proof's reference to the submitting agent: it must be
        # derive_reference(<agent DID>, reference_label) (core/zkp_verifier).
        reference_input = _zkp.REFERENCE_INPUTS.get(_zkp.canonical_circuit_id(submission.circuit_id) or "")
        reference_value: Optional[str] = None
        expected: Optional[Dict[str, str]] = None
        if reference_input:
            label = (submission.public_inputs or {}).get("reference_label")
            if not isinstance(label, str) or not 0 < len(label) <= 200:
                raise HTTPException(
                    status_code=422,
                    detail=(f"public_inputs.reference_label is required (1 to 200 characters): the proof's "
                            f"{reference_input} must be derive_reference(<your agent DID>, <label>), so a proof "
                            "names the agent that made it"),
                )
            reference_value = str(_zkp.derive_reference(current_agent.did, label))
            expected = {reference_input: reference_value}
        outcome = await verify_proof_detailed(
            circuit_id=submission.circuit_id,
            proof_data=submission.proof_data,
            public_inputs=submission.public_inputs,
            expected=expected,
        )
        is_valid = outcome.verified
        if reference_input and outcome.reason == f"'{reference_input}' differs from the expected value":
            outcome.reason = (f"the proof's {reference_input} is not derive_reference(<your agent DID>, "
                              "reference_label): it was made for another agent or another label")
        # The canonical id: a legacy alias and the full id are one circuit
        # for storage and for the reputation rule.
        circuit_id = outcome.circuit_id or submission.circuit_id
        public_values = {k: str(v) for k, v in (outcome.public_values or {}).items()} or None

        # ── Compute proof_hash + parse circuit version (regardless of path) ─
        proof_b64 = ""
        if isinstance(submission.proof_data, dict):
            proof_b64 = submission.proof_data.get("proof_bytes") or ""
        try:
            proof_bytes = base64.b64decode(proof_b64) if proof_b64 else b""
        except Exception:
            proof_bytes = proof_b64.encode("utf-8") if isinstance(proof_b64, str) else b""
        proof_hash = hashlib.sha256(proof_bytes).hexdigest()

        if "/" in circuit_id:
            _, _, version_part = circuit_id.partition("/")
            circuit_version = version_part or "unknown"
        else:
            circuit_version = "unknown"

        pp_hash = (submission.public_inputs or {}).get("policy_parameters_hash")
        pp_hash_str = str(pp_hash) if pp_hash is not None else None

        # What a verified v2 row keeps: the stated inputs with every proven
        # value (the commitment included) in canonical decimal form, so the
        # reference lookup below and anyone reading the row see one spelling.
        stored_inputs = dict(submission.public_inputs or {})
        if is_valid and public_values and reference_input:
            stored_inputs.update(public_values)

        # ── Persist (Phase 1 — kill-switch gated) ───────────────────────
        attestation_uuid: Optional[uuid.UUID] = None
        persisted_row: Optional[Attestation] = None
        earns = False
        if ZKP_PHASE_1_ENABLED:
            try:
                if is_valid:
                    # Concurrent submits of the same proof, the same reference or
                    # the same agent's circuit-day wait for each other here; the
                    # locks hold until create_attestation commits.
                    lock_keys = [f"attestation-proof:{proof_hash}", f"attestation-day:{current_agent.did}:{circuit_id}"]
                    if reference_value:
                        lock_keys.append(f"attestation-ref:{circuit_id}:{reference_value}")
                    await crud_attestation.advisory_lock(db, *lock_keys)
                    # A proof counts once. The raw bytes, and for v2 the circuit
                    # and reference: a proof changed byte by byte carries the same
                    # public values, and the reference names one agent and label.
                    earlier = await crud_attestation.find_verified_by_proof_hash(db, proof_hash=proof_hash)
                    if earlier is None and reference_value:
                        earlier = await crud_attestation.find_verified_by_reference(
                            db, circuit_id=circuit_id, reference_input=reference_input, reference=reference_value,
                        )
                    if earlier is not None:
                        # Read the id before the rollback: a rollback expires every row
                        # the session loaded, and reading an expired one here loads it
                        # outside the async driver (MissingGreenlet, found live on V0611).
                        earlier_id = earlier.id
                        await db.rollback()
                        raise HTTPException(
                            status_code=409,
                            detail=(f"This proof (or one with the same {reference_input or 'bytes'}) was already "
                                    f"attested as {earlier_id}. A proof counts once; prove again with a new "
                                    "reference_label to attest again."),
                        )
                # Taken inside the lock, so the earliest row of a day is the one that earned.
                now = datetime.now(timezone.utc)
                if is_valid:
                    # +1 for the first verified v2 attestation per agent, circuit and UTC
                    # day (crud_attestation.earned_reputation); a retired circuit's row
                    # earns as it always did.
                    earns = (
                        await crud_attestation.count_verified_on_day(
                            db, agent_did=current_agent.did, circuit_id=circuit_id, day=now,
                        ) == 0
                        if reference_input else True
                    )
                # Phase 2: compute default expiry. When Phase 2 is off we still
                # accept rows with expires_at=NULL (treated as "no expiry").
                expires_at = (
                    now + timedelta(days=ZKP_DEFAULT_EXPIRY_DAYS)
                    if ZKP_PHASE_2_ENABLED
                    else None
                )
                row = await crud_attestation.create_attestation(
                    db,
                    agent_did=current_agent.did,
                    circuit_id=circuit_id,
                    circuit_version=circuit_version,
                    public_inputs=stored_inputs,
                    proof_b64=proof_b64 or None,
                    proof_hash=proof_hash,
                    policy_parameters_hash=pp_hash_str,
                    verified=bool(is_valid),
                    failure_reason=None if is_valid else outcome.reason,
                    submitted_at=now,
                    verified_at=now if is_valid else None,
                    expires_at=expires_at,
                )
                attestation_uuid = row.id
                persisted_row = row
            except HTTPException:
                raise
            except Exception as exc:
                earns = False
                logger.error(
                    f"[ZKP-Phase1] Failed to persist attestation row: {exc}",
                    exc_info=True,
                )
                if is_valid:
                    # The replay guard and the row are one step. A verified proof that
                    # could not be checked and stored is not an attestation: answering
                    # "verified" would name an id nothing holds, and could pass a replay.
                    # Nothing was granted; the caller may submit again.
                    try:
                        await db.rollback()
                    except Exception as rb_exc:
                        logger.warning(f"[ZKP-Phase1] rollback after the failed write: {rb_exc}")
                    raise HTTPException(
                        status_code=503,
                        detail=("The proof verified, but the attestation could not be recorded, so nothing "
                                "was granted. Submit it again."),
                        headers={"Retry-After": "5"},
                    )
                # A failed proof still answers "failed": its row is only a record.

        if attestation_uuid is None:
            attestation_uuid = uuid.uuid4()
        attestation_id = str(attestation_uuid)

        # ── Reputation, event emission, response ────────────────────────
        if is_valid:
            logger.info(
                f"Attestation verified successfully for circuit: "
                f"{circuit_id} (id={attestation_id}): {outcome.reason}"
            )

            reputation_delta = None
            try:
                # Nothing stored (Phase 1 off, or the write failed): no point,
                # since there is no row to check the day against or to revoke.
                new_score = await record_attestation_success(db, current_agent.did) if (earns and persisted_row is not None) else None
                if new_score is not None:
                    reputation_delta = 1
                    logger.info(
                        f"Reputation updated for {current_agent.did}: "
                        f"new score={new_score}"
                    )
            except Exception as exc:
                logger.error(
                    f"Failed to update reputation for {current_agent.did}: {exc}"
                )

            try:
                asyncio.create_task(_emit_attestation_submitted_event(
                    agent_did=current_agent.did,
                    attestation_type=circuit_id,
                    attestation_id=attestation_id,
                    attestation_data={
                        "proof_data": submission.proof_data,
                        "public_inputs": submission.public_inputs,
                        "status": "verified",
                        "attestation_id": attestation_id,
                    },
                ))
            except Exception as exc:
                logger.error(f"Failed to schedule event emission: {exc}")

            # Phase 3 trust-chain: emit EigenTrustSignal with per-circuit
            # weight. Existing engine ingests via aggregation; the audit
            # trail goes to EventStore regardless.
            if ZKP_PHASE_3_ENABLED:
                weight = get_eigentrust_weight(circuit_id)
                if weight != 0.0:
                    try:
                        asyncio.create_task(event_emitter.emit(
                            event_type="EigenTrustSignal",
                            aggregate_id=current_agent.did,
                            data={
                                "subtype": "attestation",
                                "agent_did": current_agent.did,
                                "circuit_id": circuit_id,
                                "attestation_id": attestation_id,
                                "weight": weight,
                            },
                            idempotency_key=f"eigentrust_signal:attestation:{attestation_id}",
                        ))
                    except Exception as exc:
                        logger.error(f"[ZKP-Phase3] EigenTrustSignal emission failed: {exc}")

            # Phase 5 schedule coupling: if this agent has a schedule for
            # this circuit, advance next_due_at and stamp last_attestation_at.
            # Best-effort — never fail the submit on a schedule update glitch.
            if ZKP_PHASE_5_ENABLED:
                try:
                    # A schedule made for a retired v1.0.0 id is kept by its v2.0.0 successor.
                    for scheduled in {circuit_id, circuit_id.replace("/v2.0.0", "/v1.0.0")}:
                        await crud_attestation.update_schedule_on_attestation(
                            db,
                            agent_did=current_agent.did,
                            circuit_id=scheduled,
                        )
                except Exception as exc:
                    logger.error(f"[ZKP-Phase5] schedule advance failed: {exc}")

            return AttestationResponse(
                status="verified",
                circuit_id=circuit_id,
                message="Proof verified successfully",
                public_inputs=submission.public_inputs,
                attestation_id=attestation_id,
                reputation_delta=reputation_delta,
                proof_public_values=public_values,
            )
        else:
            logger.warning(
                f"Attestation verification failed for circuit: "
                f"{circuit_id} (id={attestation_id}): {outcome.reason}"
            )
            try:
                asyncio.create_task(_emit_attestation_submitted_event(
                    agent_did=current_agent.did,
                    attestation_type=circuit_id,
                    attestation_id=attestation_id,
                    attestation_data={
                        "proof_data": submission.proof_data,
                        "public_inputs": submission.public_inputs,
                        "status": "failed",
                        "attestation_id": attestation_id,
                    },
                ))
            except Exception as exc:
                logger.error(f"Failed to schedule event emission: {exc}")

            return AttestationResponse(
                status="failed",
                circuit_id=circuit_id,
                message=f"Proof not verified: {outcome.reason}",
                public_inputs=submission.public_inputs,
                attestation_id=attestation_id,
                proof_public_values=public_values,
                reason=outcome.reason,
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error processing attestation: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error during verification: {exc}",
        )


async def _emit_attestation_submitted_event(
    agent_did: str,
    attestation_type: str,
    attestation_data: Dict[str, Any],
    attestation_id: Optional[str] = None,
):
    """Emit AttestationSubmitted to the EventStore with deterministic idempotency.

    `attestation_id` is the canonical UUID (DB row id when Phase 1 enabled,
    in-memory UUID otherwise). It becomes the idempotency key
    `attestation:<id>` so retries don't create duplicate ledger events.
    """
    try:
        idem_key = f"attestation:{attestation_id}" if attestation_id else None
        success = await event_emitter.emit(
            event_type="AttestationSubmitted",
            aggregate_id=agent_did,
            data={
                "attestation_type": attestation_type,
                "attestation_data": attestation_data,
            },
            idempotency_key=idem_key,
        )
        if success:
            logger.info(
                f"Successfully emitted AttestationSubmitted event for {agent_did} "
                f"(idem={idem_key})"
            )
        else:
            logger.error(f"Failed to emit AttestationSubmitted event for {agent_did}")
    except Exception as exc:
        logger.error(f"Error emitting attestation submitted event: {exc}")


@router.get("/health")
async def attestation_health_check():
    """Health check endpoint for the attestation service."""
    return {"status": "healthy", "service": "Attestations"}


# ─── Phase 2 — admin/expiry-sweep (sandbox-only) ─────────────────────────
# Registered BEFORE the `/admin/{id}/revoke` route so the `run-expiry-sweep`
# literal isn't shadowed by the path-parameter catcher.

@router.post("/admin/run-expiry-sweep")
async def admin_run_expiry_sweep(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
):
    """Trigger one cycle of the attestation_expiry sweeper synchronously.

    Sandbox-only — gated by SANDBOX_MODE=true. Used by `flow_zkp_lifecycle`
    quality-gate flow to deterministically advance time without waiting for
    the daily cron. Production registries reject with 403.
    """
    if os.environ.get("SANDBOX_MODE", "false").lower() != "true":
        raise HTTPException(
            status_code=403,
            detail="run-expiry-sweep is sandbox-only (SANDBOX_MODE != true)",
        )
    # Lazy import — avoids module-level circular when reactor framework boots
    from ..background_tasks.attestation_expiry import expiry_cycle_once
    processed = await expiry_cycle_once(db)
    return {"processed": int(processed)}


@router.post("/admin/run-schedule-cron")
async def admin_run_schedule_cron(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
):
    """Trigger one cycle of the attestation_schedule cron synchronously.

    Sandbox-only — same pattern as run-expiry-sweep. Used by Phase-5
    quality-gate flow to verify the cron emits one AttestationDueReminder
    per overdue schedule and is idempotent across consecutive runs.
    """
    if os.environ.get("SANDBOX_MODE", "false").lower() != "true":
        raise HTTPException(
            status_code=403,
            detail="run-schedule-cron is sandbox-only (SANDBOX_MODE != true)",
        )
    from ..background_tasks.attestation_schedule_cron import schedule_cycle_once
    processed = await schedule_cycle_once(db)
    return {"processed": int(processed)}


# ─── Phase 5 — schedule endpoints ────────────────────────────────────────
@router.post("/schedules", response_model=ScheduleRecord)
async def create_or_upsert_schedule(
    body: CreateScheduleRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)],
) -> ScheduleRecord:
    """Agent declares a recurring-attestation schedule for a circuit.

    Idempotent: calling twice with the same (agent, circuit) updates the
    interval and resets the cycle. Returns the persisted row.
    """
    if not ZKP_PHASE_5_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_5_ENABLED=false")
    if body.circuit_id not in _ACTIVE_CIRCUIT_IDS:
        retired = _CIRCUIT_FILE_MAP.get(body.circuit_id)
        if retired:
            detail = f"Circuit '{body.circuit_id}' is retired; schedule {retired['superseded_by']} instead"
        elif body.circuit_id == "proof_of_reputation/v1.0":
            detail = "proof_of_reputation has no circuit keys, so no submission for it can verify"
        else:
            detail = f"Unknown circuit_id '{body.circuit_id}'"
        raise HTTPException(status_code=400, detail=detail)
    interval = int(body.interval_hours or 0)
    if interval < 1 or interval > 720:
        raise HTTPException(
            status_code=400,
            detail="interval_hours must be in [1, 720]",
        )
    row = await crud_attestation.upsert_schedule(
        db,
        agent_did=current_agent.did,
        circuit_id=body.circuit_id,
        interval_hours=interval,
    )
    return ScheduleRecord.from_orm_row(row)


@router.get("/schedules", response_model=ScheduleListResponse)
async def list_my_schedules(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)],
) -> ScheduleListResponse:
    if not ZKP_PHASE_5_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_5_ENABLED=false")
    rows = await crud_attestation.list_schedules(db, agent_did=current_agent.did)
    return ScheduleListResponse(
        items=[ScheduleRecord.from_orm_row(r) for r in rows],
        count=len(rows),
    )


@router.delete("/schedules/{schedule_id}")
async def disable_my_schedule(
    schedule_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)],
):
    if not ZKP_PHASE_5_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_5_ENABLED=false")
    try:
        sid = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule_id (not UUID)")
    row = await crud_attestation.get_schedule(db, schedule_id=sid)
    if row is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if row.agent_did != current_agent.did:
        raise HTTPException(
            status_code=403,
            detail="Agents may only disable their own schedules",
        )
    await crud_attestation.disable_schedule(db, schedule_id=sid)
    return {"status": "disabled", "schedule_id": str(sid)}


# ─── Phase 2 — revoke endpoints ──────────────────────────────────────────
async def _emit_attestation_revoked(
    attestation_id: str,
    agent_did: str,
    revoked_by: str,
    reason: Optional[str],
    revoked_at: datetime,
    circuit_id: Optional[str] = None,
    reputation_clawed: bool = False,
    was_verified: bool = True,
) -> None:
    try:
        await event_emitter.emit(
            event_type="AttestationRevoked",
            aggregate_id=agent_did,
            data={
                "attestation_id": attestation_id,
                "agent_did": agent_did,
                "revoked_by": revoked_by,
                "revoked_reason": reason,
                "revoked_at": revoked_at.isoformat(),
                "circuit_id": circuit_id,
            },
            idempotency_key=f"attestation_revoked:{attestation_id}",
        )
    except Exception as exc:
        logger.error(f"[AttestationRevoked] emission failed: {exc}", exc_info=True)

    # Phase 3 trust-chain claw-back: the audit event when a reputation point
    # was taken back, and the reverse EigenTrust signal for a row that was
    # verified (only those emitted the forward signal at submit).
    if ZKP_PHASE_3_ENABLED and was_verified:
        if reputation_clawed:
            try:
                await event_emitter.emit(
                    event_type="AttestationReputationClawed",
                    aggregate_id=agent_did,
                    data={
                        "attestation_id": attestation_id,
                        "agent_did": agent_did,
                        "circuit_id": circuit_id,
                        "reason": "attestation_revoked",
                        "revoked_at": revoked_at.isoformat(),
                    },
                    idempotency_key=f"attestation_clawed:{attestation_id}",
                )
            except Exception as exc:
                logger.error(f"[AttestationReputationClawed] emission failed: {exc}")

        if circuit_id:
            weight = -1.0 * get_eigentrust_weight(circuit_id)
            if weight != 0.0:
                try:
                    await event_emitter.emit(
                        event_type="EigenTrustSignal",
                        aggregate_id=agent_did,
                        data={
                            "subtype": "attestation_clawback",
                            "agent_did": agent_did,
                            "circuit_id": circuit_id,
                            "attestation_id": attestation_id,
                            "weight": weight,
                        },
                        idempotency_key=f"eigentrust_signal:clawback:{attestation_id}",
                    )
                except Exception as exc:
                    logger.error(
                        f"[ZKP-Phase3] reverse EigenTrustSignal emission failed: {exc}"
                    )


@router.post(
    "/admin/{attestation_id}/revoke",
    response_model=RevokeAttestationResponse,
    summary="Admin: revoke any attestation (Phase 2)",
)
async def admin_revoke_attestation_endpoint(
    attestation_id: str,
    body: RevokeAttestationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
) -> RevokeAttestationResponse:
    if not admin_credential(current_developer):   # D6-057 (§POCKETPAIR): a scoped key is not admin
        raise HTTPException(status_code=403, detail="Admin flag required")
    if not ZKP_PHASE_2_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_2_ENABLED=false")

    try:
        att_uuid = uuid.UUID(attestation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attestation_id (not UUID)")

    pre = await crud_attestation.get_attestation(db, att_uuid)
    if pre is None:
        raise HTTPException(status_code=404, detail="Attestation not found")
    already = pre.revoked_at is not None

    revoker_label = f"admin:{current_developer.id}"
    row = await crud_attestation.revoke_attestation(
        db,
        attestation_id=att_uuid,
        revoked_by=revoker_label,
        reason=body.reason,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Attestation not found")

    if not already:
        # Phase 3 trust-chain: take back the +1 only from the attestation that earned it.
        clawed = False
        if ZKP_PHASE_3_ENABLED:
            try:
                if await crud_attestation.earned_reputation(db, row):
                    await record_attestation_revocation(db, row.agent_did, str(row.id))
                    clawed = True
            except Exception as exc:
                logger.error(f"[ZKP-Phase3] reputation claw-back DB write failed: {exc}")
        asyncio.create_task(_emit_attestation_revoked(
            attestation_id=str(row.id),
            agent_did=row.agent_did,
            revoked_by=row.revoked_by,
            reason=row.revoked_reason,
            revoked_at=row.revoked_at,
            circuit_id=row.circuit_id,
            reputation_clawed=clawed,
            was_verified=bool(row.verified),
        ))

    return RevokeAttestationResponse(
        attestation_id=str(row.id),
        revoked_at=row.revoked_at,
        revoked_by=row.revoked_by,
        revoked_reason=row.revoked_reason,
        already_revoked=already,
    )


@router.post(
    "/{attestation_id}/revoke",
    response_model=RevokeAttestationResponse,
    summary="Agent self-revoke own attestation",
)
async def agent_revoke_attestation_endpoint(
    attestation_id: str,
    body: RevokeAttestationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)],
) -> RevokeAttestationResponse:
    if not ZKP_PHASE_2_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_2_ENABLED=false")

    try:
        att_uuid = uuid.UUID(attestation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attestation_id (not UUID)")

    pre = await crud_attestation.get_attestation(db, att_uuid)
    if pre is None:
        raise HTTPException(status_code=404, detail="Attestation not found")
    if pre.agent_did != current_agent.did:
        raise HTTPException(
            status_code=403,
            detail="Agents may only self-revoke their own attestations",
        )
    already = pre.revoked_at is not None

    row = await crud_attestation.revoke_attestation(
        db,
        attestation_id=att_uuid,
        revoked_by=current_agent.did,
        reason=body.reason,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Attestation not found")

    if not already:
        # Phase 3 trust-chain: take back the +1 only from the attestation that earned it.
        clawed = False
        if ZKP_PHASE_3_ENABLED:
            try:
                if await crud_attestation.earned_reputation(db, row):
                    await record_attestation_revocation(db, row.agent_did, str(row.id))
                    clawed = True
            except Exception as exc:
                logger.error(f"[ZKP-Phase3] reputation claw-back DB write failed: {exc}")
        asyncio.create_task(_emit_attestation_revoked(
            attestation_id=str(row.id),
            agent_did=row.agent_did,
            revoked_by=row.revoked_by,
            reason=row.revoked_reason,
            revoked_at=row.revoked_at,
            circuit_id=row.circuit_id,
            reputation_clawed=clawed,
            was_verified=bool(row.verified),
        ))

    return RevokeAttestationResponse(
        attestation_id=str(row.id),
        revoked_at=row.revoked_at,
        revoked_by=row.revoked_by,
        revoked_reason=row.revoked_reason,
        already_revoked=already,
    )


# ─── Phase 3 — admin debug endpoints (sandbox-only) ──────────────────────
@router.get("/admin/disputes/{dispute_id}/preview-slash-reduction")
async def admin_preview_slash_reduction(
    dispute_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
):
    """Compute (without applying) the slash-reduction factor a dispute would get from its
    `referenced_attestations`. Sandbox-only debug endpoint;
    surfaces the same logic that the federation slash-request path will
    consume once Phase 3b wiring is hooked into the slash pipeline.
    """
    if os.environ.get("SANDBOX_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="sandbox-only endpoint")
    if not ZKP_PHASE_3_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_3_ENABLED=false")

    # Lazy import to avoid circular when the router module loads early.
    from ..crud import crud_disputes
    dispute = await crud_disputes.get_dispute_by_id(db, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=404, detail="Dispute not found")

    refs: List[uuid.UUID] = []
    raw_refs = getattr(dispute, "referenced_attestations", None) or []
    for v in raw_refs:
        try:
            refs.append(uuid.UUID(str(v)))
        except (TypeError, ValueError):
            continue

    eligible = await crud_attestation.list_attestations_for_dispute_reduction(
        db,
        defendant_did=dispute.defendant_did,
        attestation_ids=refs,
    )
    raw_reduction = ZKP_DISPUTE_SLASH_REDUCTION * len(eligible)
    capped_reduction = min(raw_reduction, ZKP_DISPUTE_SLASH_REDUCTION_CAP)
    factor = max(0.0, 1.0 - capped_reduction)
    return {
        "dispute_id": dispute_id,
        "defendant_did": dispute.defendant_did,
        "referenced_attestations_total": len(refs),
        "eligible_attestations": [str(a.id) for a in eligible],
        "per_attestation_reduction": ZKP_DISPUTE_SLASH_REDUCTION,
        "raw_reduction": raw_reduction,
        "capped_reduction": capped_reduction,
        "slash_factor": factor,
    }


@router.get("/admin/mcp-passthrough/get-agent-profile")
async def admin_mcp_passthrough_get_agent_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
    agent_did: str = Query(...),
):
    """Sandbox-only debug: invokes the MCP `getAgentProfile` function over
    HTTP so the quality-gate flow can assert the profile shape (including
    Phase 3's `recent_attestations` field) without a JSON-RPC client.
    """
    if os.environ.get("SANDBOX_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="sandbox-only endpoint")
    from ..mcp.tools_discovery import get_agent_profile
    return await get_agent_profile(agent_did)


@router.get("/admin/governance/preview-voting-power")
async def admin_preview_voting_power(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
    agent_did: str = Query(...),
):
    """Compute the voting-power bonus an agent would receive given its recent
    verified attestations, without casting an actual vote. Sandbox-only.
    """
    if os.environ.get("SANDBOX_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="sandbox-only endpoint")
    if not ZKP_PHASE_3_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_3_ENABLED=false")

    count = await crud_attestation.count_recent_verified(
        db, agent_did=agent_did,
        since_days=ZKP_GOVERNANCE_BONUS_THRESHOLD_DAYS,
    )
    bonus_eligible = count >= ZKP_GOVERNANCE_BONUS_THRESHOLD_COUNT
    multiplier = ZKP_GOVERNANCE_BONUS_MULTIPLIER if bonus_eligible else 1.0
    return {
        "agent_did": agent_did,
        "recent_verified_attestations": count,
        "threshold_count": ZKP_GOVERNANCE_BONUS_THRESHOLD_COUNT,
        "threshold_days": ZKP_GOVERNANCE_BONUS_THRESHOLD_DAYS,
        "bonus_eligible": bonus_eligible,
        "multiplier": multiplier,
    }


# ─── Phase 1 read-side endpoints ──────────────────────────────────────────
def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Tolerant ISO8601 parser. Accepts 'Z' suffix and naive strings."""
    if not ts:
        return None
    try:
        cleaned = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise HTTPException(
            status_code=400, detail=f"Invalid ISO8601 timestamp: {ts!r}"
        )


@router.get(
    "",
    response_model=AttestationListResponse,
    summary="List attestations (admin/developer view)",
)
async def list_attestations_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
    agent_did: Optional[str] = Query(default=None),
    circuit_id: Optional[str] = Query(default=None),
    verified: Optional[bool] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO8601 lower bound (inclusive)"),
    until: Optional[str] = Query(default=None, description="ISO8601 upper bound (exclusive)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AttestationListResponse:
    since_dt = _parse_iso(since)
    until_dt = _parse_iso(until)
    rows = await crud_attestation.list_attestations(
        db,
        agent_did=agent_did,
        circuit_id=circuit_id,
        verified=verified,
        since=since_dt,
        until=until_dt,
        limit=limit,
        offset=offset,
    )
    total = await crud_attestation.count_attestations(
        db,
        agent_did=agent_did,
        circuit_id=circuit_id,
        verified=verified,
        since=since_dt,
        until=until_dt,
    )
    return AttestationListResponse(
        items=[AttestationRecord.from_orm_row(r) for r in rows],
        count=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/signing-pubkey",
    summary="Get the registry's bundle-signing Ed25519 pubkey (public)",
)
async def get_bundle_signing_pubkey():
    """Return the Ed25519 public key used to sign exportable bundles.

    Anyone with this key can verify a bundle's signature offline. The
    `pubkey_id` field is the short identifier referenced inside each
    bundle (so verifiers can pin the signing key even across rotations).
    """
    if not ZKP_PHASE_4_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_4_ENABLED=false")
    from ..services import attestation_signer
    return {
        "alg": "Ed25519",
        "pubkey_b64": attestation_signer.get_pubkey_b64(),
        "pubkey_id": attestation_signer.get_pubkey_id(),
        "issuer_registry": ZKP_BUNDLE_ISSUER_REGISTRY,
    }


def _build_canonical_bundle(row: Attestation) -> Dict[str, Any]:
    """Construct the canonical bundle dict for a stored attestation row."""
    valid_until = (
        row.expires_at.isoformat()
        if getattr(row, "expires_at", None)
        else (row.submitted_at + timedelta(days=ZKP_BUNDLE_VALID_DAYS)).isoformat()
    )
    return {
        "attestation_id": str(row.id),
        "agent_did": row.agent_did,
        "circuit_id": row.circuit_id,
        "circuit_version": row.circuit_version,
        "public_inputs": row.public_inputs or {},
        "proof_b64": row.proof_b64 or "",
        "proof_hash": row.proof_hash,
        "policy_parameters_hash": row.policy_parameters_hash,
        "verified": bool(row.verified),
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "issuer_registry": ZKP_BUNDLE_ISSUER_REGISTRY,
        "valid_until": valid_until,
        "revoked": bool(getattr(row, "revoked_at", None)),
        "revoked_at": row.revoked_at.isoformat() if getattr(row, "revoked_at", None) else None,
        "revoked_reason": getattr(row, "revoked_reason", None),
        "signature_alg": "Ed25519",
        "signature": "",
    }


@router.get("/{attestation_id}/bundle")
async def get_attestation_bundle(
    attestation_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a signed exportable bundle for an attestation (public).

    The bundle is the registry's authoritative, signature-verifiable
    export of the attestation. Anyone with the registry's signing pubkey
    can verify the bundle offline using `scripts/verify_attestation_bundle.py`.
    """
    if not ZKP_PHASE_4_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_4_ENABLED=false")
    try:
        att_uuid = uuid.UUID(attestation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attestation_id (not UUID)")

    row = await crud_attestation.get_attestation(db, att_uuid)
    if row is None:
        raise HTTPException(status_code=404, detail="Attestation not found")

    bundle = _build_canonical_bundle(row)
    if ZKP_BUNDLE_SIGNING_ENABLED:
        from ..services import attestation_signer
        bundle = attestation_signer.sign_bundle(bundle)
        # Lazy cache: persist the JSON + pubkey_id so subsequent reads can
        # short-circuit. We do NOT cache when signing is disabled (would
        # cache a partial-bundle that doesn't round-trip).
        try:
            import json as _json
            row.bundle_json = _json.dumps(bundle, sort_keys=True, separators=(",", ":"))
            row.signature_pubkey_id = bundle.get("signature_pubkey_id")
            await db.commit()
        except Exception as exc:
            logger.warning(f"[bundle] cache write failed: {exc}")
    return bundle


class VerifyBundleRequest(BaseModel):
    """POST /api/v1/public/attestations/verify-bundle body."""
    bundle: Dict[str, Any]
    issuer_pubkey_b64: Optional[str] = None


@router.get(
    "/{attestation_id}/verify",
    response_model=AttestationReverifyResponse,
    summary="Re-run bb verify against the stored proof bytes (public)",
)
async def reverify_attestation_endpoint(
    attestation_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AttestationReverifyResponse:
    try:
        att_uuid = uuid.UUID(attestation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attestation_id (not UUID)")

    row = await crud_attestation.get_attestation(db, att_uuid)
    if row is None:
        raise HTTPException(status_code=404, detail="Attestation not found")

    # Phase 2 lifecycle gating: revoked/expired rows fail re-verify regardless
    # of the underlying proof bytes. We still attempt a fresh bb verify when
    # bytes are present so the re_verified_at + verify-engine-status are
    # observable for auditors.
    now = datetime.now(timezone.utc)
    is_revoked = bool(getattr(row, "revoked_at", None))
    is_expired = (
        not is_revoked
        and getattr(row, "expires_at", None) is not None
        and row.expires_at < now
    )

    if not row.proof_b64:
        # Option B / pre-Phase-1 rows carry no proof bytes, so there is
        # nothing to re-verify: say so instead of echoing the stored flag.
        engine_verified = False
        engine_failure = "no proof bytes stored: nothing to re-verify"
    else:
        proof_data = {"proof_bytes": row.proof_b64, "format": "ultra_honk"}
        try:
            # A v2 row's reference must still name the agent that submitted it.
            reference_input = _zkp.REFERENCE_INPUTS.get(_zkp.canonical_circuit_id(row.circuit_id) or "")
            label = (row.public_inputs or {}).get("reference_label")
            expected = (
                {reference_input: str(_zkp.derive_reference(row.agent_did, label))}
                if reference_input and isinstance(label, str) and label else None
            )
            reverify = await verify_proof_detailed(
                circuit_id=row.circuit_id,
                proof_data=proof_data,
                public_inputs=row.public_inputs or {},
                expected=expected,
            )
            engine_verified = reverify.verified
        except Exception as exc:
            logger.error(f"[reverify] bb verify error for {row.id}: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Re-verify failed: {exc}")
        engine_failure = None if engine_verified else reverify.reason

    # Final verified bit: cryptographic OK AND not revoked AND not expired.
    final_verified = bool(engine_verified) and not is_revoked and not is_expired
    if is_revoked:
        failure_reason = (
            f"attestation revoked at {row.revoked_at.isoformat() if row.revoked_at else '?'}"
            f"{(' — ' + row.revoked_reason) if row.revoked_reason else ''}"
        )
    elif is_expired:
        failure_reason = f"attestation expired at {row.expires_at.isoformat()}"
    else:
        failure_reason = engine_failure

    return AttestationReverifyResponse(
        attestation_id=str(row.id),
        circuit_id=row.circuit_id,
        verified=final_verified,
        re_verified_at=now,
        public_inputs=row.public_inputs or {},
        failure_reason=failure_reason,
        revoked=is_revoked,
        expired=is_expired,
    )


@router.get(
    "/{attestation_id}",
    response_model=AttestationRecord,
    summary="Get a single attestation by id (admin/developer view)",
)
async def get_attestation_endpoint(
    attestation_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Developer, Security(get_current_developer)],
) -> AttestationRecord:
    try:
        att_uuid = uuid.UUID(attestation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attestation_id (not UUID)")

    row = await crud_attestation.get_attestation(db, att_uuid)
    if row is None:
        raise HTTPException(status_code=404, detail="Attestation not found")
    return AttestationRecord.from_orm_row(row)


# ─────────────────────────────────────────────────────────────────────────────
# Circuit Distribution Router
# Provers fetch a circuit's bytecode, source and Nargo.toml here. The
# verification key and the metadata are public as well, so anyone can check
# a proof offline with `bb verify` against the key this registry uses.
# ─────────────────────────────────────────────────────────────────────────────

# The root the verifier reads (CIRCUIT_REGISTRY_PATH, else the image path).
_CIRCUIT_REGISTRY_BASE = _zkp._CIRCUIT_REGISTRY_ROOT / "policies"

_CIRCUIT_PACKAGES: Dict[str, str] = {
    "fairMarkupPolicy": "fair_markup",
    "accurateResourceUsagePolicy": "accurate_resource_usage",
    "fairCrossRegistryFee": "fair_cross_registry_fee",
    "contentSafetyAttestation": "content_safety_attestation",
}


def _circuit_entry(name: str, version: str) -> Dict[str, Any]:
    base = _CIRCUIT_REGISTRY_BASE / name / version
    package = _CIRCUIT_PACKAGES[name]
    entry: Dict[str, Any] = {
        "source": base / "src" / "main.nr",
        "nargo": base / "Nargo.toml",
        "name": package,
    }
    if version == "v1.0.0":
        # Retired: its policy limits are private inputs that nothing binds.
        entry.update(
            status="retired",
            superseded_by=f"{name}/v2.0.0",
            bin=base / "target" / f"{package}.bin",
        )
    else:
        entry.update(
            status="active",
            circuit_json=base / "circuit.json",
            vk=base / "verification_key.bin",
            metadata=base / "metadata.json",
        )
    return entry


_CIRCUIT_FILE_MAP: Dict[str, Dict[str, Any]] = {
    f"{name}/{version}": _circuit_entry(name, version)
    for name in _CIRCUIT_PACKAGES
    for version in ("v2.0.0", "v1.0.0")
}
_ACTIVE_CIRCUIT_IDS = {cid for cid, entry in _CIRCUIT_FILE_MAP.items() if entry["status"] == "active"}

circuits_router = APIRouter(prefix="/api/v1/circuits", tags=["Circuits"])


def _resolve_circuit(circuit_id: str) -> Dict[str, Any]:
    """Look up circuit_id and raise 404 if unknown."""
    entry = _CIRCUIT_FILE_MAP.get(circuit_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Circuit '{circuit_id}' not found. Known circuits: {list(_CIRCUIT_FILE_MAP)}"
        )
    return entry


def _acir_bytes(entry: Dict[str, Any]) -> Optional[bytes]:
    """The compiled ACIR bytecode (gzipped, as bb reads it), or None."""
    if "circuit_json" in entry:
        try:
            artifact = json.loads(entry["circuit_json"].read_text())
            return base64.b64decode(artifact["bytecode"])
        except (OSError, ValueError, KeyError):
            return None
    path: Path = entry["bin"]
    return path.read_bytes() if path.exists() else None


@circuits_router.get(
    "/{circuit_id:path}/acir",
    summary="Download compiled ACIR binary for a circuit",
    description=(
        "Returns the compiled ACIR bytecode (.bin) for the requested circuit, "
        "the input `bb prove` takes. v2.0.0 circuits carry it in their tracked "
        "circuit.json, so every image serves it."
    ),
)
async def get_circuit_acir(circuit_id: str) -> Response:
    entry = _resolve_circuit(circuit_id)
    data = _acir_bytes(entry)
    if data is None:
        # §MCPTEST30 (V0525, 2026-10-01): a circuit without compiled bytecode is a missing resource, so 404 naming
        # what the server does serve, never a 500 as if the server had broken. The list says which circuits carry it
        # (`acir_available`). The retired v1 fee and safety circuits were never compiled.
        logger.warning(f"ACIR bytecode not available on this server for '{circuit_id}'")
        raise HTTPException(
            status_code=404,
            detail=(f"Circuit '{circuit_id}' has no compiled ACIR bytecode on this server: its source and Nargo.toml "
                    "are served; compile it with nargo, or ask the operator."))
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{entry["name"]}.bin"'},
    )


@circuits_router.get(
    "/{circuit_id:path}/vk",
    summary="Download the verification key for a circuit",
    description=(
        "The UltraHonk verification key this registry verifies against. Public "
        "by design: with it, an attestation's proof bytes and public inputs, "
        "anyone can run `bb verify` without trusting this registry."
    ),
)
async def get_circuit_vk(circuit_id: str) -> FileResponse:
    entry = _resolve_circuit(circuit_id)
    vk_path = entry.get("vk")
    if vk_path is None or not vk_path.exists():
        hint = f"; it is retired, use {entry['superseded_by']}" if entry["status"] == "retired" else ""
        raise HTTPException(status_code=404, detail=f"Circuit '{circuit_id}' has no published verification key{hint}")
    return FileResponse(path=str(vk_path), media_type="application/octet-stream", filename="verification_key.bin")


@circuits_router.get(
    "/{circuit_id:path}/metadata",
    summary="Circuit statement, inputs, outputs and the policy limits this registry enforces",
)
async def get_circuit_metadata(circuit_id: str) -> Dict[str, Any]:
    entry = _resolve_circuit(circuit_id)
    meta_path = entry.get("metadata")
    if meta_path is None or not meta_path.exists():
        hint = f"; it is retired, use {entry['superseded_by']}" if entry["status"] == "retired" else ""
        raise HTTPException(status_code=404, detail=f"Circuit '{circuit_id}' has no published metadata{hint}")
    meta = json.loads(meta_path.read_text())
    meta["policy_in_force"] = (_zkp.circuit_spec(circuit_id) or {}).get("policy", {})
    return meta


@circuits_router.get(
    "/{circuit_id:path}/source",
    summary="Download Noir circuit source (main.nr)",
    description=(
        "Returns the Noir source code for the circuit. Agents use this to reconstruct "
        "a minimal Nargo project directory so that nargo execute can generate a witness "
        "from the agent's own private inputs."
    ),
    response_class=PlainTextResponse,
)
async def get_circuit_source(circuit_id: str) -> PlainTextResponse:
    entry = _resolve_circuit(circuit_id)
    source_path: Path = entry["source"]
    if not source_path.exists():
        logger.error(f"Circuit source missing on disk: {source_path}")
        raise HTTPException(status_code=500, detail="Circuit source not found on server.")
    logger.info(f"Serving Noir source for circuit '{circuit_id}': {source_path}")
    return PlainTextResponse(content=source_path.read_text(encoding="utf-8"))


@circuits_router.get(
    "/{circuit_id:path}/nargo-toml",
    summary="Download Nargo.toml for a circuit",
    response_class=PlainTextResponse,
)
async def get_circuit_nargo_toml(circuit_id: str) -> PlainTextResponse:
    entry = _resolve_circuit(circuit_id)
    nargo_path: Path = entry["nargo"]
    if not nargo_path.exists():
        logger.error(f"Nargo.toml missing on disk: {nargo_path}")
        raise HTTPException(status_code=500, detail="Nargo.toml not found on server.")
    return PlainTextResponse(content=nargo_path.read_text(encoding="utf-8"))


@circuits_router.get(
    "/",
    summary="List available circuits",
)
async def list_circuits():
    """The circuits this registry serves: v2.0.0 active, v1.0.0 retired."""
    circuits = []
    for cid, entry in _CIRCUIT_FILE_MAP.items():
        item: Dict[str, Any] = {
            "circuit_id": cid,
            "name": entry["name"],
            "status": entry["status"],
            "acir_url": f"/api/v1/circuits/{cid}/acir",
            "acir_available": _acir_bytes(entry) is not None,   # §MCPTEST30 (V0525): the url answers 404 when false
            "source_url": f"/api/v1/circuits/{cid}/source",
            "nargo_toml_url": f"/api/v1/circuits/{cid}/nargo-toml",
        }
        if entry["status"] == "active":
            spec = _zkp.circuit_spec(cid) or {}
            item.update(
                vk_url=f"/api/v1/circuits/{cid}/vk",
                metadata_url=f"/api/v1/circuits/{cid}/metadata",
                public_inputs=spec.get("public_inputs", []),
                public_outputs=spec.get("public_outputs", []),
                policy=spec.get("policy", {}),
            )
        else:
            item["superseded_by"] = entry["superseded_by"]
        circuits.append(item)
    return {"circuits": circuits}


# ─── Phase 4: public verify-bundle router ─────────────────────────────────
# `/api/v1/public/attestations/verify-bundle` — accepts a posted bundle and
# returns a verdict. No auth: bundles are self-contained, anyone can verify.
public_attestations_router = APIRouter(
    prefix="/api/v1/public/attestations",
    tags=["Attestations"],
)


@public_attestations_router.post("/verify-bundle")
async def public_verify_bundle(req_body: "VerifyBundleRequest"):
    """Verify a signed attestation bundle.

    Caller may either:
      - post the bundle alone (signature is verified against the LOCAL
        registry's signing pubkey, useful for round-trip-on-the-issuer testing)
      - post the bundle + an `issuer_pubkey_b64` (the verifier's view of
        which key signed the bundle, required for cross-registry verify).

    Returns:
      `verified`: bool
      `reason`: str (verdict reason, ok or specific failure)
      `bundle_summary`: small projection of the verified fields
    """
    if not ZKP_PHASE_4_ENABLED:
        raise HTTPException(status_code=503, detail="ZKP_PHASE_4_ENABLED=false")

    bundle = dict(req_body.bundle or {})
    if not bundle:
        raise HTTPException(status_code=400, detail="missing bundle in body")

    from ..services import attestation_signer
    sig_ok, reason = attestation_signer.verify_bundle_signature(
        bundle, issuer_pubkey_b64=req_body.issuer_pubkey_b64,
    )

    return {
        "verified": bool(sig_ok),
        "reason": reason,
        "bundle_summary": {
            "attestation_id": bundle.get("attestation_id"),
            "agent_did": bundle.get("agent_did"),
            "circuit_id": bundle.get("circuit_id"),
            "issuer_registry": bundle.get("issuer_registry"),
            "valid_until": bundle.get("valid_until"),
            "revoked": bundle.get("revoked", False),
            "signature_pubkey_id": bundle.get("signature_pubkey_id"),
        },
    }


# ─── Phase 1: agent-profile augmentation router ──────────────────────────
# Public endpoint — anyone can list a given agent's verified ZKP attestations.
# Mounted from main.py alongside the main attestations router.
attestations_by_agent_router = APIRouter(
    prefix="/api/v1/agents",
    tags=["Attestations"],
)


@attestations_by_agent_router.get(
    "/by-did/{agent_did:path}/attestations",
    response_model=AttestationListResponse,
    summary="List attestations for a given agent DID (public)",
)
async def list_attestations_by_did(
    agent_did: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    circuit_id: Optional[str] = Query(default=None),
    verified: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AttestationListResponse:
    rows = await crud_attestation.list_attestations(
        db,
        agent_did=agent_did,
        circuit_id=circuit_id,
        verified=verified,
        limit=limit,
        offset=offset,
    )
    total = await crud_attestation.count_attestations(
        db,
        agent_did=agent_did,
        circuit_id=circuit_id,
        verified=verified,
    )
    return AttestationListResponse(
        items=[AttestationRecord.from_orm_row(r) for r in rows],
        count=total,
        limit=limit,
        offset=offset,
    )


@attestations_by_agent_router.get(
    "/by-did/{agent_did:path}/attestation-schedules",
    response_model=ScheduleListResponse,
    summary="List a given agent's attestation schedules (public)",
)
async def list_attestation_schedules_by_did(
    agent_did: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleListResponse:
    rows = await crud_attestation.list_schedules(db, agent_did=agent_did)
    return ScheduleListResponse(
        items=[ScheduleRecord.from_orm_row(r) for r in rows],
        count=len(rows),
    )
