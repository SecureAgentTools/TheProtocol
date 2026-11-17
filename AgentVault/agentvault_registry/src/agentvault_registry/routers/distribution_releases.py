"""V0667 D6 part 3 (order gwo_fa3b8d7611f2573a2e63ac1c): the scoped release channel's routes. Thin: every rule lives in
services/distribution_releases. A refusal answers its status with {"code", "detail"}; a reader the channel does not serve gets 404
{"detail": "Not Found"}, the same answer as a line that does not exist.

  POST /api/v1/admin/distribution-releases/{name}/builds      admin_platform: our pipeline records a build (built, refused or failed)
  POST /api/v1/admin/distribution-releases/{name}/publish     admin_platform: publish the newest built row with its signed index (his card's words)
  POST /api/v1/admin/distribution-releases/{name}/withdraw    admin_platform: the published row answers no one from now on (kept for the record)
  GET  /api/v1/admin/distribution-releases/{name}             admin_platform: every build of a name, the published one first
  GET  /api/v1/admin/distribution-releases                    admin_platform: the inbox, every build of every line
  GET  /api/v1/admin/release-channel/distributions            admin_platform: the console's release view, this frame's own distribution channel
  GET  /api/v1/federation/release-channel/distributions/{name}/index        a listed registry: the signed index
  POST /api/v1/federation/release-channel/distributions/{name}/pull-grant   a listed registry: a 15-minute pull credential for its images
  GET  /api/v1/federation/release-channel/distributions                     a frame: the published lines that name it
The frame-facing routes sit under /api/v1/federation/ because every frame's nginx-federation forwards the client certificate there.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse

from agentvault_registry import database
from agentvault_registry.security import require_admin_flag
from agentvault_registry.services import code_changes
from agentvault_registry.services import distribution_releases as dr

_ADMIN = require_admin_flag("admin_platform")

router = APIRouter(tags=["Distribution releases"])


async def _caller_spiffe(request: Request) -> Optional[str]:
    """The client certificate's SPIFFE id, or None: a missing certificate is one more caller the channel does not serve (404, never a 401
    that would tell the line exists)."""
    from agentvault_registry.core.mtls_auth import get_client_spiffe_id
    try:
        return await get_client_spiffe_id(request)
    except HTTPException:
        return None


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content=dict(dr.NOT_FOUND))


async def _run(coro) -> Any:
    try:
        return await coro
    except code_changes.CodeChangeRefusal as r:
        return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})


def _actor(admin: Any) -> Optional[int]:
    return getattr(admin, "id", None)


@router.post("/api/v1/admin/distribution-releases/{name}/builds", summary="Record a distribution build (admin_platform)")
async def record_build(name: str, body: Dict[str, Any] = Body(...), admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(dr.record_build(db, _actor(admin), name, body))


@router.post("/api/v1/admin/distribution-releases/{name}/publish", summary="Publish a distribution build with its signed index (admin_platform)")
async def publish(name: str, body: Dict[str, Any] = Body(...), admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(dr.publish(db, _actor(admin), name, (body or {}).get("index"), (body or {}).get("card_word")))


@router.post("/api/v1/admin/distribution-releases/{name}/withdraw", summary="Withdraw a published distribution (admin_platform)")
async def withdraw(name: str, body: Dict[str, Any] = Body(default={}), admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(dr.withdraw(db, _actor(admin), name, (body or {}).get("reason")))


@router.get("/api/v1/admin/distribution-releases/{name}", summary="Every build of a distribution release (admin_platform)")
async def read_release(name: str, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(dr.read(db, name))


@router.get("/api/v1/admin/distribution-releases", summary="Every distribution build, newest first (admin_platform)")
async def inbox(state: Optional[str] = None, limit: int = 100, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(dr.inbox(db, state=state, limit=limit))


@router.get("/api/v1/admin/release-channel/distributions", summary="This frame's own distribution channel, for the release view (admin_platform)")
async def frame_channel(admin=Security(_ADMIN), db=Depends(database.get_db)):
    """On the governing registry: every published line. Elsewhere: the governing registry is asked, over the federation lane with this frame's
    certificate and licence, which published lines name this frame."""
    from agentvault_registry.services import code_authority
    governing = code_authority.governing_name()
    if not governing:
        return {"governing": None, "here": False, "lines": [], "reason": "no registry governs code on this network"}
    if code_authority.is_governing():
        if not dr.serving():
            return {"governing": governing, "here": True, "lines": [], "reason": "the lines are switched off here"}
        rows = (await dr.inbox(db, state="published", limit=500))["releases"]
        return {"governing": governing, "here": True, "reason": None,
                "lines": [{"name": r["name"], "release": r["release"], "generated_at": (r["index"] or {}).get("generated_at"),
                           "images": (r["index"] or {}).get("images"), "published_at": r["published_at"],
                           "registries": r["registries"]} for r in rows]}
    from agentvault_registry.services.exchange_passport import PassportError, peer_request
    try:
        st, body = await peer_request(db, governing, "GET", "/api/v1/federation/release-channel/distributions")
    except PassportError as e:
        return {"governing": governing, "here": False, "lines": [], "reason": f"{governing} could not be asked: {getattr(e, 'detail', e)}"}
    if st == 200 and isinstance(body, dict) and isinstance(body.get("lines"), list):
        return {"governing": governing, "here": False, "lines": body["lines"], "reason": None}
    return {"governing": governing, "here": False, "lines": [],
            "reason": f"{governing} serves no distribution channel to this frame" if st == 404 else f"{governing} answered {st}"}


@router.get("/api/v1/federation/release-channel/distributions/{name}/index", summary="A distribution's signed index, for a registry it names")
async def distribution_index(name: str, spiffe: Optional[str] = Depends(_caller_spiffe),
                             licence: Optional[str] = Header(None, alias="X-Federation-License"), db=Depends(database.get_db)):
    idx = await dr.index_for(db, name, spiffe, licence)
    return idx if idx is not None else _not_found()


@router.post("/api/v1/federation/release-channel/distributions/{name}/pull-grant",
             summary="A short-lived pull credential for a distribution's images, for a registry it names")
async def pull_grant(name: str, spiffe: Optional[str] = Depends(_caller_spiffe),
                     licence: Optional[str] = Header(None, alias="X-Federation-License"), db=Depends(database.get_db)):
    grant = await dr.pull_grant(db, name, spiffe, licence)
    return grant if grant is not None else _not_found()


@router.get("/api/v1/federation/release-channel/distributions", summary="The published distributions that name the calling frame")
async def my_lines(spiffe: Optional[str] = Depends(_caller_spiffe),
                   licence: Optional[str] = Header(None, alias="X-Federation-License"), db=Depends(database.get_db)):
    lines = await dr.lines_for(db, spiffe, licence)
    return lines if lines is not None else _not_found()
