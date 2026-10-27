"""Admin API for the federation_sync worker (§pass29 Phase 6).

Endpoints under `/api/v1/admin/federation-sync/*`, admin_platform-gated.
Aggregates BOTH registry-a and frame-b-registry via Prom `registry` label.

  GET /admin/federation-sync/status   — fleet snapshot: cycles + per-peer
                                        attempt counts + recent error rate
                                        + per-peer freshness (last_synced_at
                                        from peer_registries DB)
  GET /admin/federation-sync/peers    — per-peer detail rows w/ filters
                                        (status=ACTIVE|INACTIVE|..., stale=true)
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
from sqlalchemy.orm import aliased

from .. import models, security
from ..background_tasks.federation_sync import (
    get_last_cycle_stats,
    get_sync_interval,
)
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/federation-sync", tags=["Admin — Federation Sync"])

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)

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
        logger.debug(f"[FedSyncAdmin] prom query failed: {e}")
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


# Staleness thresholds (seconds) — modal color codes based on these.
# Operates on the EFFECTIVE freshness signal:
#   - For direct peers: max(peer_registries.last_synced_at, last_card_received)
#   - For chain children: last_card_received (since last_synced_at is dead
#     metadata frozen at the topology-demotion moment per crud_peer_registry
#     audit T8 comment, 2026-05-05).
#
# §pass30 fix: the previous version measured only peer_registries.last_synced_at,
# producing a 7-of-9-peers false-positive on prod because that column is only
# written by `_update_peer_sync_status` for direct peers. Chain children's
# cards arrive fresh via the BFS mesh (verified: every source_registry's
# agent_cards.updated_at moves on every cycle) but their last_synced_at
# stays frozen — by design.
def _staleness_class(seconds_since: Optional[float], interval_sec: int) -> str:
    if seconds_since is None:
        return "never"
    if seconds_since <= interval_sec * 1.5:        # within ~1.5 cycles
        return "fresh"
    if seconds_since <= interval_sec * 4:          # within ~4 cycles
        return "stale"
    return "very_stale"


def _name_matches_source(peer_name: str, source_registry: str) -> bool:
    """Match a peer.name against agent_cards.source_registry strings.

    source_registry strings observed on prod look like:
      spiffe://agentvault.com/ns/agentvault/sa/registry-{peer_name}
      spiffe://agentvault.com/operator/{peer_name}/registry
      spiffe://frame-b.theprotocol.cloud/operator/{peer_name}/registry
      spiffe://frame-b.theprotocol.cloud/service/registry-{peer_name}

    Conservative substring match on lowercase. With only ~9 active peers
    on prod and unique-enough names (op-tokyo / op-paris / Frame-B / etc),
    false positives are unlikely. The function NEVER matches when the
    peer name appears as a *prefix* of another (e.g. `op-paris` won't
    match `op-paris-2`) because we require the peer name to be either
    surrounded by `/` `-` or end-of-string boundaries.
    """
    if not peer_name or not source_registry:
        return False
    pname = peer_name.lower()
    src = source_registry.lower()
    if pname not in src:
        return False
    # Check boundary characters to reduce false matches.
    idx = src.find(pname)
    while idx >= 0:
        left_ok = idx == 0 or src[idx - 1] in "/-:"
        end = idx + len(pname)
        right_ok = end >= len(src) or src[end] in "/-:"
        if left_ok and right_ok:
            return True
        idx = src.find(pname, idx + 1)
    return False


# ---------------------------------------------------------------------------
# Status builder
# ---------------------------------------------------------------------------

async def _build_status(db: AsyncSession) -> Dict[str, Any]:
    cycles_24h_q  = f'sum by (registry) (increase({sel("federation_sync_cycle_total")}[24h]))'
    errors_24h_q  = f'sum by (registry, reason) (increase({sel("federation_sync_errors_total")}[24h]))'
    attempts_24h_q = f'sum by (registry, peer, outcome) (increase({sel("federation_sync_peer_attempts_total")}[24h]))'
    last_success_q = f'{sel("federation_sync_last_success_timestamp_seconds")}'
    duration_q     = f'{sel("federation_sync_last_cycle_duration_ms")}'

    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        cycles, errs, attempts, last_success, duration = await asyncio.gather(
            _prom_instant(client, cycles_24h_q),
            _prom_instant(client, errors_24h_q),
            _prom_instant(client, attempts_24h_q),
            _prom_instant(client, last_success_q),
            _prom_instant(client, duration_q),
        )

    cycles_by_registry = _sum_by(cycles, "registry")
    last_success_by_registry: Dict[str, float] = {}
    for s in last_success:
        labels = s.get("metric", {})
        v = s.get("value")
        rid = labels.get("registry") or "_"
        try:
            last_success_by_registry[rid] = float(v[1])
        except (TypeError, ValueError, IndexError):
            pass
    duration_by_registry: Dict[str, float] = {}
    for s in duration:
        labels = s.get("metric", {})
        v = s.get("value")
        rid = labels.get("registry") or "_"
        try:
            val = float(v[1])
            if rid not in duration_by_registry or val > duration_by_registry[rid]:
                duration_by_registry[rid] = val
        except (TypeError, ValueError, IndexError):
            pass
    errors_by_registry: Dict[str, float] = {}
    errors_by_reason: Dict[str, float] = {}
    for s in errs:
        labels = s.get("metric", {})
        v = s.get("value")
        try:
            val = float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        rid = labels.get("registry") or "_"
        rsn = labels.get("reason") or "_"
        errors_by_registry[rid] = errors_by_registry.get(rid, 0.0) + val
        errors_by_reason[rsn] = errors_by_reason.get(rsn, 0.0) + val

    # Per-peer attempts grouped by registry+peer+outcome.
    peer_attempt_grouped = _grouped_by(attempts, ("registry", "peer", "outcome"))

    # Aggregate per peer across registries (operators care about "is peer X
    # being synced successfully" more than "is peer X being synced by registry-a").
    per_peer_attempt: Dict[str, Dict[str, int]] = {}
    for (rid, peer, outcome), v in peer_attempt_grouped.items():
        if not peer or peer == "_":
            continue
        slot = per_peer_attempt.setdefault(peer, {"success": 0, "error": 0, "skipped": 0})
        if outcome in slot:
            slot[outcome] += int(v)
        else:
            slot[outcome] = int(v)

    registries = (
        set(cycles_by_registry) | set(last_success_by_registry)
        | set(duration_by_registry) | set(errors_by_registry)
    )
    registries = {r for r in registries if r and r != "_"}

    now_ts = time.time()
    per_registry: List[Dict[str, Any]] = []
    for rid in sorted(registries):
        last_ts = last_success_by_registry.get(rid)
        seconds_since = (now_ts - last_ts) if last_ts else None
        per_registry.append({
            "registry_id": rid,
            "cycles_24h": int(cycles_by_registry.get(rid, 0)),
            "errors_24h": int(errors_by_registry.get(rid, 0)),
            "last_success_iso": (
                datetime.datetime.fromtimestamp(last_ts, datetime.timezone.utc).isoformat()
                if last_ts else None
            ),
            "seconds_since_success": int(seconds_since) if seconds_since is not None else None,
            "last_duration_ms": int(duration_by_registry.get(rid, 0)),
        })

    # Per-peer rollup from peer_registries DB (joined with attempt counts).
    interval = get_sync_interval()
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    # Pull peers WITH parent name (LEFT JOIN to self) — gives the modal
    # "chain via op-berlin" context for non-direct peers.
    Parent = aliased(models.PeerRegistry)
    peers_q = await db.execute(
        select(models.PeerRegistry, Parent.name.label("parent_name"))
        .outerjoin(Parent, Parent.id == models.PeerRegistry.parent_registry_id)
        .order_by(models.PeerRegistry.name)
    )
    peers_rows = peers_q.all()

    # §pass30: query agent_cards.updated_at grouped by source_registry — this
    # is the CANONICAL freshness signal. Chain children's last_synced_at is
    # frozen by design; their cards still flow through the BFS mesh.
    cards_by_source: Dict[str, datetime.datetime] = {}
    card_counts_by_source: Dict[str, int] = {}
    try:
        card_rows = await db.execute(text("""
            SELECT
                card_data->'federation_metadata'->>'source_registry' AS source_registry,
                MAX(updated_at) AS max_updated,
                COUNT(*) AS card_count
            FROM agent_cards
            WHERE is_active = TRUE
              AND card_data->'federation_metadata'->>'source_registry' IS NOT NULL
            GROUP BY source_registry
        """))
        for src, max_upd, cnt in card_rows:
            if src:
                cards_by_source[src] = max_upd
                card_counts_by_source[src] = int(cnt or 0)
    except Exception as e:
        logger.debug(f"[FedSyncAdmin] card-freshness rollup failed: {e}")

    per_peer: List[Dict[str, Any]] = []
    stale_count = 0
    for p, parent_name in peers_rows:
        peer_name = p.name or "(unnamed)"
        attempts_for_peer = per_peer_attempt.get(peer_name, {"success": 0, "error": 0, "skipped": 0})

        # Direct-sync freshness (only meaningful for direct peers).
        secs_since_sync = None
        if p.last_synced_at:
            secs_since_sync = (now_dt - p.last_synced_at).total_seconds()

        # Card-flow freshness (the canonical signal). Find the most-recent
        # agent_cards.updated_at across any source_registry that contains
        # this peer's name as a slug.
        max_card_updated: Optional[datetime.datetime] = None
        matched_card_count = 0
        for src, max_upd in cards_by_source.items():
            if _name_matches_source(peer_name, src):
                if max_card_updated is None or max_upd > max_card_updated:
                    max_card_updated = max_upd
                matched_card_count += card_counts_by_source.get(src, 0)
        secs_since_card = None
        if max_card_updated is not None:
            # max_card_updated is timezone-aware from PG TIMESTAMPTZ.
            secs_since_card = (now_dt - max_card_updated).total_seconds()

        # Composite freshness: the BETTER of the two signals.
        secs_effective: Optional[float] = None
        if secs_since_sync is not None and secs_since_card is not None:
            secs_effective = min(secs_since_sync, secs_since_card)
        elif secs_since_sync is not None:
            secs_effective = secs_since_sync
        elif secs_since_card is not None:
            secs_effective = secs_since_card
        freshness = _staleness_class(secs_effective, interval)

        is_chain_child = p.parent_registry_id is not None
        is_active = (p.status or "").upper() == "ACTIVE"
        if freshness in ("stale", "very_stale", "never") and is_active:
            stale_count += 1

        per_peer.append({
            "id": p.id,
            "name": peer_name,
            "base_url": p.base_url,
            "status": p.status,
            "peer_type": p.peer_type,
            "parent_registry_id": p.parent_registry_id,
            "parent_name": parent_name,
            "is_chain_child": is_chain_child,
            # Direct-sync metric (frozen for chain children — informational only)
            "last_synced_iso": p.last_synced_at.isoformat() if p.last_synced_at else None,
            "seconds_since_sync": int(secs_since_sync) if secs_since_sync is not None else None,
            # Card-flow metric — the canonical freshness signal post-§pass30
            "last_card_received_iso": max_card_updated.isoformat() if max_card_updated else None,
            "seconds_since_card": int(secs_since_card) if secs_since_card is not None else None,
            "card_count": matched_card_count,
            # Composite — driven by whichever metric is fresher
            "freshness": freshness,
            "health_check_failure_count": p.health_check_failure_count or 0,
            "last_health_check_attempt_iso": (
                p.last_health_check_attempt_at.isoformat()
                if p.last_health_check_attempt_at else None
            ),
            "attempts_24h": attempts_for_peer,
        })

    return {
        "summary": {
            "cycles_24h": int(sum(cycles_by_registry.values())),
            "errors_24h": int(sum(errors_by_registry.values())),
            "registries_reporting": len(per_registry),
            "active_peers": sum(1 for (p, _pn) in peers_rows if (p.status or "").upper() == "ACTIVE"),
            "total_peers": len(peers_rows),
            "stale_active_peers": stale_count,
            "interval_sec": interval,
        },
        "errors_by_reason": {k: int(v) for k, v in errors_by_reason.items()},
        "per_registry": per_registry,
        "per_peer": per_peer,
        "local_last_cycle": get_last_cycle_stats(),
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
    """Federation sync fleet snapshot — 5s cached."""
    now = time.monotonic()
    cached = _STATUS_CACHE.get("data")
    if cached is not None and (now - _STATUS_CACHE.get("ts", 0.0)) < _STATUS_CACHE_TTL_SEC:
        return cached
    data = await _build_status(db)
    _STATUS_CACHE["data"] = data
    _STATUS_CACHE["ts"] = now
    return data


@router.get("/peers")
async def peers_endpoint(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by peer status"),
    stale_only: bool = Query(False, description="Return only stale/never-synced active peers"),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Per-peer detail feed with optional filters."""
    data = await _build_status(db)
    peers = data["per_peer"]
    if status_filter:
        peers = [p for p in peers if (p["status"] or "").upper() == status_filter.upper()]
    if stale_only:
        peers = [
            p for p in peers
            if p["freshness"] in ("stale", "very_stale", "never")
            and (p["status"] or "").upper() == "ACTIVE"
        ]
    return {
        "peers": peers,
        "total_returned": len(peers),
        "filters_applied": {"status": status_filter, "stale_only": stale_only},
    }
