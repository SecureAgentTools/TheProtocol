"""CRUD operations for Agent entities."""
import logging
from typing import Optional, Tuple
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent
# Note: We'll import the password functions when needed to avoid circular imports

logger = logging.getLogger(__name__)

# `last_active_at` heartbeat throttle. Process-local by design: with N workers the worst case is
# N writes per agent per interval instead of one per request, which is still ~1% of the previous
# traffic and needs no coordination to achieve.
_LAST_SEEN: dict = {}
_HEARTBEAT_INTERVAL_S = 60.0
_LAST_SEEN_MAX = 20000


async def get_agent_by_client_id(db: AsyncSession, client_id: str) -> Optional[Agent]:
    """
    Retrieve an agent by their client ID.
    
    Args:
        db: Database session
        client_id: The OAuth client ID of the agent
        
    Returns:
        Agent instance if found, None otherwise
    """
    result = await db.execute(
        select(Agent).where(Agent.client_id == client_id)
    )
    return result.scalar_one_or_none()


async def get_agent_by_did(db: AsyncSession, did: str) -> Optional[Agent]:
    """
    Retrieve an agent by their DID.
    
    Args:
        db: Database session
        did: The DID of the agent
        
    Returns:
        Agent instance if found, None otherwise
    """
    result = await db.execute(
        select(Agent).where(Agent.did == did)
    )
    return result.scalar_one_or_none()


async def create_agent(
    db: AsyncSession,
    did: str,
    client_id: str,
    client_secret: str,
    creator_developer_id: int,
    public_key_jwk: Optional[dict] = None,
    commit: bool = True,
) -> Agent:
    """
    Create a new agent in the database.

    Args:
        db: Database session
        did: The DID for the agent
        client_id: OAuth client ID
        client_secret: Plain text client secret (will be hashed)
        creator_developer_id: ID of the developer creating the agent
        public_key_jwk: Optional public key in JWK format
        commit: COMMIT the agent row here (default, unchanged for every existing caller),
            or only FLUSH it so the caller's transaction still owns it.

            §FRAMELIC (2026-09-07, findings row 151). Committing here made the caller's
            own `await db.rollback()` a no-op: `/onboard/create_agent` creates the agent,
            then the card, and rolls back if the card is invalid — but the agent was
            already committed, so a request REFUSED with 400 "Invalid agent card" still
            minted a DID, client credentials, a wallet and IRONKEY birth roles, with no
            card. Measured on the EU frame: 11 such agents from one failed pass, and a
            live control reproduced it (400 returned, agent count +1). A caller that
            creates a card in the same request passes commit=False so its rollback is real.

            Callers that deliberately KEEP a cardless agent pass nothing and are unaffected:
            /agents/spawn (the child's authority rides its birth token, card non-fatal) and
            the fiat wallet flow (the buyer paid; an agent without a card beats no agent).

    Returns:
        The created Agent instance
    """
    # Import here to avoid circular dependency
    from ..security import hash_password
    
    # Hash the client secret
    hashed_secret = hash_password(client_secret)
    
    # Create the agent
    agent = Agent(
        did=did,
        client_id=client_id,
        hashed_client_secret=hashed_secret,
        creator_developer_id=creator_developer_id,
        public_key_jwk=public_key_jwk,
        status="active"
    )
    
    db.add(agent)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(agent)

    logger.info(f"Created new agent with DID: {did}, client_id: {client_id}")
    return agent


async def agent_credentials_status(db: AsyncSession, client_id: str, client_secret: str) -> Tuple[Optional[Agent], str]:
    """§TWOAGENT (2026-09-23): verify the SECRET first, then the status, and say which one failed.

    Returns (agent, "ok"), (None, "invalid") for an unknown client or a wrong secret, or (None, "suspended" / "revoked")
    for an agent whose secret is RIGHT but whose registry has stopped it. The status is only ever told to a caller
    that proved the secret, so a client_id alone cannot probe whether an agent is suspended. Measured before: a
    suspended agent's own correct credentials answered 401 "Invalid client credentials", word for word what a wrong
    secret gets, so its runtime could not tell "I was suspended" from "my secret broke" (and keeps retrying).
    """
    from ..security import verify_password
    agent = await get_agent_by_client_id(db, client_id)
    if not agent:
        logger.warning(f"Agent not found for client_id: {client_id}")
        return None, "invalid"
    if not verify_password(client_secret, agent.hashed_client_secret):
        logger.warning(f"Invalid client_secret for agent {client_id}")
        return None, "invalid"
    if agent.status in ("suspended", "revoked"):
        logger.warning(f"Agent {client_id} is blocked (status: {agent.status})")
        return None, agent.status
    await update_agent_last_active(db, agent.id)
    return agent, "ok"


async def verify_agent_credentials(
    db: AsyncSession,
    client_id: str,
    client_secret: str
) -> Optional[Agent]:
    """
    Verify agent credentials and return the agent if valid.
    
    Args:
        db: Database session
        client_id: OAuth client ID
        client_secret: Plain text client secret to verify
        
    Returns:
        Agent instance if credentials are valid, None otherwise
    """
    # Same contract as ever (None on ANY failure); the reason lives in agent_credentials_status.
    # Seen-marker only, on the same best-effort path as every other request. It used to write
    # and COMMIT the caller's session here, which is what turned row contention on a timestamp
    # into a 500 on token minting — the one endpoint an agent cannot route around.
    agent, _why = await agent_credentials_status(db, client_id, client_secret)
    return agent


async def update_agent_last_active(db: AsyncSession, agent_id: int) -> None:
    """Record that an agent was seen. BEST-EFFORT — it must never fail a request.

    This runs inside `get_current_agent`, i.e. on EVERY agent-authenticated request. Three
    properties matter, and the previous version had none of them:

    1. **It cannot fail the caller.** The database carries `lock_timeout=10s`, so when the row
       was contended this UPDATE raised `LockNotAvailableError` (55P03) *inside the auth
       dependency* and the whole request 500'd. Observed on `/auth/agent/token` and
       `/teg/balance` after the V0163 roll, when ~600 sim agents re-authenticated at once
       against a cold registry. The §V0151 lock RCA fixed the other end of this — the health
       checker that HELD the locks — and left the victim exposed. A heartbeat column must
       never be able to reject an authentication.
    2. **It does not use the caller's session.** Committing the request's transaction from an
       auth dependency also commits whatever else that request had pending, and it dragged the
       row lock into the request's lifetime.
    3. **It does not write on every request.** Per-request granularity on a "last seen"
       timestamp buys nothing and was the source of the contention. One write per agent per
       minute is the same information at ~1% of the row traffic.
    """
    import time as _time

    now = _time.monotonic()
    prev = _LAST_SEEN.get(agent_id)
    if prev is not None and (now - prev) < _HEARTBEAT_INTERVAL_S:
        return
    # Claim the slot BEFORE writing: if the write fails we still wait a full interval rather
    # than letting every request retry into the same contended row.
    _LAST_SEEN[agent_id] = now
    if len(_LAST_SEEN) > _LAST_SEEN_MAX:
        cutoff = now - _HEARTBEAT_INTERVAL_S
        for k in [k for k, v in _LAST_SEEN.items() if v < cutoff]:
            _LAST_SEEN.pop(k, None)

    try:
        from ..database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as hb:
            # Give up in 250ms instead of queueing to the 10s database ceiling: a stale
            # heartbeat is worth nothing, and waiting for one costs a request.
            await hb.execute(text("SET LOCAL lock_timeout = '250ms'"))
            await hb.execute(
                text("UPDATE agents SET last_active_at = now() WHERE id = :i"),
                {"i": agent_id},
            )
            await hb.commit()
    except Exception as exc:  # noqa: BLE001 — deliberately total
        logger.debug("last_active_at heartbeat skipped for agent %s: %s", agent_id, exc)
