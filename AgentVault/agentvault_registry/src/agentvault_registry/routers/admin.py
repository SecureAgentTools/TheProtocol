"""
Admin Dashboard Router
---------------------
Provides administrative endpoints for system oversight and monitoring.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from agentvault_registry.database import get_db
from agentvault_registry.models import Developer, Agent, BootstrapToken, Dispute
from agentvault_registry.services.developer_population import a_developer_of_this_registry
from agentvault_registry import security
from agentvault_registry.schemas import DeveloperRead
from agentvault_registry.crud import crud_disputes

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
    logger.info(f"Admin dashboard accessed by: {current_admin.email}")
    
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
    logger.info(f"System health check accessed by: {current_admin.email}")
    
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


@router.put("/disputes/{dispute_id}/ruling", response_model=Dict[str, Any], tags=["Admin — Enforcement"])
async def update_dispute_ruling_endpoint(
    dispute_id: int,
    ruling: str,
    db: AsyncSession = Depends(get_db),
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """
    Manually update the ruling of a dispute (for testing purposes).
    
    Requires admin authentication.
    
    Args:
        dispute_id: The ID of the dispute to update
        ruling: The ruling to apply (IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT, DISMISSED)
        
    Returns:
        The updated dispute information including reputation changes
    """
    logger.info(f"Admin {current_admin.email} updating ruling for dispute {dispute_id} to {ruling}")
    
    # Validate ruling value
    valid_rulings = ["IN_FAVOR_OF_COMPLAINANT", "IN_FAVOR_OF_DEFENDANT", "DISMISSED"]
    if ruling not in valid_rulings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ruling. Must be one of: {', '.join(valid_rulings)}"
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
    
    # Update the dispute ruling
    # D2: SELECT FOR UPDATE inside CRUD prevents concurrent ruling race.
    # D6: DisputeAlreadyRuled raised if dispute already CLOSED with a ruling.
    try:
        updated_dispute = await crud_disputes.update_dispute_ruling(db, dispute_id, ruling)
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
    
    # CONTRACT SPINE wiring (2026-07-25): ONE settlement authority per grievance. If this dispute
    # is linked to a spine contract, the money at issue is the ESCROWED REMAINDER — the ruling
    # drives the escrow split (claim-first; no-ops if already settled) and wallet compensation is
    # SKIPPED entirely, otherwise the defendant pays twice (wallet slash + lost escrow).
    contract_settlement = None
    try:
        from agentvault_registry.services import contract_settlement as _cs
        contract_settlement = await _cs.settle_linked_contract_for_ruling(db, updated_dispute, ruling)
    except Exception as _e:  # noqa: BLE001 — wiring must never 500 a ruling
        logger.error(f"[DisputeRuling] linked-contract settlement hook failed: {_e}", exc_info=True)

    if contract_settlement is not None:
        compensation = {"applied": False, "amount": 0,
                        "skipped_reason": "contract escrow split is the settlement",
                        "contract": contract_settlement}
    else:
        # Phase 1: Process AVT compensation (non-contract disputes only)
        compensation = await crud_disputes.process_compensation(db, updated_dispute, ruling)
    
    logger.info(
        f"Dispute #{dispute_id} resolved: ruling={ruling}, "
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
         "compensation_applied": compensation.get("applied", False),
         "compensation_amount": str(compensation.get("amount", 0))},
        [updated_dispute.complainant_did, updated_dispute.defendant_did],
        source_label="disputes.resolve"))

    # §NOTIFV2 (2026-07-27): the webhook above has fired since §HARDENING2 A1, but the PUSH never
    # did. BOTH parties are notified here, unlike dispute.filed_against_you which deliberately
    # tells only the defendant: nobody knows a ruling until they are told, including the person
    # who filed. Placed on the single converged path so the contract-escrow branch and the
    # wallet-compensation branch both notify.
    try:
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "dispute.resolved",
            [updated_dispute.complainant_did, updated_dispute.defendant_did],
            title="Dispute resolved",
            message=(f"Dispute #{updated_dispute.id} ruled {updated_dispute.ruling}."
                     + (f" Compensation: {compensation.get('amount', 0)}."
                        if compensation.get("applied") else "")),
            tags="scales", priority="high", click="/ui/#/disputes"))
    except Exception:  # noqa: BLE001
        logger.debug("dispute.resolved notify skipped", exc_info=True)

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
                "change": (complainant_final_rep - complainant_initial_rep) if complainant_initial_rep and complainant_final_rep else None
            },
            "defendant": {
                "initial": defendant_initial_rep,
                "final": defendant_final_rep,
                "change": (defendant_final_rep - defendant_initial_rep) if defendant_initial_rep and defendant_final_rep else None
            }
        },
        "compensation": compensation,
        "updated_at": updated_dispute.updated_at.isoformat()
    }
