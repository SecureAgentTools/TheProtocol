"""Admin API for the cross-TEG 2PC sweeper (§pass26).

Endpoints under `/api/v1/admin/cross-teg-sweeper/*`, all admin_platform-gated.

  GET /admin/cross-teg-sweeper/status   — fleet snapshot: per-TEG counters,
                                          pending gauge, last cycle time
  GET /admin/cross-teg-sweeper/events   — paginated audit-event feed sourced
                                          from EventStore (3 event types)

The status endpoint queries Prometheus for the sweeper's counters/gauges.
The events endpoint queries the EventStore directly for the 3 event types
(CrossTEGCoordinationAbortedByExpiry / CommitResumed / SweepErrored) and
merges into a unified feed.

Frontend: `CrossTegSweeperModal.vue` polls these via `services/api/crossTegSweeper.ts`.
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
from fastapi import APIRouter, Depends, HTTPException, Query, Security

from .. import models, security
from ..es_ssl_helper import get_httpx_verify


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/cross-teg-sweeper", tags=["Admin — Cross-TEG Sweeper"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)
EVENT_STORE_URL = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
# Registry uses `EVENT_STORE_API_KEY` (canonical TEG/registry name), with
# `EVENT_STORE_INTERNAL_KEY` accepted as a fallback for legacy deployments.
EVENT_STORE_INTERNAL_KEY = (
    os.environ.get("EVENT_STORE_API_KEY")
    or os.environ.get("EVENT_STORE_INTERNAL_KEY")
    or ""
)

SWEEPER_EVENT_TYPES = (
    "CrossTEGCoordinationAbortedByExpiry",
    "CrossTEGCoordinationCommitResumed",
    "CrossTEGSweepErrored",
)

# In-memory cache for /status (5s TTL) so the modal's 5s poll doesn't hammer Prom.
_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0


# ---------------------------------------------------------------------------
# Prometheus helpers
# ---------------------------------------------------------------------------


async def _prom_instant(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
    """Execute an instant PromQL query, return the `result` array (best-effort)."""
    try:
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=4.0)
        if r.status_code != 200:
            logger.debug(f"[CrossTegSweeperAdmin] prom query non-200: {r.status_code} for {query}")
            return []
        data = r.json()
        if data.get("status") != "success":
            return []
        return data.get("data", {}).get("result", []) or []
    except Exception as e:
        logger.debug(f"[CrossTegSweeperAdmin] prom query failed: {e}")
        return []


def _result_to_teg_map(result: List[Dict[str, Any]]) -> Dict[str, float]:
    """Convert a Prom result array → {teg_id: numeric_value}."""
    out: Dict[str, float] = {}
    for series in result:
        labels = series.get("metric", {})
        value = series.get("value")
        if not value:
            continue
        teg_id = labels.get("teg_id")
        try:
            v = float(value[1])
        except (TypeError, ValueError, IndexError):
            continue
        if teg_id:
            out[teg_id] = out.get(teg_id, 0.0) + v
    return out


def _result_to_teg_job_map(result: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build a {teg_id: job_label} index from a Prom result. Used as the
    authoritative disambiguator when a TEG's `TEG_ID` is generic enough to
    collide with another (e.g. Frame B's literal `teg-layer`). The Prom
    `job` label is unambiguous per scrape target.
    Last-write-wins is acceptable — within one cycle, every TEG has exactly
    one job label.
    """
    out: Dict[str, str] = {}
    for series in result:
        labels = series.get("metric", {})
        teg_id = labels.get("teg_id")
        job = labels.get("job")
        if teg_id and job:
            out[teg_id] = job
    return out


async def _build_status() -> Dict[str, Any]:
    """Build the full /status response by querying Prometheus."""
    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        # 24h windows + an "active" pending gauge + cycle freshness.
        cycles_24h_q = f"sum by (teg_id) (increase({sel('cross_teg_sweep_cycle_total', component='teg')}[24h]))"
        aborted_24h_q = f"sum by (teg_id) (increase({sel('cross_teg_sweep_aborted_total', component='teg')}[24h]))"
        resumed_24h_q = f"sum by (teg_id) (increase({sel('cross_teg_sweep_commit_resumed_total', component='teg')}[24h]))"
        errors_24h_q = f"sum by (teg_id) (increase({sel('cross_teg_sweep_errors_total', component='teg')}[24h]))"
        pending_q = f"sum by (teg_id) ({sel('cross_teg_pending_coordinations', component='teg')})"

        cycles, aborted, resumed, errors, pending = await asyncio.gather(
            _prom_instant(client, cycles_24h_q),
            _prom_instant(client, aborted_24h_q),
            _prom_instant(client, resumed_24h_q),
            _prom_instant(client, errors_24h_q),
            _prom_instant(client, pending_q),
        )

    c_map = _result_to_teg_map(cycles)
    a_map = _result_to_teg_map(aborted)
    r_map = _result_to_teg_map(resumed)
    e_map = _result_to_teg_map(errors)
    p_map = _result_to_teg_map(pending)

    # Build a single (teg_id → job) index across ALL series so we can
    # disambiguate teg_ids whose literal value would otherwise collide
    # (e.g. Frame B's TEG_ID=`teg-layer` historically matches Frame A's
    # legacy `teg-layer` alias). Job labels are unambiguous per scrape
    # target and stable across rebuilds.
    job_map: Dict[str, str] = {}
    for series_list in (cycles, aborted, resumed, errors, pending):
        for tid, job in _result_to_teg_job_map(series_list).items():
            job_map.setdefault(tid, job)

    # Union of TEG IDs observed across any series. Sort for stable UI order.
    all_teg_ids = sorted(set(c_map) | set(a_map) | set(r_map) | set(e_map) | set(p_map))

    per_op: List[Dict[str, Any]] = []
    for teg_id in all_teg_ids:
        errors_24h = int(e_map.get(teg_id, 0))
        per_op.append({
            "teg_id": teg_id,
            "op_slug": _teg_id_to_op_slug(teg_id, job=job_map.get(teg_id)),
            "cycles_24h": int(c_map.get(teg_id, 0)),
            "aborted_24h": int(a_map.get(teg_id, 0)),
            "resumed_24h": int(r_map.get(teg_id, 0)),
            "errors_24h": errors_24h,
            "pending": int(p_map.get(teg_id, 0)),
            "healthy": errors_24h == 0,
        })

    return {
        "summary": {
            "cycles_24h": int(sum(c_map.values())),
            "aborted_24h": int(sum(a_map.values())),
            "resumed_24h": int(sum(r_map.values())),
            "errors_24h": int(sum(e_map.values())),
            "pending_total": int(sum(p_map.values())),
            "teg_count": len(all_teg_ids),
        },
        "per_op": per_op,
        "snapshot_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _teg_id_to_op_slug(teg_id: str, *, job: Optional[str] = None) -> str:
    """Best-effort mapping of teg_id → human-friendly op_slug.

    Frame-aware: when `job` is supplied (always available on Prometheus-
    sourced responses; absent on EventStore-sourced events), it's used as
    the authoritative disambiguator first. The Prom `job` label is
    derived from the scrape target name (e.g. `frame-b-teg`, `op-tokyo-teg`),
    which is unambiguous even when two frames share the same generic
    `TEG_ID` value (Frame B's `teg-layer` collides with Frame A's
    legacy alias).

    Resolution order:
      1. job=='frame-b-teg' → 'frame-b'
      2. teg_id starts with 'teg-layer-op-' → cloud-op slug
      3. teg_id exactly 'teg-layer' (no suffix) → 'frame-b' (Frame B's
         current generic ID; the only TEG that uses this literal value)
      4. teg_id contains 'frame-b' / 'frame_b' → 'frame-b'
      5. teg_id in {'teg-layer-a', 'teg_layer_a'} → 'mainframe-a'
      6. teg_id starts with 'teg-layer-test' → sandbox slug
      7. fallback: pass through

    Generic enough to extend to additional frames if they ever ship — add
    the new frame's scrape-job name to step 1.
    """
    # 1. Job-based fast path: unambiguous when Prom is the data source.
    if job:
        jl = job.lower()
        if jl == "frame-b-teg":
            return "frame-b"

    if not teg_id:
        return ""
    lower = teg_id.lower()
    # 2a. Cloud-op pattern (`teg-layer-op-tokyo` → `op-tokyo`).
    if lower.startswith("teg-layer-op-"):
        return lower[len("teg-layer-"):]
    # 2b. Current cloud-op pattern (`teg-op-tokyo` → `op-tokyo`). The
    # registry-side TEG_ID env was originally `teg-layer-op-{city}` but
    # the cloud_provisioner today writes `teg-op-{city}`. Handle both.
    if lower.startswith("teg-op-"):
        return lower[len("teg-"):]
    # 3. Frame B's current literal TEG_ID. Distinct from Frame A's legacy
    # `teg-layer-a`. If a future deployment ever reuses this literal for
    # another frame, the job-label fast path above (step 1) catches it.
    if lower == "teg-layer":
        return "frame-b"
    # 4. Any other frame-b-tagged identifier.
    if "frame-b" in lower or "frame_b" in lower:
        return "frame-b"
    # 5. Frame A mainframe.
    if lower in ("teg-layer-a", "teg_layer_a"):
        return "mainframe-a"
    # 6. Sandbox.
    if lower.startswith("teg-layer-test"):
        return lower[len("teg-layer-"):]
    return teg_id


# ---------------------------------------------------------------------------
# EventStore helpers
# ---------------------------------------------------------------------------


async def _es_fetch_type(
    client: httpx.AsyncClient,
    event_type: str,
    limit: int,
) -> List[Dict[str, Any]]:
    headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
    try:
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/events/",
            params={"event_type": event_type, "limit": limit},
            headers=headers,
            timeout=4.0,
        )
        if r.status_code != 200:
            logger.debug(
                f"[CrossTegSweeperAdmin] EventStore non-200 ({r.status_code}) "
                f"for event_type={event_type}"
            )
            return []
        return r.json() or []
    except Exception as e:
        logger.debug(f"[CrossTegSweeperAdmin] EventStore fetch failed for {event_type}: {e}")
        return []


def _flatten_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Shape one EventStore event into the slimmer feed-row the UI expects."""
    data = raw.get("data") or {}
    event_type = raw.get("event_type", "")
    action = "unknown"
    if event_type == "CrossTEGCoordinationAbortedByExpiry":
        action = "aborted"
    elif event_type == "CrossTEGCoordinationCommitResumed":
        action = "resumed"
    elif event_type == "CrossTEGSweepErrored":
        action = "error"
    return {
        "event_id": raw.get("id") or raw.get("event_id"),
        "timestamp": raw.get("timestamp") or raw.get("created_at"),
        "event_type": event_type,
        "action": action,
        "teg_id": data.get("teg_id") or data.get("source_teg_id"),
        "op_slug": _teg_id_to_op_slug(data.get("teg_id") or data.get("source_teg_id") or ""),
        "transfer_id": data.get("transfer_id"),
        "source_agent_id": data.get("source_agent_id") or raw.get("aggregate_id"),
        "target_agent_id": data.get("target_agent_id"),
        "amount": data.get("amount"),
        "currency": data.get("currency"),
        "prior_status": data.get("prior_status"),
        "error_message": data.get("error"),
        "resolution": data.get("resolution"),
        "expired_at": data.get("expired_by_sweep_at"),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def status_endpoint(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Fleet snapshot of sweeper health, sourced from Prometheus.

    Cached for 5s to avoid hammering Prometheus when the modal polls.
    Returns 200 with empty arrays even when Prometheus is unreachable —
    UI degrades gracefully.
    """
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
    op: Optional[str] = Query(None, description="Filter by op_slug (e.g. op-paris, mainframe-a)"),
    action: Optional[str] = Query(
        None,
        description="Filter by action: aborted | resumed | error",
        pattern="^(aborted|resumed|error)$",
    ),
    limit: int = Query(50, ge=1, le=200),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Paginated audit feed across the 3 sweeper event types.

    Merges parallel EventStore queries (one per event type), sorts DESC by
    timestamp, filters by op_slug / action, returns up to `limit` events.

    No cursor pagination today — the audit feed is naturally small (sweeper
    rarely emits in healthy steady-state) and we cap at 200 rows. If feed
    growth ever crosses that, add cursor pagination then.
    """
    # Fetch each event type in parallel. Over-fetch (3x limit) so we have
    # headroom after merge + filter.
    per_type_limit = max(limit * 2, 50)
    async with httpx.AsyncClient(timeout=6.0, verify=get_httpx_verify()) as client:
        fetches = await asyncio.gather(*[
            _es_fetch_type(client, et, per_type_limit) for et in SWEEPER_EVENT_TYPES
        ])

    merged: List[Dict[str, Any]] = []
    for raw_list in fetches:
        for raw in raw_list:
            merged.append(_flatten_event(raw))

    # Apply filters
    if op:
        merged = [e for e in merged if e.get("op_slug") == op]
    if action:
        merged = [e for e in merged if e.get("action") == action]

    # Sort DESC by timestamp (newest first). Missing timestamps fall to the bottom.
    merged.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    return {
        "events": merged[:limit],
        "total_returned": min(len(merged), limit),
        "filters_applied": {
            "op": op,
            "action": action,
            "limit": limit,
        },
    }
