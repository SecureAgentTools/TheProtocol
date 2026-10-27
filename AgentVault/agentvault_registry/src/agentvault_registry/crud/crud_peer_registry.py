"""CRUD operations for PeerRegistry model."""
import logging
import re
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, select, func, text
from sqlalchemy.orm import joinedload

from .. import models, schemas

logger = logging.getLogger(__name__)

# D6-814 (2026-10-23): a card the fail-closed ingest refuses says which fields failed, and the refusals are countable.
# ASIA refused EU's SYBIL card every 30 s from 2026-09-28 to 2026-10-23 (its provider.url was ""): the log line cut
# pydantic's text at 200 characters, which held the first error and its input value (the card's own content) and never
# reached the field, so the mirror stood still for 25 days and nothing said why. The line now names each error's schema
# path, type and message, never the input; the counter is per peer and first failing field (list indices read *).
try:
    from prometheus_client import Counter as _IngestCounter
    FEDERATION_CARD_INGEST_REFUSED_TOTAL = _IngestCounter(
        "federation_card_ingest_refused_total",
        "Federated agent card updates the fail-closed ingest refused as schema-invalid, by peer and first failing field",
        labelnames=["peer", "field"],
    )
    # D6-814, the second half: ASIA skipped four NEWER copies of EU's cards (their provider fixed at the home) as
    # "0 updated, N skipped", no line anywhere, until a drift refresh by hand. A copy the ingest does not write now says
    # why: unchanged (the quiet mesh), not_newer (neither from the card's home nor newer than ours, nor a new field),
    # native_echo / native_blocked (our own card relayed back), invalid_id, tombstone_insert_refused.
    FEDERATION_CARD_INGEST_SKIPPED_TOTAL = _IngestCounter(
        "federation_card_ingest_skipped_total",
        "Federated agent card copies the ingest did not write, by peer and reason",
        labelnames=["peer", "reason"],
    )
except Exception:  # pragma: no cover  (no prometheus_client, or the name already registered)
    FEDERATION_CARD_INGEST_REFUSED_TOTAL = None
    FEDERATION_CARD_INGEST_SKIPPED_TOTAL = None

_SKIP_NAMED: set = set()   # (card, reason) pairs this worker has already named in the log; capped below


def note_ingest_skip(card_uuid, peer_svid, reason: str, detail: str = "") -> None:
    """Count a copy the ingest did not write, by peer and reason; a not_newer one is also named in the log, once per
    card and worker (the silent class: a newer copy that is not recognised as the home's own and carries an older clock)."""
    if FEDERATION_CARD_INGEST_SKIPPED_TOTAL is not None:
        try:
            FEDERATION_CARD_INGEST_SKIPPED_TOTAL.labels(peer=str(peer_svid)[:120], reason=reason).inc()
        except Exception:  # a metrics failure never decides an ingest
            pass
    if reason == "not_newer":
        key = (str(card_uuid), reason)
        if key not in _SKIP_NAMED and len(_SKIP_NAMED) < 20000:
            _SKIP_NAMED.add(key)
            logger.info("federated agent card %s from %s not written: %s (%s)", card_uuid, peer_svid, reason, detail)


def schema_refusal_fields(exc) -> List[tuple]:
    """(path, type, message) for each error of a refused card: the schema path with list indices as '*' (a bounded
    label), pydantic's error type and message; never the input value, which is the peer's untrusted content. An error
    at the card's root reads '(card)'; an exception that is not a validation error reads ('(card)', its class, '')."""
    out = []
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            for e in errors():
                loc = ".".join("*" if isinstance(p, int) else str(p) for p in (e.get("loc") or ())) or "(card)"
                out.append((loc[:80], str(e.get("type", ""))[:40], str(e.get("msg", ""))[:160]))
        except Exception:
            out = []
    return out or [("(card)", type(exc).__name__, "")]


# RCA 2026-07-10 (federation-peer ratchet): deactivation reasons the revival
# prober must NEVER auto-revive — deliberate human/lifecycle decisions.
# NULL/unknown or anything outside this set (e.g. sync_failure, probe_test)
# is considered transient and revivable after a verified identity probe.
PEER_DEACTIVATION_GUARD_REASONS = frozenset({
    "admin_deactivated", "owner_deactivated",
    "operator_revoked", "license_suspended", "license_revoked",
    "federation_revoked", "frame_revoked",
    "self_echo", "duplicate_frame", "rename_debris", "teardown",
})


async def create_peer_registry_request(
    db: AsyncSession,
    owner_id: int,
    peer_data: schemas.PeerRegistryCreate
) -> models.PeerRegistry:
    """Create a new peer registry registration request.
    
    Args:
        db: Database session
        owner_id: ID of the developer creating the request
        peer_data: Peer registry creation data
        
    Returns:
        Created PeerRegistry instance
        
    Raises:
        IntegrityError: If name or base_url already exists
    """
    try:
        db_peer = models.PeerRegistry(
            owner_developer_id=owner_id,
            name=peer_data.name,
            description=peer_data.description,
            base_url=peer_data.base_url,
            admin_contact_email=peer_data.admin_contact_email,
            discovery_auth_info=peer_data.discovery_auth_info.model_dump() if hasattr(peer_data.discovery_auth_info, 'model_dump') else dict(peer_data.discovery_auth_info),
            status="PENDING_APPROVAL"
        )
        db.add(db_peer)
        await db.commit()
        await db.refresh(db_peer)
        return db_peer
    except IntegrityError as e:
        await db.rollback()
        if "name" in str(e.orig):
            raise ValueError(f"Peer registry with name '{peer_data.name}' already exists")
        elif "base_url" in str(e.orig):
            raise ValueError(f"Peer registry with base URL '{peer_data.base_url}' already exists")
        else:
            raise


async def get_peer_registry_by_id(db: AsyncSession, peer_id: int) -> Optional[models.PeerRegistry]:
    """Get a peer registry by its ID.
    
    Args:
        db: Database session
        peer_id: ID of the peer registry
        
    Returns:
        PeerRegistry instance or None if not found
    """
    stmt = select(models.PeerRegistry).filter(models.PeerRegistry.id == peer_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_peer_registries_by_status(
    db: AsyncSession,
    status: str,
    skip: int = 0,
    limit: int = 100
) -> List[models.PeerRegistry]:
    """Get peer registries by status with pagination.
    
    Args:
        db: Database session
        status: Status to filter by
        skip: Number of records to skip
        limit: Maximum number of records to return
        
    Returns:
        List of PeerRegistry instances
    """
    stmt = select(models.PeerRegistry).filter(
        models.PeerRegistry.status == status
    ).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_active_peer_registries_all(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 1000,
) -> List[models.PeerRegistry]:
    """List ALL active peer registries — no direct-vs-chain filter.

    Used by Registry Card v0.3 sync (§pass60.4). Unlike `list_active_peer_registries`,
    which excludes chain-discovered peers to keep agent-card federation single-hop,
    RC sync iterates every active peer regardless of `parent_registry_id` because
    registry cards are cosmetic identity docs — pulling a chain-discovered peer's
    self-described card has no echo / BFS-edge / cross-publishing risk.
    """
    stmt = select(models.PeerRegistry).filter(
        models.PeerRegistry.status == "ACTIVE",
        models.PeerRegistry.peer_type.in_(("frame", "direct_peer", "cloud_operator", "discovered")),
    ).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_active_peer_registries(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100
) -> List[models.PeerRegistry]:
    """List active peer registries with pagination.

    2026-05-05 audit T8: filter out chain-child entries (parent_registry_id
    IS NOT NULL). The public /federation/peers/ endpoint advertises only
    this registry's DIRECTLY peered registries, NOT chain-discovered
    transitive ones. Cross-publishing chain children (e.g. Frame-B publishing
    op-seoul which is reached via op-tokyo chain) creates competing BFS
    edges — Frame-B → op-seoul vs op-tokyo → op-seoul — and breaks
    parent_registry_id determinism on remote crawlers. Each registry's
    chain children are discovered transitively by crawling its direct peers.

    Filter logic:
      - peer_type='discovered' → never published (purely BFS-derived)
      - peer_type='frame' / 'direct_peer' / 'cloud_operator' WITH parent=null
        → published (truly direct relationships)
      - peer_type='cloud_operator' WITH parent != null → not published
        (chain child of another peer)
    """
    stmt = select(models.PeerRegistry).filter(*_published_peer_conditions()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


def _published_peer_conditions() -> tuple:
    """The peers the public /federation/peers/ listing publishes (see list_active_peer_registries), for the list and its
    count alike."""
    return (
        models.PeerRegistry.status == "ACTIVE",
        models.PeerRegistry.peer_type.in_(("frame", "direct_peer", "cloud_operator")),
        models.PeerRegistry.parent_registry_id.is_(None),
    )


def _partner_key(name: Optional[str]) -> str:
    """The key the TEG's partner rule names a peer by (teg_core_service core/cross_teg/partner_rule.peer_key) for the
    partner id teg-<safe name>: letters and digits only."""
    from ..services.cloud_provisioner import _safe_name
    return re.sub(r"[^a-z0-9]", "", _safe_name(name or ""))


async def _released_partner_teg_id(db: AsyncSession, db_peer: models.PeerRegistry) -> Optional[str]:
    """The TEG partner a deactivation releases: teg-<safe name>, the id a reactivation and a quarantine lift register
    (reactor_helpers.register_peer_partner_on_teg), so the PeerRegistryDeactivated reactor removes what they added.

    None when the name keys no partner, or when another ACTIVE row names the same partner (the peer under a second
    spelling, e.g. a fan-out's upper-case copy of a frame): the TEG's remove-partner drops every entry naming the key,
    so removing it then would cut a peer this frame still trusts."""
    from ..services.cloud_provisioner import _safe_name
    key = _partner_key(db_peer.name)
    if not key:
        return None
    rows = (await db.execute(
        select(models.PeerRegistry.id, models.PeerRegistry.name)
        .where(models.PeerRegistry.status == "ACTIVE", models.PeerRegistry.id != db_peer.id)
    )).all()
    holders = [f"{rid}:{name}" for rid, name in rows if _partner_key(name) == key]
    if holders:
        logger.info(
            "[peer-status] peer=%s deactivated; its TEG partner teg-%s stays: ACTIVE row(s) %s name the same partner",
            db_peer.id, _safe_name(db_peer.name or ""), ", ".join(holders),
        )
        return None
    return f"teg-{_safe_name(db_peer.name or '')}"


async def update_peer_registry_status(
    db: AsyncSession,
    db_peer: models.PeerRegistry,
    new_status: str,
    admin_id: Optional[int] = None,
    reason: Optional[str] = None,
    emit: bool = True,
) -> models.PeerRegistry:
    """Update the status of a peer registry.

    RCA 2026-07-10 (federation-peer ratchet): this is the single choke point for
    peer status transitions — it stamps `deactivated_reason`/`deactivated_at` on
    INACTIVE, clears them on ACTIVE, and emits PeerRegistryDeactivated /
    PeerRegistryReactivated so a flip is never silent again.

    Args:
        db: Database session
        db_peer: PeerRegistry instance to update
        new_status: New status value
        admin_id: ID of the admin approving/rejecting (if applicable)
        reason: why (deactivations default to admin/owner_deactivated;
                the revival prober passes 'auto_revival' on reactivation)
        emit: set False to suppress the audit event (bulk/startup paths)

    Returns:
        Updated PeerRegistry instance
    """
    prior_status = (db_peer.status or "").upper()
    now = datetime.now(timezone.utc)
    db_peer.status = new_status

    if new_status == "ACTIVE" and admin_id is not None:
        db_peer.approved_at = now
        db_peer.approved_by_developer_id = admin_id

    if new_status == "INACTIVE":
        db_peer.deactivated_reason = reason or (
            "admin_deactivated" if admin_id is not None else "owner_deactivated"
        )
        db_peer.deactivated_at = now
    elif new_status == "ACTIVE":
        db_peer.deactivated_reason = None
        db_peer.deactivated_at = None

    await db.commit()
    await db.refresh(db_peer)

    # Observability (R3): emit on real INACTIVE/ACTIVE transitions. Reactivated
    # only fires for a genuine revival (prior INACTIVE), not first approval.
    # Best-effort — an emit failure must never break the status write.
    if emit and prior_status != new_status:
        event_type = None
        if new_status == "INACTIVE":
            event_type = "PeerRegistryDeactivated"
        elif new_status == "ACTIVE" and prior_status == "INACTIVE":
            event_type = "PeerRegistryReactivated"
        if event_type:
            # The TEG partner rule (ledgergate3): a reactivation registers the peer as a TEG partner, so a deactivation
            # releases it, or a deactivated peer stays a current partner at the TEG (agentvault2-56 measured it on
            # sbx-alpha 2026-10-18: the V0624 sweep's reactivate row added a fixture's partner at 21:04:22Z and the
            # deactivation at 21:08:51Z, which emitted no teg_id, removed nothing).
            teg_id = None
            if event_type == "PeerRegistryDeactivated":
                try:
                    teg_id = await _released_partner_teg_id(db, db_peer)
                except Exception as exc:  # noqa: BLE001  the event still goes out; the partner stays, as before
                    logger.warning(
                        "[peer-status] the TEG partner peer=%s releases was not derived (%s): it stays a partner",
                        db_peer.id, exc,
                    )
            try:
                from ..event_emitter import get_event_emitter
                await get_event_emitter().emit(
                    event_type=event_type,
                    aggregate_id=f"peer_registry:{db_peer.id}",
                    aggregate_type="PeerRegistry",
                    data={
                        "peer_id": db_peer.id,
                        "peer_name": db_peer.name,
                        "trust_domain": db_peer.trust_domain,
                        "prior_status": prior_status,
                        "reason": (db_peer.deactivated_reason
                                   if new_status == "INACTIVE"
                                   else (reason or "admin_reactivated")),
                        "actor_developer_id": admin_id,
                        # the TEG partner this deactivation releases (_released_partner_teg_id); None (a
                        # reactivation, or no partner to release) and the PeerRegistryDeactivated reactor skips
                        "teg_id": teg_id,
                    },
                )
            except Exception as exc:  # pragma: no cover — observability only
                logger.warning(
                    "[peer-status] %s emit failed for peer=%s (%s) — status write committed anyway",
                    event_type, db_peer.id, exc,
                )
    return db_peer


async def update_peer_registry_details(
    db: AsyncSession,
    db_peer: models.PeerRegistry,
    update_data: schemas.PeerRegistryUpdate
) -> models.PeerRegistry:
    """Update peer registry details (for owner updates).
    
    Args:
        db: Database session
        db_peer: PeerRegistry instance to update
        update_data: Update data
        
    Returns:
        Updated PeerRegistry instance
    """
    update_dict = update_data.model_dump(exclude_unset=True)
    
    # Handle discovery_auth_info separately if present
    if "discovery_auth_info" in update_dict and update_dict["discovery_auth_info"] is not None:
        auth_info = update_dict["discovery_auth_info"]
        if hasattr(auth_info, 'model_dump'):
            update_dict["discovery_auth_info"] = auth_info.model_dump()
        else:
            update_dict["discovery_auth_info"] = dict(auth_info)
    
    for field, value in update_dict.items():
        setattr(db_peer, field, value)
    
    await db.commit()
    await db.refresh(db_peer)
    return db_peer


async def get_peer_registries_by_owner(
    db: AsyncSession,
    owner_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.PeerRegistry]:
    """Get all peer registries owned by a specific developer.
    
    Args:
        db: Database session
        owner_id: ID of the owner developer
        skip: Number of records to skip
        limit: Maximum number of records to return
        
    Returns:
        List of PeerRegistry instances owned by the developer
    """
    stmt = select(models.PeerRegistry).filter(
        models.PeerRegistry.owner_developer_id == owner_id
    ).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def count_peer_registries_by_status(db: AsyncSession, status: str) -> int:
    """Count peer registries by status.
    
    Args:
        db: Database session
        status: Status to count
        
    Returns:
        Count of peer registries with the given status
    """
    stmt = select(func.count()).select_from(models.PeerRegistry).filter(
        models.PeerRegistry.status == status
    )
    result = await db.execute(stmt)
    return result.scalar()


async def count_active_peer_registries(db: AsyncSession) -> int:
    """Count the active peer registries the public listing publishes (list_active_peer_registries).

    §DOCSFIX D6-109 (2026-10-16): it counted every ACTIVE row, chain children and discovered peers included, so the
    listing's `total_items` (and `total_pages`) exceeded what it would ever list (EU: 3 items, total 5).
    """
    stmt = select(func.count()).select_from(models.PeerRegistry).filter(*_published_peer_conditions())
    result = await db.execute(stmt)
    return result.scalar()


async def update_peer_health_check_status(
    db: AsyncSession,
    peer_id: int,
    success: bool,
    failure_threshold: int = 3
) -> Optional[models.PeerRegistry]:
    """Update peer registry health check status.
    
    Args:
        db: Database session
        peer_id: ID of the peer registry
        success: Whether the health check succeeded
        failure_threshold: Number of failures before marking inactive
        
    Returns:
        Updated PeerRegistry instance or None if not found
    """
    db_peer = await get_peer_registry_by_id(db, peer_id)
    if not db_peer:
        return None
    
    db_peer.last_health_check_attempt_at = datetime.now(timezone.utc)
    
    if success:
        db_peer.health_check_failure_count = 0
        db_peer.last_synced_at = datetime.now(timezone.utc)
        # Reactivate if it was marked inactive due to health checks
        if db_peer.status == "INACTIVE" and db_peer.health_check_failure_count > 0:
            db_peer.status = "ACTIVE"
    else:
        db_peer.health_check_failure_count += 1
        # Mark as inactive if exceeded threshold
        if db_peer.health_check_failure_count >= failure_threshold and db_peer.status == "ACTIVE":
            db_peer.status = "INACTIVE"
    
    await db.commit()
    await db.refresh(db_peer)
    return db_peer


def _has_track_record_ext(card_data) -> bool:
    """Does this card carry the attested track-record extension WITH a summary?

    Deliberately narrow: the extension URI alone is not enough, because an agent's own well-known
    card carries a POINTER-ONLY version of the same extension. Only a card bearing the compact
    summary is new information worth forcing an ingest for.
    """
    try:
        from agentvault_registry.services.track_record import compact_from_card
        return compact_from_card(card_data) is not None
    except Exception:  # noqa: BLE001 — a predicate must never break the ingest
        return False


def _bond_maturity_version(card_data) -> int:
    """§BONDFILL-3 — the SHAPE version of the maturity snapshot a card carries; 0 when it carries none.

    Presence alone was the V0343 clause, and it let a card through only when it GAINED a maturity
    block. When the snapshot changed shape (v1 absolute eigentrust -> v2 relative trust), every
    mirror already HAD a block, so nothing let the new shape in: a shape change inside a field that
    already exists is invisible to a presence check exactly as a new field is to a clock.
    """
    try:
        from agentvault_registry.services.reputation_bond import extension_from_card
        p = extension_from_card(card_data)
        m = p.get("maturity") if isinstance(p, dict) else None
        if not isinstance(m, dict):
            return 0
        return int(m.get("version") or 1)
    except Exception:  # noqa: BLE001 — a predicate must never break the ingest
        return 0


def new_fields_offered(existing_cd: Dict[str, Any], incoming_cd: Dict[str, Any]) -> List[str]:
    """The fields an incoming copy carries that our stored copy lacks: the ONE list of the ingest's "new field" tests.

    A copy that is NOT newer by the clock still gets in when it offers one of these, because each is information a
    clock-only gate cannot see (each clause names the session that added it). Returned as tags so the ingest can take
    exactly these fields and nothing else (`merge_new_fields`, §ECHO).
    """
    existing_cd = existing_cd if isinstance(existing_cd, dict) else {}
    incoming_cd = incoming_cd if isinstance(incoming_cd, dict) else {}
    existing_meta = existing_cd.get('federation_metadata') or {}
    incoming_meta = incoming_cd.get('federation_metadata') or {}
    tags: List[str] = []
    # location and the origin's coordinates (the globe's registry coords)
    if incoming_cd.get('location') and not existing_cd.get('location'):
        tags.append('location')
    for key in ('origin_registry_location', 'spiffe_id', 'mtls_enabled'):
        if incoming_meta.get(key) and not existing_meta.get(key):
            tags.append('meta:' + key)
    # §pass34 (2026-05-17) — flare is monotonically additive. Peers stamp updated_at=NOW on every sync, which breaks
    # strict timestamp ordering for the flare field: an op that pulled a flare-less version through a stale relay has a
    # later clock than the origin's flare-stamped version, so a clock comparison would skip the origin's update.
    if isinstance(incoming_cd.get('flare'), dict) and not isinstance(existing_cd.get('flare'), dict):
        tags.append('flare')
    # §TRAVELREC (2026-09-11) — the work record is DERIVED at export time, so on the day the origin starts attaching
    # it, not one card's `updated_at` moves: a clock-only gate can never let it in (§DIRFEED's law from the ingest
    # side: an incremental reader is blind to a field the READ gained). Let a card that newly carries it through, once.
    if _has_track_record_ext(incoming_cd) and not _has_track_record_ext(existing_cd):
        tags.append('track_record')
    # §BONDFILL (2026-09-11) / §BONDFILL-3 — the bond's maturity snapshot arrives through the SAME blind spot, and a
    # NEWER snapshot SHAPE is new information too (absent -> v1 -> v2), never an older one: strictly greater, so a stale
    # relay carrying v1 can never overwrite a v2 the origin already sent.
    if _bond_maturity_version(incoming_cd) > _bond_maturity_version(existing_cd):
        tags.append('bond_maturity')
    return tags


def _replace_extensions(out: Dict[str, Any], incoming_cd: Dict[str, Any], uri: str) -> None:
    kept = [e for e in (out.get('extensions') or []) if not (isinstance(e, dict) and e.get('uri') == uri)]
    taken = [e for e in (incoming_cd.get('extensions') or []) if isinstance(e, dict) and e.get('uri') == uri]
    out['extensions'] = kept + taken


def merge_new_fields(existing_cd: Dict[str, Any], incoming_cd: Dict[str, Any], tags: List[str]) -> Dict[str, Any]:
    """§ECHO (2026-09-28) — OUR card plus the new fields an older copy offered, and NOTHING ELSE from that copy.

    Measured on the sandbox pair: a frame's own operator relayed back a copy of a card it had pulled from the frame
    while the agent was suspended. The copy was OLDER by the clock and got in only because it carried a `location` the
    home's copy does not; the whole card was replaced, so the home's lifted suspension came back and stayed (the
    re-stamp then out-dated the home's own clock). A copy that is not newer may add what it has and we lack; it may not
    carry its older state (the enforcement extension, the listing, the text) along with it.
    """
    import copy as _copy
    out = _copy.deepcopy(existing_cd) if isinstance(existing_cd, dict) else {}
    incoming_cd = incoming_cd if isinstance(incoming_cd, dict) else {}
    for tag in tags:
        try:
            if tag == 'location':
                out['location'] = _copy.deepcopy(incoming_cd.get('location'))
            elif tag.startswith('meta:'):
                key = tag.split(':', 1)[1]
                meta = out.get('federation_metadata')
                if not isinstance(meta, dict):
                    meta = out['federation_metadata'] = {}
                meta[key] = _copy.deepcopy((incoming_cd.get('federation_metadata') or {}).get(key))
            elif tag == 'flare':
                out['flare'] = _copy.deepcopy(incoming_cd.get('flare'))
            elif tag == 'track_record':
                from agentvault_registry.services.track_record import TRACK_RECORD_EXTENSION_URI
                _replace_extensions(out, _copy.deepcopy(incoming_cd), TRACK_RECORD_EXTENSION_URI)
            elif tag == 'bond_maturity':
                from agentvault_registry.services.reputation_bond import BOND_EXTENSION_URI
                _replace_extensions(out, _copy.deepcopy(incoming_cd), BOND_EXTENSION_URI)
        except Exception:  # noqa: BLE001 — a field that cannot be merged is left out, never the whole ingest
            logger.warning("[FederationSync] could not merge new field %s; the card keeps ours for it", tag)
    return out


def _has_bond_maturity(card_data) -> bool:
    """§BONDFILL — does this card's reputation-bond extension carry the maturity snapshot?

    Narrow on purpose, exactly like `_has_track_record_ext`: every bonded card has carried the
    bond extension since §REPBOND, so presence of the URI says nothing. Only the `maturity`
    block inside it is the new information worth forcing an ingest for.
    """
    try:
        from agentvault_registry.services.reputation_bond import extension_from_card
        p = extension_from_card(card_data)
        return isinstance(p, dict) and isinstance(p.get("maturity"), dict)
    except Exception:  # noqa: BLE001 — a predicate must never break the ingest
        return False


def _listing_export_filters():
    """§LISTPROP (2026-09-08) — which cards may leave this registry, as a filter list.

    Under `LISTING_PROPAGATION_MODE=off` an unlisted card is excluded from the export exactly as
    §DISCREFINE wrote it ("an unlisted agent never leaves this registry") — that IS the rollback.
    Under shadow/enforce it is INCLUDED, so the fan-out can emit it as a TOMBSTONE: the card's
    content still never travels (`listing_propagation.tombstone_card_data` is the whole body), but
    the peer holding a stale mirror finally hears the one word it needs. Absence cannot propagate;
    this is what replaces the absence.
    """
    from ..services import listing_propagation as _lp
    if _lp.propagation_mode() == "off":
        return [models.AgentCard.unlisted.is_(False)]
    return []


async def get_agent_cards_updated_since(
    db: AsyncSession,
    timestamp: datetime,
    limit: int = 100,
    ascending: bool = False
) -> List[models.AgentCard]:
    """Get agent cards updated since a given timestamp.

    Args:
        db: Database session
        timestamp: Get cards updated after this time
        limit: Maximum number of cards to return
        ascending: §SYNCPAGE (2026-08-03) — updated_at ASC with an id tiebreak,
            required for the federation paged cursor walk (a DESC page's
            max(updated_at) is the NEWEST row, which would make a cursor leap
            over everything unseen). Default False preserves the historical
            DESC order for non-paged callers.

    Returns:
        List of AgentCard instances updated after the timestamp
    """
    order = (
        (models.AgentCard.updated_at.asc(), models.AgentCard.id.asc())
        if ascending
        else (models.AgentCard.updated_at.desc(),)
    )
    stmt = select(models.AgentCard).options(
        joinedload(models.AgentCard.developer)
    ).filter(
        models.AgentCard.updated_at > timestamp,
        # §DISCREFINE (mig 0153) / §LISTPROP (2026-09-08): see _listing_export_filters.
        # Both export branches call it, because a peer walking the cursor and a
        # peer asking for "recent" must see the same population — otherwise the
        # card escapes through whichever branch was forgotten.
        *_listing_export_filters(),
    ).order_by(
        *order
    ).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().unique().all()


async def get_recent_agent_cards(
    db: AsyncSession,
    limit: int = 100
) -> List[models.AgentCard]:
    """Get the most recently updated agent cards.
    
    Args:
        db: Database session
        limit: Maximum number of cards to return
        
    Returns:
        List of AgentCard instances ordered by most recent updates
    """
    stmt = select(models.AgentCard).options(
        joinedload(models.AgentCard.developer)
    ).filter(
        # §DISCREFINE / §LISTPROP — see get_agent_cards_updated_since: both branches agree.
        *_listing_export_filters(),
    ).order_by(
        models.AgentCard.updated_at.desc()
    ).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().unique().all()


def _parse_datetime(value) -> Optional[datetime]:
    """Parse a datetime from string or return as-is if already a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Handle ISO format strings (with or without Z suffix)
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass
    return None


def did_issuer_vs_origin(agent_card: Dict[str, Any], peer_trust_domain: Optional[str]):
    """(issuer, origin_trust_domain, did) for a peer's card envelope — the G5 comparison, pure.

    origin = federation_metadata.source_registry's trust domain when the card carries one (a relayed
    mirror keeps its origin), else the presenting peer's trust domain (a direct push from the origin).
    """
    from ..identifiers import agent_did_issuer
    cd = agent_card.get("card_data") if isinstance(agent_card, dict) else None
    cd = cd if isinstance(cd, dict) else {}
    did = cd.get("did") or (agent_card.get("agent_did") if isinstance(agent_card, dict) else None)
    issuer = agent_did_issuer(str(did)) if did else None
    meta = cd.get("federation_metadata") if isinstance(cd.get("federation_metadata"), dict) else {}
    src = str(meta.get("source_registry") or "")
    origin = src[len("spiffe://"):].split("/", 1)[0].lower() if src.startswith("spiffe://") else (peer_trust_domain or "").strip().lower()
    return issuer, (origin or None), did


async def _apply_listing_tombstone(db: AsyncSession, card_uuid, peer_svid: str, mode: str) -> str:
    """§LISTPROP — apply an unlisting to a MIRROR we already hold. Sets one boolean and nothing else.

    Never writes card_data, never touches a NATIVE card, never inserts. Those three refusals are
    what make it safe to exempt from the fail-closed ingest validation (see the call site).
    """
    from ..services import listing_propagation as _lp
    res = await db.execute(
        select(models.AgentCard).filter(models.AgentCard.id == card_uuid).with_for_update()
    )
    existing = res.scalar_one_or_none()
    if existing is None:
        # Nothing to correct: we hold no mirror, so there is no stale row, and importing one
        # would be importing an agent its home has deliberately withdrawn.
        _lp.count("refused_insert", mode)
        return "skipped"
    fed = (existing.card_data or {}).get('federation_metadata', {}) or {}
    if not fed.get('source_registry') and not fed.get('first_synced_from'):
        # OWL24, and it applies to hiding exactly as it applies to editing: a peer is never
        # authoritative over a card that originated here.
        logger.warning("[LISTPROP] BLOCKED peer %s from unlisting NATIVE card %s", peer_svid, card_uuid)
        return "skipped"
    if mode != "enforce":
        _lp.count("shadow", mode)
        logger.info("[LISTPROP shadow] would unlist mirror %s on its home's word (via %s)", card_uuid, peer_svid)
        return "unchanged"
    if bool(existing.unlisted):
        return "unchanged"
    existing.unlisted = True
    existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _lp.count("applied_unlisted", mode)
    await db.commit()
    logger.info("[LISTPROP] mirror %s unlisted by its home (presented by %s)", card_uuid, peer_svid)
    return "updated"


async def _apply_home_denials_despite_quarantine(db: AsyncSession, card_uuid, agent_card: Dict[str, Any],
                                                 peer_svid: str) -> str:
    """§QUARANTINEDENY (2026-09-29) — a HOME's deny-only facts reach a mirror whose update the fail-closed ingest refused.

    Measured on production: EU suspended 'Test Agent v3' on 09-17; its card (created 09-12, no `protocolVersion`) fails
    today's AgentCard schema, so ASIA (FEDERATION_INGEST_FAIL_CLOSED=true) quarantined every update and kept serving its
    09-12 copy, ACTIVE and unenforced, for twelve days, while the operators (fail-closed unset) took the suspension at
    once. The quarantine refuses untrusted CONTENT; it must not keep a withdrawn agent usable here.

    Applies, from the card's own home only (the caller passes `from_origin`), to a MIRROR we already hold:
      * an enforcement extension whose status is suspended/revoked: stored as a sanitized block built by
        enforcement_propagation.extension_entry, never the peer's raw dict;
      * `is_active: false`: the home deactivated the card.
    Never the reverse: a lifted suspension, a reactivation or any content still needs a card that validates, so this
    grants the home nothing it could not already do with a valid card, and a relay nothing at all. Never touches a
    NATIVE card, never inserts. Returns "updated" when something landed, else "skipped".
    """
    from ..services import enforcement_propagation as _ep
    res = await db.execute(
        select(models.AgentCard).filter(models.AgentCard.id == card_uuid).with_for_update()
    )
    existing = res.scalar_one_or_none()
    if existing is None:
        return "skipped"   # we hold no mirror, so nothing stale is being served: importing it is the schema's call
    stored = existing.card_data if isinstance(existing.card_data, dict) else {}
    fed = stored.get('federation_metadata', {}) or {}
    if not fed.get('source_registry') and not fed.get('first_synced_from'):
        return "skipped"   # OWL24: a peer is never authoritative over a card that originated here

    landed: List[str] = []
    new_cd = None
    incoming = _ep.extension_from_card(agent_card.get('card_data')) or {}
    status = str(incoming.get('status') or '').strip().lower()
    if _ep.is_enforced_status(status):
        held = _ep.extension_from_card(stored) or {}
        if str(held.get('status') or '').strip().lower() != status:
            block = _ep.extension_entry({
                "status": status,
                "since": str(incoming.get('since'))[:64] if incoming.get('since') else None,
                "registry": str(incoming.get('registry'))[:120] if incoming.get('registry') else None,
            })
            import copy as _copy
            new_cd = _copy.deepcopy(stored)
            new_cd['extensions'] = [e for e in (new_cd.get('extensions') or [])
                                    if not (isinstance(e, dict) and e.get('uri') == _ep.ENFORCEMENT_EXTENSION_URI)]
            new_cd['extensions'].append(block)
            landed.append(f"enforcement={status}")
    if agent_card.get('is_active') is False and existing.is_active:
        existing.is_active = False
        landed.append("deactivated")
    if not landed:
        return "skipped"
    if new_cd is not None:
        existing.card_data = new_cd   # a NEW object: the ORM sees the change without flag_modified
    existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    logger.warning("[QUARANTINEDENY] mirror %s: applied its home's %s although the card failed the schema "
                   "(presented by %s); the content stays quarantined", card_uuid, ", ".join(landed), peer_svid)
    return "updated"


def is_erasure_tombstone(agent_card) -> bool:
    """D6-816 — the card a home exports after an account deletion redacted it (routers/account_deletion.py, step 5):
    inactive, its card_data reduced to the DID, the capabilities and `anonymized: true`. It is not an AgentCard and names no
    origin (no federation_metadata), so neither the fail-closed schema check nor is_origin_copy() can answer for it."""
    if not isinstance(agent_card, dict) or agent_card.get('is_active') is not False:
        return False
    cd = agent_card.get('card_data')
    return isinstance(cd, dict) and cd.get('anonymized') is True


def _stored_origin_trust_domain(fed: Dict[str, Any]) -> Optional[str]:
    """The trust domain of the registry a mirror came from, read from what WE stored when we mirrored it
    (federation_metadata.source_registry, the origin frame's SPIFFE id, kept through every relay); None when it names none."""
    src = fed.get('source_registry') if isinstance(fed, dict) else None
    if not isinstance(src, str) or not src.startswith('spiffe://'):
        return None
    td = src[len('spiffe://'):].split('/', 1)[0].strip().lower()
    return td or None


async def _apply_home_erasure(db: AsyncSession, card_uuid, agent_card: Dict[str, Any], peer_svid: str,
                              presenter_trust_domain: Optional[str], from_origin: bool) -> str:
    """D6-816 — a home's erasure reaches the mirror we hold of its card.

    A home that deletes an account redacts that developer's cards (card_data to the DID, the capabilities and
    `anonymized: true`; the name to deleted-card-<id>; no description; inactive) and keeps exporting the result. On a frame
    with FEDERATION_INGEST_FAIL_CLOSED that tombstone failed the AgentCard schema, and the home's deny-only path just above
    could not apply its deactivation because the tombstone names no origin (neither that path's tag nor its function is
    repeated here: the build and the roll drivers count both in this file): the mirror kept serving the deleted
    account's card, ACTIVE and with its full content, for as long as the mirror lived (found 2026-10-24 by
    agentvault2-aa's capture of sbx-beta's hourly read, diagnosed by agentvault2-d6; production had none in 6 h on all six).

    Applies the same redaction to a MIRROR we already hold, when the presenter is that mirror's own home: the caller's
    from_origin, or the presenter's trust domain equal to the origin we stored (source_registry), never the tombstone's
    own word. Never a native card (OWL24), never an insert, never a relay. Keeps our federation_metadata (provenance,
    no personal data). Counted as an ingest skip when it does nothing, never as a schema refusal: a tombstone is an
    answer, not a malformed card. Returns "updated" when the redaction landed, else "skipped"."""
    res = await db.execute(
        select(models.AgentCard).filter(models.AgentCard.id == card_uuid).with_for_update()
    )
    existing = res.scalar_one_or_none()
    if existing is None:
        note_ingest_skip(card_uuid, peer_svid, "erasure_no_mirror")
        return "skipped"   # we hold no copy: there is nothing to erase, and a tombstone is never imported
    stored = existing.card_data if isinstance(existing.card_data, dict) else {}
    fed = stored.get('federation_metadata', {}) or {}
    if not fed.get('source_registry') and not fed.get('first_synced_from'):
        note_ingest_skip(card_uuid, peer_svid, "erasure_native")
        return "skipped"   # OWL24: a peer is never authoritative over a card that originated here
    origin_td = _stored_origin_trust_domain(fed)
    from_home = bool(from_origin) or bool(
        origin_td and presenter_trust_domain and origin_td == presenter_trust_domain.strip().lower())
    if not from_home:
        note_ingest_skip(card_uuid, peer_svid, "erasure_not_from_home")
        return "skipped"
    if stored.get('anonymized') is True and existing.is_active is False:
        return "skipped"   # erased already: every hourly read repeats the tombstone
    incoming = agent_card.get('card_data') or {}
    caps = incoming.get('capabilities')
    redacted = {
        "did": incoming.get('did') or stored.get('did') or existing.agent_did,
        "capabilities": caps if isinstance(caps, (dict, list)) else [],
        "anonymized": True,
        "federation_metadata": dict(fed),
    }
    existing.card_data = redacted   # a NEW object: the ORM sees the change without flag_modified
    existing.name = f"deleted-card-{card_uuid}"
    existing.description = None
    existing.is_active = False
    existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    logger.info("[D6-816] mirror %s: its home's erasure applied (presented by %s): redacted and deactivated",
                card_uuid, peer_svid)
    return "updated"


def drop_export_derived(cd: Dict[str, Any]) -> None:
    """For the NATIVE-ECHO comparison only, in place: remove the extension blocks a registry DERIVES when it exports a
    card (the reputation bond, enforcement, listing and track-record blocks), and an `extensions` list left empty.

    §ECHOFLOOD (2026-10-09, measured on the sandbox): a native card is stored WITHOUT these blocks (each is derived at
    export, never persisted), while every peer's copy keeps what the export carried. So when a copy of our own card
    came back, the "is this echo unchanged?" test always saw a difference: for three sampled cards against both peers
    the reputation-bond block was the ONLY one, and each echo became an OWL24 WARNING instead of the silent no-op the
    §2026-06-16 gate intends (7,198 cards per full read, the sandbox's LogWarningStorm). A peer cannot change these
    blocks on our card anyway: this registry derives them. The mirror-update comparison keeps them (a home's state
    change must still reach its mirrors), so this runs only where the stored side is our native."""
    exts = cd.get("extensions") if isinstance(cd, dict) else None
    if not isinstance(exts, list):
        return
    from ..services.enforcement_propagation import ENFORCEMENT_EXTENSION_URI
    from ..services.listing_propagation import LISTING_EXTENSION_URI
    from ..services.reputation_bond import BOND_EXTENSION_URI
    from ..services.track_record import TRACK_RECORD_EXTENSION_URI
    derived = {BOND_EXTENSION_URI, ENFORCEMENT_EXTENSION_URI, LISTING_EXTENSION_URI, TRACK_RECORD_EXTENSION_URI}
    kept = [e for e in exts if not (isinstance(e, dict) and e.get("uri") in derived)]
    if kept:
        cd["extensions"] = kept
    else:
        cd.pop("extensions", None)


def drop_derived_since(cd: Dict[str, Any]) -> None:
    """For CHANGE DETECTION only, in place: remove the values a registry DERIVES at export time: `params.since` of the
    listing and enforcement extensions, and `params.maturity.as_of` and `params.maturity.trust_population` of the
    reputation-bond extension.

    §SYNCLOOP (2026-09-26, measured on the sandbox tier): a relaying registry derives these blocks' `since` from its OWN
    copy's `updated_at`, and the upsert re-stamps `updated_at` on every write. So a relayed dark card compared as
    changed on every hop and circled the mesh for good: 12 to 35 copies rewritten per node per sync cycle while no
    native card had changed, the only differing fields being this `since` and the sync's own timestamp (which the
    §2026-06-16 gate already ignores). The STATE (`unlisted`, `status`, `registry`) is still compared; only the
    derived clock is not, so the stored copy keeps the `since` of the write that brought the state.
    §ECHO (2026-09-28, measured on V0483): the bond's maturity snapshot stamps `as_of` = now() on every EXPORT, so once
    the origin's own copy replaces a mirror whenever it differs, every bonded card in a sync page was rewritten on every
    sync (two stored copies 30 s apart differed only in `as_of` and the sync's timestamp). The snapshot's VALUES
    (transactions, eigentrust, percentile, thresholds, matured) are still compared.
    §POPCOUNT (2026-09-28, measured on V0484): `maturity.trust_population` is the HOME FRAME's count of ranked agents,
    stamped on every bonded card it exports. It moves whenever any agent anywhere on that frame is ranked, so a full
    walk found every bonded mirror "changed": the daily digest walk rewrote ~4,445 bonded mirrors on sbx-beta in one
    minute while one mirror's own values were unchanged (stored 1418 at 14:11:15, the home exported 1427 at 14:29). It
    says nothing about the card's own agent, so it joins the derived fields; the agent's own values stay compared.
    """
    exts = cd.get("extensions") if isinstance(cd, dict) else None
    if not isinstance(exts, list):
        return
    from ..services.enforcement_propagation import ENFORCEMENT_EXTENSION_URI
    from ..services.listing_propagation import LISTING_EXTENSION_URI
    from ..services.reputation_bond import BOND_EXTENSION_URI
    for ext in exts:
        if not (isinstance(ext, dict) and isinstance(ext.get("params"), dict)):
            continue
        if ext.get("uri") in (LISTING_EXTENSION_URI, ENFORCEMENT_EXTENSION_URI):
            ext["params"].pop("since", None)
        elif ext.get("uri") == BOND_EXTENSION_URI and isinstance(ext["params"].get("maturity"), dict):
            ext["params"]["maturity"].pop("as_of", None)
            ext["params"]["maturity"].pop("trust_population", None)   # §POPCOUNT: a frame-level count


async def _set_mirror_unlisted(db: AsyncSession, card_uuid, peer_svid: str) -> int:
    """§DARKSYNC (2026-09-22) — a FULL card whose home says unlisted: set the column on a MIRROR we hold and let the
    content continue through the normal gates. Deliberately does NOT move `updated_at` (unlike the tombstone half):
    the content path's timestamp comparison must see the peer's real clock, or the content in the same card would be
    skipped as "ours is newer". A mirror only; idempotent; a no-op when there is no mirror (the create branch then
    stores the new row unlisted)."""
    res = await db.execute(text(
        "UPDATE agent_cards SET unlisted = TRUE "
        "WHERE id = :id AND unlisted = FALSE "
        "AND (card_data#>>'{federation_metadata,source_registry}') IS NOT NULL"
    ), {"id": str(card_uuid)})
    n = int(res.rowcount or 0)
    if n:
        await db.commit()
        from ..services import listing_propagation as _lp
        _lp.count("applied_unlisted_carried")
        logger.info("[DARKSYNC] mirror %s marked unlisted by its home (presented by %s)", card_uuid, peer_svid)
    return n


async def _clear_listing_tombstone(db: AsyncSession, card_uuid, peer_svid: str) -> int:
    """§LISTPROP — the RESTORE half, and it must run beside the tombstone half rather than below
    the ingest gate, or hiding becomes a ONE-WAY DOOR.

    MEASURED 2026-09-09: the subject of the live proof (`provider.url == ""`, one of 11 such cards
    on EU alone) is schema-invalid, so a fail-closed peer QUARANTINES every content update to it —
    and always has. The tombstone reached ASIA because it now sits above that gate; the re-list
    could not, because it rides a full card the peer refuses. The card would have stayed hidden on
    that peer forever, which is worse than the defect §LISTPROP set out to fix.

    So the COLUMN is restored on its own, for the same reason it is set on its own: it is not
    content. A mirror only. Idempotent, and a no-op unless something is actually hidden.
    """
    res = await db.execute(text(
        "UPDATE agent_cards SET unlisted = FALSE, updated_at = NOW() "
        "WHERE id = :id AND unlisted = TRUE "
        "AND (card_data#>>'{federation_metadata,source_registry}') IS NOT NULL"
    ), {"id": str(card_uuid)})
    n = int(res.rowcount or 0)
    if n:
        await db.commit()
        from ..services import listing_propagation as _lp
        _lp.count("applied_relist")
        logger.info("[LISTPROP] mirror %s re-listed by its home (presented by %s)", card_uuid, peer_svid)
    return n


async def upsert_agent_cards_from_peer(
    db: AsyncSession,
    peer_svid: str,
    agent_card: Dict[str, Any],
    peer_trust_domain: Optional[str] = None,
    from_origin: bool = False,
) -> str:
    """Upsert an agent card received from a federation peer.
    
    This function intelligently updates or inserts agent cards received
    from trusted peers. It preserves local modifications while accepting
    updates from authoritative sources.
    
    Args:
        db: Database session
        peer_svid: SPIFFE ID of the peer sending the card
        agent_card: Agent card data from the peer
        
    Returns:
        "created" if a new card was created, "updated" if existing was updated
    """
    
    # Extract card ID
    card_id = agent_card.get('id')
    if isinstance(card_id, str):
        try:
            card_uuid = uuid.UUID(card_id)
        except ValueError:
            # Invalid UUID, skip this card
            note_ingest_skip(card_id, peer_svid, "invalid_id")
            return "skipped"
    else:
        note_ingest_skip(card_id, peer_svid, "invalid_id")
        return "skipped"

    # D6-816 — AN ERASURE TOMBSTONE IS NOT A CARD EITHER. A home that deleted an account exports its redacted cards
    # (card_data: the DID, the capabilities, `anonymized: true`), and the fail-closed gate below would refuse each one,
    # every hourly read, as a schema-invalid card, while the mirror kept serving the deleted card active and whole.
    # It sits above §LISTPROP's handling and the gate for the reason §LISTPROP's tombstone does: it stores no content,
    # only the home's redaction of a mirror we already hold, and only when the presenter is that mirror's home
    # (_apply_home_erasure).
    if is_erasure_tombstone(agent_card):
        return await _apply_home_erasure(db, card_uuid, agent_card, peer_svid, peer_trust_domain, from_origin)

    from ..services import listing_propagation as _lp  # §LISTPROP (2026-09-08)

    # 🔴 §LISTPROP — A TOMBSTONE IS NOT A CARD AND MUST NOT BE VALIDATED AS ONE. This sits ABOVE
    # the fail-closed ingest gate below on purpose. That gate asks "is this a well-formed
    # AgentCard?", and a tombstone is deliberately NOT one — it carries a DID and one extension,
    # because the whole point is that an unlisted agent's CONTENT never leaves its home.
    # MEASURED 2026-09-09 on the live cluster, and only the live proof could see it: the unit
    # tests do not run this gate. EU exported the tombstone to ASIA every cycle and ASIA
    # QUARANTINED every one of them (`FEDERATION_INGEST_FAIL_CLOSED=true` on both frames, unset on
    # the operators), so the mirror never moved and nothing logged a refusal anyone would read.
    # The exemption is safe in a way that exempting a card would not be: a tombstone STORES
    # NOTHING. It sets one boolean on a row we already hold — never card_data, never a native
    # card, never an insert (see _apply_listing_tombstone).
    _lp_early = _lp.propagation_mode()
    # §DARKSYNC (2026-09-22): a FULL card whose home says unlisted (the envelope flag or the card's listing block) is
    # imported as an UNLISTED mirror: hidden from our discovery, still resolvable by DID, still content. Only under
    # enforce: in shadow or off it is not imported at all, because a mirror stored LISTED would put a dark agent into
    # our discovery. The content-free tombstone keeps its §LISTPROP handling below.
    _says_unlisted = bool(agent_card.get('unlisted')) or _lp.unlisted_from_card(agent_card.get('card_data')) is True
    _carried_unlisted = _says_unlisted and not _lp.is_legacy_tombstone(agent_card)
    if _carried_unlisted:
        if _lp_early != "enforce":
            _lp.count("carried_not_imported", _lp_early)
            return "skipped"
        await _set_mirror_unlisted(db, card_uuid, peer_svid)
    elif _lp_early != "off":
        if _says_unlisted:
            return await _apply_listing_tombstone(db, card_uuid, peer_svid, _lp_early)
        # …and the RESTORE, symmetrically, ABOVE the same gate. Hiding must not be a one-way door
        # for a card the peer cannot ingest (see _clear_listing_tombstone). This does not swallow
        # the card: the content update continues below exactly as before.
        if _lp_early == "enforce":
            await _clear_listing_tombstone(db, card_uuid, peer_svid)

    # AUDIT Agent-card H1 — the federated ingest path historically bypassed ALL
    # schema validation that the NATIVE create path enforces (crud/agent_card.py:
    # AgentCardModel.model_validate). A peer could thus relay a card with a
    # javascript: URL, oversized fields, or arbitrary pricing that we store +
    # re-serve + re-relay mesh-wide. When fail-closed ingest is on, validate the
    # peer card_data against the canonical AgentCard model and QUARANTINE (skip)
    # anything non-conformant. Default-off preserves current first-party behaviour.
    import os as _os
    if (_os.getenv("FEDERATION_INGEST_FAIL_CLOSED", "") or "").strip().lower() in ("1", "true", "yes", "on"):
        _cd_in = agent_card.get('card_data')
        if isinstance(_cd_in, dict):
            try:
                from agentvault import AgentCard as _AgentCardModel
                _AgentCardModel.model_validate(_cd_in)
            except Exception as _ve:
                _fields = schema_refusal_fields(_ve)
                logger.warning(
                    "AUDIT fail-closed: quarantining federated agent card %s from %s: schema-invalid card_data, "
                    "%d error(s): %s", card_uuid, peer_svid, len(_fields),
                    "; ".join(f"{p} ({t}): {m}" for p, t, m in _fields[:8]) + (" ..." if len(_fields) > 8 else ""),
                )
                if FEDERATION_CARD_INGEST_REFUSED_TOTAL is not None:
                    try:
                        FEDERATION_CARD_INGEST_REFUSED_TOTAL.labels(peer=str(peer_svid)[:120], field=_fields[0][0]).inc()
                    except Exception:  # a metrics failure never decides an ingest
                        pass
                # §QUARANTINEDENY (2026-09-29): the quarantine refuses the NEW content, and the copy we already hold
                # stays live. The home's DENY-ONLY facts in the same envelope still land on that copy (see
                # _apply_home_denials_despite_quarantine), or a suspension is dodged by a card whose other content
                # fails today's schema.
                if from_origin:
                    return await _apply_home_denials_despite_quarantine(db, card_uuid, agent_card, peer_svid)
                return "skipped"

    # §28 (2026-05-15) — Echo-prevent the flare sidecar BEFORE the wholesale
    # upsert. card_data.flare carries a `source_registry` SPIFFE indicating
    # where the flare was ORIGINALLY stamped. The check defends against a
    # malicious/buggy peer injecting flare with a bogus source_registry.
    #
    # §pass34 (2026-05-17) — Original implementation required
    # flare.source_registry == peer_svid (the immediate sender). That broke
    # BFS mesh relay: when Frame B relays SYBIL to op-tokyo, the flare's
    # source_registry is still 'registry-a' but peer_svid is 'frame-b' → drop.
    # Effect: flare reached only DIRECT peers of the origin, never relayed
    # through the mesh. SYBIL/CRUCIBLE/etc. invisible on 7-of-8 cloud-ops.
    #
    # New rule: accept flare if source_registry matches the immediate peer
    # OR ANY trusted peer registered in OUR peer_registries (i.e., a known
    # federation member). This trusts the mesh to relay flares faithfully
    # — the same trust assumption we already make for every other card_data
    # field (description, URL, pricing, …). Drops flare ONLY when claimed
    # origin is from outside our federation. Card_data without `flare` is
    # the no-op path.
    _incoming_cd = agent_card.get('card_data') or {}
    # §DIDWIDEN item 1 — G5, COUNT-ONLY for now (his plan: count first, drop when every frame carries a
    # namespace): a mirrored card whose DID names an issuer that is not the card's ORIGIN trust domain.
    # The origin is the card's own federation_metadata.source_registry (the origin frame's SPIFFE id, kept
    # through every relay); a card without it came straight from its origin, so the presenting peer ROW's
    # trust_domain is the origin. Never the peer_svid string: the agent-card sync still names presenters with
    # a legacy agentvault.com template (federation_sync ~L2542), which counted every honest relay (measured
    # 2+8 on the pair before this rule).
    try:
        _iss, _origin_td, _did_in = did_issuer_vs_origin(agent_card, peer_trust_domain)
        if _iss and _origin_td and _iss != _origin_td:
            from ..background_tasks.federation_sync import _count_did_conflict as _count
            _count((peer_svid or "").rsplit("/", 1)[-1] or "unknown", "foreign_namespace")
            logger.info("[FederationSync] agent card %s carries issuer %s but its origin is %s (counted, not dropped — G5 count-only)",
                        _did_in, _iss, _origin_td)
    except Exception:  # noqa: BLE001 — telemetry never breaks the mirror path
        pass
    _incoming_flare = _incoming_cd.get('flare') if isinstance(_incoming_cd, dict) else None
    if isinstance(_incoming_flare, dict) and _incoming_flare.get('source_registry'):
        try:
            from ..services.spiffe_canonical import (
                canonical_equals as _canon_eq_flare,
                extract_canonical as _extract_canon,
                _normalize_name as _norm_name,
            )
            _flare_origin = _incoming_flare['source_registry']
            _accepted = _canon_eq_flare(_flare_origin, peer_svid)
            # §FLARETRAVEL (2026-09-11) — ACCEPT ON THE TRUST DOMAIN WHEN THE NAME SEGMENT IS A
            # LEGACY TEMPLATE. `_build_flare_sidecar` stamps source_registry from the registry's
            # own SVID, and on this cluster that is still the legacy
            # `spiffe://<td>/ns/agentvault/sa/registry-main` shape. canonical_equals compares
            # (trust_domain, NAME), so EU's own flare canonicalises to ('eu.theprotocol.cloud',
            # 'main') while the peer it arrived from is ('eu.theprotocol.cloud', 'eu') — equal
            # registries, different labels, and the flare was dropped as an echo from a stranger.
            # Measured on the live pair: Sheldon's encirclement and rank overlay rendered on EU
            # and vanished on ASIA for exactly this reason.
            #
            # The TRUST DOMAIN is the cryptographic identity; the name segment is a label, and
            # doctrine already says never to derive a peer's identity from that legacy string.
            # Matching domains means the same registry, so this widens nothing: a flare claiming
            # an origin outside our federation still has a foreign trust domain and is still
            # dropped by the checks below.
            if not _accepted:
                _fo = _extract_canon(_flare_origin)
                _po = _extract_canon(peer_svid)
                if _fo is not None and _po is not None and _fo[0] and _fo[0] == _po[0]:
                    _accepted = True
            if not _accepted:
                # Not the immediate peer — check if it's any other known
                # trusted federation peer (BFS-mesh relay path). Peer rows
                # are mTLS-authenticated members of our federation; trusting
                # them to relay flare faithfully is the same trust we
                # already extend to every other card_data field they carry.
                _flare_canon = _extract_canon(_flare_origin)
                if _flare_canon is not None:
                    _flare_norm = _norm_name(_flare_canon[1])
                    _peers_q = await db.execute(
                        select(models.PeerRegistry.name)
                        .where(models.PeerRegistry.status == 'ACTIVE')
                    )
                    for _row in _peers_q.fetchall():
                        if _norm_name(_row[0] or '') == _flare_norm:
                            _accepted = True
                            break
            if not _accepted:
                import logging as _l
                _l.getLogger(__name__).warning(
                    "§28 flare echo-prevent: dropping card_data.flare from %s — "
                    "flare.source_registry=%s is not the immediate peer (%s) "
                    "and not any active trusted peer in our federation.",
                    card_uuid, _flare_origin, peer_svid,
                )
                _incoming_cd.pop('flare', None)
        except Exception:
            # Helper / DB unavailable → fail-closed: strip the flare block.
            if isinstance(_incoming_cd, dict):
                _incoming_cd.pop('flare', None)

    # Check if the card already exists.
    # §pass34 (2026-05-17) — SELECT FOR UPDATE serializes concurrent
    # _sync_with_peer tasks against the same row. Without this, two
    # parallel federation pulls on the same agent_card both read the
    # pre-write snapshot, decide independently whether to update, and
    # last-writer-wins clobbers field-merge preservation (in particular,
    # the preserve-local-flare guard below was being defeated by parallel
    # writers that each saw "no local flare" before the flare-bearing
    # writer committed). With row-level lock, the second writer waits,
    # then re-reads the freshly-committed state including any preserved
    # flare and merges correctly.
    stmt = select(models.AgentCard).filter(
        models.AgentCard.id == card_uuid
    ).with_for_update()
    result = await db.execute(stmt)
    existing_card = result.scalar_one_or_none()

    # §2026-06-16 FEDERATION DELTA IDEMPOTENCY — normalize a card for change
    # detection. Drops PER-REGISTRY bookkeeping (federation_metadata sync keys +
    # updated_at) that legitimately differs across the mesh; include_sticky=False
    # additionally drops locally-owned flare/iconUrl. Two relayed copies that
    # normalize-equal carry NO real change, so the upsert becomes a NO-OP — no
    # write, no updated_at re-stamp, no OWL24 warning. This restores the `since`
    # incremental filter (every relay used to re-stamp updated_at=NOW → full
    # ~1.2k-card payloads + full re-writes fleet-wide every ~30-60s) and ends the
    # relay churn + the ~5.5M/day OWL24 WARNING flood at the ROOT.
    def _norm_card(cd, *, include_sticky, native_echo=False):
        import copy as _copy
        if not isinstance(cd, dict):
            return cd
        c = _copy.deepcopy(cd)
        # Drop volatile + per-registry bookkeeping + federation SERVE-enrichment
        # that legitimately differs between a NATIVE card and its FEDERATED copies.
        # Proven (§2026-06-16, tokyo-native vs peer-copy diff): the ONLY differing
        # fields were updated_at, the whole federation_metadata block (source_registry,
        # *_synced_from, *_timestamp, origin_registry_*, protocol_version, …), and the
        # serve-derived top-level `did` (= agent_did column) + `location` (= origin
        # registry). The agent-authored CORE (name/skills/capabilities/url/provider/
        # security/…) is identical mesh-wide. Including any enrichment field makes
        # every relay look "changed" → the perpetual churn + OWL24 flood. Genuine
        # did/location changes are rare and ride the periodic full-reconcile.
        for _k in ('updated_at', 'federation_metadata', 'did', 'location'):
            c.pop(_k, None)
        if not include_sticky:
            c.pop('flare', None)
            c.pop('iconUrl', None)
        drop_derived_since(c)
        if native_echo:
            drop_export_derived(c)
        return c
    
    if existing_card:
        # OWL24 P0 FIX: NEVER overwrite a NATIVE card with peer data.
        # A native card is one that originated on THIS registry — identified by
        # the ABSENCE of 'source_registry' or 'first_synced_from' in its
        # federation_metadata. Only cards that were CREATED by federation sync
        # (i.e., synced copies) should be updatable by peers.
        existing_fed_meta = (existing_card.card_data or {}).get('federation_metadata', {})
        is_native_card = not existing_fed_meta.get('source_registry') and not existing_fed_meta.get('first_synced_from')
        
        if is_native_card:
            # §2026-06-16: a relay of our OWN native card (echoed back via a
            # third-party peer — OWL30 multi-hop) is the dominant case and is a
            # benign NO-OP. Only WARN if the peer's copy would actually CHANGE our
            # authoritative content (rare, genuinely worth a signal). This ends
            # the OWL24 WARNING flood at the root — no log-level hack.
            if (
                _norm_card(agent_card.get('card_data', {}) or {}, include_sticky=False, native_echo=True)
                == _norm_card(existing_card.card_data or {}, include_sticky=False, native_echo=True)
                and agent_card.get('name', existing_card.name) == existing_card.name
                and agent_card.get('description', existing_card.description) == existing_card.description
            ):
                note_ingest_skip(card_uuid, peer_svid, "native_echo")
                return "unchanged"
            import logging
            logging.getLogger(__name__).warning(
                f"OWL24: BLOCKED peer {peer_svid} from changing native card {card_uuid}. "
                f"Native cards are authoritative and cannot be modified by federation sync."
            )
            note_ingest_skip(card_uuid, peer_svid, "native_blocked")
            return "skipped"
        
        # §LISTPROP (2026-09-08) — THE LISTING COLUMN IS DECIDED HERE, BEFORE THE TIMESTAMP AND
        # IDEMPOTENCY GATES BELOW, AND THE REASON IS EASY TO MISS IN BOTH DIRECTIONS:
        #   · a TOMBSTONE is stamped at the epoch on purpose (so a peer that does not speak
        #     §LISTPROP declines it), so the timestamp gate below would always discard it;
        #   · a RE-LIST ships card_data byte-identical to what we already hold (the tombstone
        #     deliberately never overwrote our copy), so the idempotency gate would answer
        #     "unchanged" and the column would never come back.
        # Native cards never reach this point — the OWL24 guard above already returned.
        # §LISTPROP — BOTH halves of the listing column are decided ABOVE the ingest gate
        # (_apply_listing_tombstone / _clear_listing_tombstone). Nothing about listing is decided
        # here: a second copy would be one fact computed twice, and this copy is the one that
        # cannot run for a card the peer refuses to ingest.

        # Update existing SYNCED card if the peer's version is newer
        peer_updated_at = _parse_datetime(agent_card.get('updated_at'))
        
        # Also update if incoming card has new fields (e.g., location or registry coords): the ONE list of those tests
        # is `new_fields_offered` (§pass34 flare, §TRAVELREC, §BONDFILL-3; each clause keeps its reason there).
        incoming_card_data = agent_card.get('card_data', {})
        existing_cd = existing_card.card_data or {}
        _new_fields = new_fields_offered(existing_cd, incoming_card_data)
        has_new_fields = bool(_new_fields)
        # §ECHO (2026-09-28) — THE ORIGIN'S OWN COPY IS THE TRUTH, whatever the clocks say. The clock comparison below
        # sets the ORIGIN's clock against OUR local write stamp, two different clocks: once a stale relay had been
        # written (and re-stamped NOW), the home's genuine correction was older than that stamp and was refused until
        # the home touched the card again (measured: a lifted suspension stuck for good on three nodes). A copy the
        # caller received from the card's home (`from_origin`) therefore replaces ours whenever it differs; the
        # idempotency gate below still makes an identical copy a no-op, so a quiet mesh stays quiet.
        _newer = bool(from_origin) or bool(peer_updated_at and peer_updated_at > existing_card.updated_at)
        if has_new_fields or _newer:
            if _newer:
                # a newer copy replaces ours, as it always has
                updated_card_data = agent_card.get('card_data', {})
                _in_name = agent_card.get('name', existing_card.name)
                _in_description = agent_card.get('description', existing_card.description)
                _in_active = agent_card.get('is_active', existing_card.is_active)
            else:
                # §ECHO (2026-09-28) — ADMITTED ONLY FOR A NEW FIELD, so it brings that field and nothing else: an
                # older copy must not carry its older state (the enforcement extension, the text, the active flag)
                # in with it. Measured: a frame's own operator relayed back the SUSPENDED copy it had pulled from
                # the frame, older by the clock but carrying a `location`, and the home's lifted suspension came
                # back and stayed. See merge_new_fields.
                updated_card_data = merge_new_fields(existing_cd, incoming_card_data, _new_fields)
                _in_name, _in_description, _in_active = (
                    existing_card.name, existing_card.description, existing_card.is_active)
            # §pass34 (2026-05-17) — Preserve local flare when incoming has none.
            # Defensive safety net for BFS mesh sync: if our local copy already
            # carries a valid flare (relayed from the origin via some peer),
            # don't lose it just because THIS peer's copy doesn't have one (e.g.
            # they haven't synced yet, or they're a pre-§pass34 registry that
            # stripped it via the old echo-prevent). Flare is sticky on the way
            # in; the only thing that overwrites it is a fresh flare block from
            # an accepted source (§28 check above).
            if isinstance(updated_card_data, dict):
                _local_flare = (existing_card.card_data or {}).get('flare') if isinstance(existing_card.card_data, dict) else None
                _new_flare = updated_card_data.get('flare')
                if isinstance(_local_flare, dict) and not isinstance(_new_flare, dict):
                    updated_card_data['flare'] = _local_flare
                # §pass39c (2026-05-18) — Tier-rank preserve. The BFS mesh causes
                # stale legacy flares (e.g. shadow_chancellor cached on a peer
                # that hasn't synced yet) to overwrite newer sovereign flares.
                # Without this, every cycle a peer with old data pushes back
                # the legacy tier and the rollout never converges. Rule: when
                # local has a HIGHER-rank tier than incoming, keep local.
                # sovereign > shadow_chancellor > founder > architect > sentinel.
                # Origin-of-truth (set by registry-a's _build_flare_sidecar) is
                # still authoritative — only OLD legacy data is suppressed.
                if isinstance(_local_flare, dict) and isinstance(_new_flare, dict):
                    _FLARE_TIER_RANK = {
                        'sentinel': 1, 'architect': 2, 'founder': 3,
                        'shadow_chancellor': 4, 'sovereign': 5,
                    }
                    _local_rank = _FLARE_TIER_RANK.get(_local_flare.get('tier') or '', 0)
                    _new_rank = _FLARE_TIER_RANK.get(_new_flare.get('tier') or '', 0)
                    if _local_rank > _new_rank:
                        updated_card_data['flare'] = _local_flare
                # §pass38d (2026-05-18) — Symmetric preserve guard for iconUrl
                # (avatar). Same sticky-on-the-way-in pattern as flare: if local
                # has a non-empty iconUrl and incoming doesn't, keep local.
                # Prevents BFS relays from regressing avatar when a stale-path
                # peer has the old iconUrl-less version of a card.
                _local_icon = (existing_card.card_data or {}).get('iconUrl') if isinstance(existing_card.card_data, dict) else None
                _new_icon = updated_card_data.get('iconUrl')
                if isinstance(_local_icon, str) and _local_icon and not (isinstance(_new_icon, str) and _new_icon):
                    updated_card_data['iconUrl'] = _local_icon
            # §2026-06-16 idempotency gate: write + re-stamp ONLY if the merged
            # result actually changes our stored card. An idempotent relay (the
            # common case) returns here WITHOUT touching updated_at, keeping the
            # `since` delta filter meaningful and ending the relay churn. Sticky
            # fields ARE compared (include_sticky=True) so genuine flare/icon/tier
            # changes from the merge logic above still propagate.
            # §R55 (batch 2, 2026-09-05): the envelope's developer_verified was consumed ONCE, at the
            # shadow developer's creation, and never again — a developer who verified AFTER their
            # first card synced stayed unverified on every peer forever, so `verified_only` hid
            # their agents there (measured on op-berlin: the filter cannot see the home's truth).
            # The shadow developer now tracks the home's flag on every sync; the home touches the
            # developer's native cards when the flag flips so this update actually arrives.
            _shadow_dev = None
            _dv_changed = False
            # §ECHO: only a NEWER copy speaks for the home's developer flag; an older one would flip it back
            if _newer and 'developer_verified' in agent_card and existing_card.developer_id:
                _shadow_dev = await db.get(models.Developer, existing_card.developer_id)
                if _shadow_dev is not None and getattr(_shadow_dev, 'is_federation_shadow', False):
                    _dv_changed = bool(_shadow_dev.is_verified) != bool(agent_card.get('developer_verified'))
            if (
                _norm_card(updated_card_data, include_sticky=True)
                == _norm_card(existing_card.card_data or {}, include_sticky=True)
                and _in_name == existing_card.name
                and _in_description == existing_card.description
                and _in_active == existing_card.is_active
                and not _dv_changed
            ):
                note_ingest_skip(card_uuid, peer_svid, "unchanged")
                return "unchanged"
            if _dv_changed:
                _shadow_dev.is_verified = bool(agent_card.get('developer_verified'))
            existing_card.card_data = updated_card_data
            existing_card.name = _in_name
            existing_card.description = _in_description
            existing_card.is_active = _in_active
            if updated_card_data.get('did') and not existing_card.agent_did:
                existing_card.agent_did = updated_card_data['did']
            existing_card.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # Preserve federation metadata on synced cards
            if 'federation_metadata' not in existing_card.card_data:
                existing_card.card_data['federation_metadata'] = {}
            
            # Preserve the original source_registry and first_synced_from
            existing_card.card_data['federation_metadata']['last_synced_from'] = peer_svid
            existing_card.card_data['federation_metadata']['last_sync_timestamp'] = datetime.now(timezone.utc).isoformat()
            if 'source_registry' not in existing_card.card_data['federation_metadata']:
                existing_card.card_data['federation_metadata']['source_registry'] = peer_svid
            if 'first_synced_from' not in existing_card.card_data['federation_metadata']:
                existing_card.card_data['federation_metadata']['first_synced_from'] = peer_svid
            
            await db.commit()
            return "updated"
        else:
            # Our version is newer or same, skip update. (§LISTPROP needs nothing here: the column
            # was already settled above, on its own transaction, before this comparison ran.)
            note_ingest_skip(card_uuid, peer_svid, "not_newer",
                             f"theirs updated_at {agent_card.get('updated_at')!r}, ours {existing_card.updated_at}, "
                             f"from the card's home {bool(from_origin)}, no new field")
            return "skipped"
    else:
        # §LISTPROP — A TOMBSTONE NEVER CREATES A ROW. We do not hold this card, so there is no
        # stale mirror to correct; inserting one would import an agent its home has deliberately
        # withdrawn from discovery. (§ENFPROP's tombstone rule, unchanged: a mirror it already
        # holds, never a native card, never an insert.)
        if (_lp.propagation_mode() != "off" and _lp.unlisted_from_card(agent_card.get('card_data')) is True
                and not _carried_unlisted):
            _lp.count("refused_insert")
            note_ingest_skip(card_uuid, peer_svid, "tombstone_insert_refused")
            return "skipped"

        # Create new card
        # First, check if we have the developer
        developer_id = agent_card.get('developer_id')
        stmt = select(models.Developer).filter(
            models.Developer.id == developer_id
        )
        result = await db.execute(stmt)
        developer = result.scalar_one_or_none()
        
        if not developer:
            # Create a placeholder developer for federated content.
            # SECURITY: Never force the remote developer_id (causes collisions).
            # Never reuse a local developer by name (would grant cross-registry ownership).
            # Name is namespaced by peer SVID — structurally impossible to collide with any real account.
            peer_label = peer_svid.split('/')[-1]  # e.g. "registry-b"
            fed_email = f"federated-{developer_id}@{peer_label}.federation"
            # Get-or-create: check by email (unique constraint) to avoid duplicates
            # when multiple cards from the same remote developer arrive in one batch
            email_check = await db.execute(
                select(models.Developer).filter(models.Developer.email == fed_email)
            )
            developer = email_check.scalar_one_or_none()
            if not developer:
                developer = models.Developer(
                    name=f"fed:{peer_label}:dev-{developer_id}",
                    email=fed_email,
                    hashed_password="FEDERATED_ACCOUNT_NO_LOGIN",
                    is_verified=agent_card.get('developer_verified', False),
                    # §pass66.9 — Explicit shadow flag (replaces hashed_password
                    # literal-match filter in `list_developers`). Set at create
                    # time so the row never appears in human-facing developer
                    # listings even before any backfill ran.
                    is_federation_shadow=True,
                )
                db.add(developer)
                await db.flush()  # Ensure developer is created before referencing
        
        # Create the agent card
        card_data = agent_card.get('card_data', {})
        
        # Add federation metadata
        if 'federation_metadata' not in card_data:
            card_data['federation_metadata'] = {}
        
        card_data['federation_metadata']['source_registry'] = agent_card.get('source_registry', peer_svid)
        card_data['federation_metadata']['first_synced_from'] = peer_svid
        card_data['federation_metadata']['first_sync_timestamp'] = datetime.now(timezone.utc).isoformat()
        
        new_card = models.AgentCard(
            id=card_uuid,
            developer_id=developer.id,
            card_data=card_data,
            name=agent_card.get('name', 'Unknown Agent'),
            description=agent_card.get('description'),
            is_active=agent_card.get('is_active', True),
            agent_did=card_data.get('did'),
            created_at=_parse_datetime(agent_card.get('created_at')) or datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),  # Always fresh — enables multi-hop relay propagation
            unlisted=bool(_carried_unlisted),       # §DARKSYNC: a dark agent's mirror is born unlisted
        )
        
        db.add(new_card)
        await db.commit()
        return "created"


# --- Registry Card v0.3 (2026-05-21) ---------------------------------------

async def upsert_registry_card_from_peer(
    db: AsyncSession,
    peer_id: int,
    card: Dict[str, Any],
    *,
    etag: Optional[str] = None,
    signature_verified: bool = False,
    signature_kid: Optional[str] = None,
) -> bool:
    """Cache a v0.3 registry card fetched from a federation peer.

    Writes to peer_registries.cached_registry_card + card_etag +
    card_last_pulled_at + card_signature_verified + card_signature_kid.

    Called by federation_sync._sync_registry_card after the validator passes.
    """
    stmt = select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id)
    peer = (await db.execute(stmt)).scalar_one_or_none()
    if peer is None:
        return False
    peer.cached_registry_card = card
    peer.card_etag = etag
    peer.card_last_pulled_at = datetime.now(timezone.utc)
    peer.card_signature_verified = bool(signature_verified)
    peer.card_signature_kid = signature_kid
    await db.commit()
    return True

# --- END Registry Card v0.3 ------------------------------------------------
