"""Admin API for surveying + acting on agent-card drift (§pass36 Phase 6).

Endpoints under `/api/v1/admin/agent-card-drift/*`, all admin_platform-gated.

Drift = the agent's well-known card disagrees with the registry's stored
`card_data`. Phase 3's pull-sync worker auto-merges agent-owned fields (per
the ownership split in plan §3.1), so most drift is benign and already
reconciled. This admin surface lets operators:

  GET /admin/agent-card-drift           — list per-agent drift state w/ context
  GET /admin/agent-card-drift/{did}     — side-by-side diff (stored vs agent-served)
  POST /admin/agent-card-drift/{did}/refresh    — force one-shot pull (use after agent redeploys)
  POST /admin/agent-card-drift/{did}/force-register
        — record an operator-flagged drift event for follow-up (e.g.,
          "agent shipped a card we don't trust"). No state change to the card.

The pull/refresh action is the canonical "I want this drift accepted right
now" knob — pull-sync's merge contract already preserves registry-owned
fields, so a re-pull == accepting the agent's view.
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db
from ..event_emitter import get_event_emitter
from ..es_ssl_helper import get_httpx_verify
from ..background_tasks.agent_card_pullsync import (
    trigger_pull_for_did,
    _well_known_url_for,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/agent-card-drift",
    tags=["Admin — Agent Card Drift"],
)

EVENT_STORE_URL = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
# EventStore expects `X-Internal-Key` (per saga_timeout_admin precedent —
# verified 2026-05-17 audit). NOT `X-API-Key` or `Authorization: Bearer`.
EVENT_STORE_INTERNAL_KEY = (
    os.environ.get("EVENT_STORE_INTERNAL_KEY")
    or os.environ.get("EVENT_STORE_API_KEY")
    or ""
)


# ─── EventStore helper ──────────────────────────────────────────────────────


async def _last_drift_event(client: httpx.AsyncClient, agent_did: str) -> Optional[Dict[str, Any]]:
    """Fetch the most-recent AgentCardPulled event for a DID (or None).

    Uses `GET /events/aggregate/{did}` which DOES filter by aggregate_id —
    the generic `/events/` endpoint silently ignores the parameter (verified
    2026-05-17 audit). Returns the latest matching event (sorted desc).
    """
    try:
        headers = {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
        # URL-encode the DID — colons in did:theprotocol:... are fine but be safe.
        from urllib.parse import quote
        r = await client.get(
            f"{EVENT_STORE_URL}/api/v1/events/aggregate/{quote(agent_did, safe=':')}",
            params={"event_types": "AgentCardPulled"},
            headers=headers,
            timeout=4.0,
        )
        if r.status_code != 200:
            return None
        body = r.json()
        events = body if isinstance(body, list) else body.get("events", [])
        if not events:
            return None
        # Endpoint returns ASC by default — grab the last (most recent).
        e = events[-1]
        data = e.get("data") or e.get("event_data") or {}
        return {
            "timestamp": e.get("timestamp") or e.get("event_timestamp") or e.get("created_at"),
            "drifted_fields": data.get("drifted_fields") or [],
        }
    except Exception:
        return None


# ─── Helpers ────────────────────────────────────────────────────────────────


def _native_filter_clause() -> str:
    """SQL fragment matching native cards (no federation source registry)."""
    return "(card_data->'federation_metadata'->>'source_registry') IS NULL"


async def _list_native_with_pull_state(
    db: AsyncSession,
    limit: int,
    offset: int,
) -> List[Dict[str, Any]]:
    """Pull native-card rows w/ last-pull state for the drift view."""
    from sqlalchemy import text as _text

    sql = _text(f"""
        SELECT id, agent_did, name, last_pulled_at, last_pulled_etag,
               card_data->'supportedInterfaces'->0->>'url' AS iface_url
        FROM agent_cards
        WHERE is_active = true
          AND agent_did IS NOT NULL
          AND {_native_filter_clause()}
        ORDER BY last_pulled_at ASC NULLS FIRST, id
        LIMIT :limit OFFSET :offset
    """).bindparams(limit=limit, offset=offset)
    res = await db.execute(sql)
    rows = []
    for r in res:
        rows.append({
            "id": str(r.id),
            "agent_did": r.agent_did,
            "name": r.name,
            "last_pulled_at": r.last_pulled_at.isoformat() if r.last_pulled_at else None,
            "last_pulled_etag": r.last_pulled_etag,
            "iface_url": r.iface_url,
        })
    return rows


def _diff_keys(stored: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight diff: returns {changed: {key: {stored, fresh}}, removed: [...], added: [...]}.

    Registry-owned keys are intentionally not diffed — they're preserved by
    the pull-sync merge contract.
    """
    REGISTRY_OWNED = {"federation_metadata", "flare", "last_pulled_at", "last_pulled_etag"}
    keys = set(stored.keys()) | set(fresh.keys())
    keys -= REGISTRY_OWNED

    changed: Dict[str, Any] = {}
    removed: List[str] = []
    added: List[str] = []
    for k in sorted(keys):
        in_stored = k in stored
        in_fresh = k in fresh
        if in_stored and in_fresh:
            if stored[k] != fresh[k]:
                changed[k] = {"stored": stored[k], "fresh": fresh[k]}
        elif in_stored and not in_fresh:
            removed.append(k)
        elif in_fresh and not in_stored:
            added.append(k)
    return {
        "changed": changed,
        "removed": removed,
        "added": added,
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("")
async def list_drift_state(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """List native agents with pull-sync state for the drift dashboard."""
    rows = await _list_native_with_pull_state(db, limit, offset)

    # Enrich with EventStore-reported last-drift fields where available.
    async with httpx.AsyncClient(timeout=4.0, verify=get_httpx_verify()) as client:
        for row in rows:
            ev = await _last_drift_event(client, row["agent_did"])
            row["last_drift_event"] = ev
    return {"items": rows, "limit": limit, "offset": offset, "count": len(rows)}


@router.get("/{did:path}")
async def get_drift_diff(
    did: str = Path(..., description="Agent DID"),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Side-by-side diff for one agent: stored card_data vs the agent's live well-known.

    Fetches the well-known live (not cached) so the diff is current. If the
    agent is unreachable, returns the stored card + an `unreachable_reason`.
    """
    res = await db.execute(
        select(models.AgentCard).where(models.AgentCard.agent_did == did)
    )
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No card for agent {did}",
        )
    stored = row.card_data if isinstance(row.card_data, dict) else {}
    well_known = _well_known_url_for(stored)

    fresh: Optional[Dict[str, Any]] = None
    unreachable_reason: Optional[str] = None
    http_code: Optional[int] = None
    if not well_known:
        unreachable_reason = "non-public hostname (skipped by pull-sync)"
    else:
        try:
            async with httpx.AsyncClient(timeout=6.0, verify=True, follow_redirects=True) as client:
                resp = await client.get(well_known)
                http_code = resp.status_code
                if resp.status_code == 200:
                    body = resp.json()
                    if isinstance(body, dict):
                        fresh = body
                    else:
                        unreachable_reason = "well-known returned non-object body"
                else:
                    unreachable_reason = f"HTTP {resp.status_code}"
        except Exception as e:  # noqa: BLE001
            unreachable_reason = f"fetch error: {e.__class__.__name__}"

    diff = _diff_keys(stored, fresh or {})
    return {
        "agent_did": did,
        "name": row.name,
        "stored": stored,
        "fresh": fresh,
        "well_known_url": well_known,
        "http_code": http_code,
        "unreachable_reason": unreachable_reason,
        "diff": diff,
        "last_pulled_at": row.last_pulled_at.isoformat() if row.last_pulled_at else None,
        "last_pulled_etag": row.last_pulled_etag,
    }


@router.post("/{did:path}/refresh")
async def refresh_drift(
    did: str = Path(..., description="Agent DID"),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Force a one-shot pull-sync for this agent (bypasses the 6h scheduler).

    The merge contract (preserve registry-owned fields, overwrite agent-owned
    fields) is the same as the scheduled worker. Operators use this after an
    agent operator deploys updates to their well-known card and wants the
    registry to converge immediately.
    """
    res = await db.execute(
        select(models.AgentCard).where(models.AgentCard.agent_did == did)
    )
    if not res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No card for agent {did}",
        )
    outcome = await trigger_pull_for_did(did)
    return {"agent_did": did, "outcome": outcome}


@router.post("/{did:path}/force-register")
async def force_register_drift(
    did: str = Path(..., description="Agent DID"),
    note: Dict[str, Any] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Depends(
        security.require_admin_flag("admin_platform")
    ),
):
    """Record an operator-flagged drift event for follow-up.

    The registry can NOT push card changes to the agent (agents own their card
    per A2A v1.0 §4.1.2). This endpoint just emits a `CommanderFlaggedDrift`
    audit event so the operator's intent is logged for review. Use case:
    "agent shipped a card with values we won't allow" — Commander follows up
    out-of-band, this endpoint records the moment of flagging.
    """
    res = await db.execute(
        select(models.AgentCard).where(models.AgentCard.agent_did == did)
    )
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No card for agent {did}",
        )

    try:
        emitter = get_event_emitter()
        if emitter is not None:
            await emitter.emit(
                event_type="CommanderFlaggedDrift",
                aggregate_id=did,
                aggregate_type="AgentCard",
                data={
                    "agent_did": did,
                    "developer_id_who_flagged": current_admin.id,
                    "developer_email_who_flagged": current_admin.email,
                    "note": (note or {}).get("note") if isinstance(note, dict) else None,
                    "flagged_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[DriftAdmin] failed to emit CommanderFlaggedDrift: {e}")

    return {
        "agent_did": did,
        "flagged": True,
        "by": current_admin.email,
    }
