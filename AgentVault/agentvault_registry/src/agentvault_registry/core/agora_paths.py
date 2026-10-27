"""§AGORAWORDS Phase 5 (2026-09-22): the AGORA market's HTTP prefix, and the fallback a PEER dialer needs.

Every caller uses /api/v1/agora since V0421 (the documented name since V0419); /api/v1/exchange stays live on this
registry until a later release drops it. A dialer that reaches ANOTHER registry cannot know which one it runs, so it
asks the new name first and, only when that registry's router does not know the route at all (an older frame answers
FastAPI's bare 404, detail "Not Found"), asks the old name once. A business 404 (an unknown listing names the listing
in its detail) is an answer and is returned as it is, never re-asked under the other name. The same rule keeps these
dialers working the day the old name is dropped here and an older peer still lacks the new one.
"""
from __future__ import annotations

from typing import Any

AGORA_PREFIX = "/api/v1/agora"
LEGACY_PREFIX = "/api/v1/exchange"


def route_missing(resp: Any) -> bool:
    """True for a 404 whose registry did not know the ROUTE (detail exactly "Not Found"); False for every other answer."""
    if getattr(resp, "status_code", None) != 404:
        return False
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — an empty or HTML 404 carries no business answer either
        return True
    if not isinstance(body, dict):
        return True
    detail = body.get("detail")
    if detail is None and isinstance(body.get("error"), dict):
        detail = body["error"].get("detail")
    return detail in (None, "Not Found")


async def peer_request(client: Any, method: str, base: str, suffix: str, **kwargs: Any) -> Any:
    """`suffix` under the peer's AGORA prefix (e.g. "/listings"), falling back to the old prefix once if the route is unknown."""
    resp = await client.request(method, f"{base}{AGORA_PREFIX}{suffix}", **kwargs)
    if route_missing(resp):
        resp = await client.request(method, f"{base}{LEGACY_PREFIX}{suffix}", **kwargs)
    return resp
