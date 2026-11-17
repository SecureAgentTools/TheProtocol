"""V0664 (order gwo_48ac3a9ec2ab8bb3d5643c92, the sessions' room, seq 3638): no self-dealing on ordinary Guild orders.

A Guild order is for someone else's work. A bid or an award whose worker, payee agent or paid organization belongs to the developer
who posted the order would pay the poster's own developer (a rating folded between its own agents, an escrow moved from one of its
agents to another); it is refused, before any collateral or escrow, with a sentence that says why. Governed code has had the same
rule since slice 2 (services/code_changes.py `_own_bounty`).

GUILD_SELF_DEALING_MODE: `enforce` (the default, and the word for any value this module does not know), `shadow` (the same
decision, logged and never refused) or `off`. The session room on EU runs `shadow` for as long as the sessions' agents all belong to
one developer account (session-lead, room seq 3652); the sandbox enforces. Deny-only and Δ-irrelevant: nothing moves here.

An agent this registry holds no row for (another registry's) has no developer here and passes: the home registry vouches for its own.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MODES = ("off", "shadow", "enforce")
SENTENCE = ("this order would pay or rate the poster's own developer (the worker, its payee agent or the organization it pays "
            "belongs to the developer who posted it): a Guild order is for someone else's work, so the poster's own agents "
            "do not bid on it or win it")


def mode() -> str:
    word = str(os.getenv("GUILD_SELF_DEALING_MODE", "enforce")).strip().lower()
    return word if word in MODES else "enforce"


async def _developer_of_agent(db: AsyncSession, did: Optional[str]) -> Optional[int]:
    if not did:
        return None
    return (await db.execute(text("SELECT creator_developer_id FROM agents WHERE did = :d"), {"d": did})).scalar()


async def refusal(db: AsyncSession, order: Dict[str, Any], *, worker_did: Optional[str], payee_did: Optional[str] = None,
                  org_id: Optional[str] = None) -> Optional[str]:
    """The sentence refusing a worker, payee agent or paid organization that belongs to the poster's developer, else None."""
    poster_dev = await _developer_of_agent(db, order.get("poster_did"))
    if poster_dev is None:
        return None
    for did in (worker_did, payee_did):
        if did and await _developer_of_agent(db, did) == poster_dev:
            return SENTENCE
    if org_id:
        owner = (await db.execute(text("SELECT owner_id FROM organizations WHERE id = :o"), {"o": org_id})).scalar()
        if owner is not None and owner == poster_dev:
            return SENTENCE
    return None


async def gate(db: AsyncSession, order: Dict[str, Any], *, worker_did: Optional[str], payee_did: Optional[str] = None,
               org_id: Optional[str] = None, stage: str) -> None:
    """Deny-only, before any collateral or escrow. `stage`: bid or award. Raises 403 under enforce; logs under shadow."""
    m = mode()
    if m == "off":
        return
    why = await refusal(db, order, worker_did=worker_did, payee_did=payee_did, org_id=org_id)
    if not why:
        return
    logger.warning("[GUILD] self-dealing at %s on %s (mode %s): worker %s payee %s org %s, poster %s", stage, order.get("id"), m,
                   worker_did, payee_did, org_id, order.get("poster_did"))
    if m == "enforce":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=why)
