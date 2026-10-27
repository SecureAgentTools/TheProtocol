"""Admin API for the supply_auditor worker (§pass28 Phase 4).

Endpoints under `/api/v1/admin/supply-auditor/*`, all admin_platform-gated.
The worker runs on EVERY registry (both Frame A registry-a and Frame B
frame-b-registry by default — no env gate). The status endpoint aggregates
fleet-wide via Prometheus `registry_id` label.

  GET /admin/supply-auditor/status   — fleet snapshot: 24h cycles + breaches
                                       per registry, latest audit values
                                       per frame, live delta
  GET /admin/supply-auditor/events   — paginated EventStore feed for
                                       SupplyInvariantBreach (the worker's
                                       only emit; rare in healthy steady state)

Note: this is the *worker's* admin surface. The EventStore's own
`/projections/supply-audit` endpoint remains the authoritative read for
the current invariant state — this admin endpoint wraps it with worker-cycle
context (when last polled, fail count, breach history).
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

from .. import models, security
from ..background_tasks.supply_auditor import get_last_cycle_stats
from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/supply-auditor", tags=["Admin — Supply Auditor"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)
EVENT_STORE_URL = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
EVENT_STORE_INTERNAL_KEY = (
    os.environ.get("EVENT_STORE_API_KEY")
    or os.environ.get("EVENT_STORE_INTERNAL_KEY")
    or ""
)

_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0


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
        logger.debug(f"[SupplyAuditorAdmin] prom query failed: {e}")
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


def _max_by(result: List[Dict[str, Any]], label: str) -> Dict[str, float]:
    """For gauges with `multiprocess_mode='max'` we want last value per registry."""
    out: Dict[str, float] = {}
    for s in result:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        key = labels.get(label) or "_"
        if key not in out or val > out[key]:
            out[key] = val
    return out


def _sum_value(result: List[Dict[str, Any]]) -> float:
    out = 0.0
    for s in result:
        v = s.get("value")
        try:
            out += float(v[1])
        except (TypeError, ValueError, IndexError):
            pass
    return out


# ---------------------------------------------------------------------------
# EventStore helpers
# ---------------------------------------------------------------------------

async def _fetch_supply_audit_live(client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Read the EventStore's own /projections/supply-audit endpoint.

    This is the authoritative current-state view. The worker just polls it.
    We surface it here so the modal can show both Frame A and Frame B values
    side-by-side; the worker's recorded snapshot might be one cycle behind.
    """
    headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
    try:
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/projections/supply-audit",
            headers=headers,
            timeout=4.0,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        logger.debug(f"[SupplyAuditorAdmin] EventStore audit fetch failed: {e}")
        return None


async def _fetch_cross_frame_audit_live(client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Read the EventStore's /projections/cross-frame-audit.

    SF-4 cross-frame supply consistency + the FX invariants I1 (per-frame Δ=0),
    I2 (fx_reserve solvency ≥ floor) and I3 (per-swap value conservation, WS-E).
    This is an EventStore-only projection; the registry has no generic ES-path
    proxy, so this read-only mirror powers the FX Desk integrity panel (B8).
    """
    headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
    try:
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/projections/cross-frame-audit",
            headers=headers,
            timeout=6.0,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        logger.debug(f"[SupplyAuditorAdmin] EventStore cross-frame-audit fetch failed: {e}")
        return None


async def _es_fetch_breaches(client: httpx.AsyncClient, limit: int) -> List[Dict[str, Any]]:
    headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
    try:
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/events/",
            params={"event_type": "SupplyInvariantBreach", "limit": limit},
            headers=headers,
            timeout=4.0,
        )
        if r.status_code != 200:
            return []
        return r.json() or []
    except Exception as e:
        logger.debug(f"[SupplyAuditorAdmin] EventStore breach fetch failed: {e}")
        return []


def _flatten_breach(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = raw.get("data") or {}
    return {
        "event_id": raw.get("id") or raw.get("event_id"),
        "timestamp": raw.get("timestamp") or raw.get("created_at"),
        "delta": data.get("delta"),
        "net_supply": data.get("net_supply"),
        "total_circulating": data.get("total_circulating"),
        "tokens_issued": data.get("tokens_issued"),
        "tokens_destroyed": data.get("tokens_destroyed"),
        "tokens_fees": data.get("tokens_fees"),
        "tolerance": data.get("tolerance"),
        "auto_lockdown": data.get("auto_lockdown"),
        "audit_type": data.get("audit_type"),
        "detected_at": data.get("detected_at"),
    }


# ---------------------------------------------------------------------------
# Status builder
# ---------------------------------------------------------------------------

async def _build_status() -> Dict[str, Any]:
    cycles_24h_q   = f'sum by (registry_id) (increase({sel("supply_audit_cycle_total")}[24h]))'
    breaches_24h_q = f'sum by (registry_id) (increase({sel("supply_audit_breaches_total")}[24h]))'
    errors_24h_q   = f'sum by (registry_id, reason) (increase({sel("supply_audit_errors_total")}[24h]))'
    last_delta_q   = f'{sel("supply_audit_last_delta")}'
    net_supply_q   = f'{sel("supply_audit_net_supply")}'
    circulating_q  = f'{sel("supply_audit_circulating")}'

    # §SOVKIT T5 (2026-09-14): one client serves Prometheus and the live store audit; the store's TLS context serves both
    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        cycles, breaches, errs, last_delta, net_supply, circulating, live = await asyncio.gather(
            _prom_instant(client, cycles_24h_q),
            _prom_instant(client, breaches_24h_q),
            _prom_instant(client, errors_24h_q),
            _prom_instant(client, last_delta_q),
            _prom_instant(client, net_supply_q),
            _prom_instant(client, circulating_q),
            _fetch_supply_audit_live(client),
        )

    cycles_by_registry  = _sum_by(cycles, "registry_id")
    breach_by_registry  = _sum_by(breaches, "registry_id")
    delta_by_registry   = _max_by(last_delta, "registry_id")
    supply_by_registry  = _max_by(net_supply, "registry_id")
    circ_by_registry    = _max_by(circulating, "registry_id")

    # Group errors_by_registry (sum across reasons).
    errors_by_registry: Dict[str, float] = {}
    errors_by_reason: Dict[str, float] = {}
    for s in errs:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        rid = labels.get("registry_id") or "_"
        rsn = labels.get("reason") or "_"
        errors_by_registry[rid] = errors_by_registry.get(rid, 0.0) + val
        errors_by_reason[rsn] = errors_by_reason.get(rsn, 0.0) + val

    registries = (
        set(cycles_by_registry) | set(breach_by_registry) | set(errors_by_registry)
        | set(delta_by_registry) | set(supply_by_registry) | set(circ_by_registry)
    )
    registries = {r for r in registries if r and r != "_"}

    per_registry: List[Dict[str, Any]] = []
    for rid in sorted(registries):
        per_registry.append({
            "registry_id": rid,
            "cycles_24h": int(cycles_by_registry.get(rid, 0)),
            "breaches_24h": int(breach_by_registry.get(rid, 0)),
            "errors_24h": int(errors_by_registry.get(rid, 0)),
            "last_delta": delta_by_registry.get(rid),
            "net_supply": supply_by_registry.get(rid),
            "total_circulating": circ_by_registry.get(rid),
            "healthy": breach_by_registry.get(rid, 0) == 0 and delta_by_registry.get(rid, 0) == 0,
        })

    return {
        "summary": {
            "cycles_24h": int(sum(cycles_by_registry.values())),
            "breaches_24h": int(sum(breach_by_registry.values())),
            "errors_24h": int(sum(errors_by_registry.values())),
            "registries_reporting": len(per_registry),
            # Live ground-truth from EventStore /supply-audit (may be None if ES unreachable):
            "live_status": (live or {}).get("status"),
            "live_delta": (live or {}).get("delta"),
            "live_net_supply": (live or {}).get("net_supply"),
            "live_total_circulating": (live or {}).get("total_circulating"),
        },
        "errors_by_reason": {k: int(v) for k, v in errors_by_reason.items()},
        "per_registry": per_registry,
        "live_audit": live,                          # Full EventStore payload for the modal Live tab
        "local_last_cycle": get_last_cycle_stats(),  # This registry's most-recent recorded cycle
        "snapshot_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def status_endpoint(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Supply auditor fleet snapshot — 5s cached."""
    now = time.monotonic()
    cached = _STATUS_CACHE.get("data")
    if cached is not None and (now - _STATUS_CACHE.get("ts", 0.0)) < _STATUS_CACHE_TTL_SEC:
        return cached
    data = await _build_status()
    _STATUS_CACHE["data"] = data
    _STATUS_CACHE["ts"] = now
    return data


@router.get("/events")
async def events_endpoint(
    limit: int = Query(50, ge=1, le=200),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """SupplyInvariantBreach event feed (rare in healthy steady state)."""
    async with httpx.AsyncClient(timeout=6.0, verify=get_httpx_verify()) as client:  # §SOVKIT T5: the store's TLS context
        raw = await _es_fetch_breaches(client, limit)
    events = [_flatten_breach(r) for r in raw]
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return {
        "events": events[:limit],
        "total_returned": min(len(events), limit),
        "filters_applied": {"limit": limit},
    }


@router.get("/cross-frame-audit")
async def cross_frame_audit_endpoint(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """FX Desk integrity (B8): read-only proxy to the EventStore's
    /projections/cross-frame-audit. Surfaces the FX invariants (I1 per-frame Δ=0,
    I2 reserve solvency, I3 per-swap value-conservation) + per-frame replication
    so the FX Desk can render live cross-frame supply/value integrity instead of a
    "pending" placeholder. Returns {available: false, ...} when this frame's ES has
    no such projection (e.g. a non-FX frame) so the UI degrades gracefully.
    """
    # The EventStore is reached over mTLS (https nginx-event-store sidecar) on
    # sandbox/prod — a plain client fails (HTTP 000). get_httpx_verify() returns
    # an SSLContext carrying the SPIRE bundle CA + our client SVID (full mTLS),
    # or True for a plain-http ES. Mirrors event_emitter / es_ssl_helper.
    async with httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
        data = await _fetch_cross_frame_audit_live(client)
    if data is None:
        return {"available": False, "reason": "EventStore cross-frame-audit unavailable on this frame."}
    if isinstance(data, dict):
        return {"available": True, **data}
    return {"available": True, "data": data}
