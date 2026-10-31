"""V0650 (h) (2026-10-31): server-side @mentions in chat.

Order gwo_2c71fdfcbc1b74d55549ed8d. A message's `@name` tokens resolve to principals of its conversation and are stored
with it (chat_messages.mentions, migration 0201), so a reader can ask for the messages that name it
(GET .../messages?mentions=me) instead of every client scanning every body for its own name.

What a name is, in one place:
  * a participant developer's HANDLE (unique on this registry; the address `@name` already is in the chat routes);
  * a participant agent's CARD NAME, only where exactly one participant carries it (card names are not unique);
  * a participant agent's DID, exactly (the DID is the address, so `@did:...` always resolves).
A handle beats an equal card name. The `@` starts the body or follows a character that is not a letter, digit, `_` or
`@` (an e-mail address is never a mention); the name may not run on into a letter, digit, `_`, `-` or `:` plus a word
character (`@scout` is not `@scouting`; `@Scout:` and `@Scout.` are `@Scout`). Case is ignored and, at one `@`, the
longest name wins. An unknown or ambiguous name, a non-participant, a developer without a handle (display names and
e-mails are never matched) and the sender itself resolve to nothing: a mention is never an error.

The roster is the thread's developer and agent rows in state active or pending (the rows an org room seeds so its
agents are addressable); remote rows are skipped (a peer's principals are not resolved in v1).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import bindparam, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.models import ConversationParticipant
from agentvault_registry.services import chat_service as cs

MENTIONS_MAX = 50          # entries stored per message
ALIAS_MAX = 120            # a longer card name is not something people type after "@"
MENTION_KINDS = ("text", "card")
_RANK = ("did", "handle")  # unique addresses, in the order they win; a card name comes last and must be unique


def _choose(cands: Sequence[Tuple[str, dict]]) -> Optional[dict]:
    """The one principal an alias names, or None. A DID or a handle names one principal by construction; a card name
    only where a single participant carries it."""
    for kind in _RANK:
        hits = {p["key"]: p for k, p in cands if k == kind}
        if hits:
            return next(iter(hits.values())) if len(hits) == 1 else None
    hits = {p["key"]: p for k, p in cands if k == "name"}
    return next(iter(hits.values())) if len(hits) == 1 else None


def resolve_mentions(body: Optional[str], roster: Sequence[dict], sender_key: Optional[str]) -> List[dict]:
    """The principals a body @mentions, in order of first appearance, at most MENTIONS_MAX, never the sender.

    `roster` entries: {key, ptype, developer_id, agent_did, aliases: [(kind, alias), ...]} with kind did|handle|name.
    Each result: {key, ptype, developer_id, agent_did, token} (token: the name as written)."""
    if not body or "@" not in body or not roster:
        return []
    by_alias: Dict[str, List[Tuple[str, dict]]] = {}
    for p in roster:
        for kind, alias in p.get("aliases") or ():
            a = str(alias or "").strip()
            if a and len(a) <= ALIAS_MAX:
                by_alias.setdefault(a.lower(), []).append((kind, p))
    if not by_alias:
        return []
    names = sorted(by_alias, key=len, reverse=True)          # the longest name wins at one "@"
    pattern = re.compile(r"(?<![\w@])@(" + "|".join(re.escape(n) for n in names) + r")(?![\w-]|:\w)",
                         re.IGNORECASE)
    out: List[dict] = []
    seen = set()
    for m in pattern.finditer(body):
        token = m.group(1)
        p = _choose(by_alias.get(token.lower(), ()))
        if p is None or p["key"] == sender_key or p["key"] in seen:
            continue
        seen.add(p["key"])
        out.append({"key": p["key"], "ptype": p["ptype"], "developer_id": p.get("developer_id"),
                    "agent_did": p.get("agent_did"), "token": token})
        if len(out) >= MENTIONS_MAX:
            break
    return out


async def mention_roster(db: AsyncSession, conversation_id: str) -> List[dict]:
    """The thread's addressable principals with their aliases (one participants read, then at most one read of the
    developers' handles and one of the agents' card names)."""
    parts = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conversation_id,
        ConversationParticipant.state.in_(("active", "pending")),
        ConversationParticipant.ptype.in_(("developer", "agent"))))).scalars().all()
    dev_ids = sorted({int(p.developer_id) for p in parts if p.ptype == "developer" and p.developer_id is not None})
    dids = sorted({str(p.agent_did).lower() for p in parts if p.ptype == "agent" and p.agent_did})
    handles: Dict[int, str] = {}
    if dev_ids:
        # resolve_handle's predicate: a deleted or suspended account's handle addresses nobody
        rows = (await db.execute(sa_text(
            "SELECT id, handle FROM developers WHERE id IN :ids AND handle IS NOT NULL "
            "AND deleted_at IS NULL AND is_suspended = false"
        ).bindparams(bindparam("ids", expanding=True)), {"ids": dev_ids})).all()
        handles = {int(r[0]): str(r[1]) for r in rows if r[1]}
    card_names: Dict[str, set] = {}
    if dids:
        # agent names live on agent_cards (the agents table has no name column)
        rows = (await db.execute(sa_text(
            "SELECT agent_did, name FROM agent_cards WHERE lower(agent_did) IN :d"
        ).bindparams(bindparam("d", expanding=True)), {"d": dids})).all()
        for r in rows:
            if r[0] and r[1]:
                card_names.setdefault(str(r[0]).lower(), set()).add(str(r[1]))
    roster: Dict[str, dict] = {}
    for p in parts:
        key = cs.part_key(p)
        if p.ptype == "developer" and p.developer_id is not None:
            h = handles.get(int(p.developer_id))
            roster[key] = {"key": key, "ptype": "developer", "developer_id": int(p.developer_id), "agent_did": None,
                           "aliases": [("handle", h)] if h else []}
        elif p.ptype == "agent" and p.agent_did:
            did = str(p.agent_did)
            roster[key] = {"key": key, "ptype": "agent", "developer_id": None, "agent_did": did,
                           "aliases": [("did", did)] + [("name", n) for n in sorted(card_names.get(did.lower(), ()))]}
    return list(roster.values())


async def mentions_for(db: AsyncSession, conversation_id: str, sender: Any, kind: str, body: Optional[str],
                       rail_author: bool) -> Optional[List[dict]]:
    """What insert_message stores: the resolved mentions of a person's or an agent's text or card body, or None.
    A rail-authored row, a system row and a body without "@" cost nothing (no read at all)."""
    if rail_author or kind not in MENTION_KINDS or not body or "@" not in body:
        return None
    found = resolve_mentions(body, await mention_roster(db, conversation_id), getattr(sender, "key", None))
    return found or None
