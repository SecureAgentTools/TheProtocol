"""SF-5 WS3.5: Admin CRUD for federation_operators.

Until now, `federation_operators` rows were populated only by direct DB
inserts or as a side-effect of event-auth validation. That meant cross-frame
votes from a new frame's agents wouldn't weight correctly until someone ran
SQL manually.

These endpoints let the registry's WS3 approval flow auto-upsert an operator
row for each federated frame, and let admin tools (FrameManagement.vue)
list/suspend/activate rows without shell access.

Auth: §pass71.3 (2026-05-25) — uses `verify_event_auth` (mTLS / X-Internal-Key
/ X-Federation-License), mirroring the §pass71.2 widening on /api/v1/events/
and /api/v1/system/lockdown. The original strict `verify_internal_key` local
helper became unreachable through the canonical HTTPS path the moment the
nginx-event-store sidecar started stripping X-Internal-Key (§pass69 doctrine:
"mTLS is the authority"). Live probe pre-fix returned HTTP 422 `Field required`
on every endpoint here through the sidecar.
"""
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..models.federation_operator import FederationOperator
# §pass71.3 — single canonical auth helper; absorbs the three accepted modes
# (mTLS SVID forwarded by nginx-event-store as X-SSL-Client-S-DN / -Cert,
# X-Internal-Key for callers that bypass the sidecar, X-Federation-License
# for federated peers). The module-local _verify_internal_key helper that
# previously lived here was removed in §pass71.3 so the strict-header
# pattern can't be accidentally re-introduced.
from .events import require_origin_auth, verify_event_auth
from ..es_auth import NO_RECORD_TRUST
# §SOVKIT T2 (2026-09-14): changes need this frame's own services (require_origin_auth); reads stay on
# verify_event_auth, so a peer frame's replicator and this frame's operators can still read.

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/federation-operators", tags=["SF-5 Federation Operators"])

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


# ─── Schemas ───────────────────────────────────────────────────────

class FederationOperatorRegister(BaseModel):
    spiffe_id: str = Field(..., min_length=8, max_length=255,
                            description="spiffe://<trust_domain> (or bare trust_domain, auto-prefixed)")
    operator_name: str = Field(..., min_length=1, max_length=200)
    license_key_hash: Optional[str] = Field(
        None, max_length=64,
        description="Optional SHA-256 hex of the operator's federation license key. "
                    "Synthesized from spiffe_id if omitted (frames don't carry license keys).",
    )
    # SEC-20: the trust value the frame's registry derived for this peer (frame invitation approve, resync). Omitted: a
    # new record starts at es_auth.NO_RECORD_TRUST (the derivation with no record) and an existing one keeps its value.
    bayesian_discount: Optional[float] = Field(None, ge=0.1, le=1.0)


class FederationOperatorRead(BaseModel):
    id: str
    operator_name: str
    spiffe_id: Optional[str] = None
    license_key_hash: str
    status: str
    max_events_per_minute: Optional[int] = None
    event_count: Optional[int] = None
    last_event_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    bayesian_discount: float = 1.0

    class Config:
        from_attributes = True


# ─── Helpers ───────────────────────────────────────────────────────

def _normalize_spiffe_id(s: str) -> str:
    s = s.strip()
    if not s.startswith("spiffe://"):
        s = f"spiffe://{s}"
    return s.lower()


def _synthetic_license_key_hash(spiffe_id: str) -> str:
    """Frame operators don't carry federation license keys. Derive a stable
    hash from the SPIFFE ID so the NOT NULL + UNIQUE constraints on
    license_key_hash are satisfied."""
    return hashlib.sha256(f"frame-synthetic-{spiffe_id}".encode()).hexdigest()


# ─── Endpoints ─────────────────────────────────────────────────────

@router.post("", response_model=FederationOperatorRead, dependencies=[Depends(require_origin_auth)])
async def register_federation_operator(
    payload: FederationOperatorRegister,
    db: AsyncSession = Depends(get_db),
):
    """UPSERT a federation operator. Idempotent on spiffe_id.

    Re-registering a previously suspended/revoked operator flips status='active'
    and preserves event_count / last_event_at.
    """
    spiffe = _normalize_spiffe_id(payload.spiffe_id)
    license_hash = payload.license_key_hash or _synthetic_license_key_hash(spiffe)

    existing = (await db.execute(
        select(FederationOperator).where(FederationOperator.spiffe_id == spiffe)
    )).scalar_one_or_none()

    if existing is None:
        row = FederationOperator(
            id=str(uuid.uuid4()),
            operator_name=payload.operator_name[:200],
            license_key_hash=license_hash[:64],
            spiffe_id=spiffe,
            status="active",
            max_events_per_minute=1000,
            event_count=0,
            bayesian_discount=(payload.bayesian_discount if payload.bayesian_discount is not None
                               else NO_RECORD_TRUST),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info(f"[admin_fed_op] INSERT {spiffe} ({payload.operator_name})")
        return row

    # Existing — flip to active + update editable fields
    existing.operator_name = payload.operator_name[:200]
    existing.status = "active"
    if payload.bayesian_discount is not None:
        existing.bayesian_discount = payload.bayesian_discount
    await db.commit()
    await db.refresh(existing)
    logger.info(f"[admin_fed_op] UPDATE {spiffe} → active")
    return existing


@router.get("", dependencies=[Depends(verify_event_auth)])
async def list_federation_operators(
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(FederationOperator).order_by(FederationOperator.created_at.desc())
    )).scalars().all()
    return {
        "operators": [FederationOperatorRead.model_validate(r).model_dump(mode="json") for r in rows],
        "count": len(rows),
    }


@router.get("/by-spiffe/{spiffe_id:path}", response_model=FederationOperatorRead, dependencies=[Depends(verify_event_auth)])
async def get_by_spiffe(
    spiffe_id: str,
    db: AsyncSession = Depends(get_db),
):
    spiffe = _normalize_spiffe_id(spiffe_id)
    row = (await db.execute(
        select(FederationOperator).where(FederationOperator.spiffe_id == spiffe)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"No federation operator for {spiffe}")
    return row


@router.post("/{operator_id}/suspend", dependencies=[Depends(require_origin_auth)])
async def suspend_federation_operator(
    operator_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(FederationOperator).where(FederationOperator.id == operator_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Federation operator '{operator_id}' not found")
    row.status = "suspended"
    await db.commit()
    logger.info(f"[admin_fed_op] SUSPEND {operator_id} ({row.spiffe_id})")
    return {"status": "suspended", "id": operator_id, "spiffe_id": row.spiffe_id}


@router.post("/{operator_id}/activate", dependencies=[Depends(require_origin_auth)])
async def activate_federation_operator(
    operator_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(FederationOperator).where(FederationOperator.id == operator_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Federation operator '{operator_id}' not found")
    row.status = "active"
    await db.commit()
    logger.info(f"[admin_fed_op] ACTIVATE {operator_id} ({row.spiffe_id})")
    return {"status": "active", "id": operator_id, "spiffe_id": row.spiffe_id}


# SEC-20 (2026-10-17, his word: the trust value "has to be dervied in a meaningful way. setting it manually doesnt make
# sense to me"): there is no manual override of bayesian_discount. This frame's registry derives it from what it
# measured of each peer and writes it with the upsert above and its trust sync (/api/v1/events/operators/sync).
