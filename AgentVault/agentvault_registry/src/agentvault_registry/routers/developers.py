import json
import logging
import os
import secrets
import uuid
from datetime import datetime
from decimal import Decimal
import random
# --- MODIFIED: Added List, Optional, Annotated, Dict ---
from typing import List, Optional, Annotated, Dict, Any
# --- END MODIFIED ---

# --- MODIFIED: Added Body, Path, Response, Query ---
from fastapi import APIRouter, Depends, HTTPException, status, Body, Path, Response, Query, Request
# --- END MODIFIED ---
from sqlalchemy import select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports (will be needed later)
from agentvault_registry import schemas, models, security
from agentvault_registry.database import get_db
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.config import settings
from agentvault_registry.services.webhook_service import WebhookService
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter
import httpx
from ..es_ssl_helper import get_httpx_verify
from ..core.path_segment import seg  # §MCPTEST30 V0526: a value in a store/TEG URL path is one encoded segment (round 9: a malformed id read as an outage)
import asyncio

# TEG integration imports - moved to module level for proper initialization
from .teg_integration import (
    get_teg_token_for_agent, 
    prepare_teg_headers, 
    TEG_API_BASE_URL, 
    TEG_API_V1_PREFIX
)

logger = logging.getLogger(__name__)

# Frame-native currency (AVT=Frame-A · JDAY=Frame-B · BVT=Frame-C). Agents on this
# registry are denominated in this frame's currency; never hardcode 'AVT'. (#26)
_FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"

router = APIRouter(
    prefix="/developers",
    tags=["Developers"],
    # Apply JWT authentication to all routes in this router
    dependencies=[Depends(security.get_current_developer)]
)

# --- Endpoints will be added here based on REQ-AUTH-008 ---

@router.get("/me", response_model=schemas.DeveloperRead, summary="Get Current Developer Info")
async def read_users_me(
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)],
    db: AsyncSession = Depends(get_db),
):
    """Returns the information for the currently authenticated developer."""
    # §LEGALKIT: the console asks for renewed acceptance from these fields (Terms § 10.2), the operator document among
    # them for an account that holds operators (V0414).
    from .legal import reconsent_state as _reconsent_state
    out = schemas.DeveloperRead.model_validate(current_developer)
    for k, v in (await _reconsent_state(current_developer, db)).items():
        setattr(out, k, v)
    return out


@router.put("/me", response_model=schemas.DeveloperRead, summary="Update Developer Profile")
async def update_developer_profile(
    profile: schemas.DeveloperProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Update the profile of the currently authenticated developer.
    Only provided (non-null) fields are updated (partial update).
    """
    update_data = profile.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(current_developer, field, value)
    db.add(current_developer)
    await db.commit()
    await db.refresh(current_developer)
    logger.info(f"Profile updated for developer ID: {current_developer.id} — fields: {list(update_data.keys())}")
    return current_developer


@router.get("/me/activity", summary="Get Developer EventStore Activity")
async def get_developer_activity_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    agent_did: str | None = Query(
        None,
        description="§POCKETBRIDGE5 W-G — scope to ONE of your agents: reads that "
                    "aggregate's own ledger record (newest first) instead of "
                    "sampling the frame window.",
    ),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Event store events of all the developer's agents, newest first: transfers, locks, governance, disputes and
    attestations. An empty list when the event store cannot be reached. Needs a developer token.

    \f
    Fetch EventStore events for all agents belonging to this developer.
    Returns real economic events: transfers, locks, governance, disputes, attestations.
    Falls back to empty list if EventStore is unavailable.

    §POCKETBRIDGE5 W-G: the sampled path now reads the NEWEST window
    (`sort_order=desc`). Live-proven defect before this: the ES default is
    ASC, so "recent activity" had been serving the OLDEST 200 events of the
    frame ledger (June 4 rows, measured 2026-08-23) as the last-N window.
    """

    # Get all DIDs for this developer's agents
    stmt = select(models.Agent).where(
        models.Agent.creator_developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    agents = result.scalars().all()
    agent_dids = [a.did for a in agents]

    if not agent_dids:
        return {"events": [], "total": 0, "sampled_window": 0, "scope": "developer"}

    event_store_url = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
    event_store_key = os.environ.get("EVENT_STORE_API_KEY", "")

    if agent_did:
        # ── per-aggregate scope: that agent's OWN record, complete or clipped ──
        if agent_did not in agent_dids:
            raise HTTPException(status_code=403, detail="agent_did does not belong to this developer")
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=get_httpx_verify()) as client:
                # STREAM with a hard byte budget. An EventStore that predates the
                # bounded per-aggregate query IGNORES limit/sort_order and would
                # return the aggregate's ENTIRE history — the busiest frame-c
                # aggregate holds 1.1M events. The budget turns that into an
                # honest error instead of a 38-worker memory event.
                BYTE_BUDGET = 8_000_000
                body = bytearray()
                async with client.stream(
                    "GET",
                    f"{event_store_url}/api/v1/events/aggregate/{seg(agent_did)}",
                    params={"limit": limit, "sort_order": "desc"},
                    headers={"X-Internal-Key": event_store_key},
                ) as resp:
                    if resp.status_code != 200:
                        logger.warning(f"EventStore returned {resp.status_code} for per-agent activity")
                        return {"events": [], "total": 0, "scope": "agent", "agent_did": agent_did,
                                "error": f"EventStore returned {resp.status_code}"}
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > BYTE_BUDGET:
                            return {"events": [], "total": 0, "scope": "agent", "agent_did": agent_did,
                                    "error": "This registry's EventStore predates bounded per-agent "
                                             "queries and the record is too large to fetch whole. "
                                             "The sampled view still works."}
            rows = json.loads(bytes(body))
            if not isinstance(rows, list):
                rows = rows.get("events", rows.get("items", []))
            # An old ES returns the full ASC history (when it fits the budget):
            # normalize both worlds to "the newest `limit`, newest first".
            clipped = len(rows) > limit
            if clipped:
                rows = rows[-limit:]
            rows.sort(key=lambda e: str(e.get("timestamp") or ""), reverse=True)
            return {"events": rows, "total": len(rows), "scope": "agent",
                    "agent_did": agent_did, "complete": not clipped and len(rows) < limit}
        except Exception as exc:
            logger.warning(f"EventStore unavailable for per-agent activity ({agent_did}): {exc}")
            return {"events": [], "total": 0, "scope": "agent", "agent_did": agent_did,
                    "error": "EventStore unavailable"}

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, verify=get_httpx_verify()) as client:
            # Query EventStore — returns raw list. sort_order=desc: the window
            # must be the NEWEST slice of the ledger, not its birth.
            resp = await client.get(
                f"{event_store_url}/api/v1/events/",
                params={"limit": limit, "offset": offset, "sort_order": "desc"},
                headers={"X-Internal-Key": event_store_key}
            )
            if resp.status_code == 200:
                raw = resp.json()
                # EventStore returns a raw list, not a dict
                all_events = raw if isinstance(raw, list) else raw.get("events", raw.get("items", []))
                # Filter to events relevant to this developer's agents (check all string fields)
                dev_events = [
                    e for e in all_events
                    if not agent_dids or any(
                        did in str(e.get("aggregate_id", ""))
                        or did in str(e.get("data", {}))
                        for did in agent_dids
                    )
                ]
                # §POCKETBRIDGE2 W1.11 — this endpoint SAMPLES a bounded window of
                # the frame ledger and filters it; a small developer on a busy
                # frame can legitimately read as empty. The response now names
                # the window it scanned so clients can caption honestly.
                return {"events": dev_events, "total": len(dev_events),
                        "sampled_window": len(all_events), "scope": "developer"}
            else:
                logger.warning(f"EventStore returned {resp.status_code} for developer {current_developer.id} activity")
    except Exception as exc:
        logger.warning(f"EventStore unavailable for developer {current_developer.id} activity: {exc}")

    return {"events": [], "total": 0, "sampled_window": 0, "scope": "developer"}

# --- ADDED: API Key Management Endpoints ---
@router.post(
    "/me/apikeys",
    response_model=schemas.NewApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new programmatic API Key"
)
async def create_new_api_key(
    description: Optional[str] = Body(None, embed=True, description="Optional description for the API key."), # Use Body for optional field
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Generates a new programmatic API key (prefixed with 'avreg_') associated
    with the authenticated developer. The plain text key is returned ONLY once.
    """
    logger.info(f"Request to create new API key for developer ID: {current_developer.id}")
    # §POCKETPAIR (2026-10-15): this rail mints a '*' key that never expires, and it asked no scope at all, so ANY
    # scoped key (a paired phone's, an MCP OAuth client's) could mint itself full authority here, past the 'keys:manage'
    # gate of /auth/api-keys and past the admin gate. Only a session or a '*' key may use it now.
    if not security.key_may_mint(None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A scoped API key cannot create API keys here; sign in, or use /auth/api-keys with a 'keys:manage' key.",
        )
    plain_key = security.generate_secure_api_key()
    hashed_key = security.hash_api_key(plain_key)
    prefix = plain_key.split("_")[0] + "_"

    _dev_id = current_developer.id   # §MCPTEST30 (V0526): read before the save; a failed save expires the row
    db_api_key = await developer_crud.create_api_key(
        db=db,
        developer_id=_dev_id,
        prefix=prefix,
        hashed_key=hashed_key,
        description=description,
        key_sha256=security.api_key_lookup_hash(plain_key)
    )

    if not db_api_key:
        logger.error(f"Failed to save new API key to database for developer {_dev_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create API key."
        )

    # Validate the created object before returning
    api_key_info = schemas.ApiKeyRead.model_validate(db_api_key)

    return schemas.NewApiKeyResponse(
        plain_api_key=plain_key,
        api_key_info=api_key_info
    )

@router.get(
    "/me/apikeys",
    response_model=List[schemas.ApiKeyRead],
    summary="List active programmatic API Keys"
)
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Retrieves a list of active programmatic API keys for the authenticated developer.
    """
    logger.info(f"Request to list API keys for developer ID: {current_developer.id}")
    db_keys = await developer_crud.get_active_api_keys_for_developer(
        db=db, developer_id=current_developer.id
    )
    # Pydantic will automatically validate the list during response serialization
    return db_keys

@router.delete(
    "/me/apikeys/{key_id}", # Use integer ID from ApiKeyRead schema
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate (delete) a programmatic API Key"
)
async def delete_api_key(
    key_id: int = Path(..., description="The integer ID of the API key to deactivate."),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Deactivates (soft deletes) a specific programmatic API key owned by the
    authenticated developer.
    """
    logger.info(f"Request to deactivate API key ID: {key_id} for developer ID: {current_developer.id}")
    success = await developer_crud.deactivate_api_key(
        db=db,
        developer_id=current_developer.id,
        api_key_id=key_id # Pass integer ID
    )
    if not success:
        # CRUD function handles logging details, just raise 404 here
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found or not owned by the current user."
        )
    # §POCKETPAIR (2026-10-15): a phone paired with this key stops receiving pushes with it.
    try:
        from agentvault_registry.services.device_key_link import disable_devices_for_key
        await disable_devices_for_key(db, current_developer.id, key_id)
        await db.commit()
    except Exception:  # noqa: BLE001 - the key is revoked already; the device rows are a follow-up, logged
        await db.rollback()
        logger.warning(f"[POCKETPAIR] key {key_id} revoked, its paired devices not disabled", exc_info=True)
    # Return No Content on success
    return Response(status_code=status.HTTP_204_NO_CONTENT)
# --- END ADDED ---

# --- ADDED: Agent management endpoints ---
@router.get("/me/agents", response_model=List[schemas.AgentRead], summary="List Developer's Agents")
async def list_developer_agents(
    response: Response,
    limit: int = Query(
        200, ge=1, le=500,
        description=(
            "Max agents to return (default 200, hard-cap 500). "
            "For developers with many agents (e.g., test/canary fixture owners), "
            "this prevents 13MB+ responses + cascade-fetch storms via the "
            "frontend's per-agent balance batcher. Pass higher values "
            "deliberately when paginating; never use unbounded list."
        ),
    ),
    offset: int = Query(
        0, ge=0,
        description="Pagination offset (most recent first via created_at DESC).",
    ),
    q: Optional[str] = Query(
        None,
        description=(
            "Search across the developer's ENTIRE fleet by agent DID substring "
            "or agent-card name (case-insensitive). Bypasses the recency-window "
            "problem: a credentialed working agent created long ago (behind "
            "thousands of fixtures) is findable by name/DID even though it falls "
            "outside the default created_at-DESC window. Still capped by `limit`."
        ),
    ),
    include_dids: Optional[str] = Query(
        None,
        description=(
            "CSV of agent DIDs to force-include in the response, hydrated, "
            "REGARDLESS of the recency window. The frontend passes the DIDs it "
            "holds local credentials for, so a developer's working set is always "
            "returned (and floated to the top of the switcher) even when it was "
            "created before the most-recent `limit` agents. Max 300 DIDs."
        ),
    ),
    top_level_only: bool = Query(
        False,
        description=(
            "Exclude spawned sub-agents (HANDS) — agents that hold a BIRTH capability "
            "token (§SUBAGENT-LIABILITY). Surfaces the developer's REAL top-level agents "
            "when the created_at-DESC window is dominated by sim/forge-spawned hands. "
            "Applied server-side so the page isn't filled with thousands of hands before "
            "it ever reaches the client's filters."
        ),
    ),
    sort: Optional[str] = Query(
        None,
        description=(
            "Optional sort. 'balance' orders by liquid_balance DESC (an indexed "
            "column) — the Pocket Home 'Accounts' source. §POCKETBRIDGE F12: a "
            "recency window over a 4,000-agent fleet showed the newest forge "
            "fixtures and called the account 'no funded agents'; only the server "
            "can answer 'top by balance'. "
            "'live' (§COCKPITPOLISH) orders by last_active_at DESC NULLS LAST — the "
            "agents that have CALLED THIS REGISTRY most recently, which is the only "
            "ordering that puts the working fleet at the top of a picker. "
            "Anything else = created_at DESC."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    # §pass14 (2026-05-15) — Bearer-state-defining payload. Without an
    # explicit Cache-Control header, browsers apply heuristic caching to
    # GET responses (often ~10 min for SPA in-page reloads / back-forward
    # cache / soft refresh). That meant after a user equipped a new bearer
    # via /flare/equip, a soft reload of /flare-manager could re-render
    # from a cached pre-equip response, making it look like the equip
    # never persisted. no-store + must-revalidate forces every load to hit
    # the server, which holds the authoritative bears_*_flare flags.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    """
    List agents created by the authenticated developer (paginated).

    Returns up to ``limit`` agents (default 200, max 500), ordered by
    ``created_at DESC`` so the most recently created agents come first.
    For broad sweeps, use ``offset`` to page through the full set.

    Each agent payload includes DID, client_id, status, timestamps,
    reputation, balances, attached card data, and PB-1 flare cosmetic.
    """
    logger.info(
        f"Request to list agents for developer ID: {current_developer.id} "
        f"(limit={limit}, offset={offset})"
    )

    # Query for all agents created by this developer (paginated). Default
    # cap of 200 protects the network: a developer with 9k agents (sandbox
    # admin + canary fixtures) used to return 13MB on every page navigation,
    # which the frontend then batched into ~190 parallel /balances calls,
    # saturating TEG-A and starving canary/reactor workers of leadership.
    stmt = (
        select(models.Agent)
        .where(models.Agent.creator_developer_id == current_developer.id)
    )

    # §agentfinder (2026-07-26) — server-side search so the switcher's finder
    # resolves ANY of the developer's agents by name or DID, not just the ones
    # inside the created_at-DESC window. `AgentCard.name` is an indexed column;
    # the name match rides a bounded subquery of THIS developer's cards.
    if q and q.strip():
        term = f"%{q.strip()}%"
        name_dids = (
            select(models.AgentCard.agent_did)
            .where(models.AgentCard.developer_id == current_developer.id)
            .where(models.AgentCard.name.ilike(term))
        )
        stmt = stmt.where(
            or_(
                models.Agent.did.ilike(term),
                models.Agent.did.in_(name_dids),
            )
        )

    if top_level_only:
        # A "hand" is the HOLDER of a birth capability token (§SUBAGENT-LIABILITY).
        # Excluding them lets the recency window fill with the developer's real
        # agents instead of thousands of freshly-spawned hands sitting at the top of
        # created_at DESC. Correlated NOT EXISTS on the indexed holder_agent_did.
        stmt = stmt.where(text(
            "NOT EXISTS (SELECT 1 FROM agent_capability_tokens t "
            "WHERE t.holder_agent_did = agents.did AND (t.caveats->>'birth') = 'true')"
        ))

    if sort == "balance":
        # liquid_balance is indexed (models.py) and synced from TEG truth by the
        # reward/balance-sync rails — created_at DESC stays the tiebreak so the
        # order is stable across equal (usually zero) balances.
        stmt = stmt.order_by(models.Agent.liquid_balance.desc(), models.Agent.created_at.desc())
    elif sort == "live":
        # §COCKPITPOLISH P2 — RANK BY LIVENESS, NOT RECENCY.
        #
        # Measured on registry-a, developer 10 (4,130 agents): the created_at-DESC
        # default returns `<no name>`, `forge-a-gen-1..15` and `api-theprotocol-cloud`,
        # and the name-says-fixture population is 182 — so BOTH agent pickers opened
        # on a list containing none of the operator's real agents. The agents that
        # called this registry in the last 15 minutes number 21, and they are exactly
        # the four Ironhands, the eleven sovereigns, the mTLS senders and two service
        # agents. That is the list a picker wants.
        #
        # ⚠ `last_active_at` is stamped by the ORDINARY `get_current_agent` dependency
        # (POST /agents/heartbeat merely rides it), so this orders by "called us with
        # its own credentials", never by a dedicated liveness protocol — there isn't
        # one. The FE says so in the words it prints; do not let a caller infer more.
        #
        # NULLS LAST is load-bearing: Postgres sorts NULL FIRST on DESC by default, so
        # without it every never-active agent would outrank every live one and this
        # sort would be worse than the default it replaces.
        #
        # No index needed and none added: the developer filter already rides
        # ix_agents_creator_developer_id and the top-N heapsort over one developer's
        # 4,130 rows measured 2.6 ms (EXPLAIN ANALYZE, 2026-08-31). An index here
        # would be speculative work on a hot table.
        stmt = stmt.order_by(
            models.Agent.last_active_at.desc().nullslast(),
            models.Agent.created_at.desc(),
        )
    else:
        stmt = stmt.order_by(models.Agent.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    agents = list(result.scalars().all())

    # §agentfinder — force-include the caller's credentialed working set even
    # when it sits behind thousands of newer fixtures. Prepended so the payload
    # leads with the agents the user can actually act on; the FE sort keys on
    # credentials anyway, so order is belt-and-suspenders. Deduped by DID.
    if include_dids and include_dids.strip():
        want = [d.strip() for d in include_dids.split(",") if d.strip()][:300]
        have = {a.did for a in agents}
        missing = [d for d in want if d not in have]
        if missing:
            inc_stmt = select(models.Agent).where(
                models.Agent.creator_developer_id == current_developer.id,
                models.Agent.did.in_(missing),
            )
            included = list((await db.execute(inc_stmt)).scalars().all())
            if included:
                agents = included + agents

    logger.info(f"Found {len(agents)} agents for developer ID: {current_developer.id}")
    
    # Query for agent cards — restricted to the agents we're returning. Without
    # this restriction the call still scaled with the developer's TOTAL fleet
    # (the issue that triggered the fix above); now it's bounded by `limit`.
    page_dids = [a.did for a in agents]
    if page_dids:
        card_stmt = (
            select(models.AgentCard)
            .where(models.AgentCard.developer_id == current_developer.id)
            .where(models.AgentCard.agent_did.in_(page_dids))
        )
        card_result = await db.execute(card_stmt)
        agent_cards = card_result.scalars().all()
    else:
        agent_cards = []
    
    # --- OWL22 OPTION B: Map cards to agents via agent_did column ---
    did_to_card = {}
    for card in agent_cards:
        if card.agent_did:
            did_to_card[card.agent_did] = card
    # --- END OWL22 ---
    
    # PB-1 flare hardening: customization lives on Developer — fetch ONCE for
    # the caller, then attach to each agent that wears their flare. Agents with
    # no flare get null customization fields.
    dev_flare_customization = {
        "flare_id":           getattr(current_developer, "flare_id", None),
        "flare_display_name": getattr(current_developer, "flare_display_name", None),
        "flare_tagline":      getattr(current_developer, "flare_tagline", None),
        "flare_logo_url":     getattr(current_developer, "flare_logo_url", None),
        "flare_link_url":     getattr(current_developer, "flare_link_url", None),
        "flare_cause":        getattr(current_developer, "flare_cause", None),
        "flare_accent_color": getattr(current_developer, "flare_accent_color", None),
    }

    # §23 (2026-05-14) — Dual-slot bearer plumbing.
    # The dev's two slot selections are attached per-agent ONLY when that
    # agent bears that slot. UserAvatar.vue's typeof-aware resolver then
    # renders the corresponding slot on the agent. Same agent can bear both
    # (both fields populated); different agents can bear different slots
    # (each gets only its own slot).
    dev_selected_corner       = getattr(current_developer, "selected_corner_flare", None)
    dev_selected_encirclement = getattr(current_developer, "selected_encirclement_flare", None)
    # §23 — admin per-agent corner-badge variant precedence:
    #   1. agent.flare_corner_variant (per-agent override) wins, else
    #   2. dev's flare_corner_variant if the agent is the corner bearer
    # NULL on the agent side means "no per-agent override" — FE consumes the
    # raw value and decides which to render with the dev's variant.
    dev_corner_variant_fallback = getattr(current_developer, "flare_corner_variant", None)

    # §MARKSURFACES (2026-09-10) — the ledger-earned mark for this page, in ONE grouped
    # pass over both guild books (no N+1). This is what makes the header agent switcher
    # and My Agents able to show a rank at all: they mount `<UserAvatar :user="agent">`,
    # and until now the row they were handed simply had no track record on it.
    # Must never break the agent list — an avatar decoration is not worth a 500.
    tr_by_did: Dict[str, Any] = {}
    if page_dids:
        try:
            from agentvault_registry.services.track_record import compact_track_records
            tr_by_did = await compact_track_records(db, page_dids)
        except Exception as _tr_e:  # noqa: BLE001
            logger.warning(f"[MARK] track-record enrichment failed for developer "
                           f"{current_developer.id}: {_tr_e}")

    # Convert to response schema with card data
    agent_responses = []
    for agent in agents:
        flare_tier = getattr(agent, "flare_tier", None)
        bears_corner       = bool(getattr(agent, "bears_corner_flare", False))
        bears_encirclement = bool(getattr(agent, "bears_encirclement_flare", False))
        agent_corner_variant = getattr(agent, "flare_corner_variant", None)
        agent_dict = {
            "id": agent.id,
            "did": agent.did,
            "client_id": agent.client_id,
            "status": agent.status,
            "creator_developer_id": agent.creator_developer_id,
            "created_at": agent.created_at,
            "last_active_at": agent.last_active_at,
            # §COCKPITA R2 — the RUNTIME pair. ⚠ THIS DICT IS A SILENT-DROP MACHINE: the
            # response is assembled key by key and handed to `AgentRead(**agent_dict)`, so a
            # field added to the SCHEMA alone arrives as None forever, with every marker
            # present and nothing erroring (§EXCISION-10, and the reason PART 1 says a
            # backend field is not done until something READS it). Caught by the §COCKPITA
            # battery asserting a verdict it had just written to the database.
            "last_health": agent.last_health,
            "last_health_at": agent.last_health_at,
            "reputation_score": agent.reputation_score,
            "liquid_balance": agent.liquid_balance,
            "staked_balance": agent.staked_balance,
            "name": None,
            "description": None,
            "card_data": None,
            # PB-1 backer flare (2026-05-09) — cosmetic, public.
            "flare_tier": flare_tier,
            "flare_granted_at": getattr(agent, "flare_granted_at", None),
            # 2026-05-13 §15+§19+§20: per-agent encirclement variant.
            "flare_encirclement_variant": getattr(agent, "flare_encirclement_variant", None),
            # §28 (2026-05-13) — per-agent broken-machine overlay (independent axis).
            "flare_encirclement_overlay": getattr(agent, "flare_encirclement_overlay", None),
            # §23 (2026-05-14) — dual-slot bearer + per-agent admin corner variant
            "bears_corner_flare":       bears_corner,
            "bears_encirclement_flare": bears_encirclement,
            "flare_corner_variant":     agent_corner_variant if agent_corner_variant is not None else (dev_corner_variant_fallback if bears_corner else None),
            # The dev's slot selections — attached only when this agent bears
            # that slot. UserAvatar.vue's existing typeof-aware fallback then
            # resolves each slot independently. typeof === 'string' or null
            # respects an explicit choice; undefined falls back to flare_tier.
            "selected_corner_flare":       dev_selected_corner       if bears_corner       else None,
            "selected_encirclement_flare": dev_selected_encirclement if bears_encirclement else None,
            # §MARKSURFACES — absent for an agent with no verified work, which is the
            # honest answer and the one the FE renders as "no mark".
            "track_record": tr_by_did.get(agent.did),
            # Customization is null when the agent has no flare; otherwise
            # spread the developer's customization onto the row.
            **(dev_flare_customization if (flare_tier or bears_corner or bears_encirclement) else {
                "flare_id": None, "flare_display_name": None, "flare_tagline": None,
                "flare_logo_url": None, "flare_link_url": None, "flare_cause": None,
                "flare_accent_color": None,
            }),
        }
        
        # Add card data if available
        if agent.did in did_to_card:
            card = did_to_card[agent.did]
            agent_dict["name"] = card.name
            agent_dict["description"] = card.description
            agent_dict["card_data"] = card.card_data
        
        agent_responses.append(schemas.AgentRead(**agent_dict))
    
    return agent_responses
# --- END ADDED ---


@router.get("/me/holdings-book",
            summary="Every AGORA holding of MY agents, in one answer")
# §AGORAWORDS (V0419): the old path stays live (the console calls it until the callers switch).
# Neither name may contain an agent-tier substring (see the docstring): `holdings-book` is safe too,
# and `/developers/` short-circuits isAgentTier() to the developer tier.
@router.get("/me/share-book", include_in_schema=False)
async def my_exchange_book(
    top_holders: int = Query(5, ge=0, le=25, description="Agents to name per symbol."),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    Every AGORA holding of the developer's agents on this registry, in one answer: per listing, the points held,
    with totals per currency (never merged across currencies). A listing that has never traded has no last price, so
    its `market_value` is null rather than zero. Needs a developer token.

    \f
    The book this developer's agents hold across the local venue.

    ⚠ THE PATH IS `share-book`, NOT `exchange/portfolio`, AND THAT IS LOAD-BEARING.
    The frontend's `isAgentTier()` classifies by SUBSTRING — `url.includes('/exchange/portfolio')`
    — so a developer-tier route containing another surface's path inherits that surface's
    auth tier: the browser attached an AGENT token to this developer endpoint and got 401,
    while the same call with a developer token from a script returned 200. A route named
    out of collision range cannot be mis-tiered by a future rule either.

    🔴 WHY THIS EXISTS AT ALL. `GET /exchange/portfolio` is AGENT-tier and answers for ONE
    agent, which is correct — shares are held by an agent, not by a person. But the desk
    then showed "holds no shares on this venue" while THIS account's agents held **2.7M
    shares across three listings**, because the acting agent happened to be one of the ~4,000
    that hold none. A per-agent rail cannot answer "what do I own", and asking it 4,000 times
    is not an answer either.

    ⚠ ONE GROUPED QUERY, never a fan-out. The §COCKPITSHOW denials pane learned this the
    expensive way: it sampled the top agents BY BALANCE and reported "no refusals" over 3,357
    real ones. A per-agent loop here would be the same mistake with a worse constant.

    ⚠ TOTALS ARE PER CURRENCY AND NEVER MERGED (§SUMSPLIT / §FOREIGNACT). Listings carry
    their own currency; one number spanning AVT and BVT is a wrong number, not a rounded one.

    ⚠ A MISSING LAST PRICE IS NOT A ZERO PRICE (§RAT). A listing that has never traded has
    no mark; its `market_value` is null and the reader is told so, rather than being shown a
    position worth nothing.
    """
    dev_id = current_developer.id

    rows = (await db.execute(text("""
        WITH mine AS (
            SELECT did FROM agents
            WHERE creator_developer_id = :dev AND status = 'active'
        ), last_px AS (
            SELECT DISTINCT ON (listing_id) listing_id, price, created_at
            FROM exchange_trades
            ORDER BY listing_id, created_at DESC, seq DESC
        ), pos AS (
            SELECT p.listing_id, p.agent_did, p.qty, p.locked_qty, p.avg_cost
            FROM org_share_positions p
            JOIN mine m ON m.did = p.agent_did
            WHERE p.qty > 0
        )
        SELECT l.id                         AS listing_id,
               l.symbol                     AS symbol,
               l.display_name               AS display_name,
               l.currency                   AS currency,
               l.ipo_price                  AS ipo_price,
               l.status                     AS listing_status,
               SUM(pos.qty)                 AS qty,
               SUM(pos.locked_qty)          AS locked_qty,
               SUM(pos.qty * pos.avg_cost)  AS cost_basis,
               COUNT(*)                     AS holders,
               lp.price                     AS last_price,
               lp.created_at                AS last_trade_at
        FROM pos
        JOIN exchange_listings l ON l.id = pos.listing_id
        LEFT JOIN last_px lp ON lp.listing_id = l.id
        GROUP BY l.id, l.symbol, l.display_name, l.currency, l.ipo_price, l.status,
                 lp.price, lp.created_at
        ORDER BY SUM(pos.qty * COALESCE(lp.price, l.ipo_price, 0)) DESC
    """), {"dev": dev_id})).mappings().all()

    # Names for the agents that hold the most of each symbol. A DID is not an identity a
    # human can act on — the §COCKPITPOLISH lesson, one surface over.
    holders_by_listing: Dict[Any, List[Dict[str, Any]]] = {}
    if top_holders and rows:
        hrows = (await db.execute(text("""
            WITH mine AS (
                SELECT did FROM agents
                WHERE creator_developer_id = :dev AND status = 'active'
            ), ranked AS (
                SELECT p.listing_id, p.agent_did, p.qty,
                       ROW_NUMBER() OVER (PARTITION BY p.listing_id ORDER BY p.qty DESC) AS rn
                FROM org_share_positions p
                JOIN mine m ON m.did = p.agent_did
                WHERE p.qty > 0
            )
            SELECT r.listing_id, r.agent_did, r.qty,
                   COALESCE(NULLIF(ac.card_data->>'name', ''), '') AS name
            FROM ranked r
            LEFT JOIN agent_cards ac ON ac.agent_did = r.agent_did
            WHERE r.rn <= :n
            ORDER BY r.listing_id, r.qty DESC
        """), {"dev": dev_id, "n": top_holders})).mappings().all()
        for h in hrows:
            holders_by_listing.setdefault(h["listing_id"], []).append({
                "agent_did": h["agent_did"],
                # "" means we could not resolve a name, NOT that it has none — the caller
                # renders the DID in that case rather than inventing a label.
                "name": h["name"] or None,
                "qty": int(h["qty"]),
            })

    positions: List[Dict[str, Any]] = []
    by_ccy: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ccy = r["currency"] or "?"
        qty = int(r["qty"] or 0)
        cost = Decimal(str(r["cost_basis"] or 0))
        last = Decimal(str(r["last_price"])) if r["last_price"] is not None else None
        mkt = (Decimal(qty) * last) if last is not None else None
        positions.append({
            "listing_id": r["listing_id"],
            "symbol": r["symbol"],
            "display_name": r["display_name"],
            "currency": ccy,
            "qty": qty,
            "locked_qty": int(r["locked_qty"] or 0),
            "cost_basis": str(cost),
            "avg_cost": str(cost / qty) if qty else None,
            "last": str(last) if last is not None else None,
            "last_trade_at": r["last_trade_at"].isoformat() if r["last_trade_at"] else None,
            "ipo_price": str(r["ipo_price"]) if r["ipo_price"] is not None else None,
            "listing_status": r["listing_status"],
            "market_value": str(mkt) if mkt is not None else None,
            "unrealized_pnl": str(mkt - cost) if mkt is not None else None,
            "holders": int(r["holders"] or 0),
            "top_holders": holders_by_listing.get(r["listing_id"], []),
        })
        b = by_ccy.setdefault(ccy, {"currency": ccy, "cost_basis": Decimal(0),
                                    "market_value": Decimal(0), "positions": 0,
                                    "unpriced_positions": 0})
        b["cost_basis"] += cost
        b["positions"] += 1
        if mkt is not None:
            b["market_value"] += mkt
        else:
            b["unpriced_positions"] += 1

    currencies = []
    for b in by_ccy.values():
        # ⚠ `market_value` sums only the positions that HAVE a mark. When some are unpriced
        # the total is a floor, and `unpriced_positions` is how the reader knows that.
        currencies.append({
            "currency": b["currency"],
            "cost_basis": str(b["cost_basis"]),
            "market_value": str(b["market_value"]),
            "unrealized_pnl": str(b["market_value"] - b["cost_basis"]),
            "positions": b["positions"],
            "unpriced_positions": b["unpriced_positions"],
        })
    currencies.sort(key=lambda c: Decimal(c["market_value"]), reverse=True)

    div = (await db.execute(text("""
        SELECT COUNT(*) AS legs, COALESCE(SUM(d.amount), 0) AS amount
        FROM exchange_dividend_legs d
        JOIN agents a ON a.did = d.agent_did AND a.creator_developer_id = :dev
        WHERE d.status = 'paid'
    """), {"dev": dev_id})).mappings().first()

    agents_holding = (await db.execute(text("""
        SELECT COUNT(DISTINCT p.agent_did) AS n
        FROM org_share_positions p
        JOIN agents a ON a.did = p.agent_did AND a.creator_developer_id = :dev
        WHERE p.qty > 0
    """), {"dev": dev_id})).scalar_one()

    return {
        "positions": positions,
        "currencies": currencies,
        "agents_holding": int(agents_holding or 0),
        "dividends": {"legs": int(div["legs"] or 0), "amount": str(div["amount"] or 0)},
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/me/authz-denials", summary="Every authorization refusal across MY agents")
async def my_authz_denials(
    limit: int = Query(12, ge=1, le=50, description="How many distinct reasons to summarise."),
    examples: int = Query(6, ge=0, le=25, description="How many recent individual refusals to return."),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    Every authorization refusal recorded for the developer's agents in the last `days` (30 by default), from one
    grouped query: the `limit` most frequent reasons and the `examples` most recent refusals. A refusal whose reason
    cannot be read is counted under `(unspecified)`, never dropped. Needs a developer token.

    \f
    §COCKPITSHOW B4 — THE REFUSALS, ACROSS THE WHOLE FLEET, IN ONE QUERY.

    🔴 WHY THIS EXISTS. The desk's Denials pane fanned out over
    `/developers/me/agents?sort=balance` and asked each of the top N for its own feed.
    Measured on registry-a: it reported *"No refusals recorded for your agents in the last
    30 days"* while this developer's agents carried **3,357** of them — because the agents
    holding the refusals are working agents, and the ones holding the BALANCE are canaries
    and sim fixtures. Sampling the wrong axis and reporting the sample as the population is
    the §RAT trap wearing a fan-out: the pane was not empty, it was looking elsewhere.

    ONE grouped query over rows this developer already owns. No N+1, no cap, no sampling.

    ⚠ THE CAPTURE IS `[^"]+`, NOT `[a-z_]+`. The first version stopped at the first
    character outside the class, so `rate_per_hour_exceeded:max=30` — a spend refusal that
    carries its own limit inside the reason — matched nothing and was counted as
    `(unspecified)`. A reason class that silently excludes the reasons carrying the MOST
    detail is worse than no class at all. The FE splits on `:` for its sentence lookup and
    keeps the tail as evidence.

    ⚠ `security_audit_logs.details` is a **text** column holding JSON, not JSONB — the
    per-agent endpoint learned that the hard way (§MISUSEDETAIL: every denial arrived as
    `{}` for months because the code tested `isinstance(dict)`). The reason is therefore
    extracted with a regex over the text, and a row whose details cannot be parsed is
    counted under `(unspecified)` rather than dropped: a refusal we cannot label is still
    a refusal, and silently omitting it would understate the very number this pane exists
    to report.
    """
    _ACTIONS = [
        "ironkey.rbac_deny", "ironkey.spend_deny", "ironkey.org_ceiling_deny",
        "ironkey.capability_misuse", "ironkey.delegation_caveat_deny",
        "ironkey.capability_caveat_deny", "ironkey.capability_circuit_breaker_trip",
    ]
    params = {"d": current_developer.id, "acts": _ACTIONS, "days": days}

    summary_rows = (await db.execute(text(
        "SELECT l.action, "
        "       COALESCE(NULLIF(substring(l.details from '\"reason\"[: ]+\"([^\"]+)\"'), ''), '(unspecified)') AS reason, "
        "       count(*) AS n, max(l.timestamp) AS latest, count(DISTINCT l.actor_id) AS agents "
        "FROM security_audit_logs l "
        "JOIN agents a ON a.did = l.actor_id "
        "WHERE a.creator_developer_id = :d AND l.action = ANY(:acts) "
        "  AND l.timestamp > now() - make_interval(days => :days) "
        "GROUP BY 1, 2 ORDER BY n DESC LIMIT :lim"
    ), {**params, "lim": limit})).fetchall()

    ex_rows = []
    if examples:
        ex_rows = (await db.execute(text(
            "SELECT l.action, l.timestamp, l.actor_id, l.target_type, l.target_id, "
            "       l.severity, l.outcome, l.details, c.name "
            "FROM security_audit_logs l "
            "JOIN agents a ON a.did = l.actor_id "
            "LEFT JOIN agent_cards c ON c.agent_did = l.actor_id AND c.developer_id = :d "
            "WHERE a.creator_developer_id = :d AND l.action = ANY(:acts) "
            "  AND l.timestamp > now() - make_interval(days => :days) "
            "ORDER BY l.timestamp DESC LIMIT :lim"
        ), {**params, "lim": examples})).fetchall()

    def _reason(raw) -> Optional[str]:
        if not raw:
            return None
        try:
            d = json.loads(raw) if isinstance(raw, str) else raw
            return d.get("reason") if isinstance(d, dict) else None
        except Exception:  # noqa: BLE001
            return None

    total = sum(int(r[2]) for r in summary_rows)
    return {
        "window_days": days,
        "total": total,
        # ⚠ `total` is the sum of the summarised reasons, so a `limit` that truncates the
        # reason list also truncates the total. Said out loud rather than left to be
        # discovered: a figure whose scope is a query parameter has to declare it.
        "reasons_shown": len(summary_rows),
        "summary": [
            {"action": r[0], "reason": r[1], "count": int(r[2]),
             "latest": r[3].isoformat() if r[3] else None, "agents": int(r[4])}
            for r in summary_rows
        ],
        "examples": [
            {"action": e[0], "at": e[1].isoformat() if e[1] else None,
             "agent_did": e[2], "agent_name": e[8],
             "target_type": e[3], "target_id": e[4],
             "severity": e[5], "outcome": e[6], "reason": _reason(e[7])}
            for e in ex_rows
        ],
    }


# --- §BRIDGE R1 (2026-08-19) — the WHOLE fleet, as DIDs only ---
@router.get("/me/agent-dids", summary="List Developer's Agent DIDs (identity only)")
async def list_developer_agent_dids(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    Every agent DID this developer owns: identity only, no cards and no balances. When the list is truncated,
    `complete` is false and `total` keeps the real count. Needs a developer token.

    \f
    Every DID this developer owns. Identity only — no cards, no balances.

    WHY THIS EXISTS. Mission Control has to answer "is this event MINE?" for
    every event on the wire, which needs the developer's COMPLETE DID set.
    ``/me/agents`` is deliberately capped at 200 (hard cap 500) because it
    returns hydrated agents, and lifting that cap is exactly the 13MB-response
    + balance-fetch-storm that the cap was added to prevent. Paging it would be
    9 round trips on a landing page for an owner of 4,093 agents.

    A DID is ~36 bytes. The whole fleet of 4,093 is ~150KB of strings, one
    query, one response, no joins, no TEG calls. It answers the identity
    question and nothing else, which is the only question the bridge asks.

    Truncation is REPORTED, never silent: ``complete`` is false and ``total``
    still carries the real count, so the client can say "matching N of M"
    instead of quietly implying the rest of the fleet is idle.
    """
    response.headers["Cache-Control"] = "private, max-age=60"

    MAX_DIDS = 50_000

    total = (
        await db.execute(
            select(func.count())
            .select_from(models.Agent)
            .where(models.Agent.creator_developer_id == current_developer.id)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(models.Agent.did)
            .where(models.Agent.creator_developer_id == current_developer.id)
            .where(models.Agent.did.is_not(None))
            .order_by(models.Agent.created_at.desc())
            .limit(MAX_DIDS)
        )
    ).scalars().all()

    dids = [d for d in rows if d]
    logger.info(
        "agent-dids for developer %s: %d returned of %d owned",
        current_developer.id, len(dids), total,
    )
    return {
        "dids": dids,
        "count": len(dids),
        "total": int(total),
        "complete": len(dids) >= int(total),
    }


# --- ADDED: TEG Summary endpoint ---
@router.get("/me/teg-summary", response_model=schemas.TEGSummaryResponse, summary="Get Developer's TEG Summary")
async def get_teg_summary(
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
) -> schemas.TEGSummaryResponse:
    """
    Get aggregate TEG (Token Economic Graph) summary for the authenticated developer.
    
    Returns:
    - Total liquid balance across all agents
    - Total locked balance across all agents
    - Aggregate reputation score (average)
    - Total number of agents
    - Number of active agents
    """
    logger.info(f"Request to get TEG summary for developer ID: {current_developer.id}")
    
    # Query for all agents created by this developer
    stmt = (
        select(models.Agent)
        .where(models.Agent.creator_developer_id == current_developer.id)
    )
    result = await db.execute(stmt)
    agents = result.scalars().all()
    
    # Calculate aggregates
    total_liquid = sum(agent.liquid_balance for agent in agents)
    total_staked = sum(agent.staked_balance for agent in agents)
    total_balance = total_liquid + total_staked
    
    # Calculate average reputation (0 if no agents)
    aggregate_reputation = (
        sum(agent.reputation_score for agent in agents) / len(agents)
        if agents else 0.0
    )
    
    # Count active agents
    active_count = sum(1 for agent in agents if agent.status == "active")
    
    logger.info(
        f"TEG summary for developer {current_developer.id}: "
        f"{len(agents)} agents, {active_count} active, "
        f"total balance: {total_balance}"
    )
    
    # §ORGPOCKET O4 — every agent counted above is a row in THIS registry's
    # `agents` table (creator_developer_id = me), so the sum is denominated in
    # this frame's settlement currency and nothing else. Saying so travels with
    # the number.
    import os as _os
    _ccy = (_os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"

    return schemas.TEGSummaryResponse(
        total_liquid_balance=total_liquid,
        total_staked_balance=total_staked,
        total_balance=total_balance,
        aggregate_reputation_score=aggregate_reputation,
        agent_count=len(agents),
        active_agent_count=active_count,
        currency=_ccy,
    )
# --- END ADDED ---

# --- ADDED: Agent balance endpoints ---
@router.get("/me/agents/{agent_did}/balance", summary="Get Agent Balance")
async def get_agent_balance(
    agent_did: str = Path(..., description="The agent's DID"),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
) -> Dict[str, str]:
    """
    The balance of one of the developer's own active agents, in the frame's units, as the TEG reports it. Needs a
    developer token.
    """
    # Import the TEG integration functions
    from .teg_integration import get_teg_token_for_agent, prepare_teg_headers, TEG_API_BASE_URL, TEG_API_V1_PREFIX
    
    # Verify agent belongs to current developer
    stmt = select(models.Agent).where(
        models.Agent.did == agent_did,
        models.Agent.creator_developer_id == current_developer.id,
        models.Agent.status == "active"
    )
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(404, "Agent not found or not authorized")
    
    try:
        # Get proper TEG JWT token using the teg_integration module
        teg_token = await get_teg_token_for_agent(agent.id, agent_did)
        
        # Prepare headers based on token type (JWT, Service, or Admin Impersonate)
        headers = prepare_teg_headers(teg_token)
        
        # Make request to TEG with proper authentication
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 200:
                teg_data = response.json()
                balance = teg_data.get("balance", "0")
            elif response.status_code == 401:
                logger.error(f"TEG authentication failed for agent {agent_did}")
                balance = "0"
            else:
                logger.error(f"TEG returned {response.status_code}: {response.text}")
                balance = "0"
        
        return {
            "agent_did": agent_did,
            "balance": balance,
            "currency": _FRAME_CCY
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch balance for agent {agent_did}: {str(e)}")
        return {
            "agent_did": agent_did,
            "balance": "0",
            "currency": _FRAME_CCY,
            "error": "Unable to fetch balance"
        }


@router.post("/me/agents/balances", summary="Get Multiple Agent Balances")
async def get_agent_balances_batch(
    request: Dict[str, List[str]] = Body(..., example={"agent_dids": ["did:cos:example1", "did:cos:example2"]}),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
) -> Any:
    """
    Get token balances for multiple agents in one request.
    
    Efficient batch endpoint to retrieve balances for up to 50 agents at once.
    Returns a dictionary mapping agent DIDs to their balance information.
    
    FIXED: Now handles partial failures gracefully - if some agents are invalid
    or balance fetches fail, valid agents still return their correct balances.
    """
    agent_dids = request.get("agent_dids", [])
    
    if not agent_dids:
        return {"balances": {}}
    
    # Limit batch size
    if len(agent_dids) > 50:
        raise HTTPException(400, "Maximum 50 agents per batch request")
    
    # First, verify which agents belong to current developer
    stmt = select(models.Agent).where(
        models.Agent.did.in_(agent_dids),
        models.Agent.creator_developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    valid_agents = {agent.did: agent for agent in result.scalars().all()}
    
    logger.info(
        f"Batch balance request for {len(agent_dids)} agents, "
        f"{len(valid_agents)} belong to developer {current_developer.id}"
    )
    
    # Prepare response
    balances = {}
    
    # Import the TEG integration functions
    from .teg_integration import get_teg_token_for_agent, prepare_teg_headers, TEG_API_BASE_URL, TEG_API_V1_PREFIX
    
    # Helper function to fetch a single agent's balance
    async def fetch_single_balance(client: httpx.AsyncClient, did: str, agent: models.Agent) -> tuple[str, dict]:
        """Fetch balance for a single agent, return (did, balance_data)"""
        try:
            # Check if agent is active
            if agent.status in ("suspended", "revoked"):
                return did, {
                    "balance": "0",
                    "currency": _FRAME_CCY,
                    "error": f"Agent is {agent.status}"
                }
            
            # Get proper TEG JWT token using the teg_integration module
            teg_token = await get_teg_token_for_agent(agent.id, did)
            
            # Prepare headers based on token type (JWT, Service, or Admin Impersonate)
            headers = prepare_teg_headers(teg_token)
            
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                headers=headers,
                timeout=5.0  # Reduced timeout for batch operations
            )
            
            if response.status_code == 200:
                teg_data = response.json()
                balance = teg_data.get("balance", "0")
                return did, {
                    "balance": balance,
                    "currency": _FRAME_CCY
                }
            elif response.status_code == 401:
                logger.warning(f"TEG authentication failed for agent {did}")
                return did, {
                    "balance": "0",
                    "currency": _FRAME_CCY,
                    "error": "Authentication failed"
                }
            else:
                logger.warning(f"TEG returned {response.status_code} for agent {did}")
                return did, {
                    "balance": "0",
                    "currency": _FRAME_CCY,
                    "error": f"TEG error: {response.status_code}"
                }
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching balance for agent {did}")
            return did, {
                "balance": "0",
                "currency": _FRAME_CCY,
                "error": "Request timeout"
            }
        except Exception as e:
            logger.error(f"Failed to fetch balance for agent {did}: {str(e)}")
            return did, {
                "balance": "0",
                "currency": _FRAME_CCY,
                "error": "Unable to fetch balance"
            }
    
    # Fetch balances concurrently for all valid agents
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        # Create tasks for all valid agents
        tasks = []
        for did, agent in valid_agents.items():
            tasks.append(fetch_single_balance(client, did, agent))
        
        # Execute all tasks concurrently
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Task failed with exception: {result}")
                else:
                    did, balance_data = result
                    balances[did] = balance_data
    
    # Add error responses for agents not found or not authorized
    for did in agent_dids:
        if did not in balances:
            if did not in valid_agents:
                balances[did] = {
                    "balance": "0",
                    "currency": _FRAME_CCY,
                    "error": "Agent not found or not authorized"
                }
            else:
                # This shouldn't happen, but just in case
                balances[did] = {
                    "balance": "0",
                    "currency": _FRAME_CCY,
                    "error": "Balance fetch failed"
                }
    
    # Log summary
    successful_fetches = sum(1 for b in balances.values() if "error" not in b)
    logger.info(
        f"Batch balance response: {successful_fetches}/{len(agent_dids)} successful, "
        f"{len(agent_dids) - successful_fetches} failed"
    )
    
    return {"balances": balances}
# --- END ADDED ---


# §FEFRAME W3 (V0504): acting as your own agent needs no secret. A signed-in developer mints a short agent token for an
# agent it created on THIS registry (the same claims /auth/agent/token issues, plus `via: owner` and the owner's id and
# token_version: security.create_owner_session_token). It lives OWNER_SESSION_TOKEN_MINUTES (default 30) and only while
# the session that minted it could act: a logout everywhere, a password change, a suspension, a deletion or a transfer
# ends it on the next request (security.owner_token_refusal). Refused for an API key (a scoped programmatic key must not
# become an agent's full authority), for an agent that is not the caller's or is not active. One audit row per mint.
def owner_mint_refusal(agent: Optional[models.Agent], developer: models.Developer, bearer: str) -> Optional[tuple]:
    """(status, detail) when the mint is refused, else None. Pure: the route and tests/test_owner_session_token.py."""
    if (bearer or "").startswith("avreg_"):
        return (status.HTTP_403_FORBIDDEN,
                "An owner session token is minted from a signed-in session, not from an API key: sign in, or use the "
                "agent's own credential.")
    if agent is None or getattr(agent, "creator_developer_id", None) != developer.id:
        return (status.HTTP_404_NOT_FOUND, "Agent not found or not yours")
    if getattr(agent, "status", None) != "active":
        return (status.HTTP_403_FORBIDDEN,
                f"This agent is {getattr(agent, 'status', None) or 'not active'}: it cannot act, so no token is minted.")
    if (getattr(agent, "enforcement_status", None) or "active") in ("suspended", "revoked"):
        return (status.HTTP_403_FORBIDDEN, f"This agent is {agent.enforcement_status} by its registry's enforcement.")
    return None


@router.post("/me/agents/{agent_did}/session-token", response_model=schemas.OwnerSessionToken,
             summary="Issue a short agent token for an agent you own (no client secret)")
@limiter.limit("30/minute")
async def mint_owner_session_token(
    request: Request,
    response: Response,
    agent_did: str = Path(..., description="The DID of an agent you created on this registry"),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
) -> schemas.OwnerSessionToken:
    from ..core.client_ip import effective_client_ip
    from ..core.public_url import credential_home_url
    from ..services.admin_audit import log_session_action
    auth = request.headers.get("authorization") or ""
    bearer = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    agent = (await db.execute(select(models.Agent).where(models.Agent.did == agent_did))).scalar_one_or_none()
    refused = owner_mint_refusal(agent, current_developer, bearer)
    if refused:
        await log_session_action(db, action="owner_token.refused", actor_id=str(current_developer.id),
                                 actor_ip=effective_client_ip(request), target_type="agent", target_id=agent_did,
                                 outcome="denied", severity="warning", details={"status": refused[0]})
        raise HTTPException(status_code=refused[0], detail=refused[1])
    token, lifetime = security.create_owner_session_token(agent, current_developer)
    await log_session_action(db, action="owner_token.mint", actor_id=str(current_developer.id),
                             actor_ip=effective_client_ip(request), target_type="agent", target_id=agent_did,
                             details={"expires_in": lifetime})
    return schemas.OwnerSessionToken(access_token=token, expires_in=lifetime, agent_did=agent_did,
                                     registry_url=credential_home_url())


# --- ADDED: Agent deletion endpoint ---
@router.delete("/me/agents/{agent_did}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Developer's Agent")
async def delete_developer_agent(
    agent_did: str = Path(..., description="The agent's DID to delete"),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer)
) -> None:
    """
    Delete (deactivate) an agent owned by the authenticated developer.
    
    This endpoint allows developers to delete their agents by setting the status to 'revoked'.
    The agent's credentials will no longer be valid after this operation.
    
    Note: This is a soft delete - the agent record remains in the database
    but is marked as revoked.
    """
    logger.info(f"Developer {current_developer.id} requested to delete agent {agent_did}")
    
    # Verify agent belongs to current developer
    stmt = select(models.Agent).where(
        models.Agent.did == agent_did,
        models.Agent.creator_developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        logger.warning(f"Agent {agent_did} not found or not owned by developer {current_developer.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found or not authorized"
        )
    
    if agent.status == "revoked":
        logger.info(f"Agent {agent_did} is already revoked")
        # OWL24: Even if already revoked, ensure cards are deactivated
        # (idempotent cleanup for agents revoked before this fix)
        card_stmt = select(models.AgentCard).where(
            models.AgentCard.agent_did == agent_did,
            models.AgentCard.is_active == True
        )
        card_result = await db.execute(card_stmt)
        orphan_cards = card_result.scalars().all()
        if orphan_cards:
            for card in orphan_cards:
                card.is_active = False
                logger.info(f"OWL24: Deactivated orphan card {card.id} for already-revoked agent {agent_did}")
            await db.commit()
        return None
    
    # Update agent status to revoked
    old_status = agent.status
    agent.status = "revoked"

    # OWL24: Cascade — deactivate all agent cards linked to this agent
    card_stmt = select(models.AgentCard).where(
        models.AgentCard.agent_did == agent_did,
        models.AgentCard.is_active == True
    )
    card_result = await db.execute(card_stmt)
    cards_to_deactivate = card_result.scalars().all()
    
    for card in cards_to_deactivate:
        card.is_active = False
        logger.info(f"OWL24: Deactivating card {card.id} (cascade from agent revocation)")
    
    await db.commit()
    
    logger.info(
        f"Agent {agent_did} has been revoked by developer {current_developer.id}. "
        f"{len(cards_to_deactivate)} card(s) deactivated."
    )

    # §DOCSFIX D6-267 (2026-10-16): the owner's delete reports itself as the agent's own delete does
    # (DELETE /agents/me): AgentStatusChanged on the ledger, agent.deleted and agent.status_changed to the
    # owner's webhooks. Advisory and after the commit: the revocation stands whatever happens to a notice.
    from agentvault_registry.event_emitter import get_event_emitter
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_event
    asyncio.create_task(dispatch_webhook_event(
        "agent.deleted",
        {"agent_did": agent_did, "mode": "soft", "deleted_by": "developer"},
        source_label="developers.delete_agent", developer_id=current_developer.id))
    asyncio.create_task(dispatch_webhook_event(
        "agent.status_changed",
        {"agent_did": agent_did, "old_status": old_status, "new_status": "revoked",
         "reason": "developer_delete"},
        source_label="developers.delete_agent", developer_id=current_developer.id))
    asyncio.create_task(get_event_emitter().emit(
        event_type="AgentStatusChanged",
        aggregate_id=agent_did,
        data={"old_status": old_status, "new_status": "revoked", "reason": "developer_deletion"},
    ))

    # Return 204 No Content
    return None
# --- END ADDED ---


@router.get("/stats")
async def get_developer_stats(
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)],
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Get usage statistics for the current developer."""
    logger.info(f"Getting stats for developer {current_developer.id}")
    
    # Count developer's agents
    stmt = select(models.Agent).where(models.Agent.creator_developer_id == current_developer.id)
    result = await db.execute(stmt)
    agents = result.scalars().all()
    agent_count = len(agents)
    
    total_tokens = sum(float(a.liquid_balance or 0) + float(a.staked_balance or 0) for a in agents)

    return {
        "today": {
            "requests": 0,
            "limit": 10000,
            "agents": agent_count,
            "tokens": total_tokens
        },
        "month": {
            "requests": 0,
            "limit": 100000,
            "agents": agent_count,
            "tokens": total_tokens
        },
        "topEndpoints": [],
        "note": "Request metrics not yet implemented — agent count and token balances are real"
    }


@router.get("/webhooks")
async def list_developer_webhooks(
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)],
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> List[Dict[str, Any]]:
    """List all webhooks for the current developer."""
    stmt = select(models.DeveloperWebhook).where(
        models.DeveloperWebhook.developer_id == current_developer.id
    ).order_by(models.DeveloperWebhook.created_at.desc())
    result = await db.execute(stmt)
    webhooks = result.scalars().all()
    return [
        {
            "id": wh.id,
            "url": wh.url,
            "events": wh.events,
            "active": wh.is_active,
            "created_at": wh.created_at.isoformat() if wh.created_at else None,
            "last_triggered": wh.last_triggered_at.isoformat() if wh.last_triggered_at else None,
            "failure_count": wh.failure_count,
        }
        for wh in webhooks
    ]


# Activity endpoint removed - duplicate definition exists below


async def _refuse_unsafe_webhook_url(url: Any) -> None:
    """D6-760 (2026-10-16): this older pair of routes stored any URL unchecked. Every webhook URL now passes the
    canonical validator (input_validators.validate_webhook_url: http(s), no literal internal address, no metadata
    host, and a host that does not resolve to an internal address), with the lookup off the event loop."""
    from agentvault_registry.input_validators import avalidate_webhook_url
    if not isinstance(url, str) or len(url) > 500:
        raise HTTPException(400, "URL must be a string of at most 500 characters")
    try:
        await avalidate_webhook_url(url)
    except ValueError as e:
        raise HTTPException(400, f"Invalid webhook URL: {e}")


@router.post("/webhooks", status_code=201)
async def create_developer_webhook(
    webhook_data: Dict[str, Any] = Body(..., example={
        "url": "https://example.com/webhook",
        "events": ["agent.created", "agent.updated"]
    }),
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Create a new webhook for the current developer."""
    url = webhook_data.get("url")
    events = webhook_data.get("events", [])

    if not url:
        raise HTTPException(400, "URL is required")
    if not events:
        raise HTTPException(400, "At least one event must be specified")
    await _refuse_unsafe_webhook_url(url)

    # Enforce max 10 webhooks per developer
    stmt = select(models.DeveloperWebhook).where(
        models.DeveloperWebhook.developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    existing = result.scalars().all()
    if len(existing) >= 10:
        raise HTTPException(400, "Maximum of 10 webhooks per developer")

    # Validate event types
    valid_events = set(WebhookService.SUPPORTED_EVENTS)
    invalid = [e for e in events if e not in valid_events]
    if invalid:
        raise HTTPException(400, f"Unknown event types: {invalid}")

    webhook_id = f"wh-{uuid.uuid4().hex[:16]}"
    webhook_secret = f"whsec_{secrets.token_urlsafe(32)}"

    webhook = models.DeveloperWebhook(
        id=webhook_id,
        developer_id=current_developer.id,
        url=url,
        events=events,
        secret=webhook_secret,
        is_active=True,
        failure_count=0,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    logger.info(f"Created webhook {webhook_id} for developer {current_developer.id}")
    return {
        "id": webhook.id,
        "url": webhook.url,
        "events": webhook.events,
        "active": webhook.is_active,
        "created_at": webhook.created_at.isoformat() if webhook.created_at else None,
        "secret": webhook_secret,  # only returned on create
    }


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_developer_webhook(
    webhook_id: str,
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
):
    """Delete a webhook for the current developer, and its delivery history with it."""
    # locked first, as on DELETE /webhooks/{id}: a delivery recorded between the two deletes must not fail this one
    stmt = select(models.DeveloperWebhook).where(
        models.DeveloperWebhook.id == webhook_id,
        models.DeveloperWebhook.developer_id == current_developer.id
    ).with_for_update()
    result = await db.execute(stmt)
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    # §DOCSFIX D6-761 (2026-10-16): the deliveries go first, in the same transaction, as on DELETE /webhooks/{id}:
    # webhook_deliveries.webhook_id has no ON DELETE CASCADE, so a webhook that had ever delivered could not be
    # deleted here at all.
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(models.WebhookDelivery).where(models.WebhookDelivery.webhook_id == webhook.id))
    await db.delete(webhook)
    await db.commit()
    logger.info(f"Deleted webhook {webhook_id} for developer {current_developer.id}")
    return None


@router.put("/webhooks/{webhook_id}")
async def update_developer_webhook(
    webhook_id: str,
    webhook_data: Dict[str, Any] = Body(..., example={
        "active": False,
        "events": ["agent.created"]
    }),
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Update a webhook for the current developer."""
    stmt = select(models.DeveloperWebhook).where(
        models.DeveloperWebhook.id == webhook_id,
        models.DeveloperWebhook.developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(404, "Webhook not found")

    if "url" in webhook_data:
        await _refuse_unsafe_webhook_url(webhook_data["url"])
        webhook.url = webhook_data["url"]
    if "events" in webhook_data:
        events = webhook_data["events"]
        invalid = [e for e in events if e not in set(WebhookService.SUPPORTED_EVENTS)]
        if invalid:
            raise HTTPException(400, f"Unknown event types: {invalid}")
        webhook.events = events
    if "active" in webhook_data:
        webhook.is_active = bool(webhook_data["active"])
        if webhook.is_active:
            webhook.failure_count = 0  # reset failures when re-enabling

    await db.commit()
    await db.refresh(webhook)
    logger.info(f"Updated webhook {webhook_id} for developer {current_developer.id}")
    return {
        "id": webhook.id,
        "url": webhook.url,
        "events": webhook.events,
        "active": webhook.is_active,
        "created_at": webhook.created_at.isoformat() if webhook.created_at else None,
        "updated_at": webhook.updated_at.isoformat() if webhook.updated_at else None,
        "last_triggered": webhook.last_triggered_at.isoformat() if webhook.last_triggered_at else None,
        "failure_count": webhook.failure_count,
    }


@router.post("/webhooks/{webhook_id}/test")
async def test_developer_webhook(
    webhook_id: str,
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Send a test payload to a webhook endpoint."""
    stmt = select(models.DeveloperWebhook).where(
        models.DeveloperWebhook.id == webhook_id,
        models.DeveloperWebhook.developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    if not webhook.is_active:
        raise HTTPException(400, "Webhook is disabled")

    svc = WebhookService()
    delivery = await svc.deliver_webhook(
        webhook=webhook,
        event_type="test.ping",
        data={"message": "TheProtocol webhook test", "developer_id": current_developer.id},
        agent_did=None,
        db=db
    )
    return {
        "delivery_id": delivery.id,
        "status": delivery.response_status,
        "success": delivery.response_status is not None and 200 <= delivery.response_status < 300,
        "error": delivery.error_message,
    }


@router.get("/webhooks/{webhook_id}/deliveries")
async def list_webhook_deliveries(
    webhook_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Get delivery history for a webhook."""
    # Ownership check
    stmt = select(models.DeveloperWebhook).where(
        models.DeveloperWebhook.id == webhook_id,
        models.DeveloperWebhook.developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(404, "Webhook not found")

    # Count total
    count_stmt = select(func.count()).select_from(models.WebhookDelivery).where(
        models.WebhookDelivery.webhook_id == webhook_id
    )
    total = (await db.execute(count_stmt)).scalar()

    # Fetch page
    page_stmt = select(models.WebhookDelivery).where(
        models.WebhookDelivery.webhook_id == webhook_id
    ).order_by(models.WebhookDelivery.delivered_at.desc()).limit(limit).offset(offset)
    page_result = await db.execute(page_stmt)
    deliveries = page_result.scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "deliveries": [
            {
                "id": d.id,
                "event_type": d.event_type,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "response_status": d.response_status,
                "retry_count": d.retry_count,
                "error": d.error_message,
                "success": d.response_status is not None and 200 <= d.response_status < 300,
            }
            for d in deliveries
        ]
    }


@router.get("/activity")
async def get_developer_activity(
    days: int = Query(30, ge=1, le=365),
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> List[Dict[str, Any]]:
    """Get API activity for the current developer over the specified days."""
    logger.info(f"Getting {days} days of activity for developer {current_developer.id}")
    
    return [{
        "date": datetime.now().date().isoformat(),
        "calls": 0,
        "errors": 0,
        "unique_agents": 0,
        "note": "Activity metrics not yet implemented"
    }]


logger.info("Developer router initialized with improved batch balance endpoint.")


# ── §POCKETBRIDGE3: synced developer prefs (mig 0152) ────────────────────────
# A tiny allowlisted key/value rail so the Pocket watchlist and price-alert
# rules FOLLOW THE ACCOUNT (D3-2 synced) instead of living in one browser's
# localStorage. Deliberately not a general store: unknown keys 404, values are
# size-capped, and the shape inside `value` belongs to the FE + the
# price_alert_watcher, not to this router.

_PREF_KEYS = {"pocket.watchlist", "pocket.price_alerts", "pocket.assistant",
              # §OURSTATE-2 Away mode v1 (the stage-only Bouncer): which agent
              # answers strangers while you are away, plus per-thread silences.
              # A DESIGNATION, never an authority — the stand-in spends nothing.
              "pocket.away",
              # §OURSTATE-4 PULSE — the opt-in economy feed. Off by default;
              # the absence of a row means OFF, never "not configured yet".
              "pocket.pulse",
              # §COCKPIT P1 (2026-08-31) — saved desk layouts (which panes, where).
              # A PREFERENCE, never authority: the value decides what a human sees,
              # never what anything may do. Whole-value replace like every other key.
              "cockpit.layouts",
              # §DASHARRANGE (2026-09-02) — the dashboard's ONE layout (panes + sizes), separate
              # from the desk's named layouts on purpose: one board per person, no name to collide.
              "cockpit.dashboard"}
_PREF_MAX_BYTES = 16 * 1024


@router.get("/me/prefs/{key}")
async def get_my_pref(
    key: str,
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    """Read one synced preference. Unset is `value: null`: absence, not an error."""
    if key not in _PREF_KEYS:
        raise HTTPException(404, f"Unknown pref key '{key}' (allowed: {sorted(_PREF_KEYS)})")
    row = (
        await db.execute(
            select(models.DeveloperPref).where(
                models.DeveloperPref.developer_id == current_developer.id,
                models.DeveloperPref.key == key,
            )
        )
    ).scalar_one_or_none()
    return {
        "key": key,
        "value": row.value if row else None,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


@router.put("/me/prefs/{key}")
async def put_my_pref(
    key: str,
    body: Dict[str, Any] = Body(..., example={"value": {"starred": [{"symbol": "QCC"}]}}),
    current_developer: Annotated[models.Developer, Depends(security.get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    """Replace one synced preference (a whole-value PUT; the console owns the shape)."""
    if key not in _PREF_KEYS:
        raise HTTPException(404, f"Unknown pref key '{key}' (allowed: {sorted(_PREF_KEYS)})")
    if "value" not in body:
        raise HTTPException(422, "Body must carry a 'value' field")
    value = body["value"]
    import json as _json
    try:
        encoded = _json.dumps(value)
    except (TypeError, ValueError):
        raise HTTPException(422, "value must be JSON-serializable")
    if len(encoded.encode("utf-8")) > _PREF_MAX_BYTES:
        raise HTTPException(413, f"value exceeds {_PREF_MAX_BYTES} bytes")
    from sqlalchemy.dialects.postgresql import insert as _pg_insert
    stmt = (
        _pg_insert(models.DeveloperPref)
        .values(developer_id=current_developer.id, key=key, value=value, updated_at=func.now())
        .on_conflict_do_update(
            index_elements=["developer_id", "key"],
            set_={"value": value, "updated_at": func.now()},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"key": key, "value": value, "saved": True}


# ---------------------------------------------------------------------------
# §COCKPITMODULES M1 — "WHAT DIDN'T HAPPEN": the things this account TRIED and
# that FAILED, in one grouped read per source.
# ---------------------------------------------------------------------------

# A deployment that started and never reported an outcome is stuck, not running.
# One hour is generous: the real ones on this account complete in seconds.
_STUCK_DEPLOY_HOURS = 1


@router.get("/me/failures",
            summary="What this account tried that did not happen")
async def my_failures(
    limit: int = Query(12, ge=1, le=50, description="Rows to name per source."),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    What this account tried that did not happen: payouts on locked units that failed, webhook deliveries, agent instructions
    and deployments. Every source is always listed with its `open` count (zero included) and its age, and
    `open_total` sums them. Needs a developer token.

    \f
    The mirror of DENIALS. That pane shows what the gates REFUSED — a system working.
    This shows what the system TRIED AND FAILED — a system that owes someone something.

    🔴 WHY THIS EXISTS. Every surface in this project renders successes. `grep` for a retry
    over `staking_reward_records` returns NOTHING: a payout that fails is written to a row
    with an `error_message` and never looked at again by any code path. That is the whole
    reason **66,326 units of payouts on locked units sat undelivered for three months** while
    the system that owed it ran perfectly. Nobody was watching the failures because nothing
    showed them.

    ⚠ EVERY SOURCE REPORTS ITS AGE, NEVER ONLY ITS COUNT (§CARDPULLTICK). A verdict with no
    timestamp is indistinguishable from a fossil, and three of these sources are historical:
    a pane that implied May 2026 failures were current would be its own defect.

    ⚠ A HEALTHY SOURCE RENDERS AS HEALTHY, IT DOES NOT VANISH (§RAT). "Nothing failed" and
    "we did not look" are different facts, so every source is always in the response with an
    explicit `open` count — including zero.

    ⚠ ONE GROUPED QUERY PER SOURCE, never a fan-out. The §COCKPITSHOW denials pane sampled
    the top agents BY BALANCE and reported "no refusals" over 3,357 real ones.

    ⚠ THE ROUTE IS `me/failures` AND CARRIES NO OTHER SURFACE'S PATH FRAGMENT. The frontend
    classifies auth tier by SUBSTRING, so a developer route containing `/exchange/` inherits
    agent tier and 401s in the browser while a script gets 200 (§COCKPITBOOK).

    ⚠ CARD PULL-SYNC IS DELIBERATELY NOT A SOURCE HERE. Measured on this account:
    `last_pulled_at` is set on **12 of 4,109** cards. The other 4,097 were never pull
    CANDIDATES (they publish no well-known to pull), so rendering them as 4,097 failures
    would bury the four rows that are real. That is a fleet characteristic, not a failure
    list, and it is named in the docs rather than shown here.
    """
    dev_id = current_developer.id
    lim = max(1, min(int(limit or 12), 50))
    sources: List[Dict[str, Any]] = []

    # ---- 1. Payouts on locked units that were owed and never delivered -----------
    rows = (await db.execute(text("""
        SELECT r.id, r.agent_did, c.name AS agent_name, r.reward_amount,
               r.distribution_id, r.created_at, r.error_message
        FROM staking_reward_records r
        JOIN agents a ON a.did = r.agent_did AND a.creator_developer_id = :dev
        LEFT JOIN agent_cards c ON c.agent_did = r.agent_did
        WHERE r.error_message IS NOT NULL AND r.teg_transaction_id IS NULL
        ORDER BY r.reward_amount DESC LIMIT :lim
    """), {"dev": dev_id, "lim": lim})).mappings().all()
    agg = (await db.execute(text("""
        SELECT count(*) AS n, coalesce(sum(r.reward_amount), 0) AS amt, max(r.created_at) AS last
        FROM staking_reward_records r
        JOIN agents a ON a.did = r.agent_did AND a.creator_developer_id = :dev
        WHERE r.error_message IS NOT NULL AND r.teg_transaction_id IS NULL
    """), {"dev": dev_id})).mappings().first() or {}
    ever = (await db.execute(text("""
        SELECT max(r.created_at) AS last
        FROM staking_reward_records r
        JOIN agents a ON a.did = r.agent_did AND a.creator_developer_id = :dev
        WHERE r.error_message IS NOT NULL
    """), {"dev": dev_id})).scalar()
    sources.append({
        "key": "rewards",
        "title": "Payouts on locked units never delivered",
        # The ONLY source with an action, because it is the only one where re-driving is
        # both safe (TEG dedups on the original key) and the right remedy.
        "redrivable": True,
        "open": int(agg.get("n") or 0),
        "amount": str(agg.get("amt") or 0),
        "currency": _FRAME_CCY,
        "last_open_at": agg.get("last").isoformat() if agg.get("last") else None,
        "last_ever_at": ever.isoformat() if ever else None,
        "sentence": (
            "Owed, computed, and never paid. Nothing in this codebase retries one."
        ),
        "rows": [{
            "id": str(r["id"]),
            "agent_did": r["agent_did"],
            "agent_name": r["agent_name"],
            "amount": str(r["reward_amount"]),
            "currency": _FRAME_CCY,
            "at": r["created_at"].isoformat() if r["created_at"] else None,
            "detail": (r["error_message"] or "")[:160],
        } for r in rows],
    })

    # ---- 2. Webhook deliveries that never landed -------------------------------
    # §DOCSFIX D6-786: every answer but a 2xx (a 3xx too: not followed, retried like any failure), or none at all; the
    # rule of services/webhook_service.delivery_outcome_clause ("failed" or "pending")
    wrows = (await db.execute(text("""
        SELECT w.id AS webhook_id, w.url, w.is_active,
               count(*) AS bad, max(d.delivered_at) AS last
        FROM webhook_deliveries d
        JOIN developer_webhooks w ON w.id = d.webhook_id AND w.developer_id = :dev
        WHERE d.response_status IS NULL OR NOT (d.response_status BETWEEN 200 AND 299)
        GROUP BY w.id, w.url, w.is_active
        ORDER BY count(*) DESC LIMIT :lim
    """), {"dev": dev_id, "lim": lim})).mappings().all()
    # ⚠ A DISABLED ENDPOINT IS NOT AN OPEN FAILURE. The retry worker turning a dead URL off
    # is the system working; counting those 11 rows as live would have had me report "11
    # notifications you think you are receiving and are not" about an endpoint that has
    # been correctly off since May, while the real webhook ran 83/83.
    open_bad = sum(int(r["bad"]) for r in wrows if r["is_active"])
    sources.append({
        "key": "webhooks",
        "title": "Webhook deliveries that never landed",
        "redrivable": False,
        "open": open_bad,
        "last_open_at": max([r["last"].isoformat() for r in wrows
                             if r["is_active"] and r["last"]] or [None]) if wrows else None,
        "last_ever_at": max([r["last"].isoformat() for r in wrows if r["last"]] or [None]) if wrows else None,
        "sentence": "A notification you believe you are receiving and are not.",
        "rows": [{
            "id": str(r["webhook_id"]),
            "label": r["url"],
            "count": int(r["bad"]),
            "at": r["last"].isoformat() if r["last"] else None,
            # The distinction that makes this row readable rather than alarming.
            "muted": not r["is_active"],
            "detail": ("this endpoint is switched off — the retry worker disabled it after "
                       "repeated failures, so these are not deliveries you are still missing"
                       if not r["is_active"] else "this endpoint is live and is dropping deliveries"),
        } for r in wrows],
    })

    # ---- 3. Instructions that did not arrive -----------------------------------
    # ⚠ The stored action carries the helper's `admin.` prefix (§V0177); the unprefixed
    # name matches nothing.
    irows = (await db.execute(text("""
        SELECT l.timestamp, l.target_id, l.details, c.name AS agent_name
        FROM security_audit_logs l
        LEFT JOIN agent_cards c ON c.agent_did = l.target_id AND c.developer_id = :dev
        WHERE l.action = 'admin.cockpit.agent.instruct' AND l.actor_id = :actor
          AND l.outcome = 'failure'
        ORDER BY l.timestamp DESC LIMIT :lim
    """), {"dev": dev_id, "actor": str(dev_id), "lim": lim})).mappings().all()
    iever = (await db.execute(text("""
        SELECT max(timestamp) FROM security_audit_logs
        WHERE action = 'admin.cockpit.agent.instruct' AND actor_id = :actor
    """), {"actor": str(dev_id)})).scalar()
    idet: List[Dict[str, Any]] = []
    for r in irows:
        d: Dict[str, Any] = {}
        if r["details"]:
            try:
                parsed = json.loads(r["details"])
                if isinstance(parsed, dict):
                    d = parsed
            except Exception:  # noqa: BLE001
                d = {}
        idet.append({
            "id": (r["timestamp"].isoformat() if r["timestamp"] else "") + ":" + (r["target_id"] or ""),
            "agent_did": r["target_id"],
            "agent_name": r["agent_name"],
            "at": r["timestamp"].isoformat() if r["timestamp"] else None,
            "detail": str(d.get("detail") or d.get("outcome") or "did not arrive")[:160],
        })
    sources.append({
        "key": "instructions",
        "title": "Instructions that did not arrive",
        "redrivable": False,
        "open": len(idet),
        "last_open_at": idet[0]["at"] if idet else None,
        "last_ever_at": iever.isoformat() if iever else None,
        "sentence": "You told an agent to do something and it never heard you.",
        "rows": idet,
    })

    # ---- 4. Deployments that started and never finished ------------------------
    # A deployment stuck in `running` is the quietest failure of the four: nothing errored,
    # so nothing anywhere says it went wrong.
    drows = (await db.execute(text("""
        SELECT d.id, d.agent_did, c.name AS agent_name, d.status, d.environment,
               d.started_at, d.error_message,
               EXTRACT(epoch FROM (now() - d.started_at)) / 3600.0 AS hours
        FROM agent_deployments d
        JOIN agents a ON a.did = d.agent_did AND a.creator_developer_id = :dev
        LEFT JOIN agent_cards c ON c.agent_did = d.agent_did
        WHERE d.status = 'failed'
           OR (d.status = 'running' AND d.started_at < now() - (:hrs || ' hours')::interval)
        ORDER BY d.started_at DESC LIMIT :lim
    """), {"dev": dev_id, "lim": lim, "hrs": str(_STUCK_DEPLOY_HOURS)})).mappings().all()
    sources.append({
        "key": "deployments",
        "title": "Deployments that never finished",
        "redrivable": False,
        "open": len(drows),
        "last_open_at": drows[0]["started_at"].isoformat() if drows and drows[0]["started_at"] else None,
        "last_ever_at": drows[0]["started_at"].isoformat() if drows and drows[0]["started_at"] else None,
        "sentence": "Started, then silence — no success, no error, no end.",
        "rows": [{
            "id": str(r["id"]),
            "agent_did": r["agent_did"],
            "agent_name": r["agent_name"],
            "at": r["started_at"].isoformat() if r["started_at"] else None,
            "label": f"{r['status']} · {r['environment'] or 'production'}",
            "detail": (r["error_message"] or
                       f"still 'running' after {float(r['hours'] or 0):.1f} hours")[:160],
        } for r in drows],
    })

    return {
        "sources": sources,
        "open_total": sum(int(s["open"]) for s in sources),
        "currency": _FRAME_CCY,
    }


@router.post("/me/failures/rewards/{record_id}/redrive",
             summary="Pay one failed payout record of my agents (owner only)")
async def redrive_reward(
    record_id: str = Path(..., description="The staking_reward_records id."),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    Pay one payout record of the developer's agents that failed, with the record's original idempotency key.
    A record that is not the developer's, or that is already paid, answers 404. A payout on locked units is a switch
    per registry (`STAKING_REWARDS_ENABLED`): discretionary, paid in platform units, off on the public network,
    where this answers 403 and the record stays listed. Needs a developer token.

    \f
    §COCKPITMODULES M0 — the durable half of the 66,326 AVT finding.

    🔴 THE GAP THIS CLOSES. Nothing in this codebase ever retried a failed payout record.
    The distributor wrote an `error_message` and moved on; no worker, no sweep, no alert
    ever read that column again. Sixteen records — 66,326 AVT — sat that way from May to
    August while every dashboard reported a healthy system.

    🔴 AND IT IS DELIBERATELY **NOT** AN UNATTENDED RETRY WORKER. A loop that moves money on
    its own is exactly the unattended money movement this project gates everywhere else, and
    the one-off execute for these sixteen was itself blocked by a permission gate — correctly,
    for a transfer that size. So the machine stops being the thing that FORGETS, and the
    human stays the thing that PAYS: the failures are shown, and a person presses this.

    🔴 WHAT MAKES THIS EXACTLY-ONCE IS THE ROW STATE — AND I HAD THIS WRONG AT FIRST.
    The WHERE clause above requires `error_message IS NOT NULL AND teg_transaction_id IS
    NULL`. A successful redrive writes the tx id, so the row can never match again: a second
    press gets the same 404 as a stranger's id. That guard does not expire.

    ⚠ IT IS **NOT** THE IDEMPOTENCY KEY, WHICH IS WHAT I ORIGINALLY CLAIMED HERE. The key
    is still the original `staking-{distribution_id}-{agent_did}` and passing it is still
    right — but MEASURED, `teg_idempotency_records.expires_at` is `created_at + 24 HOURS`.
    A payout that failed in May has no surviving cache entry, so there is nothing to dedup
    against and the money simply moves. A battery leg asserting "same key ⇒ nothing moves"
    failed by exactly 1e-6 and is the only reason this docstring is now true. The dedup is
    real and useful — it makes a double-click or a retry storm inside 24h free — but it was
    never the guarantee for a three-month-old failure, and describing it as one would have
    put a safety claim in front of an operator that the system does not honour.

    ⚠ The original key still matters most for records whose error says `exhausted`: the
    rail's own docstring warns those partial legs are ALREADY COMMITTED, so re-driving one
    inside the window returns the original result rather than paying the committed legs
    twice. Minting a fresh key would forfeit even that.

    ⚠ OWNERSHIP IS IN THE WHERE CLAUSE, not in a check after the read. A second developer
    asking for this record's id gets the same 404 as a record that does not exist — the
    absence of the row IS the refusal, so there is no ordering in which a leak is possible.

    ⚠ Δ-neutral by construction: a transfer between existing accounts, never a mint.

    §MEMBERSHIP (2026-10-02, agentvault2-15's finding): a staking reward is not paid where
    STAKING_REWARDS_ENABLED is off, and that includes one earned before the switch: "no reward is
    distributed" is what this registry says about itself (core/staking_gate.py), so this press refuses
    rather than paying it. The record stays listed; it can be paid if rewards are ever switched back on.
    """
    from agentvault_registry.core.staking_gate import (
        REWARDS_DISABLED_SENTENCE as _REWARDS_OFF, staking_rewards_enabled as _rewards_on,
    )
    if not _rewards_on():
        raise HTTPException(status.HTTP_403_FORBIDDEN, _REWARDS_OFF)
    dev_id = current_developer.id

    row = (await db.execute(text("""
        SELECT r.id, r.agent_did, r.reward_amount, r.distribution_id, r.error_message
        FROM staking_reward_records r
        JOIN agents a ON a.did = r.agent_did AND a.creator_developer_id = :dev
        WHERE r.id::text = :rid
          AND r.error_message IS NOT NULL
          AND r.teg_transaction_id IS NULL
    """), {"dev": dev_id, "rid": str(record_id)})).mappings().first()
    if not row:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No undelivered payout with that id belongs to you. It may already have been "
            "paid; re-driving a delivered payout is not possible by design.",
        )

    key = f"staking-{row['distribution_id']}-{row['agent_did']}"
    amount = Decimal(str(row["reward_amount"]))

    from agentvault_registry.services.reward_funding import fund_reward_via_waterfall
    from agentvault_registry.services.admin_audit import log_admin_action
    from agentvault_registry.teg_client import TEGClientError

    try:
        res = await fund_reward_via_waterfall(
            db,
            target_agent_did=row["agent_did"],
            amount=amount,
            reason="staking_reward",
            reference_id=row["distribution_id"],
            idempotency_key=key,           # ← the ORIGINAL key. Never a new one.
        )
    except TEGClientError as e:
        # ⚠ `log_admin_action` takes `actor_id`, NOT `developer_id`, and takes no `request`.
        # Inside a try/except the wrong signature makes the audit SILENTLY never write while
        # the money path still runs (§COCKPITA).
        await log_admin_action(
            db, action="cockpit.reward.redrive", actor_id=str(dev_id),
            target_type="staking_reward_record", target_id=str(row["id"]),
            outcome="failure", severity="warning", error_message=str(e)[:400],
            details={"agent_did": row["agent_did"], "amount": str(amount), "key": key},
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"The payment rail refused and no money moved: {str(e)[:200]}",
        )

    moved = str(res.get("funded_amount") or "0")
    completed = res.get("status") == "completed"
    tx = res.get("first_transaction_id") or ""

    await db.execute(text("""
        UPDATE staking_reward_records
        SET status = :st, teg_transaction_id = :tx, error_message = :err
        WHERE id::text = :rid
    """), {
        "rid": str(row["id"]),
        "st": "distributed" if completed else "partial",
        "tx": tx,
        # 🔴 THE ORIGINAL ERROR TEXT IS KEPT, NOT CLEARED — a correction to the one-off
        # script that paid the first sixteen. That script set `error_message = None` on
        # success, which erased the only record that those payments had ever failed: the
        # pane's "last failed N ago" line then had nothing to read and said "none on
        # record" about sixteen real May failures. `teg_transaction_id IS NULL` is what
        # makes a row OPEN, so setting the tx closes it without destroying the evidence.
        # An exhausted waterfall committed SOME legs, so it says so instead of "paid".
        "err": row["error_message"] if completed else
               f"waterfall exhausted: funded {moved} of {row['reward_amount']} "
               f"(after: {row['error_message']})",
    })
    await log_admin_action(
        db, action="cockpit.reward.redrive", actor_id=str(dev_id),
        target_type="staking_reward_record", target_id=str(row["id"]),
        outcome="success" if completed else "partial",
        details={"agent_did": row["agent_did"], "amount": str(amount),
                 "funded": moved, "tx": tx, "key": key},
    )
    await db.commit()

    return {
        "paid": completed,
        "funded_amount": moved,
        "shortfall": str(res.get("shortfall") or "0"),
        "currency": _FRAME_CCY,
        "transaction_id": tx,
        "agent_did": row["agent_did"],
        "idempotency_key": key,
    }


# ---------------------------------------------------------------------------
# §COCKPITMODULES M2 — EARNINGS: the income half of the book.
# ---------------------------------------------------------------------------

@router.get("/me/earnings",
            summary="What my agents have actually been paid")
async def my_earnings(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    The payout records of the developer's agents for their locked units: per agent, the payouts delivered and the
    ones that failed (from the same table), with the locked balance as the registry's cache holds it, and totals in
    this frame's unit. A payout on locked units is a switch per registry (`STAKING_REWARDS_ENABLED`): discretionary,
    paid in platform units, off on the public network, where no new record is written. Needs a developer token.

    \f
    `share-book` answers what this account OWNS. This answers what it is paid.

    ⚠ ONE GROUPED QUERY, per agent, never a fan-out (§COCKPITSHOW).

    ⚠ THE FAILED PAYOUTS ARE SHOWN BESIDE THE PAID ONES, from the SAME table, so the two
    panes cannot disagree about the same fact. An income pane that silently omitted the undelivered
    rows would be how 66,326 units went missing in the first place: every surface
    summing only what succeeded.

    ⚠ `staked` comes from `agents.staked_balance`, which is the registry's cache. It is
    labelled as the registry's view rather than presented as TEG truth — the two can lag,
    and a number that might be stale must say which side it came from (§XHIRE).
    """
    dev_id = current_developer.id
    lim = max(1, min(int(limit or 10), 50))

    rows = (await db.execute(text("""
        SELECT a.did,
               c.name                                            AS agent_name,
               a.staking_tier                                    AS tier,
               a.staked_balance                                  AS staked,
               COUNT(r.id) FILTER (WHERE r.teg_transaction_id IS NOT NULL)  AS paid_n,
               COALESCE(SUM(r.reward_amount) FILTER (WHERE r.teg_transaction_id IS NOT NULL), 0) AS paid_amt,
               COUNT(r.id) FILTER (WHERE r.teg_transaction_id IS NULL
                                     AND r.error_message IS NOT NULL)       AS failed_n,
               COALESCE(SUM(r.reward_amount) FILTER (WHERE r.teg_transaction_id IS NULL
                                     AND r.error_message IS NOT NULL), 0)   AS failed_amt,
               MAX(r.created_at) FILTER (WHERE r.teg_transaction_id IS NOT NULL) AS last_paid_at
        FROM agents a
        LEFT JOIN agent_cards c ON c.agent_did = a.did
        LEFT JOIN staking_reward_records r ON r.agent_did = a.did
        WHERE a.creator_developer_id = :dev
        GROUP BY a.did, c.name, a.staking_tier, a.staked_balance
        HAVING COUNT(r.id) > 0 OR COALESCE(a.staked_balance, 0) > 0
        ORDER BY COALESCE(SUM(r.reward_amount) FILTER (WHERE r.teg_transaction_id IS NOT NULL), 0) DESC
        LIMIT :lim
    """), {"dev": dev_id, "lim": lim})).mappings().all()

    tot = (await db.execute(text("""
        SELECT COUNT(*)                                        AS records,
               COUNT(DISTINCT r.agent_did)                     AS agents,
               COALESCE(SUM(r.reward_amount) FILTER (WHERE r.teg_transaction_id IS NOT NULL), 0) AS paid,
               COALESCE(SUM(r.reward_amount) FILTER (WHERE r.teg_transaction_id IS NULL
                                     AND r.error_message IS NOT NULL), 0)   AS undelivered
        FROM staking_reward_records r
        JOIN agents a ON a.did = r.agent_did AND a.creator_developer_id = :dev
    """), {"dev": dev_id})).mappings().first() or {}

    return {
        # ⚠ ONE currency, and it is this frame's. Agents on this registry are denominated in
        # it; a total spanning frames would be a wrong number, not a rounded one (§SUMSPLIT).
        "currency": _FRAME_CCY,
        "records": int(tot.get("records") or 0),
        "agents": int(tot.get("agents") or 0),
        "paid_total": str(tot.get("paid") or 0),
        "undelivered_total": str(tot.get("undelivered") or 0),
        "rows": [{
            "did": r["did"],
            "agent_name": r["agent_name"],
            "tier": r["tier"],
            "staked": str(r["staked"] or 0),
            "paid_n": int(r["paid_n"] or 0),
            "paid": str(r["paid_amt"] or 0),
            "failed_n": int(r["failed_n"] or 0),
            "failed": str(r["failed_amt"] or 0),
            "last_paid_at": r["last_paid_at"].isoformat() if r["last_paid_at"] else None,
        } for r in rows],
    }


# ---------------------------------------------------------------------------
# §COCKPITMODULES M4 — AGENT LOGS: why an agent went quiet.
# ---------------------------------------------------------------------------

@router.get("/me/agent-logs",
            summary="The newest ERROR/WARN lines across all my agents")
async def my_agent_logs(
    level: str = Query("ERROR", description="ERROR | WARN | INFO | DEBUG"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    The newest ERROR and WARN log lines across all the developer's agents, from one query, with the level asked for
    and how many lines exist. Needs a developer token.

    \f
    The pair to the progress pane: that one shows an agent talking, this shows it hurting.

    ⚠ THE EXISTING RAIL IS PER-AGENT (`GET /agents/{did}/logs`) AND CORRECTLY SO — logs
    belong to an agent. But asking it once per agent is the denials fan-out again: this
    account has 4,100+ agents and 1.1M log lines. ONE grouped query, ordered on the existing
    `ix_agent_logs_timestamp`, measured at ~24 ms.

    ⚠ THE LEVEL IS REPORTED, NEVER ASSUMED. A quiet ERROR feed and an unread ERROR feed look
    identical unless the pane says which level it asked for and how many exist (§RAT).
    """
    dev_id = current_developer.id
    lim = max(1, min(int(limit or 20), 100))
    lvl = (level or "ERROR").strip().upper()
    if lvl not in {"ERROR", "WARN", "INFO", "DEBUG"}:
        raise HTTPException(422, "level must be one of ERROR, WARN, INFO, DEBUG")

    rows = (await db.execute(text("""
        SELECT l.agent_did, c.name AS agent_name, l.level, l.message, l.timestamp
        FROM agent_logs l
        JOIN agents a ON a.did = l.agent_did AND a.creator_developer_id = :dev
        LEFT JOIN agent_cards c ON c.agent_did = l.agent_did
        WHERE l.level = :lvl
        ORDER BY l.timestamp DESC
        LIMIT :lim
    """), {"dev": dev_id, "lvl": lvl, "lim": lim})).mappings().all()

    counts = (await db.execute(text("""
        SELECT l.level, COUNT(*) AS n, MAX(l.timestamp) AS last
        FROM agent_logs l
        JOIN agents a ON a.did = l.agent_did AND a.creator_developer_id = :dev
        GROUP BY l.level
    """), {"dev": dev_id})).mappings().all()

    return {
        "level": lvl,
        "levels": {c["level"]: {"count": int(c["n"]),
                                "last": c["last"].isoformat() if c["last"] else None}
                   for c in counts},
        "rows": [{
            "agent_did": r["agent_did"],
            "agent_name": r["agent_name"],
            "level": r["level"],
            "message": (r["message"] or "")[:400],
            "at": r["timestamp"].isoformat() if r["timestamp"] else None,
        } for r in rows],
    }


# ---------------------------------------------------------------------------
# §COCKPITMODULES M3 — WORK: contracts, guild orders and disputes, either side.
# ---------------------------------------------------------------------------

@router.get("/me/work",
            summary="Contracts, guild work and disputes my agents are party to")
async def my_work(
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """
    A read-only summary of the contracts, Guild work and disputes the developer's agents are party to, on both sides
    (client and provider), across every agent the account owns. Needs a developer token.

    \f
    ⚠ THE PLAN FOR THIS PANE SAID "mount `BridgeWorkView`, do not re-implement it", AND
    THAT PREMISE WAS STALE — the same way §DIVVERBS' was. That component is an 840-line
    MODAL: it takes a `show` prop and installs a FOCUS TRAP. Mounting it inside a dashboard
    tile would trap keyboard focus in a grid cell, which is an accessibility defect, not a
    shortcut. So this is a read-only SUMMARY over the same three rails, and the modal stays
    the one place the work is actually done.

    ⚠ ACCOUNT-WIDE, like `share-book`, and NOT following the header switcher. Work belongs
    to an agent, but a desk asking "what is outstanding" means across everything I own; the
    pane says which convention it follows so it cannot be misread (§FOREIGNACT).

    ⚠ Both sides of every relationship: an agent is as often the CLIENT as the provider, and
    a pane showing only one side would under-report by construction.
    """
    dev_id = current_developer.id
    mine = "(SELECT did FROM agents WHERE creator_developer_id = :dev)"

    contracts = (await db.execute(text(f"""
        SELECT status, COUNT(*) AS n, MAX(created_at) AS last
        FROM contracts
        WHERE provider_did IN {mine} OR client_did IN {mine}
        GROUP BY status ORDER BY COUNT(*) DESC
    """), {"dev": dev_id})).mappings().all()

    disputes = (await db.execute(text(f"""
        SELECT status, COUNT(*) AS n, MAX(created_at) AS last
        FROM disputes
        WHERE complainant_did IN {mine} OR defendant_did IN {mine}
        GROUP BY status ORDER BY COUNT(*) DESC
    """), {"dev": dev_id})).mappings().all()

    guild = (await db.execute(text(f"""
        SELECT status, COUNT(*) AS n, MAX(created_at) AS last
        FROM guild_work_orders
        WHERE poster_did IN {mine} OR worker_did IN {mine}
        GROUP BY status ORDER BY COUNT(*) DESC
    """), {"dev": dev_id})).mappings().all()

    def pack(rows, open_states):
        out = [{"status": r["status"], "n": int(r["n"]),
                "last": r["last"].isoformat() if r["last"] else None} for r in rows]
        return {
            "total": sum(x["n"] for x in out),
            # "Open" is named per family rather than guessed from the word: a contract that
            # is `offered` is open, a dispute that is `CLOSED` is not, and the two families
            # do not share a vocabulary or even a case convention.
            "open": sum(x["n"] for x in out if x["status"] in open_states),
            "by_status": out,
        }

    return {
        "contracts": pack(contracts, {"offered", "agreed", "active", "submitted", "disputed"}),
        "disputes":  pack(disputes,  {"OPEN", "open", "UNDER_REVIEW"}),
        "guild":     pack(guild,     {"open", "bidding", "awarded", "submitted"}),
    }


# ─── §LEGALKIT (2026-09-20): the account export Privacy § 6 promises (Art. 20 GDPR) ────────────────
@router.get("/me/export", summary="Download the account's data as one JSON document (Art. 20 GDPR)")
async def export_my_account(
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Everything the account holds that the person gave us or that is theirs to take along: profile
    and settings, the agents with their cards, API-key and webhook METADATA (never a secret half),
    organisation memberships, saved preferences, purchases, support tickets, the legal acceptance
    record. Hashed material, access tokens and other secrets are never in it; the pseudonymous ledger is public
    and is not repeated here (Privacy § 10)."""
    from sqlalchemy import select as _select

    def _iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    dev = current_developer
    profile = {
        "id": dev.id, "name": dev.name, "email": dev.email, "handle": getattr(dev, "handle", None),
        "display_name": getattr(dev, "display_name", None), "bio": getattr(dev, "bio", None),
        "avatar_url": getattr(dev, "avatar_url", None), "website_url": getattr(dev, "website_url", None),
        "github_url": getattr(dev, "github_url", None), "twitter_handle": getattr(dev, "twitter_handle", None),
        "company": getattr(dev, "company", None), "timezone": getattr(dev, "timezone", None),
        "profile_visibility": getattr(dev, "profile_visibility", None),
        "location": {"latitude": getattr(dev, "latitude", None), "longitude": getattr(dev, "longitude", None),
                     "label": getattr(dev, "location_label", None)},
        "notification_prefs": getattr(dev, "notification_prefs", None),
        "dev_card_passport_opt_out": getattr(dev, "dev_card_passport_opt_out", None),
        "is_verified": dev.is_verified, "is_admin": dev.is_admin,
        "two_fa_enabled": getattr(dev, "two_fa_enabled", None), "push_login_enabled": getattr(dev, "push_login_enabled", None),
        "created_at": _iso(dev.created_at), "last_login_at": _iso(getattr(dev, "last_login_at", None)),
        "tos_accepted_version": dev.tos_accepted_version, "tos_accepted_at": _iso(dev.tos_accepted_at),
    }

    agents_rows = (await db.execute(_select(models.Agent).where(models.Agent.creator_developer_id == dev.id))).scalars().all()
    agent_dids = [a.did for a in agents_rows]
    cards = {}
    if agent_dids:
        for c in (await db.execute(_select(models.AgentCard).where(models.AgentCard.agent_did.in_(agent_dids)))).scalars().all():
            cards[c.agent_did] = {"name": getattr(c, "name", None), "is_active": getattr(c, "is_active", None),
                                  "card_data": getattr(c, "card_data", None), "updated_at": _iso(getattr(c, "updated_at", None))}
    agents = [{
        "did": a.did, "client_id": a.client_id, "status": getattr(a, "status", None), "created_at": _iso(a.created_at),
        "last_active_at": _iso(getattr(a, "last_active_at", None)), "reputation_score": getattr(a, "reputation_score", None),
        "staking_tier": getattr(a, "staking_tier", None), "enforcement_status": getattr(a, "enforcement_status", None),
        "location": {"latitude": getattr(a, "latitude", None), "longitude": getattr(a, "longitude", None)},
        "card": cards.get(a.did),
    } for a in agents_rows]

    keys = [{"prefix": k.key_prefix, "description": k.description, "scopes": getattr(k, "scopes", None), "is_active": k.is_active,
             "created_at": _iso(k.created_at), "expires_at": _iso(getattr(k, "expires_at", None)), "last_used_at": _iso(getattr(k, "last_used_at", None))}
            for k in (await db.execute(_select(models.DeveloperApiKey).where(models.DeveloperApiKey.developer_id == dev.id))).scalars().all()]
    hooks = [{"id": getattr(h, "id", None), "url": h.url, "events": getattr(h, "events", None), "is_active": h.is_active,
              "created_at": _iso(h.created_at), "last_triggered_at": _iso(getattr(h, "last_triggered_at", None)), "failure_count": getattr(h, "failure_count", None)}
             for h in (await db.execute(_select(models.DeveloperWebhook).where(models.DeveloperWebhook.developer_id == dev.id))).scalars().all()]
    memberships = []
    try:
        for m in (await db.execute(_select(models.OrganizationMember).where(models.OrganizationMember.developer_id == dev.id))).scalars().all():
            memberships.append({"organization_id": getattr(m, "organization_id", None), "role": getattr(m, "role", None),
                                "joined_at": _iso(getattr(m, "joined_at", None) or getattr(m, "created_at", None))})
    except Exception:  # a frame without the org tables answers the rest of the export
        memberships = []
    prefs = {}
    try:
        for p in (await db.execute(_select(models.DeveloperPref).where(models.DeveloperPref.developer_id == dev.id))).scalars().all():
            prefs[getattr(p, "key", str(getattr(p, "id", "")))] = getattr(p, "value", None)
    except Exception:
        prefs = {}
    purchases = []
    try:
        for pu in (await db.execute(_select(models.FiatPurchase).where(models.FiatPurchase.developer_id == dev.id))).scalars().all():
            purchases.append({"id": getattr(pu, "id", None), "amount_eur": str(getattr(pu, "amount_eur", "")), "amount_avt": str(getattr(pu, "amount_avt", "")),
                              "status": getattr(pu, "status", None), "created_at": _iso(getattr(pu, "created_at", None)),
                              "tos_version": getattr(pu, "tos_version", None)})
    except Exception:
        purchases = []
    tickets = []
    try:
        for tk in (await db.execute(_select(models.SupportTicket).where(models.SupportTicket.developer_id == dev.id))).scalars().all():
            tickets.append({"id": getattr(tk, "id", None), "subject": getattr(tk, "subject", None), "status": getattr(tk, "status", None),
                            "created_at": _iso(getattr(tk, "created_at", None))})
    except Exception:
        tickets = []
    acceptances = [{"document": r.document, "version": r.version, "via": r.via, "subject_kind": r.subject_kind, "accepted_at": _iso(r.accepted_at)}
                   for r in (await db.execute(_select(models.LegalAcceptance).where(models.LegalAcceptance.developer_id == dev.id)
                                              .order_by(models.LegalAcceptance.accepted_at.desc()))).scalars().all()]

    body = {
        "export_version": "1", "exported_at": datetime.utcnow().isoformat() + "Z",
        "registry": os.getenv("REGISTRY_NAME", "") or settings.PROJECT_NAME,
        "profile": profile, "agents": agents, "api_keys": keys, "webhooks": hooks,
        "organization_memberships": memberships, "preferences": prefs, "purchases": purchases,
        "support_tickets": tickets, "legal_acceptances": acceptances,
        "not_included": [
            "hashed passwords, recovery keys, API-key secrets, agent client secrets, TOTP material (never exportable)",
            "the append-only ledger (public and pseudonymous; see Privacy § 10)",
        ],
    }
    return Response(content=json.dumps(body, default=str, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="theprotocol-account-{dev.id}.json"'})
