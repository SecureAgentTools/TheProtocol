"""
EigenTrust++ reputation API — Phase 2

Router prefix: /api/v1/reputation
Auth: Developer JWT for GET endpoints, Admin JWT for trigger POST.

Routes:
  GET  /{did}/trust-score         — GlobalTrustVector for agent
  GET  /{did}/trust-graph         — LocalTrustScore relationships
  GET  /{did}/volume-profile      — Transaction volume stats for agent
  GET  /computation-status        — Last epoch metadata
  POST /admin/trigger-computation — Force immediate epoch (admin)
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Security
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from ..database import get_db
from ..models import LocalTrustScore, GlobalTrustVector
from ..security import get_current_developer, require_admin_flag
from ..models import Developer

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/reputation",
    tags=["EigenTrust++ Reputation"],
)


# --- Response schemas ---

class TrustScoreResponse(BaseModel):
    did: str
    global_trust: float
    similarity_score: float
    integer_projection: int
    epoch: int
    computed_at: str


class TrustEdgeResponse(BaseModel):
    from_did: str
    to_did: str
    satisfactory: int
    unsatisfactory: int
    local_trust: float
    normalized: float
    # float, not int: the column is NUMERIC(36,18) since mig 0171, and an int here
    # would coerce every sub-unit volume back to 0 in the API response.
    tx_volume: float
    last_updated: str


class TrustGraphResponse(BaseModel):
    relationships: list[TrustEdgeResponse]
    total: int
    page: int
    per_page: int


class ComputationStatusResponse(BaseModel):
    epoch: Optional[int]
    computed_at: Optional[str]
    agents_computed: Optional[int]
    computation_time_ms: Optional[int]
    next_scheduled_at: Optional[str]
    last_epoch_converged: Optional[bool]
    # §DOCSFIX D6-604: where the two fields above come from. shared: Redis, the same on every worker; process: this
    # worker's memory (a registry without Redis), null unless this worker ran the epoch.
    state_store: Optional[str] = None


class TriggerResponse(BaseModel):
    status: str
    message: str


# --- Endpoints ---

@router.get(
    "/computation-status",
    response_model=ComputationStatusResponse,
    summary="EigenTrust++ computation status",
)
async def get_computation_status(
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer),
):
    """
    Returns metadata about the most recent EigenTrust++ epoch.
    """
    from ..services.eigentrust_engine import get_last_epoch_result, get_next_scheduled_at, state_store

    last = await get_last_epoch_result()
    next_at = await get_next_scheduled_at()

    # Also query the DB for the latest epoch row directly
    max_epoch_result = await db.execute(
        select(func.max(GlobalTrustVector.epoch))
    )
    max_epoch = max_epoch_result.scalar()

    count_result = await db.execute(
        select(func.count()).select_from(GlobalTrustVector)
    )
    agent_count = count_result.scalar()

    # Get latest computed_at and computation_time_ms from DB
    db_row = None
    if max_epoch is not None:
        db_rows = await db.execute(
            select(GlobalTrustVector)
            .where(GlobalTrustVector.epoch == max_epoch)
            .limit(1)
        )
        db_row = db_rows.scalar_one_or_none()

    return ComputationStatusResponse(
        epoch=max_epoch,
        computed_at=db_row.computed_at.isoformat() if db_row else None,
        agents_computed=agent_count,
        computation_time_ms=db_row.computation_time_ms if db_row else None,
        next_scheduled_at=next_at.isoformat() if next_at else None,
        last_epoch_converged=last.get("converged") if last else None,
        state_store=await state_store(),
    )


@router.get(
    "/{did}/trust-score",
    response_model=TrustScoreResponse,
    summary="EigenTrust++ score for agent",
)
async def get_trust_score(
    did: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer),
):
    """
    Returns the latest GlobalTrustVector for the given agent DID.
    404 if no epoch has been computed for this agent yet.
    """
    result = await db.execute(
        select(GlobalTrustVector).where(GlobalTrustVector.agent_did == did)
    )
    row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No EigenTrust++ score computed for {did}. "
                   "Trigger a computation via POST /api/v1/reputation/admin/trigger-computation",
        )

    # §DOCSFIX D6-602 (2026-10-16): the integer the engine published, by the engine's own projection and the
    # epoch's own floor (its smallest positive value). This route answered linear x1000 whatever
    # EIGENTRUST_PROJECTION said, so under `log` it disagreed with the agent's reputation_score.
    from ..services import eigentrust_engine as _et
    log_floor = 0.0
    if _et.PROJECTION_MODE == "log":
        log_floor = (await db.execute(
            select(func.min(GlobalTrustVector.global_trust)).where(
                GlobalTrustVector.epoch == row.epoch, GlobalTrustVector.global_trust > 0)
        )).scalar() or 0.0
    return TrustScoreResponse(
        did=row.agent_did,
        global_trust=round(row.global_trust, 6),
        similarity_score=round(row.similarity_score, 4),
        integer_projection=_et._project(float(row.global_trust), float(log_floor)),
        epoch=row.epoch,
        computed_at=row.computed_at.isoformat(),
    )


@router.get(
    "/{did}/trust-graph",
    response_model=TrustGraphResponse,
    summary="Local trust relationships for agent",
)
async def get_trust_graph(
    did: str,
    direction: str = Query("both", pattern="^(incoming|outgoing|both)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer),
):
    """
    Returns LocalTrustScore rows for the given agent.
    direction: outgoing (from_did=did) | incoming (to_did=did) | both
    Excludes self-loop rows (ZKP attestation signals).
    """
    offset = (page - 1) * per_page

    if direction == "outgoing":
        condition = (LocalTrustScore.from_did == did) & (LocalTrustScore.to_did != did)
    elif direction == "incoming":
        condition = (LocalTrustScore.to_did == did) & (LocalTrustScore.from_did != did)
    else:
        condition = (
            or_(LocalTrustScore.from_did == did, LocalTrustScore.to_did == did)
            & (LocalTrustScore.from_did != LocalTrustScore.to_did)
        )

    count_result = await db.execute(
        select(func.count()).select_from(LocalTrustScore).where(condition)
    )
    total = count_result.scalar()

    rows_result = await db.execute(
        select(LocalTrustScore)
        .where(condition)
        .order_by(LocalTrustScore.last_updated.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = rows_result.scalars().all()

    return TrustGraphResponse(
        relationships=[
            TrustEdgeResponse(
                from_did=r.from_did,
                to_did=r.to_did,
                satisfactory=r.satisfactory,
                unsatisfactory=r.unsatisfactory,
                local_trust=round(r.local_trust, 4),
                normalized=round(r.normalized, 6),
                tx_volume=r.tx_volume,
                last_updated=r.last_updated.isoformat(),
            )
            for r in rows
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/{did}/volume-profile",
    response_model=dict,
    summary="Transaction volume profile for agent",
)
async def get_volume_profile(
    did: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer),
):
    """
    Returns transaction volume statistics for the given agent DID.
    Data sourced from local_trust_scores.tx_volume.
    Response: { total_volume, unique_peers, avg_per_peer, volume_rank }
    """
    from sqlalchemy import or_

    # Total volume (sum of tx_volume for all pairs involving this agent)
    vol_result = await db.execute(
        select(func.sum(LocalTrustScore.tx_volume)).where(
            or_(LocalTrustScore.from_did == did, LocalTrustScore.to_did == did)
        )
    )
    total_volume = vol_result.scalar() or 0

    # Unique peer count
    peers_from = await db.execute(
        select(func.count(LocalTrustScore.to_did.distinct())).where(
            LocalTrustScore.from_did == did
        )
    )
    peers_to = await db.execute(
        select(func.count(LocalTrustScore.from_did.distinct())).where(
            LocalTrustScore.to_did == did
        )
    )
    unique_peers = (peers_from.scalar() or 0) + (peers_to.scalar() or 0)

    avg_per_peer = round(total_volume / unique_peers, 2) if unique_peers > 0 else 0.0

    # Volume rank: count how many agents have higher total volume (approximate)
    # Get all agents' total volume and find rank
    volume_rank = None
    try:
        all_vols = await db.execute(
            select(
                LocalTrustScore.from_did,
                func.sum(LocalTrustScore.tx_volume).label("vol")
            ).group_by(LocalTrustScore.from_did)
        )
        rows = all_vols.all()
        sorted_vols = sorted([r.vol for r in rows], reverse=True)
        if sorted_vols:
            higher_count = sum(1 for v in sorted_vols if v > total_volume)
            volume_rank = higher_count + 1
    except Exception:
        pass

    return {
        "did": did,
        "total_volume": total_volume,
        "unique_peers": unique_peers,
        "avg_per_peer": avg_per_peer,
        "volume_rank": volume_rank,
    }


@router.post(
    "/admin/trigger-computation",
    response_model=TriggerResponse,
    summary="Force immediate EigenTrust++ epoch (admin)",
)
async def trigger_computation(
    current_developer: Developer = Depends(require_admin_flag("admin_platform")),
):
    """
    Triggers an immediate EigenTrust++ epoch outside the normal schedule.
    Runs in background — returns immediately.
    Requires admin_platform (or legacy is_admin super-flag).
    """
    # RBAC §65 (2026-05-08): migrated from manual `is_admin` check to
    # `require_admin_flag("admin_platform")`. EigenTrust epoch trigger is
    # infrastructure/meta-admin (matches the admin_platform blast-radius
    # cheatsheet). Super-flag still passes via legacy fallback.
    from ..background_tasks.eigentrust_worker import trigger_manual_epoch
    asyncio.create_task(trigger_manual_epoch())

    return TriggerResponse(
        status="started",
        message="EigenTrust++ epoch triggered. Check /computation-status for results.",
    )


# ---------------------------------------------------------------------------
# SF-5D: Cross-Frame Reputation (foreign EigenTrust scores)
# ---------------------------------------------------------------------------

@router.get("/cross-frame", summary="Cross-frame reputation scores")
async def get_cross_frame_reputation():
    """
    SF-5D: Returns foreign EigenTrust reputation scores from other frames.

    These scores are fetched from the EventStore's cross-frame-reputation
    projection (built on ReputationChanged events replicated via SF-4).
    Updated each EigenTrust epoch (hourly).
    """
    from ..services.eigentrust_engine import get_all_foreign_reputation, state_store
    foreign = await get_all_foreign_reputation()
    return {
        "foreign_reputation": list(foreign.values()),
        "agent_count": len(foreign),
        "status": "OK",
        "store": await state_store(),   # §DOCSFIX D6-604: shared (Redis, every worker) or process (this worker only)
    }
