"""The personal Claude bridge, as the registry calls it (brain 2: routers/assistant.py's /assistant/ask, and since V0654
the in-chat assistant, routers/chat.py's /conversations/{id}/assist).

The bridge is a host-side wrapper around `claude -p` (scripts/commander_ai_bridge.py) riding the Commander's own Claude
subscription: PERSONAL use, so every caller here is admin-only by construction (security.admin_credential), flag-gated
(COMMANDER_AI_BRIDGE_ENABLED, on EU alone for his proof of concept) and rate-limited per developer. V0654 (ap), order
gwo_03a846cb91b37628c3c6710a: an in-chat reply runs with NO tools (`tools="none"`: its prompt carries the room's lines, and a
read tool would let a line in the room steer it into his other threads; session-lead's review, the sessions' room seq
1124-1125), and the registry
asks for one only from a bridge whose /health says it can (an older bridge ignores the field and would run with every
tool its list names).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

ASK_WINDOW_S = 60
ASK_MAX_PER_WINDOW = int(os.getenv("COMMANDER_AI_BRIDGE_RATE_PER_MIN", "10"))
PROMPT_MAX_CHARS = 4000            # the Pocket assistant's own ask (the bridge's full profile)
CHAT_PROMPT_MAX_CHARS = 12000      # an in-chat ask, the room's lines included (the bridge's read profile)
_HEALTH_TTL_S = 60.0
_health_cache: Dict[str, Any] = {"at": 0.0, "none": None}
CHAT_PROFILE = "none"          # the bridge profile an in-chat answer runs with: no tools at all


class BridgeError(Exception):
    """The bridge did not answer usefully: `status` is what the registry answers its caller."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def flag_on() -> bool:
    return (os.getenv("COMMANDER_AI_BRIDGE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"))


def bridge_url() -> str:
    return (os.getenv("COMMANDER_AI_BRIDGE_URL", "") or "").strip().rstrip("/")


def _headers() -> Dict[str, str]:
    token = (os.getenv("COMMANDER_AI_BRIDGE_TOKEN", "") or "").strip()
    return {"X-Bridge-Token": token} if token else {}


async def rate_ok(dev_id: int) -> bool:
    """Redis fixed window, one budget for both callers; degrades OPEN on Redis failure (availability over strictness for a
    personal, admin-only, flag-gated endpoint)."""
    try:
        from ..background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return True
        key = f"assistant_ask:{dev_id}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, ASK_WINDOW_S)
        return int(n) <= ASK_MAX_PER_WINDOW
    except Exception:  # noqa: BLE001
        return True


async def chat_profile_supported() -> bool:
    """Does the bridge list the no-tools profile (/health's profiles)? Cached a minute; unreachable or silent reads False:
    an older bridge ignores the field and would run with every tool its list names."""
    now = time.monotonic()
    if _health_cache["none"] is not None and now - _health_cache["at"] < _HEALTH_TTL_S:
        return bool(_health_cache["none"])
    url = bridge_url()
    ok = False
    if url:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
                r = await client.get(f"{url}/health", headers=_headers())
            ok = r.status_code == 200 and CHAT_PROFILE in ((r.json() or {}).get("profiles") or [])
        except (httpx.HTTPError, ValueError):
            ok = False
    _health_cache.update(at=now, none=ok)
    return ok


async def ask(prompt: str, *, tools: Optional[str] = None) -> Dict[str, Any]:
    """One ask: {"reply", "meta"}; BridgeError(502/504) when the bridge cannot be reached, times out or fails.

    The connect fast-fails (a dead or filtered bridge must answer in seconds, not hang a worker); the READ timeout stays
    long because claude -p legitimately takes tens of seconds."""
    url = bridge_url()
    if not url:
        raise BridgeError(503, "The personal assistant is enabled here but its address is not configured.")
    body: Dict[str, Any] = {"prompt": prompt}
    if tools:
        body["tools"] = tools
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            r = await client.post(f"{url}/ask", json=body, headers=_headers())
    except httpx.TimeoutException:
        raise BridgeError(504, "The assistant took too long to answer.")
    except httpx.HTTPError as e:
        raise BridgeError(502, f"The assistant could not be reached ({type(e).__name__}).")
    if r.status_code != 200:
        raise BridgeError(502, f"The assistant could not answer just now (HTTP {r.status_code}).")
    try:
        data = r.json()
    except ValueError:
        raise BridgeError(502, "The assistant answered in a form the registry cannot read.")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if tools and meta.get("tools") != tools:      # it must say it ran with exactly the tools asked for
        raise BridgeError(502, "The assistant ran with other tools than the registry asked for.")
    return {"reply": str(data.get("reply") or ""), "meta": meta}
