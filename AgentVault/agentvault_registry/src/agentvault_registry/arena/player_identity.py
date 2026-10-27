"""Who a game call acts as: one rule for the five game servers (arena, td, snake, trading, lobby).

D6-633 (2026-10-16). Each server derived the player from the bearer token by decoding it with
`settings.SECRET_KEY`, which the registry's settings do not define (the JWT key is API_KEY_SECRET), so every
decode raised and every bearer token fell back to `token:<its first 12 characters>`. Those characters are the
encoded JWT header, the same for every token the registry issues, so every player who sent a token was one and
the same player, and any string with that prefix could act as them. Where a decode would have worked, a
developer token became a player too (`dev:<id>`, or its bare subject in three of the servers).

Now: no Authorization header plays as the shared anonymous player (documented). Any Authorization header must
be a current agent JWT of this registry, validated the way the registry's own routes validate one (signature and
expiry, an agent token, the agent present and neither suspended nor revoked, an owner session still live:
security.get_current_actor_for_read_optional), and the player is that agent's DID. Anything else is refused:
there is no fallback identity.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

ANONYMOUS_PLAYER = "anonymous"

REFUSED_MESSAGE = (
    "The Authorization header is not a current agent token of this registry. Send a current agent JWT from this "
    "registry as 'Authorization: Bearer <token>', or no Authorization header to play as the shared anonymous player."
)


async def resolve_player_id(request: Request) -> Optional[str]:
    """The player id this call acts as: ANONYMOUS_PLAYER, an agent's DID, or None when the call must be refused."""
    auth = request.headers.get("authorization")
    if auth is None or not auth.strip():
        return ANONYMOUS_PLAYER
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    from ..database import AsyncSessionLocal
    from ..security import get_current_actor_for_read_optional
    try:
        async with AsyncSessionLocal() as db:
            actor = await get_current_actor_for_read_optional(db=db, authorization=f"Bearer {parts[1]}")
    except Exception as e:  # noqa: BLE001 - an unreadable credential plays as nobody, never as someone
        logger.warning(f"[games] player credential could not be checked: {e}")
        return None
    if not actor or actor.get("kind") != "agent" or not actor.get("agent_did"):
        return None
    return str(actor["agent_did"])


def refused_response(request_id: Any) -> JSONResponse:
    """The JSON-RPC answer to a call whose credential is refused (401, code -32001 like the registry's MCP server)."""
    return JSONResponse(
        status_code=401,
        content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": REFUSED_MESSAGE}},
        headers={"WWW-Authenticate": "Bearer"},
    )
