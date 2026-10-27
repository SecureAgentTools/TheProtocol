"""Admin Agent Evals — suite/task CRUD + run-now. Commander/admin only."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db

router = APIRouter(prefix="/admin/evals", tags=["Admin — Agent Evals"])


class SuiteUpsert(BaseModel):
    key: str = Field(..., max_length=80)
    name: str = Field(..., max_length=160)
    description: Optional[str] = None
    task_type: str = Field("http_probe", pattern="^(http_probe|a2a_message|code_patch)$")  # code_patch: GÖDEL FORGE quorum-scored
    config: Optional[Dict[str, Any]] = None
    interval_minutes: Optional[int] = Field(None, ge=1)
    enabled: bool = False
    pay_per_task: str = "0"
    emit_reputation_signal: bool = False
    target_dids: Optional[List[str]] = None


class TaskUpsert(BaseModel):
    name: str = Field(..., max_length=160)
    input: Optional[Dict[str, Any]] = None
    scorer: str = Field("status_ok", pattern="^(exact|contains|regex|status_ok|latency_under_ms|code_patch)$")
    expected: Optional[Dict[str, Any]] = None
    weight: float = 1.0
    # GÖDEL FORGE (mig 0124): holdout = hidden test (expected/grading never shown to the target);
    # grader_config = per-task grader params (code_patch problem set for the verifier quorum).
    holdout: bool = False
    grader_config: Optional[Dict[str, Any]] = None


@router.get("/suites")
async def list_all_suites(
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    rows = (await db.execute(select(models.EvalSuite).order_by(models.EvalSuite.id))).scalars().all()
    out = []
    for s in rows:
        n_tasks = len((await db.execute(
            select(models.EvalTask.id).where(models.EvalTask.suite_id == s.id)
        )).scalars().all())
        out.append({
            "id": s.id, "key": s.key, "name": s.name, "task_type": s.task_type,
            "enabled": s.enabled, "interval_minutes": s.interval_minutes,
            "pay_per_task": float(s.pay_per_task or 0),
            "emit_reputation_signal": s.emit_reputation_signal,
            "target_dids": s.target_dids, "tasks": n_tasks,
            "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        })
    return {"suites": out}


@router.post("/suites")
async def upsert_suite(
    body: SuiteUpsert,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    existing = (await db.execute(
        select(models.EvalSuite).where(models.EvalSuite.key == body.key)
    )).scalar_one_or_none()
    from decimal import Decimal
    fields = dict(
        name=body.name, description=body.description, task_type=body.task_type,
        config=body.config, interval_minutes=body.interval_minutes, enabled=body.enabled,
        pay_per_task=Decimal(body.pay_per_task), emit_reputation_signal=body.emit_reputation_signal,
        target_dids=body.target_dids,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        suite = existing
    else:
        suite = models.EvalSuite(key=body.key, **fields)
        db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return {"id": suite.id, "key": suite.key, "enabled": suite.enabled}


@router.delete("/suites/{suite_id}", status_code=204)
async def delete_suite(
    suite_id: int,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    suite = (await db.execute(
        select(models.EvalSuite).where(models.EvalSuite.id == suite_id)
    )).scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    await db.delete(suite)
    await db.commit()


@router.post("/suites/{suite_id}/tasks")
async def add_task(
    suite_id: int,
    body: TaskUpsert,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    suite = (await db.execute(
        select(models.EvalSuite).where(models.EvalSuite.id == suite_id)
    )).scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    task = models.EvalTask(
        suite_id=suite_id, name=body.name, input=body.input,
        scorer=body.scorer, expected=body.expected, weight=body.weight,
        holdout=body.holdout, grader_config=body.grader_config,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return {"id": task.id, "suite_id": suite_id, "name": task.name}


@router.post("/suites/{suite_id}/run")
async def run_now(
    suite_id: int,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    from ..background_tasks.eval_runner import run_suite_once, EVALS_ENABLED
    if not EVALS_ENABLED:
        raise HTTPException(status_code=409, detail="EVALS_ENABLED is false on this registry")
    run_id = await run_suite_once(suite_id)
    if run_id is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return {"suite_id": suite_id, "run_id": run_id, "status": "completed"}
