"""V0657 (a), item 9: a dispute's parties as a ruler reads them, not as eight characters of a DID.

Each party: its name (agent display names live on agent_cards, which covers local agents and federated mirrors; the
agents table has no name column), its owner (the developer's name, else @handle: never an e-mail address, the rule of
services/chat_service.display_names) for an agent of this registry, and its home (this registry, or the registry a
mirrored card names). A DID nobody names stays its DID, never a blank.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def names_for(db: AsyncSession, dids: Iterable[str]) -> Dict[str, Optional[str]]:
    """DID -> its card's name (None when no card names it)."""
    wanted = [d for d in dict.fromkeys(dids or []) if d]
    out: Dict[str, Optional[str]] = {d: None for d in wanted}
    if not wanted:
        return out
    rows = (await db.execute(text("SELECT agent_did, name FROM agent_cards WHERE lower(agent_did) = ANY(:d)"),
                             {"d": [d.lower() for d in wanted]})).all()
    by_lower = {d.lower(): d for d in wanted}
    for r in rows:
        did = by_lower.get(str(r[0]).lower())
        if did and r[1]:
            out[did] = r[1]
    return out


async def parties(db: AsyncSession, dids: Iterable[str]) -> Dict[str, Dict[str, Optional[str]]]:
    """DID -> {did, name, owner, home}."""
    wanted = [d for d in dict.fromkeys(dids or []) if d]
    names = await names_for(db, wanted)
    out: Dict[str, Dict[str, Optional[str]]] = {
        d: {"did": d, "name": names.get(d), "owner": None, "home": None} for d in wanted}
    if not wanted:
        return out
    rows = (await db.execute(text(
        "SELECT a.did, COALESCE(NULLIF(trim(v.name), ''), '@' || NULLIF(trim(v.handle), ''), 'dev ' || v.id) "
        "FROM agents a LEFT JOIN developers v ON v.id = a.creator_developer_id WHERE a.did = ANY(:d)"),
        {"d": wanted})).all()
    for r in rows:
        if r[0] in out:
            out[r[0]]["owner"] = r[1]
            out[r[0]]["home"] = "this registry"
    rest = [d for d in wanted if out[d]["home"] is None]
    if rest:
        rows = (await db.execute(text(
            "SELECT agent_did, card_data -> 'federation_metadata' ->> 'source_registry' FROM agent_cards "
            "WHERE agent_did = ANY(:d)"), {"d": rest})).all()
        for r in rows:
            if r[0] in out and r[1]:
                out[r[0]]["home"] = r[1]
    return out
