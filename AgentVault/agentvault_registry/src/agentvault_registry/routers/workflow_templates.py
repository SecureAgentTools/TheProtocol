"""V0664 "Migrate a system", M4 (order gwo_e97a483512cfaf2151f17b7a): the template library's routes. Thin: every rule
lives in services/workflow_templates (Library over DbStore). A refusal answers its status with {"code", "detail"}.

  GET  /api/v1/workflow-templates                          public templates (kind, from, to, pricing, q, sort)
  GET  /api/v1/workflow-templates/{tid}                    a visible template: listing, versions index, structure
  GET  /api/v1/workflow-templates/{tid}/versions/{n}       a version with its files (free and visible, owner, buyer)
  GET  /api/v1/workflow-templates/{tid}/versions/{n}/kit   the same, counted as a kit download (rate-limited)
  POST /api/v1/workflow-templates                          create (a draft v1)              any agent; visible or priced: the bond
  POST /api/v1/workflow-templates/{tid}/versions           a new draft version (the owner)
  POST /api/v1/workflow-templates/{tid}/versions/{n}/publish   publish (immutable after; the owner)
  PATCH /api/v1/workflow-templates/{tid}                   the listing, never the content (the owner)
  POST /api/v1/workflow-templates/{tid}/fork               a private free fork, lineage kept any agent
  POST /api/v1/workflow-templates/{tid}/purchase           the escrow legs, once per buyer
  POST /api/v1/workflow-templates/{tid}/instantiate        a V0663 workflow draft with provenance
  POST /api/v1/workflow-templates/{tid}/certified          {attestation_id, attestation_data}: a certified run
Reads take no credential (a public or unlisted template), an agent JWT or a developer JWT; writes are an agent's, gated
as routers/contract_templates.py gates its create and fork. Off unless WORKFLOW_TEMPLATES_ENABLED (503).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from agentvault_registry import database, models
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter
from agentvault_registry.security import get_current_actor_for_read_optional, get_current_agent
from agentvault_registry.services import workflow_templates as wt

router = APIRouter(tags=["Workflow templates"])


def store_for(db: Any) -> Any:
    return wt.DbStore(db)


def _require_enabled() -> None:
    if not wt.templates_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Workflow templates are switched off on this registry (WORKFLOW_TEMPLATES_ENABLED)")


def _reader(actor: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The library's actor for a read: none, an agent (its developer and organization) or a developer."""
    if not actor:
        return None
    if actor.get("kind") == "agent":
        agent = actor.get("agent")
        return {"kind": "agent", "did": actor.get("agent_did"),
                "developer_id": getattr(agent, "creator_developer_id", None),
                "org": str(getattr(agent, "organization_id", None) or "") or None}
    if actor.get("kind") == "developer":
        return {"kind": "developer", "developer_id": getattr(actor.get("developer"), "id", None)}
    return None


def _writer(agent: models.Agent) -> Dict[str, Any]:
    return {"kind": "agent", "did": agent.did, "developer_id": getattr(agent, "creator_developer_id", None),
            "org": str(getattr(agent, "organization_id", None) or "") or None}


async def _run(step):
    try:
        return await step
    except wt.LibraryRefusal as r:
        return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})


def _lib(db: Any) -> wt.Library:
    return wt.Library(store_for(db))


# -- reads -------------------------------------------------------------------------------------------------------------

@router.get("/api/v1/workflow-templates", summary="Public workflow templates (migration templates), newest first")
async def list_templates(kind: Optional[str] = Query(None, max_length=20), from_: Optional[str] = Query(None, alias="from", max_length=20),
                         to: Optional[str] = Query(None, max_length=20), pricing: Optional[str] = Query(None, max_length=12),
                         q: Optional[str] = Query(None, max_length=80), sort: str = Query("new", max_length=12),
                         limit: int = Query(50, ge=1, le=100), db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).list({"kind": kind, "from": from_, "to": to, "pricing": pricing, "q": q, "sort": sort,
                                     "limit": limit}))


# before /{tid}: FastAPI matches in registration order, so "mine" would otherwise be read as a template id
@router.get("/api/v1/workflow-templates/mine", summary="My templates: drafts, versions and buyers (an agent's own, or a developer's agents')")
async def my_templates(actor=Depends(get_current_actor_for_read_optional), db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).mine(_reader(actor)))


@router.get("/api/v1/workflow-templates/{tid}", summary="A template: its listing, versions and structure (never its files)")
async def get_template(tid: str, actor=Depends(get_current_actor_for_read_optional), db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).detail(_reader(actor), tid))


@router.get("/api/v1/workflow-templates/{tid}/versions/{n}", summary="A version with its files (free, the owner or a buyer)")
async def get_version(tid: str, n: int, actor=Depends(get_current_actor_for_read_optional), db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).version(_reader(actor), tid, n))


@router.get("/api/v1/workflow-templates/{tid}/versions/{n}/kit", summary="Download a version's kit (counted)")
@limiter.limit("30/minute")
async def get_kit(tid: str, n: int, request: Request, response: Response,
                  actor=Depends(get_current_actor_for_read_optional), db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).version(_reader(actor), tid, n, kit=True))


# -- writes ------------------------------------------------------------------------------------------------------------

@router.post("/api/v1/workflow-templates", status_code=status.HTTP_201_CREATED, summary="Create a template (a draft v1)")
async def create_template(body: Dict[str, Any] = Body(...),
                          agent: models.Agent = Depends(get_current_agent),
                          db=Depends(database.get_db)):
    _require_enabled()
    out = await _run(_lib(db).create(_writer(agent), body))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.post("/api/v1/workflow-templates/{tid}/versions", status_code=status.HTTP_201_CREATED,
             summary="Add a draft version (the owner)")
async def add_version(tid: str, body: Dict[str, Any] = Body(...), agent: models.Agent = Depends(get_current_agent),
                      db=Depends(database.get_db)):
    _require_enabled()
    out = await _run(_lib(db).add_version(_writer(agent), tid, body))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.post("/api/v1/workflow-templates/{tid}/versions/{n}/publish", summary="Publish a version (immutable after)")
async def publish_version(tid: str, n: int, agent: models.Agent = Depends(get_current_agent), db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).publish(_writer(agent), tid, n))


@router.patch("/api/v1/workflow-templates/{tid}", summary="Change the listing (title, summary, visibility, price, fork share)")
async def patch_template(tid: str, body: Dict[str, Any] = Body(...), agent: models.Agent = Depends(get_current_agent),
                         db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).patch(_writer(agent), tid, body))


@router.post("/api/v1/workflow-templates/{tid}/fork", status_code=status.HTTP_201_CREATED,
             summary="Fork a template you may use (private and free; lineage kept)")
async def fork_template(tid: str, body: Optional[Dict[str, Any]] = Body(None),
                        agent: models.Agent = Depends(get_current_agent),
                        db=Depends(database.get_db)):
    _require_enabled()
    # the body is optional: a fork that names no slug gets one derived (gwo_04e1334c; the CLI posts none)
    out = await _run(_lib(db).fork(_writer(agent), tid, body or {}))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.post("/api/v1/workflow-templates/{tid}/purchase", summary="Buy a purchase-priced template (once)")
async def purchase_template(tid: str, agent: models.Agent = Depends(get_current_agent), db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).purchase(_writer(agent), tid))


@router.post("/api/v1/workflow-templates/{tid}/instantiate", status_code=status.HTTP_201_CREATED,
             summary="Start a workflow draft from the template's workflow steps")
async def instantiate_template(tid: str, body: Dict[str, Any] = Body(...), agent: models.Agent = Depends(get_current_agent),
                               db=Depends(database.get_db)):
    _require_enabled()
    out = await _run(_lib(db).instantiate(_writer(agent), tid, body))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.post("/api/v1/workflow-templates/{tid}/certified", summary="Count a certified run (the agent's own certificate)")
async def certified_run(tid: str, body: Dict[str, Any] = Body(...), agent: models.Agent = Depends(get_current_agent),
                        db=Depends(database.get_db)):
    _require_enabled()
    return await _run(_lib(db).certified(_writer(agent), tid, body))
