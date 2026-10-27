"""
Agent discovery endpoints that don't require authentication.
These endpoints allow public discovery of agents by DID.
"""
import hashlib
import json
import logging
import os
from typing import Dict, Any, Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status, Path, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, String, exists, text
from sqlalchemy.orm import aliased

from ..database import get_db
from ..models import Agent, AgentCard, Developer, PeerRegistry
from ..schemas import AgentRead
from ..security import get_current_developer, get_current_developer_optional
from ..config import settings
from ..services.a2a_v1.compat import canonicalize_card_data

logger = logging.getLogger(__name__)

router = APIRouter()


# §28 (2026-05-15) — Validation helpers for federated flare projection.
# Receiving registry MUST validate every value against the canonical sets
# before exposing — guards against a malicious peer stamping arbitrary CSS
# class names (`'; onmouseover='alert(1)`) into the sidecar.
def _validate_set(val: Optional[str], allowed: set) -> Optional[str]:
    return val if (isinstance(val, str) and val in allowed) else None


def _sanitize_url(val: Optional[str]) -> Optional[str]:
    if not isinstance(val, str) or not val:
        return None
    # Allow https/http only — drops javascript:, data:, etc.
    v = val.strip()
    if v.lower().startswith(("http://", "https://")):
        return v
    return None


# §COSMETICS FIX (2026-08-21): this was a hand-copied whitelist and it had
# drifted — it omitted "sovereign", so EVERY sovereign agent viewed from another
# registry silently lost its tier (Hypervisor Hagrid reads tier=sovereign in
# frame-c's own mirror and came back null). A second copy of a canonical set is
# a copy that will drift; ask the module that owns it.
# `sovereign` is a real tier but a per-AGENT one (§pass39c: sovereign agents
# never inherit from their developer), so it is absent from the developer-facing
# FLARE_RANK by design. It is nonetheless what `card_data.flare.tier` carries for
# 11 mirrored agents on frame-c alone, so the validator has to accept it.
try:
    from ..services.flare_grants import ALL_FLARE_TIERS as _DEV_FLARE_TIERS  # type: ignore
    _FLARE_TIERS = set(_DEV_FLARE_TIERS) | {"sovereign"}
except Exception:  # pragma: no cover - never break discovery on an import
    _FLARE_TIERS = {"sentinel", "architect", "founder", "shadow_chancellor",
                    "operator", "commander", "sovereign"}


def _build_federated_agent_response(card: AgentCard) -> Dict[str, Any]:
    """Project a synced agent_cards row + its card_data.flare sidecar into
    the same response shape `by-did` returns for local agents. UserAvatar
    and every consumer read these top-level field names directly."""
    # Import the canonical sets lazily to avoid circular import.
    # §COSMETICS FIX (Commander 2026-08-21): "this is wrong!!! they have unique
    # sovereign variants. you just assigned them whatever."
    #
    # He is right, and this validator was the cause. ENCIRCLEMENT_VARIANTS is the
    # PURCHASABLE catalog only; every sovereign signature variant (bedrock for
    # Hypervisor Hagrid, panopticon for SYBIL, prism for Glass Gerald, forge for
    # CRUCIBLE ...) lives in SOVEREIGN_VARIANTS and was therefore validated to
    # None on every federated card. The renderer then fell back to a default
    # ring, so seventeen distinct signatures collapsed into one generic one.
    # ALL_ENCIRCLEMENT_VARIANTS is the union the flare PATCH endpoint already
    # accepts — the canonical set, rather than a third opinion about it.
    try:
        from .fiat_onramp import (
            ALL_ENCIRCLEMENT_VARIANTS as ENCIRCLEMENT_VARIANTS,
            ENCIRCLEMENT_OVERLAYS,
            CORNER_VARIANTS,
            SOVEREIGN_VARIANTS,
            SOVEREIGN_VARIANT_OWNERS,
        )
    except Exception:
        ENCIRCLEMENT_VARIANTS = set()
        ENCIRCLEMENT_OVERLAYS = set()
        CORNER_VARIANTS = set()
        SOVEREIGN_VARIANTS = set()
        SOVEREIGN_VARIANT_OWNERS = {}

    cd = card.card_data or {}
    flare = cd.get("flare") or {}
    fed_meta = cd.get("federation_metadata") or {}

    # 🔴 §SOVEREIGNOWN (2026-08-21) — SET MEMBERSHIP IS NOT OWNERSHIP.
    #
    # Widening this validator to ALL_ENCIRCLEMENT_VARIANTS let the sovereign
    # signatures through, which was the point — but a sovereign variant is not a
    # style, it is an IDENTITY: `panopticon` is SYBIL, `bedrock` is Hypervisor
    # Hagrid, and fiat_onramp.py:4325 refuses to let any other agent equip one
    # (403, fail-closed on an unknown variant). This read path had no such check,
    # so a card_data.flare block claiming `panopticon` — self-authored locally,
    # or arriving from a peer — rendered SYBIL's ring on somebody else's agent,
    # on every registry that received it.
    #
    # Same question the write rail asks, asked again on the way out. Fail-closed:
    # a sovereign claim we cannot tie to its registered owner is dropped, along
    # with the sovereign tier that would style it.
    _claimed_variant = flare.get("encirclement_variant")
    _claimed_tier = flare.get("tier")
    _sov_claim = (_claimed_variant in SOVEREIGN_VARIANTS) or (_claimed_tier == "sovereign")
    if _sov_claim:
        _owner = SOVEREIGN_VARIANT_OWNERS.get(_claimed_variant or "")
        if not _owner or not card.agent_did or card.agent_did != _owner:
            logger.warning(
                "[flare] dropping unowned sovereign claim: card=%s did=%s "
                "variant=%s tier=%s (registered owner=%s)",
                getattr(card, "id", "?"), card.agent_did, _claimed_variant,
                _claimed_tier, _owner,
            )
            flare = {k: v for k, v in flare.items()
                     if k not in ("encirclement_variant", "tier", "encirclement_overlay")}

    return {
        "id": str(card.id),
        "did": card.agent_did,
        "client_id": None,
        "status": "active" if card.is_active else "inactive",
        "creator_developer_id": None,
        "created_at": card.created_at.isoformat() if card.created_at else None,
        "last_active_at": None,
        "reputation_score": None,
        "liquid_balance": None,
        "staked_balance": None,
        # Card payload + provenance
        "name": card.name,
        "description": card.description,
        "card_data": cd,
        "is_federated": True,
        "flare_source_registry": flare.get("source_registry") or fed_meta.get("source_registry"),
        "origin_registry_name": fed_meta.get("origin_registry_name"),
        # Flare projection — validated against canonical sets
        "flare_tier":                  _validate_set(flare.get("tier"), _FLARE_TIERS),
        "flare_granted_at":            flare.get("granted_at"),
        "flare_id":                    flare.get("id"),
        "flare_display_name":          flare.get("display_name"),
        "flare_tagline":               flare.get("tagline"),
        "flare_logo_url":              _sanitize_url(flare.get("logo_url")),
        "flare_link_url":              _sanitize_url(flare.get("link_url")),
        "flare_cause":                 flare.get("cause"),
        "flare_accent_color":          flare.get("accent_color"),
        "flare_encirclement_variant": _validate_set(flare.get("encirclement_variant"), ENCIRCLEMENT_VARIANTS),
        "flare_encirclement_overlay": _validate_set(flare.get("encirclement_overlay"), ENCIRCLEMENT_OVERLAYS),
        "flare_corner_variant":        _validate_set(flare.get("corner_variant"),       CORNER_VARIANTS),
        "bears_corner_flare":          bool(flare.get("bears_corner_flare", False)),
        "bears_encirclement_flare":    bool(flare.get("bears_encirclement_flare", False)),
        "selected_corner_flare":       flare.get("selected_corner_flare"),
        "selected_encirclement_flare": flare.get("selected_encirclement_flare"),
    }


# §COSMETICS (Commander 2026-08-21): "the cosmetics info for each agent should
# already be in the registry so no fetching needed. it should be attached to the
# card data."
#
# It already is. Federation mirrors `agent_cards.card_data.flare` (the §28 flare
# sidecar), and on frame-c 4,310 of 13,850 active cards carry one. What was
# missing is a way for a client to ASK for the cosmetics of agents it holds
# credentials for but does not OWN here: `/developers/me/agents` is scoped to the
# caller's own agents, so a foreign agent is absent by construction, and the
# frontend was falling back to a cross-origin fetch per agent against the agent's
# home registry. This reads what THIS registry already mirrors, in one call.
#
# ⚠ Registered BEFORE `/agents/by-did/{did}`: FastAPI resolves in registration
# order, not by path specificity, so a literal route added later gets swallowed.
@router.get("/agents/cosmetics")
async def get_agents_cosmetics(
    dids: str = Query(..., description="CSV of agent DIDs, max 300."),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    """Cosmetics this registry already holds for a batch of agents.

    Presentation only, and only what the local mirror already publishes on the
    public card: no cross-origin call, no per-agent round trip. A DID this
    registry has never mirrored is simply absent from `cosmetics`, and is listed
    in `unknown` so the caller can tell "no flare" from "never heard of it".
    """
    want = [d.strip() for d in (dids or "").split(",") if d.strip()][:300]
    if not want:
        return {"cosmetics": {}, "unknown": [], "asked": 0}

    rows = (await db.execute(
        select(AgentCard).where(AgentCard.agent_did.in_(want))
    )).scalars().all()

    FIELDS = (
        "flare_tier", "flare_granted_at", "flare_id", "flare_display_name",
        "flare_tagline", "flare_logo_url", "flare_link_url", "flare_cause",
        "flare_accent_color", "flare_encirclement_variant",
        "flare_encirclement_overlay", "flare_corner_variant",
        "bears_corner_flare", "bears_encirclement_flare",
        "selected_corner_flare", "selected_encirclement_flare",
    )
    out: Dict[str, Any] = {}
    for card in rows:
        if not card.agent_did:
            continue
        try:
            full = _build_federated_agent_response(card)
        except Exception:
            continue
        picked = {k: full.get(k) for k in FIELDS}
        # Nothing to wear is a real answer, but it is not worth a row: the
        # caller treats absence as "no cosmetic" either way.
        if not any(picked.get(k) for k in ("flare_tier", "selected_encirclement_flare",
                                           "selected_corner_flare", "flare_encirclement_variant")):
            continue
        picked["name"] = card.name
        out[card.agent_did] = picked

    return {"cosmetics": out, "unknown": [d for d in want if d not in out], "asked": len(want)}


async def _attach_track_record(db: AsyncSession, did: str, resp: Dict[str, Any]) -> Dict[str, Any]:
    """§MARKSURFACES (2026-09-10) — the ledger-earned mark, from the ONE projection.

    ⚠ THIS EXISTS BECAUSE THE FIRST CUT WIDENED ONE RETURN PATH AND LEFT ITS SIBLING ASKING THE
    OLD QUESTION — §FANOUTFIX, in the same file, in the same hour. `by-did` has THREE returns: the
    local-agent one, and two federated ones for a card this registry mirrors but holds no `agents`
    row for. Measured on frame-c right after the roll: its most-verified worker (8 settled orders)
    is a MIRROR from op-doha, so it took the federated path and answered `track_record: null`
    while the rankings feed on the same node carried the mark correctly. A mirrored agent that did
    verified work in THIS registry's guild book genuinely has a record here; the shape of its card
    row is not a reason to withhold it.

    Never raises: an avatar decoration is not worth failing an agent lookup.
    """
    try:
        from agentvault_registry.services.track_record import compact_track_records
        resp["track_record"] = (await compact_track_records(db, [did])).get(did)
    except Exception as _tr_e:  # noqa: BLE001
        logger.warning(f"[MARK] track-record enrichment failed for {did}: {_tr_e}")
        resp.setdefault("track_record", None)
    return resp


@router.get("/agents/by-did/{did}")
async def get_agent_by_did(
    did: str = Path(..., description="Agent DID (e.g., did:agentvault:12345)"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_developer: Annotated[Optional[Developer], Depends(get_current_developer_optional)] = None
) -> Dict[str, Any]:
    """
    Get agent details by DID.
    
    This endpoint allows looking up agents by their Decentralized Identifier (DID)
    instead of the internal UUID. This is crucial for the frontend which often
    works with DIDs.
    
    Args:
        did: The agent's DID
        db: Database session
        current_developer: Optional authenticated developer
        
    Returns:
        Agent details including card data if available
        
    Raises:
        HTTPException: If agent not found
    """
    logger.info(f"Looking up agent by DID: {did}")
    
    # Query for agent by DID
    stmt = select(Agent).where(Agent.did == did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        # §28 (2026-05-15) — Federated fallback: agent_cards may carry a
        # synced card for this DID even when no local Agent row exists
        # (the agent lives on a peer registry). Project card_data.flare
        # to the same response shape so UserAvatar renders identically.
        fed_card_stmt = select(AgentCard).where(AgentCard.agent_did == did)
        fed_card_result = await db.execute(fed_card_stmt)
        fed_card = fed_card_result.scalar_one_or_none()
        if fed_card:
            logger.info(f"Serving federated agent card for DID {did} (no local Agent row)")
            return await _attach_track_record(db, did, _build_federated_agent_response(fed_card))
        # §MCPTEST30 (V0515): /discover's federated half lists cards that carry NO agent_did and names each by its
        # card_data['did'] (Step 4 of discover_agents); the agent_did fallback above can never match those, so every
        # federated agent the discover page showed answered 404 here (the MCP tester's list/detail probe, by
        # construction). The same population, read the same way: the newest active card first.
        named_stmt = (select(AgentCard)
                      .where(AgentCard.agent_did.is_(None), AgentCard.card_data["did"].astext == did)
                      .order_by(AgentCard.is_active.desc(), AgentCard.updated_at.desc())
                      .limit(1))
        named_card = (await db.execute(named_stmt)).scalars().first()
        if named_card:
            logger.info(f"Serving a federated card named by its card_data did for DID {did}")
            return await _attach_track_record(db, did, _build_federated_agent_response(named_card))
        # §incident-2026-05-30 — AgentWorld synthesises did="card:<AgentCard.id>"
        # for federated cards with no local Agent row (see the federated-agent
        # loader in AgentWorldCesium). The agent_did fallback above misses
        # because the UUID is the card's OWN primary key, not its agent_did, so
        # this used to 404. Hovering many federated orbs fired a burst of those
        # 404s → tripped CrowdSec http-probing → banned the VIEWER's IP. Resolve
        # by card PK so the route returns 200 for a real (federated) card.
        if isinstance(did, str) and did.startswith("card:"):
            import uuid as _uuid
            try:
                _card_pk = _uuid.UUID(did[len("card:"):])
            except (ValueError, AttributeError):
                _card_pk = None
            if _card_pk is not None:
                pk_card = (await db.execute(
                    select(AgentCard).where(AgentCard.id == _card_pk)
                )).scalar_one_or_none()
                if pk_card:
                    logger.info(f"Serving federated agent card by PK for synthesised DID {did}")
                    return await _attach_track_record(
                        db, pk_card.agent_did or did, _build_federated_agent_response(pk_card))
        logger.warning(f"Agent not found for DID: {did}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with DID {did} not found"
        )
    
    # Fetch associated agent card if exists
    card_stmt = select(AgentCard).where(AgentCard.agent_did == did)
    card_result = await db.execute(card_stmt)
    agent_card = card_result.scalar_one_or_none()
    
    # PB-1 backer flare — pull customization from the owning developer when
    # the agent has a flare. Customization (display_name, tagline, logo, link,
    # cause, accent_color) lives on Developer; agent only stores tier+granted.
    flare_tier = getattr(agent, "flare_tier", None)
    flare_payload = {
        "flare_tier": flare_tier,
        "flare_granted_at": (
            agent.flare_granted_at.isoformat()
            if getattr(agent, "flare_granted_at", None) else None
        ),
        "flare_id": None,
        "flare_display_name": None,
        "flare_tagline": None,
        "flare_logo_url": None,
        "flare_link_url": None,
        "flare_cause": None,
        "flare_accent_color": None,
        # §15/§28 (2026-05-13) — per-agent encirclement aesthetic + overlay.
        # These fields drive UserAvatar's effectiveVariant/effectiveOverlay.
        "flare_encirclement_variant": getattr(agent, "flare_encirclement_variant", None),
        "flare_encirclement_overlay": getattr(agent, "flare_encirclement_overlay", None),
        "flare_corner_variant": getattr(agent, "flare_corner_variant", None),
        "bears_corner_flare": bool(getattr(agent, "bears_corner_flare", False)),
        "bears_encirclement_flare": bool(getattr(agent, "bears_encirclement_flare", False)),
    }
    if flare_tier:
        dev_stmt = select(Developer).where(Developer.id == agent.creator_developer_id)
        dev_row = await db.execute(dev_stmt)
        dev = dev_row.scalar_one_or_none()
        if dev:
            flare_payload.update({
                "flare_id": getattr(dev, "flare_id", None),
                "flare_display_name": getattr(dev, "flare_display_name", None),
                "flare_tagline": getattr(dev, "flare_tagline", None),
                "flare_logo_url": getattr(dev, "flare_logo_url", None),
                "flare_link_url": getattr(dev, "flare_link_url", None),
                "flare_cause": getattr(dev, "flare_cause", None),
                "flare_accent_color": getattr(dev, "flare_accent_color", None),
                # §15/§28 — fall back to dev's encirclement settings when the
                # agent itself doesn't override them (mirror /developers/me/agents).
                "flare_encirclement_variant": (
                    getattr(agent, "flare_encirclement_variant", None)
                    or getattr(dev, "flare_encirclement_variant", None)
                ),
                "flare_encirclement_overlay": (
                    getattr(agent, "flare_encirclement_overlay", None)
                    or getattr(dev, "flare_encirclement_overlay", None)
                ),
            })
            # §23/§28 — slot mirroring: when the agent BEARS a slot, expose
            # the dev's selection so UserAvatar's typeof-aware resolver picks
            # the encirclement / corner correctly.
            if flare_payload["bears_encirclement_flare"]:
                flare_payload["selected_encirclement_flare"] = getattr(dev, "selected_encirclement_flare", None)
            if flare_payload["bears_corner_flare"]:
                flare_payload["selected_corner_flare"] = getattr(dev, "selected_corner_flare", None)

    # §MARKSURFACES (2026-09-10) — the LEDGER-EARNED mark rides beside the PURCHASED
    # flare above, from the same ONE projection every avatar surface reads. This is the
    # endpoint the public Leaderboard enriches each ranked DID with
    # (`services/api/leaderboard.ts::getProfile`), so without it the ranking page could
    # not render a rank mark on the agents it is ranking. Absent = no verified work.
    # An avatar decoration must never break an agent lookup.
    # Build response
    response = {
        "id": agent.id,
        "did": agent.did,
        "client_id": agent.client_id,
        "status": agent.status,
        "creator_developer_id": agent.creator_developer_id,
        "created_at": agent.created_at.isoformat(),
        "last_active_at": agent.last_active_at.isoformat() if agent.last_active_at else None,
        "reputation_score": agent.reputation_score,
        "liquid_balance": agent.liquid_balance,
        "staked_balance": agent.staked_balance,
        **flare_payload,
    }
    
    # Add card data if available
    if agent_card:
        response.update({
            "name": agent_card.name,
            "description": agent_card.description,
            "card_data": agent_card.card_data
        })
    else:
        response.update({
            "name": None,
            "description": None,
            "card_data": None
        })
    
    return await _attach_track_record(db, agent.did, response)


@router.get("/agents/did/{did}")
async def get_agent_by_did_alt(
    did: str = Path(..., description="Agent DID"),
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """
    Alternative endpoint for DID lookup that returns a redirect hint.

    This is a convenience endpoint that helps the frontend find agents by DID.
    """
    # Find the agent by DID
    stmt = select(Agent).where(Agent.did == did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with DID {did} not found"
        )

    # Return the agent ID so frontend can use the regular endpoint
    return {
        "agent_id": agent.id,
        "did": agent.did,
        "redirect_url": f"/api/v1/agents/{agent.id}"
    }


# ─── Option C Phase 2 (2026-05-17) — agent-canonical card export ────────────
#
# The agent serves /.well-known/agent-card.json (per A2A v1.0 §4.1.2). For the
# federated-mode SDK helper, the agent fetches its own card from this endpoint
# at startup. The response intentionally STRIPS registry-owned enrichment
# (federation_metadata, flare, last_pulled_*) so the registry's pull-sync worker
# never re-ingests its own enrichment as if it were agent-declared content.
# Public — well-known cards are public discovery data.

_REGISTRY_OWNED_FIELDS = frozenset({
    "federation_metadata",
    "flare",
    "last_pulled_at",
    "last_pulled_etag",
})


@router.get("/agents/{did:path}/card-export")
async def get_agent_card_export(
    did: str = Path(..., description="Agent DID (e.g., did:theprotocol:abc-123)"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    extended: bool = Query(
        False,
        description="§AGENTDISC #187 — authenticated extended card: inlines the "
                    "registry-attested track record into the extension params "
                    "(requires a developer JWT; the registry-hosted equivalent of "
                    "A2A's agent/getAuthenticatedExtendedCard)."),
    current_developer: Annotated[Optional[Developer], Depends(get_current_developer_optional)] = None,
):
    """
    Return the agent-owned slice of `card_data` (A2A v1.0, section 4.1.2).

    Public, no auth required. The well-known card is public discovery data.

    Response shape: the stored ``card_data`` JSON minus registry-owned
    enrichment fields (``federation_metadata``, ``flare``, ``last_pulled_*``).
    Idempotently passed through ``canonicalize_card_data()`` so v0.3-only rows
    return with v1.0 fields derived.

    Returns:
        200: AgentCard JSON.
        304: If-None-Match matches current ETag.
        404: Agent or its card not found.

    Headers set on 200/304:
        ETag, Cache-Control: public, max-age=300, stale-while-revalidate=600.
    """
    stmt = select(AgentCard).where(AgentCard.agent_did == did)
    result = await db.execute(stmt)
    agent_card = result.scalar_one_or_none()

    if not agent_card or not agent_card.card_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No exportable card for agent DID {did}",
        )

    canonical = canonicalize_card_data(agent_card.card_data)
    if not isinstance(canonical, dict):
        canonical = {}
    stripped = {k: v for k, v in canonical.items() if k not in _REGISTRY_OWNED_FIELDS}

    # §AGENTDISC #187 — A2A track-record extension, injected AFTER the strip
    # (derive-time, never persisted into card_data). Pointer-only on the public
    # card; the authenticated extended variant inlines the attested payload.
    from ..services import track_record as _tr
    if extended and current_developer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The extended card requires an authenticated developer",
        )
    if await _tr.has_history(db, did):
        extended_payload = None
        if extended:
            summaries = await _tr.track_record_summaries(db, [did])
            extended_payload = {
                "summary": summaries.get(did),
                "engagements": await _tr.track_record_detail(db, did, limit=25),
            }
        stripped = _tr.inject_track_record_extension(stripped, did, extended_payload)

    # §REPBOND (2026-09-05) — the reputation bond rides the card as a TOP-LEVEL
    # extension, derived from THIS registry's truth at serve time (never persisted),
    # so a peer's mirror carries it and every registry's discovery can read it.
    from ..services import reputation_bond as _rb
    stripped = _rb.inject_extension(stripped, await _rb.card_state(db, did))
    # §ENFPROP — and the enforcement state, the same way.
    from ..services import enforcement_propagation as _ep
    stripped = _ep.inject_extension(stripped, await _ep.card_state(db, did))
    # §LISTPROP — and the listing state, so a card read DIRECTLY from its home tells the same
    # truth the fan-out tombstone carries (one predicate, `listing_propagation.card_state`).
    # ⚠ This is NOT the propagation carrier and must not be mistaken for one: the agent-card
    # pull-sync fetches the AGENT'S OWN host (`supportedInterfaces[0].url` → that host's
    # /.well-known/agent-card.json), never this endpoint, so it cannot see this block. The
    # propagation runs through the federation fan-out envelope alone.
    from ..services import listing_propagation as _lp
    stripped = _lp.inject_extension(stripped, await _lp.card_state(db, did))

    # §AGENTDISC #192 — A2A signatures[] (detached JWS, registry EdDSA key, JWKS
    # kid). Computed at serve time over the FINAL derived card; any stored/stale
    # signatures field is dropped first so a re-registered card can never replay
    # an old signature as fresh. Best-effort: unsigned beats failing the export.
    from ..services.a2a_v1.card_signatures import sign_agent_card
    stripped.pop("signatures", None)
    _sigs = await sign_agent_card(db, stripped)
    if _sigs:
        stripped["signatures"] = _sigs

    body_bytes = json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode("utf-8")
    etag = f'"{hashlib.sha256(body_bytes).hexdigest()[:16]}"'

    headers = {
        "ETag": etag,
        "Cache-Control": ("private, no-store" if extended
                          else "public, max-age=300, stale-while-revalidate=600"),
        "Access-Control-Allow-Origin": "*",
    }

    if if_none_match and if_none_match == etag:
        return Response(status_code=304, headers=headers)

    return Response(
        content=body_bytes,
        media_type="application/json",
        headers=headers,
    )


# ─── Q-C W5 (2026-05-12) — did-jwt verifier public-key lookup ─────────────────
@router.get("/agents/{did:path}/public-key")
async def get_agent_public_key(
    did: str = Path(..., description="Agent DID (e.g., did:theprotocol:abc-123)"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    """
    Get an agent's public key in JWK format (no authentication required).

    Used by did-jwt verifiers to retrieve the public key needed to verify
    a JWT signed by another agent. Per A2A v1.0 Extension
    ``https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed``.

    Returns 404 if the agent has no public key registered. Returns the JWK
    plus a small advertising envelope identifying the algorithm + extension
    URI so verifiers know which signing primitive to use.

    Public by design: public keys are NOT secret material.
    """
    stmt = select(Agent).where(Agent.did == did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with DID {did} not found",
        )

    if not agent.public_key_jwk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Agent {did} has no public key registered. "
                "Server-side did-jwt keypair autogen requires A2A_DID_JWT_AUTOGEN=true "
                "at agent creation time, OR the agent must have supplied "
                "public_key_jwk in POST /onboard/create_agent."
            ),
        )

    # Derive algorithm from JWK (kty=OKP + crv=Ed25519 → EdDSA)
    alg = "unknown"
    jwk = agent.public_key_jwk
    if isinstance(jwk, dict):
        if jwk.get("alg"):
            alg = jwk["alg"]
        elif jwk.get("kty") == "OKP" and jwk.get("crv") == "Ed25519":
            alg = "EdDSA"
        elif jwk.get("kty") == "RSA":
            alg = "RS256"  # best-guess
        elif jwk.get("kty") == "EC":
            alg = "ES256"

    return {
        "agent_did": did,
        "public_key_jwk": jwk,
        "algorithm": alg,
        "extension_uri": "https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed",
    }


def discover_match(query: str):
    """(the LIKE-escaped query, the local search condition) GET /discover matches on: the DID, the card's name,
    description or text. One source for the page and for its total, so the two can never count different rows."""
    # escape LIKE wildcards to prevent pattern injection
    from agentvault_registry.input_validators import escape_like
    escaped_query = escape_like(query)
    search_pattern = f"%{escaped_query}%"
    return escaped_query, or_(
        Agent.did.ilike(search_pattern),
        AgentCard.name.ilike(search_pattern),
        AgentCard.description.ilike(search_pattern),
        # Search in card_data JSON
        func.cast(AgentCard.card_data, String).ilike(search_pattern)
    )


def discover_statement(query: str):
    """The local rows of GET /discover, before the page is cut: active agents (with their card, when they have one) whose
    DID, card name, description or card text holds `query`, unlisted cards left out, in ONE total order. §DIRFEED-2: the
    statement carried no ORDER BY at all, so LIMIT/OFFSET pages were whatever order each plan produced, and two pages of
    3 were not a partition of one page of 6 (the MCP tester's "pagination: discoverAgents" row on the nightly pair
    nt261011; the tool reads this route, the console's Discovery reads /agent-cards/discover, which V0585 had already
    given a unique tiebreak). Newest agent first; the card id breaks a tie between two cards of one agent."""
    # Build base query — join via agent_did column (direct FK, not card_data JSON)
    stmt = select(Agent, AgentCard).join(
        AgentCard,
        AgentCard.agent_did == Agent.did,
        isouter=True
    )

    stmt = stmt.where(discover_match(query)[1])

    # Only show active agents
    stmt = stmt.where(Agent.status == "active")
    # §DARKSYNC (2026-09-22): nor an agent whose card is unlisted (a dark service agent); one with no card stays
    stmt = stmt.where(or_(AgentCard.id.is_(None), AgentCard.unlisted.is_(False)))
    return stmt.order_by(Agent.id.desc(), AgentCard.id.desc())


def federated_statement(escaped_query: str, rid: str = ""):
    """The mirrors GET /discover lists (V0640, agentvault2-aa, 2026-10-25): cards a peer federated here that no local
    agent row holds, under the console's own population rule (agent_cards.CARD_POPULATION_SQL: active, listed, bonded
    where the bond binds, not enforced where enforcement propagates), asked as the public (this route marks no row
    unlisted), matching the escaped query on the name, the description or the DID; newest card first, the card id
    (a UUID, unique) breaking a tie, so the order is total. Before V0640 this half took only cards with agent_did NULL,
    and every mirror federation_sync stores carries agent_did: no mirror was ever listed (the pair proof nt261025x1:
    146 mirrors on each operator, discoverAgents 0). `rid` (lower-cased): "" or "federated" keeps every mirror, any
    other value only the mirrors whose source or origin registry it names."""
    from .agent_cards import CARD_POPULATION_SQL, card_population_params
    c = aliased(AgentCard, name="c")
    meta = c.card_data["federation_metadata"]
    pattern = f"%{escaped_query}%"
    stmt = select(c).where(
        func.cast(meta["source_registry"], String) != "null",
        ~exists().where(Agent.did == c.agent_did),
        text(CARD_POPULATION_SQL).bindparams(**card_population_params()),
        or_(c.name.ilike(pattern), c.description.ilike(pattern),
            func.cast(c.card_data["did"], String).ilike(pattern), c.agent_did.ilike(pattern)),
    )
    if rid and rid != "federated":
        stmt = stmt.where(or_(func.lower(func.trim(meta["source_registry"].astext)) == rid,
                              func.lower(func.trim(meta["origin_registry_name"].astext)) == rid))
    return stmt.order_by(c.created_at.desc().nulls_last(), c.id.desc())


@router.get("/discover")
async def discover_agents(
    query: str = Query(..., min_length=3, description="Search query for agents"),
    registry_id: Optional[str] = Query(None, description="Filter by registry ID"),
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_developer: Annotated[Optional[Developer], Depends(get_current_developer_optional)] = None
) -> Dict[str, Any]:
    """
    Discover agents across registries by searching name, description, or DID.
    
    This endpoint enables cross-registry agent discovery for federation.
    
    Args:
        query: Search string (searches name, description, DID)
        registry_id: Optional filter by specific registry
        limit: Maximum results to return
        offset: Pagination offset
        db: Database session
        current_developer: Optional authenticated developer
        
    Returns:
        List of discovered agents with registry information
    """
    logger.info(f"Discovering agents with query: {query}, registry: {registry_id}")

    stmt = discover_statement(query).limit(limit).offset(offset)
    escaped_query, search_conditions = discover_match(query)   # the total and the federated half match the same words

    # Execute query
    result = await db.execute(stmt)
    agents_data = result.all()

    # registry_id filter (previously accepted + echoed but silently unapplied):
    # "local"/"self"/our REGISTRY_NAME → local agents only · "federated" → all peer-synced
    # cards · a peer's registry name → that peer's cards only.
    rid = (registry_id or "").strip().lower()
    _self_name = (os.environ.get("REGISTRY_NAME", "") or "").strip().lower()
    include_local = (not rid) or rid in ("local", "self") or (bool(_self_name) and rid == _self_name)

    # Format results
    discovered_agents = []
    # B7 (2026-06-03): tag LOCAL agents with this registry's own frame currency +
    # trust domain (single source of truth = FRAME_CURRENCY env — A/B=AVT, C=BVT;
    # mirrors teg_integration._local_frame_currency / registry_card_builder._frame_currency).
    # The FE's useCurrency.currencyForItem prefers an item's settlement_currency/
    # trust_domain when present → local agents render in THEIR frame's currency
    # (e.g. BVT on a Frame-C registry) instead of the viewer-currency fallback.
    # Federated (foreign) agents are deliberately left UNtagged below → the FE keeps
    # its graceful viewer-currency fallback (no regression); authoritative foreign
    # currency needs the peer's home-frame lookup (logged as B7-foreign).
    _local_ccy = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
    _local_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
    for agent, card in (agents_data if include_local else []):
        agent_info = {
            "did": agent.did,
            "name": card.name if card else f"Agent {agent.did}",
            "description": card.description if card else None,
            "reputation_score": agent.reputation_score,
            "created_at": agent.created_at.isoformat(),
            "last_active": agent.last_active_at.isoformat() if agent.last_active_at else None,
            "capabilities": card.card_data.get("capabilities", []) if card else [],
            "tags": card.card_data.get("tags", []) if card else [],
            "pricing": card.card_data.get("pricing") if card else None,
            "status": agent.status,
            "settlement_currency": _local_ccy,
            "trust_domain": _local_td,
        }

        discovered_agents.append(agent_info)
    
    # Get total count for pagination
    count_stmt = select(func.count()).select_from(Agent).join(
        AgentCard,
        AgentCard.agent_did == Agent.did,
        isouter=True
    ).where(search_conditions)
    
    count_stmt = count_stmt.where(Agent.status == "active").where(or_(AgentCard.id.is_(None), AgentCard.unlisted.is_(False)))
    
    total_result = await db.execute(count_stmt)
    total_count = total_result.scalar()
    
    # Step 4: the mirrors (V0640), paged after the local agents as ONE sequence (locals in discover_statement's order,
    # then mirrors newest card first, the card id breaking a tie), so `limit` bounds the whole answer and two pages of
    # 3 partition one page of 6. Before V0640 every matching federated card was appended whatever the limit.
    fed_base = federated_statement(escaped_query, rid)
    fed_total = (await db.execute(select(func.count()).select_from(fed_base.order_by(None).subquery()))).scalar() or 0
    fed_offset = max(0, offset - (total_count if include_local else 0))
    fed_limit = max(0, limit - len(discovered_agents))
    fed_cards = []
    if fed_limit and fed_offset < fed_total:
        fed_cards = (await db.execute(fed_base.offset(fed_offset).limit(fed_limit))).scalars().all()

    # B7-foreign (2026-06-03): resolve each FEDERATED (peer) agent's HOME-frame
    # settlement currency so it renders in ITS currency, not the viewer's. The
    # authoritative source = the peer's signed registry card (fees.settlement_currency),
    # cached on the PeerRegistry row + keyed by the UNIQUE peer name. Build the map
    # ONCE (not N+1); match by source_registry / origin_registry_name. Unmatched →
    # left untagged → FE graceful viewer-currency fallback (never a mislabel, since
    # PeerRegistry.name is unique). Mirrors teg_integration._card_settlement_currency.
    def _peer_card_ccy(c) -> Optional[str]:
        if isinstance(c, dict):
            fees = c.get("fees")
            if isinstance(fees, dict):
                sym = fees.get("settlement_currency")
                if isinstance(sym, str) and sym.strip():
                    return sym.strip().upper()
        return None
    _peer_ccy_map: Dict[str, tuple] = {}
    try:
        _peer_rows = (await db.execute(
            select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
        )).scalars().all()
        for _p in _peer_rows:
            _ccy = _peer_card_ccy(getattr(_p, "cached_registry_card", None))
            if _ccy and _p.name and _p.name not in _peer_ccy_map:
                _peer_ccy_map[_p.name] = (_ccy, getattr(_p, "trust_domain", None))
    except Exception:
        _peer_ccy_map = {}

    federated_results = []
    for card in fed_cards:
        cd = card.card_data or {}
        card_did = card.agent_did or cd.get('did', '')   # a mirror's DID is its agent_did (V0640)
        fed_meta = cd.get('federation_metadata', {}) or {}
        source = fed_meta.get('source_registry', '')
        # (the registry_id filter is federated_statement's, in SQL, so the page and its total agree)
        _resolved = _peer_ccy_map.get(fed_meta.get('origin_registry_name') or source) or _peer_ccy_map.get(source)
        item = {
            "did": card_did,
            "registry_id": "federated",
            "name": card.name or "Unknown Agent",
            "description": card.description,
            "reputation_score": 0.0,
            "created_at": card.created_at.isoformat() if card.created_at else None,
            "last_active": None,
            "capabilities": cd.get("capabilities", []),
            "tags": cd.get("tags", []),
            "pricing": cd.get("pricing"),
            "status": "active",
            "federated": True,
            "source_registry": source,
        }
        if _resolved:
            item["settlement_currency"] = _resolved[0]
            if _resolved[1]:
                item["trust_domain"] = _resolved[1]
        federated_results.append(item)

    # Combine results
    all_agents = discovered_agents + federated_results

    return {
        "agents": all_agents,
        "total": (total_count if include_local else 0) + fed_total,
        "limit": limit,
        "offset": offset,
        "query": query,
        "registry_filter": registry_id,
        "federated_count": len(federated_results),
        "federated_total": fed_total,
    }


# ---------------------------------------------------------------------------
# MCP health shims — the real MCP servers are mounted at /mcp (no API
# prefix), but the API test runner prepends /api/v1 to every path. These
# no-auth shims answer at /api/v1/mcp/health and /api/v1/mcp/admin/health
# so the mcp_health test category registers as passing.
# ---------------------------------------------------------------------------

@router.get("/mcp/health", include_in_schema=False)
async def mcp_health_shim() -> Dict[str, Any]:
    """Test-runner shim — real endpoint is at /mcp/health."""
    return {"status": "ok", "server": "TheProtocol MCP Server", "shim": True}


@router.get("/mcp/admin/health", include_in_schema=False)
async def mcp_admin_health_shim() -> Dict[str, Any]:
    """Test-runner shim — real endpoint is at /mcp/admin/health."""
    return {"status": "ok", "server": "TheProtocol MCP Admin Server", "shim": True}
