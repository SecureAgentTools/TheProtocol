"""V0662, item 14 (order gwo_d721ad2f8118863d62815103): GET /api/v1/agent-cards/{did}/icon, a card's icon served from
this registry's own origin (services/card_icons fetches it once through the outbound guard and keeps it).

Public, as the card is: whoever can read a card can see its icon. The DID names a card this registry holds (its own,
or a mirror); the address is read from that card, never from the request, so the route cannot be pointed anywhere.
  200  the icon (a PNG, or a sanitised SVG), nosniff, a CSP that runs nothing when it is opened on its own, an ETag
  304  the ETag matched
  307  a card of this registry names a path on this origin (/static/...): served there, nothing fetched
  404  no such card, no icon, or an icon this registry does not serve; the detail says which
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from agentvault_registry import database
from agentvault_registry.services import card_icons

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_DID = 300
_CACHE_CONTROL = "public, max-age=3600"
_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def _not_here(detail: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": detail}, headers={"Cache-Control": "public, max-age=300"})


@router.get(
    "/{did}/icon",
    summary="A card's icon, served from this registry",
    description=("The icon an agent card names (iconUrl), fetched once by this registry through its outbound guard, "
                 "re-encoded (a PNG, or an SVG rebuilt from an allowlist) and served from this origin. 404 with the "
                 "reason when the card names none or the icon cannot be served."),
    responses={200: {"content": {"image/png": {}, "image/svg+xml": {}}}, 304: {}, 307: {}, 404: {}},
)
async def get_card_icon(did: str, request: Request, db=Depends(database.get_db)):
    if not did.startswith("did:") or len(did) > _MAX_DID:
        return _not_here("not a DID")
    found = await card_icons.card_icon_address(db, did)
    try:
        # the read is done: end its transaction before any outbound wait, so no pooled connection waits on a fetch
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass
    if found is None:
        return _not_here("this registry holds no active card with that DID that names an icon (no icon)")
    address, native = found
    if address.startswith("/") and not address.startswith("//"):
        if native:
            return RedirectResponse(address, status_code=307, headers={"Cache-Control": _CACHE_CONTROL})
        return _not_here("the card names a path on its own registry, which this registry does not serve")
    if not address.lower().startswith(("http://", "https://", "data:")):
        return _not_here("the card's icon address is not one this registry fetches (scheme)")
    redis = await card_icons.redis_handle()
    try:
        icon = await card_icons.icon_for_url(address, redis=redis)
    except card_icons.IconUnavailable as e:
        return _not_here(f"the card's icon is not served here ({e.reason})")
    return icon_response(icon, request)


def icon_response(icon: card_icons.Icon, request: Request) -> Response:
    """An icon as this registry serves it (here and from routers/outside_images, V0663): nosniff, a CSP that runs
    nothing when it is opened on its own, an ETag, and a 304 when the reader already holds that ETag."""
    etag = '"' + hashlib.sha256(icon.body).hexdigest()[:32] + '"'
    headers = {
        "Cache-Control": _CACHE_CONTROL,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": _CSP,
    }
    if etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(content=icon.body, media_type=icon.content_type, headers=headers)
