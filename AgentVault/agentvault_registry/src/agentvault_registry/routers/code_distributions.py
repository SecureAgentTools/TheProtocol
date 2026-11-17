"""V0666 D1, code distributions (order gwo_f1c05b131b9208a94074beae): an organization's release line on top of our release,
`<base_release>_<slug>`. A code distribution, never an AGORA payout (AGORA's distributions are payouts to holders, a
different thing that shares the word). Thin: every rule lives in services/code_distributions over the Code changes store.

  POST  /api/v1/code-distributions                          an owner or admin of the organization creates a line
  GET   /api/v1/code-distributions/{slug}                   its organization's members and platform admins
  PATCH /api/v1/code-distributions/{slug}                   owners and admins: title, open paths, team, quorum, pass rule
  GET   /api/v1/organizations/{org_id}/code-distributions   an organization's lines (its members)
  GET   /api/v1/admin/code-distributions                    every line on the frame (admin_platform)
  POST  /api/v1/admin/code-distributions/{slug}/pause       admin_platform, with a reason: no proposal, vote, ballot or merge
  POST  /api/v1/admin/code-distributions/{slug}/resume      admin_platform
A change into a line: POST /api/v1/code-changes with code_distribution; its vote and its owner's go and veto:
routers/code_changes. CODE_DISTRIBUTIONS_ENABLED (default off): off, every route here answers 404.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field

from agentvault_registry import database
from agentvault_registry.security import get_current_developer, require_admin_flag
from agentvault_registry.services import code_changes, code_distributions

_ADMIN = require_admin_flag("admin_platform")


def _switch() -> None:
    if not code_distributions.enabled():
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(tags=["Code distributions"], dependencies=[Depends(_switch)])


class CreateIn(BaseModel):
    organization_id: str = Field(..., max_length=64)
    slug: str = Field(..., max_length=40)
    title: str = Field(..., max_length=200)
    base_release: str = Field(..., max_length=8)
    open_paths: List[str] = Field(..., max_length=code_changes.MAX_PATHS)
    decider_team_id: Optional[str] = Field(None, max_length=64)
    quorum_percent: int = code_distributions.QUORUM_DEFAULT
    pass_rule: str = Field("simple", max_length=12)


class UpdateIn(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    open_paths: Optional[List[str]] = Field(None, max_length=code_changes.MAX_PATHS)
    decider_team_id: Optional[str] = Field(None, max_length=64)
    quorum_percent: Optional[int] = None
    pass_rule: Optional[str] = Field(None, max_length=12)


class PauseIn(BaseModel):
    reason: str = Field(..., max_length=500)


def _flow(db: Any) -> code_distributions.CodeDistributionFlow:
    return code_distributions.CodeDistributionFlow(code_changes.store_for(db))


def _admin_actor(admin: Any) -> Dict[str, Any]:
    return {"developer_id": getattr(admin, "id", None), "admin": True}


async def _run(step):
    try:
        return await step
    except code_changes.CodeChangeRefusal as r:
        return code_changes_refused(r)


def code_changes_refused(r: code_changes.CodeChangeRefusal):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})


@router.post("/api/v1/code-distributions", status_code=201,
             summary="Create an organization's code distribution (its release line; not an AGORA payout)")
async def create(body: CreateIn, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    from fastapi.responses import JSONResponse
    out = await _run(_flow(db).create({"developer_id": developer.id}, body.model_dump()))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.get("/api/v1/code-distributions/{slug}", summary="One code distribution (an organization's release line)")
async def read(slug: str, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await _run(_flow(db).read({"developer_id": developer.id, "admin": _is_admin(developer)}, slug))


@router.patch("/api/v1/code-distributions/{slug}", summary="Change a code distribution within its bounds")
async def update(slug: str, body: UpdateIn, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await _run(_flow(db).update({"developer_id": developer.id}, slug, body.model_dump(exclude_unset=True)))


@router.get("/api/v1/organizations/{org_id}/code-distributions",
            summary="An organization's code distributions (its release lines; not AGORA payouts)")
async def list_for_org(org_id: str, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await _run(_flow(db).list_for_org({"developer_id": developer.id, "admin": _is_admin(developer)}, org_id))


@router.get("/api/v1/admin/code-distributions", summary="Every code distribution on this frame (admin_platform)")
async def list_all(admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(_flow(db).list_all(_admin_actor(admin)))


@router.post("/api/v1/admin/code-distributions/{slug}/pause", summary="Pause a code distribution (admin_platform)")
async def pause(slug: str, body: PauseIn, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(_flow(db).pause(_admin_actor(admin), slug, body.reason))


@router.post("/api/v1/admin/code-distributions/{slug}/resume", summary="Resume a paused code distribution (admin_platform)")
async def resume(slug: str, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(_flow(db).resume(_admin_actor(admin), slug))


def _is_admin(developer: Any) -> bool:
    """A platform admin reads every line: require_admin_flag("admin_platform")'s rule, read without refusing (legacy
    is_admin or the flag, on this request's credential: security.admin_flag_credential, the reviewed inline twin)."""
    from agentvault_registry.security import admin_flag_credential
    return admin_flag_credential(developer, "admin_platform")
