"""V0652 (ac) gwo_2ae43c7789db1e808ea1417f (2026-11-01, agentvault2-14): a pinned status board per room.

The maintainer (the sessions' room, seq 257): "this makes me miss the sequence to evaluate who posts what from just the
chat. i have to go to the guild and look there". An organization's room has ONE board, kept fresh by the room's owner
or the members the owner names (the current release, the open orders, what waits on the owner), pinned above the
history beside the approvals. Its every edit is kept (who, when, the text after it).

The board is conversation state, like the room's rules: a thread's timer and a burn do not touch it. An edit names the
revision it was written against (`base_rev`): one written against an older board is refused, so two editors never
overwrite each other unseen. The owner is the organization's owner (or a member holding the owner role), read live; a
named editor is a principal key (dev:<id>, agt:<did>) the owner listed, honoured only while that principal still belongs
to the organization. An admin flag on an account grants nothing here. Nothing here moves money.
"""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChatBoardRevision, Conversation
from . import chat_service as cs

logger = logging.getLogger(__name__)

BOARD_MAX = 4000
EDITORS_MAX = 20
_KEY_RE = re.compile(r"^(dev:[0-9]{1,12}|agt:did:[a-z0-9]+:[^\s]{1,240})$")


def normalize_editors(keys: Any) -> Tuple[Optional[List[str]], Optional[str]]:
    """The owner's list as stored (each a principal key, lowercased, once, in order), or a refusal reason. Pure."""
    if keys is None:
        return [], None
    if not isinstance(keys, list):
        return None, "editors must be a list of principal keys (dev:<id>, agt:<did>)"
    out: List[str] = []
    for k in keys:
        if not isinstance(k, str):
            return None, "each editor is a principal key (dev:<id>, agt:<did>)"
        k = k.strip().lower()
        if not _KEY_RE.match(k):
            return None, f"{k[:60]!r} is not a principal key (dev:<id>, agt:<did>)"
        if k not in out:
            out.append(k)
    if len(out) > EDITORS_MAX:
        return None, f"at most {EDITORS_MAX} editors"
    return out, None


def board_text_refusal(text: Any) -> Optional[str]:
    """Why a board's text is refused, or None. An empty text clears the board. Pure."""
    if not isinstance(text, str):
        return "text must be a string (markdown; an empty one clears the board)"
    if len(text) > BOARD_MAX:
        return f"the board holds at most {BOARD_MAX} characters"
    return None


async def _room(db: AsyncSession, conversation_id: str) -> Conversation:
    conv = await cs._get_conversation(db, conversation_id)
    if conv.kind != "org" or not conv.org_id:
        raise cs.ChatError(409, "a status board belongs to an organization's room")
    return conv


async def _is_owner(db: AsyncSession, org_id: str, actor: "cs.Actor") -> bool:
    """The organization's owner: its owner_id, or a member holding the owner role (read live, as the room reads it)."""
    if actor.ptype != "developer" or actor.developer_id is None:
        return False
    row = (await db.execute(sa_text("SELECT owner_id FROM organizations WHERE id = :o"), {"o": org_id})).first()
    if row is not None and row[0] is not None and int(row[0]) == int(actor.developer_id):
        return True
    return (await cs.actor_org_role(db, org_id, actor)) == "owner"


async def _still_member(db: AsyncSession, org_id: str, actor: "cs.Actor") -> bool:
    """Still in the organization (the room's own rule: an active member, or an agent assigned to it)."""
    return (await cs.actor_org_role(db, org_id, actor)) is not None


async def authority(db: AsyncSession, conv: Conversation, actor: "cs.Actor") -> Optional[str]:
    """`owner`, `editor` or None, read live: the organization's owner, or a principal the owner named that still
    belongs to the organization."""
    if await _is_owner(db, conv.org_id, actor):
        return "owner"
    try:
        key = cs.principal_key(actor.ptype, actor.sender_id)
    except (ValueError, TypeError):
        return None
    if key in (conv.board_editors or []) and await _still_member(db, conv.org_id, actor):
        return "editor"
    return None


def view(conv: Conversation, names: Dict[str, str], can_edit: bool, is_owner: bool) -> Dict[str, Any]:
    """The board as a member reads it (with whether the reader may edit it, and the editors when the reader owns it)."""
    b = conv.board if isinstance(conv.board, dict) else {}
    by = b.get("updated_by") or {}
    by_key = None
    try:
        by_key = cs.principal_key(by.get("ptype"), by.get("id")) if by.get("ptype") else None
    except (ValueError, TypeError):
        by_key = None
    out: Dict[str, Any] = {"text": b.get("text") or "", "rev": int(b.get("rev") or 0),
                           "updated_at": b.get("updated_at"),
                           "updated_by": ({"ptype": by.get("ptype"), "id": by.get("id"),
                                           "name": names.get(by_key) if by_key else None} if by else None),
                           "can_edit": bool(can_edit)}
    if is_owner:
        out["editors"] = [{"key": k, "name": names.get(k)} for k in (conv.board_editors or [])]
    return out


async def _names(db: AsyncSession, keys: Iterable[Optional[str]]) -> Dict[str, str]:
    ks = [k for k in keys if k]
    return await cs.display_names(db, ks) if ks else {}


async def read_board(db: AsyncSession, conversation_id: str, actor: "cs.Actor") -> Dict[str, Any]:
    """The board, for a member of the room."""
    conv = await _room(db, conversation_id)
    await cs.resolve_membership(db, conv, actor)
    who = await authority(db, conv, actor)
    b = conv.board if isinstance(conv.board, dict) else {}
    by = b.get("updated_by") or {}
    keys = list(conv.board_editors or []) if who == "owner" else []
    if by.get("ptype"):
        try:
            keys.append(cs.principal_key(by["ptype"], by.get("id")))
        except (ValueError, TypeError):
            pass
    out = view(conv, await _names(db, keys), who is not None, who == "owner")
    out["conversation_id"] = conv.id
    return out


async def set_board(db: AsyncSession, conversation_id: str, actor: "cs.Actor", text: Any,
                    base_rev: Any) -> Tuple[Dict[str, Any], Conversation, bool]:
    """Write the board (the owner or a named editor), against the revision the writer read. COMMITS; the caller fans
    the change out. An edit that changes nothing writes nothing."""
    conv = await _room(db, conversation_id)
    await cs.resolve_membership(db, conv, actor)
    who = await authority(db, conv, actor)
    if who is None:
        raise cs.ChatError(403, "the room's owner, or a member the owner named, keeps its status board")
    reason = board_text_refusal(text)
    if reason:
        raise cs.ChatError(422, reason)
    row = (await db.execute(select(Conversation).where(Conversation.id == conv.id).with_for_update())).scalars().first()
    b = dict(row.board) if isinstance(row.board, dict) else {}
    rev = int(b.get("rev") or 0)
    try:
        base = int(base_rev)
    except (TypeError, ValueError):
        raise cs.ChatError(422, "base_rev must be the revision you read (0 for a board never written)")
    if base != rev:
        raise cs.ChatError(409, f"the board changed since you read it (now revision {rev}): read it again")
    text = text.strip()
    if text == (b.get("text") or ""):
        await db.rollback()
        return await read_board(db, conversation_id, actor), conv, False
    when = cs.message_clock()
    rev += 1
    row.board = {"text": text, "rev": rev, "updated_at": when.isoformat(),
                 "updated_by": {"ptype": actor.ptype, "id": actor.sender_id}}
    db.add(ChatBoardRevision(conversation_id=row.id, rev=rev, actor_ptype=actor.ptype, actor_id=actor.sender_id,
                             text=text, created_at=when))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise cs.ChatError(409, "another edit of the board landed at the same moment: read it again")
    return await read_board(db, conversation_id, actor), row, True


async def set_editors(db: AsyncSession, conversation_id: str, actor: "cs.Actor", keys: Any) -> Dict[str, Any]:
    """The owner names who keeps the board with them (principal keys of the organization's members and agents)."""
    conv = await _room(db, conversation_id)
    if not await _is_owner(db, conv.org_id, actor):
        raise cs.ChatError(403, "the room's owner names who keeps its status board")
    editors, reason = normalize_editors(keys)
    if reason:
        raise cs.ChatError(422, reason)
    for k in editors or []:
        kind, ident = k.split(":", 1)
        probe = cs.Actor("developer", developer_id=int(ident)) if kind == "dev" else cs.Actor("agent", agent_did=ident)
        if not await _still_member(db, conv.org_id, probe):
            raise cs.ChatError(422, f"{k[:60]} does not belong to this organization")
    row = (await db.execute(select(Conversation).where(Conversation.id == conv.id).with_for_update())).scalars().first()
    row.board_editors = editors or None
    await db.commit()
    return await read_board(db, conversation_id, actor)


async def board_history(db: AsyncSession, conversation_id: str, actor: "cs.Actor") -> Dict[str, Any]:
    """Every edit of the board, oldest first: when, who (by name), the text after it. A member of the room reads it."""
    conv = await _room(db, conversation_id)
    await cs.resolve_membership(db, conv, actor)
    rows = (await db.execute(select(ChatBoardRevision).where(ChatBoardRevision.conversation_id == conv.id)
                             .order_by(ChatBoardRevision.rev.asc()))).scalars().all()
    keys = []
    for r in rows:
        try:
            keys.append(cs.principal_key(r.actor_ptype, r.actor_id))
        except (ValueError, TypeError):
            pass
    names = await _names(db, keys)
    out = []
    for r in rows:
        try:
            k = cs.principal_key(r.actor_ptype, r.actor_id)
        except (ValueError, TypeError):
            k = None
        out.append({"rev": int(r.rev), "at": r.created_at.isoformat() if isinstance(r.created_at, datetime.datetime)
                    else (str(r.created_at) if r.created_at else None),
                    "by": {"ptype": r.actor_ptype, "id": r.actor_id, "name": names.get(k) if k else None},
                    "text": r.text})
    return {"conversation_id": conv.id, "revisions": out}


async def fan_out_board(conv: Conversation, board: Dict[str, Any], updater: "cs.Actor") -> None:
    """The board's change, after its commit: the WS envelope `chat.board_updated` to the room's members and the
    updater's household, and a wake for waiting syncs. No notice: the board is read where it is pinned."""
    from ..database import get_db_context
    try:
        async with get_db_context() as db:
            recipients = await cs.recipients_snapshot(db, conv, updater)
            owner = updater.developer_id if updater.ptype == "developer" else (
                (await cs.agent_owner_map(db, [updater.agent_did or ""])).get(updater.agent_did or "")
                if updater.agent_did else None)
        from agentvault_registry.routers.websocket import manager
    except Exception as e:  # noqa: BLE001 — the board is stored; its push is a courtesy
        logger.debug("[CHAT] board fan-out for %s skipped: %s", conv.id, e)
        return
    public = {k: v for k, v in board.items() if k not in ("editors", "can_edit")}
    envelope = {"type": "chat.board_updated", "data": {"conversation_id": conv.id, "board": public,
                                                       "actor_name": updater.display_name or ""}}
    devs = {int(r["owner_developer_id"]) for r in recipients if r.get("owner_developer_id") is not None}
    if owner is not None:
        devs.add(int(owner))
    for d in devs:
        try:
            await manager.broadcast_to_subscribers(f"chat:dev:{d}", dict(envelope))
        except Exception as e:  # noqa: BLE001
            logger.debug("[CHAT] WS board update to dev %s failed: %s", d, e)
