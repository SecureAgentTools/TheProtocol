"""
Admin Dashboard Router
---------------------
Provides administrative endpoints for system oversight and monitoring.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from agentvault_registry.database import get_db
from agentvault_registry.models import Developer, Agent, BootstrapToken, Dispute
from agentvault_registry.services.developer_population import a_developer_of_this_registry
from agentvault_registry import security
from agentvault_registry.schemas import DeveloperRead
from agentvault_registry.crud import crud_disputes
from agentvault_registry.core.log_identity import email_for_log   # V0653 (am) item 7: no address in a log

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin",
)


# §pass58 PR-6b: per-endpoint tags reflect the feature area; RBAC sub-flag in docstring/Depends.
@router.get("/dashboard", response_model=Dict[str, Any], tags=["Admin — Platform"])
async def get_admin_dashboard(
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """
    Get administrative dashboard statistics.
    
    Requires admin authentication.
    
    Returns:
        - developer_count: Total number of registered developers
        - agent_count: Total number of registered agents
        - bootstrap_tokens_issued: Total number of bootstrap tokens created
        - active_developers: Number of verified developers
        - active_agents: Number of active agents
        - tokens_used: Number of bootstrap tokens that have been used
        - tokens_expired: Number of expired bootstrap tokens
    """
    logger.info(f"Admin dashboard accessed by: {email_for_log(current_admin.email)}")
    
    try:
        # Get developer statistics
        # §NIGHTLYTRUTH (2026-09-14): both counts exclude SOFT-DELETED developers, the same predicate the
        # admin list applies (`admin_developers.py`: deleted_at IS NULL). Measured on sandbox-A: the
        # dashboard said 633 developers and 633 active while the list held 625, the eight being accounts
        # the tester's own deletion lifecycles had removed; the federation suite's cross-reference row
        # (`dashboard_total_developers_matches_admin_list`) was red on it every night. A deleted account
        # is not a developer of this registry and cannot be an active one.
        # §NIGHTLYTRUTH-2 (2026-10-11): nor federation placeholders (services/developer_population.py): sandbox-A's
        # dashboard said 1,450 while the list held 1,324, the 126 being sandbox-B's placeholders.
        developer_count_stmt = select(func.count()).select_from(Developer).where(
            a_developer_of_this_registry()
        )
        developer_count_result = await db.execute(developer_count_stmt)
        developer_count = developer_count_result.scalar() or 0

        # Get verified developer count
        verified_developers_stmt = select(func.count()).select_from(Developer).where(
            Developer.is_verified == True,
            a_developer_of_this_registry(),
        )
        verified_developers_result = await db.execute(verified_developers_stmt)
        active_developers = verified_developers_result.scalar() or 0
        
        # Get agent statistics
        agent_count_stmt = select(func.count()).select_from(Agent)
        agent_count_result = await db.execute(agent_count_stmt)
        agent_count = agent_count_result.scalar() or 0
        
        # Get active agent count
        active_agents_stmt = select(func.count()).select_from(Agent).where(
            Agent.status == "active"
        )
        active_agents_result = await db.execute(active_agents_stmt)
        active_agents = active_agents_result.scalar() or 0
        
        # Get bootstrap token statistics
        bootstrap_tokens_stmt = select(func.count()).select_from(BootstrapToken)
        bootstrap_tokens_result = await db.execute(bootstrap_tokens_stmt)
        bootstrap_tokens_issued = bootstrap_tokens_result.scalar() or 0
        
        # Get used tokens count
        used_tokens_stmt = select(func.count()).select_from(BootstrapToken).where(
            BootstrapToken.used_at.isnot(None)
        )
        used_tokens_result = await db.execute(used_tokens_stmt)
        tokens_used = used_tokens_result.scalar() or 0
        
        # Get expired tokens count
        current_time = datetime.now(timezone.utc)
        expired_tokens_stmt = select(func.count()).select_from(BootstrapToken).where(
            BootstrapToken.expires_at < current_time,
            BootstrapToken.used_at.is_(None)
        )
        expired_tokens_result = await db.execute(expired_tokens_stmt)
        tokens_expired = expired_tokens_result.scalar() or 0
        
        dashboard_data = {
            "developer_count": developer_count,
            "agent_count": agent_count,
            "bootstrap_tokens_issued": bootstrap_tokens_issued,
            "active_developers": active_developers,
            "active_agents": active_agents,
            "tokens_used": tokens_used,
            "tokens_expired": tokens_expired,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        # §RELEASECHANNEL (2026-09-21): behind or not, and on what; admin-only on purpose (a public "behind" mark
        # would name a vulnerable node to strangers).
        try:
            from agentvault_registry.core import release_channel as _rc
            dashboard_data["release_channel"] = _rc.dashboard_summary()
        except Exception as _exc:  # noqa: BLE001 — the dashboard must not fail on the release block
            dashboard_data["release_channel"] = {"error": str(_exc)[:120]}
        
        logger.info(f"Dashboard data retrieved: {dashboard_data}")
        return dashboard_data
        
    except Exception as e:
        logger.error(f"Error retrieving dashboard data: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard statistics"
        )


@router.get("/system-health", response_model=Dict[str, Any], tags=["Admin — Platform"])
async def get_system_health(
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """
    Get system health information.
    
    Requires admin authentication.
    
    Returns system health metrics and status information.
    """
    logger.info(f"System health check accessed by: {email_for_log(current_admin.email)}")
    
    try:
        # Check database connectivity
        db_healthy = False
        try:
            await db.execute(select(1))
            db_healthy = True
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
        
        # Get recent activity metrics
        recent_developers_stmt = select(func.count()).select_from(Developer).where(
            Developer.created_at >= func.now() - text("INTERVAL '7 days'"),
            a_developer_of_this_registry(),
        )
        recent_developers_result = await db.execute(recent_developers_stmt)
        recent_developers = recent_developers_result.scalar() or 0
        
        recent_agents_stmt = select(func.count()).select_from(Agent).where(
            Agent.created_at >= func.now() - text("INTERVAL '7 days'")
        )
        recent_agents_result = await db.execute(recent_agents_stmt)
        recent_agents = recent_agents_result.scalar() or 0
        
        health_data = {
            "status": "healthy" if db_healthy else "degraded",
            "database": "connected" if db_healthy else "disconnected",
            "recent_activity": {
                "developers_last_7_days": recent_developers,
                "agents_last_7_days": recent_agents
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return health_data
        
    except Exception as e:
        logger.error(f"Error retrieving system health: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system health information"
        )


@router.get("/disputes/queue", response_model=Dict[str, Any], tags=["Admin — Enforcement"])
async def dispute_queue(
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """One ruler's queue (V0657 (a), item 3): every open dispute record, and every Guild order and contract in
    `disputed` that has no open record (each can be given one: POST /admin/disputes/queue/{kind}/{ref}/record), so
    every dispute is ruled from the same screen by the same rules."""
    from agentvault_registry.services import dispute_queue as dq
    return await dq.queue(db)


@router.post("/disputes/queue/{kind}/{ref}/record", response_model=Dict[str, Any], tags=["Admin — Enforcement"])
async def file_dispute_record(
    kind: str,
    ref: str,
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """Give a disputed Guild order (`guild`) or contract (`contract`) without an open record its record, filed by the
    system and linked: a ruling on it settles that escrow."""
    from agentvault_registry.services import dispute_queue as dq
    try:
        rid = await dq.file_record(db, kind, ref)
    except dq.QueueRefused as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    logger.info(f"Admin {email_for_log(current_admin.email)} filed dispute record {rid} for {kind} {ref}")
    return {"dispute_id": rid, "kind": kind, "ref": ref}


@router.get("/disputes/{dispute_id}/preview", response_model=Dict[str, Any], tags=["Admin — Enforcement"])
async def preview_dispute_ruling(
    dispute_id: int,
    ruling: str,
    worker_share: Optional[Decimal] = Query(None, ge=0, le=1),
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """What a ruling would do, before it is made (V0657 (a), item 7), read only: who gets what (a Guild order's escrow
    split and the worker's collateral, a contract's split, or the complainant's explicit claim from the defendant's
    wallet), each agent's reputation change, and the enforcement step a ruling for the complainant opens (the offense,
    the escalation level, a warning or a slash, a pause, a suspension). The ruling applies the same rules."""
    d = await crud_disputes.get_dispute_by_id(db, dispute_id)
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dispute with ID {dispute_id} not found")
    if d.status == "CLOSED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Dispute {dispute_id} is already ruled ({d.ruling}); a correction is previewed at "
                                   f"/admin/disputes/{dispute_id}/correction-preview")
    from agentvault_registry.services import dispute_settlement
    try:
        return await dispute_settlement.preview(db, d, ruling, worker_share)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


class DisputeCorrectionIn(BaseModel):
    """V0657 (a): the correction rail. The reason is required: it is kept and told to both parties."""
    ruling: str = Field(..., description="The corrected ruling")
    note: str = Field(..., min_length=10, max_length=4000, description="Why the ruling is corrected")


@router.get("/disputes/{dispute_id}/correction-preview", response_model=Dict[str, Any], tags=["Admin — Enforcement"])
async def preview_dispute_correction(
    dispute_id: int,
    ruling: str,
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """What correcting a ruling would do, read only: the reputation changes undone, the enforcement actions reversed
    (and what a correction does not undo: a slash's money, a suspension), the corrected ruling's own reputation rule."""
    from agentvault_registry.services import dispute_correction
    d = await crud_disputes.get_dispute_by_id(db, dispute_id)
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dispute with ID {dispute_id} not found")
    try:
        return await dispute_correction.plan(db, d, ruling)
    except dispute_correction.CorrectionRefused as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/disputes/{dispute_id}/correct", response_model=Dict[str, Any], tags=["Admin — Enforcement"])
async def correct_dispute_ruling(
    dispute_id: int,
    body: DisputeCorrectionIn,
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """Correct a ruling (V0657 (a), the Commander's approval at room seq 1473 and 1482): the old ruling's reputation
    changes are undone and the enforcement actions it opened reversed, the corrected ruling's reputation rule applies,
    and why is kept (dispute_corrections), told to both parties and to the ledger. A correction moves no money."""
    from agentvault_registry.services import dispute_correction
    logger.info(f"Admin {email_for_log(current_admin.email)} correcting dispute {dispute_id} to {body.ruling}")
    try:
        return await dispute_correction.apply(db, dispute_id, body.ruling, note=body.note,
                                              corrected_by=current_admin.id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except dispute_correction.CorrectionRefused as e:
        # CorrectionInFlight too: a second correction at the same moment, or one while another is still applying
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/disputes/{dispute_id}/corrections/{correction_id}/finish", response_model=Dict[str, Any],
             tags=["Admin — Enforcement"])
async def finish_dispute_correction(
    dispute_id: int,
    correction_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """Finish a correction that a failure left 'applying' (V0657 (a), session-lead's review at room seq 1597): the steps
    it recorded are kept, the rest are done once, from the plan stored when it claimed the record."""
    from agentvault_registry.services import dispute_correction
    logger.info(f"Admin {email_for_log(current_admin.email)} finishing correction {correction_id} of dispute {dispute_id}")
    try:
        return await dispute_correction.finish(db, dispute_id, correction_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except dispute_correction.CorrectionRefused as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


class DisputeRulingIn(BaseModel):
    """V0657 (a): a ruling as a ruler makes it. `ruling` may also come as the query parameter (the MCP tool's form)."""
    ruling: Optional[str] = Field(None, description="IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT or DISMISSED")
    note: Optional[str] = Field(None, max_length=4000, description="The ruler's reason: kept on the record, told to both "
                                                                   "parties, carried in DisputeResolved")
    worker_share: Optional[Decimal] = Field(None, ge=0, le=1, description="For a dispute about a Guild order: the "
                                            "worker's share of its escrow (the rest goes back to the poster). Unset, "
                                            "the ruling decides it (services/dispute_rules.guild_worker_share)")


@router.put("/disputes/{dispute_id}/ruling", response_model=Dict[str, Any], tags=["Admin — Enforcement"])
async def update_dispute_ruling_endpoint(
    dispute_id: int,
    ruling: Optional[str] = None,
    body: Optional[DisputeRulingIn] = Body(None),
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """
    Rule on a dispute (admin_enforcement).

    The ruling (IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT or DISMISSED) comes in the body or as the `ruling` query
    parameter; the body may add the ruler's reason (`note`) and, for a dispute about a Guild order, the worker's share
    of the order's escrow. GET /admin/disputes/{id}/preview shows what a ruling would do before it is made.

    One settlement authority (V0657 (a)): a dispute about a Guild order settles that order's escrow, and the money moves
    BEFORE the ruling is written (a ruling lands only when its money did; an order settled elsewhere moves nothing); a
    dispute about a contract settles the contract's escrow (the contract spine). Neither moves money from a wallet. A
    dispute about neither may move the complainant's explicit claim from the defendant's wallet. The record keeps who
    ruled, when, why and what the ruling did; both parties are told, the reason included.
    """
    if not isinstance(body, DisputeRulingIn):     # called directly (not through FastAPI) the default is Body's marker
        body = None
    if not isinstance(ruling, str):
        ruling = None
    r = ((body.ruling if body else None) or ruling or "").strip()
    note = body.note if body else None
    share = body.worker_share if body else None
    logger.info(f"Admin {email_for_log(current_admin.email)} ruling dispute {dispute_id}: {r}")

    from agentvault_registry.services.dispute_rules import RULINGS
    if r not in RULINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ruling. Must be one of: {', '.join(RULINGS)}"
        )

    # Get the dispute before update to track reputation changes
    dispute_before = await crud_disputes.get_dispute_by_id(db, dispute_id)
    if not dispute_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispute with ID {dispute_id} not found"
        )

    if dispute_before.status == "CLOSED":
        # D6 (2026-05-06): align with crud_disputes.DisputeAlreadyRuled — 409 Conflict
        # (was 400) so retries / replays receive a stable, idempotency-aware response.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dispute {dispute_id} is already closed (ruling={dispute_before.ruling})"
        )

    # Get initial reputation scores
    from sqlalchemy import select
    from agentvault_registry.models import Agent

    complainant_result = await db.execute(
        select(Agent).where(Agent.did == dispute_before.complainant_did)
    )
    complainant = complainant_result.scalar_one_or_none()
    complainant_initial_rep = complainant.reputation_score if complainant else None

    defendant_result = await db.execute(
        select(Agent).where(Agent.did == dispute_before.defendant_did)
    )
    defendant = defendant_result.scalar_one_or_none()
    defendant_initial_rep = defendant.reputation_score if defendant else None

    # V0657 (a): a dispute about a Guild order — its escrow first. A failed split raises here (the order back to
    # disputed), and no ruling is written: the ruler retries.
    from agentvault_registry.services import dispute_settlement
    guild = await dispute_settlement.settle_guild_for_ruling(
        db, dispute_before, r, worker_share=share, actor=f"admin:{current_admin.id}", note=note)
    if share is not None and guild is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="worker_share applies only to a dispute about a Guild order")

    # Update the dispute ruling
    # D2: SELECT FOR UPDATE inside CRUD prevents concurrent ruling race.
    # D6: DisputeAlreadyRuled raised if dispute already CLOSED with a ruling.
    try:
        updated_dispute = await crud_disputes.update_dispute_ruling(
            db, dispute_id, r, ruled_by=current_admin.id, note=note, money=guild)
    except crud_disputes.DisputeAlreadyRuled as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

    if not updated_dispute:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update dispute ruling"
        )

    # Get updated reputation scores
    await db.refresh(complainant) if complainant else None
    await db.refresh(defendant) if defendant else None

    complainant_final_rep = complainant.reputation_score if complainant else None
    defendant_final_rep = defendant.reputation_score if defendant else None

    if guild is not None:
        compensation = {"applied": False, "amount": 0,
                        "skipped_reason": "the Guild order's escrow split is the settlement", "guild": guild}
    else:
        # CONTRACT SPINE wiring (2026-07-25): ONE settlement authority per grievance. If this dispute
        # is linked to a spine contract, the money at issue is the ESCROWED REMAINDER — the ruling
        # drives the escrow split (claim-first; no-ops if already settled) and wallet compensation is
        # SKIPPED entirely, otherwise the defendant pays twice (wallet slash + lost escrow).
        contract_settlement = None
        try:
            from agentvault_registry.services import contract_settlement as _cs
            contract_settlement = await _cs.settle_linked_contract_for_ruling(db, updated_dispute, r)
        except Exception as _e:  # noqa: BLE001 — wiring must never 500 a ruling
            logger.error(f"[DisputeRuling] linked-contract settlement hook failed: {_e}", exc_info=True)

        if contract_settlement is not None:
            compensation = {"applied": False, "amount": 0,
                            "skipped_reason": "contract escrow split is the settlement",
                            "contract": contract_settlement}
        else:
            # Phase 1: Process compensation (no escrow): the complainant's explicit claim (V0657 (a), item 2)
            compensation = await crud_disputes.process_compensation(db, updated_dispute, r)
        # V0657 (a), item 22: the money is the record's too
        updated_dispute.outcome = {**(updated_dispute.outcome or {}), "money": crud_disputes._jsonable(compensation)}
        await db.commit()
        # the commit expired the row; read after it without this, it lazy-loads outside the greenlet (MissingGreenlet,
        # answered 500 after the ruling had landed: V0657's pair proof, room seq 1879)
        await db.refresh(updated_dispute)

    logger.info(
        f"Dispute #{dispute_id} resolved: ruling={r}, "
        f"compensation={'applied' if compensation['applied'] else 'not applied'} "
        f"({compensation.get('amount', 0)} AVT)"
    )

    # A1 (2026-07-24): dispute.resolved was subscribable but never fired.
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    _aio.create_task(dispatch_webhook_for_agents(
        "dispute.resolved",
        {"dispute_id": updated_dispute.id, "ruling": updated_dispute.ruling,
         "status": updated_dispute.status,
         "complainant_did": updated_dispute.complainant_did,
         "defendant_did": updated_dispute.defendant_did,
         "ruling_note": updated_dispute.ruling_note,
         "compensation_applied": compensation.get("applied", False),
         "compensation_amount": str(compensation.get("amount", 0))},
        [updated_dispute.complainant_did, updated_dispute.defendant_did],
        source_label="disputes.resolve"))

    # §NOTIFV2 (2026-07-27): BOTH parties hear the ruling. V0657 (a): in words, with the ruler's reason.
    dispute_settlement.notify_ruled(updated_dispute, compensation)

    return {
        "dispute_id": updated_dispute.id,
        "status": updated_dispute.status,
        "ruling": updated_dispute.ruling,
        "complainant_did": updated_dispute.complainant_did,
        "defendant_did": updated_dispute.defendant_did,
        "reputation_changes": {
            "complainant": {
                "initial": complainant_initial_rep,
                "final": complainant_final_rep,
                "change": (complainant_final_rep - complainant_initial_rep) if complainant_initial_rep is not None and complainant_final_rep is not None else None
            },
            "defendant": {
                "initial": defendant_initial_rep,
                "final": defendant_final_rep,
                "change": (defendant_final_rep - defendant_initial_rep) if defendant_initial_rep is not None and defendant_final_rep is not None else None
            }
        },
        "compensation": compensation,
        "ruled_by": updated_dispute.ruled_by,
        "ruled_at": updated_dispute.ruled_at.isoformat() if updated_dispute.ruled_at else None,
        "ruling_note": updated_dispute.ruling_note,
        "outcome": updated_dispute.outcome,
        "updated_at": updated_dispute.updated_at.isoformat()
    }
