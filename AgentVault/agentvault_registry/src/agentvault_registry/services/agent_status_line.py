"""V0650 (a) (2026-10-31, agentvault2-14): an agent's status line, and an organization's presence.

An agent says what it is doing in one line (up to 140 characters) that expires on its own (1 second to a day, an hour by
default): PUT /api/v1/agents/me/status. Its organization's members and agents read the organization's presence: every
agent assigned to it, with its card name, its owner, when it was last active, its account status and its live line
(GET /api/v1/organizations/{org_id}/presence). A line past its expiry reads as no line, and so does a suspended agent's.

Every member of the organization reads a status line, so a line that carries a credential's shape is refused (the
MCP audit sanitizer's own screen), and so is one with a control character (a newline, a NUL). Portable SQL only: the
tests read real SQLite rows. Nothing here moves money.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, AgentCard, AgentStatusLine

MAX_TEXT = 140
MAX_TTL_S = 86400
DEFAULT_TTL_S = 3600
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _utc(ts: Optional[_dt.datetime]) -> Optional[_dt.datetime]:
    """SQLite hands back naive datetimes; Postgres aware ones. Both read as UTC."""
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)


def clean_text(value: Any) -> str:
    """The line as stored, or ValueError with the reason (a body validator turns it into a 422)."""
    t = str(value if value is not None else "").strip()
    if not t:
        raise ValueError("a status line needs some text")
    if len(t) > MAX_TEXT:
        raise ValueError(f"a status line is at most {MAX_TEXT} characters")
    if _CONTROL_RE.search(t):
        raise ValueError("a status line is one line of text: no newline or control character")
    from ..mcp.audit_sanitizer import redact_text_shapes
    if redact_text_shapes(t) != t:
        raise ValueError("a status line may not carry anything shaped like a credential: every member of the "
                         "organization reads it")
    return t


def live_line(row: Optional[AgentStatusLine], now: Optional[_dt.datetime] = None) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    now = now or _now()
    expires = _utc(row.expires_at)
    if expires is None or expires <= now:
        return None
    set_at = _utc(row.set_at)
    return {"text": row.status_text, "set_at": set_at.isoformat() if set_at else None,
            "expires_at": expires.isoformat(), "expires_in_seconds": int((expires - now).total_seconds())}


async def set_line(db: AsyncSession, agent_did: str, text: str, ttl_seconds: int = DEFAULT_TTL_S) -> Dict[str, Any]:
    text = clean_text(text)
    ttl = max(1, min(int(ttl_seconds or DEFAULT_TTL_S), MAX_TTL_S))
    now = _now()
    for attempt in (1, 2):
        row = await db.get(AgentStatusLine, agent_did)
        if row is None:
            row = AgentStatusLine(agent_did=agent_did, status_text=text, set_at=now,
                                  expires_at=now + _dt.timedelta(seconds=ttl))
            db.add(row)
        else:
            row.status_text, row.set_at = text, now
            row.expires_at = now + _dt.timedelta(seconds=ttl)
        try:
            await db.commit()
            break
        except IntegrityError:
            # Two writes of one agent's first line raced: the other row exists now; write over it once.
            await db.rollback()
            if attempt == 2:
                raise
    return live_line(row, now) or {}


async def read_line(db: AsyncSession, agent_did: str) -> Optional[Dict[str, Any]]:
    return live_line(await db.get(AgentStatusLine, agent_did))


async def org_presence(db: AsyncSession, org_id: str) -> Dict[str, Any]:
    """Every agent assigned to the organization (a revoked agent is no longer present), oldest first."""
    now = _now()
    rows = (await db.execute(
        select(Agent, AgentStatusLine)
        .outerjoin(AgentStatusLine, AgentStatusLine.agent_did == Agent.did)
        .where(Agent.organization_id == org_id, Agent.status != "revoked")
        .order_by(Agent.created_at, Agent.id)
    )).all()
    dids = [a.did for a, _ in rows]
    names: Dict[str, str] = {}
    if dids:
        for did, name in (await db.execute(
                select(AgentCard.agent_did, AgentCard.name).where(AgentCard.agent_did.in_(dids))
                .order_by(AgentCard.is_active.desc(), AgentCard.created_at))).all():
            names.setdefault(did, name)
    agents: List[Dict[str, Any]] = []
    for a, line in rows:
        last = _utc(a.last_active_at)
        agents.append({
            "did": a.did,
            "name": names.get(a.did),
            "owner_developer_id": a.creator_developer_id,
            "last_active_at": last.isoformat() if last else None,
            "account_status": a.status,
            "status": live_line(line, now) if a.status == "active" else None,
        })
    return {"organization_id": org_id, "as_of": now.isoformat(), "agents": agents, "count": len(agents)}
