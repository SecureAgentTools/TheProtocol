"""Admin API for the agent_card_pullsync worker (§pass36 Option C Phase 3).

Endpoints under `/api/v1/admin/agent-card-pullsync/*`, all admin_platform-gated.

  GET /admin/agent-card-pullsync/status   — cycle snapshot + per-agent last
                                            pull state + Prom 24h rollup
  GET /admin/agent-card-pullsync/events   — paginated AgentCardPulled stream
                                            from EventStore (drift audit)
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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db
from ..es_ssl_helper import get_httpx_verify
from ..background_tasks import agent_card_pullsync as pullsync_module

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/agent-card-pullsync",
    tags=["Admin — Agent Card Pull-Sync"],
)

PROMETHEUS_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)
EVENT_STORE_URL = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
# EventStore expects `X-Internal-Key` (per saga_timeout_admin precedent — verified
# 2026-05-17 audit). NOT `X-API-Key` or `Authorization: Bearer`.
EVENT_STORE_INTERNAL_KEY = (
    os.environ.get("EVENT_STORE_INTERNAL_KEY")
    or os.environ.get("EVENT_STORE_API_KEY")
    or ""
)

_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL_SEC = 5.0


# ─── Prometheus helpers ──────────────────────────────────────────────────────


async def _prom_instant(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
    try:
        r = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=4.0,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("status") != "success":
            return []
        return data.get("data", {}).get("result", []) or []
    except Exception as e:
        logger.debug(f"[AgentCardPullSyncAdmin] prom query failed: {e}")
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


def _sum_total(result: List[Dict[str, Any]]) -> float:
    out = 0.0
    for s in result:
        v = s.get("value")
        try:
            out += float(v[1])
        except (TypeError, ValueError, IndexError):
            continue
    return out


# ─── EventStore helpers ──────────────────────────────────────────────────────


async def _es_fetch_events(
    client: httpx.AsyncClient,
    event_type: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """Pull recent events of a given type from EventStore.

    Uses the canonical `GET /events/` endpoint per saga_timeout_admin
    precedent — verified 2026-05-17 audit. `/events/export` requires
    `since_seq`/`since` parameters which we don't have.
    """
    try:
        headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/events/",
            params={
                "event_type": event_type,
                "limit": min(int(limit), 1000),  # plan §12.4 — never exceed 1000
            },
            headers=headers,
            timeout=6.0,
        )
        if r.status_code != 200:
            logger.debug(f"[AgentCardPullSyncAdmin] ES /events/ {event_type}: {r.status_code}")
            return []
        body = r.json()
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and "events" in body:
            return body["events"]
        return []
    except Exception as e:
        logger.debug(f"[AgentCardPullSyncAdmin] ES fetch failed: {e}")
        return []


async def _es_fetch_events_for_agent(
    client: httpx.AsyncClient,
    agent_did: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """Pull recent AgentCardPulled events for ONE agent.

    `/events/aggregate/{did}` honors the DID filter; the generic `/events/`
    endpoint does not (verified 2026-05-17 audit).
    """
    try:
        from urllib.parse import quote
        headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/events/aggregate/{quote(agent_did, safe=':')}",
            params={"event_types": "AgentCardPulled"},
            headers=headers,
            timeout=6.0,
        )
        if r.status_code != 200:
            return []
        body = r.json()
        events = body if isinstance(body, list) else body.get("events", [])
        # Return most-recent first (the endpoint returns ASC).
        return list(reversed(events))[: int(limit)]
    except Exception as e:
        logger.debug(f"[AgentCardPullSyncAdmin] ES per-agent fetch failed: {e}")
        return []


def _flatten_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    # EventStore wire shape uses `data` + `timestamp` (verified 2026-05-17
    # audit against working saga_timeout_admin). Fall back to alt names for
    # any future shape changes.
    data = raw.get("data") or raw.get("event_data") or {}
    return {
        "event_id": raw.get("event_id") or raw.get("id"),
        "event_type": raw.get("event_type"),
        "timestamp": (
            raw.get("timestamp")
            or raw.get("event_timestamp")
            or raw.get("created_at")
        ),
        "agent_did": data.get("agent_did") or raw.get("aggregate_id"),
        "registry_id": data.get("registry_id"),
        "drift": bool(data.get("drift")),
        "drifted_fields": data.get("drifted_fields") or [],
        "new_etag": data.get("new_etag"),
    }


# ─── Status builder ──────────────────────────────────────────────────────────


async def _build_status(db: AsyncSession) -> Dict[str, Any]:
    """Build the /status response shape.

    Combines:
      - Worker's in-process snapshot (last cycle stats)
      - Prom 24h rollups by outcome + per-field drift
      - DB rollup: total native agents w/ pull state buckets
    """
    snapshot = pullsync_module.get_snapshot()

    async with httpx.AsyncClient(timeout=6.0, verify=get_httpx_verify()) as client:
        # Prom 24h rollup
        pulls_24h, drift_24h, cycles_24h = await asyncio.gather(
            _prom_instant(
                client,
                f'sum by (outcome) (increase({sel("agent_card_pullsync_pulls_total")}[24h]))',
            ),
            _prom_instant(
                client,
                f'sum by (field) (increase({sel("agent_card_pullsync_drift_detected_total")}[24h]))',
            ),
            _prom_instant(
                client,
                f'sum by (registry_id) (increase({sel("agent_card_pullsync_cycle_total")}[24h]))',
            ),
        )

    pulls_24h_map = _sum_by(pulls_24h, "outcome")
    drift_24h_map = _sum_by(drift_24h, "field")
    cycles_24h_map = _sum_by(cycles_24h, "registry_id")

    # DB rollup: per native-card pull state.
    # Pull-sync only applies to native cards — same filter as worker.
    # We need: never_pulled / stale / fresh buckets.
    now = datetime.datetime.now(datetime.timezone.utc)
    interval_sec = (snapshot or {}).get("interval_sec") or 21600
    stale_cutoff = now - datetime.timedelta(seconds=interval_sec * 2)

    # Native cards: card_data->federation_metadata->source_registry IS NULL
    # (postgres JSONB).
    from sqlalchemy import text as _text

    native_filter = (
        "is_active = true AND agent_did IS NOT NULL "
        "AND (card_data->'federation_metadata'->>'source_registry') IS NULL"
    )

    # §FEDSYNCTRUTH (2026-09-03) — the buckets say WHY a card has no fresh pull: never asked,
    # unreachable by construction (internal host), asked and failed (in backoff), or asked and
    # fresh/stale. "never_pulled" alone hid the cursor defect for months.
    from ..background_tasks.agent_card_pullsync import (
        _CANDIDATE_URL_SQL_EXPR as _url_expr,
        _internal_url_sql_regex,
        _SCHEME_HOST_SQL_REGEX as _scheme_re,
    )
    counts_q = await db.execute(_text(f"""
        SELECT
          COUNT(*)                                                           AS total,
          COUNT(*) FILTER (WHERE last_pulled_at IS NULL)                      AS never_pulled,
          COUNT(*) FILTER (WHERE last_pulled_at < :stale_cutoff)              AS stale,
          COUNT(*) FILTER (WHERE last_pulled_at >= :stale_cutoff)             AS fresh,
          COUNT(*) FILTER (WHERE {_url_expr} !~* :scheme_re)                   AS no_interface_url,
          COUNT(*) FILTER (WHERE {_url_expr} ~* :scheme_re
                             AND {_url_expr} ~* :internal_re)                AS internal_host,
          COUNT(*) FILTER (WHERE last_pull_attempt_at IS NULL
                             AND {_url_expr} ~* :scheme_re
                             AND {_url_expr} !~* :internal_re)               AS never_attempted,
          COUNT(*) FILTER (WHERE last_pull_attempt_at IS NOT NULL
                             AND coalesce(pull_failures, 0) > 0)             AS attempted_failed
        FROM agent_cards
        WHERE {native_filter}
    """).bindparams(stale_cutoff=stale_cutoff, internal_re=_internal_url_sql_regex(), scheme_re=_scheme_re))
    db_row = counts_q.first()
    db_buckets = {
        "total_native_active": int(db_row.total or 0),
        "never_pulled": int(db_row.never_pulled or 0),
        "stale": int(db_row.stale or 0),
        "fresh": int(db_row.fresh or 0),
        "no_interface_url": int(db_row.no_interface_url or 0),
        "internal_host": int(db_row.internal_host or 0),
        "never_attempted": int(db_row.never_attempted or 0),
        "attempted_failed": int(db_row.attempted_failed or 0),
    }

    summary = {
        "cycles_24h": int(_sum_total(cycles_24h)),
        "pulls_200_24h": int(pulls_24h_map.get("200", 0)),
        "pulls_304_24h": int(pulls_24h_map.get("304", 0)),
        "pulls_4xx_24h": int(pulls_24h_map.get("4xx", 0)),
        "pulls_5xx_24h": int(pulls_24h_map.get("5xx", 0)),
        "pulls_timeout_24h": int(pulls_24h_map.get("timeout", 0)),
        "pulls_skipped_24h": int(pulls_24h_map.get("skipped", 0)),
        "drift_events_24h": int(sum(drift_24h_map.values())),
    }

    # Banner heuristic — surfaces issues:
    # - any 5xx/timeout in last 24h → warning
    # - any never_pulled with active is_active=true after N cycles → warning
    has_errors = (summary["pulls_5xx_24h"] + summary["pulls_timeout_24h"]) > 0
    banner = None
    if has_errors:
        banner = {
            "level": "warn",
            "msg": (
                f"pull-sync had {summary['pulls_5xx_24h']} 5xx + "
                f"{summary['pulls_timeout_24h']} timeout pulls in last 24h"
            ),
        }
    elif db_buckets["never_pulled"] > 0:
        banner = {
            "level": "info",
            "msg": f"{db_buckets['never_pulled']} native agents never pulled yet",
        }

    return {
        "worker_snapshot": snapshot,
        "summary": summary,
        "db_buckets": db_buckets,
        "drift_24h_by_field": drift_24h_map,
        "cycles_24h_by_registry": cycles_24h_map,
        "banner": banner,
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/status")
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Pull-sync worker status snapshot — 5s cached."""
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
    agent_did: Optional[str] = Query(None),
    drifted_field: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Recent `AgentCardPulled` audit events (drift trail).

    Uses the per-aggregate endpoint when `agent_did` is specified (EventStore's
    generic /events/ doesn't filter by aggregate_id — verified 2026-05-17).
    """
    per_type_limit = max(limit * 2, 50)
    async with httpx.AsyncClient(timeout=6.0, verify=get_httpx_verify()) as client:
        if agent_did:
            raw_list = await _es_fetch_events_for_agent(client, agent_did, per_type_limit)
        else:
            raw_list = await _es_fetch_events(client, "AgentCardPulled", per_type_limit)

    events = [_flatten_event(r) for r in raw_list]
    # agent_did filter already applied server-side via /events/aggregate; keep
    # client-side filter as a defensive net.
    if agent_did:
        events = [e for e in events if e.get("agent_did") == agent_did]
    if drifted_field:
        events = [
            e for e in events
            if drifted_field in {f.split(":", 1)[0] for f in (e.get("drifted_fields") or [])}
        ]
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    return {
        "events": events[:limit],
        "total_returned": min(len(events), limit),
        "filters_applied": {
            "agent_did": agent_did,
            "drifted_field": drifted_field,
            "limit": limit,
        },
    }
