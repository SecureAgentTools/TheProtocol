"""§POCKETBRIDGE3 (WS-D) — the assistant panel's server seams.

Three brains, one panel; only ONE of them touches this router:

  * Brain 1 (default): the deterministic voice grammar — pure FE, never here.
  * Brain 2: the PERSONAL Claude Code bridge (D3-3, built flagged OFF). A
    host-side wrapper around `claude -p` (scripts/commander_ai_bridge.py) rides
    the Commander's Claude subscription; this router only AUTHENTICATES,
    RATE-LIMITS and PROXIES to it. ToS boundary stated plainly: subscription
    auth is PERSONAL use — the endpoint is admin-only by construction and must
    never become a multi-user product feature. Other users get brain 3.
  * Brain 3: BYO Anthropic API key — pure FE (key stays client-side, never
    server-persisted), never here.

The bridge can only TALK: every money action still goes through the app's
confirm-gated doors (D5 — identical to the voice iron rule). Flag OFF (the
default) makes this file byte-inert beyond the status read.
"""
import logging
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Body

from .. import models, security
from ..database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["Assistant"])

_ASK_WINDOW_S = 60
_ASK_MAX_PER_WINDOW = int(os.getenv("COMMANDER_AI_BRIDGE_RATE_PER_MIN", "10"))
_PROMPT_MAX_CHARS = 4000


def _flag_on() -> bool:
    return (os.getenv("COMMANDER_AI_BRIDGE_ENABLED", "false").strip().lower()
            in ("1", "true", "yes", "on"))


def _bridge_url() -> str:
    return (os.getenv("COMMANDER_AI_BRIDGE_URL", "") or "").strip().rstrip("/")


@router.get("/status")
async def assistant_status(
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)],
) -> Dict[str, Any]:
    """What brains exist for THIS caller. The bridge is visible only to an
    admin with the flag on; everyone else sees it absent."""
    is_admin = bool(getattr(current_developer, "is_admin", False))
    return {
        "grammar": True,
        "byo": True,
        "bridge": {
            "enabled": _flag_on() and is_admin,
            "configured": bool(_bridge_url()),
            "admin_only": True,
            "note": "Personal Claude Code bridge — rides the operator's own subscription; per-account, never multi-user.",
        },
    }


async def _rate_ok(dev_id: int) -> bool:
    """Redis fixed window; degrades OPEN on Redis failure (availability over
    strictness for a personal, admin-only, flag-gated endpoint)."""
    try:
        from ..background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return True
        key = f"assistant_ask:{dev_id}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, _ASK_WINDOW_S)
        return int(n) <= _ASK_MAX_PER_WINDOW
    except Exception:  # noqa: BLE001
        return True


@router.post("/ask")
async def assistant_ask(
    request: Request,
    body: Dict[str, Any] = Body(..., example={"prompt": "what needs me today?"}),
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    if not _flag_on():
        raise HTTPException(404, "Assistant bridge is not enabled on this registry")
    if not security.admin_credential(current_developer):   # D6-057 (§POCKETPAIR): an admin's scoped key is not admin
        raise HTTPException(403, "The personal Claude bridge is admin-only by construction")
    url = _bridge_url()
    if not url:
        raise HTTPException(503, "Bridge enabled but COMMANDER_AI_BRIDGE_URL is not configured")

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(422, "prompt is required")
    if len(prompt) > _PROMPT_MAX_CHARS:
        raise HTTPException(413, f"prompt exceeds {_PROMPT_MAX_CHARS} characters")
    if not await _rate_ok(current_developer.id):
        raise HTTPException(429, f"Bridge rate limit: {_ASK_MAX_PER_WINDOW}/min")

    headers = {}
    token = (os.getenv("COMMANDER_AI_BRIDGE_TOKEN", "") or "").strip()
    if token:
        headers["X-Bridge-Token"] = token
    try:
        # connect fast-fails (a dead/filtered bridge must 502 in seconds, not
        # hang the worker 120s — measured against a ufw-dropped port); the READ
        # timeout stays long because claude -p legitimately takes tens of seconds.
        timeout = httpx.Timeout(120.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{url}/ask", json={"prompt": prompt}, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Bridge unreachable: {type(e).__name__}")

    try:
        from ..services.admin_audit import log_admin_action
        await log_admin_action(
            db,
            action="assistant.bridge_ask",
            actor_id=current_developer.id,
            actor_ip=(request.client.host if request.client else None),
            target_type="assistant_bridge",
            outcome="success" if r.status_code == 200 else "failure",
            details={"chars": len(prompt), "bridge_status": r.status_code},
        )
    except Exception:  # noqa: BLE001 — audit is best-effort, never blocks the reply
        logger.warning("assistant.bridge_ask audit write failed", exc_info=True)

    if r.status_code != 200:
        raise HTTPException(502, f"Bridge returned HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(502, "Bridge returned non-JSON")
    return {"brain": "claude-bridge", "reply": data.get("reply", ""), "meta": data.get("meta")}
