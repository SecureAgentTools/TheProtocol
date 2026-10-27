"""Admin API for the saga_timeout_checker worker (§pass27 Phase 3).

Endpoints under `/api/v1/admin/saga-timeout/*`, all admin_platform-gated.

The worker runs on BOTH registry-a and frame-b-registry. The status endpoint
aggregates fleet-wide via Prometheus `registry_id` label so the modal shows
both frames in one view.

  GET /admin/saga-timeout/status   — fleet snapshot: 24h sums per cycle_kind,
                                     per-registry breakdown, frame-pair flow
                                     matrix, current pending backlog
  GET /admin/saga-timeout/events   — paginated activity feed merging:
                                     - SettlementSagaTimedOut (new)
                                     - CrossFrameTransferRefunded (existing,
                                       saga emits via refund path)
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
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db
from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/saga-timeout", tags=["Admin — Saga Timeout"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)
EVENT_STORE_URL = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
EVENT_STORE_INTERNAL_KEY = (
    os.environ.get("EVENT_STORE_API_KEY")
    or os.environ.get("EVENT_STORE_INTERNAL_KEY")
    or ""
)

_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0

SAGA_EVENT_TYPES = (
    "SettlementSagaTimedOut",
    "CrossFrameTransferRefunded",
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
        logger.debug(f"[SagaTimeoutAdmin] prom query failed: {e}")
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


def _sum_value(result: List[Dict[str, Any]]) -> float:
    out = 0.0
    for s in result:
        v = s.get("value")
        try:
            out += float(v[1])
        except (TypeError, ValueError, IndexError):
            pass
    return out


def _grouped_by(result: List[Dict[str, Any]], keys: tuple) -> Dict[tuple, float]:
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

async def _build_status(db: AsyncSession) -> Dict[str, Any]:
    cycle_24h_q = f'sum by (registry_id, cycle_kind) (increase({sel("saga_timeout_checker_cycle_total")}[24h]))'
    settle_24h_q = f'sum by (registry_id) (increase({sel("saga_settlement_timed_out_total")}[24h]))'
    refund_24h_q = f'sum by (registry_id, source_frame, target_frame) (increase({sel("saga_cross_frame_refunded_total")}[24h]))'
    errors_24h_q = f'sum by (registry_id, cycle_kind, reason) (increase({sel("saga_timeout_checker_errors_total")}[24h]))'
    pending_q = f'sum by (registry_id, cycle_kind) ({sel("saga_pending_timeouts")})'

    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        cycles, settle, refund, errs, pending = await asyncio.gather(
            _prom_instant(client, cycle_24h_q),
            _prom_instant(client, settle_24h_q),
            _prom_instant(client, refund_24h_q),
            _prom_instant(client, errors_24h_q),
            _prom_instant(client, pending_q),
        )

    cycles_by_registry_kind = _grouped_by(cycles, ("registry_id", "cycle_kind"))
    settle_by_registry = _sum_by(settle, "registry_id")
    refund_by_pair = _grouped_by(refund, ("registry_id", "source_frame", "target_frame"))
    errors_by_registry_kind = _grouped_by(errs, ("registry_id", "cycle_kind"))
    pending_by_registry_kind = _grouped_by(pending, ("registry_id", "cycle_kind"))

    # Per-registry rollup.
    registries = set()
    for (rid, _ck) in cycles_by_registry_kind:
        registries.add(rid)
    for rid in settle_by_registry:
        registries.add(rid)
    for (rid, _ck) in errors_by_registry_kind:
        registries.add(rid)
    for (rid, _ck) in pending_by_registry_kind:
        registries.add(rid)
    for (rid, _sf, _tf) in refund_by_pair:
        registries.add(rid)

    per_registry: List[Dict[str, Any]] = []
    for rid in sorted(r for r in registries if r and r != "_"):
        per_registry.append({
            "registry_id": rid,
            "settlement_cycles_24h": int(cycles_by_registry_kind.get((rid, "settlement"), 0)),
            "cross_frame_cycles_24h": int(cycles_by_registry_kind.get((rid, "cross_frame"), 0)),
            "settlements_timed_out_24h": int(settle_by_registry.get(rid, 0)),
            "cross_frame_refunded_24h": int(sum(
                v for (rr, _sf, _tf), v in refund_by_pair.items() if rr == rid
            )),
            "errors_24h": int(sum(v for (rr, _ck), v in errors_by_registry_kind.items() if rr == rid)),
            "pending_now": int(sum(v for (rr, _ck), v in pending_by_registry_kind.items() if rr == rid)),
        })

    # Frame-pair flow matrix (collapsed across registries; the source_frame
    # label is the registry's local trust domain, target_frame is the
    # cross-frame destination).
    frames = set()
    for (_rid, sf, tf), _v in refund_by_pair.items():
        if sf and sf != "_": frames.add(sf)
        if tf and tf != "_": frames.add(tf)
    frame_pair_matrix: List[Dict[str, Any]] = []
    for sf in sorted(frames):
        for tf in sorted(frames):
            cnt = int(sum(v for (_rid, ssf, ttf), v in refund_by_pair.items()
                          if ssf == sf and ttf == tf))
            if cnt or sf == tf:
                frame_pair_matrix.append({
                    "source_frame": sf,
                    "target_frame": tf,
                    "refunded_24h": cnt,
                })

    # Pending sagas table — cross_registry_settlements in non-terminal saga
    # states whose `saga_timeout_at` is past. Mirrors the worker's own query.
    pending_settlements: List[Dict[str, Any]] = []
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        rows = await db.execute(
            select(models.CrossRegistrySettlement)
            .where(
                models.CrossRegistrySettlement.saga_state.in_(["INITIATED", "SLASH_REQUESTED"]),
                models.CrossRegistrySettlement.saga_timeout_at.isnot(None),
                models.CrossRegistrySettlement.saga_timeout_at < now,
            )
            .order_by(models.CrossRegistrySettlement.saga_timeout_at.asc())
            .limit(50)
        )
        for s in rows.scalars().all():
            saga_started = getattr(s, "saga_started_at", None) or getattr(s, "created_at", None)
            pending_settlements.append({
                "settlement_id": str(s.id),
                "saga_state": s.saga_state,
                "status": s.status,
                "dispute_id": s.dispute_id,
                "saga_timeout_at": s.saga_timeout_at.isoformat() if s.saga_timeout_at else None,
                "age_hours": (
                    (now - saga_started).total_seconds() / 3600 if saga_started else None
                ),
                "requested_amount": str(s.requested_amount) if s.requested_amount is not None else None,
                "defendant_did": s.defendant_did,
                "complainant_did": s.complainant_did,
            })
    except Exception as e:
        logger.debug(f"[SagaTimeoutAdmin] pending settlements probe failed: {e}")

    total_pending = int(sum(pending_by_registry_kind.values()))

    return {
        "summary": {
            "settlements_timed_out_24h": int(sum(settle_by_registry.values())),
            "cross_frame_refunded_24h": int(sum(v for v in refund_by_pair.values())),
            "pending_now": total_pending,
            "errors_24h": int(sum(errors_by_registry_kind.values())),
            "settlement_cycles_24h": int(sum(
                v for (_rid, ck), v in cycles_by_registry_kind.items() if ck == "settlement"
            )),
            "cross_frame_cycles_24h": int(sum(
                v for (_rid, ck), v in cycles_by_registry_kind.items() if ck == "cross_frame"
            )),
        },
        "per_registry": per_registry,
        "frame_pair_matrix": frame_pair_matrix,
        "pending_settlements": pending_settlements,
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
        logger.debug(f"[SagaTimeoutAdmin] EventStore fetch {event_type} failed: {e}")
        return []


def _flatten_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = raw.get("data") or {}
    event_type = raw.get("event_type", "")
    if event_type == "SettlementSagaTimedOut":
        action = "settlement"
    elif event_type == "CrossFrameTransferRefunded":
        action = "cross_frame"
    else:
        action = "unknown"
    return {
        "event_id": raw.get("id") or raw.get("event_id"),
        "timestamp": raw.get("timestamp") or raw.get("created_at"),
        "event_type": event_type,
        "action": action,
        "registry_id": data.get("registry_id"),
        "source_frame": data.get("source_frame"),
        "target_frame": data.get("target_frame"),
        "settlement_id": data.get("settlement_id"),
        "transfer_id": data.get("transfer_id") or raw.get("aggregate_id"),
        "sender_did": data.get("sender_did"),
        "receiver_did": data.get("receiver_did"),
        "amount": data.get("amount"),
        "reason": data.get("reason"),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Fleet-wide saga timeout snapshot — 5s cached."""
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
    action: Optional[str] = Query(
        None,
        description="settlement | cross_frame",
        pattern="^(settlement|cross_frame)$",
    ),
    source_frame: Optional[str] = Query(None),
    target_frame: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Recent saga-timeout events merging settlement + cross-frame refund streams."""
    per_type_limit = max(limit * 2, 50)
    async with httpx.AsyncClient(timeout=6.0, verify=get_httpx_verify()) as client:
        fetches = await asyncio.gather(*[
            _es_fetch_type(client, et, per_type_limit) for et in SAGA_EVENT_TYPES
        ])

    merged: List[Dict[str, Any]] = []
    for raw_list in fetches:
        for raw in raw_list:
            merged.append(_flatten_event(raw))

    if action:
        merged = [e for e in merged if e.get("action") == action]
    if source_frame:
        merged = [e for e in merged if e.get("source_frame") == source_frame]
    if target_frame:
        merged = [e for e in merged if e.get("target_frame") == target_frame]

    merged.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    return {
        "events": merged[:limit],
        "total_returned": min(len(merged), limit),
        "filters_applied": {
            "action": action,
            "source_frame": source_frame,
            "target_frame": target_frame,
            "limit": limit,
        },
    }
