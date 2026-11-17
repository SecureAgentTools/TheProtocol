"""V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane's routes. Thin: every rule lives in services/content_changes (ContentChangeFlow over DbStore).
A refusal answers its status with {"code", "detail"} (and "reasons" for our checker's). Behind CODE_DISTRIBUTIONS_ENABLED, as the lines are (off, each answers 404).

  POST /api/v1/content-changes                    a member's agent proposes a content change into an organization's line (our checker runs first)
  GET  /api/v1/content-changes                    the reader's organizations' changes (filters: code_distribution, state, kind, organization_id)
  GET  /api/v1/content-changes/{cid}              one change: record, checker verdict, ballot, applied before and after
  POST /api/v1/content-changes/{cid}/vote         a decider's vote, through one of their agents (gov.vote)
  POST /api/v1/content-changes/{cid}/withdraw     the proposer's (or an admin's) withdrawal while it is in its ballot
  POST /api/v1/content-changes/{cid}/undo         one step back, by the line's deciders or a platform admin
  GET  /api/v1/admin/content-changes              admin_platform: every organization's changes in one inbox
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Security
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agentvault_registry import database
from agentvault_registry.routers.utils import get_current_agent
from agentvault_registry.security import get_current_developer, require_admin_flag, require_agent_permission
from agentvault_registry.services import code_changes, code_distributions, content_changes

_ADMIN = require_admin_flag("admin_platform")


def _switch() -> None:
    from fastapi import HTTPException
    if not code_distributions.enabled():
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(tags=["Content changes"], dependencies=[Depends(_switch)])


class ProposeIn(BaseModel):
    code_distribution: str = Field(..., max_length=40)
    kind: str = Field(..., max_length=16)
    target: str = Field(..., max_length=200)
    title: str = Field(..., max_length=160)
    problem: str = Field(..., max_length=6000)
    content: Dict[str, Any]
    room_id: Optional[str] = Field(None, max_length=36)       # V0667 D5b: a room of the line's organization: its live card and state lines go there


class VoteIn(BaseModel):
    vote: bool


class ReasonIn(BaseModel):
    reason: str = Field("", max_length=500)


def _refused(r: code_changes.CodeChangeRefusal) -> JSONResponse:
    body: Dict[str, Any] = {"code": r.code, "detail": r.sentence}
    if getattr(r, "reasons", None):
        body["reasons"] = r.reasons
    return JSONResponse(status_code=r.status, content=body)


async def _run(step):
    try:
        return await step
    except code_changes.CodeChangeRefusal as r:
        return _refused(r)


def _is_admin(developer: Any) -> bool:
    from agentvault_registry.security import admin_flag_credential
    return admin_flag_credential(developer, "admin_platform")


def _flow(db: Any, agent: Any = None) -> content_changes.ContentChangeFlow:
    return content_changes.ContentChangeFlow(content_changes.store_for(db, agent))


def _reader(developer: Any) -> Dict[str, Any]:
    return {"developer_id": developer.id, "admin": _is_admin(developer)}


@router.post("/api/v1/content-changes", status_code=201, summary="Propose a content change into an organization's line (a member's agent)")
async def propose(body: ProposeIn, agent=Depends(get_current_agent), db=Depends(database.get_db)):
    actor = {"did": agent.did, "developer_id": agent.creator_developer_id}
    payload = body.model_dump()
    if payload.get("room_id") is None:
        payload.pop("room_id", None)
    out = await _run(_flow(db, agent).propose(actor, payload))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.get("/api/v1/content-changes", summary="The content changes of the reader's organizations, newest first")
async def list_changes(code_distribution: Optional[str] = Query(None, max_length=40), state: Optional[str] = Query(None, max_length=16),
                       kind: Optional[str] = Query(None, max_length=16), organization_id: Optional[str] = Query(None, max_length=64),
                       limit: int = Query(50, ge=1, le=200), developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await _run(_flow(db).list(_reader(developer), slug=code_distribution, state=state, kind=kind, organization_id=organization_id, limit=limit))


@router.get("/api/v1/admin/content-changes", summary="Every organization's content changes in one inbox (admin_platform)")
async def inbox(code_distribution: Optional[str] = Query(None, max_length=40), state: Optional[str] = Query(None, max_length=16),
                kind: Optional[str] = Query(None, max_length=16), organization_id: Optional[str] = Query(None, max_length=64),
                limit: int = Query(50, ge=1, le=200), admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(_flow(db).list({"developer_id": getattr(admin, "id", None), "admin": True}, slug=code_distribution, state=state, kind=kind,
                                     organization_id=organization_id, limit=limit))


@router.get("/api/v1/content-changes/{cid}", summary="One content change: record, checker verdict, ballot, applied before and after")
async def view(cid: str, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await _run(_flow(db).view(_reader(developer), cid))


@router.post("/api/v1/content-changes/{cid}/vote", summary="A decider's vote on a content change (through one of their agents)")
async def vote(cid: str, body: VoteIn, agent=Security(require_agent_permission("gov.vote")), db=Depends(database.get_db)):
    return await _run(_flow(db, agent).vote({"did": agent.did, "developer_id": agent.creator_developer_id}, cid, body.model_dump()))


@router.post("/api/v1/content-changes/{cid}/withdraw", summary="Withdraw a content change while it is in its ballot (its proposer, or an admin)")
async def withdraw(cid: str, body: Optional[ReasonIn] = None, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await _run(_flow(db).withdraw(_reader(developer), cid, (body or ReasonIn()).model_dump()))


@router.post("/api/v1/content-changes/{cid}/undo", summary="Undo an applied content change in one step (the line's deciders, or an admin)")
async def undo(cid: str, body: Optional[ReasonIn] = None, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await _run(_flow(db).undo(_reader(developer), cid, (body or ReasonIn()).model_dump()))
