"""§REPBOND — the developer-tier, public and admin rails of the reputation bond.

The agent-tier rails (deposit from the agent's own balance, status, release) live
beside the other enforcement self-service routes in `enforcement_agent.py`; the
rule itself is `services/reputation_bond.py`. This file adds:

  GET  /api/v1/reputation-bond/config                       public — amount, mode, thresholds
  GET  /api/v1/agents/{did}/reputation                      public — the `reputation` block for ONE agent
  GET  /api/v1/developers/me/agents/{did}/reputation-bond   owner — state + progress
  POST /api/v1/developers/me/agents/{did}/reputation-bond   owner — bond it FROM A WALLET AGENT
                                                            (`funder_did`, both agents the caller's)
  POST /api/v1/developers/me/agents/{did}/reputation-bond/unlock
                                                            owner — §BONDFILL-3: at maturity, take the
                                                            declared share back and STAY bonded
  POST /api/v1/developers/me/agents/{did}/reputation-bond/backstop
                                                            owner — the DEMONSTRATION path (treasury),
                                                            only while REPUTATION_BOND_TREASURY_BACKSTOP
  GET  /api/v1/admin/reputation-bond/overview               admin — counts by status, unbonded providers
  POST /api/v1/admin/reputation-bond/backstop               admin — bond named DIDs / every unbonded
                                                            provider from the treasury (dry_run first)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.core.frame_currency import frame_currency
from agentvault_registry.models import Agent, AgentCard, Developer
from agentvault_registry.security import get_current_developer
from agentvault_registry.services import reputation_bond as _rb
from agentvault_registry.services import enforcement_propagation as _ep  # §ENFPROP

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Reputation Bond"])


class WalletBondIn(BaseModel):
    funder_did: str = Field(..., description="The agent whose balance funds the bond (your wallet agent, or the agent itself)")
    amount: Optional[str] = Field(None, description="Optional amount ≥ the required bond")


class AdminBackstopIn(BaseModel):
    dids: Optional[List[str]] = Field(None, description="Agents to bond from the treasury")
    all_providers: bool = Field(False, description="Every unbonded local agent whose card declares a price")
    dry_run: bool = Field(True, description="List what WOULD be bonded; nothing is written")
    limit: int = Field(200, ge=1, le=2000)


async def _owned_agent(db: AsyncSession, developer: Developer, did: str) -> Agent:
    res = await db.execute(select(Agent).where(Agent.did == did))
    agent = res.scalar_one_or_none()
    if agent is None or agent.creator_developer_id != developer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No agent {did} in your account")
    return agent


@router.get("/api/v1/reputation-bond/config", summary="The bond this registry asks of a provider (public)")
async def bond_config(db: AsyncSession = Depends(get_db)):
    return _rb.config_block(await _rb.policy_json(db))


@router.get("/api/v1/agents/{did}/reputation", summary="An agent's reputation block: bond, maturity, volume (public)")
async def agent_reputation(did: str, db: AsyncSession = Depends(get_db)):
    agent = await _rb.load_agent(db, did)
    if agent is not None:
        state = await _rb.bond_state(db, did)
        state["staked"] = str(agent.staked_balance or 0)
        state["source"] = "registry"
        state["enforcement"] = await _ep.enforcement_block(db, did)  # §ENFPROP
        return state
    # a mirrored card of a foreign agent: what its home registry signed onto the card
    res = await db.execute(
        select(AgentCard.card_data).where(AgentCard.agent_did == did, AgentCard.is_active == True)  # noqa: E712
        .order_by(AgentCard.updated_at.desc()).limit(1)
    )
    cd = res.scalar_one_or_none()
    if cd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Agent {did} is not known to this registry")
    p = _rb.extension_from_card(cd) or {}
    st = p.get("status") or "none"
    return {
        "agent_did": did,
        "bond": {"status": st, "is_bonded": _rb.is_bonded_status(st), "amount": _rb.money_str(p.get("amount")),
                 "currency": p.get("currency"), "locked_at": p.get("locked_at"),
                 "matured_at": p.get("matured_at"), "funded_by": p.get("funded_by"),
                 "progress": None, "source": "card", "registry": p.get("registry")},
        "is_bonded": _rb.is_bonded_status(st), "volume": None, "transactions": None,
        "eigentrust": None, "mode": _rb.bond_mode(), "source": "card",
        "enforcement": await _ep.enforcement_block(db, did),  # §ENFPROP
    }


@router.get("/api/v1/developers/me/agents/{did}/reputation-bond", summary="Your agent's bond state and progress")
async def my_agent_bond(did: str, db: AsyncSession = Depends(get_db),
                        developer: Developer = Security(get_current_developer)):
    agent = await _owned_agent(db, developer, did)
    return await _rb.bond_state(db, did, agent=agent)


@router.post("/api/v1/developers/me/agents/{did}/reputation-bond",
             summary="Bond your agent from a wallet agent you own (the birth-flow door)")
async def bond_from_wallet(did: str, body: WalletBondIn, db: AsyncSession = Depends(get_db),
                           developer: Developer = Security(get_current_developer)):
    """Units: funder → treasury through the escrow deposit rail, idempotent reference on
    the row. Both agents must be the caller's; funding an agent from itself is `self`."""
    agent = await _owned_agent(db, developer, did)
    funder = await _owned_agent(db, developer, body.funder_did)
    funded_by = "self" if funder.did == agent.did else "wallet"
    amt = Decimal(str(body.amount)) if body.amount else None
    policy = await _rb.policy_json(db)
    bond = await _rb.deposit(db, agent, funder_did=funder.did, funded_by=funded_by,
                             actor=f"developer:{developer.id}", amount=amt, policy=policy)
    state = await _rb.bond_state(db, did, policy=policy, agent=agent)
    return {"bond_id": bond.id, "status": bond.status, "amount": _rb.money_str(bond.amount),
            "funded_by": bond.funded_by, "funder_did": bond.funder_did,
            "escrow_ref": bond.escrow_ref, "teg_transaction_id": bond.teg_transaction_id,
            "reputation": state}


@router.post("/api/v1/developers/me/agents/{did}/reputation-bond/unlock",
             summary="At maturity, take the declared share of your agent's bond back and stay bonded")
async def unlock_my_agent_bond(did: str, db: AsyncSession = Depends(get_db),
                               developer: Developer = Security(get_current_developer)):
    """
    The owner's door to the maturity unlock: pay the frame's declared share of the agent's bond back to its funder
    and keep the rest bonded, so the agent keeps providing. Releasing everything is POST
    /api/v1/agents/reputation-bond/release. A 409 names the one reason it cannot happen yet (not matured, cooldown,
    already unlocked, a treasury-backstopped bond, or a registry that releases nothing at maturity).

    \f
    §BONDFILL-3 — the owner's door to the maturity unlock. The agent keeps trading on the
    remainder; releasing everything is still `/api/v1/agents/reputation-bond/release`, the EXIT.
    409 names the one reason it cannot happen yet (not matured, cooldown, already unlocked, a
    treasury-backstopped bond, or a registry that releases nothing at maturity).
    """
    agent = await _owned_agent(db, developer, did)
    policy = await _rb.policy_json(db)
    bond = await _rb.unlock(db, agent, actor=f"developer:{developer.id}", policy=policy)
    state = await _rb.bond_state(db, did, policy=policy, agent=agent)
    out = {"bond_id": bond.id, "status": bond.status,
            "unlocked": _rb.money_str(bond.partial_released_amount),
            "still_held": _rb.money_str(bond.amount),
            "currency": frame_currency(),
            "unlocked_at": bond.partial_released_at.isoformat() if bond.partial_released_at else None,
            "paid_to": bond.funder_did or agent.did,
            "unlock_teg_transaction_id": bond.partial_release_teg_transaction_id,
            "fire": _rb.fire_state(bond.status, bond.partial_released_at)}
    out["reputation"] = state
    return out


@router.post("/api/v1/developers/me/agents/{did}/reputation-bond/backstop",
             summary="Bond your agent from the treasury (demonstration backstop, while the registry allows it)")
async def bond_backstop(did: str, db: AsyncSession = Depends(get_db),
                        developer: Developer = Security(get_current_developer)):
    if not _rb.treasury_backstop_enabled():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="This registry does not backstop bonds from its treasury. Fund the bond from the "
                   "agent's balance or from a wallet agent you own.")
    agent = await _owned_agent(db, developer, did)
    policy = await _rb.policy_json(db)
    bond = await _rb.backstop(db, agent, actor=f"developer:{developer.id}", policy=policy)
    state = await _rb.bond_state(db, did, policy=policy, agent=agent)
    return {"bond_id": bond.id, "status": bond.status, "amount": _rb.money_str(bond.amount),
            "funded_by": bond.funded_by,
            "note": "Demonstration: the treasury underwrote this bond. It is planned that a bond "
                    "comes out of the genesis grant or your own income; a backstopped bond pays "
                    "nothing back on release.",
            "reputation": state}


_PROVIDERS_SQL = text("""
SELECT a.did, a.reputation_bond_status, c.card_data
  FROM agents a
  JOIN LATERAL (
        SELECT card_data FROM agent_cards ac
         WHERE ac.agent_did = a.did AND ac.is_active = TRUE
           AND (ac.card_data#>>'{federation_metadata,source_registry}') IS NULL
         ORDER BY ac.updated_at DESC LIMIT 1
       ) c ON TRUE
 WHERE a.status = 'active'
   AND COALESCE(a.reputation_bond_status, 'none') NOT IN ('locked', 'matured')
 ORDER BY a.created_at ASC
 LIMIT :lim
""")


async def _unbonded_providers(db: AsyncSession, limit: int) -> List[str]:
    res = await db.execute(_PROVIDERS_SQL, {"lim": max(limit * 20, 2000)})
    out: List[str] = []
    for r in res.mappings().all():
        if _rb.is_paid_card(r["card_data"]):
            out.append(r["did"])
            if len(out) >= limit:
                break
    return out


@router.get("/api/v1/admin/reputation-bond/overview", summary="Bond population by status; unbonded providers")
async def admin_overview(db: AsyncSession = Depends(get_db),
                         admin: Developer = Security(security.require_admin_flag("admin_enforcement"))):
    res = await db.execute(text("SELECT status, COUNT(*) AS n, COALESCE(SUM(amount),0) AS total FROM reputation_bonds GROUP BY status"))
    by_status = {r["status"]: {"count": int(r["n"]), "total": str(r["total"])} for r in res.mappings().all()}
    unbonded = await _unbonded_providers(db, 2000)
    return {"config": _rb.config_block(await _rb.policy_json(db)), "by_status": by_status,
            "unbonded_providers": len(unbonded), "unbonded_provider_sample": unbonded[:25]}


@router.post("/api/v1/admin/reputation-bond/backstop",
             summary="Bond agents from the treasury (existing providers get their bond this way)")
async def admin_backstop(body: AdminBackstopIn, db: AsyncSession = Depends(get_db),
                         admin: Developer = Security(security.require_admin_flag("admin_enforcement"))):
    """The Commander's answer 5 (2026-09-05): existing agents get the bond from the treasury.
    Treasury-backstopped bonds move no money (the treasury keeps its own escrow); they make
    the running providers pass the gate and show the bond in discovery. `dry_run` lists first."""
    dids: List[str] = list(body.dids or [])
    if body.all_providers:
        dids += [d for d in await _unbonded_providers(db, body.limit) if d not in dids]
    policy = await _rb.policy_json(db)
    results: List[Dict[str, Any]] = []
    for did in dids[: body.limit]:
        agent = await _rb.load_agent(db, did)
        if agent is None:
            results.append({"did": did, "result": "unknown"})
            continue
        if _rb.is_bonded_status(agent.reputation_bond_status):
            results.append({"did": did, "result": "already_bonded", "status": agent.reputation_bond_status})
            continue
        if body.dry_run:
            results.append({"did": did, "result": "would_bond", "amount": _rb.money_str(_rb.bond_amount(policy))})
            continue
        try:
            bond = await _rb.backstop(db, agent, actor=f"admin:{admin.id}", policy=policy)
            results.append({"did": did, "result": "bonded", "bond_id": bond.id, "amount": _rb.money_str(bond.amount)})
        except Exception as e:  # noqa: BLE001 — one failure must not hide the others; it is reported per DID
            logger.error("[REPBOND] admin backstop failed for %s: %s", did, e)
            await db.rollback()
            results.append({"did": did, "result": "error", "detail": str(e)[:200]})
    try:
        from agentvault_registry.routers.admin_helpers import log_admin_action  # type: ignore
    except Exception:  # noqa: BLE001
        log_admin_action = None
    if log_admin_action and not body.dry_run:
        try:
            await log_admin_action(db, admin.id, "reputation_bond.backstop",
                                   {"count": len(results), "all_providers": body.all_providers})
        except Exception:  # noqa: BLE001
            pass
    counts: Dict[str, int] = {}
    for r in results:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    return {"dry_run": body.dry_run, "mode": _rb.bond_mode(), "amount": _rb.money_str(_rb.bond_amount(policy)),
            "counts": counts, "results": results}
