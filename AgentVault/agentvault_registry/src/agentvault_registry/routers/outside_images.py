"""V0663 (order gwo_e3187dbb237a06e8261c1dfc): GET /api/v1/public/images?src=<address>, the remaining outside images (peer
registries' logos, developer avatars, flare logos) served from this registry's own origin.

Public, as the records that name them are. The address must be one a record of this registry names
(services/outside_images.address_kind); anything else is a 404 with nothing looked up beyond that answer and nothing
fetched. A named image goes through services/card_icons exactly as a card icon does (fetched once through the outbound
guard, size and type bounded, rasters written again as PNG, SVG rebuilt from the allowlist) and is answered by
routers/card_icons.icon_response (nosniff, a sandbox CSP, an ETag).
  200  the image; 304 the ETag matched
  404  no src, an address no record here names, or one this registry does not serve; the detail says which
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agentvault_registry import database
from agentvault_registry.routers.card_icons import icon_response
from agentvault_registry.services import card_icons, outside_images

router = APIRouter(prefix="/api/v1/public/images", tags=["Public"])


def _not_here(detail: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": detail}, headers={"Cache-Control": "public, max-age=300"})


@router.get(
    "",
    summary="An outside image a record of this registry names, served from this registry",
    description=("A peer registry's logo, a developer's avatar or a flare logo, named by a record of this registry, "
                 "fetched once through its outbound guard, re-encoded (a PNG, or an SVG rebuilt from an allowlist) and "
                 "served from this origin. 404 with the reason for an address no record here names."),
    responses={200: {"content": {"image/png": {}, "image/svg+xml": {}}}, 304: {}, 404: {}},
)
async def outside_image(request: Request, src: Optional[str] = None, db=Depends(database.get_db)):
    if not src:
        return _not_here("no src: name the image's address")
    redis = await card_icons.redis_handle()
    kind = await outside_images.address_kind(db, redis, src)
    try:
        await db.rollback()   # the reads are done: no pooled connection waits on the fetch
    except Exception:  # noqa: BLE001
        pass
    if kind is None:
        return _not_here("not an image any record here names (a peer's logo, a developer's avatar or a flare logo)")
    try:
        icon = await card_icons.icon_for_url(src, redis=redis)
    except card_icons.IconUnavailable as e:
        return _not_here(f"the image is not served here ({e.reason})")
    return icon_response(icon, request)
