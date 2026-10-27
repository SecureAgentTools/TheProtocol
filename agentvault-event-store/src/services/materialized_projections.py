"""
Materialized Balance Projections — Phase 1 Scaling
Reads from the trigger-maintained materialized_balances table
instead of replaying events. O(1) lookups vs O(n) replay.

Tables are maintained by a PostgreSQL AFTER INSERT trigger on the events table.
See migrations/materialized_balances.sql for the trigger definition.

Fallback: when MATERIALIZED_BALANCES=false (or table doesn't exist),
the caller falls back to the original event-replay path.
"""
import logging
import os
from decimal import Decimal
from typing import Optional, List, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MATERIALIZED_ENABLED = os.getenv('MATERIALIZED_BALANCES', 'true').lower() == 'true'


async def get_materialized_balance(db_session: AsyncSession, agent_did: str) -> Optional[dict]:
    """Get a single agent's balance from the materialized table. O(1)."""
    if not MATERIALIZED_ENABLED:
        return None

    try:
        result = await db_session.execute(
            text(
                "SELECT liquid_balance, staked_balance, event_count, last_event_timestamp "
                "FROM materialized_balances WHERE agent_did = :did"
            ),
            {"did": agent_did}
        )
        row = result.fetchone()
        if row:
            return {
                "agent_did": agent_did,
                "liquid_balance": Decimal(str(row[0])),
                "staked_balance": Decimal(str(row[1])),
                "event_count": row[2],
                "last_event_timestamp": row[3],
            }
        return None
    except Exception as e:
        logger.warning(f"[Materialized] Balance lookup failed for {agent_did}: {e}")
        return None


async def get_all_materialized_balances(db_session: AsyncSession) -> Optional[List[dict]]:
    """Get all agent balances from materialized table. For supply audit.
    Returns None (not empty list) on failure so caller can distinguish
    'no data' from 'feature disabled / error'.
    """
    if not MATERIALIZED_ENABLED:
        return None

    try:
        result = await db_session.execute(
            text(
                "SELECT agent_did, liquid_balance, staked_balance, event_count, last_event_timestamp "
                "FROM materialized_balances ORDER BY agent_did"
            )
        )
        rows = result.fetchall()
        return [
            {
                "agent_did": row[0],
                "liquid_balance": Decimal(str(row[1])),
                "staked_balance": Decimal(str(row[2])),
                "event_count": row[3],
                "last_event_timestamp": row[4],
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"[Materialized] All balances lookup failed: {e}")
        return None


async def get_supply_summary(db_session: AsyncSession) -> Optional[dict]:
    """Get supply summary from the trigger-maintained singleton row.
    Returns None on failure so caller can fall back to event-replay.
    """
    if not MATERIALIZED_ENABLED:
        return None

    try:
        result = await db_session.execute(
            text(
                "SELECT tokens_issued, tokens_destroyed, tokens_fees_collected, "
                "tokens_minted_compensation, total_events, updated_at, "
                "COALESCE(transit_net, 0) "  # §B: non-supply (transfer / cross-frame) net accumulator
                "FROM supply_summary WHERE id = 1"
            )
        )
        row = result.fetchone()
        if row:
            tokens_issued = Decimal(str(row[0]))
            tokens_destroyed = Decimal(str(row[1]))
            tokens_fees_collected = Decimal(str(row[2]))
            tokens_minted_compensation = Decimal(str(row[3]))
            transit_net = Decimal(str(row[6]))  # §B
            return {
                "tokens_issued": str(tokens_issued + tokens_minted_compensation),
                "tokens_destroyed": str(tokens_destroyed),
                "tokens_fees_collected": str(tokens_fees_collected),
                "transit_net": str(transit_net),  # §B
                # §B: per-frame invariant is tokens_issued − tokens_destroyed + transit_net = circulating.
                "net_supply": str(tokens_issued + tokens_minted_compensation - tokens_destroyed + transit_net),
                "total_events": row[4],
                "updated_at": str(row[5]) if row[5] else None,
            }
        return None
    except Exception as e:
        logger.warning(f"[Materialized] Supply summary lookup failed: {e}")
        return None
