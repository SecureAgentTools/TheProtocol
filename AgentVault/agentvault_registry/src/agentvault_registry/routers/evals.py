"""Public Agent Evals endpoints — suites, per-agent results, leaderboard.

Unauthenticated reads (Tier-1). Feature-gated: when EVALS_ENABLED is false the
tables are empty, so these return empty lists rather than erroring.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..database import get_db

router = APIRouter(prefix="/evals", tags=["Agent Evals"])


@router.get("/suites", summary="List published eval suites")
async def list_suites(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(models.EvalSuite).where(models.EvalSuite.enabled.is_(True))
        .order_by(models.EvalSuite.key)
    )).scalars().all()
    return {
        "suites": [
            {
                "key": s.key, "name": s.name, "description": s.description,
                "task_type": s.task_type, "interval_minutes": s.interval_minutes,
                "pays": float(s.pay_per_task or 0) > 0,
            }
            for s in rows
        ]
    }


@router.get("/agents/{agent_did:path}/results", summary="Recent eval results for an agent")
async def agent_results(
    agent_did: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(models.EvalResult)
        .where(models.EvalResult.agent_did == agent_did)
        .order_by(models.EvalResult.created_at.desc())
        .limit(limit)
    )).scalars().all()
    # Map suite_id → key for readability.
    suite_keys = {
        s.id: s.key for s in (await db.execute(select(models.EvalSuite))).scalars().all()
    }
    return {
        "agent_did": agent_did,
        "results": [
            {
                "run_id": r.run_id,
                "suite": suite_keys.get(r.suite_id, str(r.suite_id)),
                "score": round(r.score, 3),
                "passed": r.passed,
                "latency_ms": r.latency_ms,
                "error": r.error,
                "at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/leaderboard", summary="Agents ranked by mean eval score")
async def leaderboard(
    suite: Optional[str] = Query(None, description="Filter to one suite key"),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    params = {"lim": limit}
    where = ""
    if suite:
        srow = (await db.execute(
            select(models.EvalSuite.id).where(models.EvalSuite.key == suite)
        )).scalar_one_or_none()
        if srow is None:
            return {"suite": suite, "entries": []}
        where = "WHERE suite_id = :sid"
        params["sid"] = srow
    rows = (await db.execute(sa_text(f"""
        SELECT agent_did,
               AVG(score) AS mean_score,
               COUNT(*)   AS runs,
               MAX(created_at) AS last_at
        FROM eval_results
        {where}
        GROUP BY agent_did
        ORDER BY mean_score DESC, runs DESC
        LIMIT :lim
    """), params)).fetchall()
    return {
        "suite": suite,
        "entries": [
            {
                "agent_did": r[0],
                "mean_score": round(float(r[1]), 3),
                "runs": int(r[2]),
                "last_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ],
    }
