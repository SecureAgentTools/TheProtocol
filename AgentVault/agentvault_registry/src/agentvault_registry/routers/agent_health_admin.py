"""Admin API for the agent_health_checker worker (§pass29 Phase 7).

Endpoints under `/api/v1/admin/agent-health/*`, admin_platform-gated.
Aggregates BOTH registry-a and frame-b-registry via Prom `registry_id`.

  GET /admin/agent-health/status       — fleet snapshot: cycle/probe/error
                                          counts per registry + 24h state-
                                          change breakdown + DB summary of
                                          agents by last_health bucket
  GET /admin/agent-health/transitions  — recent state transitions (in-memory
                                          ring buffer, newest first)
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
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..background_tasks.agent_health_checker import (
    get_last_cycle_stats,
    get_recent_transitions,
)
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/agent-health", tags=["Admin — Agent Health"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)

_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0


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
        logger.debug(f"[AgentHealthAdmin] prom query failed: {e}")
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


async def _build_status(db: AsyncSession) -> Dict[str, Any]:
    cycles_q       = f'sum by (registry_id) (increase({sel("agent_health_cycle_total")}[24h]))'
    probes_q       = f'sum by (registry_id, outcome) (increase({sel("agent_health_probes_total")}[24h]))'
    transitions_q  = f'sum by (registry_id, from_state, to_state) (increase({sel("agent_health_state_changes_total")}[24h]))'

    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        cycles, probes, transitions_prom = await asyncio.gather(
            _prom_instant(client, cycles_q),
            _prom_instant(client, probes_q),
            _prom_instant(client, transitions_q),
        )

    cycles_by_registry = _sum_by(cycles, "registry_id")

    # Probes by outcome (sum across registries)
    probes_by_outcome: Dict[str, float] = {}
    probes_by_registry: Dict[str, float] = {}
    for s in probes:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        rid = labels.get("registry_id") or "_"
        outcome = labels.get("outcome") or "_"
        probes_by_outcome[outcome] = probes_by_outcome.get(outcome, 0.0) + val
        probes_by_registry[rid] = probes_by_registry.get(rid, 0.0) + val

    # Transitions by (from, to)
    transitions_grid: Dict[str, Dict[str, int]] = {}
    for s in transitions_prom:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        f = labels.get("from_state") or "?"
        t = labels.get("to_state") or "?"
        if f == "_" or t == "_":
            continue
        row = transitions_grid.setdefault(f, {})
        row[t] = int(row.get(t, 0) + val)

    registries = set(cycles_by_registry) | set(probes_by_registry)
    registries = {r for r in registries if r and r != "_"}
    per_registry: List[Dict[str, Any]] = []
    for rid in sorted(registries):
        per_registry.append({
            "registry_id": rid,
            "cycles_24h": int(cycles_by_registry.get(rid, 0)),
            "probes_24h": int(probes_by_registry.get(rid, 0)),
        })

    # DB rollup: agents by last_health bucket (current state).
    db_summary: Dict[str, int] = {"healthy": 0, "unhealthy": 0, "unreachable": 0, "never_observed": 0}
    try:
        rows = await db.execute(text("""
            SELECT COALESCE(last_health, 'never_observed') AS bucket, COUNT(*)
            FROM agents
            WHERE status IN ('active', 'healthy', 'unhealthy', 'unreachable')
            GROUP BY bucket
        """))
        for bucket, n in rows:
            db_summary[bucket or "never_observed"] = int(n or 0)
    except Exception as e:
        logger.debug(f"[AgentHealthAdmin] DB summary failed: {e}")

    # Agents currently in non-healthy state (worth surfacing as a top-of-mind list).
    flapping_dids: List[Dict[str, Any]] = []
    try:
        rows = await db.execute(text("""
            SELECT a.did, a.last_health, a.last_active_at, ac.card_data->>'url' AS url
            FROM agents a
            JOIN agent_cards ac ON ac.agent_did = a.did
            WHERE a.status IN ('active', 'healthy', 'unhealthy', 'unreachable')
            AND a.last_health IN ('unhealthy', 'unreachable')
            ORDER BY a.last_active_at DESC NULLS LAST
            LIMIT 25
        """))
        for did, lh, last_active, url in rows:
            flapping_dids.append({
                "agent_did": did,
                "last_health": lh,
                "last_active_iso": last_active.isoformat() if last_active else None,
                "url": url,
            })
    except Exception as e:
        logger.debug(f"[AgentHealthAdmin] flapping query failed: {e}")

    total_active = sum(db_summary.values())
    return {
        "summary": {
            "cycles_24h": int(sum(cycles_by_registry.values())),
            "probes_24h": int(sum(probes_by_registry.values())),
            "state_changes_24h": int(sum(
                sum(row.values()) for row in transitions_grid.values()
            )),
            "registries_reporting": len(per_registry),
            "agents_active": total_active,
            "agents_unhealthy": db_summary.get("unhealthy", 0),
            "agents_unreachable": db_summary.get("unreachable", 0),
            "agents_never_observed": db_summary.get("never_observed", 0),
            "interval_sec": 300,
        },
        "probes_by_outcome": {k: int(v) for k, v in probes_by_outcome.items()},
        "transitions_grid": transitions_grid,
        "per_registry": per_registry,
        "db_summary": db_summary,
        "flapping_or_down": flapping_dids,
        "local_last_cycle": get_last_cycle_stats(),
        "snapshot_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@router.get("/status")
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Agent-health fleet snapshot — 5s cached."""
    now = time.monotonic()
    cached = _STATUS_CACHE.get("data")
    if cached is not None and (now - _STATUS_CACHE.get("ts", 0.0)) < _STATUS_CACHE_TTL_SEC:
        return cached
    data = await _build_status(db)
    _STATUS_CACHE["data"] = data
    _STATUS_CACHE["ts"] = now
    return data


@router.get("/transitions")
async def transitions_endpoint(
    limit: int = Query(100, ge=1, le=200),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Recent agent-health state transitions (in-memory ring buffer, newest first)."""
    transitions = get_recent_transitions(limit)
    return {
        "transitions": transitions,
        "total_returned": len(transitions),
        "filters_applied": {"limit": limit},
    }
