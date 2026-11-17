"""V0665 the contributor track (order gwo_5e0701efdef9d3989491bc37): the reads and the one equip route. No route here grants an item: the
unlock records are written by services/contributor_track alone (a test greps the tree).

  GET /api/v1/public/contributor-track           the track: every item, its condition and why it is not earnable yet; no developer in it
  GET /api/v1/developers/me/contributor-track    my progress (n of m), my unlocks, my season wins, the title I wear
  GET /api/v1/developers/{id}/contributor-track  a developer's public face: unlocked items and the equipped title, never progress
  PUT /api/v1/developers/me/flare/title          wear an unlocked title (title_key null takes it off); 403 with what unlocks it otherwise
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.registry_identity import FLARE_TITLES
from ..database import get_db
from ..models import Developer
from ..security import get_current_developer_unified
from ..services import contributor_track

router = APIRouter(tags=["Contributor track"])


class TitleIn(BaseModel):
    title_key: Optional[str] = Field(None, max_length=64)


@router.get("/api/v1/public/contributor-track", summary="The contributor track: every item and what unlocks it (no developer data)")
async def public_track() -> Dict[str, Any]:
    return contributor_track.public_track()


@router.get("/api/v1/developers/me/contributor-track", summary="My progress on the contributor track")
async def my_track(db: AsyncSession = Depends(get_db), dev: Developer = Security(get_current_developer_unified)) -> Dict[str, Any]:
    return await contributor_track.view_for(db, dev.id, equipped_title=getattr(dev, "flare_title", None))


@router.get("/api/v1/developers/{developer_id}/contributor-track", summary="A developer's unlocked items and the title they wear")
async def public_profile_track(developer_id: int, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    dev = await db.get(Developer, developer_id)
    if dev is None:
        raise HTTPException(404, "no such developer")
    return await contributor_track.public_view_for(db, developer_id, equipped_title=getattr(dev, "flare_title", None))


@router.put("/api/v1/developers/me/flare/title", summary="Wear an unlocked title (null takes it off)")
async def equip_title(body: TitleIn, db: AsyncSession = Depends(get_db),
                      dev: Developer = Security(get_current_developer_unified)) -> Dict[str, Any]:
    key = body.title_key
    if key is None:
        dev.flare_title = None
    else:
        if key not in FLARE_TITLES:
            raise HTTPException(400, f"Unknown title '{key}'. Valid: {sorted(FLARE_TITLES)}")
        await contributor_track.require_unlocked(db, dev.id, "title", key)
        dev.flare_title = key
    db.add(dev)
    await db.commit()
    return {"title": dev.flare_title}
