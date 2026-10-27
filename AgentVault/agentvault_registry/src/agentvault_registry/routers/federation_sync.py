"""Federation synchronization endpoints for peer-to-peer registry communication.

This module contains the core federation protocol endpoints that enable
secure agent card synchronization between trusted registry instances.

All endpoints require mTLS authentication with valid SPIFFE SVIDs.

P1-001: Fixed synchronous ORM calls (db.query, db.commit, db.rollback) → async equivalents
P1-002: Fixed Session type annotation → AsyncSession to match get_db() yield type
"""
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
import secrets as _secrets
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

import time as _time

from .. import models, schemas
from ..database import get_db
from ..crud import crud_peer_registry
from ..identity import svid_client
from ..core.federation_auth import require_peer_registry_identity, FEDERATION_INTERNAL_SECRET
from ..core.mtls_auth import get_client_spiffe_id, TRUSTED_SPIFFE_DOMAINS
from ..core.client_ip import is_internal_request
from .. import security
from ..config import settings

# Cached display name for origin_registry_name stamping (TTL 5 min)
_registry_display_name: Optional[str] = None
_registry_display_name_ts: float = 0


async def _build_flare_sidecar(
    agent: Optional[models.Agent],
    dev: Optional[models.Developer],
    our_spiffe: str,
) -> Optional[Dict[str, Any]]:
    """§28 federation: stamp the per-agent flare payload onto an export card.

    Mirrors the local /agents/by-did flare shape so receiving registries can
    project it directly to UserAvatar prop names. Returns None when there's
    nothing meaningful to share (no tier, no overlay, no customization).

    Whitelist-stamps every field — adding a new flare-related column to
    Developer/Agent later does NOT auto-leak into the federation payload.
    """
    # §COSMETICS-ORIGIN (Commander-approved 2026-08-21): the guard used to be
    # "no developer tier, no sidecar", which silently dropped the flare of every
    # agent whose OWN tier is the interesting one. Measured on registry-a: the
    # six legacy service agents (CronAgent, WeatherAgent, TimezoneAgent,
    # UnitConverterAgent, CurrencyAgent, DnsSSLAgent) are tier=sovereign with
    # unique variants (aurora, phoenix, galaxy, matrix, sakura, crystal) and
    # exported a flare block with tier=NULL and variant=NULL, because their
    # owning developer holds no flare tier of their own.
    #
    # A sovereign tier is set ON THE AGENT and is never inherited (§pass39c), so
    # gating its export on the developer was always the wrong question. Export
    # when EITHER side has something to say; the dev-derived customization
    # fields below are already None-safe when the developer has no flare.
    _agent_tier = getattr(agent, "flare_tier", None) if agent is not None else None
    _dev_tier = getattr(dev, "flare_tier", None) if dev is not None else None
    if not _agent_tier and not _dev_tier:
        return None
    bears_corner = bool(getattr(agent, "bears_corner_flare", False)) if agent is not None else False
    bears_enc    = bool(getattr(agent, "bears_encirclement_flare", False)) if agent is not None else False
    # §pass39c (2026-05-18) — Sovereign agents NEVER inherit from dev. The
    # sovereign tier is per-agent (variant + overlay set on agents row),
    # NOT user-selectable. Without this guard, dev.flare_encirclement_overlay
    # (e.g. Commander's 'glitch') leaks onto every sovereign card's federated
    # export — confusing because the agent intentionally has NULL overlay.
    is_sovereign_agent = (
        agent is not None
        and getattr(agent, "flare_tier", None) == "sovereign"
    )
    return {
        "v": 1,
        "encirclement_variant": (
            (getattr(agent, "flare_encirclement_variant", None) if agent is not None else None)
            or (None if is_sovereign_agent else (getattr(dev, "flare_encirclement_variant", None) if bears_enc else None))
        ),
        "encirclement_overlay": (
            (getattr(agent, "flare_encirclement_overlay", None) if agent is not None else None)
            or (None if is_sovereign_agent else (getattr(dev, "flare_encirclement_overlay", None) if bears_enc else None))
        ),
        "corner_variant": (
            (getattr(agent, "flare_corner_variant", None) if agent is not None else None)
            or (None if is_sovereign_agent else (getattr(dev, "flare_corner_variant", None) if bears_corner else None))
        ),
        "tier": getattr(agent, "flare_tier", None) if agent is not None else None,
        "selected_corner_flare":       getattr(dev, "selected_corner_flare", None) if bears_corner else None,
        "selected_encirclement_flare": getattr(dev, "selected_encirclement_flare", None) if bears_enc    else None,
        "bears_corner_flare":          bears_corner,
        "bears_encirclement_flare":    bears_enc,
        "id":           getattr(dev, "flare_id", None),
        "display_name": getattr(dev, "flare_display_name", None),
        "tagline":      getattr(dev, "flare_tagline", None),
        "logo_url":     getattr(dev, "flare_logo_url", None),
        "link_url":     getattr(dev, "flare_link_url", None),
        "cause":        getattr(dev, "flare_cause", None),
        "accent_color": getattr(dev, "flare_accent_color", None),
        "granted_at":   dev.flare_granted_at.isoformat() if getattr(dev, "flare_granted_at", None) else None,
        "source_registry": our_spiffe,
        "stamped_at": datetime.now(timezone.utc).isoformat(),
    }


async def _get_display_name(db: AsyncSession) -> str:
    """Get human-readable registry name for federation card stamping.

    §pass34 (2026-05-17) — Resolution order (first non-empty wins):
      1. `registry_self.federation_name` — canonical, set at provision time
         for cloud-ops and via REGISTRY_FEDERATION_NAME env seed for mainframes.
         The right answer going forward; immune to admin profile drift.
      2. First admin developer's `display_name` — LEGACY transition fallback.
         The 0061 migration seeds registry_self from this same field, so this
         path is only taken before the migration runs (e.g. ephemeral sandboxes
         that haven't migrated yet). Will be removed in a follow-up cleanup
         once all production registries have run migration 0061.
      3. `settings.REGISTRY_NAME` env — compose-level identity, last resort.

    Returns 'Unknown Registry' when nothing is configured, to keep the export
    path running rather than hard-failing.

    Result is cached at module scope for 5 min (TTL also bypassed when a row
    is missing, so the first post-migration call after a restart picks up the
    seeded value immediately).
    """
    global _registry_display_name, _registry_display_name_ts
    if _registry_display_name and (_time.time() - _registry_display_name_ts < 300):
        return _registry_display_name

    name: Optional[str] = None
    try:
        # 1) registry_self singleton — the right answer.
        row = (await db.execute(
            select(models.RegistrySelf.federation_name).where(models.RegistrySelf.id == 1)
        )).first()
        if row and row[0]:
            name = str(row[0]).strip() or None
    except Exception:
        # Table doesn't exist yet (pre-migration registry). Fall through.
        name = None

    if not name:
        try:
            # 2) Legacy: first admin developer's display_name. Transition path
            #    until all production registries have run migration 0061.
            row = (await db.execute(
                select(models.Developer.display_name)
                .where(models.Developer.is_admin == True)
                .order_by(models.Developer.id)
                .limit(1)
            )).first()
            if row and row[0]:
                name = str(row[0]).strip() or None
        except Exception:
            name = None

    if not name:
        # 3) Compose env, last resort.
        name = getattr(settings, 'REGISTRY_NAME', None) or 'Unknown Registry'

    _registry_display_name = name
    _registry_display_name_ts = _time.time()
    return name

# Federation protocol schemas
class FederationPeerInfo(BaseModel):
    """Information about a federation peer."""
    id: int
    name: str
    base_url: str
    spiffe_id: str
    status: str = "ACTIVE"
    last_synced_at: Optional[datetime] = None

class AgentCardSyncData(BaseModel):
    """Agent card data for federation synchronization."""
    id: str  # UUID as string
    developer_id: int
    developer_name: str
    developer_verified: bool
    card_data: Dict[str, Any]
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    source_registry: str  # SPIFFE ID of the source registry
    # §DARKSYNC (2026-09-22): the home says this agent is UNLISTED (hidden from discovery, still federated). Carried on
    # the envelope as well as the card's listing block, because the v0.3 projection strips extensions.
    unlisted: bool = False

class FederationSyncRequest(BaseModel):
    """Request body for pushing agent cards to a peer."""
    source_registry: str = Field(..., description="SPIFFE ID of the source registry")
    agent_cards: List[AgentCardSyncData] = Field(..., description="List of agent cards to sync")
    sync_timestamp: datetime = Field(..., description="Timestamp of this sync operation")

class FederationSyncResponse(BaseModel):
    """Response from a sync operation."""
    status: str = Field(..., description="Status of the sync operation")
    cards_received: int = Field(..., description="Number of cards received")
    cards_updated: int = Field(..., description="Number of cards updated")
    cards_created: int = Field(..., description="Number of new cards created")
    sync_timestamp: datetime = Field(..., description="Timestamp of sync completion")

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/federation",
    tags=["Federation - Synchronization"]
)

# OWL18: Replaced local mTLS-only auth with flexible federation_auth.require_peer_registry_identity
# Supports both mTLS (production) and internal secret (Docker dev)


@router.get("/policy-compliance")
async def get_federation_policy_compliance(
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """
    Return this registry's active policy hash to a validated peer registry (mTLS). The answer has the shape of the
    admin endpoint /api/v1/admin/federation/policy-compliance, which stays for self-checks; cross-frame pollers read
    this one.

    \f
    Return THIS registry's active policy hash to a validated peer registry.

    Phase 9 (2026-04-27): mTLS-aware policy compliance endpoint. The
    central registry's compliance_poller fetches this via SPIFFE mTLS
    through the nginx-federation sidecar; the peer SVID is validated by
    require_peer_registry_identity.

    The legacy admin-JWT endpoint at /api/v1/admin/federation/policy-compliance
    is preserved (registry_health.py:516) for self-check use cases. This
    federation-namespaced version is what cross-frame pollers should hit.

    Response is identical in shape to the admin endpoint so the poller can
    use either source.
    """
    # §TRUSTCHAIN (2026-09-12): ONE hash. This used to hash the RAW policy row (or the shipped
    # default when no row existed) while the signed registry card publishes the hash of the
    # RESOLVED document (`frame_policy.ResolvedPolicy.hash`). Measured on EU, an amended frame:
    # the card said d2f2040f…, this endpoint said b82a5cad… — so a peer comparing the card it
    # fetched against what this endpoint served would have read a drift that never happened,
    # and the poller's baseline would have been a fact the card does not publish. Journal 45's
    # sentence is "the same hash is served by the federation compliance endpoint"; now it is.
    from ..services import frame_policy as fp

    policy = await fp.load(db)
    policy_hash = policy.hash()  # bare hex; the card prefixes 'sha256:' — same digest

    registry_did = getattr(settings, "REGISTRY_DID", None)

    logger.info(
        f"[federation/policy-compliance] Served to peer={spiffe_id} "
        f"hash={policy_hash[:16]}... version={policy.version} source={policy.source}"
    )

    return {
        "registry_did": registry_did,
        "policy_version": policy.version,
        "policy_source": policy.source,
        "policy_hash": policy_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/peers", response_model=List[FederationPeerInfo])
async def get_federation_peers(
    db: AsyncSession = Depends(get_db),  # P1-002: Fixed Session → AsyncSession
    spiffe_id: str = Depends(require_peer_registry_identity)
) -> List[FederationPeerInfo]:
    """Get list of trusted federation peers.
    
    Returns a list of active peer registries that this registry
    can synchronize with.
    
    Requires: Valid peer registry SPIFFE SVID
    """
    # Use async CRUD function
    peers = await crud_peer_registry.list_active_peer_registries(db, skip=0, limit=1000)
    
    peer_list = []
    for peer in peers:
        # Use own trust domain for peer SPIFFE ID construction
        _local_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
        peer_spiffe_id = f"spiffe://{_local_domain}/ns/agentvault/sa/registry-{peer.name.lower().replace(' ', '-')}"
        
        peer_list.append(FederationPeerInfo(
            id=peer.id,
            name=peer.name,
            base_url=peer.base_url,
            spiffe_id=peer_spiffe_id,
            status=peer.status or "ACTIVE",
            last_synced_at=peer.last_synced_at
        ))
    
    logger.info(f"Returning {len(peer_list)} federation peers to {spiffe_id}")
    return peer_list


async def _get_operator_location(db: AsyncSession) -> Optional[dict]:
    """Get this registry's operator location (first admin developer's coordinates).
    Used to stamp origin_registry_location in federation_metadata so receiving
    registries know WHERE this registry is geographically."""
    try:
        stmt = (
            select(models.Developer.latitude, models.Developer.longitude, models.Developer.location_label)
            .where(models.Developer.is_admin == True)
            .order_by(models.Developer.id.asc())
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.first()
        if row and row.latitude is not None:
            return {'latitude': row.latitude, 'longitude': row.longitude, 'label': row.location_label or ''}
    except Exception:
        pass
    return None


@router.post("/ironhand-probe")
async def federation_ironhand_probe(
    body: dict,
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """
    Peer-authenticated IRONHAND remote fire. A peer registry asks this registry, the home of the source agent, to
    fire its own probe agent, so the source's own SVID and balance are the ones used. Body: {source_did?,
    target_did, amount?}. A low, one-way transfer. Auth: a validated peer registry SVID (mTLS).

    \f
    Peer-authenticated IRONHAND remote fire — the cluster cockpit trigger.

    The hub (registry-a) calls this on a SOURCE's HOME registry so that registry fires its
    OWN embodied probe/agent — ITS SVID rides the hop, ITS balance moves. Routed under
    /api/v1/federation/* because that is the ONLY prefix the cross-registry mTLS gateway
    forwards (verified empirically: /api/v1/admin/* → gateway 404). Delegates to the same
    local-fire core /admin/ironhand/probe uses. Body: {source_did?, target_did, amount?}.
    The fire is low + one-way → Δ-safe. Auth: validated peer registry SVID (mTLS).
    """
    from agentvault_registry.routers.agent_mtls import _fire_probe_core
    logger.info(f"[FED ironhand-probe] peer={spiffe_id} source={(body or {}).get('source_did')}")
    return await _fire_probe_core(db, body or {})


@router.post("/canary-fire")
async def federation_canary_fire(
    body: dict,
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """
    Peer-authenticated scheduled canary fire: the master registry dispatches a due remote path here, and this
    registry fires its own canary path with its own canary agent (its credentials and SVID stay home). Idempotent on
    test_id: a repeated dispatch answers {replayed: true} and never fires again. Body: {remote_path_id, test_id}. A
    low canary transfer. Auth: a validated peer registry SVID (mTLS).

    \f
    §V0045 Canary Cockpit EXECUTOR — peer-authenticated scheduled-canary remote fire.

    The master (registry-a, CANARY_RUNNER_MODE=master) dispatches each due remote path
    here; THIS registry fires its OWN local canary_paths row with its OWN canary agent
    (creds/SVID stay home) — the same cluster-cockpit pattern as /ironhand-probe, on the
    same federation mTLS channel (the only prefix the cross-registry gateway forwards).
    Idempotent on test_id (canary_test_results replay guard): duplicate dispatches ack
    {replayed:true} and never re-fire. Body: {remote_path_id:int, test_id:"canary-…"}.
    Low-amount canary transfer → Δ-safe. Auth: validated peer registry SVID (mTLS).
    """
    from agentvault_registry.background_tasks.canary_runner import execute_canary_fire
    body = body or {}
    logger.info(
        f"[FED canary-fire] peer={spiffe_id} path={body.get('remote_path_id')} test={body.get('test_id')}"
    )
    try:
        return await execute_canary_fire(
            db, int(body.get("remote_path_id") or 0), str(body.get("test_id") or "")
        )
    except Exception as e:
        logger.error(f"[FED canary-fire] failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)[:200]}


@router.post("/canary-refill")
async def federation_canary_refill(
    body: dict,
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """
    Peer-authenticated canary refill: the master registry asks this registry to top up its own canary senders from
    its own treasury (the units never leave this registry). Body: {dry_run?, max_fund?}. Idempotent per sender per
    hour. A treasury-to-agent transfer through the registry rail. Auth: a validated peer registry SVID (mTLS).

    \f
    §R5 (batch 2, 2026-09-05) — peer-authenticated canary REFILL. The master asks this
    registry to top up ITS OWN canary senders from ITS OWN treasury (the canary-fire pattern:
    same federation mTLS channel, same identity dependency, the money never leaves the home).
    Replaces the master logging in here with an admin PASSWORD over the host port.
    Body: {dry_run?: bool, max_fund?: int}. Idempotent per sender per hour (refill_reference).
    Δ-safe: treasury → agent through the registry rail (TokensTransferred emitted).
    """
    from agentvault_registry.background_tasks.canary_rebalancer import refill_local_senders
    body = body or {}
    logger.info(f"[FED canary-refill] peer={spiffe_id} dry_run={bool(body.get('dry_run'))}")
    try:
        return await refill_local_senders(
            requested_by=spiffe_id, dry_run=bool(body.get("dry_run")), max_fund=body.get("max_fund"),
        )
    except Exception as e:
        logger.error(f"[FED canary-refill] failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────────────
# §FEDSYNC-V2 (2026-08-05) — cheap answers to the two questions every sync
# cycle asks, so the expensive walk runs only when the answer demands it.
#
#   /sync-watermark — "does this peer have anything NEWER than my cursor?"
#       One indexed read (ix_agent_cards_updated_at_id). The steady state of
#       this mesh is 0 changed cards/hour across 18 registries on one host;
#       before this endpoint every such answer cost a full-table scan + a
#       serialized empty page per peer per cycle.
#
#   /sync-digest — "does this peer's CORPUS differ from mine at all?"
#       Replaces the timed §SYNCPAGE full re-walk (8,900 cards × every peer ×
#       every FULL_RECONCILE_DAYS) as the standing completeness guarantee.
#       Buckets by ORIGIN registry, which is hop-independent (stamped once at
#       first export, preserved through relays) and therefore comparable
#       between ANY two registries — unlike source_registry (last hop) or
#       updated_at (LOCAL ingest time on every node, proven differing).
#       The per-card term mirrors the §2026-06-16 ingest normalization
#       (_norm_card include_sticky=False) EXACTLY: two copies digest-equal
#       ⟺ the upsert would call them "unchanged". flare/iconUrl are excluded
#       because the ingest's preserve/tier-rank guards make them legitimately
#       diverge per node; updated_at/federation_metadata/did/location are
#       per-registry bookkeeping. jsonb cast: op-tier DBs store card_data as
#       json (provisioning vintage), mainframes as jsonb — ::jsonb
#       canonicalizes both (verified byte-identical md5 across PG 15/16).
#
# Old clients never call these; old servers 404 them and the caller falls
# back to exactly the pre-§FEDSYNC-V2 behavior. Both endpoints are peer-auth
# (same gate as /agent-cards).
# ─────────────────────────────────────────────────────────────────────────────

FEDSYNC_DIGEST_ALGO = "fedsync-digest-v1"

# Shared between the serving endpoint below and the worker's local computation
# (background_tasks/federation_sync.py imports it) — ONE definition, so the two
# sides can never drift.
FEDSYNC_DIGEST_SQL = """
SELECT
  COALESCE(card_data::jsonb->'federation_metadata'->>'origin_registry_name', :own_name) AS bucket,
  count(*)::bigint AS n,
  COALESCE(sum(('x' || substr(md5(
      ((card_data::jsonb - 'updated_at' - 'federation_metadata' - 'did' - 'location' - 'flare' - 'iconUrl')::text)
      || coalesce(name,'') || '|' || coalesce(description,'') || '|' || is_active::text
  ), 1, 12))::bit(48)::bigint), 0)::numeric AS s
FROM agent_cards
WHERE is_active
GROUP BY 1
"""


# §TRAVELREC / §DIRFEED — THE SHAPE OF WHAT WE EXPORT IS PART OF WHETHER TWO CORPORA AGREE.
# The digest hashes STORED cards, so the day this registry starts DERIVING a new field onto the
# cards it exports, every bucket still matches and every peer skips the walk entirely. The cards
# did not change; what we say about them did. §DIRFEED's answer from the reader's side is "name
# what you extract and re-read everything when that changes" — this is the writer's half: bump
# this string whenever the export gains or drops a derived field, and every peer re-walks once.
# §BONDFILL-3 — bumped because the maturity snapshot changed SHAPE (v1 -> v2, the relative trust
# gate) inside an extension every bonded card already carries. Measured on ASIA after V0345: its
# mirrors still held the v1 snapshot from 07:49, because no card's clock had moved and nothing
# told ASIA the shape of what it had already read was stale.
CARD_EXPORT_VERSION = "2026-09-11.bondfill3"


async def compute_digest_buckets(db: AsyncSession, own_name: str) -> Dict[str, Dict[str, Any]]:
    """Run the digest SQL and shape it as {bucket: {count, sum}} (sum as str —
    48-bit terms summed over ~10k rows exceed JS-safe integers)."""
    from sqlalchemy import text as _sql_text
    res = await db.execute(_sql_text(FEDSYNC_DIGEST_SQL), {"own_name": own_name})
    out: Dict[str, Dict[str, Any]] = {}
    for bucket, n, s in res.fetchall():
        out[str(bucket)] = {"count": int(n), "sum": str(int(s))}
    return out


@router.get("/sync-watermark")
async def get_sync_watermark(
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
) -> Dict[str, Any]:
    """
    The newest updated_at this registry could export, plus the active card count: a peer whose cursor is already
    past max_updated_at has nothing to pull and skips the page walk. Auth: a validated peer registry SVID (mTLS).

    \f
    §FEDSYNC-V2 — the newest updated_at this registry could export, plus the
    active-card count. A peer whose cursor is already past max_updated_at has
    nothing to pull and skips the page walk entirely. Index-backed: ~0.1 ms.
    """
    from sqlalchemy import text as _sql_text
    row = await db.execute(_sql_text(
        "SELECT (SELECT max(updated_at) FROM agent_cards), "
        "(SELECT count(*) FROM agent_cards WHERE is_active)"
    ))
    max_uat, active_count = row.fetchone()
    return {
        "max_updated_at": max_uat.isoformat() if max_uat else None,
        "active_count": int(active_count or 0),
        # §TRAVELREC — the watermark is the FIRST gate a peer hits, and it answers a question about
        # STORED rows. A derived field added to the export changes no row, so a peer would skip
        # here and never reach the digest probe, let alone the feed. Publish the export shape at
        # the first gate too, or the version check sits behind a door nobody opens.
        "export_version": CARD_EXPORT_VERSION,
    }


@router.get("/sync-digest")
async def get_sync_digest(
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
) -> Dict[str, Any]:
    """
    A digest of this registry's card corpus per origin registry. A peer compares it bucket by bucket (skipping its
    own bucket) and walks the pages only where a bucket differs. Auth: a validated peer registry SVID (mTLS).

    \f
    §FEDSYNC-V2 — per-origin corpus digest. See the module comment above for
    why origin buckets are the only cross-registry-comparable key. The caller
    compares bucket-by-bucket (skipping its OWN bucket — it is authoritative
    for its natives) and runs the read-repair walk only on mismatch.
    """
    own_name = await _get_display_name(db)
    buckets = await compute_digest_buckets(db, own_name)
    return {
        "algo": FEDSYNC_DIGEST_ALGO,
        "own_name": own_name,
        "buckets": buckets,
        "export_version": CARD_EXPORT_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/agent-cards", response_model=List[AgentCardSyncData])
async def get_agent_cards_for_sync(
    since: Optional[datetime] = Query(None, description="Return cards updated after this timestamp"),
    limit: int = Query(100, ge=1, le=20000, description="Maximum number of cards to return"),
    paged: bool = Query(
        False,
        description=(
            "§SYNCPAGE (2026-08-03): cursor-walk mode. Serves a PURE updated_at-ASC "
            "page (id tiebreak) with NO flare-augmentation prepend, and treats a "
            "missing `since` as epoch. Old clients never send it; old servers "
            "ignore it — both directions degrade to the pre-§SYNCPAGE behavior."
        ),
    ),
    peer_protocol_version: str = Query(
        "1.0",
        description=(
            "Q-C W11 / BL-15 (2026-05-12): A2A protocol version the calling peer speaks. "
            "'1.0' (default) → full dual-shape cards (no behavior change vs pre-Q-C). "
            "'0.3' or '0.3.0' → strict-v0.3 projection (strips supportedInterfaces / "
            "securitySchemes / security / extensions). Per Commander Q10 signoff."
        ),
    ),
    listing_carry: bool = Query(
        False,
        description=(
            "§DARKSYNC (2026-09-22): the puller stores unlisted mirrors and hides them from its discovery. "
            "An unlisted card is then exported IN FULL with its listing block and the envelope's `unlisted`. "
            "A puller that does not send it keeps receiving the content-free §LISTPROP tombstone."
        ),
    ),
    db: AsyncSession = Depends(get_db),  # P1-002: Fixed Session → AsyncSession
    spiffe_id: str = Depends(require_peer_registry_identity),
    response: Response = None,  # §SYNCPAGE — truth headers for the paged walk
) -> List[AgentCardSyncData]:
    """Get agent cards for federation synchronization.
    
    Returns agent cards that have been created or updated since the
    specified timestamp. If no timestamp is provided, returns the most
    recently updated cards up to the limit.
    
    Requires: Valid peer registry SPIFFE SVID
    """
    logger.info(f"Peer {spiffe_id} requesting agent cards since {since}")
    
    our_spiffe_id = svid_client.get_spiffe_id() or "spiffe://agentvault.com/ns/agentvault/sa/registry-main"
    
    # Use async CRUD functions
    if paged and not since:
        # §SYNCPAGE — a paged walk with no cursor starts at epoch (the old
        # no-`since` branch served the NEWEST page, which made a fresh peer's
        # truncation gap consist of the OLDEST, most dormant agents — the ones
        # least likely to ever be re-shipped by an update).
        since = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if since:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        cards = await crud_peer_registry.get_agent_cards_updated_since(db, since, limit, ascending=paged)
    else:
        cards = await crud_peer_registry.get_recent_agent_cards(db, limit)

    # §SYNCPAGE truth headers — the echo-prevention filter below shrinks pages
    # AFTER the SQL limit, so "fewer items than limit" is NOT a reliable
    # end-of-data signal for the client (live E2E 2026-08-03: frame-c served
    # 484 of a 500-limit page to op-doha while 7.4k rows remained — the walk
    # read it as caught-up and truncated). State the truth out-of-band: the
    # PRE-filter CRUD page being full ⇒ more data exists, and the exact resume
    # cursor is the last ASC row's updated_at. Old clients ignore the headers.
    if paged and response is not None and len(cards) == limit and cards:
        response.headers["X-Sync-Has-More"] = "1"
        try:
            response.headers["X-Sync-Next-Cursor"] = cards[-1].updated_at.isoformat()
        except Exception:
            pass

    # §SYNCPAGE (2026-08-03) — a paged walk visits EVERY card in updated_at
    # order, so nothing can be "buried past limit": the burial problem the
    # augmentation exists to solve is structurally absent on this path. Worse,
    # the prepended augment cards carry timestamps NEWER than the page range
    # and would poison the client's cursor (cursor = max(updated_at seen)
    # would leap past unseen rows). Skip it entirely when paged.
    if not paged:
        # §pass38d (2026-05-18) — Export-side augmentation for flare/avatar bearers.
        # Mirror of the Discovery-side augmentation shipped in §pass38c. Native
        # cards with flare_tier (developers.flare_tier) or iconUrl set rank
        # by updated_at DESC and can fall past `limit` when sim agents churn
        # faster. The result: relays propagate stale versions through the BFS
        # mesh and peers never see the fresh flare/avatar.
        # Fix: prepend any native flare/iconUrl-bearing cards not already in the
        # primary result set. Same OR predicate as the Discovery augmentation
        # (agent_cards.py:335) so the two are symmetric.
        try:
            from sqlalchemy import or_ as _or, text as _text
            from sqlalchemy.orm import selectinload as _selectinload
            _already_ids = {c.id for c in cards}
            _aug_stmt = (
                select(models.AgentCard)
                .options(_selectinload(models.AgentCard.developer))
                .outerjoin(
                    models.Developer,
                    models.Developer.id == models.AgentCard.developer_id,
                )
                .where(
                    models.AgentCard.is_active.is_(True),
                    _or(
                        _text("(card_data->'flare') IS NOT NULL"),
                        models.Developer.flare_tier.isnot(None),
                        _text("(card_data->>'iconUrl') IS NOT NULL AND length(card_data->>'iconUrl') > 0"),
                    ),
                )
            )
            # §2026-06-22 FIX (project_federation_flare_augmentation_fullcorpus): bound the
            # augmentation by `since` + limit. Without this it re-selected ~98.5% of the ACTIVE
            # corpus on EVERY federation pull regardless of changes (no since-filter, no limit)
            # → full-corpus wire payload + the agent_cards FOR-UPDATE convoy that drove the
            # host load-327 incident. The §pass38d intent is to rescue FRESH flare/avatar cards
            # that fell past `limit` — "fresh" means updated since the last sync — so bounding
            # by `since` preserves that intent while restoring true deltas. A no-`since` full
            # pull stays unbounded by design (a cold peer legitimately wants everything).
            if since:
                _aug_stmt = _aug_stmt.where(models.AgentCard.updated_at > since)
            _aug_stmt = _aug_stmt.limit(limit)
            _aug_res = await db.execute(_aug_stmt)
            _aug_items = [c for c in _aug_res.scalars().all() if c.id not in _already_ids]
            if _aug_items:
                cards = list(_aug_items) + list(cards)
                logger.info(f"[FEDERATION EXPORT] flare/avatar augmentation: {len(_aug_items)} cards prepended")
        except Exception as _aug_e:  # noqa: BLE001
            logger.warning(f"[FEDERATION EXPORT] augmentation failed: {_aug_e}")

    sync_data = []
    skipped_federated = 0
    # W3 (2026-05-05) — canonical SPIFFE comparison (was substring match).
    # Substring failed across legacy + current SPIFFE patterns (e.g. legacy
    # `spiffe://agentvault.com/ns/agentvault/sa/registry-op-paris` doesn't
    # substring-match modern `spiffe://agentvault.com/operator/op-paris/registry`
    # in either direction → cards leaked back to source). canonical_equals
    # extracts (trust_domain, registry_name) from both sides; same name → same
    # registry, even across legacy and current patterns.
    from ..services.spiffe_canonical import canonical_equals as _canon_eq
    # §ECHOFLOOD (2026-10-09) — the requester under EVERY form a copy of its cards can be recorded here (its peer
    # row's name as well as the id it presents): a frame presenting its per-service SVID matched none of them and was
    # served its own cards back on every full read. A failed lookup keeps the presented id alone, as before.
    from ..core.federation_auth import requester_source_forms
    try:
        _requester_forms = await requester_source_forms(db, spiffe_id)
    except Exception as _rf_e:  # noqa: BLE001 — the feed must not fail on this lookup; say so
        logger.warning("[ECHOFLOOD] could not resolve the forms of requester %s (%s); echo prevention matches "
                       "its presented id only", spiffe_id, _rf_e)
        _requester_forms = {spiffe_id}

    # §28 (2026-05-15) — bulk-load Agent rows by DID for every export card in
    # ONE query so the per-card flare stamp can read per-agent overrides
    # (flare_encirclement_variant/overlay/corner_variant, bears_*_flare flags)
    # without N+1 db hits. Cards without a matching agent_did still get the
    # dev-level fallback in _build_flare_sidecar.
    _export_dids = [c.agent_did for c in cards if c.agent_did]
    _agent_by_did: Dict[str, models.Agent] = {}
    if _export_dids:
        _agents_q = await db.execute(
            select(models.Agent).where(models.Agent.did.in_(_export_dids))
        )
        for _a in _agents_q.scalars().all():
            _agent_by_did[_a.did] = _a

    # §REPBOND (2026-09-05) — batch-load the bond state of the native cards in this page so
    # the exported card carries the bond extension (derive-time, never persisted; a relayed
    # card keeps whatever its origin put on it).
    from agentvault_registry.services import reputation_bond as _rb
    try:
        _bond_card_state = await _rb.card_states(db, [c.agent_did for c in cards if c.agent_did])
    except Exception as _rb_e:  # noqa: BLE001 — the fan-out must not fail on a bond read; say so
        logger.error("[REPBOND] fan-out bond state load failed: %s", _rb_e)
        _bond_card_state = {}
    # §ENFPROP (2026-09-05) — the same shape for the ENFORCEMENT state (suspended/revoked): derived onto
    # the exported card, never persisted; a mirror answers its gates from this block.
    from agentvault_registry.services import enforcement_propagation as _ep
    try:
        _enf_card_state = await _ep.card_states(db, [c.agent_did for c in cards if c.agent_did])
    except Exception as _ep_e:  # noqa: BLE001 — the fan-out must not fail on this read; say so
        logger.error("[ENFPROP] fan-out enforcement state load failed: %s", _ep_e)
        _enf_card_state = {}
    # §TRAVELREC (2026-09-11) — and the WORK RECORD, which until now did not travel at all.
    # The bond crossed because it is injected here; the record did not because its injector was
    # only ever called on the agent's OWN well-known card. So a peer mirrored a bonded, certified,
    # enforced card carrying no evidence of the work that earned any of it, and its discovery page
    # rendered nothing where the home frame renders "250 jobs verified". Same class as §FANOUTFIX:
    # a capability built correctly and wired at one of its call sites.
    from agentvault_registry.services import track_record as _tr
    try:
        _tr_card_state = await _tr.compact_track_records(db, [c.agent_did for c in cards if c.agent_did])
    except Exception as _tr_e:  # noqa: BLE001 — a record read must not fail the fan-out; say so
        logger.error("[TRAVELREC] fan-out track-record load failed: %s", _tr_e)
        _tr_card_state = {}
    # §LISTPROP (2026-09-08) — the LISTING state needs no state load at all: unlike enforcement
    # (which lives on the `agents` row) it lives on the card row this loop already holds. What it
    # does need is the mode, read once per fan-out rather than per card.
    from agentvault_registry.services import listing_propagation as _lp
    _listing_mode = _lp.propagation_mode()
    _listing_tombstones = 0
    _listing_carried = 0
    for card in cards:
        # OWL24 + OWL30: Echo prevention with hub relay.
        # Native cards: always served to any peer.
        # Federated cards: served to peers EXCEPT back to the original source
        #   (prevents infinite loops while enabling card propagation through hub).
        card_data = card.card_data or {}
        fed_meta = card_data.get('federation_metadata', {})
        card_source = fed_meta.get('source_registry') or fed_meta.get('first_synced_from')
        if card_source:
            # Don't send a card back to the registry it came from
            if any(_canon_eq(card_source, _f) for _f in _requester_forms):
                skipped_federated += 1
                continue

        # §LISTPROP (2026-09-08) — AN UNLISTED CARD LEAVES AS A TOMBSTONE, NEVER AS CONTENT.
        # Before this, `unlisted` removed the card from the export selector entirely, so a peer
        # holding the mirror was told nothing and kept showing it forever (absence does not
        # propagate). The tombstone carries the DID and the listing block and NOTHING else, so
        # §DISCREFINE's posture is kept: the agent's name, skills, pricing and URL still never
        # leave this registry. `updated_at` is the epoch and `is_active` is False on purpose —
        # that is what makes the envelope harmless to a peer that does not speak §LISTPROP
        # (see the module docstring's four quadrants).
        # §DARKSYNC (2026-09-22): to a puller that asked (`listing_carry`), under enforce, the unlisted card leaves IN
        # FULL with its listing block and the envelope flag (below), because unlisted means "not in discovery", not
        # "never leaves home". Everyone else still receives the tombstone.
        _carry_unlisted = bool(listing_carry) and _listing_mode == "enforce" and bool(getattr(card, "unlisted", False))
        # §ECHO-2 (2026-09-28): the block names the card's HOME, so two relays of one mirror hand out the same block
        # (see listing_propagation.export_state); used by both unlisted branches below, so a listed card skips it.
        _listing_state = (_lp.export_state(card_data, card.updated_at, relayed=bool(card_source))
                          if bool(getattr(card, "unlisted", False)) else None)
        if _listing_mode != "off" and bool(getattr(card, "unlisted", False)) and not _carry_unlisted:
            _listing_tombstones += 1
            _lp.count("exported_tombstone", _listing_mode)
            sync_data.append(AgentCardSyncData(
                id=str(card.id),
                developer_id=card.developer_id,
                developer_name=_lp.TOMBSTONE_NAME,
                developer_verified=False,
                card_data=_lp.tombstone_card_data(
                    card.agent_did, _listing_state, card_source,
                ),
                name=_lp.TOMBSTONE_NAME,
                description=None,
                is_active=False,
                created_at=card.created_at,
                updated_at=_lp.TOMBSTONE_EPOCH,
                source_registry=card_source or our_spiffe_id,
            ))
            continue

        # Ensure DID is included in card_data for federation peers
        export_card_data = dict(card.card_data) if card.card_data else {}
        if card.agent_did and 'did' not in export_card_data:
            export_card_data['did'] = card.agent_did

        # Stamp origin_registry_name for relay attribution (self-describing cards)
        if 'federation_metadata' not in export_card_data:
            export_card_data['federation_metadata'] = {}
        if 'origin_registry_name' not in export_card_data['federation_metadata']:
            export_card_data['federation_metadata']['origin_registry_name'] = await _get_display_name(db)

        # §REPBOND — native cards carry this registry's bond truth as a top-level extension.
        if not card_source and card.agent_did:
            export_card_data = _rb.inject_extension(export_card_data, _bond_card_state.get(card.agent_did))
            export_card_data = _ep.inject_extension(export_card_data, _enf_card_state.get(card.agent_did))
            # §TRAVELREC — only when there IS history. An agent with no settled work exports no
            # extension at all, so a peer distinguishes "no record" from "a record of zero", which
            # are different facts and must not render the same.
            _tr_compact = _tr_card_state.get(card.agent_did)
            if _tr_compact:
                export_card_data = _tr.inject_track_record_extension(
                    export_card_data, card.agent_did, compact=_tr_compact)
        # Include origin REGISTRY's geographic position in federation_metadata.
        # This tells receiving registries WHERE the home registry is on the globe.
        # ONLY stamp on NATIVE cards (originated here). For relayed cards, preserve
        # the original source's location — don't overwrite with ours.
        is_native_card = (
            'origin_registry_name' not in export_card_data.get('federation_metadata', {})
            or export_card_data['federation_metadata'].get('origin_registry_name') == await _get_display_name(db)
        )
        if 'origin_registry_location' not in export_card_data['federation_metadata'] and is_native_card:
            op_loc = await _get_operator_location(db)
            if op_loc:
                export_card_data['federation_metadata']['origin_registry_location'] = op_loc

        # Include developer location for agent-level positioning.
        # For relayed cards, the location was set by the original source and travels as-is.
        if 'location' not in export_card_data and card.developer and card.developer.latitude is not None:
            export_card_data['location'] = {
                'latitude': card.developer.latitude,
                'longitude': card.developer.longitude,
                'label': card.developer.location_label or '',
            }

        # §28 (2026-05-15) — Stamp per-agent flare sidecar (only on NATIVE
        # cards — relayed cards already carry their origin's flare and we
        # must not overwrite). Helper returns None when the dev has no
        # flare; in that case we don't add the key, so old code on the
        # peer side sees no schema change.
        if is_native_card and 'flare' not in export_card_data:
            _agent_for_did = _agent_by_did.get(card.agent_did) if card.agent_did else None
            _flare = await _build_flare_sidecar(_agent_for_did, card.developer, our_spiffe_id)
            if _flare:
                export_card_data['flare'] = _flare

        # §DARKSYNC: the listing block goes on LAST (after every other extension), and before the v0.3 projection,
        # which strips extensions; the envelope's `unlisted` carries the word past it.
        if _carry_unlisted:
            export_card_data = _lp.inject_extension(export_card_data, _listing_state)
            _listing_carried += 1
            _lp.count("exported_carried", _listing_mode)

        # Q-C W11 / BL-15 (2026-05-12): per Commander Q10, stamp the
        # protocol version we're emitting and optionally project to strict v0.3
        # when the peer asks. mTLS / peer trust / topology are unchanged — this
        # only touches the response body shape.
        peer_speaks_v03 = peer_protocol_version.strip().startswith("0.3")
        if peer_speaks_v03:
            try:
                from ..services.a2a_v1.compat import render_for_v03_peer
                export_card_data = render_for_v03_peer(export_card_data)
                export_card_data.setdefault('federation_metadata', {})
                export_card_data['federation_metadata']['protocol_version'] = "0.3.0"
            except Exception as e:
                logger.warning(f"[BL-15] v0.3 projection failed for card {card.id}: {e}")
                export_card_data.setdefault('federation_metadata', {})
                export_card_data['federation_metadata']['protocol_version'] = export_card_data.get('protocolVersion', "1.0")
        else:
            export_card_data.setdefault('federation_metadata', {})
            export_card_data['federation_metadata']['protocol_version'] = export_card_data.get('protocolVersion', "1.0")

        sync_data.append(AgentCardSyncData(
            id=str(card.id),
            developer_id=card.developer_id,
            developer_name=card.developer.name,
            developer_verified=card.developer.is_verified,
            card_data=export_card_data,
            name=card.name,
            description=card.description,
            is_active=card.is_active,
            created_at=card.created_at,
            updated_at=card.updated_at,
            source_registry=fed_meta.get('source_registry') or our_spiffe_id,
            unlisted=_carry_unlisted,
        ))
    
    if skipped_federated:
        logger.info(f"OWL24: Skipped {skipped_federated} federated cards (echo prevention)")
    if _listing_tombstones:
        logger.info(f"[LISTPROP] {_listing_tombstones} of {len(sync_data)} exported as listing "
                    f"tombstones (mode={_listing_mode}) to peer {spiffe_id}")
    if _listing_carried:
        logger.info(f"[DARKSYNC] {_listing_carried} of {len(sync_data)} unlisted cards exported in full, flagged "
                    f"(mode={_listing_mode}) to peer {spiffe_id}")
    logger.info(f"Returning {len(sync_data)} native agent cards to peer {spiffe_id}")
    return sync_data


# =============================================================================
# Registry-card fan-out (§pass66 — 2026-05-22)
# =============================================================================
# Mirrors the agent-cards fan-out above but for Registry Card v0.3. Solves a
# topology problem on cloud-ops:
#
#   - cloud-op REGISTRY containers live on `operator-net` only (NOT on the
#     central reg's `agentvault_identity_network`)
#   - peer URLs like `https://op-london.op.theprotocol.cloud:8443` resolve via
#     PUBLIC DNS from operator-net → the host's public IP (`:8443`) → nginx-a
#     (Frame A's federation nginx) → SNI doesn't match a vhost for op-london
#     → cert mismatch + 404 → httpx.ConnectError → silently swallowed at DEBUG
#     log level → `cached_registry_card` rows for the 10 discovered peers
#     never populate.
#
# Calling cloud-op's federation_sync directly to each peer fundamentally
# can't reach `discovered` peers' nginx-federation containers (Docker DNS
# alias only resolves inside agentvault_identity_network, where the cloud-op
# isn't joined). The fix is the same pattern that makes AGENT cards work:
# the cloud-op's parent mainframe fans out ALL the cards it has cached.
#
# So this endpoint returns:
#   1. THE central reg's OWN current registry card (always fresh from builder)
#   2. Every `cached_registry_card` from the central reg's `peer_registries`
#      where status=ACTIVE — these are cards the central reg ALREADY pulled
#      from its peers (which it CAN reach because it's on the identity net).
#
# Calling pattern: cloud-op federation_sync → its DIRECT peer's
# `/api/v1/federation/registry-cards` → receives full fleet view in one call.
# Mirror of how cloud-ops get the full agent-card fleet via `/agent-cards`.

class RegistryCardSyncData(BaseModel):
    """One peer's registry card payload + the etag the central reg saw last."""
    peer_name: str
    base_url: str
    trust_domain: Optional[str] = None
    card: Dict[str, Any]
    card_etag: Optional[str] = None
    card_signature_verified: bool = False
    card_signature_kid: Optional[str] = None
    card_last_pulled_at: Optional[datetime] = None
    # §2026-06-18 Federated Stock Cards fan-out CARRY: the serving registry's cached
    # AGORA catalog for this peer (its own for the self entry), so a consumer learns
    # cross-frame venues' catalogs transitively — no direct reachability needed.
    # Shape: {listings:[...], digest:"sha256:…", currency, signature_verified}. Absent
    # when the peer has no catalog. Verified consumer-side against the digest signed
    # into this same peer's (relayed) registry card.
    stock_card: Optional[Dict[str, Any]] = None


@router.get("/registry-cards", response_model=List[RegistryCardSyncData])
async def get_registry_cards_for_sync(
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
) -> List[RegistryCardSyncData]:
    """Fan-out: return THIS registry's own card + all `cached_registry_card`
    rows from the central reg's `peer_registries` (status=ACTIVE).

    Cloud-ops can't reach `discovered` peer URLs on the operator-net Docker
    bridge (no DNS alias): they call THIS endpoint on their direct mainframe
    peer to get the full fleet's registry cards in one mTLS request. Mirrors
    the working `/federation/agent-cards` fan-out.

    Auth: same SPIFFE-SVID gate as the rest of `/federation/*` (peer registry
    must present a valid client cert from a trusted trust_domain).
    """
    from sqlalchemy import select as _sel
    from ..services.registry_card_builder import build_registry_card
    from ..services.stock_card_builder import (
        exchange_enabled as _sc_enabled, build_stock_card as _build_sc,
        market_enabled as _mk_en, market_epoch as _mk_ep,
    )

    out: List[RegistryCardSyncData] = []

    # §2026-06-18 Federated Stock Cards fan-out CARRY: ship our cached peer catalogs
    # (+ our own) alongside each card so a consumer learns cross-frame venues' catalogs
    # transitively — no direct reachability needed (mirrors the registry-card BFS).
    def _sc_payload(listings, digest, currency, verified, market=None, market_epoch=None):
        p = {"listings": listings or [], "digest": digest,
             "currency": currency, "signature_verified": bool(verified)}
        if isinstance(market, dict):  # §2026-06-25 carry the coarse market block transitively
            p["market"] = market
            p["market_epoch"] = market_epoch
        return p
    fsc_by_spiffe: Dict[str, Any] = {}
    try:
        for _r in (await db.execute(_sel(models.FederatedStockCard))).scalars().all():
            fsc_by_spiffe[_r.source_spiffe_id] = _sc_payload(
                _r.listings_json, _r.digest, _r.currency, _r.signature_verified,
                market=getattr(_r, "market_json", None), market_epoch=getattr(_r, "market_epoch", None))
    except Exception:
        fsc_by_spiffe = {}  # table absent (pre-0093) → carry simply off
    own_sc = None
    try:
        if _sc_enabled():
            _doc = await _build_sc(db=db, sign=False)
            if _doc.get("listings"):
                own_sc = _sc_payload(_doc["listings"], _doc["digest"], _doc.get("currency"), True,
                                     market=_doc.get("market"),
                                     market_epoch=(_mk_ep() if _mk_en() else None))
    except Exception as e:
        logger.warning(f"[RegistryCardsFanout] own stock card build failed (non-fatal): {e}")

    # 1. Our OWN card — fresh from the builder so it reflects current state
    #    (capabilities, software_version, supply audit, etc.). Cheap — the
    #    builder caches sub-components for 10s.
    try:
        own_card = await build_registry_card(db=db)
        own_identity = own_card.get("identity") or {}
        out.append(RegistryCardSyncData(
            peer_name=own_identity.get("registry_name") or "self",
            base_url=own_identity.get("public_url") or "",
            trust_domain=own_identity.get("trust_domain"),
            card=own_card,
            card_etag=(own_card.get("lifecycle") or {}).get("card_etag"),
            card_signature_verified=True,
            card_signature_kid=(own_card.get("signature") or {}).get("kid"),
            card_last_pulled_at=datetime.now(timezone.utc),
            stock_card=own_sc,
        ))
    except Exception as e:
        logger.warning(f"[RegistryCardsFanout] own card build failed (non-fatal): {e}")

    # 2. Every cached peer card we know about (status='ACTIVE').
    peers = (await db.execute(
        _sel(models.PeerRegistry).where(
            models.PeerRegistry.status == "ACTIVE",
            models.PeerRegistry.cached_registry_card.is_not(None),
        )
    )).scalars().all()

    for p in peers:
        if not isinstance(p.cached_registry_card, dict):
            continue
        # Don't echo back the requesting peer's OWN card to itself — they
        # always have a fresher local copy.
        peer_id_in_card = (p.cached_registry_card.get("identity") or {}).get("spiffe_id")
        if peer_id_in_card and peer_id_in_card == spiffe_id:
            continue
        out.append(RegistryCardSyncData(
            peer_name=p.name,
            base_url=p.base_url,
            trust_domain=p.trust_domain,
            card=p.cached_registry_card,
            card_etag=p.card_etag,
            card_signature_verified=bool(getattr(p, "card_signature_verified", False)),
            card_signature_kid=getattr(p, "card_signature_kid", None),
            card_last_pulled_at=p.card_last_pulled_at,
            stock_card=fsc_by_spiffe.get(peer_id_in_card),
        ))

    logger.info(
        f"[RegistryCardsFanout] peer={spiffe_id} requesting fleet registry "
        f"cards → returned {len(out)} (self + {len(out)-1} peer-cached)"
    )
    return out


@router.post("/sync-request", response_model=FederationSyncResponse)
async def receive_sync_request(
    sync_request: FederationSyncRequest,
    db: AsyncSession = Depends(get_db),  # P1-002: Fixed Session → AsyncSession
    spiffe_id: str = Depends(require_peer_registry_identity)
) -> FederationSyncResponse:
    """Receive and process agent cards from a federation peer.
    
    Allows a trusted peer registry to push its updated agent cards.
    Intelligently merges with existing data.
    
    Requires: Valid peer registry SPIFFE SVID
    """
    logger.info(f"Received sync request from {spiffe_id} with {len(sync_request.agent_cards)} cards")
    
    # Verify source_registry matches authenticated SPIFFE ID (anti-spoofing)
    if sync_request.source_registry != spiffe_id:
        logger.error(f"Source registry mismatch: claimed {sync_request.source_registry}, authenticated as {spiffe_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Source registry does not match authenticated identity"
        )
    
    cards_created = 0
    cards_updated = 0
    
    try:
        # P1-001: Use async ORM instead of db.query()
        peer_name = spiffe_id.split("/registry-")[-1].replace("-", " ").title()
        stmt = select(models.PeerRegistry).where(
            models.PeerRegistry.name == peer_name,
            models.PeerRegistry.status == "ACTIVE"
        )
        result = await db.execute(stmt)
        peer = result.scalar_one_or_none()
        
        if peer:
            peer.last_synced_at = datetime.now(timezone.utc)

        # §ECHO (2026-09-28) — the PUSH path takes the pull's rule (background_tasks.federation_sync._process_peer_cards):
        # a RELAYED copy of a card whose origin we pull from directly is not ingested, and the origin's own copy
        # replaces ours whenever it differs. The presenter is named by its peer ROW, matched on the authenticated
        # SPIFFE id (the legacy name above rarely matches a current identity); a presenter we cannot name makes every
        # copy of a direct origin a relay, which the pull still delivers. A failure to read our peers keeps the
        # pre-§ECHO behaviour for this push.
        from ..background_tasks.federation_sync import (
            direct_source_names, is_origin_copy, presenter_svid_for, relayed_copy_of_direct_origin,
        )
        _direct, _presenter = set(), ""
        try:
            from ..services.spiffe_canonical import canonical_equals as _canon_eq
            _peers_all = await crud_peer_registry.list_active_peer_registries_all(db, skip=0, limit=1000)
            _direct = direct_source_names(_peers_all)
            _presenter = (peer.name if peer else next(
                (p.name for p in _peers_all if _canon_eq(presenter_svid_for(p), spiffe_id)), "")) or ""
        except Exception as _dexc:  # noqa: BLE001
            logger.warning("[FederationSync] push from %s: could not read our direct sources (%s); ingesting as before",
                           spiffe_id, _dexc)
        cards_relay_ignored = 0

        # Process each card using async CRUD
        for card_data in sync_request.agent_cards:
            _card = card_data.model_dump()
            if relayed_copy_of_direct_origin(_card, _presenter, _direct):
                cards_relay_ignored += 1
                continue
            result = await crud_peer_registry.upsert_agent_cards_from_peer(
                db=db,
                peer_svid=spiffe_id,
                agent_card=_card,
                from_origin=is_origin_copy(_card, _presenter),
            )

            if result == "created":
                cards_created += 1
            elif result == "updated":
                cards_updated += 1
        if cards_relay_ignored:
            logger.info("[FederationSync] push from %s: %d relayed copies of a direct origin ignored",
                        spiffe_id, cards_relay_ignored)
        
        # P1-001: Use async commit
        await db.commit()
        
        response = FederationSyncResponse(
            status="success",
            cards_received=len(sync_request.agent_cards),
            cards_updated=cards_updated,
            cards_created=cards_created,
            sync_timestamp=datetime.now(timezone.utc)
        )
        
        logger.info(f"Sync from {spiffe_id} completed: {cards_created} created, {cards_updated} updated")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing sync request from {spiffe_id}: {e}", exc_info=True)
        # P1-001: Use async rollback
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process sync request"
        )


@router.get("/sync-status")
async def get_sync_status(
    db: AsyncSession = Depends(get_db),  # P1-002: Fixed Session → AsyncSession
    spiffe_id: str = Depends(require_peer_registry_identity)
) -> Dict[str, Any]:
    """Get synchronization status information.
    
    Returns information about the federation sync status, including
    last sync times with peers and any pending syncs.
    
    Requires: Valid peer registry SPIFFE SVID
    """
    # Use async CRUD function
    peers = await crud_peer_registry.list_active_peer_registries(db, skip=0, limit=1000)
    
    peer_status = []
    for peer in peers:
        peer_status.append({
            "peer_name": peer.name,
            "peer_url": peer.base_url,
            "last_synced_at": peer.last_synced_at,
            "health_check_status": "healthy" if (peer.health_check_failure_count or 0) == 0 else "unhealthy",
            "health_check_failures": peer.health_check_failure_count or 0
        })
    
    return {
        "federation_enabled": True,
        "our_registry": svid_client.get_spiffe_id() or "unknown",
        "total_peers": len(peers),
        "healthy_peers": sum(1 for p in peers if (p.health_check_failure_count or 0) == 0),
        "peer_status": peer_status,
        "last_check": datetime.now(timezone.utc)
    }


# ═══════════════════════════════════════════════════════════════════════
# Manual Sync Trigger — decentralized, admin-initiated, optional cascade
# ═══════════════════════════════════════════════════════════════════════

_last_trigger_ts: float = 0

_ADMIN_FEDERATION_GATE = security.require_admin_flag("admin_federation")

SYNC_TRIGGER_AUTH_REQUIRED = (
    "Federation authentication required (an mTLS peer certificate, the internal lane from inside this "
    "host, or an admin developer token)"
)


async def require_sync_trigger_identity(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> str:
    """§RELEASEHARDEN D1 (2026-09-14) — who may trigger a sync cycle.

    Until V0367 this route declared no dependency at all: anyone who could reach it ran a full sync
    against every active peer and, with `cascade: true`, made this registry dial every peer's trigger
    with its internal secret. Every other route in this file depends on `require_peer_registry_identity`.

    Tried in order. The federation LICENCE (mode 3 of `get_federation_identity`) is never read: a licence
    authenticates a peer's ledger writes and relays, it does not start sync cycles (agentvault2-85's
    condition for §SOVKIT: fix toward SVID or the internal lane, never toward licence acceptance).
      1. an mTLS peer certificate, narrowed exactly as the other routes narrow it (identity class, the
         operator licence ratchet, the ACTIVE peer-row bind) by handing the identity `get_client_spiffe_id`
         verified to `require_peer_registry_identity`. Named, not fixed: an `X-SSL-Client-Cert` HEADER
         proves no key possession, so this mode is as sound as every path to the port overwriting that
         header (the class §SOVKIT S1 closes on the event store); the blast radius here is one sync cycle;
      2. the internal lane: X-Federation-Secret + X-Federation-SPIFFE-ID from INSIDE this host, compared in
         constant time, the trust domain checked, then the same peer narrowing;
      3. an admin developer through the standard gate `require_admin_flag("admin_federation")`, where the
         OPA shadow and the §MCPSCOPE API-key scope check live (a bare is_admin check would let a narrowed
         avreg_ key through). A developer without the flag is refused 403.
    Returns the identity the caller acted as (a SPIFFE id, or `developer:<id>`).
    """
    # 1. mTLS
    try:
        spiffe_id = await get_client_spiffe_id(request)
    except HTTPException:
        spiffe_id = None
    if spiffe_id:
        return await require_peer_registry_identity(spiffe_id=spiffe_id)

    # 2. the internal lane
    fed_secret = request.headers.get("X-Federation-Secret")
    fed_spiffe_id = request.headers.get("X-Federation-SPIFFE-ID")
    if fed_secret and fed_spiffe_id:
        if not is_internal_request(request):
            logger.warning("[SyncTrigger] X-Federation-Secret presented by a NON-INTERNAL caller — refused")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="the internal-secret rail is not reachable from outside this host",
            )
        if not FEDERATION_INTERNAL_SECRET or not _secrets.compare_digest(fed_secret, FEDERATION_INTERNAL_SECRET):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid federation secret")
        if not any(fed_spiffe_id.startswith(f"spiffe://{d}/") for d in TRUSTED_SPIFFE_DOMAINS):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Federation identity from untrusted domain")
        return await require_peer_registry_identity(spiffe_id=fed_spiffe_id)

    # 3. an admin developer, through the standard gate
    if authorization:
        token = await security.oauth2_scheme_required(request)
        developer_id = await security.verify_access_token_required(request, token=token, db=db)
        developer = await security.get_current_developer(db=db, developer_id=developer_id)
        admin = await _ADMIN_FEDERATION_GATE(current_developer=developer)
        return f"developer:{admin.id}"

    logger.warning("[SyncTrigger] refused: no mTLS peer certificate, no internal lane, no developer token")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SYNC_TRIGGER_AUTH_REQUIRED)


@router.post("/sync/trigger")
async def trigger_sync(
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    identity: str = Depends(require_sync_trigger_identity),
):
    """Trigger immediate federation sync.

    Accepts an admin developer JWT (the console, Galactic Command, the MCP tool for an admin) or a peer
    registry's mTLS / internal-lane identity (a cascade from a peer). Never a federation licence.
    Body: {"cascade": false, "peer_name": null}
    Rate limited: 1 per 30 seconds.
    """
    logger.info(f"[SyncTrigger] triggered by {identity}")

    global _last_trigger_ts
    now = _time.time()
    if now - _last_trigger_ts < 30:
        raise HTTPException(429, f"Rate limited. Try again in {30 - int(now - _last_trigger_ts)}s")
    _last_trigger_ts = now

    cascade = body.get("cascade", False)
    peer_name = body.get("peer_name")

    # Run sync cycle
    from ..background_tasks.federation_sync import FederationSyncWorker
    worker = FederationSyncWorker()

    our_spiffe = svid_client.get_spiffe_id()
    if not our_spiffe:
        raise HTTPException(503, "SPIFFE identity not available")

    # §pass78c (2026-06-06): mirror _sync_cycle (background_tasks/federation_sync.py)
    # — use the *_all variant so the manual trigger ALSO pulls parented
    # cloud_operator children + 'discovered' peers (the peer-to-peer relay chain).
    # The filtered list silently skipped a frame's hop-depth ME-op children
    # (e.g. frame-c → op-doha), so a manual trigger could never repair the chain.
    active_peers = await crud_peer_registry.list_active_peer_registries_all(db, skip=0, limit=1000)

    if peer_name:
        active_peers = [p for p in active_peers if peer_name.lower() in p.name.lower()]

    if not active_peers:
        return {"status": "no_peers", "synced": 0, "cascade_sent": 0}

    # Sync with each peer
    import asyncio
    tasks = [worker._sync_with_peer(p, our_spiffe) for p in active_peers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    success = sum(1 for r in results if r is True)

    logger.info(f"[SyncTrigger] Manual sync: {success}/{len(active_peers)} peers synced")

    # Cascade: notify peers to also sync (depth-1, non-blocking)
    cascade_sent = 0
    if cascade:
        import httpx as _httpx
        for peer in active_peers:
            try:
                # Build mTLS or internal-secret headers for the peer
                base = peer.base_url.rstrip('/')

                # Use same DNS bypass as federation_helper
                from urllib.parse import urlparse as _up
                from .agent_locations import _needs_dns_bypass, _get_host_public_ip
                parsed = _up(base)
                cascade_url = f"{base}/api/v1/federation/sync/trigger"

                if parsed.hostname and _needs_dns_bypass(parsed.hostname):
                    host_ip = _get_host_public_ip()
                    if host_ip:
                        cascade_url = f"https://{host_ip}/api/v1/federation/sync/trigger"
                        headers = {"Host": parsed.hostname}
                    else:
                        headers = {}
                else:
                    headers = {}

                # Add federation auth
                fed_secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
                if fed_secret:
                    headers["X-Federation-Secret"] = fed_secret
                    headers["X-Federation-SPIFFE-ID"] = our_spiffe

                async with _httpx.AsyncClient(timeout=10, verify=False) as client:
                    r = await client.post(cascade_url, json={"cascade": False},
                                          headers=headers)
                    if r.status_code in (200, 201, 429):
                        cascade_sent += 1
                        logger.info(f"[SyncTrigger] Cascade → {peer.name}: {r.status_code}")
            except Exception as e:
                logger.warning(f"[SyncTrigger] Cascade → {peer.name} failed: {e}")

    return {
        "status": "completed",
        "synced_peers": success,
        "total_peers": len(active_peers),
        "cascade_sent": cascade_sent,
        "cascade_requested": cascade,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# §FXSELFHEAL (2026-08-10) — remote parked-route recovery, ORIGIN side.
#
# A `post_conversion_remote` dead-letter row lives HERE (the origin frame) while the
# converted funds sit at the DESTINATION frame's @fx_router. The origin genuinely cannot
# refund them (fx_router_keeper phase-guards those rows); recovery is re-delivery ON the
# frame holding the funds. These three peer-authenticated endpoints let that frame's
# fx_router_keeper pull its own workload and drive the row through an explicit
# claim-before-sweep CAS:
#
#     pending ──claim──▶ sweeping ──resolve(swept)──▶ swept
#                          │
#                          └──resolve(released)──▶ pending   (retry next cycle)
#
# The CAS is the ONLY double-pay guard — the sweep rail has no per-route idempotency —
# and it interlocks with the manual runbook in both directions (the runbook's work list
# is status='pending' and its mark is CAS'd on 'pending'). A row stuck in 'sweeping'
# (claimer crashed between sweep and resolve) is NEVER auto-released: releasing it after
# a successful sweep would double-pay. It surfaces via /fx/parked-stats for manual
# count-reconciliation (the 2026-08-10 §FXRECOVER procedure).
#
# Gate: FX_REMOTE_RECOVERY_MODE in ('endpoints','on') — default 'off' ⇒ byte-inert 404,
# exactly like a pre-§FXSELFHEAL node, which is also what the keeper's fail-open client
# expects from an old peer.
# ═══════════════════════════════════════════════════════════════════════════════

def _fx_remote_recovery_endpoints_enabled() -> bool:
    return (os.getenv("FX_REMOTE_RECOVERY_MODE", "off") or "off").strip().lower() in ("endpoints", "on")


def _fxsh_require_enabled() -> None:
    if not _fx_remote_recovery_endpoints_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="FX remote recovery endpoints disabled on this registry")


async def _fxsh_validate_router(db: AsyncSession, spiffe_id: str, router_did: str,
                                currency: Optional[str] = None) -> None:
    """The caller may only touch rows parked at a router THIS frame's own gateway directory
    attributes to the caller's frame. Defense in depth on top of peer auth: a different
    (authenticated) peer claiming someone else's rows could at worst park them in
    'sweeping' (denial-of-recovery, surfaced by parked-stats) — never move money — but we
    refuse it outright when the directory lets us."""
    from .teg_integration import _fx_route_peer_gateways, _fx_route_find_active_peer
    gateways = [g for g in _fx_route_peer_gateways()
                if str(g.get("router_did", "")).strip() == (router_did or "").strip()]
    if not gateways:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"router_did {router_did} is not a configured peer gateway here")
    if currency:
        if not any(str(g.get("currency", "")).strip().upper() == currency.strip().upper()
                   for g in gateways):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="router/currency mismatch against gateway directory")
    # Best-effort trust-domain bind: gateway registry_id → ACTIVE peer row → trust_domain
    # must appear in the presented SPIFFE id. Legacy rows without trust_domain only log.
    try:
        reg_id = str(gateways[0].get("registry_id", "")).strip()
        peer = await _fx_route_find_active_peer(db, reg_id) if reg_id else None
        td = (getattr(peer, "trust_domain", None) or "").strip() if peer else ""
        if td and td not in (spiffe_id or ""):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="caller identity does not match the gateway's trust domain")
        if not td:
            logger.info(f"[fxselfheal] no trust_domain bind for gateway {reg_id} "
                        f"(peer row missing/unstamped) — proceeding on peer auth + directory match")
    except HTTPException:
        raise
    except Exception as _e:  # noqa: BLE001 — bind is best-effort, never a crash path
        logger.warning(f"[fxselfheal] trust-domain bind check errored (proceeding): {_e}")


@router.get("/fx/ledger", summary="Internal: can this frame's ledger record a movement now (federation-authed)")
async def fx_ledger_state_federated(_peer_identity: str = Depends(require_peer_registry_identity)):
    """
    Internal and read-only: this frame's TEG ledger gate as its /health reports it, for a peer frame about to
    convert into this frame's unit, on the federation channel every proxy forwards. Auth: a validated peer registry
    SVID (mTLS).

    \f
    §LEDGERGATE (V0603): this frame's TEG ledger gate as its /health reports it, for a peer frame about to convert into
    this frame's currency (routers/teg_integration._fx_route_gd_ledger_refusal). V0602 served it at /api/v1/teg/fx/ledger,
    a path no frame's federation proxy forwards: every peer read answered 404 at the edge and the check went ahead,
    measured in drill 3 (2026-10-12: four routes into sbx-alpha converted and parked during a 107 s store outage). Under
    /api/v1/federation/ it rides the channel every proxy forwards. Read-only.
    """
    from .teg_integration import _fx_local_ledger_state
    return await _fx_local_ledger_state()


@router.get("/fx/parked-at")
async def fx_parked_at(
    router_did: str = Query(..., description="The CALLER's @fx_router DID"),
    min_age_sec: int = Query(900, ge=300, le=86400),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """List pending post_conversion_remote rows whose funds sit at the caller's router.
    min_age_sec floors at 300 s: the photo-finish class (egress COMPLETED seconds after
    the dead-letter write, 2 live cases found 2026-08-10) must age out before recovery."""
    _fxsh_require_enabled()
    await _fxsh_validate_router(db, spiffe_id, router_did)
    from sqlalchemy import text as _text
    rows = (await db.execute(_text(
        """
        SELECT route_id, receiver_did, amount, currency, created_at, origin_did
          FROM fx_route_dead_letters
         WHERE status = 'pending'
           AND phase = 'post_conversion_remote'
           AND parked_at_did = :router
           AND receiver_did IS NOT NULL
           AND created_at < now() - make_interval(secs => :age)
         ORDER BY created_at ASC
         LIMIT :lim
        """), {"router": router_did, "age": min_age_sec, "lim": limit})).mappings().all()
    return {
        "router_did": router_did,
        "rows": [
            {"route_id": r["route_id"], "receiver_did": r["receiver_did"],
             "amount": str(r["amount"]), "currency": r["currency"], "origin_did": r["origin_did"],
             "created_at": r["created_at"].isoformat() if r["created_at"] else None}
            for r in rows
        ],
    }


class FxParkedClaimBody(BaseModel):
    route_id: str = Field(min_length=8, max_length=64)
    router_did: str = Field(min_length=8, max_length=120)


@router.post("/fx/parked-claim")
async def fx_parked_claim(
    body: FxParkedClaimBody,
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """CAS pending → sweeping. 409 when the row is not claimable (already claimed, already
    resolved, wrong router, or too young); the caller simply skips it."""
    _fxsh_require_enabled()
    await _fxsh_validate_router(db, spiffe_id, body.router_did)
    from sqlalchemy import text as _text
    res = await db.execute(_text(
        """
        UPDATE fx_route_dead_letters
           SET status = 'sweeping', claimed_by = :who, claimed_at = now()
         WHERE route_id = :rid AND status = 'pending'
           AND phase = 'post_conversion_remote'
           AND parked_at_did = :router
           AND receiver_did IS NOT NULL
           AND created_at < now() - interval '300 seconds'
        RETURNING route_id, receiver_did, amount, currency
        """), {"who": (spiffe_id or "peer")[:200], "rid": body.route_id,
               "router": body.router_did})
    row = res.mappings().first()
    if row is None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="row not claimable (not pending / wrong router / too young)")
    await db.commit()
    logger.info(f"[fxselfheal] CLAIMED route={body.route_id} by {spiffe_id}")
    return {"claimed": True, "route_id": row["route_id"], "receiver_did": row["receiver_did"],
            "amount": str(row["amount"]), "currency": row["currency"]}


class FxParkedResolveBody(BaseModel):
    route_id: str = Field(min_length=8, max_length=64)
    router_did: str = Field(min_length=8, max_length=120)
    outcome: str = Field(pattern="^(swept|delivered|released)$")
    resolution_tx: Optional[str] = Field(default=None, max_length=120)
    error: Optional[str] = Field(default=None, max_length=480)


@router.post("/fx/parked-resolve")
async def fx_parked_resolve(
    body: FxParkedResolveBody,
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """CAS sweeping → swept (the keeper delivered it now) | delivered (the keeper found the
    route had ALREADY been delivered from the destination frame: the ambiguous-2PC class, no
    units moved) | released (retry next cycle; retries+1, last_error recorded). Only from
    'sweeping'. 'swept' and 'delivered' both require resolution_tx so every terminal row names
    the transaction that paid the receiver."""
    _fxsh_require_enabled()
    await _fxsh_validate_router(db, spiffe_id, body.router_did)
    from sqlalchemy import text as _text
    if body.outcome in ("swept", "delivered"):
        if not (body.resolution_tx or "").strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"resolution_tx required for outcome={body.outcome}")
        res = await db.execute(_text(
            """
            UPDATE fx_route_dead_letters
               SET status = :st, resolution_tx = :tx, resolved_at = now(), last_error = NULL
             WHERE route_id = :rid AND status = 'sweeping' AND parked_at_did = :router
            RETURNING route_id
            """), {"st": body.outcome, "tx": body.resolution_tx, "rid": body.route_id,
                   "router": body.router_did})
    else:
        res = await db.execute(_text(
            """
            UPDATE fx_route_dead_letters
               SET status = 'pending', claimed_by = NULL, claimed_at = NULL,
                   retries = COALESCE(retries, 0) + 1, last_error = :err
             WHERE route_id = :rid AND status = 'sweeping' AND parked_at_did = :router
            RETURNING route_id
            """), {"err": (body.error or "released by claimer")[:480],
                   "rid": body.route_id, "router": body.router_did})
    row = res.first()
    if row is None:
        await db.rollback()
        # Idempotency courtesy: resolving an already-terminal row with the SAME tx is a repeat
        # of a delivered outcome, not a conflict — the claimer may be retrying a lost ack.
        if body.outcome in ("swept", "delivered"):
            from sqlalchemy import text as _t2
            prior = (await db.execute(_t2(
                "SELECT resolution_tx FROM fx_route_dead_letters WHERE route_id = :rid "
                "AND status IN ('swept','delivered')"),
                {"rid": body.route_id})).scalar_one_or_none()
            if prior and prior == body.resolution_tx:
                return {"resolved": True, "route_id": body.route_id, "already": True}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="row not in 'sweeping' (not claimed, or resolved by someone else)")
    await db.commit()
    logger.info(f"[fxselfheal] RESOLVED route={body.route_id} outcome={body.outcome} by {spiffe_id}")
    return {"resolved": True, "route_id": body.route_id, "outcome": body.outcome}


@router.get("/fx/parked-stats")
async def fx_parked_stats(
    db: AsyncSession = Depends(get_db),
    spiffe_id: str = Depends(require_peer_registry_identity),
):
    """Origin-side reconciliation surface: status counts + stale 'sweeping' claims (>1h) that
    need MANUAL count-reconciliation (never auto-released)."""
    _fxsh_require_enabled()
    from sqlalchemy import text as _text
    counts = (await db.execute(_text(
        "SELECT status, count(*) AS n FROM fx_route_dead_letters GROUP BY status"))).mappings().all()
    stale = (await db.execute(_text(
        """
        SELECT route_id, claimed_by, claimed_at, amount, currency
          FROM fx_route_dead_letters
         WHERE status = 'sweeping' AND claimed_at < now() - interval '1 hour'
         ORDER BY claimed_at ASC LIMIT 20
        """))).mappings().all()
    return {
        "counts": {r["status"]: r["n"] for r in counts},
        "stale_sweeping": [
            {"route_id": r["route_id"], "claimed_by": r["claimed_by"],
             "claimed_at": r["claimed_at"].isoformat() if r["claimed_at"] else None,
             "amount": str(r["amount"]), "currency": r["currency"]}
            for r in stale
        ],
    }
