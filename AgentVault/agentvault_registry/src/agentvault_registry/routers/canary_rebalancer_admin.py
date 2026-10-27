"""Admin API for the canary_rebalancer worker (§pass27 Phase 2).

Endpoints under `/api/v1/admin/canary-rebalancer/*`, all admin_platform-gated.

  GET /admin/canary-rebalancer/status   — fleet snapshot: 24h sums + per-agent
                                          balance/state from worker's in-memory
                                          cache + canary_agents DB
  GET /admin/canary-rebalancer/events   — paginated EventStore feed for the
                                          two new event types:
                                            CanaryRebalancerFunded
                                            CanaryRebalancerErrored

Pattern mirrors §pass26 / Phase 1: 5s in-memory status cache, server-side
filters for events, no cursor pagination.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from agentvault_registry.core.observability_urls import prometheus_url
import time
from typing import Any, Dict, List, Optional

import httpx
from agentvault_registry.core.prom_self import sel  # this registry's own series in the shared Prometheus
from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..background_tasks.canary_rebalancer import (
    get_live_agent_state,
    get_runtime_config,
)
from ..database import get_db
from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/canary-rebalancer", tags=["Admin — Canary Rebalancer"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)
EVENT_STORE_URL = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
EVENT_STORE_INTERNAL_KEY = (
    os.environ.get("EVENT_STORE_API_KEY")
    or os.environ.get("EVENT_STORE_INTERNAL_KEY")
    or ""
)

_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0

REBALANCER_EVENT_TYPES = (
    "CanaryRebalancerFunded",
    "CanaryRebalancerErrored",
)


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
        logger.debug(f"[CanaryRebalancerAdmin] prom query failed: {e}")
        return []


def _sum_value(result: List[Dict[str, Any]]) -> float:
    out = 0.0
    for s in result:
        v = s.get("value")
        try:
            out += float(v[1])
        except (TypeError, ValueError, IndexError):
            pass
    return out


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
    cycles_q  = f'sum(increase({sel("canary_rebalance_cycle_total")}[24h]))'
    funded_q  = f'sum(increase({sel("canary_rebalance_funded_total")}[24h]))'
    errors_q  = f'sum(increase({sel("canary_rebalance_errors_total")}[24h]))'
    disbursed_q = f'sum(increase({sel("canary_rebalance_avt_disbursed_total")}[24h]))'
    funded_by_home_q = f'sum by (home_kind) (increase({sel("canary_rebalance_funded_total")}[24h]))'
    errors_by_home_q = f'sum by (home_kind) (increase({sel("canary_rebalance_errors_total")}[24h]))'

    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        cyc, fnd, err, disb, fnd_by_home, err_by_home = await asyncio.gather(
            _prom_instant(client, cycles_q),
            _prom_instant(client, funded_q),
            _prom_instant(client, errors_q),
            _prom_instant(client, disbursed_q),
            _prom_instant(client, funded_by_home_q),
            _prom_instant(client, errors_by_home_q),
        )

    cycles_24h = int(_sum_value(cyc))
    funded_24h = int(_sum_value(fnd))
    errors_24h = int(_sum_value(err))
    avt_disbursed_24h = _sum_value(disb)

    funded_by_home = {k: int(v) for k, v in _sum_by(fnd_by_home, "home_kind").items()}
    errors_by_home = {k: int(v) for k, v in _sum_by(err_by_home, "home_kind").items()}

    # Per-agent: canary_agents JOIN live state cache.
    agents_q = await db.execute(
        select(models.CanaryAgent).where(models.CanaryAgent.is_active == True).order_by(
            models.CanaryAgent.frame, models.CanaryAgent.registry_id
        )
    )
    agents = list(agents_q.scalars().all())
    live = get_live_agent_state()

    per_agent: List[Dict[str, Any]] = []
    agents_under_floor = 0
    for a in agents:
        ls = live.get(a.agent_did, {})
        balance = ls.get("balance")
        # Derive home_kind for display (same logic as worker, but read from DB-known fields).
        home_kind = "unknown"
        url = a.registry_url or ""
        if "registry-a" in url:
            home_kind = "mainframe-a"
        elif url.endswith(":8100"):
            home_kind = "frame-b"
        else:
            # Try to parse op slug from registry_id or URL.
            home_kind = a.registry_id or "unknown"
        state = ls.get("state", "unknown")
        if state == "under_floor":
            agents_under_floor += 1
        per_agent.append({
            "agent_did": a.agent_did,
            "name": (a.notes or a.agent_did[:30]),
            "home_kind": home_kind,
            "registry_url": a.registry_url,
            "frame": a.frame,
            "current_balance": balance,
            "balance_checked_iso": ls.get("balance_checked_iso"),
            "last_funded_iso": ls.get("last_funded_iso"),
            "next_eligible_iso": ls.get("next_eligible_iso"),
            "last_error": ls.get("last_error"),
            "state": state,
        })

    return {
        "summary": {
            "cycles_24h": cycles_24h,
            "funded_24h": funded_24h,
            "errors_24h": errors_24h,
            "avt_disbursed_24h": str(int(avt_disbursed_24h)) if avt_disbursed_24h else "0",
            "agents_active": len(agents),
            "agents_under_floor": agents_under_floor,
        },
        "by_home_kind": {
            "funded": funded_by_home,
            "errors": errors_by_home,
        },
        "config": get_runtime_config(),
        "per_agent": per_agent,
        "snapshot_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# EventStore feed
# ---------------------------------------------------------------------------

async def _es_fetch_type(client: httpx.AsyncClient, event_type: str, limit: int) -> List[Dict[str, Any]]:
    headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
    try:
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/events/",
            params={"event_type": event_type, "limit": limit},
            headers=headers,
            timeout=4.0,
        )
        if r.status_code != 200:
            return []
        return r.json() or []
    except Exception as e:
        logger.debug(f"[CanaryRebalancerAdmin] EventStore fetch {event_type} failed: {e}")
        return []


def _flatten_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = raw.get("data") or {}
    event_type = raw.get("event_type", "")
    action = "unknown"
    if event_type == "CanaryRebalancerFunded":
        action = "funded"
    elif event_type == "CanaryRebalancerErrored":
        action = "error"
    return {
        "event_id": raw.get("id") or raw.get("event_id"),
        "timestamp": raw.get("timestamp") or raw.get("created_at"),
        "event_type": event_type,
        "action": action,
        "agent_did": data.get("agent_did") or raw.get("aggregate_id"),
        "home_kind": data.get("home_kind"),
        "registry_url": data.get("registry_url"),
        "amount": data.get("amount"),
        "pre_balance": data.get("pre_balance"),
        "reason": data.get("reason"),
        "floor": data.get("floor"),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Rebalancer fleet snapshot — 5s cached."""
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
    agent_did: Optional[str] = Query(None, description="Filter by exact agent DID"),
    action: Optional[str] = Query(None, description="funded | error", pattern="^(funded|error)$"),
    home_kind: Optional[str] = Query(None, description="Filter by home_kind"),
    limit: int = Query(50, ge=1, le=200),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Recent rebalancer audit events from EventStore."""
    per_type_limit = max(limit * 2, 50)
    async with httpx.AsyncClient(timeout=6.0, verify=get_httpx_verify()) as client:
        fetches = await asyncio.gather(*[
            _es_fetch_type(client, et, per_type_limit) for et in REBALANCER_EVENT_TYPES
        ])

    merged: List[Dict[str, Any]] = []
    for raw_list in fetches:
        for raw in raw_list:
            merged.append(_flatten_event(raw))

    if agent_did:
        merged = [e for e in merged if e.get("agent_did") == agent_did]
    if action:
        merged = [e for e in merged if e.get("action") == action]
    if home_kind:
        merged = [e for e in merged if e.get("home_kind") == home_kind]

    merged.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    return {
        "events": merged[:limit],
        "total_returned": min(len(merged), limit),
        "filters_applied": {
            "agent_did": agent_did,
            "action": action,
            "home_kind": home_kind,
            "limit": limit,
        },
    }
