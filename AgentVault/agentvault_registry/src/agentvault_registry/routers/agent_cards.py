import logging
import uuid
import math
import datetime
import json
import os
from agentvault_registry.services import reputation_bond as _rb
from agentvault_registry.services import enforcement_propagation as _ep  # §ENFPROP
import re
import time
from typing import Optional, List, Dict, Any, Tuple, Annotated

from sqlalchemy import select, func, or_, text, bindparam
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import cast, Text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload # Keep import for get_agent_card

from fastapi import APIRouter, Depends, HTTPException, status, Query, Response, Security
from pydantic import BaseModel, Field, ValidationError as PydanticValidationError # To catch validation errors
import httpx

# Import local dependencies with absolute imports
from agentvault_registry import schemas, models, database
from agentvault_registry.security import get_current_developer, get_current_developer_optional, verify_programmatic_api_key, get_current_actor_for_read_optional, admin_credential
from agentvault_registry.crud import agent_card
from agentvault_registry.server_keymanager import get_server_keymanager
from agentvault_registry.config import settings
from agentvault_registry.federation_helper import query_all_peers

# Import WebSocket notification functions
from agentvault_registry.core.card_stub import STUB_CARD_DESCRIPTION
from agentvault_registry.routers.websocket import (
    notify_agent_update, 
    notify_agent_status_change, 
    broadcast_notification,
    send_notification
)

# Import the AgentCard model from the core library for validation
try:
    from agentvault import AgentCard as AgentCardModel
    from agentvault.agent_card_utils import discover_agents_federated
    _agentvault_lib_available = True
except ImportError:
    AgentCardModel = None # type: ignore
    discover_agents_federated = None # type: ignore
    _agentvault_lib_available = False
    logging.warning("Could not import 'agentvault' library. Agent Card validation and federated discovery will be unavailable.")

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Helper Function to build response dict (Original Version - Assumes developer loaded) ---
async def _health_for(db: AsyncSession, agent_did: Optional[str]):
    """(last_health, last_health_at) for a card's agent, or (None, None).

    §CARDLINK (2026-09-08). The health columns live on `agents`, not on `agent_cards`, and this
    read is the modal's path: `discoveryService.lookupByID` falls through to `/agent-cards/{id}`
    whenever its list cache has not been filled, which is every anonymous `/explore` visit.
    Measured before this: the badge read "not checked from this registry" on a card the discover
    rail already knew was `unhealthy` — honest, and less than we know.

    ⚠ NOT a relationship/property on the ORM model: `AgentCardSummary.model_validate(card)` runs
    under `from_attributes`, so a lazy-loading property would fire a query inside a sync
    attribute read and raise MissingGreenlet in the async session. An explicit await here is the
    boring answer and the only safe one.

    A card with no local agent row — every FEDERATED MIRROR is one — correctly yields (None, None),
    which the UI renders as "not checked from this registry". That is the third state, and it is
    true: this registry has never probed a peer's agent.
    """
    if not agent_did:
        return None, None
    try:
        row = (await db.execute(
            select(models.Agent.last_health, models.Agent.last_health_at)
            .where(models.Agent.did == agent_did)
        )).first()
    except Exception as exc:                     # a health garnish must never fail a card read
        logger.debug(f"[CARDLINK] health lookup for {agent_did} failed: {exc}")
        return None, None
    return (row[0], row[1]) if row else (None, None)


def _build_agent_card_read_dict(db_card: models.AgentCard, health=None) -> dict:
    """Builds the dictionary for AgentCardRead response from the ORM model.

    `health` is the optional `(last_health, last_health_at)` pair from `_health_for`. Sites that
    do not pass it publish the third state (never probed here) rather than an invented one.
    """
    if not db_card:
        return {} # Should not happen if called correctly

    developer_verified = False # Default to False if not loaded
    # Original logic assumed relationship was loaded via selectinload
    if hasattr(db_card, 'developer') and db_card.developer:
        developer_verified = getattr(db_card.developer, 'is_verified', False)
        logger.debug(f"Developer relationship was loaded for Card {db_card.id}. Verified: {developer_verified}")
    else:
        logger.warning(f"Developer relationship not loaded for AgentCard {db_card.id} when building response.")

    return {
        "id": db_card.id,
        # the card's agent DID (schemas.AgentCardRead.agent_did has declared it since OWL22; the builder never set it,
        # so every public read answered null and an external index could not key a native card by DID — §DIDWIDEN)
        "agent_did": getattr(db_card, "agent_did", None),
        "developer_id": db_card.developer_id,
        "card_data": db_card.card_data,
        "name": db_card.name,
        "description": db_card.description,
        "is_active": db_card.is_active,
        # §DISCREFINE — this builder is a field-by-field mapper, i.e. the silent-drop
        # machine of §EXCISION-10: a new column reaches nobody until it is listed HERE.
        # The battery caught exactly that on the first run.
        "unlisted": bool(getattr(db_card, "unlisted", False)),
        # §CARDLINK — whether the PUBLISHED ADDRESS answers, in three states. `None` is
        # "never probed here" and must not read as "dead" (§RAT: never-observed and failing
        # must not look the same).
        "endpoint_health": (health or (None, None))[0] or None,
        "endpoint_checked_at": (health or (None, None))[1],
        "created_at": db_card.created_at,
        "updated_at": db_card.updated_at,
        "developer_is_verified": developer_verified,
    }
# --- End Helper ---


# --- Local flare sidecar injection (mirrors federation_sync export shape) ---
# Local cards don't get card_data.flare persisted on write — flare state lives
# on the agents/developers tables. Inject it at response time so Discovery /
# UserAvatar reads a uniform shape for local and federated cards alike.
# Returns None silently when there's no flare to ship (no agent_did, no tier).
async def _inject_flare_into_card_data(
    db: AsyncSession,
    response_dict: dict,
    db_card: models.AgentCard,
) -> None:
    """Mutate response_dict['card_data']['flare'] with the per-agent flare
    sidecar. Reuses federation_sync._build_flare_sidecar so local-injection
    and peer-export carry identical wire shapes (consumers hoist the same
    fields either way)."""
    if not isinstance(response_dict.get("card_data"), dict):
        return
    if not getattr(db_card, "agent_did", None):
        return
    dev = getattr(db_card, "developer", None)
    # 🔴 NO DEV-TIER PRE-FILTER HERE. §COSMETICS-ORIGIN widened `_build_flare_sidecar` to ship
    # when EITHER the agent or the developer has a tier — a sovereign tier is set ON THE AGENT
    # and is never inherited (§pass39c). This caller kept asking the OLD question, so an agent
    # whose own tier is the interesting one had its flare dropped on every LOCAL read while the
    # federated export carried it correctly. Answering it here needs the agent row, so load it
    # and let the one rule decide. (findings row 169)
    try:
        agent_row = (await db.execute(
            select(models.Agent).where(models.Agent.did == db_card.agent_did)
        )).scalar_one_or_none()
        if not agent_row:
            return
        # Import here to avoid an import cycle (federation_sync imports models).
        from agentvault_registry.routers.federation_sync import _build_flare_sidecar
        _local_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
        our_spiffe = f"spiffe://{_local_domain}/ns/agentvault/sa/registry-main"
        sidecar = await _build_flare_sidecar(agent_row, dev, our_spiffe)
        if sidecar:
            response_dict["card_data"] = {**response_dict["card_data"], "flare": sidecar}
    except Exception as e:
        # Never let flare injection break a card response — log and move on.
        logger.warning(f"Flare injection failed for card {db_card.id}: {e}")


async def _inject_flare_into_card_data_batch(
    db: AsyncSession,
    items: list,
    db_cards: list[models.AgentCard],
) -> None:
    """Batched variant for list endpoints. One agents query, one developers
    pre-loaded via selectinload. items[i]['card_data']['flare'] is mutated
    in-place when there's a flare to ship."""
    if not items or len(items) != len(db_cards):
        return
    # Collect agent_dids of cards that COULD have flare. ⚠ "COULD" is decided by the agent OR
    # the developer (§COSMETICS-ORIGIN) — a dev-tier filter here silently dropped every agent
    # whose OWN tier is sovereign. The agents query below is one `did IN (...)`, so a longer
    # candidate list costs no extra round trip; the builder returns None when neither side has
    # anything to say. (findings row 169)
    candidate_idxs: list[int] = []
    dids: list[str] = []
    for idx, db_card in enumerate(db_cards):
        if not getattr(db_card, "agent_did", None):
            continue
        if not isinstance(items[idx].get("card_data"), dict):
            continue
        candidate_idxs.append(idx)
        dids.append(db_card.agent_did)
    if not candidate_idxs:
        return
    try:
        from agentvault_registry.routers.federation_sync import _build_flare_sidecar
        # One query for all candidate agents.
        agent_rows = (await db.execute(
            select(models.Agent).where(models.Agent.did.in_(dids))
        )).scalars().all()
        agent_by_did = {a.did: a for a in agent_rows}
        _local_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
        our_spiffe = f"spiffe://{_local_domain}/ns/agentvault/sa/registry-main"
        for idx in candidate_idxs:
            db_card = db_cards[idx]
            agent_row = agent_by_did.get(db_card.agent_did)
            if not agent_row:
                continue
            sidecar = await _build_flare_sidecar(agent_row, db_card.developer, our_spiffe)
            if sidecar:
                items[idx]["card_data"] = {**items[idx]["card_data"], "flare": sidecar}
    except Exception as e:
        logger.warning(f"Batched flare injection failed: {e}")
# --- End flare injection ---


# --- §TWOAGENT #10 (2026-09-23): the home extensions on every read of a native card ---
# The bond, enforcement and listing states are this registry's to state, from its own rows, the same way the card-export
# and the federation export state them. A read that served stored card_data stated nothing (the federated Directory
# indexes exactly these reads), and stored card_data is owner content. A mirror keeps its home's copy.
async def _state_home_extensions(db: AsyncSession, response_dict: dict, db_card: models.AgentCard) -> None:
    from ..services.home_extensions import derive_for_read
    response_dict["card_data"] = await derive_for_read(
        db, response_dict.get("card_data"), getattr(db_card, "agent_did", None))


async def _state_home_extensions_batch(db: AsyncSession, items: list, db_cards: list) -> None:
    """The list twin: one query per extension for the page (items[i] belongs to db_cards[i])."""
    if not items or len(items) != len(db_cards):
        return
    from ..services.home_extensions import derive_for_read_batch
    await derive_for_read_batch(db, items, [getattr(c, "agent_did", None) for c in db_cards])


# --- POST /agent-cards ---
@router.post(
    "/",
    response_model=schemas.AgentCardRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new Agent Card",
    description="Submits a new Agent Card associated with the authenticated developer.",
    dependencies=[Security(get_current_developer)] # Apply standard JWT auth here
)
async def submit_agent_card(
    card_in: schemas.AgentCardCreate,
    # Dependencies last
    db: AsyncSession = Depends(database.get_db),
    current_developer: models.Developer = Security(get_current_developer),
) -> schemas.AgentCardRead:
    """
    Endpoint to submit a new Agent Card.
    Requires developer authentication via JWT Bearer token.
    Validates the provided `card_data` against the core AgentCard schema.
    """
    logger.info(f"Received request to create agent card from developer ID: {current_developer.id}")
    try:
        db_agent_card = await agent_card.create_agent_card(
            db=db, developer_id=current_developer.id, card_create=card_in
        )
        # Refresh to load the relationship for the response
        if db_agent_card:
             logger.info(f"Refreshing developer relationship for created card {db_agent_card.id}")
             await db.refresh(db_agent_card, attribute_names=['developer'])
        else:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create agent card record.")

        # Send WebSocket notification for agent creation
        try:
            # Extract DID from card_data if available
            agent_did = db_agent_card.card_data.get('humanReadableId', str(db_agent_card.id))
            
            # Notify subscribers of this agent's topic. Anyone may hold `agent:<id>` (routers/websocket.py::topic_allowed),
            # so this carries public card facts only: the owner's email and developer id went to every subscriber
            # until 2026-09-24 (§TWOAGENT, the #34 class).
            await notify_agent_update(agent_did, {
                "action": "created",
                "name": db_agent_card.name,
                "description": db_agent_card.description,
                "agent_id": str(db_agent_card.id),
                "is_active": db_agent_card.is_active
            })
            
            # Send personal notification to the creator
            await send_notification(
                str(current_developer.id),
                "Agent Created",
                f"Your agent '{db_agent_card.name}' has been successfully created!",
                "success"
            )
            
            # Broadcast to all users
            await broadcast_notification(
                "New Agent",
                f"A new agent '{db_agent_card.name}' has joined the network!",
                "info"
            )
            
            logger.info(f"WebSocket notifications sent for new agent: {db_agent_card.name}")
        except Exception as ws_error:
            # Don't fail the request if WebSocket notification fails
            logger.warning(f"Failed to send WebSocket notification: {ws_error}")

        response_dict = _build_agent_card_read_dict(db_agent_card)
        await _state_home_extensions(db, response_dict, db_agent_card)
        return schemas.AgentCardRead.model_validate(response_dict)
    except ValueError as e:
        logger.warning(f"Failed to create agent card due to validation/DB error: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to create agent card: {e}",
        )
    except Exception as e:
        logger.exception(f"Unexpected error creating agent card for developer {current_developer.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the agent card.",
        )


# B9 (2026-06-03) — focused Discovery showcases that bypass the general list's
# fetch window. On a 12k-card frame the handful of encircled / cross-currency
# agents would otherwise be buried past the limit (and force a 25MB client fetch).
# These run a tiny server-side-filtered query so the showcase loads complete + fast
# on ANY frame size. Items carry card_data + injected flare + B8 currency tags —
# same wire shape as list_agent_cards' include_card_data branch (the FE parser +
# useCurrency consume them identically).
async def _list_focused_subset(
    db: AsyncSession,
    *,
    bearing_encirclement: bool,
    foreign_only: bool,
    limit: int,
) -> dict:
    local_ccy = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
    local_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")

    # peer name -> (currency, trust_domain) from cached signed registry cards.
    # Built FIRST so foreign_only can filter the query directly by foreign-peer
    # origin (precise + complete; avoids burying foreign cards behind a blind limit).
    peer_ccy_map: Dict[str, tuple] = {}
    try:
        for p in (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE"))).scalars().all():
            c = getattr(p, "cached_registry_card", None)
            if isinstance(c, dict) and isinstance(c.get("fees"), dict):
                s = c["fees"].get("settlement_currency")
                if isinstance(s, str) and s.strip() and p.name and p.name not in peer_ccy_map:
                    peer_ccy_map[p.name] = (s.strip().upper(), getattr(p, "trust_domain", None))
    except Exception:
        peer_ccy_map = {}
    foreign_origins = [name for name, (ccy, _td) in peer_ccy_map.items() if ccy and ccy != local_ccy]

    if foreign_only and not foreign_origins:
        return {"items": [], "pagination": {"total_items": 0, "limit": limit, "offset": 0, "total_pages": 0, "current_page": 1}}
    # §TWOAGENT #9 (2026-09-23): peer rows store `asia` while every ASIA-native mirror's card says `ASIA`
    # (the registry-card fan-out re-inserts a peer frame under its UPPERCASE card name), so an exact IN matched
    # only operator-homed cards and hid the peer FRAME's own agents from foreign_only. Names are case-insensitive
    # here as they are in discover and in resolve_peer_name.
    foreign_origins_lc = sorted({n.lower() for n in foreign_origins})

    stmt = (
        select(models.AgentCard)
        .options(selectinload(models.AgentCard.developer))
        .outerjoin(models.Agent, models.Agent.did == models.AgentCard.agent_did)
        .where(models.AgentCard.is_active.is_(True), models.AgentCard.unlisted.is_(False))   # §DARKSYNC: a showcase
    )
    if bearing_encirclement:
        # local flare lives on the agents/developers rows; federated flare in card_data.flare
        stmt = stmt.where(or_(
            models.Agent.bears_encirclement_flare.is_(True),
            models.Agent.flare_tier == "sovereign",
            models.Agent.flare_encirclement_variant.isnot(None),
            text("(card_data->'flare'->>'bears_encirclement_flare') = 'true'"),
            text("(card_data->'flare'->>'selected_encirclement_flare') IS NOT NULL"),
            text("(card_data->'flare'->>'encirclement_variant') IS NOT NULL"),
        ))
    if foreign_only:
        # directly select cards whose home registry (origin) is a foreign-currency
        # peer → only-foreign result, complete regardless of total frame size.
        # Raw JSONB path (proven) + expanding bindparam for the origins list.
        stmt = stmt.where(
            text("LOWER(card_data->'federation_metadata'->>'origin_registry_name') IN :forg")
            .bindparams(bindparam("forg", value=foreign_origins_lc, expanding=True))
        )
    stmt = stmt.limit(max(limit, 1) if foreign_only else 500)
    cards = (await db.execute(stmt)).scalars().all()

    def _resolve(cd: dict):
        fm = (cd.get("federation_metadata") or {}) if isinstance(cd, dict) else {}
        # §DISCFIX — a card with no federation SOURCE is local, full stop. Local
        # cards carry origin_registry_name='<own name>' in their stamp, and the
        # old check read that as "federated from Registry-A" → the Distinguished
        # grid badged the registry's own agents as foreign mirrors of itself.
        if not (fm.get("source_registry") or fm.get("first_synced_from")):
            return local_ccy, local_td, "Local"
        origin = fm.get("origin_registry_name") or fm.get("source_registry") or ""
        r = peer_ccy_map.get(origin) or peer_ccy_map.get(fm.get("source_registry") or "")
        if r:
            return r[0], r[1], origin
        fees = cd.get("fees") if isinstance(cd.get("fees"), dict) else {}
        pr = cd.get("pricing") if isinstance(cd.get("pricing"), dict) else {}
        sym = fees.get("settlement_currency") or pr.get("currency")
        return ((sym.strip().upper() if isinstance(sym, str) and sym.strip() else None), None, origin)

    items: list = []
    for c in cards:
        d = {**schemas.AgentCardSummary.model_validate(c).model_dump(), "card_data": c.card_data}
        ccy, td, origin = _resolve(c.card_data or {})
        if ccy:
            d["settlement_currency"] = ccy
        if td:
            d["trust_domain"] = td
        d["origin_registry_name"] = origin or "Local"
        items.append(d)

    # inject flare on local cards so UserAvatar renders the encirclement (parallel to `cards`)
    await _state_home_extensions_batch(db, items, list(cards))
    await _inject_flare_into_card_data_batch(db, items, list(cards))

    if foreign_only:
        items = [d for d in items if d.get("settlement_currency") and d["settlement_currency"] != local_ccy]

    items = items[: max(limit, 1)]
    return {"items": items, "pagination": {"total_items": len(items), "limit": limit, "offset": 0, "total_pages": 1, "current_page": 1}}



async def _attach_registry_trust(db: AsyncSession, summaries: list, viewer_actor: Optional[dict]) -> int:
    """§TRUSTCHAIN (2026-09-12) — journal 45's last claim, made true on the wire:
    "an agent reading discovery from the backend receives the verdict in the same response".

    Until now the verdict rode ONLY `/federation/registries` (per peer, developer viewer only) and
    the FE joined it onto cards by origin name; software reading `/agent-cards/` got nothing.
    This attaches `registry_trust` to every card whose `origin_registry_name` is an ACTIVE peer of
    this frame, for an IDENTIFIED caller (developer or agent). Three rules it keeps:
      * anonymous callers get nothing (a published verdict on a peer is a credit bureau);
      * a native card ("Local") gets nothing — a frame holds no opinion of itself;
      * ONE implementation: `peer_trust_policy.trust_block`, the block `/federation/registries`
        serves, computed once per peer per request. The origin name is the one the union path
        already resolved (`summary_dict["origin_registry_name"]`); nothing is re-derived here.
    Fails OPEN: on any error the cards render without the block, and the FE reads an absent block
    as "not told", which is a state and not an endorsement. Returns the number of cards tagged.
    """
    if viewer_actor is None or not summaries:
        return 0

    def _origin(s: Any) -> Optional[str]:
        o = s.get("origin_registry_name") if isinstance(s, dict) else getattr(s, "origin_registry_name", None)
        return o if isinstance(o, str) and o and o != "Local" else None

    wanted = {o.lower() for o in (_origin(s) for s in summaries) if o}
    if not wanted:
        return 0
    try:
        from ..services import frame_policy as _fp
        from ..services import peer_trust_policy as _ptp
        peers_res = await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE"))
        peers = {p.name.lower(): p for p in peers_res.scalars().all() if getattr(p, "name", None)}
        policy = await _fp.load(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[DISCOTRUST] registry_trust not attached (non-fatal, cards render without it): {exc}")
        return 0
    blocks: Dict[int, Dict[str, Any]] = {}
    tagged = 0
    for s in summaries:
        o = _origin(s)
        if not o:
            continue
        peer = peers.get(o.lower())
        if peer is None:
            continue
        if peer.id not in blocks:
            blocks[peer.id] = _ptp.trust_block(peer, policy)
        if isinstance(s, dict):
            s["registry_trust"] = blocks[peer.id]
        else:
            s.registry_trust = blocks[peer.id]
        tagged += 1
    return tagged


# --- GET /agent-cards ---
@router.get(
    "/",
    response_model=None,
    summary="List Agent Cards",
    description="Retrieves a paginated list of active Agent Cards, optionally filtered by search query, tags, TEE status, or ownership.",
)
async def list_agent_cards(
    # Dependencies (non-default) first
    db: AsyncSession = Depends(database.get_db),
    current_developer: Optional[models.Developer] = Depends(get_current_developer_optional), # Correct dependency
    viewer_actor: Optional[dict] = Depends(get_current_actor_for_read_optional),  # §TRUSTCHAIN: developer OR agent
    # Query parameters with defaults after dependencies
    skip: int = Query(0, ge=0, description="Number of records to skip for pagination."),
    limit: int = Query(100, ge=1, le=5000, description="Maximum number of records to return."),
    active_only: bool = Query(True, description="Filter for active agent cards only."),
    search: Optional[str] = Query(
        None,
        max_length=100,
        description="Search term to filter by name or description (case-insensitive, max 100 chars)."
    ),
    tags: Optional[List[str]] = Query(
        None,
        description="List of tags to filter by (agents must have ALL specified tags)."
    ),
    has_tee: Optional[bool] = Query(None, description="Filter for agents that have TEE details declared."),
    tee_type: Optional[str] = Query(None, max_length=50, description="Filter by the specific TEE type string (e.g., 'Intel SGX', max 50 chars)."),
    owned_only: bool = Query(False, description="If true, only return cards owned by the authenticated developer (requires authentication)."),
    include_federated: bool = Query(False, description="If true, include results from federated peer registries."),
    include_card_data: bool = Query(False, description="If true, include full card_data in each item (for map/universe views)."),
    bearing_encirclement: bool = Query(False, description="B9: return only agents bearing an encirclement flare (the Distinguished showcase) — server-filtered, complete on any frame size."),
    foreign_only: bool = Query(False, description="B9: return only cross-currency (foreign-frame) agents relative to this registry's settlement currency."),
    # §DIRFEED (2026-09-06) — the INDEX FEED: an external directory walks this list as a change feed.
    # `updated_since` is the cursor (inclusive), `natives_only` drops this registry's mirrors of other
    # registries' agents (they are indexed from their origin, never from a mirror). Both are echoed back
    # in `applied_filters` because FastAPI silently ignores a query parameter a server does not declare,
    # so a client cannot otherwise tell an applied filter from an ignored one.
    updated_since: Optional[datetime.datetime] = Query(None, description="Index cursor: return only cards whose updated_at is at or after this instant (ISO-8601). Ordering flips to updated_at ASC."),
    natives_only: bool = Query(False, description="Return only cards NATIVE to this registry (no federation_metadata.source_registry / first_synced_from). Implies include_federated=false."),
    include_unlisted: bool = Query(False, description="§DARKSYNC: admins only, include unlisted (dark) cards. The owner's `owned_only` list always includes its own."),
):
    """
    Public endpoint to list and search for Agent Cards.
    Can optionally filter by owned cards if authenticated.
    Can filter by TEE presence and type.
    """
    # §DIRFEED: a mirror is by definition not native, so asking peers while filtering to natives would
    # contradict itself — natives_only wins and the fan-out is skipped.
    if natives_only:
        include_federated = False
    applied_filters: Optional[Dict[str, Any]] = None
    # §DARKSYNC (2026-09-22): unlisted (dark) cards are not in discovery. Everyone gets listed cards only, except the
    # owner listing its own (`owned_only`) and an admin who asks for them.
    listed_only = not (owned_only or (include_unlisted and current_developer is not None
                                      and admin_credential(current_developer)))   # D6-821: on this credential
    if updated_since is not None or natives_only:
        applied_filters = {
            "updated_since": updated_since.isoformat() if updated_since is not None else None,
            "natives_only": bool(natives_only),
            "listed_only": bool(listed_only),
        }

    developer_id_filter: Optional[int] = None
    if owned_only:
        if current_developer is None:
            logger.warning("Attempted to list owned cards without valid authentication.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to list owned agent cards."
            )
        developer_id_filter = current_developer.id
        logger.info(f"Listing agent cards for owner ID: {developer_id_filter}, skip={skip}, limit={limit}, active_only={active_only}, search='{search}', tags={tags}, has_tee={has_tee}, tee_type='{tee_type}'")
    else:
        logger.info(f"Listing public agent cards with skip={skip}, limit={limit}, active_only={active_only}, search='{search}', tags={tags}, has_tee={has_tee}, tee_type='{tee_type}'")

    try:
        # B9 (2026-06-03) — focused showcase subsets (encircled / cross-currency)
        # short-circuit the general list path entirely → tiny complete payload,
        # immune to the fetch-window burial on large frames.
        if bearing_encirclement or foreign_only:
            return await _list_focused_subset(
                db, bearing_encirclement=bearing_encirclement, foreign_only=foreign_only, limit=limit,
            )
        # B8 (2026-06-03) — FX-aware discovery currency tagging. Mirror /discover B7:
        # tag each returned card with its HOME-frame settlement_currency + trust_domain
        # so the FE (useCurrency.currencyForItem / isForeignItem) can render foreign
        # agents in THEIR currency and grey/badge cross-currency cards when the viewer's
        # frame has FX off. Additive keys only (splatted post-model_dump like card_data,
        # so no schema change). Local agent currency = FRAME_CURRENCY env (A/B=AVT, C=BVT);
        # federated agent currency = the peer's signed registry card (built once below).
        _local_ccy = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
        _local_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")

        def _native_card(it: Any) -> bool:
            """A card is native to THIS registry iff it has no federation source."""
            cd = (getattr(it, "card_data", None) if not isinstance(it, dict) else it.get("card_data")) or {}
            fm = cd.get("federation_metadata") or {} if isinstance(cd, dict) else {}
            return not (fm.get("source_registry") or fm.get("first_synced_from"))

        def _peer_card_ccy(c: Any) -> Optional[str]:
            """settlement_currency from a peer's cached signed registry card (fees block)."""
            if isinstance(c, dict):
                fees = c.get("fees")
                if isinstance(fees, dict):
                    sym = fees.get("settlement_currency")
                    if isinstance(sym, str) and sym.strip():
                        return sym.strip().upper()
            return None

        # §pass35.2 (2026-05-17) — DROP native_only entirely.
        #
        # History:
        # • §pass10 added native_only=include_federated to prevent peer-sync
        #   churn from burying native cards past `limit` on Frame A.
        # • §pass35 relaxed it only when `search` was provided. But Discovery.vue
        #   calls /agent-cards/ WITHOUT a search param (it filters client-side)
        #   so on Frame B SYBIL (synced from Registry-A with full card_data +
        #   flare) was still excluded — only the peer's stripped summary
        #   reached the UI, killing the flare visual and showing
        #   "synced from op-singapore" instead of "Registry-A".
        # • §pass35.2 drops the gate entirely. Smart dedup (below) already
        #   prefers entries with richer card_data over stripped peer-query
        #   summaries — that handles peer-sync duplicates without dropping
        #   our locally-mirrored federated rows.
        items, total_items = await agent_card.list_agent_cards(
            db=db, skip=skip, limit=limit, active_only=active_only, search=search, tags=tags,
            developer_id=developer_id_filter,
            has_tee=has_tee,
            tee_type=tee_type,
            native_only=bool(natives_only),   # §DIRFEED
            updated_since=updated_since,      # §DIRFEED
            listed_only=listed_only,          # §DARKSYNC
        )

        # §pass35.3 (2026-05-17) — Flare-bearing card augmentation.
        #
        # Even with native_only=False the CRUD orders by updated_at DESC and
        # caps at `limit` (250 from Discovery.vue). On Frame B SYBIL's local
        # row was at rank 1226 of 1362 active cards — newer sim/canary updates
        # had pushed it out of the limit window. The peer query then provided
        # the stripped op-singapore version with no card_data; dedup had only
        # the stripped entry to choose from, so the flare never reached the UI.
        #
        # Fix: when include_card_data + include_federated, also fetch ALL
        # cards with `card_data->'flare'` present that weren't already in
        # `items`, and prepend them. Flare-bearing cards are a small set
        # (Frame B currently has ~7) so the cost is negligible. This guarantees
        # the locally-mirrored, fully-stamped flare card always reaches the FE
        # and wins the smart dedup over any peer-query stripped version.
        # §DIRFEED: the augmentation below deliberately prepends cards that match NO filter; under a cursor
        # that would hand an index rows it did not ask for and break the feed's contract.
        if include_federated and include_card_data and updated_since is None:
            try:
                # §pass38c (2026-05-18) — broadened augmentation. Original §pass35.3
                # query (`card_data->'flare' IS NOT NULL`) only rescued federated
                # cards where peers had stamped flare into card_data at export
                # time. On the HOME registry, flare is never persisted into
                # card_data — it lives on `developers.flare_tier` / `agents.flare_tier`
                # and is response-time injected by _inject_flare_into_card_data_batch.
                # Result: native flare-bearing cards (SYBIL, CRUCIBLE, sentinel
                # wallet) ranked past `limit` and disappeared from Discovery.
                # Boris (avatar/iconUrl, no flare_tier) had the same problem.
                # New OR catches: (1) already-stamped (existing), (2) developer has
                # flare_tier (native flare-bearers), (3) card_data.iconUrl set
                # (avatar-bearers like Boris).
                already_ids = {item.id for item in items}
                flare_stmt = (
                    select(models.AgentCard)
                    .options(selectinload(models.AgentCard.developer))
                    .outerjoin(
                        models.Developer,
                        models.Developer.id == models.AgentCard.developer_id,
                    )
                    .where(
                        models.AgentCard.is_active.is_(True),
                        models.AgentCard.unlisted.is_(False) if listed_only else text("TRUE"),   # §DARKSYNC
                        or_(
                            text("(card_data->'flare') IS NOT NULL"),
                            models.Developer.flare_tier.isnot(None),
                            text("(card_data->>'iconUrl') IS NOT NULL AND length(card_data->>'iconUrl') > 0"),
                        ),
                    )
                )
                flare_res = await db.execute(flare_stmt)
                flare_items = [c for c in flare_res.scalars().all() if c.id not in already_ids]
                if flare_items:
                    # Prepend so they iterate first in the federation loop — gives
                    # them priority via insert(0, ...) ordering when stamped.
                    items = list(flare_items) + list(items)
                    logger.info(f"[FEDERATION] flare-augmentation: {len(flare_items)} cards added")
            except Exception as flare_e:  # noqa: BLE001
                logger.warning(f"[FEDERATION] flare-augmentation failed: {flare_e}")

        # Construct pagination info
        current_page = (skip // limit) + 1 if limit > 0 else 1
        total_pages = math.ceil(total_items / limit) if limit > 0 else (1 if total_items > 0 else 0)

        pagination_info = schemas.PaginationInfo(
            total_items=total_items,
            limit=limit,
            offset=skip,
            total_pages=total_pages,
            current_page=current_page,
        )
        # Serialize items — include card_data when requested (for map/universe views)
        if include_card_data:
            summaries = []
            for item in items:
                _d = {**schemas.AgentCardSummary.model_validate(item).model_dump(),
                      "card_data": getattr(item, 'card_data', None)}
                # B8: tag native cards with this frame's currency (foreign-synced
                # cards in the non-federated path are left untagged → FE viewer-
                # currency fallback; the federated path below resolves them fully).
                if _native_card(item):
                    _d["settlement_currency"] = _local_ccy
                    _d["trust_domain"] = _local_td
                summaries.append(_d)
            # §28.1 (2026-05-15) — Batch-inject flare into card_data for local
            # cards in the simple (non-federated) list path. Map / universe
            # views read flare composition from this payload. Federated path
            # below leaves peer-sourced summaries untouched (peers already
            # stamp via federation_sync._build_flare_sidecar on their export).
            await _state_home_extensions_batch(db, summaries, list(items))
            await _inject_flare_into_card_data_batch(db, summaries, list(items))
        else:
            summaries = [schemas.AgentCardSummary.model_validate(item) for item in items]
        
        # Handle federated search if requested
        if include_federated:
            logger.info("[FEDERATION] Federated search requested, using federation_helper")
            # Always use our federation helper to query peer registries
            try:
                _fed_stats: Dict[str, int] = {}
                federated_results = await query_all_peers(
                    db=db,
                    search=search,
                    tags=tags,
                    limit=limit,
                    offset=skip,
                    active_only=active_only,
                    has_tee=has_tee,
                    tee_type=tee_type,
                    stats=_fed_stats,
                )
                
                # Build SVID → peer name mapping to detect agents synced from peers
                # Federation sync stores source_registry as a SPIFFE ID in card_data.federation_metadata
                peer_stmt = select(models.PeerRegistry).filter(models.PeerRegistry.status == "ACTIVE")
                peer_result = await db.execute(peer_stmt)
                active_peers = peer_result.scalars().all()
                svid_to_peer_name: Dict[str, str] = {}
                peer_name_slugs: Dict[str, str] = {}  # OWL24: slug → peer name
                _peer_ccy_map: Dict[str, tuple] = {}  # B8: peer name → (settlement_currency, trust_domain)
                for p in active_peers:
                    # Match the SVID format used by federation_sync._process_peer_cards
                    svid = f"spiffe://agentvault.com/ns/agentvault/sa/registry-{p.name.lower().replace(' ', '-')}"
                    svid_to_peer_name[svid] = p.name
                    # Also map by peer name directly (for robustness)
                    svid_to_peer_name[p.name.lower()] = p.name
                    # OWL24 FIX: Build slug-based mapping for SPIFFE format mismatches.
                    # Source uses /service/registry-b but SVID uses /ns/.../sa/registry-registry-b
                    # Extract the slug from the peer name (e.g., "Registry B" → "registry-b")
                    slug = p.name.lower().replace(' ', '-')  # e.g., "registry-b"
                    peer_name_slugs[slug] = p.name
                    # B8: peer's home-frame currency from its signed registry card.
                    _pccy = _peer_card_ccy(getattr(p, "cached_registry_card", None))
                    if _pccy and p.name and p.name not in _peer_ccy_map:
                        _peer_ccy_map[p.name] = (_pccy, getattr(p, "trust_domain", None))
                logger.info(f"[FEDERATION] Built SVID mapping for {len(active_peers)} peers: {list(svid_to_peer_name.values())} slugs: {list(peer_name_slugs.keys())}")
                
                # Add local results with correct origin_registry_name
                # Agents synced from peers have federation_metadata in card_data
                # §pass12 (2026-05-15) — Collect local summary_dicts so we can
                # batch-inject flare on them after the loop (federated branch
                # rebuilds dicts from scratch and bypasses the simple-path
                # injection above).
                _local_summaries: list = []
                _local_items_for_flare: list = []
                # §TWOAGENT V0438: the local rows' card_data as the simple path above already STATED it (the home
                # extensions derived, owner copies dropped). V0437 derived the page a second time here, which doubled
                # the three queries on Discovery's read (measured on sbx-alpha: ~1.3 s per pass on a 5,000-card page).
                # The simple path's `summaries` stay derived, because they are what this route answers with if the
                # federated branch fails.
                _stated_card_data = ({getattr(it, "id", None): s.get("card_data") for it, s in zip(items, summaries)}
                                     if include_card_data and len(summaries) == len(items) else {})
                for item in items:
                    summary_dict = schemas.AgentCardSummary.model_validate(item).model_dump()
                    if include_card_data:
                        summary_dict["card_data"] = getattr(item, 'card_data', None)

                    # Check if this agent was synced from a peer registry
                    card_data = getattr(item, 'card_data', None) or {}
                    fed_meta = card_data.get('federation_metadata', {})
                    # ONLY use creation-time metadata (source_registry, first_synced_from)
                    # DO NOT use last_synced_from — that gets set when a LOCAL card is updated by a peer
                    source = fed_meta.get('source_registry', '') or fed_meta.get('first_synced_from', '')
                    
                    origin = "Local"
                    # §pass10 (2026-05-15) — Native-card guard: a card is
                    # NATIVE on this registry iff `source` is empty (no
                    # source_registry, no first_synced_from). Native cards
                    # MUST resolve to "Local" regardless of any
                    # federation_metadata.origin_registry_name that may have
                    # been stamped by an older code path (legacy §15-era
                    # writes left "Registry-A" on this registry's own cards,
                    # which then misclassified SYBIL et al. as federated).
                    meta_origin = fed_meta.get('origin_registry_name')
                    if source and meta_origin and meta_origin.lower() not in ('unknown registry', 'local', 'agentvault registry'):
                        # Self-describing card: use embedded origin_registry_name FIRST
                        # This is the authoritative source for relay-propagated cards
                        origin = meta_origin
                    elif source:
                        # Try exact SVID match first
                        if source in svid_to_peer_name:
                            origin = svid_to_peer_name[source]
                        else:
                            # Try substring match on full SVID
                            matched = False
                            for svid, pname in svid_to_peer_name.items():
                                if svid in source or source in svid:
                                    origin = pname
                                    matched = True
                                    break
                            # OWL24 FIX: Slug-based fallback — extract slug from source SPIFFE URI
                            # e.g., "spiffe://agentvault.com/service/registry-b" → "registry-b"
                            if not matched:
                                source_lower = source.lower()
                                for slug, pname in peer_name_slugs.items():
                                    if slug in source_lower:
                                        origin = pname
                                        matched = True
                                        logger.info(f"[FEDERATION] OWL24 slug match: '{slug}' found in '{source_lower[:60]}' → peer '{pname}'")
                                        break
                            # (Self-describing fallback moved to top of origin resolution)
                        if origin != "Local":
                            logger.info(f"[FEDERATION] Agent '{getattr(item, 'name', '?')}' detected as synced from peer '{origin}' (source={source[:60]})")
                    
                    summary_dict["origin_registry_name"] = origin
                    # §pass12 — collect local-origin dicts for batch flare injection.
                    if include_card_data and origin == "Local":
                        if getattr(item, "id", None) in _stated_card_data:
                            summary_dict["card_data"] = _stated_card_data[getattr(item, "id", None)]
                        _local_summaries.append(summary_dict)
                        _local_items_for_flare.append(item)
                    federated_results.insert(0, summary_dict)

                # §pass12 (2026-05-15) — Batch-inject flare into local-card
                # summary_dicts in the federated branch. This is what feeds
                # Discovery (`include_federated=true` + `include_card_data=true`)
                # — without it, local cards (SYBIL, Gerald, ...) ship without
                # `card_data.flare` and UserAvatar falls back to bare initials.
                if include_card_data and _local_summaries:
                    # (the home extensions were stated once, above; `_stated_card_data` carried them here)
                    await _inject_flare_into_card_data_batch(db, _local_summaries, _local_items_for_flare)

                # Deduplicate: agents synced from peers exist in both local DB and live peer query.
                # Local copies (inserted at front) take priority — remove peer duplicates by name.
                #
                # §pass35 (2026-05-17) — when both entries share the same name,
                # prefer the one with non-empty `card_data` (the local DB copy
                # carries flare + federation_metadata + capabilities; peer
                # query results from federation_helper.query_all_peers have
                # only id/name/description/is_active/origin). This is a
                # defense-in-depth dedup: even if the new native_only relax
                # doesn't surface the local copy first, a later-encountered
                # richer entry replaces the prior stripped one in-place.
                def _card_data_richness(entry: Any) -> int:
                    cd = None
                    if isinstance(entry, dict):
                        cd = entry.get("card_data")
                    else:
                        cd = getattr(entry, "card_data", None)
                    if not isinstance(cd, dict):
                        return 0
                    return len(cd)

                # §TWOAGENT #11 (2026-09-23): the DID is the only address an agent has, and names are not unique (two
                # different agents called "Echo" are two agents). Rows that carry a DID are deduplicated BY DID, the
                # local copy first; only a row with no DID falls back to the old name rule.
                federated_results, _fed_dropped = dedup_federated_rows(federated_results, _card_data_richness)
                applied_filters = dict(applied_filters or {})
                applied_filters.update({
                    "search": search, "tags": tags, "has_tee": has_tee, "tee_type": tee_type,
                    "include_federated": True, "listed_only": bool(listed_only),
                    "federated": {
                        "peers_queried": _fed_stats.get("peers", 0),
                        "peer_cards_read": _fed_stats.get("fetched", 0),
                        "peer_cards_matched": _fed_stats.get("matched", 0),
                        "duplicates_dropped": _fed_dropped,
                        "how": "each peer's most recent cards (its sync feed takes no search) filtered here by the "
                               "same rules as the local list; deduplicated by DID, local copy first",
                    },
                })

                # Respect the caller's `limit`. Without this, the
                # include_card_data + include_federated path returned the ENTIRE
                # deduped union — on sandbox-A that is 12,722 cards / ~25 MB,
                # which hung the Universe + Galactic map loads (their FE comments
                # already document fetchAllForMap / fetchAllAgents as "capped").
                # The front of the list holds flare-augmented + local cards
                # (prepended above), so the important rows survive the slice.
                # Capture the true union size first so pagination stays accurate.
                _federated_total = len(federated_results)
                if limit and limit > 0:
                    federated_results = federated_results[skip : skip + limit]

                # Replace summaries with combined results (preserve card_data if requested)
                if include_card_data:
                    summaries = []
                    for item in federated_results:
                        d = schemas.AgentCardSummary.model_validate(item).model_dump()
                        # Preserve card_data from the dict (set earlier in the loop)
                        if isinstance(item, dict) and 'card_data' in item:
                            d['card_data'] = item['card_data']
                        # B8: FX currency tag by canonical origin (Local → this frame;
                        # peer → its signed card currency). Unmatched peer → untagged
                        # (FE viewer-currency fallback; never a mislabel).
                        _org = (item.get('origin_registry_name') if isinstance(item, dict) else None) or 'Local'
                        if _org == 'Local':
                            d['settlement_currency'] = _local_ccy
                            d['trust_domain'] = _local_td
                        else:
                            _r = _peer_ccy_map.get(_org)
                            if _r:
                                d['settlement_currency'] = _r[0]
                                if _r[1]:
                                    d['trust_domain'] = _r[1]
                        summaries.append(d)
                else:
                    summaries = [schemas.AgentCardSummary.model_validate(item) for item in federated_results]

                # Update total count (true union size, not the sliced window)
                total_items = _federated_total
                
                # Recalculate pagination info
                current_page = (skip // limit) + 1 if limit > 0 else 1
                total_pages = math.ceil(total_items / limit) if limit > 0 else (1 if total_items > 0 else 0)
                
                pagination_info = schemas.PaginationInfo(
                    total_items=total_items,
                    limit=limit,
                    offset=skip,
                    total_pages=total_pages,
                    current_page=current_page,
                )
            except Exception as e:
                logger.error(f"[FEDERATION] Error during federated discovery: {e}")
                # Continue with local results only
        
        # §TRUSTCHAIN: the host registry's verdict, on the card, for an identified caller (journal 45).
        await _attach_registry_trust(db, summaries, viewer_actor)
        if include_card_data:
            # Return as plain dict to preserve card_data (not stripped by schema)
            items_out = [s.model_dump() if hasattr(s, 'model_dump') else s for s in summaries]
            return {"items": items_out, "pagination": pagination_info.model_dump(), "applied_filters": applied_filters}
        return schemas.AgentCardListResponse(items=summaries, pagination=pagination_info, applied_filters=applied_filters)

    except SQLAlchemyError:
        raise   # §MCPTEST30 (V0546): the errors module answers a database error by its cause (a caller's value 422, capacity 503)
    except Exception as e:
        logger.exception("Error listing agent cards")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving agent cards.",
        )


def dedup_federated_rows(rows: list, richness=None) -> tuple:
    """§TWOAGENT #11: deduplicate the federated listing. A row with a DID is kept once per DID (the first, which is the
    local copy: local rows are prepended). A row without a DID falls back to the legacy name rule, keeping the richer
    of two same-named rows. Returns (rows, dropped_count)."""
    def _get(entry, key):
        return entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
    richness = richness or (lambda e: 0)
    seen_did: set = set()
    seen_name: Dict[str, int] = {}
    out: list = []
    dropped = 0
    for entry in rows:
        did = _get(entry, "agent_did")
        if did:
            if did in seen_did:
                dropped += 1
                continue
            seen_did.add(did)
            out.append(entry)
            continue
        name_key = (_get(entry, "name") or "").lower().strip()
        if not name_key:
            out.append(entry)
            continue
        if name_key not in seen_name:
            seen_name[name_key] = len(out)
            out.append(entry)
            continue
        dropped += 1
        idx = seen_name[name_key]
        if richness(entry) > richness(out[idx]):
            out[idx] = entry
    return out, dropped


# --- GET /agent-cards/discover — §DISCFIX (2026-08-03) ---------------------
# Purpose-built server-side search for the Discovery view. The legacy path
# (`GET /agent-cards/?limit=5000&include_card_data=true`) measured 19.8s /
# 3.4MB on registry-a and its updated_at-DESC window surfaced only 337 of
# 1,970 local agents; the FE then deduplicated by NAME, which collapses the
# forge lineages (83 distinct agents share the name "forge-a-gen-1") and hid
# ~5,500 real agents. This endpoint:
#   • dedups by agent_did (the identity key; mirrors of one agent share it),
#   • filters + sorts + paginates in SQL (3 queries, ~ms at 8k cards),
#   • returns per-origin facet counts so the peer filter shows the truth,
#   • joins agents.reputation_score + last_active_at (real liveness) for
#     local agents — federated mirrors honestly carry null,
#   • ships a COMPACT projection (id/did/name/pricing/tags/flare/iconUrl),
#     not the full card_data blob.
# Registered BEFORE the "/{card_id}" route — FastAPI registration order beats
# path specificity (§NOTIFV2), so declaring it later would 404 via UUID parse.
# ── §DISCREFINE (2026-08-23) — ONE price rule, two legal dialects ──────────
# A card may declare its charge in the legacy top-level `pricing` block, OR in
# the A2A v1.0 payment extension, which our own SDK says an agent accepting A2A
# payments MUST publish (theprotocol-sdk/registry/cost_composition.py). This
# query read only the first, so SYBIL — 5.0 AVT, its container live with
# PAYMENT_REQUIRED=true — was listed "Free" under a "no payment required" note
# and a free-call button. Reading the extension is CONFORMANCE with the standard
# we vendor at tag v1.0.1, not a workaround for one card.
#
# The raw extension object is pulled ONCE in `slim` as `pay_ext` so that the
# derived columns AND the pricing filter can both read it: SQL cannot reference
# an output alias from its own WHERE, but it can read a prior CTE's column. That
# is why the rule below lives in Python constants and is substituted in — one
# source of truth for the row, the filter, the facet count and the sort.
_EXT_A2A_PAYMENT = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"
# ⚠ THE COLUMN IS `JSON`, NOT `JSONB`, ON 8 OF THE 13 CLOUD-OPS — and models.py
# declares plain `JSON`, so those databases are the ones honouring the model. Every
# jsonb_* function here must therefore cast; without it `discover` 500s outright
# (not just this filter - this CTE backs every discover query) on half the fleet.
# It was masked until 2026-08-27 because ops relayed buys to their hosting frame,
# so the local pricing path never ran there.
_PAY_EXT_SQL = (
    "jsonb_path_query_first(c.card_data::jsonb, "
    "'$.extensions[*] ? (@.uri == \"" + _EXT_A2A_PAYMENT + "\")')"
)
_NUMERIC = "'^[0-9]+(\\.[0-9]+)?$'"

# Paid ⇔ the legacy block says payment_required, OR the extension carries a
# positive numeric base_rate. `required` is carried through as payment_required
# but deliberately does NOT decide paid-ness: it declares extension support, not
# a charge. This is the same read the SDK performs.
_SQL_IS_PAID = (
    "COALESCE("
    "COALESCE((s.card_data#>'{pricing,payment_required}')::text,'false') = 'true'"
    " OR ((s.pay_ext->'params'->>'base_rate') ~ " + _NUMERIC +
    " AND (s.pay_ext->'params'->>'base_rate')::numeric > 0)"
    ", FALSE)"
)
_SQL_SAFE_PRICE = (
    "COALESCE("
    "CASE WHEN (s.card_data#>>'{pricing,base_rate}') ~ " + _NUMERIC +
    " THEN (s.card_data#>>'{pricing,base_rate}')::numeric END,"
    "CASE WHEN (s.pay_ext->'params'->>'base_rate') ~ " + _NUMERIC +
    " THEN (s.pay_ext->'params'->>'base_rate')::numeric END)"
)
# §DOCSFIX CB-437: an extension that names no currency is priced in this registry's own unit, as /a2a-payment/quote and
# the console read an absent currency (it was 'AVT', a unit no production frame uses). A SQL literal: the code comes from
# the frame's env and is used only when it is letters and digits.
from agentvault_registry.core.frame_currency import frame_currency as _frame_currency
_OWN_CCY_SQL = ("'" + _frame_currency() + "'") if re.fullmatch(r"[A-Z0-9]{1,16}", _frame_currency()) else "NULL"
# Both dialects are normalised into ONE object shape so no client ever learns
# there were two. `source` names which dialect answered, for the battery and for
# anyone debugging a card that prices itself in an unexpected place.
_SQL_PRICING_EFFECTIVE = (
    "CASE"
    " WHEN jsonb_typeof((s.card_data->'pricing')::jsonb) = 'object'"
    " AND ((s.card_data#>>'{pricing,base_rate}') IS NOT NULL"
    " OR COALESCE((s.card_data#>'{pricing,payment_required}')::text,'false') = 'true')"
    " THEN (s.card_data->'pricing')::jsonb || jsonb_build_object('source','pricing-block')"
    " WHEN (s.pay_ext->'params'->>'base_rate') IS NOT NULL"
    " THEN jsonb_build_object("
    "'model', COALESCE(s.pay_ext->'params'->>'pricing_model','per_request'),"
    "'currency', COALESCE(s.pay_ext->'params'->>'currency'," + _OWN_CCY_SQL + "),"
    "'base_rate', s.pay_ext->'params'->>'base_rate',"
    "'payment_required', COALESCE((s.pay_ext->>'required')::boolean, TRUE),"
    "'source', 'a2a-extension')"
    " ELSE NULL END"
)

# §V0640 (agentvault2-aa, 2026-10-25): WHO DISCOVERY LISTS, one rule for both discover routes: the console's
# /agent-cards/discover (the slim CTE below) and the mirrors of GET /discover (routers/agent_discovery.py, the route the
# MCP discoverAgents tool reads). GET /discover kept a copy of its own that took only cards with agent_did NULL, while
# every mirror federation_sync stores carries agent_did (uix_agent_cards_agent_did), so it listed no mirror at all (the
# pair proof nt261025x1: 146 mirrors on each operator, discoverAgents 0). `c` is the card row.
#   §DISCREFINE: unlisted cards leave the population entirely (page, facets AND tag counts all read the CTE, so a
#   hidden agent cannot leak through a count while being absent from the list). Admins pass :include_unlisted.
#   §REPBOND: under REPUTATION_BOND_MODE=enforce an unbonded provider leaves the population the same way.
#   §ENFPROP: under ENFORCEMENT_PROPAGATION_MODE=enforce a suspended/revoked agent (its own row, or its home's block
#   on a mirrored card) leaves the population the same way.
_CARD_POPULATION_TEMPLATE = (
    "c.is_active = TRUE AND c.agent_did IS NOT NULL"
    " AND (CAST(:include_unlisted AS boolean) OR c.unlisted = FALSE)"
    " AND (CAST(:include_unbonded AS boolean) OR @@CARD_IS_BONDED@@)"
    " AND (CAST(:include_enforced AS boolean) OR NOT @@CARD_IS_ENFORCED@@)"
)


def _render_card_population(template: str) -> str:
    out = template
    for token, sql in (("@@CARD_IS_BONDED@@", _rb.sql_card_is_bonded("c")),
                       ("@@CARD_IS_ENFORCED@@", _ep.sql_card_is_enforced("c"))):
        if token not in out:
            raise RuntimeError(f"the discovery population lost its {token} token")
        out = out.replace(token, sql)
    return out


CARD_POPULATION_SQL = _render_card_population(_CARD_POPULATION_TEMPLATE)


def card_population_params(viewer_is_admin: bool = False, include_unbonded: Optional[bool] = None) -> Dict[str, bool]:
    """The binds CARD_POPULATION_SQL reads, for one viewer. An admin sees unlisted cards (to moderate what the public
    cannot see; the console marks each such row) and, under enforce, may ask to see unbonded and enforced ones too. The
    public never does, and a caller that marks no row unlisted (GET /discover) asks as the public."""
    behind = bool(include_unbonded and viewer_is_admin)
    return {
        "include_unlisted": bool(viewer_is_admin),
        # §REPBOND: the population filter binds only under enforce; admins may look behind it.
        "include_unbonded": True if _rb.bond_mode() != "enforce" else behind,
        # §ENFPROP: the same admin override hides nothing from a moderator; the public never sees an enforced agent
        # under enforce.
        "include_enforced": True if _ep.propagation_mode() != "enforce" else behind,
    }


_DISCOVER_SLIM_CTE_TEMPLATE = """
WITH slim AS (
    SELECT DISTINCT ON (c.agent_did)
        c.id, c.agent_did, c.name, c.description, c.created_at, c.updated_at,
        c.developer_id,
        ((c.card_data#>>'{federation_metadata,source_registry}') IS NULL) AS is_local,
        CASE WHEN (c.card_data#>>'{federation_metadata,source_registry}') IS NULL THEN 'Local'
             ELSE COALESCE(NULLIF(c.card_data#>>'{federation_metadata,origin_registry_name}',''),'Federated')
        END AS origin,
        c.card_data,
        c.unlisted,
        @@PAY_EXT@@ AS pay_ext
    FROM agent_cards c
    -- who discovery lists: _CARD_POPULATION_TEMPLATE above, the rule GET /discover's mirrors pass too (V0640)
    WHERE @@CARD_POPULATION@@
      -- §REPBOND: the viewer's own "bonded only" filter (any mode).
      AND (NOT CAST(:bonded_only AS boolean) OR @@CARD_IS_BONDED@@)
    ORDER BY c.agent_did,
             ((c.card_data#>>'{federation_metadata,source_registry}') IS NULL) DESC,
             c.updated_at DESC
),
base AS (
    SELECT s.*,
        a.reputation_score,
        a.last_active_at,
        -- §REPBOND (2026-09-05): the bond travels with the row (local truth on the
        -- agents row; a federated mirror answers through its card's extension).
        a.reputation_bond_status,
        a.staked_balance,
        @@IS_BONDED@@ AS is_bonded,
        @@IS_ENFORCED@@ AS is_enforced,
        COALESCE(d.is_verified, FALSE) AS developer_verified,
        @@IS_PAID@@ AS is_paid,
        (a.last_active_at IS NOT NULL AND a.last_active_at > now() - interval '24 hours') AS is_live,
        @@SAFE_PRICE@@ AS safe_price,
        @@PRICING_EFFECTIVE@@ AS pricing_effective,
        -- §CHATCOHERE D5 — the registry's own last word on whether this agent
        -- answers. NULL means "never probed here", which is NOT "broken": a
        -- federated mirror is legitimately never probed locally (§RAT's law —
        -- never-observed and failing must not look the same).
        a.last_health AS last_health,
        a.last_health_at AS last_health_at
    FROM slim s
    LEFT JOIN agents a ON a.did = s.agent_did
    LEFT JOIN developers d ON d.id = s.developer_id
    WHERE (CAST(:q AS text) IS NULL
           OR s.name ILIKE CAST(:qpat_name AS text)
           OR COALESCE(s.description,'') ILIKE CAST(:qpat_desc AS text)
           OR COALESCE(s.card_data->>'tags','') ILIKE CAST(:qpat_tags AS text)
           -- 🔴 §DIDSEARCH (2026-09-01) — HIS REPORT: *"discovery doesnt take my dids i
           -- search in the searchbar."* Exactly right, and the search box had been
           -- PROMISING it: the placeholder reads "Search by name, tag, capability, or
           -- DID..." in all nine locales while the DID was the one thing this clause never
           -- looked at. MEASURED on registry-a: `Ironhand Victor` answers 200 at
           -- /agents/by-did, its NAME returns 59 results, and its own full DID returns 0.
           -- A search box that names a field it does not search is §DISCREFINE's blank
           -- promise in the most-used input on the page.
           -- ⚠ Safe for the WHOLE population, not just local agents: this CTE selects
           -- `WHERE c.agent_did IS NOT NULL`, so every row it can return — federated
           -- mirrors included — carries the column. A fix that reached only local agents
           -- would have been the worse outcome: it looks like it works.
           OR s.agent_did ILIKE CAST(:qpat_did AS text)
           -- 🔴 §CAPSEARCH (2026-09-01) — the placeholder's LAST unmet promise. It reads
           -- "Search by name, tag, capability, or DID..." and §DIDSEARCH closed the DID
           -- half; `capability` was still matched by nothing. MEASURED on frame-c: the
           -- eleven paid service agents carry real capability text in `skills[]` ("Current
           -- conditions and forecast", "DNS records and TLS certificate check"), and their
           -- DESCRIPTIONS already carry most of it — which is why 5 of 7 sample phrases
           -- already worked. The gap this closes is the SYNONYM: the description says
           -- "cryptocurrency price tracker" while the skill says "crypto prices"; the
           -- description says "SSL certificate" while the skill says "TLS certificate".
           -- Both returned 0 rows before this clause and 1 after.
           -- ⚠ NEVER `card_data->>'skills'` — that renders the whole array as text
           -- INCLUDING its keys, so ILIKE '%name%' or '%description%' would match every
           -- card on the registry. Match the VALUES of the elements, nothing else.
           -- ⚠ `skills` is NOT reliably an array: measured 12,122 JSON-null, 41 absent,
           -- 3,089 real arrays out of 15,252 active cards. jsonb_array_elements() ERRORS
           -- on a scalar and Postgres does not guarantee a type guard evaluates first,
           -- so the CASE substitutes an empty array rather than relying on ordering.
           -- 🔴 §JSONCAST (2026-09-05): `card_data` is `json` (not jsonb) on the four older
           -- Frame-A operators (berlin/paris/washington/london; qatest16 and every mainframe are
           -- jsonb). Postgres resolves function types for the WHOLE statement at parse time, so an
           -- uncast `jsonb_typeof(json)` made discover answer 500 on those four nodes from the day
           -- this clause reached them (V0213) — even with no `q`, even though the branch is never
           -- taken. Cast, like every sibling call. Gate: tests/test_discover_sql_json_columns.py.
           OR EXISTS (
                SELECT 1 FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof((s.card_data->'skills')::jsonb) = 'array'
                         THEN (s.card_data->'skills')::jsonb ELSE '[]'::jsonb END) sk
                WHERE COALESCE(sk->>'name','')        ILIKE CAST(:qpat_skill AS text)
                   OR COALESCE(sk->>'description','') ILIKE CAST(:qpat_skill AS text)))
      AND (CAST(:tag AS text) IS NULL
           OR (jsonb_typeof((s.card_data->'tags')::jsonb) = 'array'
               AND jsonb_exists((s.card_data->'tags')::jsonb, CAST(:tag_member AS text))))
      AND (CAST(:verified_only AS boolean) = FALSE OR COALESCE(d.is_verified, FALSE))
      AND (CAST(:active_24h AS boolean) = FALSE
           OR (a.last_active_at IS NOT NULL AND a.last_active_at > now() - interval '24 hours'))
      AND (CAST(:pricing AS text) IS NULL
           OR (CAST(:pricing_paid AS text) = 'paid' AND @@IS_PAID@@)
           OR (CAST(:pricing_free AS text) = 'free' AND NOT @@IS_PAID@@))
      -- §CHATCOHERE D5 (2026-09-01) — "answerable": what this registry is willing
      -- to put in front of someone who has never used it. TWO halves, both honest:
      --   1. the card has DESCRIBED ITSELF — it is not still wearing the pull-sync
      --      stub the registry minted on its behalf. An agent that has never said
      --      what it does cannot be a meaningful first choice.
      --   2. no health probe has come back UNREACHABLE. NULL is kept, deliberately:
      --      "never probed here" is not "broken" (§RAT), and every federated mirror
      --      is legitimately NULL.
      -- Default FALSE ⇒ discovery's population is byte-identical unless asked.
      AND (CAST(:answerable_only AS boolean) = FALSE
           OR (COALESCE(NULLIF(TRIM(s.description), ''), '') <> ''
               AND s.description <> CAST(:stub_description AS text)
               AND COALESCE(a.last_health, '') <> 'unreachable'))
      AND (CAST(:encircled_only AS boolean) = FALSE
           OR a.bears_encirclement_flare IS TRUE
           OR a.flare_tier = 'sovereign'
           OR a.flare_encirclement_variant IS NOT NULL
           OR (s.card_data->'flare'->>'bears_encirclement_flare') = 'true'
           OR (s.card_data->'flare'->>'selected_encirclement_flare') IS NOT NULL
           OR (s.card_data->'flare'->>'encirclement_variant') IS NOT NULL)
)
"""


def _render_discover_cte(template: str) -> str:
    """Substitute the price-rule SQL into the template, asserting every token.

    A patch that does not assert each replacement lies (§BRIDGE R11): a renamed
    token would leave `@@IS_PAID@@` sitting in a statement that then fails at
    QUERY time, on a public endpoint, instead of at import. Fail here instead.
    """
    subs = {
        "@@PAY_EXT@@": _PAY_EXT_SQL,
        "@@IS_PAID@@": _SQL_IS_PAID,
        "@@SAFE_PRICE@@": _SQL_SAFE_PRICE,
        "@@PRICING_EFFECTIVE@@": _SQL_PRICING_EFFECTIVE,
    }
    out = template
    for token, sql in subs.items():
        if token not in out:
            raise RuntimeError(f"discover CTE template lost its {token} token")
        out = out.replace(token, sql)
    # V0640: the population (who discovery lists) is ONE rule, the one GET /discover's mirrors pass; it carries the
    # card-level bond and enforcement tokens, which the loop below then substitutes.
    if "@@CARD_POPULATION@@" in out:
        out = out.replace("@@CARD_POPULATION@@", _CARD_POPULATION_TEMPLATE)
    # §REPBOND — ONE rule for "bonded", owned by services/reputation_bond.py. These two
    # tokens live in the discover CTE only; the renderer is shared with a second template
    # that never carried them (measured 2026-09-05: asserting them there killed every
    # worker at import on both sandbox frames), so they substitute WHERE PRESENT.
    for token, sql in (("@@IS_BONDED@@", _rb.sql_is_bonded("a", "s")),
                       ("@@CARD_IS_BONDED@@", _rb.sql_card_is_bonded("c")),
                       ("@@IS_ENFORCED@@", _ep.sql_is_enforced("a", "s")),
                       ("@@CARD_IS_ENFORCED@@", _ep.sql_card_is_enforced("c"))):
        if token in out:
            out = out.replace(token, sql)
    if "@@" in out:
        raise RuntimeError("discover CTE still carries an unsubstituted @@token@@")
    return out


_DISCOVER_SLIM_CTE = _render_discover_cte(_DISCOVER_SLIM_CTE_TEMPLATE)

# §MCPTEST30 V0614 (2026-10-14) — the facet and tag sets as SELECT bodies over `base`: the page statement carries them
# as CTEs (one statement, one snapshot), and an empty page, which has no row to carry them, reads them with this same text.
_DISCOVER_FACET_SELECT = """
    SELECT origin, COUNT(*) AS count,
           COUNT(*) FILTER (WHERE is_live) AS live_24h,
           COUNT(*) FILTER (WHERE is_paid) AS paid
    FROM base
    GROUP BY GROUPING SETS ((origin), ())
"""
_DISCOVER_TAG_SELECT = """
    SELECT tg.tag AS tag, COUNT(*) AS count
    FROM base b,
         LATERAL jsonb_array_elements_text(
             -- same json/jsonb caveat as _PAY_EXT_SQL above
             CASE WHEN jsonb_typeof((b.card_data->'tags')::jsonb) = 'array'
                  THEN (b.card_data->'tags')::jsonb ELSE '[]'::jsonb END
         ) AS tg(tag)
    GROUP BY tg.tag
    ORDER BY count DESC, tg.tag
    LIMIT 24
"""


def _json_list(v) -> list:
    """A jsonb aggregate as a list of dicts: asyncpg decodes jsonb, a str is parsed, anything else reads empty."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


# ── §BUYSERVICE (2026-08-24): the SAME price rule, asked about ONE card ──────
# The buy/quote rails need the effective price of a single agent. Re-deriving the
# dual-dialect rule in Python would make a THIRD copy (SQL here, cardPricing.ts on
# the FE) and copies drift — that is how SYBIL came to be listed Free while its A2A
# extension charged 5 AVT. So this reuses the identical constants against a one-row
# CTE that reproduces the `s.` alias they are written for: a quote can never disagree
# with what Discover shows, because it is not a second opinion.
_ONE_CARD_PRICING_SQL = _render_discover_cte(
    "WITH s AS ("
    "  SELECT c.card_data AS card_data, @@PAY_EXT@@ AS pay_ext"
    "  FROM agent_cards c"
    "  WHERE c.agent_did = :did AND c.is_active = TRUE"
    "  LIMIT 1"
    ") "
    "SELECT @@PRICING_EFFECTIVE@@ AS pricing,"
    "       @@IS_PAID@@ AS is_paid,"
    "       @@SAFE_PRICE@@ AS safe_price,"
    # §BATCH4 (2026-09-05): a card declares its A2A endpoint in one of TWO legal places — legacy top-level `url`,
    # or A2A v1.0 `supportedInterfaces[0].url` (the pull-sync's _well_known_url_for reads the same field). The buy
    # rail read only the legacy one, so every v1.0-shaped card (SYBIL) was "no A2A endpoint to call".
    "       COALESCE(NULLIF(s.card_data->>'url',''), s.card_data->'supportedInterfaces'->0->>'url') AS endpoint_url,"
    "       s.card_data->>'name' AS name "
    "FROM s"
)


async def effective_pricing_for_did(db, did: str) -> Optional[dict]:
    """Effective price + A2A endpoint for one agent, or None when no active card.

    Returns {pricing, is_paid, safe_price, endpoint_url, name}; `pricing` is the
    normalised object (with its `source`) or None for a genuinely free card.
    """
    from sqlalchemy import text as _sa_text

    row = (await db.execute(_sa_text(_ONE_CARD_PRICING_SQL), {"did": did})).mappings().first()
    if not row:
        return None
    return {
        "pricing": row["pricing"],
        "is_paid": bool(row["is_paid"]),
        "safe_price": row["safe_price"],
        "endpoint_url": row["endpoint_url"],
        "name": row["name"],
    }

# §DIRFEED-2 (2026-10-08, the nightly pair nt261008): every sort ends on the card id, the one unique column. A fresh
# frame's agents tie on liveness, reputation, price and even created_at (one transaction stamps a whole seed), and
# LIMIT/OFFSET pages over a tie are not a partition: the tester's two pages of 3 held rows its page of 6 did not.
_DISCOVER_SORTS = {
    # default browse (no query): live agents first, then reputation, paid, newest —
    # surfaces real working agents instead of the newest forge spawn.
    "relevance": "ORDER BY is_live DESC, COALESCE(reputation_score,0) DESC, is_paid DESC, created_at DESC, id DESC",
    "newest": "ORDER BY created_at DESC, id DESC",
    "reputation": "ORDER BY COALESCE(reputation_score,-1) DESC, created_at DESC, id DESC",
    "price_low": "ORDER BY safe_price ASC NULLS LAST, created_at DESC, id DESC",
    "price_high": "ORDER BY safe_price DESC NULLS LAST, created_at DESC, id DESC",
}
# relevance WITH a query ranks exact > prefix > substring, then reputation.
_DISCOVER_SORT_RELEVANCE_Q = (
    # §CAPSEARCH: tier 3 keeps the feature STRICTLY ADDITIVE. A row that matched only a
    # skill sorts below every row that matched name/description/tags/DID, so widening the
    # WHERE cannot displace a result that was already on the page. PROVEN on frame-c before
    # the code changed: for q="chat" the six pre-existing results come back as #1-#6 in the
    # same order, and the 101 newly-reachable agents begin at #7. (Most of those 101 are
    # forge fixtures using "chat" as a skill name — a property of this dev network, not of
    # the design, and precisely why they are tiered rather than interleaved.)
    "ORDER BY (CASE WHEN LOWER(name) = CAST(:qlow AS text) THEN 0 "
    "WHEN name ILIKE CAST(:qpre AS text) THEN 1 "
    "WHEN name ILIKE CAST(:qpat_name AS text) "
    "  OR COALESCE(description,'') ILIKE CAST(:qpat_desc AS text) "
    "  OR COALESCE(card_data->>'tags','') ILIKE CAST(:qpat_tags AS text) "
    "  OR agent_did ILIKE CAST(:qpat_did AS text) THEN 2 "
    "ELSE 3 END), "
    "COALESCE(reputation_score,0) DESC, created_at DESC, id DESC"
)


@router.get(
    "/discover",
    summary="Discovery search (server-side, faceted)",
    description="Fast faceted agent search for the Discovery view: DID-deduped, "
                "origin/pricing/tag filters, reputation + liveness joined for "
                "local agents, per-origin facet counts. Public.",
)
async def discover_agent_cards(
    db: AsyncSession = Depends(database.get_db),
    q: Optional[str] = Query(None, max_length=100, description="Search name / description / tags."),
    origins: Optional[str] = Query(None, max_length=600, description="Comma-separated origin names; 'local' = this registry."),
    pricing: Optional[str] = Query(None, pattern="^(free|paid)$"),
    tag: Optional[str] = Query(None, max_length=60, description="Exact tag membership filter."),
    verified_only: bool = Query(False),
    active_24h: bool = Query(False, description="Only agents seen alive in the last 24h (local liveness)."),
    encircled_only: bool = Query(False, description="Only agents bearing an encirclement flare (the Distinguished showcase)."),
    foreign_only: bool = Query(False, description="Only agents whose home frame settles in a different currency."),
    answerable_only: bool = Query(
        False,
        description="Only agents this registry can offer as a first move: the card has "
                    "actually described itself (it is not still wearing the pull-sync "
                    "stub) and no health probe has come back unreachable. Default FALSE "
                    "— discovery's population is unchanged unless a caller asks."),
    bonded_only: bool = Query(False, description="§REPBOND: only agents holding a reputation bond."),
    include_unbonded: Optional[bool] = Query(
        None,
        description="§REPBOND: only meaningful under REPUTATION_BOND_MODE=enforce, where unbonded "
                    "providers leave the population; an admin viewer may pass true to see them."),
    sort: str = Query("relevance", pattern="^(relevance|newest|reputation|price_low|price_high|proven)$"),
    limit: int = Query(30, ge=1, le=120),
    offset: int = Query(0, ge=0),
    viewer: Optional[models.Developer] = Depends(get_current_developer_optional),
):
    t_start = time.monotonic()
    # §DISCREFINE: discovery stays PUBLIC — the optional dependency never 401s, it
    # only tells us whether the caller is an admin. Admins see unlisted agents so
    # they can moderate what the public cannot see; every row carries `unlisted`
    # so the UI can mark them as hidden-from-others rather than passing them off
    # as normal listings.
    viewer_is_admin = viewer is not None and admin_credential(viewer)   # D6-821: on this credential
    _bond_mode = _rb.bond_mode()
    q_norm = (q or "").strip() or None
    qpat = f"%{q_norm}%" if q_norm else None
    tag_norm = (tag or "").strip() or None
    pricing_norm = pricing if pricing in ("free", "paid") else None
    # §DISCECHO (2026-09-07) — say what actually ran. FastAPI silently drops a query parameter an
    # endpoint does not declare, so a caller who guesses wrong gets a 200 and a full first page with no
    # signal: agentvault2-eb measured `?skip=4` on THIS route returning the same four rows as `?skip=0`,
    # forever, because the page parameter here is `offset`. The index feed already answers this with
    # `applied_filters` (§DIRFEED) and discover — the more public of the two, the one the landing preview
    # and /explore both read — had no echo at all. Names the paging and the filters that shaped the page;
    # null means "not asked", which is why it is built from the normalised values rather than the raw ones.
    applied_filters = {
        "q": q_norm,
        "origins": (origins or "").strip() or None,
        "pricing": pricing_norm,
        "tag": tag_norm,
        "verified_only": bool(verified_only) or None,
        "active_24h": bool(active_24h) or None,
        "encircled_only": bool(encircled_only) or None,
        "foreign_only": bool(foreign_only) or None,
        "answerable_only": bool(answerable_only) or None,
        "bonded_only": bool(bonded_only) or None,
        "include_unbonded": None,     # set below to the value that BINDS (§TWOAGENT #8)
        "sort": sort,
        "limit": limit,
        "offset": offset,
    }
    base_params = {
        "q": q_norm,
        "qpat_name": qpat, "qpat_desc": qpat, "qpat_tags": qpat, "qpat_did": qpat,
        "qpat_skill": qpat,  # §CAPSEARCH
        "tag": tag_norm, "tag_member": tag_norm,
        "verified_only": bool(verified_only),
        "active_24h": bool(active_24h),
        "encircled_only": bool(encircled_only),
        "answerable_only": bool(answerable_only),
        "stub_description": STUB_CARD_DESCRIPTION,
        "pricing": pricing_norm, "pricing_paid": pricing_norm, "pricing_free": pricing_norm,
        # who discovery lists (include_unlisted, include_unbonded, include_enforced): the one rule (V0640)
        **card_population_params(viewer_is_admin, include_unbonded),
        "bonded_only": bool(bonded_only),
    }
    # §TWOAGENT #8 (2026-09-23): the echo carried the RAW request value, so a non-admin under
    # REPUTATION_BOND_MODE=enforce who sent include_unbonded=true read `applied_filters.include_unbonded: true`
    # over a page the filter never widened (it binds for admins only). Echo what bound; null = not asked.
    if include_unbonded is not None:
        applied_filters["include_unbonded"] = bool(base_params["include_unbonded"])

    # Peer name → (settlement currency, trust domain) from the cached signed
    # registry cards — enriches federated items whose card_data lacks the fees
    # block, and defines the foreign_only origin set (same source of truth as
    # the legacy _list_focused_subset).
    _local_ccy = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
    peer_ccy_map: Dict[str, tuple] = {}
    try:
        for p in (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE"))).scalars().all():
            c = getattr(p, "cached_registry_card", None)
            if isinstance(c, dict) and isinstance(c.get("fees"), dict):
                s = c["fees"].get("settlement_currency")
                # keyed LOWER — peer_registries stores display case while origin
                # stamps drift (the §PEERFIX class); every lookup below lowers too.
                if isinstance(s, str) and s.strip() and p.name and p.name.lower() not in peer_ccy_map:
                    peer_ccy_map[p.name.lower()] = (s.strip().upper(), getattr(p, "trust_domain", None))
    except Exception:
        peer_ccy_map = {}
    foreign_origins = [name for name, (ccy, _td) in peer_ccy_map.items() if ccy and ccy != _local_ccy]

    origin_list = [o.strip().lower() for o in (origins or "").split(",") if o.strip()]
    if foreign_only:
        if not foreign_origins:
            return {"items": [], "total": 0, "has_more": False,
                    "facets": {"total": 0, "live_24h": 0, "paid": 0, "free": 0, "origins": [], "tags": []},
                    "applied_filters": applied_filters,
                    "generated_in_ms": round((time.monotonic() - t_start) * 1000, 1)}
        origin_list = [o for o in origin_list if o in foreign_origins] if origin_list else foreign_origins
    origin_clause = ""
    if origin_list:
        origin_clause = "WHERE LOWER(origin) IN :origin_list"

    sort_sql = _DISCOVER_SORTS.get(sort, _DISCOVER_SORTS["relevance"])
    sort_params: dict = {}
    if sort == "relevance" and q_norm:
        sort_sql = _DISCOVER_SORT_RELEVANCE_Q
        sort_params = {"qlow": q_norm.lower(), "qpre": f"{q_norm}%"}

    # §AGENTDISC #191 — proof-weighted ranking. Scores come from the SAME grouped
    # aggregation the Proven-work band renders (services/track_record: ONE source of
    # truth), so the why-ranked-here explanation can never drift from the order.
    # History-bearing DIDs are few (bounded CASE, capped 50); EigenTrust reputation
    # rides as the SQL-side tiebreak layer per PROOF_WEIGHTS.reputation_percent.
    ranking_meta = None
    if sort == "proven":
        _scores: Dict[str, float] = {}
        try:
            from agentvault_registry.services.track_record import (
                PROOF_FORMULA, PROOF_WEIGHTS, track_record_scores)
            _scores = await track_record_scores(db)
        except Exception as pr_e:  # noqa: BLE001 — ranking must never break discovery
            logger.warning(f"discover proven-sort scoring failed: {pr_e}")
        if _scores:
            _cases = []
            for _i, (_d, _s) in enumerate(_scores.items()):
                _cases.append(f"WHEN :prd{_i} THEN CAST(:prs{_i} AS float)")
                sort_params[f"prd{_i}"] = _d
                sort_params[f"prs{_i}"] = float(_s)
            _score_case = "CASE agent_did " + " ".join(_cases) + " ELSE 0 END"
            sort_sql = (
                f"ORDER BY (({_score_case}) + 0.01*LEAST(COALESCE(reputation_score,0),100)) DESC, "
                "is_live DESC, COALESCE(reputation_score,0) DESC, created_at DESC, id DESC"
            )
        else:
            sort_sql = _DISCOVER_SORTS["relevance"]
        try:
            ranking_meta = {"sort": "proven", "weights": PROOF_WEIGHTS,
                            "formula": PROOF_FORMULA, "scored_agents": len(_scores)}
        except Exception:  # noqa: BLE001
            ranking_meta = {"sort": "proven", "scored_agents": len(_scores)}

    try:
        # ── Query 1: page + total + facets + top tags, in ONE statement ───
        # §MCPTEST30 V0614 (2026-10-14) — one statement reads one snapshot. The total, the facets and the tags were
        # three statements under READ COMMITTED, so cards landing between them made one answer carry a total and a
        # facet total that disagree: the federation suite's discovery_ranked_page_is_public_and_partitions read
        # facets 6542 against total 6544 while the V0613 round's own lifecycles created agents, and the 10-13
        # nightly 6473 against 6472. The facet and tag sets now ride as two scalar subqueries over the same `base`
        # (computed once, where it was computed three times). An empty page has no row to carry them, so it reads
        # them on its own below.
        # §REPBOND — a bonded provider ranks first (shadow and enforce; off = untouched).
        if _bond_mode != "off" and sort in ("relevance", "proven"):
            sort_sql = sort_sql.replace("ORDER BY ", "ORDER BY is_bonded DESC, ", 1)
        page_sql = text(
            _DISCOVER_SLIM_CTE
            + f"""
            , facet AS ({_DISCOVER_FACET_SELECT}
            ), tagc AS ({_DISCOVER_TAG_SELECT}
            )
            SELECT id, agent_did, name, description, created_at, updated_at,
                   developer_id, is_local, origin, reputation_score, last_active_at,
                   developer_verified, is_paid, is_live, unlisted,
                   -- §CARDLINK (2026-09-08) — A COLUMN LIVES IN THREE PLACES HERE, NOT TWO.
                   -- The slim CTE selects it, THIS projection has to carry it out of `base`, and
                   -- the payload dict below has to name it. I did the CTE and the payload and
                   -- missed this line: `/agent-cards/discover` answered 500 with
                   -- `NoSuchColumnError: last_health` on EU until the roll's public-rail smoke
                   -- refused (§DISCECHO — /health was 200 the whole time). §EXCISION-10's
                   -- field-by-field-mapper class, one layer further out.
                   last_health, last_health_at,
                   is_bonded, reputation_bond_status, staked_balance, card_data, is_enforced,
                   card_data->>'humanReadableId' AS human_readable_id,
                   card_data->>'did'             AS card_did,
                   card_data->'tags'             AS tags,
                   pricing_effective             AS pricing,
                   card_data->>'iconUrl'         AS icon_url,
                   card_data->'flare'            AS flare,
                   card_data#>>'{{fees,settlement_currency}}'          AS fee_ccy,
                   COALESCE(card_data#>>'{{pricing,currency}}',
                            pay_ext->'params'->>'currency')            AS pricing_ccy,
                   card_data#>>'{{federation_metadata,source_registry}}' AS source_registry,
                   COUNT(*) OVER () AS full_total,
                   (SELECT COALESCE(jsonb_agg(jsonb_build_object('origin', f.origin, 'count', f.count,
                                                                 'live_24h', f.live_24h, 'paid', f.paid)
                                              ORDER BY f.count DESC), '[]'::jsonb)
                      FROM facet f)                                  AS facets_json,
                   (SELECT COALESCE(jsonb_agg(jsonb_build_object('tag', t.tag, 'count', t.count)
                                              ORDER BY t.count DESC, t.tag), '[]'::jsonb)
                      FROM tagc t)                                   AS tags_json
            FROM base
            {origin_clause}
            {sort_sql}
            LIMIT :page_limit OFFSET :page_offset
            """
        )
        if origin_list:
            page_sql = page_sql.bindparams(bindparam("origin_list", expanding=True))
        page_rows = (await db.execute(page_sql, {
            **base_params, **sort_params,
            **({"origin_list": origin_list} if origin_list else {}),
            "page_limit": limit, "page_offset": offset,
        })).mappings().all()

        if page_rows:
            # the facets over the origin-UNfiltered set and the top tags, from the page's own snapshot
            facet_rows = _json_list(page_rows[0]["facets_json"])
            tag_rows = _json_list(page_rows[0]["tags_json"])
        else:
            # an empty page carries no row: the facets and the tags in two statements of their own, as before V0614
            facet_rows = (await db.execute(text(_DISCOVER_SLIM_CTE + _DISCOVER_FACET_SELECT + "    ORDER BY count DESC\n"),
                                           dict(base_params))).mappings().all()
            tag_rows = (await db.execute(text(_DISCOVER_SLIM_CTE + _DISCOVER_TAG_SELECT),
                                         dict(base_params))).mappings().all()
    except Exception:
        logger.exception("discover_agent_cards query failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Discovery search failed.",
        )

    # ── Local flare sidecars for the page (response-time, like the list path;
    #    federated rows already carry persisted card_data.flare selected above).
    flare_by_did: dict[str, dict] = {}
    local_dids = [r["agent_did"] for r in page_rows if r["is_local"] and r["agent_did"] and not r["flare"]]
    if local_dids:
        try:
            from agentvault_registry.routers.federation_sync import _build_flare_sidecar
            agent_rows = (await db.execute(
                select(models.Agent).where(models.Agent.did.in_(local_dids))
            )).scalars().all()
            dev_ids = {r["developer_id"] for r in page_rows if r["is_local"] and r["developer_id"]}
            dev_rows = (await db.execute(
                select(models.Developer).where(models.Developer.id.in_(list(dev_ids)))
            )).scalars().all() if dev_ids else []
            dev_by_id = {d.id: d for d in dev_rows}
            dev_for_did = {r["agent_did"]: dev_by_id.get(r["developer_id"]) for r in page_rows if r["is_local"]}
            _local_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
            our_spiffe = f"spiffe://{_local_domain}/ns/agentvault/sa/registry-main"
            for agent_row in agent_rows:
                # The agent row is already loaded, so a dev-tier guard here buys nothing and
                # costs the sovereigns their rings (§COSMETICS-ORIGIN; findings row 169).
                # `dev` may be None — the builder is None-safe on both sides.
                dev = dev_for_did.get(agent_row.did)
                sidecar = await _build_flare_sidecar(agent_row, dev, our_spiffe)
                if sidecar:
                    flare_by_did[agent_row.did] = sidecar
        except Exception as flare_e:  # noqa: BLE001 — flare must never break discovery
            logger.warning(f"discover flare injection failed: {flare_e}")

    _local_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")

    # §REPBOND — the `reputation` block per row (bond state + maturity progress + volume
    # for local agents; the mirrored card's signed extension for federated ones). Three
    # batch queries for the page; must never break discovery.
    rep_by_did: Dict[str, dict] = {}
    try:
        _rep_rows = [{
            "agent_did": r["agent_did"], "is_federated": not bool(r["is_local"]),
            "card_data": r["card_data"], "staked_balance": r["staked_balance"],
            "settlement_currency": r["fee_ccy"], "origin": r["origin"],
        } for r in page_rows if r["agent_did"]]
        rep_by_did = await _rb.reputation_blocks(db, _rep_rows)
    except Exception as _rb_e:  # noqa: BLE001
        logger.error(f"[REPBOND] discovery reputation blocks failed: {_rb_e}")
        rep_by_did = {}
    # §AGENTDISC #188 — registry-attested track-record enrichment: ONE grouped pass
    # over both guild books for the page's DIDs (no N+1). Rides the registry-owned
    # channel like `flare` — never agent card_data. Must never break discovery.
    tr_by_did: Dict[str, dict] = {}
    try:
        # §MARKSURFACES (2026-09-10) — this projection USED to be built inline here, and
        # that was why only this endpoint could show a mark. It now lives in
        # `services/track_record.compact_track_record`, which every avatar-bearing
        # enrichment endpoint reads, so the ring on Discovery and the ring on the
        # Leaderboard are the same fact assembled by the same code.
        from agentvault_registry.services.track_record import (
            compact_track_records, compact_from_card)
        _page_dids = [r["agent_did"] for r in page_rows if r["agent_did"]]
        tr_by_did = await compact_track_records(db, _page_dids)
        # §TRAVELREC (2026-09-11) — the local guild book only knows work done HERE, so a mirrored
        # card rendered no record at all: a peer saw a bonded, certified agent with no evidence of
        # the work that earned either. The origin registry now states the summary on the card it
        # signs, so read it back for any row the local book does not cover. It is the ORIGIN's
        # claim, carried as `attested` with a `verify_at` pointing at the home attestation, and it
        # never overwrites a record this frame computed itself.
        for _r in page_rows:
            _d = _r["agent_did"]
            if not _d or tr_by_did.get(_d):
                continue
            # ⚠ `card_data` is ALREADY a dict here (asyncpg decodes jsonb), and `_jsonb` is
            # defined further down this function — reading it from up here raised
            # UnboundLocalError on every call, which the except below logged as a warning and
            # swallowed. §DISCECHO's ordering class: a block placed above what it reads, made
            # invisible by a handler that keeps the endpoint alive. The endpoint answered 200
            # and the feature simply did not exist.
            _cd = _r["card_data"] if "card_data" in _r.keys() else None
            _att = compact_from_card(_cd if isinstance(_cd, dict) else None)
            if _att:
                tr_by_did[_d] = _att
    except Exception as tr_e:  # noqa: BLE001 — attestation must never break discovery
        logger.warning(f"discover track-record enrichment failed: {tr_e}")

    def _spiffe_host(spiffe: Optional[str]) -> Optional[str]:
        if not isinstance(spiffe, str):
            return None
        m = re.match(r"^spiffe://([^/]+)", spiffe)
        return m.group(1) if m else None

    def _jsonb(v):
        if v is None or isinstance(v, (dict, list)):
            return v
        try:
            return json.loads(v)
        except Exception:
            return None

    items = []
    for r in page_rows:
        flare = _jsonb(r["flare"]) or flare_by_did.get(r["agent_did"])
        items.append({
            "id": str(r["id"]),
            "agent_did": r["agent_did"],
            "did": r["card_did"] or r["agent_did"],
            "name": r["name"],
            "description": r["description"] or "",
            "human_readable_id": r["human_readable_id"],
            "origin_registry_name": r["origin"],
            "is_local": bool(r["is_local"]),
            "is_active": True,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "reputation_score": float(r["reputation_score"]) if r["reputation_score"] is not None else None,
            "last_active_at": r["last_active_at"].isoformat() if r["last_active_at"] else None,
            "is_live": bool(r["is_live"]),
            # §CARDLINK (2026-09-08) — WHETHER THE PUBLISHED ADDRESS ANSWERS, so a reader is
            # never handed an endpoint to call that is not there. His report: *"dont provide a
            # link for them that is dead."* This column was already selected and used in a
            # WHERE clause, and never reached the payload, so no surface could act on it.
            # ⚠ THREE STATES, and NULL is the one that matters: `null` means never probed here
            # (a federated mirror legitimately never is), which is NOT "broken" — §RAT's law
            # that never-observed and failing must not look the same. `is_live` is NOT this
            # fact: it is `last_active_at` within 24h, i.e. account activity, and it read True
            # for every one of the thirty agents whose address answered 404.
            "endpoint_health": r["last_health"] or None,
            "endpoint_checked_at": r["last_health_at"].isoformat() if r["last_health_at"] else None,
            "is_paid": bool(r["is_paid"]),
            # Only ever TRUE for an admin viewer: everyone else had these rows
            # filtered out of the population upstream, counts included.
            "unlisted": bool(r["unlisted"]),
            "developer_is_verified": bool(r["developer_verified"]),
            "tags": _jsonb(r["tags"]) or [],
            "pricing": _jsonb(r["pricing"]),
            "icon_url": r["icon_url"],
            "flare": flare,
            "track_record": tr_by_did.get(r["agent_did"]),
            # §REPBOND
            "is_bonded": bool(r["is_bonded"]),
            "is_enforced": bool(r["is_enforced"]),
            "reputation": rep_by_did.get(r["agent_did"]),
            "settlement_currency": (
                (_local_ccy if r["is_local"] else None)
                or (peer_ccy_map.get((r["origin"] or "").lower()) or (None,))[0]
                or r["fee_ccy"] or r["pricing_ccy"]
            ),
            "trust_domain": (
                _local_td if r["is_local"]
                else ((peer_ccy_map.get((r["origin"] or "").lower()) or (None, None))[1]
                      or _spiffe_host(r["source_registry"]))
            ),
        })

    total = int(page_rows[0]["full_total"]) if page_rows else 0
    origins_out = []
    facet_total = {"count": 0, "live_24h": 0, "paid": 0}
    for fr in facet_rows:
        if fr["origin"] is None:  # the () grouping-set row = grand totals
            facet_total = {"count": int(fr["count"]), "live_24h": int(fr["live_24h"]), "paid": int(fr["paid"])}
        else:
            origins_out.append({
                "name": fr["origin"],
                "count": int(fr["count"]),
                "live_24h": int(fr["live_24h"]),
                "paid": int(fr["paid"]),
            })

    return {
        "items": items,
        "total": total,
        "has_more": offset + len(items) < total,
        "ranking": ranking_meta,
        "facets": {
            "total": facet_total["count"],
            "live_24h": facet_total["live_24h"],
            "paid": facet_total["paid"],
            "free": facet_total["count"] - facet_total["paid"],
            "origins": origins_out,
            "tags": [{"name": tr["tag"], "count": int(tr["count"])} for tr in tag_rows],
        },
        "applied_filters": applied_filters,
        "generated_in_ms": round((time.monotonic() - t_start) * 1000, 1),
    }


# §BATCH9 (2026-09-06, eb's finding): registered BEFORE the /{card_id} route — FastAPI registration order beats path
# specificity, and card_id was widened to str, so the literal "by-hri" matched /{card_id} and this route could never be
# reached (its MCP tool theprotocol_getAgentCardByHRI 404'd for every input on every node). Same class as line ~792 and the
# /notifications/{id:int} vs /notifications/catalog case: literal routes first.
# --- NEW: Alternative endpoint that uses query parameter instead of path parameter ---
@router.get(
    "/by-hri",
    response_model=schemas.AgentCardRead,
    summary="Get Agent Card by Human-Readable ID (Query Parameter)",
    description="Alternative endpoint to retrieve an agent card by HRI using a query parameter.",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Agent Cards"
)
async def get_agent_card_by_hri_query(
    hri: str = Query(..., description="The humanReadableId of the agent to retrieve"),
    db: AsyncSession = Depends(database.get_db),
) -> schemas.AgentCardRead:
    """
    Alternative endpoint to retrieve a specific Agent Card by its humanReadableId using a query parameter.
    This avoids potential issues with URL path parameters containing slashes.
    """
    logger.info(f"get_agent_card_by_hri_query called with HRI: '{hri}'")

    db_card = await agent_card.get_agent_card_by_human_readable_id(db=db, human_readable_id=hri)
    
    if db_card is None:
        logger.error(f"⚠️ Agent card with humanReadableId '{hri}' not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Agent Card with humanReadableId '{hri}' not found"
        )
    
    logger.info(f"✓ Successfully found agent card: {db_card.name} (ID: {db_card.id})")

    response_dict = _build_agent_card_read_dict(
        db_card, health=await _health_for(db, getattr(db_card, "agent_did", None)))
    await _state_home_extensions(db, response_dict, db_card)
    await _inject_flare_into_card_data(db, response_dict, db_card)
    return schemas.AgentCardRead.model_validate(response_dict)


# --- Helper: Resolve Agent from DID (agents table) then find AgentCard via developer_id ---


# --- GET /agent-cards/{card_id} ---
@router.get(
    "/{card_id}",
    response_model=schemas.AgentCardRead,
    summary="Get Agent Card by ID",
    description="Retrieves the details of a specific Agent Card by its UUID, DID, or integer ID.",
)
async def get_agent_card(
    card_id: str,  # Changed from uuid.UUID to str to accept multiple formats
    # Dependency after path param
    db: AsyncSession = Depends(database.get_db),
) -> schemas.AgentCardRead:
    """
    Public endpoint to retrieve a specific Agent Card by its ID.
    Supports multiple ID formats:
    - UUID (e.g., "123e4567-e89b-12d3-a456-426614174000")
    - DID (e.g., "did:cos:example-agent")
    - Integer ID (e.g., "65")
    """
    logger.info(f"Fetching agent card with ID: {card_id}")
    
    # Use the unified multi-format resolver (UUID, DID via agents table, integer ID, humanReadableId)
    db_card = await _resolve_agent_card(db=db, card_id=card_id)
    
    if db_card is None:
        logger.warning(f"Agent card with ID {card_id} not found (tried UUID, DID, integer ID, humanReadableId).")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Card not found")

    response_dict = _build_agent_card_read_dict(
        db_card, health=await _health_for(db, getattr(db_card, "agent_did", None)))
    await _state_home_extensions(db, response_dict, db_card)
    await _inject_flare_into_card_data(db, response_dict, db_card)
    return schemas.AgentCardRead.model_validate(response_dict)


async def _find_card_by_agent_did(
    db: AsyncSession, did: str
) -> Optional[models.AgentCard]:
    """
    Find the AgentCard linked to a specific agent DID.
    OWL22 Option B: Uses the agent_did column for direct lookup.
    Falls back to developer_id matching for legacy cards without agent_did set.

    OWL24 Fix: Uses scalars().first() instead of scalar_one_or_none() to avoid
    MultipleResultsFound crash if legacy duplicate agent_did values exist.
    Filters for active cards and orders by newest first.
    """
    # --- OWL22+OWL24: Primary path — direct agent_did column lookup (defensive) ---
    direct_stmt = (
        select(models.AgentCard)
        .options(selectinload(models.AgentCard.developer))
        .where(
            models.AgentCard.agent_did == did,
            models.AgentCard.is_active == True
        )
        .order_by(models.AgentCard.updated_at.desc())
    )
    direct_result = await db.execute(direct_stmt)
    direct_card = direct_result.scalars().first()
    if direct_card:
        logger.debug(f"Found card {direct_card.id} via agent_did column for DID: {did}")
        return direct_card

    # --- OWL24: Also check inactive cards if no active card found ---
    inactive_stmt = (
        select(models.AgentCard)
        .options(selectinload(models.AgentCard.developer))
        .where(models.AgentCard.agent_did == did)
        .order_by(models.AgentCard.updated_at.desc())
    )
    inactive_result = await db.execute(inactive_stmt)
    inactive_card = inactive_result.scalars().first()
    if inactive_card:
        logger.debug(f"Found inactive card {inactive_card.id} via agent_did column for DID: {did}")
        return inactive_card

    # --- Fallback: legacy path for cards without agent_did set ---
    logger.debug(f"No card with agent_did={did}, falling back to developer_id matching")
    agent_stmt = select(models.Agent).where(models.Agent.did == did)
    agent_result = await db.execute(agent_stmt)
    agent_obj = agent_result.scalar_one_or_none()
    if not agent_obj:
        logger.debug(f"No agent found with DID: {did}")
        return None

    card_stmt = (
        select(models.AgentCard)
        .options(selectinload(models.AgentCard.developer))
        .where(
            models.AgentCard.developer_id == agent_obj.creator_developer_id,
            models.AgentCard.agent_did.is_(None)  # Only unlinked cards
        )
        .order_by(models.AgentCard.updated_at.desc())
    )
    card_result = await db.execute(card_stmt)
    card = card_result.scalars().first()
    if card:
        logger.info(f"Legacy fallback: matched unlinked card {card.id} for DID {did}")
    return card


# --- Helper: Multi-format card lookup (UUID, DID, integer ID) ---
async def _resolve_agent_card(
    db: AsyncSession, card_id: str
) -> Optional[models.AgentCard]:
    """
    Resolve an agent card from multiple ID formats:
    - UUID (e.g., "123e4567-e89b-12d3-a456-426614174000")
    - DID (e.g., "did:cos:example-agent") → via agents table + developer_id join
    - humanReadableId (e.g., "charlie-the-arbiter")
    - Integer ID (e.g., "65") → via agents table
    Returns the AgentCard model or None.
    """
    # 1. Try as UUID
    try:
        card_uuid = uuid.UUID(card_id)
        db_card = await agent_card.get_agent_card(db=db, card_id=card_uuid)
        if db_card:
            return db_card
    except ValueError:
        pass

    # 2. Try as DID — look up agents table, then find card via developer_id
    if card_id.startswith("did:"):
        db_card = await _find_card_by_agent_did(db, card_id)
        if db_card:
            return db_card

    # 3. Try as integer ID (agent table → developer_id → card)
    try:
        agent_int_id = int(card_id)
        agent_stmt = select(models.Agent).where(models.Agent.id == agent_int_id)
        agent_result = await db.execute(agent_stmt)
        agent_obj = agent_result.scalar_one_or_none()
        if agent_obj:
            db_card = await _find_card_by_agent_did(db, agent_obj.did)
            if db_card:
                return db_card
    except ValueError:
        pass

    # 4. Try as humanReadableId in card_data
    hri_stmt = (
        select(models.AgentCard)
        .options(selectinload(models.AgentCard.developer))
        .filter(text("card_data->>'humanReadableId' = :hri_val"))
    ).params(hri_val=card_id)
    hri_result = await db.execute(hri_stmt)
    db_card = hri_result.scalar_one_or_none()
    if db_card:
        return db_card

    return None


# --- §DISCREFINE: PATCH /agent-cards/{card_id}/listing --------------------
# Registered BEFORE "/{card_id}" would be reached for this shape; the path is
# distinct enough that ordering is not load-bearing here, but the /discover
# lesson (§NOTIFV2: registration order beats path specificity) is why this sits
# above the generic routes rather than below them.
class ListingVisibilityIn(BaseModel):
    unlisted: bool = Field(
        ...,
        description="TRUE hides the agent from discovery, search and facets, here and on every peer (it still federates as an unlisted mirror, §DARKSYNC).",
    )


@router.patch(
    "/{card_id}/listing",
    summary="Show or hide this agent in discovery",
    description=(
        "Owner-only. `unlisted=true` removes the agent from discovery, search "
        "and facet counts, here and on every peer. It still federates, as an UNLISTED "
        "mirror, so a peer can resolve and pay it by DID while hiding it from its own "
        "discovery. It is NOT access control: anyone holding the DID can still fetch "
        "the card, because a counterparty must be able to read it to speak A2A. The "
        "unlisting also travels to peers as a tombstone carrying the DID and the "
        "listing block only, and a peer hides its mirror within two pull cycles, so "
        "no peer stores a listed copy of an unlisted agent."
    ),
    dependencies=[Security(get_current_developer)],
)
async def set_agent_card_listing(
    card_id: str,
    body: ListingVisibilityIn,
    db: AsyncSession = Depends(database.get_db),
    current_developer: models.Developer = Security(get_current_developer),
):
    db_card = await _resolve_agent_card(db=db, card_id=card_id)
    if db_card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Card not found")
    if db_card.developer_id != current_developer.id:
        # Admins deliberately do NOT get a bypass here. They can SEE hidden
        # agents in order to moderate; deciding whether someone else's agent is
        # listed is the owner's call, not an operator's.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to change the listing of this agent card",
        )

    # §REPBOND — listing (unlisted → listed) is a provider act: the bond gate applies.
    if not body.unlisted and db_card.agent_did:
        await _rb.gate(db, db_card.agent_did, site="listing")
        await _ep.gate(db, db_card.agent_did, site="listing")
    was = bool(db_card.unlisted)
    db_card.unlisted = bool(body.unlisted)
    await db.commit()
    await db.refresh(db_card)
    if was != bool(db_card.unlisted):
        _agent_updated_notice(db_card.agent_did, ["unlisted"], unlisted=bool(db_card.unlisted))
    logger.info(
        f"[DISCREFINE] developer {current_developer.id} set unlisted="
        f"{db_card.unlisted} (was {was}) on card {db_card.id} ({db_card.agent_did})"
    )
    return {
        "agent_did": db_card.agent_did,
        "unlisted": bool(db_card.unlisted),
        "changed": was != bool(db_card.unlisted),
        "note": (
            "Hidden from discovery on this registry. Its content is no longer exported to "
            "peers, and peers running §LISTPROP are told to hide their copy — usually within "
            "two of their pull cycles. A peer on an older image keeps its copy until it drops "
            "it. A direct DID lookup still resolves."
            if db_card.unlisted else
            "Listed in discovery on this registry, exported to peers again, and peers running "
            "§LISTPROP restore their copy on their next pull."
        ),
    }


def _agent_updated_notice(agent_did: Optional[str], changed: List[str], **extra) -> None:
    """§TWOAGENT (2026-09-24): agent.updated, owner-scoped, after the commit, for a NATIVE card (a card with an agent
    here). Subscribable and documented, it was dispatched by nothing."""
    if not agent_did:
        return
    try:
        import asyncio as _asyncio
        from ..background_tasks.reactor_helpers import dispatch_webhook_for_agents
        _asyncio.create_task(dispatch_webhook_for_agents(
            "agent.updated", {"agent_did": agent_did, "changed": list(changed), **extra}, [agent_did],
            source_label="agent_cards.update"))
    except Exception as e:  # noqa: BLE001 — a notice is advisory; the update committed
        logger.warning(f"agent.updated webhook not scheduled for {agent_did}: {e}")


# --- PUT /agent-cards/{card_id} ---
@router.put(
    "/{card_id}",
    response_model=schemas.AgentCardRead,
    summary="Update an Agent Card",
    description="Updates an existing Agent Card. Requires ownership. Accepts UUID, DID, or integer ID.",
    dependencies=[Security(get_current_developer)]
)
async def update_agent_card(
    card_id: str,
    card_in: schemas.AgentCardUpdate,
    # Dependencies after path and body params
    db: AsyncSession = Depends(database.get_db),
    current_developer: models.Developer = Security(get_current_developer),
) -> schemas.AgentCardRead:
    """
    Endpoint to update an Agent Card.
    Requires developer authentication (JWT) and ownership of the card.
    Accepts multiple ID formats: UUID, DID, or integer ID.
    Validates `card_data` if provided.
    """
    logger.info(f"Received request to update agent card {card_id} from developer ID: {current_developer.id}")
    # Multi-format lookup (UUID, DID, integer ID)
    db_card = await _resolve_agent_card(db=db, card_id=card_id)
    if db_card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Card not found")

    # Check ownership
    if db_card.developer_id != current_developer.id:
        logger.warning(f"Developer {current_developer.id} attempted to update agent card {card_id} owned by {db_card.developer_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this agent card")

    # §REPBOND — declaring a price on the card is a provider act: the bond gate applies.
    if db_card.agent_did and getattr(card_in, "card_data", None) and _rb.is_paid_card(card_in.card_data):
        await _rb.gate(db, db_card.agent_did, site="pricing")
        await _ep.gate(db, db_card.agent_did, site="pricing")
    try:
        # Pass the fetched db_card to the update function
        updated_card = await agent_card.update_agent_card(db=db, db_card=db_card, card_update=card_in)

        # Refresh developer relationship AFTER update
        if updated_card:
             logger.info(f"Refreshing developer relationship for updated card {updated_card.id}")
             await db.refresh(updated_card, attribute_names=['developer'])
        else:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update agent card record.")

        # Send WebSocket notification for agent update
        try:
            # Extract DID from card_data if available
            agent_did = updated_card.card_data.get('humanReadableId', str(updated_card.id))
            
            # Notify all connected users about the update
            await notify_agent_update(agent_did, {
                "action": "updated",
                "name": updated_card.name,
                "description": updated_card.description,
                "agent_id": str(updated_card.id),
                "is_active": updated_card.is_active,
                "changes": {
                    "name": updated_card.name,
                    "description": updated_card.description,
                    "is_active": updated_card.is_active
                }
            })
            
            # Send personal notification to the owner
            await send_notification(
                str(current_developer.id),
                "Agent Updated",
                f"Your agent '{updated_card.name}' has been successfully updated!",
                "success"
            )
            
            logger.info(f"WebSocket notifications sent for updated agent: {updated_card.name}")
        except Exception as ws_error:
            # Don't fail the request if WebSocket notification fails
            logger.warning(f"Failed to send WebSocket notification: {ws_error}")

        _agent_updated_notice(updated_card.agent_did,
                              [k for k in ("card_data", "is_active") if getattr(card_in, k, None) is not None],
                              name=updated_card.name)
        response_dict = _build_agent_card_read_dict(updated_card)
        await _state_home_extensions(db, response_dict, updated_card)
        return schemas.AgentCardRead.model_validate(response_dict)
    except ValueError as e:
        logger.warning(f"Failed to update agent card {card_id} due to validation/DB error: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to update agent card: {e}",
        )
    except Exception as e:
        logger.exception(f"Unexpected error updating agent card {card_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the agent card.",
        )


# --- DELETE /agent-cards/{card_id} ---
@router.delete(
    "/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an Agent Card",
    description="Marks an Agent Card as inactive (soft delete). Requires ownership.",
    dependencies=[Security(get_current_developer)]
)
async def delete_agent_card(
    card_id: str,
    # Dependencies after path param
    db: AsyncSession = Depends(database.get_db),
    current_developer: models.Developer = Security(get_current_developer),
):
    """
    Endpoint to soft-delete (deactivate) an Agent Card.
    Requires developer authentication (JWT) and ownership.
    Accepts multiple ID formats: UUID, DID, or integer ID.
    Returns 204 No Content on success.
    """
    logger.info(f"Received request to deactivate agent card {card_id} from developer ID: {current_developer.id}")
    # Multi-format lookup (UUID, DID, integer ID)
    db_card = await _resolve_agent_card(db=db, card_id=card_id)
    if db_card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Card not found")

    # Check ownership
    if db_card.developer_id != current_developer.id:
        logger.warning(f"Developer {current_developer.id} attempted to delete agent card {card_id} owned by {db_card.developer_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this agent card")

    # Store name before deletion for notification
    agent_name = db_card.name
    agent_did = db_card.card_data.get('humanReadableId', str(db_card.id))
    resolved_uuid = db_card.id  # Use the resolved UUID for CRUD operations

    # Call the delete (deactivate) function
    success = await agent_card.delete_agent_card(db=db, card_id=resolved_uuid)

    # Check result and raise appropriate error if deletion failed unexpectedly
    if not success:
        # Re-check the card status to see if it failed because it wasn't found
        # or due to a DB error during the update.
        check_card = await agent_card.get_agent_card(db=db, card_id=resolved_uuid)
        if not check_card:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Card not found during deletion process.")
        elif check_card.is_active: # Still active? Then the update failed.
             logger.error(f"Failed to deactivate agent card {card_id} due to a database error during update.")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to deactivate agent card due to internal error.")

    # Send WebSocket notification for agent deletion
    try:
        # Notify all connected users about the deletion
        await notify_agent_update(agent_did, {
            "action": "deleted",
            "name": agent_name,
            "agent_id": str(card_id),
            "is_active": False
        })
        
        # Change status to offline
        await notify_agent_status_change(agent_did, "offline")
        
        # Send personal notification to the owner
        await send_notification(
            str(current_developer.id),
            "Agent Deactivated",
            f"Your agent '{agent_name}' has been deactivated.",
            "warning"
        )
        
        # Broadcast to all users
        await broadcast_notification(
            "Agent Offline",
            f"Agent '{agent_name}' has been deactivated and is now offline.",
            "warning"
        )
        
        logger.info(f"WebSocket notifications sent for deleted agent: {agent_name}")
    except Exception as ws_error:
        # Don't fail the request if WebSocket notification fails
        logger.warning(f"Failed to send WebSocket notification: {ws_error}")

    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- GET /agent-cards/id/{human_readable_id} ---
@router.get(
    "/id/{human_readable_id:path}", # Use path parameter to allow slashes
    response_model=schemas.AgentCardRead,
    summary="Get Agent Card by Human-Readable ID",
    description="Retrieves the details of a specific Agent Card by its humanReadableId (e.g., 'org/agent').",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Agent Cards"
)
async def get_agent_card_by_human_id(
    human_readable_id: str,
    # Dependency after path param
    db: AsyncSession = Depends(database.get_db),
) -> schemas.AgentCardRead:
    """
    Public endpoint to retrieve a specific Agent Card by its humanReadableId.
    """
    logger.info(f"get_agent_card_by_human_id called with HRI: '{human_readable_id}'")

    # URL decoding for human_readable_id which might be sent URL-encoded
    import urllib.parse
    try:
        decoded_id = urllib.parse.unquote(human_readable_id)
    except Exception:
        decoded_id = human_readable_id
    db_card = await agent_card.get_agent_card_by_human_readable_id(db=db, human_readable_id=decoded_id)
    
    if db_card is None:
        logger.warning(f"⚠️ Agent card with humanReadableId '{decoded_id}' not found via CRUD function.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Agent Card with humanReadableId '{decoded_id}' not found"
        )
    
    logger.info(f"✓ Successfully found agent card: {db_card.name} (ID: {db_card.id})")

    response_dict = _build_agent_card_read_dict(
        db_card, health=await _health_for(db, getattr(db_card, "agent_did", None)))
    await _state_home_extensions(db, response_dict, db_card)
    return schemas.AgentCardRead.model_validate(response_dict)
