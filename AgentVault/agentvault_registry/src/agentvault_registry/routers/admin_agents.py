"""
Admin Agent Management Router (M2, 2026-04-20)

Admin-facing endpoints for managing agent accounts.  Distinct from
enforcement_admin.py — this is for ownership, identity, and lifecycle hygiene;
enforcement_admin.py remains the canonical interface for discipline (suspend
via offense, slash stake, etc.).

Endpoints (gate on granular admin flags via require_admin_flag):
  list/detail/orphans/rotate-credentials → admin_support
  transfer-ownership/force-mtls/hard-delete → admin_platform
  bulk/suspend → admin_enforcement
Legacy is_admin=True passes every check via super-flag fallback.

Routes:
  GET    /api/v1/admin/agents                        — list with filters
  GET    /api/v1/admin/agents/orphans                 — agents whose creator is deleted
  GET    /api/v1/admin/agents/{did}                   — full detail
  POST   /api/v1/admin/agents/{did}/transfer-ownership — reassign creator_developer
  POST   /api/v1/admin/agents/{did}/rotate-credentials — new client_secret (shown once)
  POST   /api/v1/admin/agents/{did}/force-mtls-enrol   — admin IRONHAND enrolment
  DELETE /api/v1/admin/agents/{did}                    — hard delete (final audit)
  POST   /api/v1/admin/agents/bulk/suspend             — loop-based bulk suspend

All mutations emit audit events to EventStore.
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Path, status, Security
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, schemas, security
from agentvault_registry.database import get_db
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.services.coordinated_suspension import (
    coordinated_agent_suspend,
    coordinated_agent_reinstate,
)
from agentvault_registry.es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/agents",
    tags=["Admin — Agent Management"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_agent(db: AsyncSession, agent_did: str) -> models.Agent:
    stmt = select(models.Agent).where(models.Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_did} not found",
        )
    return agent


async def _load_agent_card_name(db: AsyncSession, agent_did: str) -> Optional[str]:
    """Best-effort agent name lookup from agent_cards (latest active)."""
    try:
        result = await db.execute(
            select(models.AgentCard.name)
            .where(models.AgentCard.agent_did == agent_did, models.AgentCard.is_active.is_(True))
            .order_by(models.AgentCard.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    except Exception:
        return None


async def _bulk_agent_names(db: AsyncSession, dids: List[str]) -> Dict[str, str]:
    """Bulk name lookup for a list of DIDs. Skips missing cards."""
    if not dids:
        return {}
    try:
        result = await db.execute(
            select(models.AgentCard.agent_did, models.AgentCard.name)
            .where(models.AgentCard.agent_did.in_(dids), models.AgentCard.is_active.is_(True))
        )
        names: Dict[str, str] = {}
        for did, name in result.all():
            if did not in names and name:
                names[did] = name
        return names
    except Exception:
        return {}


async def _emit_admin_action(
    *,
    event_type: str,
    agent_did: str,
    actor: models.Developer,
    data: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,  # §BATCH7: value-touching admin actions carry a deterministic key
) -> None:
    """Emit audit event to EventStore. Never raises."""
    try:
        emitter = get_event_emitter()
        payload = {
            "actor_developer_id": actor.id,
            "actor_email": actor.email,
            "target_agent_did": agent_did,
        }
        if data:
            payload.update(data)
        await emitter.emit(
            event_type=event_type,
            aggregate_id=f"agent:{agent_did}",
            aggregate_type="Agent",
            data=payload,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"[AdminAgents] Failed to emit {event_type}: {e}", exc_info=True)


def _to_admin_read(
    agent: models.Agent,
    *,
    name: Optional[str] = None,
    creator_email: Optional[str] = None,
    creator_deleted: bool = False,
    # §pass37 (2026-05-18) — Option C signal cell fields. All optional so
    # callers that don't have the data (e.g. orphans endpoint) get sane null
    # defaults and the existing serialisation path keeps working.
    last_pulled_at: Optional[datetime] = None,
    last_pulled_etag: Optional[str] = None,
    current_signing_kid: Optional[str] = None,
    drift_count_24h: int = 0,
) -> schemas.AgentAdminRead:
    return schemas.AgentAdminRead(
        did=agent.did,
        name=name,
        client_id=agent.client_id,
        status=agent.status,
        enforcement_status=getattr(agent, "enforcement_status", "active"),
        enforcement_level=int(getattr(agent, "enforcement_level", 0)),
        offense_count=int(getattr(agent, "offense_count", 0)),
        creator_developer_id=agent.creator_developer_id,
        creator_developer_email=creator_email,
        creator_developer_deleted=creator_deleted,
        organization_id=getattr(agent, "organization_id", None),
        team_id=getattr(agent, "team_id", None),
        reputation_score=int(getattr(agent, "reputation_score", 0)),
        liquid_balance=float(agent.liquid_balance or 0),
        staked_balance=float(agent.staked_balance or 0),
        staking_tier=getattr(agent, "staking_tier", None),
        auto_compound_enabled=bool(getattr(agent, "auto_compound_enabled", False)),
        mtls_enabled=bool(getattr(agent, "mtls_enabled", False)),
        spiffe_id=getattr(agent, "spiffe_id", None),
        created_at=agent.created_at,
        last_active_at=agent.last_active_at,
        last_pulled_at=last_pulled_at,
        last_pulled_etag=last_pulled_etag,
        current_signing_kid=current_signing_kid,
        drift_count_24h=drift_count_24h,
    )


# §pass37 (2026-05-18) — Bulk-load Option C signal data for a page of agents.
#
# Three cheap LEFT-JOINed lookups:
#   1. agent_cards.last_pulled_at / last_pulled_etag    — Phase 3 pull-sync state
#   2. agent_signing_keys.max(rotation_seq) per did      — Phase 9.a current key
#   3. count(*) FILTER drift events from local audit     — see note below
#
# For the 24h drift count we COULD hit EventStore /events/aggregate per DID,
# but that's N round-trips per page. Instead we read the local audit ring
# buffer maintained by the pull-sync worker (in-memory) AS WELL AS a single
# group-by query against the registry's local copy of AgentCardPulled emits.
# In practice the worker emits via Kafka → EventStore; the registry doesn't
# keep a local table. So we go with a SINGLE EventStore call (no aggregate
# filter) and bucket in Python — that's one round trip per /admin/agents
# page load. Bounded at 200 most-recent events per request.
async def _signal_data_for_agents(
    db: AsyncSession,
    dids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Returns {did: {last_pulled_at, last_pulled_etag, current_signing_kid, drift_count_24h}}.
    Missing keys default to (None/0). Single DB round-trip per signal source.
    """
    if not dids:
        return {}

    out: Dict[str, Dict[str, Any]] = {d: {} for d in dids}

    # 1. agent_cards.last_pulled_at + last_pulled_etag (LEFT JOIN equivalent)
    try:
        card_q = await db.execute(
            select(
                models.AgentCard.agent_did,
                models.AgentCard.last_pulled_at,
                models.AgentCard.last_pulled_etag,
            ).where(models.AgentCard.agent_did.in_(dids))
        )
        for row in card_q:
            d = row[0]
            if d in out:
                out[d]["last_pulled_at"] = row[1]
                out[d]["last_pulled_etag"] = row[2]
    except Exception as e:
        logger.debug(f"[AdminAgents.signals] agent_cards lookup failed: {e}")

    # 2. agent_signing_keys.max(rotation_seq) per did → kid
    try:
        from sqlalchemy import func as _func
        sk_q = await db.execute(
            select(
                models.AgentSigningKey.agent_did,
                _func.max(models.AgentSigningKey.rotation_seq).label("max_seq"),
            )
            .where(models.AgentSigningKey.agent_did.in_(dids))
            .group_by(models.AgentSigningKey.agent_did)
        )
        for row in sk_q:
            d, max_seq = row[0], row[1]
            if d in out and max_seq is not None:
                out[d]["current_signing_kid"] = f"{d}#{int(max_seq)}"
    except Exception as e:
        logger.debug(f"[AdminAgents.signals] signing_keys lookup failed: {e}")

    # 3. drift_count_24h via EventStore single call (most-recent N events of
    #    AgentCardPulled, bucket by aggregate_id in Python). Bounded.
    try:
        import os as _os
        import httpx as _httpx
        EVENT_STORE_URL = _os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
        EVENT_STORE_INTERNAL_KEY = (
            _os.environ.get("EVENT_STORE_INTERNAL_KEY")
            or _os.environ.get("EVENT_STORE_API_KEY")
            or ""
        )
        headers = (
            {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY}
            if EVENT_STORE_INTERNAL_KEY else {}
        )
        async with _httpx.AsyncClient(timeout=4.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{EVENT_STORE_URL}/api/v1/events/",
                params={"event_type": "AgentCardPulled", "limit": 1000},
                headers=headers,
            )
            if r.status_code == 200:
                body = r.json()
                events = body if isinstance(body, list) else body.get("events", [])
                from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                cutoff = _dt.now(_tz.utc) - _td(hours=24)
                for ev in events:
                    ts_raw = ev.get("timestamp") or ev.get("event_timestamp")
                    if not ts_raw:
                        continue
                    try:
                        ts = _dt.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=_tz.utc)
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    agg = ev.get("aggregate_id") or (ev.get("data") or {}).get("agent_did")
                    if agg and agg in out:
                        out[agg]["drift_count_24h"] = out[agg].get("drift_count_24h", 0) + 1
    except Exception as e:
        logger.debug(f"[AdminAgents.signals] EventStore drift count failed: {e}")

    return out


# ---------------------------------------------------------------------------
# GET / — list
# ---------------------------------------------------------------------------

@router.get("", response_model=schemas.AgentAdminListResponse, summary="List agents")
async def list_agents(
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        pattern=r"^(all|active|suspended|revoked|pending)$",
    ),
    enforcement_status: Optional[str] = Query(
        None, pattern=r"^(active|suspended|revoked)$"
    ),
    creator_developer_id: Optional[int] = Query(None, ge=1),
    organization_id: Optional[str] = Query(None),
    has_mtls: Optional[bool] = Query(None),
    # §pass37 (2026-05-18) — Option C signal filters.
    never_pulled: Optional[bool] = Query(
        None,
        description="When true, filter to native cards never pulled by agent_card_pullsync.",
    ),
    has_drift: Optional[bool] = Query(
        None,
        description="When true, filter to agents with at least one AgentCardPulled event in last 24h.",
    ),
    search: Optional[str] = Query(None, max_length=200, description="DID fragment, client_id, or agent-card name"),
    sort_by: str = Query("created_at", pattern=r"^(created_at|last_active_at|reputation_score|liquid_balance)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.AgentAdminListResponse:
    base = select(models.Agent)
    count_base = select(func.count(models.Agent.id))

    conditions = []
    if status_filter and status_filter != "all":
        conditions.append(models.Agent.status == status_filter)
    if enforcement_status:
        conditions.append(models.Agent.enforcement_status == enforcement_status)
    if creator_developer_id is not None:
        conditions.append(models.Agent.creator_developer_id == creator_developer_id)
    if organization_id:
        conditions.append(models.Agent.organization_id == organization_id)
    if has_mtls is True:
        conditions.append(models.Agent.mtls_enabled.is_(True))
    elif has_mtls is False:
        conditions.append(models.Agent.mtls_enabled.is_(False))
    if search:
        like = f"%{search.lower()}%"
        conditions.append(
            or_(
                func.lower(models.Agent.did).like(like),
                func.lower(models.Agent.client_id).like(like),
                # P7 (GCC agent finder): display names live on agent_cards, not agents.
                models.Agent.did.in_(
                    select(models.AgentCard.agent_did).where(
                        models.AgentCard.is_active.is_(True),
                        func.lower(models.AgentCard.name).like(like),
                    )
                ),
            )
        )

    if conditions:
        base = base.where(and_(*conditions))
        count_base = count_base.where(and_(*conditions))

    total_result = await db.execute(count_base)
    total = int(total_result.scalar() or 0)

    sort_col = {
        "created_at": models.Agent.created_at,
        "last_active_at": models.Agent.last_active_at,
        "reputation_score": models.Agent.reputation_score,
        "liquid_balance": models.Agent.liquid_balance,
    }[sort_by]

    list_result = await db.execute(
        base.order_by(sort_col.desc()).limit(limit).offset(offset)
    )
    agents = list_result.scalars().all()

    # Bulk-load creator emails + agent names
    creator_ids = list({a.creator_developer_id for a in agents if a.creator_developer_id is not None})
    creator_map: Dict[int, Dict[str, Any]] = {}
    if creator_ids:
        result = await db.execute(
            select(models.Developer.id, models.Developer.email, models.Developer.deleted_at)
            .where(models.Developer.id.in_(creator_ids))
        )
        for dev_id, email, deleted_at in result.all():
            creator_map[dev_id] = {"email": email, "deleted": deleted_at is not None}

    name_map = await _bulk_agent_names(db, [a.did for a in agents])

    # §pass37 (2026-05-18) — Option C signal data for the compound Signals
    # cell. Bulk-loaded for the page; missing entries default to null/0.
    signals = await _signal_data_for_agents(db, [a.did for a in agents])

    rows = [
        _to_admin_read(
            a,
            name=name_map.get(a.did),
            creator_email=(creator_map.get(a.creator_developer_id) or {}).get("email"),
            creator_deleted=(creator_map.get(a.creator_developer_id) or {}).get("deleted", False),
            last_pulled_at=(signals.get(a.did) or {}).get("last_pulled_at"),
            last_pulled_etag=(signals.get(a.did) or {}).get("last_pulled_etag"),
            current_signing_kid=(signals.get(a.did) or {}).get("current_signing_kid"),
            drift_count_24h=(signals.get(a.did) or {}).get("drift_count_24h", 0),
        )
        for a in agents
    ]

    # §pass37 — post-filter on Option C signal flags. Done here (Python) rather
    # than in SQL because (a) the drift count depends on EventStore data, and
    # (b) filtering by `last_pulled_at IS NULL` would require a LEFT JOIN that
    # changes the count(*) total. We accept that the `total` reflects the
    # pre-signal-filter count; that's why filters compose downstream from the
    # paginated page rather than the whole dataset.
    if never_pulled is True:
        rows = [r for r in rows if r.last_pulled_at is None]
    if has_drift is True:
        rows = [r for r in rows if r.drift_count_24h > 0]

    return schemas.AgentAdminListResponse(
        agents=rows,
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /orphans — must register BEFORE /{did} to avoid route-matching conflict
# ---------------------------------------------------------------------------

class OrphanedListingSweepIn(BaseModel):
    """§ORPHANLIST — a sweep is a WRITE, so it asks before it acts."""
    dry_run: bool = Field(
        True,
        description="TRUE (the default) counts and names what WOULD be unlisted and changes nothing.",
    )
    limit: int = Field(500, ge=1, le=5000, description="Safety ceiling for one pass.")


@router.post(
    "/orphaned-listings/sweep",
    summary="Unlist agent cards whose owner has been deleted",
    description=(
        "Agents whose creator developer is soft-deleted keep advertising work on behalf of an "
        "account that no longer exists, and NOBODY can take them down: the listing rail is "
        "owner-only by design, admins get no bypass, and `reinstate` refuses a deleted "
        "developer. That is a one-way door into a permanently listed card. Deletion itself now "
        "settles the listing (§ORPHANLIST); this sweep is for the cards orphaned BEFORE that "
        "shipped.\n\n"
        "Unlisting, not deactivating: the card stays fetchable by DID so a counterparty holding "
        "a past receipt can still read who they dealt with. `updated_at` is touched so the "
        "unlisting travels to peers as a §LISTPROP tombstone rather than dying on this node.\n\n"
        "Defaults to a DRY RUN."
    ),
)
async def sweep_orphaned_listings(
    body: OrphanedListingSweepIn,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    stmt = (
        select(models.AgentCard, models.Developer.deleted_at)
        .join(models.Developer, models.AgentCard.developer_id == models.Developer.id)
        .where(models.Developer.deleted_at.is_not(None))
        .where(models.AgentCard.unlisted.is_(False))
        .order_by(models.AgentCard.updated_at.asc())
        .limit(body.limit)
    )
    rows = (await db.execute(stmt)).all()
    named = [{"agent_did": c.agent_did, "name": c.name,
              "owner_deleted_at": d.isoformat() if d else None} for c, d in rows]

    if body.dry_run:
        return {"dry_run": True, "would_unlist": len(named), "cards": named[:50],
                "note": "nothing was changed; call again with dry_run=false to apply"}

    now = datetime.now(timezone.utc)
    for card, _ in rows:
        card.unlisted = True
        card.updated_at = now
    await db.commit()

    logger.warning(
        "[ORPHANLIST] admin %s unlisted %s orphaned agent card(s)", admin.id, len(named)
    )
    try:
        emitter = get_event_emitter()
        if emitter is not None:
            await emitter.emit(
                event_type="OrphanedListingsSwept",
                aggregate_id=f"registry:{admin.id}",
                aggregate_type="Registry",
                data={"count": len(named), "by_developer_id": admin.id,
                      "agent_dids": [n["agent_did"] for n in named][:200],
                      "swept_at": now.isoformat()},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ORPHANLIST] emit failed: %s", exc)

    return {"dry_run": False, "unlisted": len(named), "cards": named[:50]}


@router.get("/orphans", response_model=schemas.AgentAdminListResponse, summary="Orphaned agents")
async def list_orphan_agents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.AgentAdminListResponse:
    """
    Agents whose creator developer has been soft-deleted (developers.deleted_at IS NOT NULL).
    These agents are candidates for ownership transfer or bulk suspension.
    """
    joined = select(models.Agent, models.Developer.email).join(
        models.Developer, models.Agent.creator_developer_id == models.Developer.id
    ).where(models.Developer.deleted_at.is_not(None))

    count_stmt = select(func.count(models.Agent.id)).join(
        models.Developer, models.Agent.creator_developer_id == models.Developer.id
    ).where(models.Developer.deleted_at.is_not(None))

    total_result = await db.execute(count_stmt)
    total = int(total_result.scalar() or 0)

    result = await db.execute(
        joined.order_by(models.Agent.created_at.desc()).limit(limit).offset(offset)
    )
    rows = result.all()
    agents = [row[0] for row in rows]
    emails = {row[0].creator_developer_id: row[1] for row in rows}
    name_map = await _bulk_agent_names(db, [a.did for a in agents])

    return schemas.AgentAdminListResponse(
        agents=[
            _to_admin_read(
                a,
                name=name_map.get(a.did),
                creator_email=emails.get(a.creator_developer_id),
                creator_deleted=True,
            )
            for a in agents
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /{did} — full detail
# ---------------------------------------------------------------------------

@router.get("/{agent_did}", response_model=schemas.AgentAdminDetailRead, summary="Agent detail")
async def get_agent_detail(
    agent_did: str = Path(...),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.AgentAdminDetailRead:
    agent = await _load_agent(db, agent_did)

    name = await _load_agent_card_name(db, agent_did)

    creator_email: Optional[str] = None
    creator_deleted = False
    if agent.creator_developer_id:
        dev_result = await db.execute(
            select(models.Developer.email, models.Developer.deleted_at)
            .where(models.Developer.id == agent.creator_developer_id)
        )
        row = dev_result.first()
        if row:
            creator_email = row[0]
            creator_deleted = row[1] is not None

    # §pass34 (2026-05-17) — load the full agent_card row (including card_data)
    # so the admin drawer's Card Data + Federation tabs can render structured
    # views without an extra round-trip.
    card_row = (await db.execute(
        select(models.AgentCard).where(models.AgentCard.agent_did == agent_did)
    )).scalar_one_or_none()

    # Active staking positions
    stakes_result = await db.execute(
        select(models.Stake)
        .where(models.Stake.agent_did == agent_did)
        .order_by(models.Stake.staked_at.desc())
        .limit(50)
    )
    stakes = stakes_result.scalars().all()

    # Open dispute counts (status != CLOSED)
    open_as_c_result = await db.execute(
        select(func.count(models.Dispute.id))
        .where(models.Dispute.complainant_did == agent_did, models.Dispute.status != "CLOSED")
    )
    open_as_d_result = await db.execute(
        select(func.count(models.Dispute.id))
        .where(models.Dispute.defendant_did == agent_did, models.Dispute.status != "CLOSED")
    )

    # §pass37 (2026-05-18) — signal data + Option C drawer tabs
    signals = await _signal_data_for_agents(db, [agent_did])
    sig = signals.get(agent_did) or {}

    base = _to_admin_read(
        agent, name=name, creator_email=creator_email, creator_deleted=creator_deleted,
        last_pulled_at=sig.get("last_pulled_at"),
        last_pulled_etag=sig.get("last_pulled_etag"),
        current_signing_kid=sig.get("current_signing_kid"),
        drift_count_24h=sig.get("drift_count_24h", 0),
    )

    # signing-keys rotation history
    sk_rows = (await db.execute(
        select(models.AgentSigningKey)
        .where(models.AgentSigningKey.agent_did == agent_did)
        .order_by(models.AgentSigningKey.rotation_seq.asc())
    )).scalars().all()
    signing_keys = [
        schemas.AgentSigningKeyRead(
            rotation_seq=row.rotation_seq,
            kid=f"{agent_did}#{row.rotation_seq}",
            algorithm=row.algorithm or "EdDSA",
            public_jwk=row.public_jwk,
            created_at=row.created_at,
            expires_at=row.expires_at,
            is_current=row.expires_at is None,
        )
        for row in sk_rows
    ]

    # most-recent AgentCardPulled event for this DID (Option C Phase 6).
    last_drift_event: Optional[schemas.AgentLastDriftEvent] = None
    try:
        import os as _os
        import httpx as _httpx
        from urllib.parse import quote as _q
        EVENT_STORE_URL = _os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
        EVENT_STORE_INTERNAL_KEY = (
            _os.environ.get("EVENT_STORE_INTERNAL_KEY")
            or _os.environ.get("EVENT_STORE_API_KEY")
            or ""
        )
        headers = (
            {"X-Internal-Key": EVENT_STORE_INTERNAL_KEY} if EVENT_STORE_INTERNAL_KEY else {}
        )
        async with _httpx.AsyncClient(timeout=4.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{EVENT_STORE_URL}/api/v1/events/aggregate/{_q(agent_did, safe=':')}",
                params={"event_types": "AgentCardPulled"},
                headers=headers,
            )
            if r.status_code == 200:
                evs = r.json() or []
                if isinstance(evs, list) and evs:
                    # endpoint returns ASC — grab the last (most recent)
                    e = evs[-1]
                    data = e.get("data") or {}
                    last_drift_event = schemas.AgentLastDriftEvent(
                        timestamp=e.get("timestamp") or e.get("event_timestamp"),
                        drifted_fields=data.get("drifted_fields") or [],
                        new_etag=data.get("new_etag"),
                    )
    except Exception as e:
        logger.debug(f"[AdminAgents] last_drift_event lookup failed (non-fatal): {e}")

    return schemas.AgentAdminDetailRead(
        **base.model_dump(),
        public_key_jwk=agent.public_key_jwk,
        reputation_bond_amount=float(getattr(agent, "reputation_bond_amount", 0) or 0),
        reputation_bond_status=getattr(agent, "reputation_bond_status", "none"),
        rewards_paused_until=getattr(agent, "rewards_paused_until", None),
        total_rewards_earned=float(agent.total_rewards_earned) if agent.total_rewards_earned is not None else None,
        last_reward_distribution=getattr(agent, "last_reward_distribution", None),
        last_offense_at=getattr(agent, "last_offense_at", None),
        mtls_enrolled_at=getattr(agent, "mtls_enrolled_at", None),
        latitude=getattr(agent, "latitude", None),
        longitude=getattr(agent, "longitude", None),
        location_label=getattr(agent, "location_label", None),
        stakes=[
            schemas.AgentAdminStakePosition(
                id=str(s.id),
                amount=float(s.amount),
                staked_at=s.staked_at,
                unstaked_at=s.unstaked_at,
                is_active=bool(s.is_active),
            )
            for s in stakes
        ],
        open_disputes_as_complainant=int(open_as_c_result.scalar() or 0),
        open_disputes_as_defendant=int(open_as_d_result.scalar() or 0),
        # §pass34 (2026-05-17) — full card_data for the admin drawer's
        # Card Data + Federation tabs (no second round-trip).
        card_data=(card_row.card_data if card_row else None),
        card_id=(str(card_row.id) if card_row else None),
        card_created_at=(card_row.created_at if card_row else None),
        card_updated_at=(card_row.updated_at if card_row else None),
        card_is_active=(bool(card_row.is_active) if card_row else None),
        # §pass37 (2026-05-18) — Option C inline
        signing_keys=signing_keys,
        last_drift_event=last_drift_event,
    )


# ---------------------------------------------------------------------------
# POST /{did}/transfer-ownership
# ---------------------------------------------------------------------------

@router.post(
    "/{agent_did}/transfer-ownership",
    response_model=schemas.AgentAdminActionResponse,
    summary="Reassign agent to a new developer",
)
async def transfer_ownership(
    agent_did: str,
    body: schemas.AgentOwnershipTransferRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> schemas.AgentAdminActionResponse:
    agent = await _load_agent(db, agent_did)

    new_dev_result = await db.execute(
        select(models.Developer).where(models.Developer.id == body.new_creator_developer_id)
    )
    new_dev = new_dev_result.scalar_one_or_none()
    if new_dev is None:
        raise HTTPException(404, f"Target developer {body.new_creator_developer_id} not found")
    if new_dev.deleted_at is not None:
        raise HTTPException(400, "Cannot transfer to a deleted developer")
    if new_dev.is_suspended:
        raise HTTPException(400, "Cannot transfer to a suspended developer")

    old_dev_id = agent.creator_developer_id
    if old_dev_id == new_dev.id:
        raise HTTPException(400, "Agent is already owned by that developer")

    agent.creator_developer_id = new_dev.id
    # The card follows the agent (batch 7): without this the new owner cannot edit their own
    # agent's card — the card row keeps the OLD developer_id and every PUT 403s.
    from sqlalchemy import update as _update
    await db.execute(
        _update(models.AgentCard)
        .where(models.AgentCard.agent_did == agent_did)
        .values(developer_id=new_dev.id)
    )
    await db.commit()
    logger.warning(
        f"[AdminAgents] Agent {agent_did} OWNERSHIP transferred from developer {old_dev_id} "
        f"to {new_dev.id} by admin {admin.id}: {body.reason}"
    )
    await _emit_admin_action(
        event_type="AgentOwnershipTransferred",
        agent_did=agent_did,
        actor=admin,
        data={
            "old_creator_developer_id": old_dev_id,
            "new_creator_developer_id": new_dev.id,
            "new_creator_email": new_dev.email,
            "reason": body.reason,
        },
        idempotency_key=f"ownership-{agent_did}-{old_dev_id}-{new_dev.id}",  # §BATCH7
    )

    return schemas.AgentAdminActionResponse(
        did=agent_did,
        action="transfer_ownership",
        status="transferred",
        message=f"Agent {agent_did} reassigned from developer {old_dev_id} to {new_dev.id} ({new_dev.email})",
    )


# ---------------------------------------------------------------------------
# POST /{did}/rotate-credentials
# ---------------------------------------------------------------------------

@router.post(
    "/{agent_did}/rotate-credentials",
    response_model=schemas.AgentRotateCredentialsResponse,
    summary="Rotate agent client_secret (shown ONCE)",
)
async def rotate_credentials(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.AgentRotateCredentialsResponse:
    agent = await _load_agent(db, agent_did)

    if agent.status == "revoked":
        raise HTTPException(400, "Cannot rotate credentials for a revoked agent")

    new_secret = secrets.token_urlsafe(32)
    agent.hashed_client_secret = security.hash_password(new_secret)
    rotated_at = datetime.now(timezone.utc)

    await db.commit()
    logger.warning(
        f"[AdminAgents] Agent {agent_did} CREDENTIALS rotated by admin {admin.id}"
    )
    await _emit_admin_action(
        event_type="AgentCredentialsRotated",
        agent_did=agent_did,
        actor=admin,
        data={"rotated_at": rotated_at.isoformat()},
    )

    from agentvault_registry.core.public_url import credential_home_url  # §FEFRAME W1
    return schemas.AgentRotateCredentialsResponse(
        did=agent_did,
        client_id=agent.client_id,
        new_client_secret=new_secret,
        rotated_at=rotated_at,
        registry_url=credential_home_url(),
    )


# ---------------------------------------------------------------------------
# POST /{did}/force-mtls-enrol
# ---------------------------------------------------------------------------

@router.post(
    "/{agent_did}/force-mtls-enrol",
    response_model=schemas.AgentAdminActionResponse,
    summary="Admin-initiated IRONHAND mTLS enrolment",
)
async def force_mtls_enrol(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> schemas.AgentAdminActionResponse:
    agent = await _load_agent(db, agent_did)

    if agent.mtls_enabled:
        raise HTTPException(400, "Agent is already mTLS-enrolled")
    if agent.status != "active":
        raise HTTPException(400, f"Cannot enrol non-active agent (status={agent.status})")

    # Lazy import to avoid circulars — reuse the same helper agent_mtls.py calls
    try:
        from agentvault_registry.services.agent_spire import register_agent_spire_entry
    except Exception:
        raise HTTPException(500, "IRONHAND enrolment service unavailable")

    try:
        spiffe_id = register_agent_spire_entry(agent_did)
    except RuntimeError as e:
        logger.error(f"[AdminAgents] force-mtls-enrol SPIRE failed for {agent_did}: {e}")
        raise HTTPException(500, f"SPIRE registration failed: {str(e)[:200]}")
    except Exception as e:
        logger.error(f"[AdminAgents] force-mtls-enrol failed for {agent_did}: {e}", exc_info=True)
        raise HTTPException(500, f"Enrolment failed: {str(e)[:200]}")

    # Persist mTLS state on the agent (matches agent_mtls.py:enable-mtls pattern)
    agent.mtls_enabled = True
    agent.spiffe_id = spiffe_id
    agent.mtls_enrolled_at = datetime.now(timezone.utc)
    agent.mtls_revoked_at = None  # D6-802: an administrator's enrolment ends an administrator's revoke
    await db.commit()

    await _emit_admin_action(
        event_type="AgentMtlsEnrolled",
        agent_did=agent_did,
        actor=admin,
        data={"spiffe_id": spiffe_id, "initiated_by": "admin"},
    )

    return schemas.AgentAdminActionResponse(
        did=agent_did,
        action="force_mtls_enrol",
        status="enrolled",
        message=f"Agent {agent_did} enrolled for mTLS (SPIFFE ID: {spiffe_id or 'pending'})",
    )


# ---------------------------------------------------------------------------
# DELETE /{did} — hard delete (final)
# ---------------------------------------------------------------------------

@router.delete(
    "/{agent_did}",
    response_model=schemas.AgentAdminActionResponse,
    summary="Hard-delete agent (final audit event)",
)
async def hard_delete_agent(
    agent_did: str,
    body: schemas.AgentHardDeleteRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> schemas.AgentAdminActionResponse:
    agent = await _load_agent(db, agent_did)

    if body.confirm_did != agent_did:
        raise HTTPException(400, "confirm_did does not match target agent DID")

    # Guards: reject if any financial or legal state active
    liquid = float(agent.liquid_balance or 0)
    staked = float(agent.staked_balance or 0)
    if liquid > 0 or staked > 0:
        raise HTTPException(
            400,
            f"Cannot hard-delete agent with non-zero balance (liquid={liquid}, locked={staked}). "
            f"Transfer or burn the balance first."
        )

    active_stakes_result = await db.execute(
        select(func.count(models.Stake.id))
        .where(models.Stake.agent_did == agent_did, models.Stake.is_active.is_(True))
    )
    if int(active_stakes_result.scalar() or 0) > 0:
        raise HTTPException(400, "Cannot hard-delete agent with active lock positions")

    open_disputes_result = await db.execute(
        select(func.count(models.Dispute.id))
        .where(
            or_(models.Dispute.complainant_did == agent_did, models.Dispute.defendant_did == agent_did),
            models.Dispute.status != "CLOSED",
        )
    )
    if int(open_disputes_result.scalar() or 0) > 0:
        raise HTTPException(400, "Cannot hard-delete agent involved in open disputes")

    # Emit the final audit event BEFORE deleting — the row disappears and we need the trail.
    await _emit_admin_action(
        event_type="AgentHardDeleted",
        agent_did=agent_did,
        actor=admin,
        data={
            "reason": body.reason,
            "creator_developer_id": agent.creator_developer_id,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
        },
    )

    _creator_dev_id = agent.creator_developer_id
    # §MCPTEST30 V0637: the agent's cards go inactive with it, in the same transaction, as the owner's delete does
    # (developers.py, OWL24). A hard delete left them active and listed, each naming an agent that no longer exists
    # (seven on sbx-alpha, found by the MCP tester). Deactivated, never deleted: the federation feed carries an
    # inactive card to every mirror, where a deleted one would stay a ghost there.
    cards = (await db.execute(select(models.AgentCard).where(
        models.AgentCard.agent_did == agent_did, models.AgentCard.is_active.is_(True)))).scalars().all()
    for card in cards:
        card.is_active = False
    await db.delete(agent)
    await db.commit()
    logger.warning(
        f"[AdminAgents] Agent {agent_did} HARD-DELETED by admin {admin.id}: {body.reason} "
        f"({len(cards)} card(s) deactivated)"
    )

    # A1 (2026-07-24): agent.deleted webhook. The row is gone, so the DID can't be
    # resolved anymore — dispatch directly with the captured owner developer id.
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_event
    _aio.create_task(dispatch_webhook_event(
        "agent.deleted",
        {"agent_did": agent_did, "mode": "hard", "deleted_by": "admin", "reason": body.reason},
        source_label="admin_agents.hard_delete", developer_id=_creator_dev_id))

    return schemas.AgentAdminActionResponse(
        did=agent_did,
        action="hard_delete",
        status="deleted",
        message=(f"Agent {agent_did} permanently deleted, {len(cards)} card(s) deactivated. Final audit event "
                 f"AgentHardDeleted emitted to EventStore."),
    )


# ---------------------------------------------------------------------------
# POST /bulk/suspend
# ---------------------------------------------------------------------------

@router.post(
    "/bulk/suspend",
    response_model=schemas.AgentBulkSuspendResponse,
    summary="Bulk-suspend up to 50 agents (loop-based)",
)
async def bulk_suspend_agents(
    body: schemas.AgentBulkSuspendRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_enforcement")),
) -> schemas.AgentBulkSuspendResponse:
    """Phase 6: coordinated suspension. Each agent gets registry status flip
    + IRONHAND mTLS revoke + TEG account suspend, unless body.soft_suspend is
    True (registry only — escape hatch for soft cooldowns).

    Per-agent partial-failure is captured in `results[i].reason` so the admin
    sees exactly which lever fired. The bulk operation never aborts on a single
    agent failure — surface the full breakdown.
    """
    # §29 OPA I3 `bulk_blast_radius_ok` — LIVE CALL SITE. Python authorizes the ACTION
    # (admin_enforcement) but never the SCALE; bulk_suspend against 1,400 agents should not be one
    # click away from one JWT. Shadow-mode observes only (OPA can never grant, and under
    # OPA_ENFORCE=false it cannot block either), so this is Δ-irrelevant and cannot break the
    # endpoint — but it makes the scale visible and is ready to bite when enforce is ratcheted.
    try:
        from agentvault_registry import opa_shadow
        await opa_shadow.shadow_check(
            "agentvault/invariants/bulk_blast_radius_ok",
            {"is_admin": True, "target_count": len(body.agent_dids),
             "confirmed": bool(getattr(body, "confirmed", False))},
            True,
            label="bulk_suspend",
        )
    except Exception as exc:  # observability must never break an admin action
        logger.debug(f"[OPA] bulk blast-radius check skipped: {exc!r}")

    results: List[schemas.AgentBulkActionResult] = []
    succeeded = skipped = failed = 0
    soft = bool(getattr(body, "soft_suspend", False))
    # Aggregate counters for the response so admin sees lever-by-lever outcome
    mtls_revoked = teg_suspended = 0

    for did in body.agent_dids:
        try:
            stmt = select(models.Agent).where(models.Agent.did == did)
            result = await db.execute(stmt)
            agent = result.scalar_one_or_none()
            if agent is None:
                results.append(schemas.AgentBulkActionResult(did=did, status="failed", reason="not found"))
                failed += 1
                continue

            if agent.status == "suspended" or getattr(agent, "enforcement_status", None) == "suspended":
                results.append(schemas.AgentBulkActionResult(did=did, status="skipped", reason="already suspended"))
                skipped += 1
                continue

            csr = await coordinated_agent_suspend(
                db, agent, reason=body.reason, actor=admin, soft=soft,
            )
            if csr.mtls == "revoked":
                mtls_revoked += 1
            if csr.teg == "suspended":
                teg_suspended += 1

            # Build per-row reason from the coordinated result
            lever_summary = f"registry={csr.registry} mtls={csr.mtls} teg={csr.teg} cross_teg={csr.cross_teg}"
            if csr.error:
                lever_summary += f" err={csr.error.strip()}"
            results.append(schemas.AgentBulkActionResult(did=did, status="succeeded", reason=lever_summary))
            succeeded += 1

            await _emit_admin_action(
                event_type="AgentSuspended",
                agent_did=did,
                actor=admin,
                data={
                    "reason": body.reason,
                    "bulk": True,
                    "soft_suspend": soft,
                    "mtls": csr.mtls,
                    "teg": csr.teg,
                },
            )
        except Exception as e:
            logger.error(f"[AdminAgents] bulk_suspend failed for {did}: {e}")
            results.append(schemas.AgentBulkActionResult(did=did, status="failed", reason=str(e)[:200]))
            failed += 1

    # Commit once at the end — transaction semantics are per-row via in-memory mutation
    try:
        await db.commit()
    except Exception as e:
        logger.error(f"[AdminAgents] bulk_suspend commit failed: {e}")
        raise HTTPException(500, "Bulk suspend commit failed; no changes persisted")

    logger.warning(
        f"[AdminAgents] Bulk-suspend by admin {admin.id}: {succeeded}/{len(body.agent_dids)} succeeded "
        f"(mtls_revoked={mtls_revoked}, teg_suspended={teg_suspended}, soft={soft}), "
        f"{skipped} skipped, {failed} failed. Reason: {body.reason}"
    )

    return schemas.AgentBulkSuspendResponse(
        requested=len(body.agent_dids),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        results=results,
    )


# ---------------------------------------------------------------------------
# POST /bulk/reinstate (Phase 6)
# ---------------------------------------------------------------------------

@router.post(
    "/bulk/reinstate",
    response_model=schemas.AgentBulkSuspendResponse,
    summary="Bulk-reinstate suspended agents (Phase 6 — coordinated reinstate)",
)
async def bulk_reinstate_agents(
    body: schemas.AgentBulkReinstateRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_enforcement")),
) -> schemas.AgentBulkSuspendResponse:
    """Reverse of bulk/suspend. Re-enrolls mTLS (fresh SVID), reactivates TEG,
    flips registry status to active. Soft mode = registry only.
    """
    results: List[schemas.AgentBulkActionResult] = []
    succeeded = skipped = failed = 0
    soft = bool(getattr(body, "soft_reinstate", False))
    mtls_enrolled = teg_reinstated = 0

    for did in body.agent_dids:
        try:
            stmt = select(models.Agent).where(models.Agent.did == did)
            res = await db.execute(stmt)
            agent = res.scalar_one_or_none()
            if agent is None:
                results.append(schemas.AgentBulkActionResult(did=did, status="failed", reason="not found"))
                failed += 1
                continue

            if agent.status != "suspended" and getattr(agent, "enforcement_status", None) != "suspended":
                results.append(schemas.AgentBulkActionResult(did=did, status="skipped", reason="not suspended"))
                skipped += 1
                continue

            crr = await coordinated_agent_reinstate(db, agent, actor=admin, soft=soft)
            if crr.mtls == "enrolled":
                mtls_enrolled += 1
            if crr.teg == "reinstated":
                teg_reinstated += 1

            lever_summary = f"registry={crr.registry} mtls={crr.mtls} teg={crr.teg} cross_teg={crr.cross_teg}"
            if crr.error:
                lever_summary += f" err={crr.error.strip()}"
            results.append(schemas.AgentBulkActionResult(did=did, status="succeeded", reason=lever_summary))
            succeeded += 1

            try:
                await get_event_emitter().emit_agent_reinstated(
                    agent_did=did,
                    actor_developer_id=admin.id,
                    actor_email=admin.email,
                    prior_reason=body.reason or None,
                )
            except Exception as exc:
                logger.warning(f"[AdminAgents] AgentReinstated emit failed for {did}: {exc}")
        except Exception as e:
            logger.error(f"[AdminAgents] bulk_reinstate failed for {did}: {e}")
            results.append(schemas.AgentBulkActionResult(did=did, status="failed", reason=str(e)[:200]))
            failed += 1

    try:
        await db.commit()
    except Exception as e:
        logger.error(f"[AdminAgents] bulk_reinstate commit failed: {e}")
        raise HTTPException(500, "Bulk reinstate commit failed; no changes persisted")

    logger.info(
        f"[AdminAgents] Bulk-reinstate by admin {admin.id}: {succeeded}/{len(body.agent_dids)} succeeded "
        f"(mtls_enrolled={mtls_enrolled}, teg_reinstated={teg_reinstated}, soft={soft}), "
        f"{skipped} skipped, {failed} failed."
    )

    return schemas.AgentBulkSuspendResponse(
        requested=len(body.agent_dids),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        results=results,
    )


# ---------------------------------------------------------------------------
# GET /by-developer/{developer_id} (Phase 6 — cascade preview for frontend)
# ---------------------------------------------------------------------------

@router.get(
    "/by-developer/{developer_id}",
    summary="List agents owned by a developer (cascade preview for suspend UX)",
)
async def list_agents_by_developer(
    developer_id: int,
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> Dict[str, Any]:
    """Phase 6: thin endpoint used by the AdminDevelopers UI to preview which
    agents will cascade-suspend when a developer is suspended."""
    count_stmt = select(func.count(models.Agent.id)).where(
        models.Agent.creator_developer_id == developer_id
    )
    count_res = await db.execute(count_stmt)
    total = int(count_res.scalar() or 0)

    stmt = select(models.Agent).where(
        models.Agent.creator_developer_id == developer_id
    ).limit(limit)
    res = await db.execute(stmt)
    rows = res.scalars().all()
    agents = [
        {
            "did": a.did,
            "name": getattr(a, "name", None),
            "status": a.status,
            "mtls_enabled": bool(a.mtls_enabled),
            "spiffe_id": a.spiffe_id,
        }
        for a in rows
    ]
    return {"developer_id": developer_id, "total": total, "agents": agents}


# ---------------------------------------------------------------------------
# §pass37 (2026-05-18) — POST /bulk/refresh-cards
# Option C bulk action: force a one-shot pull-sync against each agent's
# /.well-known/agent-card.json. Bypasses the 6h scheduler. Same shape as
# bulk/suspend so the frontend can reuse the result-handler.
# ---------------------------------------------------------------------------

@router.post(
    "/bulk/refresh-cards",
    response_model=schemas.AgentBulkRefreshCardsResponse,
    summary="Bulk refresh agent-card pull state from /.well-known/agent-card.json",
)
async def bulk_refresh_cards(
    body: schemas.AgentBulkRefreshCardsRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> schemas.AgentBulkRefreshCardsResponse:
    """Trigger an immediate pull-sync for each DID in the request body.

    The per-agent merge contract (Option C Phase 3) preserves registry-owned
    fields (federation_metadata, flare, last_pulled_*). Agent-canonical fields
    are overwritten from the agent's well-known. Each pull is best-effort —
    unreachable agents return status="timeout"/"5xx" without breaking the
    overall request.

    Audit: each successful pull emits its own `AgentCardPulled` event (only
    when drift is detected — already wired by the worker).
    """
    from agentvault_registry.background_tasks.agent_card_pullsync import (
        trigger_pull_for_did,
    )

    requested = len(body.agent_dids)
    succeeded = 0
    failed = 0
    skipped = 0
    results: List[schemas.AgentBulkRefreshCardResult] = []

    for did in body.agent_dids:
        try:
            outcome = await trigger_pull_for_did(did)
        except Exception as e:  # noqa: BLE001
            outcome = {"status": "error", "reason": str(e)}

        st = outcome.get("status", "error")
        if st == "ok":
            succeeded += 1
        elif st == "skipped":
            skipped += 1
        else:
            failed += 1

        results.append(schemas.AgentBulkRefreshCardResult(
            agent_did=did,
            status=st,
            http=outcome.get("http"),
            url=outcome.get("url"),
            drifted_fields=outcome.get("drifted_fields") or [],
            listed_columns=outcome.get("listed_columns") or [],
            reason=outcome.get("reason"),
        ))

    # Audit emit so the bulk action lands in EventStore alongside the per-
    # agent AgentCardPulled events. Reuses the existing _emit_admin_action
    # helper (one event covers the whole bulk action; per-agent details live
    # in the AgentCardPulled events emitted by the worker).
    try:
        # _emit_admin_action signature: (event_type, agent_did, actor, data).
        # For a bulk action there's no single agent_did, so use a sentinel.
        await _emit_admin_action(
            event_type="AdminBulkRefreshCards",
            agent_did=f"bulk:{admin.id}",
            actor=admin,
            data={
                "requested": requested,
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
                "reason": body.reason,
                "agent_dids": body.agent_dids,
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[bulk_refresh_cards] audit emit failed (non-fatal): {e}")

    return schemas.AgentBulkRefreshCardsResponse(
        requested=requested,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        results=results,
    )
