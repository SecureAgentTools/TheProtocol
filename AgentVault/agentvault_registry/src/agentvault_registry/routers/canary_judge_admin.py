"""Admin API for the canary_judge worker (§pass27 Phase 1).

Endpoints under `/api/v1/admin/canary-judge/*`, all admin_platform-gated.
Lives alongside the legacy `/admin/canary/*` router (which still backs
AdminCanaries.vue) — this one is the Tier-3 modal feed.

  GET /admin/canary-judge/status   — judge summary (Prom-sourced 24h sums +
                                     per-path stats from canary_test_results
                                     DB; live in-flight count from
                                     `canary_transfer_pending` gauge)
  GET /admin/canary-judge/events   — paginated activity feed; DB-sourced
                                     (judge persists outcomes to
                                     canary_test_results — no EventStore
                                     query needed)

Pattern mirrors §pass26's `cross_teg_sweeper_admin.py`: 5s in-memory cache on
the status response, server-side filters for events, no cursor pagination.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from agentvault_registry.core.observability_urls import prometheus_url
from agentvault_registry.es_ssl_helper import get_httpx_verify
import time
from typing import Any, Dict, List, Optional

import httpx
from agentvault_registry.core.prom_self import sel  # this registry's own series in the shared Prometheus
from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/canary-judge", tags=["Admin — Canary Judge"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)

# 5s status cache to avoid hammering Prom from the modal's 5s poll.
_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0


# ---------------------------------------------------------------------------
# Prometheus helpers (same shape as cross_teg_sweeper_admin)
# ---------------------------------------------------------------------------

async def _prom_instant(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
    try:
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=4.0)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("status") != "success":
            return []
        return data.get("data", {}).get("result", []) or []
    except Exception as e:
        logger.debug(f"[CanaryJudgeAdmin] prom query failed: {e}")
        return []


def _sum_by_label(result: List[Dict[str, Any]], label: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for s in result:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        key = labels.get(label) or "_"
        out[key] = out.get(key, 0.0) + val
    return out


def _grouped_by(result: List[Dict[str, Any]], keys: tuple) -> Dict[tuple, float]:
    """Group Prom result rows by a tuple of label names → summed value."""
    out: Dict[tuple, float] = {}
    for s in result:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        k = tuple(labels.get(lbl) or "_" for lbl in keys)
        out[k] = out.get(k, 0.0) + val
    return out


# ---------------------------------------------------------------------------
# Status builder
# ---------------------------------------------------------------------------

def _summary_from_paths(per_path: List[Dict[str, Any]]) -> Dict[str, Any]:
    """§MCPTEST30 (V0541): the 24 h totals of THIS registry's canaries, from the per-path rows of its own results.

    They came from Prometheus (`sum by (outcome) (increase(canary_transfer_total[24h]))`) with no label for the
    asking registry, so every registry reported the whole scraped fleet, beside a per-path list that was its own: a
    sandbox registry printed Frame A's ~3,600 failed firings a day (its paths still fire at the stopped legacy nodes)
    as its own 37.6 %, and the federation suite's judge check failed on production's canaries (round 11)."""
    passes = sum(int(p.get("passes_24h") or 0) for p in per_path)
    failures = sum(int(p.get("failures_24h") or 0) for p in per_path)
    cycles = passes + failures
    return {
        "cycles_24h": cycles,
        "passes_24h": passes,
        "failures_24h": failures,
        "pass_rate_24h": round(passes / cycles * 100, 1) if cycles else None,
    }


async def _build_status(db: AsyncSession) -> Dict[str, Any]:
    # ---- Prom queries ----
    # 24h windows on the existing metrics emitted by canary_judge. §MCPTEST30 (V0541): the outcome totals are no longer
    # read here (they were the whole scraped fleet's); the summary sums this registry's own rows (_summary_from_paths).
    by_pb_outcome = f'sum by (path, backend, outcome) (increase({sel("canary_transfer_total")}[24h]))'
    path_health_q = f'{sel("canary_path_health")}'
    pending_q     = f'sum({sel("canary_transfer_pending")})'

    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        by_pbo, path_health, pending = await asyncio.gather(
            _prom_instant(client, by_pb_outcome),
            _prom_instant(client, path_health_q),
            _prom_instant(client, pending_q),
        )

    pb_outcome = _grouped_by(by_pbo, ("path", "backend", "outcome"))
    # Build per-(path, backend) aggregates from the Prom slice.
    per_pb: Dict[tuple, Dict[str, int]] = {}
    for (p, b, o), v in pb_outcome.items():
        if p == "_" or b == "_":
            continue
        key = (p, b)
        per_pb.setdefault(key, {"passes_24h": 0, "failures_24h": 0})
        if o == "passed":
            per_pb[key]["passes_24h"] = int(v)
        elif o == "failed":
            per_pb[key]["failures_24h"] = int(v)

    # Live in-flight count.
    in_flight = 0
    for s in pending:
        v = s.get("value")
        try:
            in_flight += int(float(v[1]))
        except (TypeError, ValueError, IndexError):
            pass

    # Health flag per (path, backend) from the gauge.
    health_map: Dict[tuple, int] = {}
    for s in path_health:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            health_map[(labels.get("path") or "_", labels.get("backend") or "_")] = int(float(v[1]))
        except (TypeError, ValueError, IndexError):
            pass

    # ---- DB queries: per-path stats. Two passes (avoids SQLAlchemy
    # WithinGroup+filter combo that asyncpg doesn't translate). Pass 1:
    # counts + last_fired (all outcomes). Pass 2: latency aggregates
    # (passed-only). Merge by path_id.
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    counts_q = await db.execute(
        select(
            models.CanaryPath.id,
            models.CanaryPath.path_id,
            models.CanaryPath.backend,
            models.CanaryPath.is_active,
            models.CanaryTestResult.outcome,
            func.count(models.CanaryTestResult.id).label("n"),
            func.max(models.CanaryTestResult.fired_at).label("last_fired_at"),
        )
        .select_from(models.CanaryPath)
        .outerjoin(
            models.CanaryTestResult,
            and_(
                models.CanaryTestResult.path_id == models.CanaryPath.id,
                models.CanaryTestResult.fired_at >= cutoff,
            ),
        )
        .group_by(
            models.CanaryPath.id,
            models.CanaryPath.path_id,
            models.CanaryPath.backend,
            models.CanaryPath.is_active,
            models.CanaryTestResult.outcome,
        )
    )
    counts_by_path: Dict[int, Dict[str, Any]] = {}
    for path_id_db, path_human, backend, is_active, outcome, n, last_fired in counts_q:
        entry = counts_by_path.setdefault(int(path_id_db), {
            "path_human": path_human,
            "backend": backend,
            "is_active": bool(is_active),
            "passed": 0,
            "failed": 0,
            "fired": 0,
            "last_fired_at": None,
        })
        if outcome:
            entry[outcome] = int(n or 0)
        if last_fired is not None and (entry["last_fired_at"] is None or last_fired > entry["last_fired_at"]):
            entry["last_fired_at"] = last_fired

    latency_q = await db.execute(
        select(
            models.CanaryTestResult.path_id,
            func.avg(models.CanaryTestResult.total_latency_ms).label("avg_ms"),
            func.percentile_cont(0.5).within_group(
                models.CanaryTestResult.total_latency_ms.asc()
            ).label("p50_ms"),
            func.percentile_cont(0.95).within_group(
                models.CanaryTestResult.total_latency_ms.asc()
            ).label("p95_ms"),
            func.max(models.CanaryTestResult.total_latency_ms).label("max_ms"),
        )
        .where(
            models.CanaryTestResult.fired_at >= cutoff,
            models.CanaryTestResult.outcome == "passed",
            models.CanaryTestResult.total_latency_ms.is_not(None),
        )
        .group_by(models.CanaryTestResult.path_id)
    )
    latency_by_path: Dict[int, Dict[str, Optional[int]]] = {}
    for path_id_db, avg_ms, p50, p95, max_ms in latency_q:
        latency_by_path[int(path_id_db)] = {
            "avg_latency_ms": int(avg_ms) if avg_ms is not None else None,
            "p50_latency_ms": int(p50) if p50 is not None else None,
            "p95_latency_ms": int(p95) if p95 is not None else None,
            "max_latency_ms": int(max_ms) if max_ms is not None else None,
        }

    per_path: List[Dict[str, Any]] = []
    for path_id_db, entry in sorted(counts_by_path.items(), key=lambda kv: kv[1]["path_human"]):
        n_passed = int(entry.get("passed", 0))
        n_failed = int(entry.get("failed", 0))
        denom = n_passed + n_failed
        pass_rate = round(n_passed / denom * 100, 1) if denom else None
        lat = latency_by_path.get(path_id_db, {})
        per_path.append({
            "path_id": int(path_id_db),
            "path_human": entry["path_human"],
            "backend": entry["backend"],
            "is_active": entry["is_active"],
            "passes_24h": n_passed,
            "failures_24h": n_failed,
            "pass_rate_24h": pass_rate,
            "avg_latency_ms": lat.get("avg_latency_ms"),
            "p50_latency_ms": lat.get("p50_latency_ms"),
            "p95_latency_ms": lat.get("p95_latency_ms"),
            "max_latency_ms": lat.get("max_latency_ms"),
            "last_fired_iso": entry["last_fired_at"].isoformat() if entry["last_fired_at"] else None,
            "health": bool(health_map.get((entry["path_human"], entry["backend"]), 1)),
        })

    # Failure-type breakdown for the Outcome tab.
    fail_breakdown_q = await db.execute(
        select(
            func.coalesce(models.CanaryTestResult.failure_type, "other").label("ft"),
            func.count().label("n"),
        )
        .where(
            models.CanaryTestResult.fired_at >= cutoff,
            models.CanaryTestResult.outcome == "failed",
        )
        .group_by("ft")
    )
    by_failure: Dict[str, int] = {}
    for ft, n in fail_breakdown_q:
        by_failure[ft] = int(n or 0)

    return {
        "summary": {
            **_summary_from_paths(per_path),
            "errors_24h": 0,  # judge errors are loop-level; if needed surface from worker_errors_total
            "active_paths": sum(1 for p in per_path if p["is_active"]),
            "in_flight_count": in_flight,
        },
        "by_failure_type": by_failure,
        "per_path": per_path,
        "snapshot_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Judge summary snapshot — 5s cached. Degrades gracefully if Prom is partitioned."""
    now = time.monotonic()
    cached = _STATUS_CACHE.get("data")
    if cached is not None and (now - _STATUS_CACHE.get("ts", 0.0)) < _STATUS_CACHE_TTL_SEC:
        return cached
    data = await _build_status(db)
    _STATUS_CACHE["data"] = data
    _STATUS_CACHE["ts"] = now
    return data


@router.get("/events")
async def events_endpoint(
    path: Optional[str] = Query(None, description="Filter by path_human (e.g. registry-a→tokyo:async)"),
    backend: Optional[str] = Query(None, description="Filter by backend (intra|async|2pc)"),
    outcome: Optional[str] = Query(None, description="Filter by outcome (passed|failed|fired)"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Recent canary_test_results, filtered. Sorted DESC by fired_at."""
    stmt = (
        select(
            models.CanaryTestResult,
            models.CanaryPath.path_id.label("path_human"),
        )
        .join(models.CanaryPath, models.CanaryPath.id == models.CanaryTestResult.path_id)
        .order_by(models.CanaryTestResult.fired_at.desc())
        .limit(limit)
    )
    if path:
        stmt = stmt.where(models.CanaryPath.path_id == path)
    if backend:
        stmt = stmt.where(models.CanaryTestResult.backend == backend)
    if outcome:
        stmt = stmt.where(models.CanaryTestResult.outcome == outcome)

    rows = await db.execute(stmt)
    events: List[Dict[str, Any]] = []
    for r, path_human in rows:
        events.append({
            "test_id": r.test_id,
            "path_id": int(r.path_id),
            "path_human": path_human,
            "backend": r.backend,
            "fired_iso": r.fired_at.isoformat() if r.fired_at else None,
            "completed_iso": r.completed_at.isoformat() if r.completed_at else None,
            "outcome": r.outcome,
            "http_status": r.http_status,
            "http_latency_ms": r.http_latency_ms,
            "total_latency_ms": r.total_latency_ms,
            "failure_type": r.failure_type,
            "failure_detail": r.failure_detail,
            "transfer_id": r.transfer_id,
            "sender_did": r.sender_did,
            "receiver_did": r.receiver_did,
            "amount": str(r.amount) if r.amount is not None else None,
        })

    return {
        "events": events,
        "total_returned": len(events),
        "filters_applied": {
            "path": path,
            "backend": backend,
            "outcome": outcome,
            "limit": limit,
        },
    }
