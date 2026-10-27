"""Internal endpoints used by sibling services (TEG, EventStore) on the same
Docker network. Not exposed for external use; relies on network isolation
(matches the pattern in `agent_locations.py:get_emission_policies_internal`).

Currently exposes:
  - POST /internal/agents/home-trust-domains — bulk home-trust-domain lookup
    for the TEG home-frame guard. Returns a mapping from DID → trust_domain
    string ("agentvault.com"|"frame-b.theprotocol.cloud"|"sandbox-b.test"|...)
    or null (unknown).

Native cards (no `source_registry` in federation_metadata) are returned as
THIS registry's own SPIRE_TRUST_DOMAIN so callers can compare directly
without scope-specific aliasing.
"""
from __future__ import annotations

import logging
import os
from typing import Annotated, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..services import spiffe_canonical

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_DIDS_PER_REQUEST = 1000


class HomeFramesRequest(BaseModel):
    dids: List[str] = Field(
        ...,
        min_length=1,
        max_length=_MAX_DIDS_PER_REQUEST,
        description="Agent DIDs to resolve. Capped to bound query size.",
    )


# Response schema kept stable: top-level key is `home_trust_domains` instead of
# the older `home_frames`. Resolver TEG-side reads this key.


async def _peer_trust_domain_for_canonical(
    db: AsyncSession,
    canonical: Tuple[str, str],
) -> Optional[str]:
    """Resolve a (trust_domain, registry_name) tuple to a trust_domain string
    using peer_registries as the authoritative source. Falls back to:
      - hard-known Frame B name list (legacy stamps)
      - the SPIFFE's own trust_domain (defensive)
    Returns None if classification fails entirely.
    """
    if not canonical:
        return None
    spiffe_td, name = canonical
    norm_name = spiffe_canonical._normalize_name(name)

    # peer_registries lookup with prefix variations
    candidates = {norm_name, f"op-{norm_name}", f"registry-{norm_name}"}
    stmt = select(models.PeerRegistry).where(
        func.lower(models.PeerRegistry.name).in_(list(candidates))
    )
    rows = (await db.execute(stmt)).scalars().all()
    for peer in rows:
        if peer.trust_domain:
            return peer.trust_domain.lower()

    # Hardcoded Frame B name fallback (handles legacy SPIFFE stamps where the
    # SPIFFE trust_domain says agentvault.com but the registry IS Frame B)
    if norm_name in spiffe_canonical._KNOWN_FRAME_B_NAMES:
        return "frame-b.theprotocol.cloud"

    # Defensive fallback to the SPIFFE's own trust_domain
    if spiffe_td:
        return spiffe_td.lower()

    return None


@router.post(
    "/internal/agents/home-trust-domains",
    summary="Bulk home-trust-domain lookup (internal; no auth, network-isolated)",
    description=(
        "Returns the trust_domain (frame identifier) of each DID's home "
        "registry. Native cards (created on this registry) return 'native'. "
        "Federated cards return the home registry's trust_domain (resolved via "
        "peer_registries.trust_domain, which is authoritative). Unknown DIDs return null."
    ),
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Internal"
)
async def get_home_trust_domains(
    request: HomeFramesRequest,
    db: Annotated[AsyncSession, Depends(database.get_db)] = None,
) -> Dict[str, Dict[str, Optional[str]]]:
    if not request.dids:
        return {"home_trust_domains": {}}

    # Our own SPIRE_TRUST_DOMAIN — used as the "native" answer so callers
    # can string-compare against their LOCAL_TRUST_DOMAIN directly.
    own_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com").lower()

    stmt = (
        select(
            models.AgentCard.agent_did,
            models.AgentCard.card_data,
        )
        .where(models.AgentCard.agent_did.in_(request.dids))
    )
    rows = (await db.execute(stmt)).all()

    # Build map of distinct source SPIFFE → resolved trust_domain (cache so
    # bulk lookups for the same source skip the peer query).
    resolved_cache: Dict[str, Optional[str]] = {}
    home_trust_domains: Dict[str, Optional[str]] = {}

    for did, card_data in rows:
        if not did:
            continue
        fed_meta = (card_data or {}).get("federation_metadata") or {}
        source = fed_meta.get("source_registry") or fed_meta.get("first_synced_from")
        if not source:
            home_trust_domains[did] = own_td
            continue
        if source in resolved_cache:
            home_trust_domains[did] = resolved_cache[source]
            continue
        canonical = spiffe_canonical.extract_canonical(source)
        if canonical is None:
            resolved_cache[source] = None
            home_trust_domains[did] = None
            continue
        td = await _peer_trust_domain_for_canonical(db, canonical)
        resolved_cache[source] = td
        home_trust_domains[did] = td

    for did in request.dids:
        home_trust_domains.setdefault(did, None)

    return {"home_trust_domains": home_trust_domains}


# Backwards-compat alias — older TEG resolvers may still hit /home-frames.
# Keep the same response shape but key it as expected by older callers.
@router.post(
    "/internal/agents/home-frames",
    summary="(Legacy alias) Bulk home-frame lookup",
    description=(
        "[DEPRECATED] Use POST /api/v1/internal/agents/home-trust-domains instead. "
        "Same response shape, canonical naming. A legacy alias, kept for older "
        "callers and to be removed."
    ),
    deprecated=True,
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Internal"
)
async def get_home_frames_legacy_alias(
    request: HomeFramesRequest,
    db: Annotated[AsyncSession, Depends(database.get_db)] = None,
) -> Dict[str, Dict[str, Optional[str]]]:
    body = await get_home_trust_domains(request, db)
    return {"home_trust_domains": body["home_trust_domains"]}
