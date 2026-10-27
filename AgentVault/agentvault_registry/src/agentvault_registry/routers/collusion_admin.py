"""Admin API for the collusion_worker (§pass28 Phase 5).

Endpoints under `/api/v1/admin/collusion/*`, all admin_platform-gated.
The worker runs DAILY (86400s default cadence) on every registry. The
status endpoint aggregates fleet-wide via Prometheus `registry_id` label
and queries the AuditorFlagLog table for ring history.

  GET /admin/collusion/status   — last cycle freshness + 24h/lifetime ring
                                  counts per registry + per-severity rollup
  GET /admin/collusion/rings    — paginated AuditorFlagLog rows with
                                  `flag_type='CollusionRingDetected'` — the
                                  ring detail feed with severity / SCC size /
                                  member DIDs in `details` JSON
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
from ..background_tasks.collusion_worker import (
    get_last_cycle_stats,
    get_interval_sec,
)
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/collusion", tags=["Admin — Collusion Detector"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)

_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 15.0  # 24h-cadence worker → longer cache acceptable


# ---------------------------------------------------------------------------
# Prometheus helpers
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
        logger.debug(f"[CollusionAdmin] prom query failed: {e}")
        return []


def _sum_by(result: List[Dict[str, Any]], label: str) -> Dict[str, float]:
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


# ---------------------------------------------------------------------------
# Status builder
# ---------------------------------------------------------------------------

async def _build_status(db: AsyncSession) -> Dict[str, Any]:
    # Prom aggregates (cycles + rings + errors) across registries.
    cycles_24h_q  = f'sum by (registry_id) (increase({sel("collusion_cycle_total")}[24h]))'
    decays_24h_q  = f'sum by (registry_id) (increase({sel("collusion_decay_passes_total")}[24h]))'
    rings_24h_q   = f'sum by (registry_id) (increase({sel("collusion_rings_detected_total")}[24h]))'
    errors_24h_q  = f'sum by (registry_id, stage) (increase({sel("collusion_errors_total")}[24h]))'

    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        cycles, decays, rings_prom, errs = await asyncio.gather(
            _prom_instant(client, cycles_24h_q),
            _prom_instant(client, decays_24h_q),
            _prom_instant(client, rings_24h_q),
            _prom_instant(client, errors_24h_q),
        )

    cycles_by_registry = _sum_by(cycles, "registry_id")
    decays_by_registry = _sum_by(decays, "registry_id")
    rings_by_registry  = _sum_by(rings_prom, "registry_id")

    errors_by_registry: Dict[str, float] = {}
    errors_by_stage: Dict[str, float] = {}
    for s in errs:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        rid = labels.get("registry_id") or "_"
        stage = labels.get("stage") or "_"
        errors_by_registry[rid] = errors_by_registry.get(rid, 0.0) + val
        errors_by_stage[stage] = errors_by_stage.get(stage, 0.0) + val

    registries = (
        set(cycles_by_registry) | set(decays_by_registry)
        | set(rings_by_registry) | set(errors_by_registry)
    )
    registries = {r for r in registries if r and r != "_"}

    # DB aggregates from auditor_flag_logs (ring history, severity rollup).
    cutoff_24h = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    # Lifetime ring count.
    total_q = await db.execute(
        select(func.count()).select_from(models.AuditorFlagLog).where(
            models.AuditorFlagLog.flag_type == "CollusionRingDetected"
        )
    )
    lifetime_rings = int(total_q.scalar() or 0)

    # 24h ring count.
    db_rings_24h_q = await db.execute(
        select(func.count()).select_from(models.AuditorFlagLog).where(
            models.AuditorFlagLog.flag_type == "CollusionRingDetected",
            models.AuditorFlagLog.created_at >= cutoff_24h,
        )
    )
    rings_24h_db = int(db_rings_24h_q.scalar() or 0)

    # Severity rollup (lifetime).
    severity_q = await db.execute(
        select(
            models.AuditorFlagLog.severity,
            func.count().label("n"),
        )
        .where(models.AuditorFlagLog.flag_type == "CollusionRingDetected")
        .group_by(models.AuditorFlagLog.severity)
    )
    by_severity: Dict[str, int] = {}
    for sev, n in severity_q:
        by_severity[sev or "UNKNOWN"] = int(n or 0)

    # Last 5 distinct flagged DIDs (top-of-mind list).
    last_dids_q = await db.execute(
        select(models.AuditorFlagLog.flagged_agent_did, func.max(models.AuditorFlagLog.created_at).label("last_seen"))
        .where(models.AuditorFlagLog.flag_type == "CollusionRingDetected")
        .group_by(models.AuditorFlagLog.flagged_agent_did)
        .order_by(func.max(models.AuditorFlagLog.created_at).desc())
        .limit(8)
    )
    top_dids: List[Dict[str, Any]] = []
    for did, last_seen in last_dids_q:
        top_dids.append({
            "agent_did": did,
            "last_flagged_iso": last_seen.isoformat() if last_seen else None,
        })

    # Per-registry rollup.
    per_registry: List[Dict[str, Any]] = []
    for rid in sorted(registries):
        per_registry.append({
            "registry_id": rid,
            "cycles_24h": int(cycles_by_registry.get(rid, 0)),
            "decay_passes_24h": int(decays_by_registry.get(rid, 0)),
            "rings_detected_24h": int(rings_by_registry.get(rid, 0)),
            "errors_24h": int(errors_by_registry.get(rid, 0)),
        })

    local = get_last_cycle_stats()
    next_cycle_iso = None
    if local.get("last_cycle_iso"):
        try:
            last = datetime.datetime.fromisoformat(local["last_cycle_iso"])
            next_cycle_iso = (last + datetime.timedelta(seconds=get_interval_sec())).isoformat()
        except Exception:
            pass

    return {
        "summary": {
            "lifetime_rings": lifetime_rings,
            "rings_24h": rings_24h_db,
            "cycles_24h": int(sum(cycles_by_registry.values())),
            "errors_24h": int(sum(errors_by_registry.values())),
            "registries_reporting": len(per_registry),
            "interval_sec": get_interval_sec(),
            "next_cycle_iso": next_cycle_iso,
        },
        "by_severity": by_severity,
        "errors_by_stage": {k: int(v) for k, v in errors_by_stage.items()},
        "per_registry": per_registry,
        "top_flagged_dids": top_dids,
        "local_last_cycle": local,
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
    """Collusion worker fleet snapshot — 15s cached (24h-cadence worker)."""
    now = time.monotonic()
    cached = _STATUS_CACHE.get("data")
    if cached is not None and (now - _STATUS_CACHE.get("ts", 0.0)) < _STATUS_CACHE_TTL_SEC:
        return cached
    data = await _build_status(db)
    _STATUS_CACHE["data"] = data
    _STATUS_CACHE["ts"] = now
    return data


@router.get("/rings")
async def rings_endpoint(
    severity: Optional[str] = Query(None, description="LOW | MEDIUM | HIGH"),
    agent_did: Optional[str] = Query(None, description="Filter by flagged agent DID"),
    since: Optional[str] = Query(None, description='Window: "24h", "7d", "30d", "all"'),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Paginated CollusionRingDetected rows. Sorted DESC by created_at."""
    stmt = (
        select(models.AuditorFlagLog)
        .where(models.AuditorFlagLog.flag_type == "CollusionRingDetected")
        .order_by(models.AuditorFlagLog.created_at.desc())
        .limit(limit)
    )
    if severity:
        stmt = stmt.where(models.AuditorFlagLog.severity == severity.upper())
    if agent_did:
        stmt = stmt.where(models.AuditorFlagLog.flagged_agent_did == agent_did)
    if since and since != "all":
        win_map = {"24h": 24, "7d": 168, "30d": 720}
        hours = win_map.get(since)
        if hours:
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
            stmt = stmt.where(models.AuditorFlagLog.created_at >= cutoff)

    rows = await db.execute(stmt)
    out: List[Dict[str, Any]] = []
    for r in rows.scalars().all():
        details = r.details or {}
        out.append({
            "id": r.id,
            "flagged_agent_did": r.flagged_agent_did,
            "severity": r.severity,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "scc_size": details.get("scc_size"),
            "score": details.get("score"),
            "members": details.get("members") or details.get("ring_members") or [],
            "details": details,
        })

    return {
        "rings": out,
        "total_returned": len(out),
        "filters_applied": {
            "severity": severity,
            "agent_did": agent_did,
            "since": since,
            "limit": limit,
        },
    }
