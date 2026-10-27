"""Admin API for the canary IRONHAND mTLS observability (§pass30).

Endpoints under `/api/v1/admin/canary-ironhand/*`, admin_platform-gated.
Tier-3 worker modal feed.

  GET /admin/canary-ironhand/status   — fleet summary + per-path stats + by-failure-type
  GET /admin/canary-ironhand/events   — paginated activity feed
                                       (canary_test_results WHERE transport='ironhand_mtls')
  GET /admin/canary-ironhand/svids    — per-canary SPIRE entry health crossref

Pattern mirrors canary_judge_admin: 5s in-memory cache on status, server-side
filters for events, no cursor pagination.
"""
from __future__ import annotations

import asyncio
import datetime
import json
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

router = APIRouter(prefix="/admin/canary-ironhand", tags=["Admin — Canary IRONHAND"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)
# Optional "user:pass" for an authenticated (public) Prometheus — lets cloud-ops +
# sovereign frames reach the shared Prom for the one genuinely fleet-wide metric
# (revocation-propagation p95). Unset on Frame-A (internal Prom needs no auth).
_PROM_BASIC_AUTH = os.environ.get("PROMETHEUS_BASIC_AUTH", "").strip()


def _prom_auth() -> Optional[httpx.BasicAuth]:
    if _PROM_BASIC_AUTH and ":" in _PROM_BASIC_AUTH:
        user, _, pwd = _PROM_BASIC_AUTH.partition(":")
        return httpx.BasicAuth(user, pwd)
    return None

_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0


def _parse_node_path(notes: Optional[str]) -> List[str]:
    """Extract the cross-frame FX corridor (registry slugs) from a canary_paths.notes
    value. FX paths are tagged `fx {"node_path": [...]}` — the `fx` prefix triggers the
    runner's synchronous FX self-stamp (canary_runner._record_fire), and the embedded
    JSON carries the corridor the IRONHAND Theatre animates the orb along. Intra/local
    paths (no JSON) return [] → the FE renders them as log-only, no orb travel.
    """
    if not notes:
        return []
    s = notes.strip()
    brace = s.find("{")
    if brace < 0:
        return []
    try:
        obj = json.loads(s[brace:])
        np = obj.get("node_path")
        if isinstance(np, list) and all(isinstance(x, str) for x in np):
            return np
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Prom helpers
# ---------------------------------------------------------------------------

async def _prom_instant(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
    try:
        r = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=4.0,
            auth=_prom_auth(),
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("status") != "success":
            return []
        return data.get("data", {}).get("result", []) or []
    except Exception as e:
        logger.debug(f"[CanaryIronhandAdmin] prom query failed: {e}")
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
# Status
# ---------------------------------------------------------------------------

async def _build_status(db: AsyncSession) -> Dict[str, Any]:
    # ---- Local-DB 24h outcome counts (decentralized — replaces Prometheus,
    #      which cloud-ops + sovereign frames B/C cannot reach; every registry
    #      that runs canaries already holds its own judged canary_test_results). ----
    since_24h = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    counts_q = await db.execute(
        select(
            models.CanaryTestResult.path_id,
            models.CanaryTestResult.outcome,
            func.count().label("n"),
        )
        .where(
            and_(
                models.CanaryTestResult.transport == "ironhand_mtls",
                models.CanaryTestResult.fired_at >= since_24h,
            )
        )
        .group_by(
            models.CanaryTestResult.path_id,
            models.CanaryTestResult.outcome,
        )
    )
    # keyed by (canary_paths.id:int, outcome:str). 'passed'/'failed' are judged;
    # 'fired' is unjudged/pending (judge OFF) and excluded from the pass-rate.
    count_by_pk_outcome: Dict[tuple, int] = {
        (int(pk), outcome): int(n) for pk, outcome, n in counts_q.all()
    }

    # by_failure_type — judged failures grouped by the local failure_type column
    ftype_q = await db.execute(
        select(
            models.CanaryTestResult.failure_type,
            func.count().label("n"),
        )
        .where(
            and_(
                models.CanaryTestResult.transport == "ironhand_mtls",
                models.CanaryTestResult.outcome == "failed",
                models.CanaryTestResult.fired_at >= since_24h,
            )
        )
        .group_by(models.CanaryTestResult.failure_type)
    )
    by_failure_type: Dict[str, int] = {}
    for ftype, n in ftype_q.all():
        key = ftype or "unknown"
        by_failure_type[key] = by_failure_type.get(key, 0) + int(n)

    # Aggregate 24h totals
    passes_24h = sum(v for (_pk, oc), v in count_by_pk_outcome.items() if oc == "passed")
    failures_24h = sum(v for (_pk, oc), v in count_by_pk_outcome.items() if oc == "failed")
    cycles_24h = passes_24h + failures_24h
    pass_rate_24h = (
        round(passes_24h / cycles_24h * 100, 2) if cycles_24h else None
    )

    # revocation p95 — Phase-3b: LOCAL-FIRST. Each registry's revocation_drill writes
    # propagation-lag samples to a per-registry Redis ring (canary:ironhand:revoc_lag_ms);
    # we compute p95 from those locally → no Prometheus needed where a drill runs. Falls
    # back to the shared Prom histogram (fleet aggregate) only when the local ring is empty.
    revoc_p95_ms: Optional[int] = None
    revoc_p95_source = "none"
    try:
        from ..background_tasks.leader import get_redis
        _r = await get_redis()
        if _r is not None:
            raw = await _r.lrange("canary:ironhand:revoc_lag_ms", 0, 499)
            samples = sorted(int(x) for x in raw)
            if len(samples) >= 5:  # enough for a meaningful p95
                idx = min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))
                revoc_p95_ms = samples[idx]
                revoc_p95_source = "local"
    except Exception:
        pass
    if revoc_p95_ms is None:
        # Prom fallback (this registry's own series, sel()) — used until local drill samples accumulate.
        revoc_p95_q = (
            'histogram_quantile(0.95, '
            f'sum by (le) (rate({sel("canary_ironhand_revocation_propagation_seconds_bucket")}[10m])))'
        )
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
                revoc_p95 = await _prom_instant(client, revoc_p95_q)
            if revoc_p95:
                sec = float(revoc_p95[0]["value"][1])
                if sec == sec:  # not NaN
                    revoc_p95_ms = int(sec * 1000)
                    revoc_p95_source = "prometheus"
        except Exception:
            pass

    # ---- DB query: active paths with transport='ironhand_mtls' ----
    paths_q = await db.execute(
        select(models.CanaryPath, models.CanaryAgent)
        .join(
            models.CanaryAgent,
            models.CanaryPath.sender_agent_id == models.CanaryAgent.id,
        )
        .where(
            and_(
                models.CanaryPath.is_active.is_(True),
                models.CanaryPath.transport == "ironhand_mtls",
            )
        )
    )
    path_rows = paths_q.all()

    per_path: List[Dict[str, Any]] = []
    for path, sender in path_rows:
        passes = count_by_pk_outcome.get((path.id, "passed"), 0)
        fails_for_path = count_by_pk_outcome.get((path.id, "failed"), 0)
        total = passes + fails_for_path
        rate = round(passes / total * 100, 2) if total else None

        # Latency from DB — only counted on http_status=200
        lat_q = await db.execute(
            select(
                func.percentile_cont(0.5).within_group(
                    models.CanaryTestResult.http_latency_ms.asc()
                ).label("p50"),
                func.percentile_cont(0.95).within_group(
                    models.CanaryTestResult.http_latency_ms.asc()
                ).label("p95"),
            )
            .where(
                and_(
                    models.CanaryTestResult.path_id == path.id,
                    models.CanaryTestResult.transport == "ironhand_mtls",
                    models.CanaryTestResult.http_status == 200,
                    models.CanaryTestResult.fired_at
                    >= datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(hours=24),
                )
            )
        )
        lat_row = lat_q.first()
        p50_ms = int(lat_row.p50) if lat_row and lat_row.p50 is not None else None
        p95_ms = int(lat_row.p95) if lat_row and lat_row.p95 is not None else None

        per_path.append({
            "path_id": path.path_id,
            "sender_did": sender.agent_did,
            "transport": path.transport,
            "amount": str(path.amount),
            "interval_sec": path.interval_sec,
            "is_active": path.is_active,
            "passes_24h": passes,
            "failures_24h": fails_for_path,
            "pass_rate_24h": rate,
            "p50_latency_ms": p50_ms,
            "p95_latency_ms": p95_ms,
        })

    return {
        "snapshot_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "active_paths": len(per_path),
            "cycles_24h": cycles_24h,
            "passes_24h": passes_24h,
            "failures_24h": failures_24h,
            "pass_rate_24h": pass_rate_24h,
            "revocation_p95_propagation_ms": revoc_p95_ms,
            "revocation_p95_source": revoc_p95_source,
            "interval_sec": 60,
        },
        "per_path": per_path,
        "by_failure_type": dict(
            sorted(by_failure_type.items(), key=lambda kv: -kv[1])
        ),
    }


@router.get("/status", summary="Canary IRONHAND mTLS status (Tier-3 modal feed)")
async def get_status(
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    now = time.time()
    if _STATUS_CACHE["data"] is not None and now - _STATUS_CACHE["ts"] < _STATUS_CACHE_TTL_SEC:
        return _STATUS_CACHE["data"]
    data = await _build_status(db)
    _STATUS_CACHE["ts"] = now
    _STATUS_CACHE["data"] = data
    return data


# ---------------------------------------------------------------------------
# Events feed
# ---------------------------------------------------------------------------

@router.get("/events", summary="Canary IRONHAND fire history (paginated)")
async def get_events(
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    path: Optional[str] = Query(None, description="Filter by canary_paths.path_id"),
    outcome: Optional[str] = Query(
        None, description="ok | failure | failure-by-type (passes failure_type)"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    # Resolve path filter to numeric id if provided
    path_filter_id: Optional[int] = None
    if path:
        pq = await db.execute(
            select(models.CanaryPath.id).where(models.CanaryPath.path_id == path)
        )
        row = pq.first()
        if row:
            path_filter_id = row[0]

    stmt = (
        select(
            models.CanaryTestResult,
            models.CanaryPath.path_id.label("path_human"),
            models.CanaryPath.notes.label("path_notes"),
            models.Agent.spiffe_id.label("sender_spiffe"),
        )
        .join(
            models.CanaryPath,
            models.CanaryTestResult.path_id == models.CanaryPath.id,
        )
        # Sender is local + (for FX paths) mTLS-enrolled — its SVID is the identity
        # that rides the FX route (home-registry-vouched origin_agent_spiffe). LEFT
        # JOIN so non-enrolled / missing agents still return the row.
        .outerjoin(
            models.Agent,
            models.Agent.did == models.CanaryTestResult.sender_did,
        )
        .where(models.CanaryTestResult.transport == "ironhand_mtls")
    )
    if path_filter_id is not None:
        stmt = stmt.where(models.CanaryTestResult.path_id == path_filter_id)
    if outcome == "ok":
        stmt = stmt.where(models.CanaryTestResult.http_status == 200)
    elif outcome == "failure":
        stmt = stmt.where(models.CanaryTestResult.failure_type.isnot(None))
    elif outcome and outcome not in ("ok", "failure"):
        # treat as failure_type filter
        stmt = stmt.where(models.CanaryTestResult.failure_type == outcome)

    stmt = stmt.order_by(models.CanaryTestResult.fired_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    events: List[Dict[str, Any]] = []
    for row, path_human, path_notes, sender_spiffe in rows:
        events.append({
            "test_id": row.test_id,
            "path_human": path_human,
            "transport": row.transport,
            "fired_iso": row.fired_at.isoformat() if row.fired_at else None,
            "completed_iso": row.completed_at.isoformat() if row.completed_at else None,
            "backend": row.backend,
            "sender_did": row.sender_did,
            "receiver_did": row.receiver_did,
            "amount": str(row.amount),
            "transfer_id": row.transfer_id,
            "http_status": row.http_status,
            "http_latency_ms": row.http_latency_ms,
            "outcome": row.outcome,
            "failure_type": row.failure_type,
            "failure_detail": row.failure_detail,
            # IRONHAND Theatre: corridor the orb travels + the agent SVID that rides it.
            # node_path is [] for intra/local paths (FE renders those as log-only).
            "node_path": _parse_node_path(path_notes),
            "origin_agent_spiffe": sender_spiffe or "",
        })

    return {"events": events, "limit": limit, "offset": offset, "count": len(events)}


# ---------------------------------------------------------------------------
# SVID health crossref
# ---------------------------------------------------------------------------

@router.get("/svids", summary="Canary IRONHAND SPIRE entry health crossref")
async def get_svids(
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Crossreference canary-mtls agents (canary_agents joined via canary_paths
    where transport='ironhand_mtls') with SPIRE entries via agent_spire helper.

    Returns:
      [
        { sender_did, path_id, spiffe_id, mtls_enabled, mtls_enrolled_at,
          spire_entry_present, spire_ttl_sec, spire_selector }
      ]
    """
    # All sender agents on ironhand paths
    q = await db.execute(
        select(models.CanaryPath, models.CanaryAgent, models.Agent)
        .join(
            models.CanaryAgent,
            models.CanaryPath.sender_agent_id == models.CanaryAgent.id,
        )
        .outerjoin(
            models.Agent,
            models.Agent.did == models.CanaryAgent.agent_did,
        )
        .where(models.CanaryPath.transport == "ironhand_mtls")
    )
    rows = q.all()

    # Try to fetch live SPIRE entries (best-effort — local docker exec may not
    # work in all environments, so don't fail if it does)
    spire_entries: Dict[str, Dict[str, Any]] = {}
    try:
        from ..services import agent_spire as _agent_spire
        # agent_spire.py doesn't expose a list helper today; we look up
        # per-DID via the existing convention. Skip if not exposed.
        list_fn = getattr(_agent_spire, "list_entries", None)
        if callable(list_fn):
            try:
                live = list_fn()
                if isinstance(live, list):
                    for e in live:
                        sid = e.get("spiffe_id") or ""
                        spire_entries[sid] = e
            except Exception as e:
                logger.debug(f"[CanaryIronhandAdmin] list_entries failed: {e}")
    except Exception:
        pass

    out: List[Dict[str, Any]] = []
    for path, canary, agent in rows:
        spiffe_id = getattr(agent, "spiffe_id", None) if agent else None
        spire_present = spiffe_id in spire_entries if spiffe_id else False
        out.append({
            "path_id": path.path_id,
            "sender_did": canary.agent_did,
            "spiffe_id": spiffe_id,
            "mtls_enabled": getattr(agent, "mtls_enabled", False) if agent else False,
            "mtls_enrolled_at": (
                agent.mtls_enrolled_at.isoformat()
                if agent and getattr(agent, "mtls_enrolled_at", None)
                else None
            ),
            "spire_entry_present": spire_present,
        })

    return {"svids": out, "count": len(out)}
