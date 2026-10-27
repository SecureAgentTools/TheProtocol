"""
TITANIUM VAULT D2: Enforcement Admin Router — FULL §4.9 (11 routes)

Routes:
  GET  /agents/{did}/slash-preview       — dry-run force-unstake
  POST /agents/{did}/slash-stake         — execute force-unstake slash
  GET  /agents/{did}/status              — full enforcement status summary
  POST /agents/{did}/record-offense      — manual offense recording
  POST /agents/{did}/pause-rewards       — manually pause rewards
  POST /agents/{did}/resume-rewards      — resume paused rewards
  POST /agents/{did}/suspend             — suspend agent
  POST /agents/{did}/reinstate           — lift suspension
  GET  /policy                           — get active enforcement policy
  PUT  /policy                           — update enforcement policy (admin override)
  GET  /policy/defaults                  — factory default policy
  GET  /pending                          — list pending enforcement actions
  POST /pending/{action_id}/approve      — approve pending action
  POST /pending/{action_id}/reject       — reject pending action

Auth: Admin JWT required on all endpoints.
Spec: Economic Engine §4.7, §4.9
"""
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.models import Developer
from agentvault_registry.services.force_unstake import (
    get_force_unstake_service,
    AgentNotFoundError,
    ForceUnstakeError,
    InsufficientStakeError,
    NoActiveStakeError,
    TegUnlockError,
)
from agentvault_registry.crud import crud_enforcement

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/enforcement",
    tags=["Enforcement Admin"]
)


# ── Request / Response Models ────────────────────────────────────────

class SlashStakeRequest(BaseModel):
    amount: int = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=500)


class RecordOffenseRequest(BaseModel):
    offense_type: str = Field("dispute_lost", description="Type of offense")
    severity: int = Field(1, ge=1, le=4, description="Severity (1–4)")
    reference: Optional[str] = Field(None, description="Dispute ID or other reference")
    disputed_amount: int = Field(0, ge=0)


class PauseRewardsRequest(BaseModel):
    duration_days: int = Field(7, gt=0, le=365)
    reason: str = Field(..., min_length=1, max_length=500)


class SuspendRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ReinstateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class UpdatePolicyRequest(BaseModel):
    policy_json: Dict[str, Any]
    reason: str = Field(..., min_length=1, max_length=500)


class RejectActionRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/agents/{agent_did}/slash-preview", response_model=Dict[str, Any],
            summary="Preview a forced release (dry run)")
async def slash_stake_preview(
    agent_did: str,
    amount: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    service = get_force_unstake_service()
    preview = await service.calculate_force_unstake_preview(
        db=db, agent_did=agent_did, required_amount=amount
    )
    if "error" in preview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=preview["error"])
    return preview


@router.post("/agents/{agent_did}/slash-stake", response_model=Dict[str, Any],
             summary="Execute a forced-release slash on an agent")
async def slash_stake_execute(
    agent_did: str,
    request: SlashStakeRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    logger.info(f"[EnforcementAdmin] Slash by {admin.email}: {agent_did}, amt={request.amount}")
    service = get_force_unstake_service()
    try:
        result = await service.force_unstake_for_slash(
            db=db,
            agent_did=agent_did,
            required_amount=request.amount,
            admin_did=f"did:developer:{admin.id}",
            reason=request.reason,
        )
    except ForceUnstakeError as e:
        raise _slash_refusal(e)
    return result


def _slash_refusal(e: ForceUnstakeError) -> HTTPException:
    """§MCPTEST30 (V0550): the refusal says its reason. Every ForceUnstakeError used to answer 400 "An internal error
    occurred", the nonexistent agent and the agent with nothing staked included (agentvault2-45 found it pinning the
    sweep's refusals). The service's own sentences are ours and name no internals; the TEG's failure text is logged,
    never returned."""
    if isinstance(e, AgentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    if isinstance(e, (NoActiveStakeError, InsufficientStakeError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if isinstance(e, TegUnlockError):
        logger.error(f"[EnforcementAdmin] slash: {e}")
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                             detail="The TEG did not release the locked units, so nothing was slashed (the transaction was rolled back)")
    logger.warning(f"[EnforcementAdmin] slash refused: {e}")
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/agents/{agent_did}/status", response_model=Dict[str, Any],
            summary="Full enforcement status summary for agent")
async def get_agent_enforcement_status(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    summary = await crud_enforcement.get_agent_enforcement_status(db, agent_did)
    if not summary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Agent {agent_did} not found")
    return summary


@router.post("/agents/{agent_did}/record-offense", response_model=Dict[str, Any],
             summary="Manually record an offense and trigger escalation")
async def record_offense(
    agent_did: str,
    request: RecordOffenseRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    from agentvault_registry.services.enforcement_engine import get_enforcement_engine
    engine = get_enforcement_engine()
    action = await engine.evaluate_dispute_outcome(
        db=db,
        defendant_did=agent_did,
        dispute_id=request.reference or "admin_manual",
        disputed_amount=request.disputed_amount,
    )
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Agent {agent_did} not found")
    return {
        "action_id": action.id,
        "action_type": action.action_type,
        "status": action.status,
        "escalation_level": action.escalation_level,
        "amount": action.amount,
    }


@router.post("/agents/{agent_did}/pause-rewards", response_model=Dict[str, Any],
             summary="Hold back an agent's payments on locked units for a number of days (admin)")
async def pause_rewards(
    agent_did: str,
    request: PauseRewardsRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    from sqlalchemy import select
    from agentvault_registry.models import Agent
    from datetime import timedelta, datetime, timezone

    result = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Agent {agent_did} not found")

    policy_row = await crud_enforcement.get_active_policy(db)
    policy_version = policy_row.version if policy_row else 1

    agent.rewards_paused_until = datetime.now(timezone.utc) + timedelta(days=request.duration_days)

    action = await crud_enforcement.create_enforcement_action(
        db=db,
        agent_did=agent_did,
        action_type="pause_rewards",
        trigger="admin_manual",
        trigger_reference=f"admin:{admin.id}",
        amount=None,
        escalation_level=agent.enforcement_level or 1,
        policy_version=policy_version,
        status="executed",
    )
    action.executed_at = datetime.now(timezone.utc)
    action.approved_by = f"did:developer:{admin.id}"
    await db.commit()

    return {
        "action_id": action.id,
        "agent_did": agent_did,
        "rewards_paused_until": agent.rewards_paused_until.isoformat(),
        "reason": request.reason,
    }


@router.post("/agents/{agent_did}/resume-rewards", response_model=Dict[str, Any],
             summary="Lift the hold on an agent's payments on locked units (admin)")
async def resume_rewards(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    from sqlalchemy import select
    from agentvault_registry.models import Agent
    from datetime import datetime, timezone

    result = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Agent {agent_did} not found")

    policy_row = await crud_enforcement.get_active_policy(db)
    policy_version = policy_row.version if policy_row else 1

    agent.rewards_paused_until = None

    action = await crud_enforcement.create_enforcement_action(
        db=db,
        agent_did=agent_did,
        action_type="resume_rewards",
        trigger="admin_manual",
        trigger_reference=f"admin:{admin.id}",
        amount=None,
        escalation_level=0,
        policy_version=policy_version,
        status="executed",
    )
    action.executed_at = datetime.now(timezone.utc)
    action.approved_by = f"did:developer:{admin.id}"
    await db.commit()

    return {
        "action_id": action.id,
        "agent_did": agent_did,
        "rewards_paused_until": None,
    }


def _dispatch_owner_lifecycle(agent_did: str, new_status: str, old_status: Optional[str], reason: str,
                              action_id: Any) -> None:
    """§TWOAGENT #30: the owner-scoped webhooks of a single-agent enforcement flip (fire-and-forget, never fails the
    route). `agent.status_changed` carries the same keys as the coordinated rail's; `agent.suspended` /
    `agent.reinstated` name the agent and the reason, and which rail acted."""
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        event = "agent.suspended" if new_status == "suspended" else "agent.reinstated"
        _aio.create_task(dispatch_webhook_for_agents(
            "agent.status_changed",
            {"agent_did": agent_did, "old_status": old_status, "new_status": new_status, "reason": reason, "soft": False},
            [agent_did], source_label="enforcement_admin.single"))
        _aio.create_task(dispatch_webhook_for_agents(
            event,
            {"agent_did": agent_did, "target_agent_did": agent_did, "reason": reason, "rail": "admin_enforcement_single",
             "enforcement_action_id": str(action_id) if action_id is not None else None},
            [agent_did], source_label="enforcement_admin.single"))
    except Exception:  # noqa: BLE001 — a webhook is advisory; the flip already committed
        logger.debug("[TWOAGENT #30] owner lifecycle dispatch skipped", exc_info=True)


@router.post("/agents/{agent_did}/suspend", response_model=Dict[str, Any],
             summary="Suspend agent (freeze all operations)")
async def suspend_agent(
    agent_did: str,
    request: SuspendRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    from sqlalchemy import select
    from agentvault_registry.models import Agent
    from datetime import datetime, timezone

    result = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Agent {agent_did} not found")

    policy_row = await crud_enforcement.get_active_policy(db)
    policy_version = policy_row.version if policy_row else 1

    _old_status = agent.status
    agent.enforcement_status = "suspended"
    agent.status = "suspended"
    # §TWOAGENT #30 (2026-09-23): the flip must reach the peers' MIRRORS, and only the CARD travels. The coordinated
    # rail touched it (§ENFPROP) and this rail did not, so a suspension made here never reached another frame: measured
    # 1200 s / 118 polls on EU for an ASIA agent, 900 s / 80 polls the other way. Touch it on THIS transaction.
    from agentvault_registry.services import enforcement_propagation as _ep
    await _ep.touch_native_card_no_commit(db, agent_did)

    action = await crud_enforcement.create_enforcement_action(
        db=db,
        agent_did=agent_did,
        action_type="suspend",
        trigger="admin_manual",
        trigger_reference=f"admin:{admin.id}: {request.reason}",
        amount=None,
        escalation_level=agent.enforcement_level or 3,
        policy_version=policy_version,
        status="executed",
    )
    action.executed_at = datetime.now(timezone.utc)
    action.approved_by = f"did:developer:{admin.id}"
    await db.commit()

    # §TWOAGENT #30: the owner's webhook. `agent.suspended` / `agent.status_changed` are in the vocabulary and an owner
    # can subscribe to them, but this rail delivered neither (it emits no AgentSuspended event, so the reactor never ran,
    # and the push below is a phone notification). Owner-scoped, like the coordinated rail's inline dispatch; no admin
    # e-mail in the payload (that is the owner's agent, not the admin's business card).
    if _old_status != "suspended":
        _dispatch_owner_lifecycle(agent_did, "suspended", _old_status, request.reason, action.id)

    # §NOTIFV2 — this single-agent enforcement route is a SECOND suspended call site
    # (services/coordinated_suspension.py is the other, and is the one the bulk levers use).
    # Wiring only the coordinated helper left agent.suspended silent for the most
    # common admin action; verified live by suspending a test agent and finding no log row.
    try:
        import asyncio as _aio2
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio2.create_task(notify_agent_owners(
            "agent.suspended", [agent_did],
            title="Agent suspended",
            message=f"{agent_did[:40]} was suspended. Reason: {request.reason}",
            # D6-781: the owner's agent list (the console has no #/agents; Pocket opens its own Agents tab)
            tags="warning", priority="high", click="/ui/#/my-agents"))
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] agent.suspended emit failed", exc_info=True)

    return {
        "action_id": action.id,
        "agent_did": agent_did,
        "enforcement_status": agent.enforcement_status,
        "reason": request.reason,
    }


@router.post("/agents/{agent_did}/reinstate", response_model=Dict[str, Any],
             summary="Reinstate suspended agent")
async def reinstate_agent(
    agent_did: str,
    request: ReinstateRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    from sqlalchemy import select
    from agentvault_registry.models import Agent
    from datetime import datetime, timezone

    result = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Agent {agent_did} not found")

    if agent.enforcement_status == "revoked":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot reinstate a revoked agent")

    policy_row = await crud_enforcement.get_active_policy(db)
    policy_version = policy_row.version if policy_row else 1

    _old_status = agent.status
    agent.enforcement_status = "active"
    agent.status = "active"
    agent.rewards_paused_until = None
    # §TWOAGENT #30: the reinstatement travels by the card too (see suspend_agent).
    from agentvault_registry.services import enforcement_propagation as _ep
    await _ep.touch_native_card_no_commit(db, agent_did)

    action = await crud_enforcement.create_enforcement_action(
        db=db,
        agent_did=agent_did,
        action_type="reinstate",
        trigger="admin_manual",
        trigger_reference=f"admin:{admin.id}: {request.reason}",
        amount=None,
        escalation_level=0,
        policy_version=policy_version,
        status="executed",
    )
    action.executed_at = datetime.now(timezone.utc)
    action.approved_by = f"did:developer:{admin.id}"
    await db.commit()

    # §TWOAGENT #30: the owner's webhook (see suspend_agent).
    if _old_status != "active":
        _dispatch_owner_lifecycle(agent_did, "active", _old_status, request.reason, action.id)

    # §NOTIFV2 — this single-agent enforcement route is a SECOND reinstated call site
    # (services/coordinated_suspension.py is the other, and is the one the bulk levers use).
    # Wiring only the coordinated helper left agent.reinstated silent for the most
    # common admin action; verified live by suspending a test agent and finding no log row.
    try:
        import asyncio as _aio2
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio2.create_task(notify_agent_owners(
            "agent.reinstated", [agent_did],
            title="Agent reinstated",
            message=f"{agent_did[:40]} is active again.",
            # D6-781: the owner's agent list (the console has no #/agents; Pocket opens its own Agents tab)
            tags="white_check_mark", priority="default", click="/ui/#/my-agents"))
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] agent.reinstated emit failed", exc_info=True)

    return {
        "action_id": action.id,
        "agent_did": agent_did,
        "enforcement_status": agent.enforcement_status,
        "reason": request.reason,
    }


@router.get("/policy", response_model=Dict[str, Any],
            summary="Get active enforcement policy")
async def get_policy(
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    row = await crud_enforcement.get_active_policy(db)
    if not row:
        return {
            "version": 0,
            "is_active": True,
            "modified_by": "factory_defaults",
            "policy_json": await crud_enforcement.get_policy_defaults(),
        }
    return {
        "id": row.id,
        "version": row.version,
        "is_active": row.is_active,
        "modified_by": row.modified_by,
        "modified_at": row.modified_at.isoformat(),
        "previous_version": row.previous_version,
        "policy_json": row.policy_json,
    }


@router.get("/policy/resolved", response_model=Dict[str, Any],
            summary="The policy this frame is ACTUALLY running (row merged onto defaults), with per-field provenance")
async def get_resolved_policy(
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    """§FRAMEPOLICY — GET /policy returns the stored ROW, which is not what the
    frame runs: a row written before a section existed is missing that section,
    and every consumer silently falls back to the factory default (registry-a's
    row predates §REPBOND by five months and carries no slash_waterfall).

    This returns the RESOLVED document — the row deep-merged onto the defaults —
    plus, for every rule the frame's own code reads, whether the value was set
    HERE or is the shipped default. `policy_hash` is the same value published on
    the signed registry card and by /federation/policy-compliance.
    """
    from ..services.frame_policy import load as _load_frame_policy, GOVERNED_PATHS
    pol = await _load_frame_policy(db)
    return {
        "policy_version": pol.version,
        "policy_source": pol.source,
        "policy_hash": pol.hash(),
        "modified_by": pol.modified_by,
        "modified_at": pol.modified_at.isoformat() if pol.modified_at else None,
        "policy_json": pol.doc,
        "governed": pol.posture(GOVERNED_PATHS),
        "governed_paths": list(GOVERNED_PATHS),
    }


@router.put("/policy", response_model=Dict[str, Any],
            summary="Update enforcement policy (admin override)")
async def update_policy(
    request: UpdatePolicyRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    modified_by = f"admin_override:developer_{admin.id}"
    return await _apply_policy_update(db, admin, request.policy_json, modified_by, request.reason)


async def _apply_policy_update(db: AsyncSession, admin: Developer, policy_json: Dict[str, Any],
                               modified_by: str, reason: str) -> Dict[str, Any]:
    """§REPBOND — ONE path for every policy write: validate (422 on a shape the engine
    could not execute), version, and when the SLASH WATERFALL changed, say so in the
    audit log and on the ledger (`SlashWaterfallChanged`) — the order a slash drains
    from is a security setting, not a preference."""
    # §FRAMEPOLICY (2026-09-11) — refuse a document the frame could not mean.
    # crud_enforcement.validate_policy_json checks the shapes the ENGINE must be
    # able to execute; it has no opinion on a key that does not exist, so until
    # now `standrd_quorum_percent` was accepted, stored, versioned, audited and
    # then read by nobody. An ignored rule is worse than a refused one.
    from ..services.frame_policy import validate_document as _validate_policy_doc
    from ..services.frame_policy import resolve as _resolve_policy
    _problems = _validate_policy_doc(_resolve_policy(policy_json))
    _unknown = [p for p in _problems if p.startswith("unknown policy key")]
    _bad = [p for p in _problems if not p.startswith("unknown policy key")]
    if _unknown or _bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="policy refused: " + "; ".join((_unknown + _bad)[:8]),
        )

    before_row = await crud_enforcement.get_active_policy(db)
    before_wf = (before_row.policy_json if before_row and before_row.policy_json
                 else crud_enforcement.DEFAULT_POLICY_JSON).get("slash_waterfall")
    try:
        new_policy = await crud_enforcement.update_policy(
            db=db, new_policy_json=policy_json, modified_by=modified_by,
        )
    except ValueError as ve:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"policy refused: {ve}")
    logger.info(f"[EnforcementAdmin] Policy updated to v{new_policy.version} by {admin.email}")
    after_wf = (new_policy.policy_json or {}).get("slash_waterfall")
    waterfall_changed = before_wf != after_wf
    if waterfall_changed:
        try:
            from agentvault_registry.services.admin_audit import log_admin_action
            kw = dict(action="enforcement.slash_waterfall.changed", actor_id=str(admin.id),
                      target_type="enforcement_policy", target_id=str(new_policy.id),
                      outcome="success", severity="warning")
            kw["details"] = {"before": before_wf, "after": after_wf, "reason": reason}
            await log_admin_action(db, **kw)
        except Exception as e:  # noqa: BLE001 — the audit row is best-effort, the event below is not silent either
            logger.error(f"[EnforcementAdmin] slash-waterfall audit row failed: {e}")
        try:
            from agentvault_registry.event_emitter import get_event_emitter
            emitter = get_event_emitter()
            if emitter is not None:
                await emitter.emit(  # §EMITKEY: emit(), not emit_event()
                    aggregate_id=f"enforcement_policy:{new_policy.id}",
                    event_type="SlashWaterfallChanged",
                    data={"policy_id": new_policy.id, "version": new_policy.version,
                                "before": before_wf, "after": after_wf, "reason": reason,
                                "modified_by": modified_by},
                    idempotency_key=f"slashwf-policy-{new_policy.id}",
                )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[EnforcementAdmin] SlashWaterfallChanged emit failed: {e}")
    return {
        "id": new_policy.id,
        "version": new_policy.version,
        "is_active": new_policy.is_active,
        "modified_by": new_policy.modified_by,
        "modified_at": new_policy.modified_at.isoformat(),
        "slash_waterfall_changed": waterfall_changed,
    }


class PolicySectionUpdate(BaseModel):
    value: Any
    reason: str = Field(..., min_length=1, max_length=500)


@router.get("/policy/section/{name}", response_model=Dict[str, Any],
            summary="One section of the active enforcement policy (e.g. slash_waterfall, staking_reputation, reputation_bond)")
async def get_policy_section(
    name: str,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    if name not in crud_enforcement.DEFAULT_POLICY_JSON:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown policy section {name!r}")
    row = await crud_enforcement.get_active_policy(db)
    pj = row.policy_json if row and row.policy_json else crud_enforcement.DEFAULT_POLICY_JSON
    return {"section": name, "value": pj.get(name, crud_enforcement.DEFAULT_POLICY_JSON.get(name)),
            "default": crud_enforcement.DEFAULT_POLICY_JSON.get(name),
            "version": row.version if row else 0, "source": "policy" if row and name in (row.policy_json or {}) else "default"}


@router.put("/policy/section/{name}", response_model=Dict[str, Any],
            summary="Replace ONE section of the enforcement policy (validated, versioned, audited)")
async def put_policy_section(
    name: str,
    body: PolicySectionUpdate,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    if name not in crud_enforcement.DEFAULT_POLICY_JSON:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown policy section {name!r}")
    row = await crud_enforcement.get_active_policy(db)
    import copy as _copy
    pj = _copy.deepcopy(row.policy_json if row and row.policy_json else crud_enforcement.DEFAULT_POLICY_JSON)
    pj[name] = body.value
    modified_by = f"admin_section:{name}:developer_{admin.id}"
    out = await _apply_policy_update(db, admin, pj, modified_by, body.reason)
    out["section"] = name
    return out


@router.get("/policy/defaults", response_model=Dict[str, Any],
            summary="Get factory default enforcement policy")
async def get_policy_defaults(
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    return await crud_enforcement.get_policy_defaults()


@router.get("/pending", response_model=Dict[str, Any],
            summary="List pending enforcement actions requiring approval")
async def list_pending_actions(
    action_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    actions = await crud_enforcement.get_pending_enforcement_actions(
        db=db, action_type=action_type, page=page, per_page=per_page
    )
    return {
        "items": [
            {
                "id": a.id,
                "agent_did": a.agent_did,
                "action_type": a.action_type,
                "trigger": a.trigger,
                "trigger_reference": a.trigger_reference,
                "amount": a.amount,
                "escalation_level": a.escalation_level,
                "correlation_count": a.correlation_count,
                "correlation_multi": a.correlation_multi,
                "policy_version": a.policy_version,
                "created_at": a.created_at.isoformat(),
            }
            for a in actions
        ],
        "page": page,
        "per_page": per_page,
    }


@router.post("/pending/{action_id}/approve", response_model=Dict[str, Any],
             summary="Approve and execute a pending enforcement action")
async def approve_pending_action(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    from agentvault_registry.services.enforcement_engine import get_enforcement_engine

    action = await crud_enforcement.approve_enforcement_action(
        db=db, action_id=action_id, approved_by=f"did:developer:{admin.id}"
    )
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Pending action {action_id} not found")

    engine = get_enforcement_engine()
    action = await engine.execute_enforcement_action(db, action)

    return {
        "id": action.id,
        "status": action.status,
        "executed_at": action.executed_at.isoformat() if action.executed_at else None,
        "approved_by": action.approved_by,
    }


@router.post("/pending/{action_id}/reject", response_model=Dict[str, Any],
             summary="Reject a pending enforcement action")
async def reject_pending_action(
    action_id: str,
    request: RejectActionRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    action = await crud_enforcement.reject_enforcement_action(
        db=db, action_id=action_id, rejected_reason=request.reason
    )
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Pending action {action_id} not found")
    return {
        "id": action.id,
        "status": action.status,
        "rejected_reason": action.rejected_reason,
    }


# ============================================================================
# Phase 3 Pull: Registry-Level Quarantine & Blacklist Management
# Routes: /api/v1/admin/enforcement/registries/*
# ============================================================================

from sqlalchemy import select as sa_select
from agentvault_registry.models import FederatedRegistryCompliance, PeerRegistry
from agentvault_registry.services.federation_compliance_monitor import (
    NotQuarantined,
    get_federation_compliance_monitor,
)
from agentvault_registry.core.base_network_params import DriftSeverity


class RegistryQuarantineRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)
    grace_hours: int = Field(0, ge=0, le=336, description="Grace period in hours (0 = immediate)")


class RegistryLiftQuarantineRequest(BaseModel):
    new_policy_hash: str = Field(
        ..., min_length=64, max_length=64,
        description="SHA-256 hash of the corrected policy JSON submitted by the operator"
    )


class RegistryBlacklistRequest(BaseModel):
    reason: str = Field(
        ..., min_length=10, max_length=500,
        description="Detailed reason for blacklisting (IRREVERSIBLE from API)"
    )


@router.get("/registries/quarantined",
            summary="List all currently quarantined federated registries")
async def list_quarantined_registries(
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    """Return all peers currently in quarantined state with their compliance context."""
    result = await db.execute(
        sa_select(FederatedRegistryCompliance, PeerRegistry)
        .join(PeerRegistry, FederatedRegistryCompliance.peer_registry_id == PeerRegistry.id)
        .where(FederatedRegistryCompliance.federation_status == "quarantined")
    )
    rows = result.all()

    return {
        "quarantined_count": len(rows),
        "registries": [
            {
                "peer_registry_id": compliance.peer_registry_id,
                "peer_name": peer.name,
                "peer_url": peer.base_url,
                "federation_status": compliance.federation_status,
                "quarantine_reason": compliance.quarantine_reason,
                "quarantine_since": compliance.quarantine_since.isoformat()
                    if compliance.quarantine_since else None,
                "grace_expires": compliance.quarantine_grace_expires.isoformat()
                    if compliance.quarantine_grace_expires else None,
                "grace_active": compliance.in_grace_period(),
                "compliance_score": compliance.compliance_score,
                "drift_events_count": compliance.drift_events_count,
                "consecutive_poll_failures": compliance.consecutive_poll_failures,
            }
            for compliance, peer in rows
        ],
    }


@router.post("/registries/{peer_id}/quarantine",
             summary="Manually quarantine a federated registry (admin decision)")
async def quarantine_registry(
    peer_id: int,
    request: RegistryQuarantineRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    """Manually transition a federated peer to QUARANTINED state."""
    monitor = get_federation_compliance_monitor()
    try:
        await monitor.trigger_quarantine(
            db=db,
            peer_id=peer_id,
            reason=request.reason,
            severity=DriftSeverity.HIGH,
            grace_hours=request.grace_hours,
            admin_email=admin.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return {
        "peer_registry_id": peer_id,
        "federation_status": "quarantined",
        "grace_hours": request.grace_hours,
        "quarantined_by": admin.email,
    }


@router.post("/registries/{peer_id}/lift-quarantine",
             summary="Lift quarantine after operator submits corrected policy")
async def lift_registry_quarantine(
    peer_id: int,
    request: RegistryLiftQuarantineRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    """Restore FEDERATED status once operator has corrected the policy drift."""
    monitor = get_federation_compliance_monitor()
    try:
        await monitor.lift_quarantine(
            db=db,
            peer_id=peer_id,
            new_policy_hash=request.new_policy_hash,
            admin_email=admin.email,
        )
    except NotQuarantined as exc:      # §MCPTEST30 (V0638): a federated peer has no quarantine to lift
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "peer_registry_id": peer_id,
        "federation_status": "federated",
        "new_policy_hash": request.new_policy_hash,
        "lifted_by": admin.email,
    }


@router.post("/registries/{peer_id}/blacklist",
             summary="Permanently blacklist a federated registry (IRREVERSIBLE from API)")
async def blacklist_registry(
    peer_id: int,
    request: RegistryBlacklistRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
):
    """
    Permanently blacklist a federated registry.

    ⚠️  IRREVERSIBLE from the API. Requires direct DB intervention to undo.
    The UI must show a confirmation dialog before calling this endpoint.
    Emits RegistryBlacklisted event to the immutable EventStore.
    """
    monitor = get_federation_compliance_monitor()
    try:
        await monitor.trigger_blacklist(
            db=db,
            peer_id=peer_id,
            reason=request.reason,
            admin_email=admin.email,
            automated=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return {
        "peer_registry_id": peer_id,
        "federation_status": "blacklisted",
        "reason": request.reason,
        "blacklisted_by": admin.email,
        "warning": "This action is IRREVERSIBLE from the API.",
    }
