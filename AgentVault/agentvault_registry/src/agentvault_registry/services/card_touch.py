"""Card touches — the one way row-only state reaches a peer.

A peer's federation pull is incremental (`?since=<cursor>`): a mirrored card refreshes only when the
CARD's updated_at moves. State that lives in a ROW beside the card (a bond, a developer's verification)
therefore never reaches a peer on its own. §REPBOND learned it for the bond (`reputation_bond.touch_native_card`);
§R55 (batch 2, 2026-09-05) found the second instance: `developers.is_verified` rides the envelope as
`developer_verified`, the peer copies it into its shadow developer, and nothing re-exported the cards
when the flag flipped. Touch the developer's native (non-mirrored) cards at that moment.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

NATIVE_ONLY = "(card_data#>>'{federation_metadata,source_registry}') IS NULL"


async def touch_developer_native_cards(db: AsyncSession, developer_id: int, *, reason: str = "") -> int:
    """Move updated_at on every ACTIVE native card the developer owns, so the next federation
    cycle re-exports them (with the developer's current verification). Never a mirror.
    Best-effort by design: a failed touch is logged, never raised into the caller's rail."""
    try:
        res = await db.execute(text(
            "UPDATE agent_cards SET updated_at = NOW() WHERE developer_id = :dev AND is_active = TRUE AND " + NATIVE_ONLY
        ), {"dev": int(developer_id)})
        await db.commit()
        n = res.rowcount or 0
        if n:
            logger.info("[CARDTOUCH] developer %s: %d native card(s) touched%s", developer_id, n, f" ({reason})" if reason else "")
        return n
    except Exception as e:  # noqa: BLE001
        logger.warning("[CARDTOUCH] developer %s touch failed: %s", developer_id, e)
        return 0
