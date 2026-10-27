"""
Enforcement Agent Router — Economic Engine §4.10

Agent self-service endpoints (require agent JWT):

  GET  /enforcement/my-status            — agent views own enforcement state
  POST /agents/reputation-bond/deposit   — lock 50 AVT as reputation bond
  GET  /agents/reputation-bond/status    — bond maturity progress
  GET  /fees/current-rate                — public: current transaction fee rate

Auth: Agent JWT on deposit + status. /fees/current-rate is public (developer auth sufficient).
Spec: Economic Engine §4.10
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from agentvault_registry.database import get_db
from agentvault_registry.models import Agent, ReputationBond, GlobalTrustVector, Developer
from agentvault_registry.security import get_current_agent, get_current_developer
from agentvault_registry.core.frame_currency import frame_currency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Enforcement Agent"])


# ── Response Models ──────────────────────────────────────────────────

class BondDepositRequest(BaseModel):
    """Optional override for bond amount (uses policy default if omitted)."""
    amount: Optional[int] = Field(None, gt=0, description="Amount to lock, in the frame's unit; defaults to the policy amount (50)")


# ── Endpoints ────────────────────────────────────────────────────────

@router.get(
    "/api/v1/enforcement/my-status",
    response_model=Dict[str, Any],
    summary="Agent views own enforcement status",
)
async def get_my_enforcement_status(
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent),
):
    """Returns the calling agent's enforcement state: level, offense count, restrictions."""
    agent_did = current_agent.did

    gtv_result = await db.execute(
        select(GlobalTrustVector).where(GlobalTrustVector.agent_did == agent_did)
    )
    gtv = gtv_result.scalar_one_or_none()

    bond_result = await db.execute(
        select(ReputationBond).where(ReputationBond.agent_did == agent_did)
    )
    bond = bond_result.scalar_one_or_none()

    active_restrictions = []
    now = datetime.now(timezone.utc)

    if current_agent.enforcement_status == "suspended":
        active_restrictions.append("account_suspended")
    if current_agent.rewards_paused_until and current_agent.rewards_paused_until > now:
        active_restrictions.append(
            f"rewards_paused_until:{current_agent.rewards_paused_until.isoformat()}"
        )

    bond_info = None
    if bond:
        # §BONDFILL-3: one maturity rule. The thresholds come from the frame's resolved policy and the
        # progress from the same reader as /agents/reputation-bond/status. This block used to read the
        # retired `reputation_bond.*` keys with literals of its own, so it showed every agent the absolute
        # EigenTrust gate (0.1) that no agent can meet. It does not stamp maturity; the bond route does.
        from ..services import reputation_bond as _rb
        thresholds = _rb.maturity_thresholds(await _rb.policy_json(db))
        activity = (await _rb.activity_batch(db, [agent_did])).get(agent_did)
        bond_info = {
            "status": bond.status,
            "amount": bond.amount,
            "locked_at": bond.locked_at.isoformat(),
            "matured_at": bond.matured_at.isoformat() if bond.matured_at else None,
            "maturity_progress": _rb.progress_for(activity, bond.locked_at, thresholds),
        }

    return {
        "did": agent_did,
        "offense_count": current_agent.offense_count,
        "enforcement_level": current_agent.enforcement_level,
        "enforcement_status": current_agent.enforcement_status,
        "rewards_paused_until": (
            current_agent.rewards_paused_until.isoformat()
            if current_agent.rewards_paused_until else None
        ),
        "reputation_score": current_agent.reputation_score,
        "eigentrust_score": round(gtv.global_trust, 4) if gtv else 0.0,
        "reputation_bond": bond_info,
        "active_restrictions": active_restrictions,
    }


@router.post(
    "/api/v1/agents/reputation-bond/deposit",
    response_model=Dict[str, Any],
    summary="Deposit the reputation bond (escrowed by the treasury, funded from the agent's own balance)",
)
async def deposit_reputation_bond(
    request: BondDepositRequest,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent),
):
    """
    Deposit the calling agent's reputation bond: the amount moves from the agent's own balance into the treasury's
    escrow under an idempotent reference. An agent already bonded gets its existing bond in the answer. `amount` may
    exceed the required bond, never undercut it. To fund the bond from a wallet agent, use POST
    /api/v1/developers/me/agents/{did}/reputation-bond.

    \f
    §REPBOND (2026-09-05): the bond is MONEY the TEG treasury holds in escrow. This route
    moves it from the calling agent's own balance through the escrow deposit rail under an
    idempotent reference (the pre-0173 route only wrote the registry's balance cache and the
    next sync erased it — R54). Idempotent: an already-bonded agent gets its bond back.
    `amount` may exceed the required bond, never undercut it. To fund the bond from a
    WALLET agent use the developer-tier rail (POST /developers/me/agents/{did}/reputation-bond).
    """
    from ..services import reputation_bond as _rb
    policy = await _rb.policy_json(db)
    amt = Decimal(str(request.amount)) if request.amount else None
    bond = await _rb.deposit(db, current_agent, funder_did=current_agent.did, funded_by="self",
                             actor=f"agent:{current_agent.did}", amount=amt, policy=policy)
    state = await _rb.bond_state(db, current_agent.did, policy=policy, agent=current_agent)
    return {
        "message": "Bond locked" if bond.status == "locked" else f"Bond {bond.status}",
        "bond_id": bond.id,
        "amount": _rb.money_str(bond.amount),
        "currency": frame_currency(),
        "status": bond.status,
        "locked_at": bond.locked_at.isoformat() if bond.locked_at else None,
        "escrow_ref": bond.escrow_ref,
        "teg_transaction_id": bond.teg_transaction_id,
        "reputation": state,
    }


@router.post(
    "/api/v1/agents/reputation-bond/release",
    response_model=Dict[str, Any],
    summary="Release a MATURED bond back to its funder (after the cooldown)",
)
async def release_reputation_bond(
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent),
):
    """Treasury → funder through the blessed treasury helper (fee-free, Δ=0). A bond the
    treasury backstopped is released without a payout. 409 with the progress while the
    bond is not matured or still inside its cooldown."""
    from ..services import reputation_bond as _rb
    bond = await _rb.release(db, current_agent, actor=f"agent:{current_agent.did}")
    return {
        "bond_id": bond.id,
        "status": bond.status,
        "amount": _rb.money_str(bond.amount),
        "currency": frame_currency(),
        "released_at": bond.released_at.isoformat() if bond.released_at else None,
        "paid_to": None if bond.funded_by == "treasury" else (bond.funder_did or current_agent.did),
        "release_teg_transaction_id": bond.release_teg_transaction_id,
    }


@router.post(
    "/api/v1/agents/reputation-bond/unlock",
    response_model=Dict[str, Any],
    summary="At maturity, take the declared share of the bond back and stay bonded",
)
async def unlock_reputation_bond(
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent),
):
    """
    At maturity, pay the frame's declared share of the bond (`enforcement.bond_maturity_releases_percent`, at most
    80) from escrow back to its funder and keep the rest bonded: the agent stays a provider. POST
    /api/v1/agents/reputation-bond/release is the full exit.

    \f
    §BONDFILL-3 — the agent-tier twin of the owner's unlock. Pays the frame's declared share
    (enforcement.bond_maturity_releases_percent, at most 80) escrow → funder and keeps the rest
    bonded; the agent stays a provider. `/release` beside this remains the exit.
    """
    from ..services import reputation_bond as _rb
    bond = await _rb.unlock(db, current_agent, actor=f"agent:{current_agent.did}")
    return {"bond_id": bond.id, "status": bond.status,
            "unlocked": _rb.money_str(bond.partial_released_amount),
            "still_held": _rb.money_str(bond.amount),
            "currency": frame_currency(),
            "unlocked_at": bond.partial_released_at.isoformat() if bond.partial_released_at else None,
            "paid_to": bond.funder_did or current_agent.did,
            "unlock_teg_transaction_id": bond.partial_release_teg_transaction_id,
            "fire": _rb.fire_state(bond.status, bond.partial_released_at)}


@router.get(
    "/api/v1/agents/reputation-bond/status",
    response_model=Dict[str, Any],
    summary="Check bond state and maturity progress",
)
async def get_bond_status(
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent),
):
    """Returns the calling agent's bond (state, funding, ledger ids) and its maturity
    progress; stamps `matured_at` the moment the progress says so. 404 keeps the old
    contract for an agent that never bonded."""
    from ..services import reputation_bond as _rb
    state = await _rb.bond_state(db, current_agent.did, agent=current_agent)
    bond = state["bond"]
    if bond["status"] == "none":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "No reputation bond found for this agent",
                    "required_amount": bond["required_amount"], "currency": bond["currency"],
                    "config": state["config"]},
        )
    prog = bond.get("progress") or {}
    return {
        "bond_id": None,
        "status": bond["status"],
        "amount": bond["amount"],
        "currency": bond["currency"],
        "locked_at": bond["locked_at"],
        "matured_at": bond["matured_at"],
        "released_at": bond["released_at"],
        "funded_by": bond["funded_by"],
        "funder_did": bond["funder_did"],
        "escrow_ref": bond["escrow_ref"],
        "teg_transaction_id": bond["teg_transaction_id"],
        "maturity_conditions_met": bool(prog.get("matured")) if prog else bond["status"] == "matured",
        "maturity_progress": prog or None,
        "reputation": state,
    }


@router.get(
    "/api/v1/fees/current-rate",
    response_model=Dict[str, Any],
    summary="Current transaction fee rate (public)",
)
async def get_current_fee_rate(
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer),
):
    """
    The rates a transfer is charged, as the charge path states them
    (TransactionFeeService.get_current_rate, which the registry card publishes too). This
    route used to read the policy row with literals of its own (1.5 and 7.5): on a row
    without a `transaction_fees` section it reported those while every transfer paid 0.5
    and 5.0.
    """
    from ..services.transaction_fee_service import get_transaction_fee_service
    return await get_transaction_fee_service().get_current_rate(db)
