"""Federation License Self-Serve Rotation (BL-1, 2026-05-11).

Allows an operator to rotate their OWN federation license without admin
intervention. The caller proves ownership by sending the current
`X-Federation-License: tp_fed_<...>` header — mode 3 in
core/federation_auth.py.

Rotation model: UPDATE federation_licenses row in place.
  - operator_did has UNIQUE constraint, so we cannot have two rows for the
    same operator. The row's secret material (license_key_hash + prefix) is
    rewritten atomically. The federation_license_rotations table holds the
    audit trail (one row per rotation event, idempotency-keyed).

Idempotency:
  - X-Idempotency-Key header (16-64 chars) UNIQUE on federation_license_rotations.
  - 24h TTL on the row.
  - Replay with same key returns the same plain key without re-rotating.
  - Replay with expired key returns 410 Gone.

Master kill-switch env: FEDERATION_LICENSE_ROTATE_SELF_ENABLED (default false).
Production stays false until §13 burn-in passes; sandbox-A flips true.

Strategy: PRODUCTION_DOCS/ROADMAP/Operator_CLI_Strategy.md §3.2.9 + §7.2.1.
"""

import datetime
import hashlib
import logging
import os
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.core.federation_auth import get_federation_identity

logger = logging.getLogger(__name__)


# §FEDLICENCE improvement 11 (2026-09-28): a rotation keeps the NEW key in plain text so a client that lost the response can
# replay its idempotency key within 24 h and receive the same key (without that, the old key is dead and the new one
# unknown). The column's own comment promised it was "cleared at returned-state"; nothing ever cleared it, so every
# rotation's plain key stayed at rest for good. A replay after the window already answers 410, so a key whose window has
# closed is cleared: at the start of every rotation and once per license_drift_monitor cycle.
def expired_rotation_key_sweep(now: datetime.datetime):
    """The UPDATE that clears the plain key of every rotation whose 24 h replay window has closed."""
    return (update(models.FederationLicenseRotation)
            .where(models.FederationLicenseRotation.expires_at <= now,
                   models.FederationLicenseRotation.new_license_key.is_not(None))
            .values(new_license_key=None)
            .execution_options(synchronize_session=False))


async def clear_expired_rotation_keys(db: AsyncSession, now: Optional[datetime.datetime] = None) -> int:
    """Clear, and COMMIT, every expired rotation's plain key; returns how many rows it cleared."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    res = await db.execute(expired_rotation_key_sweep(now))
    n = int(res.rowcount or 0)
    if n:
        await db.commit()
        logger.info(f"[License Rotate-Self] cleared the plain key of {n} rotation(s) past their replay window")
    return n


# ── Kill switch ─────────────────────────────────────────────
def _self_serve_enabled() -> bool:
    """Master kill switch. Defaults FALSE (production posture)."""
    return os.getenv("FEDERATION_LICENSE_ROTATE_SELF_ENABLED", "false").lower() in (
        "true", "1", "yes",
    )


# ── Schemas ─────────────────────────────────────────────────
class RotateSelfRequest(BaseModel):
    reason: str = Field(
        ...,
        description="Why rotation is requested. One of: leak_suspected, scheduled_rotation, post_incident.",
        min_length=1, max_length=64,
    )


class RotateSelfResponse(BaseModel):
    rotation_id: str = Field(..., description="Idempotency-tracked rotation record id")
    license_id: str = Field(..., description="ID of the license row (unchanged across rotations)")
    license_key: str = Field(..., description="PLAIN key — shown ONCE per idempotency-key, cannot be retrieved later")
    operator_did: str = Field(..., description="Operator DID (unchanged from prior license)")
    operator_name: str = Field(..., description="Operator name (unchanged)")
    rotated_at: datetime.datetime = Field(..., description="When the rotation was committed")
    idempotent_replay: bool = Field(False, description="True if this is a retry of a prior call")


# ── Router ──────────────────────────────────────────────────
router = APIRouter(
    prefix="/api/v1/federation/license",
    tags=["Federation License (Self-Serve)"],
)


# ── Helpers ─────────────────────────────────────────────────
_VALID_REASONS = {"leak_suspected", "scheduled_rotation", "post_incident"}


def _generate_license_key() -> tuple[str, str, str]:
    """Generate a new federation license key.

    Returns (plain_key, sha256_hex, prefix_12). Format matches existing
    federation_licenses.py:_generate_federation_license_key() for parity.
    """
    plain = f"tp_fed_{secrets.token_hex(32)}"
    return plain, hashlib.sha256(plain.encode()).hexdigest(), plain[:12]


async def _resolve_caller_license(
    db: AsyncSession, license_key: str
) -> models.FederationLicense:
    """Resolve the caller's license row by SHA-256 hash of the presented key.

    Raises 401 if not found, 403 if not active.
    """
    key_hash = hashlib.sha256(license_key.encode()).hexdigest()
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.license_key_hash == key_hash
        )
    )
    lic = result.scalar_one_or_none()
    if not lic:
        raise HTTPException(status_code=401, detail="Federation license not recognised")
    if lic.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"License is not active (status={lic.status}); contact support to reinstate.",
        )
    return lic


# ── Endpoint ────────────────────────────────────────────────
@router.post(
    "/rotate-self",
    response_model=RotateSelfResponse,
    status_code=status.HTTP_200_OK,
    summary="Self-Serve Federation License Rotation",
)
async def rotate_self(
    body: RotateSelfRequest,
    request: Request,
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
    x_federation_license: Optional[str] = Header(None, alias="X-Federation-License"),
    db: AsyncSession = Depends(get_db),
) -> RotateSelfResponse:
    """Rotate the federation license that authenticated this request.

    Auth model (custom: it does NOT use the get_federation_identity dependency, because
    idempotent replay must accept the OLD key, which would fail the standard
    federation_auth check after rotation):

      Path A, a fresh rotation (no prior rotation row for this idem key):
        Caller MUST present the CURRENT active license key via
        X-Federation-License. Hash is looked up in federation_licenses table.

      Path B, an idempotent replay (a prior rotation row exists):
        Caller MUST present the SAME key they used originally (the pre-rotation
        key). Hash is looked up in `rotation.prev_license_key_hash`.

    Idempotent on X-Idempotency-Key (24h TTL). Replay returns the cached plain
    key from the original rotation.
    """
    # Hard gate: kill switch
    if not _self_serve_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Self-serve license rotation is disabled on this registry. "
                "Set FEDERATION_LICENSE_ROTATE_SELF_ENABLED=true to enable."
            ),
        )

    # Validate reason whitelist
    if body.reason not in _VALID_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid reason. Must be one of: {sorted(_VALID_REASONS)}",
        )

    # X-Federation-License header is required (custom auth — no mTLS-only path)
    if not x_federation_license:
        raise HTTPException(
            status_code=400,
            detail="X-Federation-License header required for self-serve rotation",
        )

    # Idempotency-key length sanity
    if len(x_idempotency_key) < 16 or len(x_idempotency_key) > 64:
        raise HTTPException(
            status_code=400,
            detail="X-Idempotency-Key must be 16-64 chars",
        )

    caller_key_hash = hashlib.sha256(x_federation_license.encode()).hexdigest()
    now = datetime.datetime.now(datetime.timezone.utc)
    await clear_expired_rotation_keys(db, now)   # §FEDLICENCE improvement 11: no plain key outlives its replay window

    # ── IDEMPOTENT REPLAY CHECK ────────────────────────────
    existing = await db.execute(
        select(models.FederationLicenseRotation).where(
            models.FederationLicenseRotation.idempotency_key == x_idempotency_key
        )
    )
    rot = existing.scalar_one_or_none()

    if rot is not None:
        # TTL check
        if rot.expires_at <= now:
            raise HTTPException(
                status_code=410,
                detail="Idempotency key expired (24h TTL). Request a fresh idempotency key.",
            )
        # Path B auth: caller must present the OLD key (same one that
        # initiated the rotation). Compare hash against prev_license_key_hash.
        if rot.prev_license_key_hash and rot.prev_license_key_hash != caller_key_hash:
            # Or — the caller might be presenting the NEW key (also valid;
            # they have legitimate access). Look up by current hash to confirm
            # operator identity.
            cur_lic = await db.execute(
                select(models.FederationLicense).where(
                    models.FederationLicense.license_key_hash == caller_key_hash,
                    models.FederationLicense.id == rot.caller_license_id,
                )
            )
            if not cur_lic.scalar_one_or_none():
                raise HTTPException(
                    status_code=403,
                    detail="Idempotency-key was created by a different license holder.",
                )

        # Resume: return the same plain key (returned-state means rotation
        # is complete; the new_license_key field holds the once-per-key cache)
        if rot.status == "returned" and rot.new_license_key:
            # Fetch the now-rotated license row for operator_did / operator_name
            lic_row = await db.get(models.FederationLicense, rot.caller_license_id)
            return RotateSelfResponse(
                rotation_id=rot.id,
                license_id=rot.caller_license_id,
                license_key=rot.new_license_key,
                operator_did=lic_row.operator_did if lic_row else "",
                operator_name=lic_row.operator_name if lic_row else "",
                rotated_at=rot.returned_at or rot.committed_at or now,
                idempotent_replay=True,
            )

        # Unexpected partial state — shouldn't happen with the atomic flow
        # below, but kept for forward compatibility / safety.
        raise HTTPException(
            status_code=500,
            detail=f"Rotation row in unexpected state: {rot.status}",
        )

    # ── PATH A: FRESH ROTATION ─────────────────────────────
    # Caller must present the CURRENT active key.
    caller_lic = await _resolve_caller_license(db, x_federation_license)
    operator_name = caller_lic.operator_name
    operator_did = caller_lic.operator_did

    # Fresh rotation: generate new key, audit-trail row, atomic UPDATE.
    plain_key, new_hash, new_prefix = _generate_license_key()
    rotation_id = str(uuid.uuid4())
    prev_hash = caller_lic.license_key_hash  # snapshot BEFORE we mutate it

    rot = models.FederationLicenseRotation(
        id=rotation_id,
        idempotency_key=x_idempotency_key,
        caller_license_id=caller_lic.id,
        prev_license_key_hash=prev_hash,
        new_license_id=caller_lic.id,  # update-in-place: same row
        status="returned",
        reason=body.reason,
        new_license_key=plain_key,
        committed_at=now,
        returned_at=now,
        expires_at=now + datetime.timedelta(hours=24),
    )
    db.add(rot)

    # Rotation: UPDATE the existing row in place. operator_did + operator_name
    # stay the same; only secret material rotates. last_seen_at is reset; the
    # event_count counter is preserved (rotation doesn't reset usage history).
    caller_lic.license_key_hash = new_hash
    caller_lic.license_key_prefix = new_prefix
    caller_lic.last_seen_at = now
    # Note: status stays 'active'; we do NOT flip to revoked because revoked
    # means "this operator is excluded from federation." Rotation is a
    # secret-material change, not a status change.

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(f"[License Rotate-Self] Atomic commit failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal commit failure — rotation aborted. Old license still active. Detail: {str(exc)[:200]}",
        )

    await db.refresh(caller_lic)
    logger.info(
        f"[License Rotate-Self] OK: operator={operator_name} did={operator_did} "
        f"license_id={caller_lic.id} reason={body.reason} rotation_id={rotation_id}"
    )

    # CRITICAL: sync the new hash to EventStore's federation_operators projection
    # IMMEDIATELY. Without this, the operator's NEXT event write via X-Federation-License
    # fails authentication at EventStore (which independently checks license_key_hash
    # against its own federation_operators table per events.py:152-178). Mirrors the
    # call sites in routers/federation_licenses.py:327 (generate) + :457 (revoke).
    #
    # Best-effort — failure logs but does NOT roll back the registry-side rotation.
    # If sync fails, the hourly `license_drift_monitor` background task catches it,
    # and the operator's next federation call against mainframe still authenticates
    # via the registry-side hash (which IS updated).
    try:
        from agentvault_registry.routers.federation_licenses import _sync_license_to_eventstore
        await _sync_license_to_eventstore(
            license_id=caller_lic.id,
            operator_name=operator_name,
            license_key_hash=new_hash,
            op_status="active",
            max_events_per_minute=caller_lic.max_events_per_minute,
        )
        logger.info(
            f"[License Rotate-Self] EventStore federation_operators sync OK: "
            f"license_id={caller_lic.id}"
        )
    except Exception as exc:
        # Don't fail the rotation if EventStore is unreachable — the drift_monitor
        # background task will eventually reconcile (hourly). But log loudly.
        logger.error(
            f"[License Rotate-Self] EventStore sync FAILED for license_id={caller_lic.id}: {exc}. "
            f"Registry-side rotation succeeded; EventStore federation_operators row still "
            f"has the OLD hash. Operator's event writes via license-key fallback will "
            f"reject until license_drift_monitor reconciles (≤ 1h) OR a manual "
            f"_sync_license_to_eventstore call is made."
        )

    return RotateSelfResponse(
        rotation_id=rotation_id,
        license_id=caller_lic.id,
        license_key=plain_key,
        operator_did=operator_did,
        operator_name=operator_name,
        rotated_at=now,
        idempotent_replay=False,
    )
