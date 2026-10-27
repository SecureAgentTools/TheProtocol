"""§MEMBERSHIP (2026-10-02): who the members of this registry are, and am I one.

Two reads, no writes. Membership is derived from the reputation bond (services/membership.py), so there is
nothing to join here: you become a member by posting the bond for one of your agents and waiting
GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS, and you stop being one when the bond is released or forfeited.

    GET /api/v1/membership/stats   public: how many members, joined and left in 30 days, the rules
    GET /api/v1/membership/me      your developer: member or not, since when, weight, what is missing

Both answer in either GOVERNANCE_WEIGHT_MODE: a lock-mode registry still has members (the bond exists
there too); `mode` says whether they are what weighs a vote.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Security
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import get_db
from agentvault_registry.models import Developer
from agentvault_registry.security import get_current_developer
from agentvault_registry.services import membership as _membership

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Membership"])


@router.get("/api/v1/membership/stats", summary="Members of this registry: count, 30-day flow, the rules (public)")
async def membership_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Counts only: no member is named here. The registry board reads this for each registry."""
    return await _membership.stats(db)


@router.get("/api/v1/membership/me", summary="Am I a member of this registry, and if not, what is missing")
async def my_membership(
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await _membership.status_for_developer(db, developer)
