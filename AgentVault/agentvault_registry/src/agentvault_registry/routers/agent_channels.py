"""§COCKPITA R4 — the two channels between the desk and a RUNNING agent.

His ask carried two different things in one sentence — *"webhooks to the mounted running
dockerized agents for prompting while the agent works"* — and they are split here on
purpose, because they carry opposite risk:

  R4a  PROGRESS  (agent -> desk)   the agent says what it is doing while it works.
                                   OBSERVATION. Nothing can act on it. Redis ring, bounded,
                                   no schema: a progress note is a breadcrumb, not a record,
                                   and giving it a table would imply a permanence it has not
                                   earned.
  R4b  INSTRUCT  (desk -> agent)   the human sends the agent an instruction.
                                   🔴 This is the ONLY part of the cockpit that can make an
                                   agent ACT. Everything else on the desk watches. It is
                                   therefore owner-gated, audited at the choke point, sent
                                   over the A2A standard, and REFUSES — by name, per agent —
                                   when the agent declares no A2A interface.

🔴 WHY A2A AND NOT A WEBHOOK. A webhook posts a body of our choosing to a URL of our
choosing; that is a private protocol between this registry and whichever agent happens to
speak it. The fleet already has a standard for "send this agent a message": the A2A JSONRPC
interface its own card advertises in `supportedInterfaces`. Measured before choosing:
SYBIL and Gregory and Chester and Boris mount `/api/a2a`; Hagrid and Gerald do not. So the
capability is genuinely per-agent, and the honest surface says which — a button that posts
into a 404 is the blank-promise class (§DISCREFINE).

⚠ THE ADDRESS COMES FROM THE CARD, NEVER FROM THE CALLER. An instruct endpoint that took a
URL would be an open relay wearing a cockpit's clothes.
"""
import datetime as _dt
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.config import settings
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_agent, get_current_developer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Agent Channels"])

# A ring per agent. Small on purpose: this is "what is it doing right now", and a long
# scrollback here would be a worse version of the ledger that already exists.
RING_MAX = 50
RING_TTL_SEC = 6 * 3600
INSTRUCT_TIMEOUT_SEC = float(getattr(settings, "AGENT_INSTRUCT_TIMEOUT_SEC", 15))


def _client_ip(request: Request) -> Optional[str]:
    """§XFFTRUST — the LAST XFF element, never the first. nginx APPENDS the real peer, so
    `hosts[0]` is whatever the caller wrote."""
    try:
        from agentvault_registry.core.client_ip import effective_client_ip
        return effective_client_ip(request)
    except Exception:  # noqa: BLE001
        return None


def _ring_key(did: str) -> str:
    return f"cockpit:progress:{did}"


async def _redis():
    """The ONE redis handle, borrowed from ws_manager — same reasoning as liability's:
    two spellings of the same key is how a channel silently splits in half.

    ⚠ `manager`, not `ws_manager`. The wrong name here is what made P7's presence gate
    answer "unknown" forever while reading as correct policy.
    """
    try:
        from agentvault_registry.routers.websocket import manager as _ws
        return await _ws._get_redis()
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────── R4a: PROGRESS (agent -> desk) ───────────────────────────

class ProgressIn(BaseModel):
    """What an agent says about the work it is doing.

    Deliberately NOT free-form telemetry: a phase, a human sentence, and an optional
    correlation ref so a note can be tied to the contract or job it belongs to.
    """
    phase: str = Field(..., max_length=48, description="e.g. 'scanning', 'settling', 'idle'")
    note: str = Field("", max_length=280)
    ref: Optional[str] = Field(None, max_length=128, description="contract id, job id, anything the agent correlates on")
    pct: Optional[int] = Field(None, ge=0, le=100)


@router.post("/api/v1/agents/progress", summary="Report what this agent is doing (agent JWT)")
async def post_progress(body: ProgressIn, request: Request,
                        agent: models.Agent = Depends(get_current_agent)):
    """The agent's own voice. It can only ever speak about ITSELF: the DID is taken from
    the token, never from the body, so one agent cannot narrate another's work."""
    r = await _redis()
    if r is None:
        # Fail SOFT and say so. A progress channel that takes down the agent reporting into
        # it would be worse than no channel at all.
        return {"stored": False, "reason": "progress buffer unavailable"}
    row = {
        "did": agent.did,
        "phase": body.phase,
        "note": body.note,
        "ref": body.ref,
        "pct": body.pct,
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    try:
        k = _ring_key(agent.did)
        await r.lpush(k, json.dumps(row))
        await r.ltrim(k, 0, RING_MAX - 1)
        await r.expire(k, RING_TTL_SEC)
    except Exception:  # noqa: BLE001
        logger.debug("[CHANNELS] progress push failed", exc_info=True)
        return {"stored": False, "reason": "progress buffer unavailable"}
    return {"stored": True, "at": row["at"]}


@router.get("/api/v1/agents/progress", summary="Recent progress from MY agents (developer JWT)")
async def get_progress(limit: int = 60,
                       dev: models.Developer = Depends(get_current_developer),
                       db: AsyncSession = Depends(get_db)):
    """
    Recent progress reports from the developer's own agents. Scoped by ownership in the database query (the set of
    agents is read here, never taken from a parameter). Needs a developer token.

    \f
    Scoped by OWNERSHIP at the database, not by a filter the client could widen.

    ⚠ The DID set is read here rather than trusted from a query parameter — the §ORGLEAK
    law: a surface that accepts the set it is scoped to is not scoped.
    """
    # §COCKPITPOLISH P4 — the NAME rides the same query that does the scoping.
    # Rows rendered phase, note, percent and age and never said WHICH AGENT was speaking.
    # With one reporter that reads fine; with eleven it is unreadable, and the screenshot
    # that prompted this showed eleven rows alternating IDLE/READING from a single agent
    # with nothing on screen to tell you so. Resolving the name HERE rather than in the
    # client means it comes from the same authority as the ownership check, and costs no
    # extra round trip: the LEFT JOIN rides the query that was already being made.
    res = await db.execute(text(
        "SELECT a.did, c.name FROM agents a "
        "LEFT JOIN agent_cards c ON c.agent_did = a.did AND c.developer_id = :d "
        "WHERE a.creator_developer_id = :d AND a.status = 'active'"
    ), {"d": dev.id})
    rows = res.fetchall()
    dids = [r[0] for r in rows]
    names = {r[0]: r[1] for r in rows if r[1]}
    r = await _redis()
    if r is None:
        return {"notes": [], "agents": len(dids), "degraded": True,
                "reason": "progress buffer unavailable — this is not the same as 'no agents reported'"}
    notes: List[Dict[str, Any]] = []
    try:
        for did in dids:
            raw = await r.lrange(_ring_key(did), 0, RING_MAX - 1)
            for item in raw or []:
                try:
                    n = json.loads(item)
                except Exception:  # noqa: BLE001
                    continue
                # ⚠ An unresolved name stays ABSENT rather than becoming the DID here:
                # the client decides how to render "no card name", and a server that
                # substitutes silently removes that choice.
                if n.get("did") in names:
                    n["agent_name"] = names[n["did"]]
                notes.append(n)
    except Exception:  # noqa: BLE001
        return {"notes": [], "agents": len(dids), "degraded": True,
                "reason": "progress buffer unavailable"}
    notes.sort(key=lambda n: n.get("at") or "", reverse=True)
    return {"notes": notes[: max(1, min(limit, 200))], "agents": len(dids), "degraded": False}


@router.get("/api/v1/agents/instructions", summary="Instructions I have sent, delivered or not (developer JWT)")
async def get_instruction_history(limit: int = 40,
                                  dev: models.Developer = Depends(get_current_developer),
                                  db: AsyncSession = Depends(get_db)):
    """
    The instructions the developer has sent to their agents, delivered or not, with the outcome of each. Scoped by
    the query to the calling developer; no parameter can widen it. A row whose details cannot be parsed is still
    returned with its outcome. Needs a developer token.

    \f
    §COCKPITPOLISH P7.1 — WHAT YOU TOLD YOUR AGENTS, AND WHETHER IT LANDED.

    Every instruct attempt has written a `security_audit_logs` row since §COCKPITA R4 —
    delivered or not, because an instruction that failed to arrive was still ISSUED — and
    until now NOTHING RENDERED THEM. A rail that writes and is never read is a rail nobody
    can tell has stopped writing.

    ⚠ SCOPED BY THE WHERE CLAUSE, NOT BY A FILTER. `actor_id = me` is applied in SQL, so
    this endpoint cannot be widened by a parameter; there is no parameter that names the
    actor. Same law as the progress reader above (§ORGLEAK).

    ⚠ THE COLUMN IS `timestamp`, NOT `created_at` (§FIRMBOOKS), and `details` is TEXT
    holding JSON rather than JSONB — so it is parsed here and a row whose details cannot
    be parsed still returns with its outcome intact rather than being dropped. A history
    that silently omits the malformed entries is a history you cannot trust to be complete.

    ⚠ The stored action carries the helper's `admin.` prefix (§V0177): the row reads
    `admin.cockpit.agent.instruct`. Grepping the unprefixed name finds nothing.
    """
    lim = max(1, min(int(limit or 40), 200))
    res = await db.execute(text(
        "SELECT l.timestamp, l.target_id, l.outcome, l.details, c.name "
        "FROM security_audit_logs l "
        "LEFT JOIN agent_cards c ON c.agent_did = l.target_id AND c.developer_id = :d "
        "WHERE l.action = 'admin.cockpit.agent.instruct' AND l.actor_id = :actor "
        "ORDER BY l.timestamp DESC LIMIT :lim"
    ), {"d": dev.id, "actor": str(dev.id), "lim": lim})

    out: List[Dict[str, Any]] = []
    for ts, target, outcome, details, name in res.fetchall():
        d: Dict[str, Any] = {}
        if details:
            try:
                parsed = json.loads(details)
                if isinstance(parsed, dict):
                    d = parsed
            except Exception:  # noqa: BLE001
                d = {}
        out.append({
            "at": ts.isoformat() if ts else None,
            "agent_did": target,
            "agent_name": name,
            "outcome": outcome,                        # success | failure, from the audit row
            "delivery": d.get("outcome"),              # delivered | unreachable | refused …
            "elapsed_ms": d.get("elapsed_ms"),
            "transport": d.get("transport"),
            "ref": d.get("ref"),
            "text_len": d.get("text_len"),
            "detail": d.get("detail"),
        })
    # ⚠ The instruction TEXT is deliberately not stored and so cannot be returned: the
    # audit row keeps its LENGTH, not its content. Saying that here stops the next reader
    # assuming the field was lost rather than never taken.
    return {"instructions": out, "count": len(out), "text_retained": False}


# ─────────────────────────────── R4b: INSTRUCT (desk -> agent) ───────────────────────────

def _a2a_endpoint(card: Optional[Dict[str, Any]]) -> Optional[str]:
    """The agent's OWN advertised A2A address, or None.

    None is a real answer and the caller must render it as one: several sovereign agents
    (Hagrid, Gerald) mount no A2A interface at all, and showing them an instruct box that
    cannot work is the blank promise §DISCREFINE named.
    """
    if not isinstance(card, dict):
        return None
    for iface in (card.get("supportedInterfaces") or []):
        if not isinstance(iface, dict):
            continue
        if str(iface.get("protocolBinding") or "").upper() == "JSONRPC":
            url = (iface.get("url") or "").strip()
            if url:
                return url
    return None


class InstructIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    ref: Optional[str] = Field(None, max_length=128)


@router.get("/api/v1/agents/{did}/channel", summary="Can this agent be instructed, and how?")
async def channel_capability(did: str,
                             dev: models.Developer = Depends(get_current_developer),
                             db: AsyncSession = Depends(get_db)):
    """Answers the door's own question BEFORE it is drawn, so the desk never renders a
    control that cannot work."""
    res = await db.execute(text("""
        SELECT a.did, ac.card_data
          FROM agents a LEFT JOIN agent_cards ac ON ac.agent_did = a.did
         WHERE a.did = :did AND a.creator_developer_id = :dev
    """), {"did": did, "dev": dev.id})
    row = res.fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such agent of yours")
    ep = _a2a_endpoint(row[1])
    return {
        "did": did,
        "can_instruct": bool(ep),
        "transport": "a2a-jsonrpc" if ep else None,
        # The reason is the product: it tells the owner what to CHANGE.
        "reason": None if ep else
        "This agent's card declares no A2A (JSONRPC) interface, so there is no standard "
        "address to send an instruction to. Publish one in supportedInterfaces to enable this.",
    }


@router.post("/api/v1/agents/{did}/instruct", summary="Send an instruction to a running agent (owner only)")
async def instruct_agent(did: str, body: InstructIn, request: Request,
                         dev: models.Developer = Depends(get_current_developer),
                         db: AsyncSession = Depends(get_db)):
    """
    Send an instruction to a running agent (owner only). The ownership test is in the query, so a non-owner cannot
    learn that the agent exists; the address comes from the agent's card, never from the caller; every attempt is
    audited; an agent with no A2A interface answers 409 with what is missing. Needs a developer token.

    \f
    🔴 THE ONE CONTROL ON THIS DESK THAT MAKES SOMETHING HAPPEN.

    Four constraints, none of them optional:
      1. OWNER ONLY — the ownership test is in the WHERE clause, not in an `if` after the
         read, so a non-owner cannot even learn the agent exists.
      2. THE ADDRESS COMES FROM THE CARD — never from the caller. Otherwise this is an open
         relay: post any body to any URL, signed by the registry's own egress.
      3. AUDITED AT THE CHOKE POINT — one place sends, one place records, so an instruction
         that happened and an instruction that was logged cannot diverge.
      4. IT REFUSES BY NAME — an agent with no A2A interface gets 409 and a sentence saying
         what is missing, not a silent no-op.
    """
    res = await db.execute(text("""
        SELECT a.did, ac.card_data
          FROM agents a LEFT JOIN agent_cards ac ON ac.agent_did = a.did
         WHERE a.did = :did AND a.creator_developer_id = :dev AND a.status = 'active'
    """), {"did": did, "dev": dev.id})
    row = res.fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such active agent of yours")
    endpoint = _a2a_endpoint(row[1])
    if not endpoint:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=(
            "This agent declares no A2A (JSONRPC) interface in its card, so there is no "
            "standard address to instruct it on. Publish one in supportedInterfaces first."
        ))

    # A2A message/send, the same shape the SDK speaks. Not a bespoke webhook body.
    payload = {
        "jsonrpc": "2.0",
        "id": f"cockpit-{int(time.time() * 1000)}",
        "method": "message/send",
        "params": {"message": {
            "role": "user",
            "parts": [{"kind": "text", "text": body.text}],
            "messageId": f"ckd-{int(time.time() * 1000)}",
        }},
    }
    started = time.monotonic()
    outcome, detail, agent_reply = "delivered", None, None
    try:
        async with httpx.AsyncClient(timeout=INSTRUCT_TIMEOUT_SEC) as client:
            resp = await client.post(endpoint, json=payload,
                                     headers={"Content-Type": "application/json"})
        if 200 <= resp.status_code < 300:
            try:
                agent_reply = resp.json()
            except Exception:  # noqa: BLE001
                agent_reply = {"raw": (resp.text or "")[:500]}
        else:
            outcome, detail = "refused", f"agent answered HTTP {resp.status_code}"
    except Exception as e:  # noqa: BLE001
        outcome, detail = "unreachable", type(e).__name__
    elapsed_ms = int((time.monotonic() - started) * 1000)

    # ⚠ Audited whatever the outcome. An instruction that failed to arrive is still an
    # instruction that was ISSUED, and the record of who tried is the point.
    # ⚠ THE SIGNATURE IS `actor_id` (str) AND THERE IS NO `request` PARAMETER. The first
    # draft passed `developer_id=` and `request=`; inside this try/except that TypeError
    # would have made the audit silently never write while the instruction still fired —
    # the worst possible shape for a security-relevant record. Verified against
    # `services/admin_audit.py:85` before shipping, not after.
    # ⚠ The helper PREFIXES what it stores (`_log_action`: f"{prefix}.{action}"), so the
    # row reads `admin.cockpit.agent.instruct`. Anything grepping for the unprefixed name
    # finds nothing — the §V0177 trap, which has now bitten this project four times.
    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db, action="cockpit.agent.instruct",
            actor_id=str(dev.id), actor_ip=_client_ip(request),
            target_type="agent", target_id=did,
            outcome="success" if outcome == "delivered" else "failure",
            severity="info" if outcome == "delivered" else "warning",
            details={"outcome": outcome, "transport": "a2a-jsonrpc", "endpoint": endpoint,
                     "elapsed_ms": elapsed_ms, "ref": body.ref,
                     "text_len": len(body.text), "detail": detail},
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("[CHANNELS] instruct audit write failed for %s", did, exc_info=True)

    if outcome != "delivered":
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            detail=f"Instruction not delivered ({outcome}): {detail}")
    return {"delivered": True, "transport": "a2a-jsonrpc", "elapsed_ms": elapsed_ms,
            "agent_reply": agent_reply}
