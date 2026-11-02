"""V0653: org.session_offline, a session went quiet (session-lead, the sessions' room seq 716; his approval of the missing
notices, the gaps file sessionlogs2026/NOTIFICATION_GAPS_2026-10-31.md: "in-app (a session's status line expired)").

An agent assigned to an organization says what it does in a status line that expires on its own (V0650 (a),
services/agent_status_line.py). When a line expires and is not renewed, the session went quiet, and its owner hears it
once, in the app (org.session_offline, the catalog's default). A leader-elected sweep every minute reads the lines of
active agents assigned to an organization whose expiry fell in the last WINDOW_S (a line that lapsed while no worker
ran for longer than that is not announced late), and marks each (agent, expiry) told in Redis before it notifies:
without Redis it tells nobody rather than telling twice. A line renewed in time never fires; a new line after a quiet
spell starts over. Portable SQL (the expiry is compared in Python, as agent_status_line reads it). Nothing here moves
money. SESSION_OFFLINE_WATCH_ENABLED=false keeps it off.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

INTERVAL_S = int(os.getenv("SESSION_OFFLINE_INTERVAL_SECONDS", "60"))
WINDOW_S = 900
MARK_TTL_S = 86400
_task: Optional[asyncio.Task] = None
_stop = False


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _utc(ts: Optional[_dt.datetime]) -> Optional[_dt.datetime]:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)


def mark_key(agent_did: str, expires_at: _dt.datetime) -> str:
    """One mark per line that lapsed: the agent and the second its line expired."""
    return f"notify:session_offline:{agent_did}:{int(expires_at.timestamp())}"


async def lapsed_lines(db, now: _dt.datetime, window_s: int = WINDOW_S) -> List[Dict[str, Any]]:
    """The lines that expired in (now - window_s, now] of active agents assigned to an organization, oldest first, each
    with the agent's card name and its owner."""
    from agentvault_registry.models import Agent, AgentCard, AgentStatusLine
    rows = (await db.execute(
        select(AgentStatusLine, Agent)
        .join(Agent, Agent.did == AgentStatusLine.agent_did)
        .where(Agent.status == "active", Agent.organization_id.isnot(None))
    )).all()
    floor = now - _dt.timedelta(seconds=window_s)
    out: List[Dict[str, Any]] = []
    for line, agent in rows:
        exp = _utc(line.expires_at)
        if exp is None or not (floor < exp <= now) or not agent.creator_developer_id:
            continue
        out.append({"agent_did": agent.did, "owner": int(agent.creator_developer_id), "org_id": agent.organization_id,
                    "text": line.status_text, "expires_at": exp, "name": None})
    if out:
        dids = [o["agent_did"] for o in out]
        names: Dict[str, str] = {}
        for did, name in (await db.execute(
                select(AgentCard.agent_did, AgentCard.name).where(AgentCard.agent_did.in_(dids))
                .order_by(AgentCard.is_active.desc(), AgentCard.created_at))).all():
            names.setdefault(did, name)
        for o in out:
            o["name"] = names.get(o["agent_did"])
    return sorted(out, key=lambda o: o["expires_at"])


async def _org_room(db, org_id: str) -> Optional[str]:
    from sqlalchemy import text as sa_text
    row = (await db.execute(sa_text(
        "SELECT id FROM conversations WHERE kind = 'org' AND org_id = :o ORDER BY last_seq DESC, id LIMIT 1"),
        {"o": org_id})).first()
    return str(row[0]) if row else None


async def sweep_once(db, redis, now: Optional[_dt.datetime] = None, notify=None) -> int:
    """Tell each lapsed line's owner once. Returns how many were told. `notify` defaults to push_notify.notify."""
    if redis is None:
        return 0
    now = now or _now()
    if notify is None:
        from agentvault_registry.background_tasks.push_notify import notify as _notify
        notify = _notify
    told = 0
    for o in await lapsed_lines(db, now):
        try:
            first = await redis.set(mark_key(o["agent_did"], o["expires_at"]), "1", nx=True, ex=MARK_TTL_S)
        except Exception:  # noqa: BLE001 — a mark nobody can write is a notice nobody sends (never twice)
            logger.debug("[SESSION-OFFLINE] no mark for %s", o["agent_did"], exc_info=True)
            continue
        if not first:
            continue
        name = o["name"] or f"agent …{o['agent_did'][-8:]}"
        room = await _org_room(db, o["org_id"]) if o["org_id"] else None
        await notify(
            "org.session_offline", [o["owner"]],
            title=f"{name} went quiet",
            message=(f"Its status line expired at {o['expires_at'].strftime('%H:%M')}Z and was not renewed: "
                     f"“{o['text']}”")[:300],
            tags="zzz", click=f"/ui#/pocket/ourchat/{room}" if room else "/ui#/pocket/ourchat")
        told += 1
    return told


async def _loop() -> None:
    from agentvault_registry.database import AsyncSessionLocal
    from .leader import get_redis, try_acquire_leadership
    from . import vitals as _vitals
    await _vitals.register("session_offline_watch", module=__name__, pattern="hand-rolled",
                           interval_sec=INTERVAL_S, enabled=True)
    while not _stop:
        try:
            if await try_acquire_leadership("session_offline_watch"):
                async with _vitals.cycle("session_offline_watch") as _ctx:
                    redis = await get_redis()
                    async with AsyncSessionLocal() as db:
                        n = await sweep_once(db, redis)
                    _ctx.note(told=n, redis=redis is not None)
                if n:
                    logger.info("[SESSION-OFFLINE] told %s owner(s) that a session went quiet", n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SESSION-OFFLINE] sweep error: %s", exc)
        await asyncio.sleep(INTERVAL_S)


async def start_session_offline_watch() -> None:
    global _task, _stop
    _stop = False
    if _task is None:
        _task = asyncio.create_task(_loop())


async def stop_session_offline_watch() -> None:
    global _task, _stop
    _stop = True
    if _task:
        _task.cancel()
        _task = None
