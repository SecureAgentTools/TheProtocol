"""V0663 (agent workflows): /api/v1/workflows. A workflow is a parent record over Guild orders (services/workflows.py).

Agent tier throughout, like the Guild: the owner is the acting agent. Reading a workflow, its candidates and its receipt chain is
the owner's too in this slice. 503 while the Guild is off (a workflow runs only on its orders)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers.guild import guild_enabled
from agentvault_registry.security import get_current_agent
from agentvault_registry.services import workflows as svc

router = APIRouter(tags=["Agent workflows"])


def _require_enabled() -> None:
    if not guild_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="The Guild is disabled on this registry")


class StepIn(BaseModel):
    key: str = Field(..., max_length=40, description="A short name for the step: lowercase letters, digits, - and _")
    role: str = Field(..., max_length=80, description="The role the step's worker plays")
    spec: Optional[str] = Field(None, max_length=6000)
    acceptance: Optional[str] = Field(None, max_length=2000, description="How the poster decides the step is done")
    budget: float = Field(..., gt=0)
    deadline_seconds: Optional[int] = Field(None, ge=60, le=2592000)
    ruleset: Optional[dict[str, Any]] = Field(None, description="Rules for this step, tightening the workflow's")
    input_from: Optional[str] = Field(None, max_length=40, description="An earlier step whose output this one takes")


class WorkflowIn(BaseModel):
    title: str = Field(..., max_length=200)
    total_budget: float = Field(..., gt=0)
    currency: Optional[str] = Field(None, max_length=12)
    ruleset: Optional[dict[str, Any]] = Field(
        None, description="bonded_only, min_reputation, min_proven_orders, max_price, org_ids, independent_of")
    steps: list[StepIn] = Field(..., min_length=1, max_length=svc.MAX_STEPS)


@router.post("/api/v1/workflows", summary="Create a workflow template (a draft; nothing is posted yet)")
async def create_workflow(body: WorkflowIn, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    return await svc.create(db, agent.did, body.model_dump())


@router.get("/api/v1/workflows", summary="My workflows")
async def my_workflows(limit: int = 50, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    return {"workflows": await svc.list_for(db, agent.did, limit)}


@router.get("/api/v1/workflows/{wid}", summary="One workflow: its steps, orders, ruleset hash and receipt chain")
async def get_workflow(wid: str, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    w = await svc._load_workflow(db, wid)
    svc._owned(w, agent.did)
    return await svc.view(db, wid)


@router.get("/api/v1/workflows/{wid}/chain", summary="The receipt chain alone, for an offline check")
async def get_chain(wid: str, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    w = await svc._load_workflow(db, wid)
    svc._owned(w, agent.did)
    v = await svc.view(db, wid)
    return {"id": wid, "ruleset_hash": v["ruleset_hash"], "chain": v["chain"], "chain_ok": v["chain_ok"],
            "verify": "link n: receipt = sha256(prev + '|' + step + '|' + output_hash); the first prev is 64 zeros"}


@router.get("/api/v1/workflows/{wid}/steps/{step_key}/candidates",
            summary="Which agents of this registry pass a step's rules")
async def step_candidates(wid: str, step_key: str, agent: models.Agent = Depends(get_current_agent),
                          db: AsyncSession = Depends(get_db)):
    _require_enabled()
    w = await svc._load_workflow(db, wid)
    svc._owned(w, agent.did)
    return await svc.candidates(db, wid, step_key)


@router.post("/api/v1/workflows/{wid}/advance",
             summary="Record settled steps and post the next step's Guild order (owner; idempotent)")
async def advance_workflow(wid: str, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    return await svc.advance(db, agent, wid)


@router.post("/api/v1/workflows/{wid}/cancel", summary="Cancel a workflow once no step order is open (owner)")
async def cancel_workflow(wid: str, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    return await svc.cancel(db, agent, wid)
