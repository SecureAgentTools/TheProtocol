"""Federation helper for querying peer registries during agent discovery.

This module queries peer registries via the same mTLS-authenticated
/api/v1/federation/agent-cards endpoint used by the background sync worker.

OWL19:  mTLS via nginx sidecars is the default transport.
ROUND7B: Rewrote to use proven sync endpoint + mTLS auth (fixing 3-layer breakage
         in the old /internal/federation/query path).

LAYERS FIXED:
  1. No mTLS certs → now uses svid_client.get_client_cert_config()
  2. nginx path mismatch → now uses /api/v1/federation/agent-cards (proxied)
  3. Wrong FastAPI route → same endpoint the background sync hits (200 OK proven)
  4. Missing Bearer token → mTLS auth, no token needed
"""
import logging
import os
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from agentvault_registry import models
from agentvault_registry.identity import svid_client

logger = logging.getLogger(__name__)


# §TWOAGENT #11 (2026-09-23) — the live fan-out reads each peer's SYNC FEED (`/federation/agent-cards`), which takes
# `since`/`limit` and no search at all. The caller's filters were accepted and never applied, so
# `GET /agent-cards/?search=X&include_federated=true` answered with every peer's most recent cards (measured on ASIA:
# search=Scrivener → 27 unrelated peer rows of 30), each without a DID and labelled with the peer that ANSWERED
# rather than the frame the agent lives on. The filters below are the local listing's own rules
# (crud/agent_card.list_agent_cards), applied to each fetched card, so both halves of one list answer one question.
def peer_card_matches(card: Dict[str, Any], *, search: Optional[str] = None, tags: Optional[List[str]] = None,
                      has_tee: Optional[bool] = None, tee_type: Optional[str] = None) -> bool:
    """The local listing's filters, applied to one card from a peer's sync feed."""
    cd = card.get("card_data") if isinstance(card.get("card_data"), dict) else {}
    if search:
        needle = search.lower()
        hay = " ".join(str(x or "") for x in (card.get("name"), card.get("description"))).lower()
        if needle not in hay:
            return False
    if tags:
        card_tags = cd.get("tags") if isinstance(cd.get("tags"), list) else []
        if not set(tags).issubset(set(card_tags)):
            return False
    tee = (cd.get("capabilities") or {}).get("teeDetails") if isinstance(cd.get("capabilities"), dict) else None
    if has_tee is not None and bool(tee) != bool(has_tee):
        return False
    if tee_type:
        if not (isinstance(tee, dict) and str(tee.get("type") or "").lower() == tee_type.lower()):
            return False
    return True


def peer_card_summary(card: Dict[str, Any], peer_name: str) -> Dict[str, Any]:
    """One row of the federated listing. The DID is the only address an agent has, so it travels; the origin is the
    frame the agent LIVES on (a peer that mirrors a third frame's card re-exports that card's own
    federation_metadata), never merely the peer that answered."""
    cd = card.get("card_data") if isinstance(card.get("card_data"), dict) else {}
    fm = cd.get("federation_metadata") if isinstance(cd.get("federation_metadata"), dict) else {}
    home = fm.get("origin_registry_name") if (fm.get("source_registry") or fm.get("first_synced_from")) else None
    return {
        "id": card.get("id", ""),
        "name": card.get("name", "Unnamed Agent"),
        "description": card.get("description"),
        "is_active": card.get("is_active", True),
        "origin_registry_name": home or peer_name,
        "agent_did": cd.get("did") or card.get("agent_did"),
        "updated_at": card.get("updated_at"),
    }


async def query_peer_registry(
    peer: models.PeerRegistry,
    search: Optional[str] = None,
    tags: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
    active_only: bool = True,
    has_tee: Optional[bool] = None,
    tee_type: Optional[str] = None,
    outcomes: Optional[Dict[Any, Any]] = None,
    stats: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Query a single peer registry for agent cards.

    Uses the same endpoint and authentication as the background sync worker:
      - HTTPS peers: mTLS with SPIRE SVID client certificates
      - HTTP  peers: Internal shared-secret headers (Mode 2 fallback)

    Endpoint: GET /api/v1/federation/agent-cards  (proxied through nginx mTLS sidecar)

    Returns:
        List of agent card summary dicts, each with 'origin_registry_name' set.
    """
    logger.info(f"[FEDERATION QUERY] Starting query to peer: {peer.name} (ID: {peer.id})")
    logger.info(f"[FEDERATION QUERY] Peer base_url: {peer.base_url}, status: {peer.status}")

    endpoint_url = ""  # declare for error handler

    try:
        # 2026-05-18: rewrite hostname to the agentvault_identity_network alias
        # via _to_internal_mtls_url. For Frame B operators stored as
        # op-X.frame-b.theprotocol.cloud (DNS alias only on frame_b_identity_network,
        # registry-a not on that net → resolves to public IP → host nginx :8443 SNI
        # passthrough → falls to default upstream → CERTIFICATE_VERIFY_FAILED). The
        # helper rewrites op-*.frame-b.* → op-*.op.* which IS aliased on
        # agentvault_identity_network with cert SAN match. No-op for other URLs.
        from agentvault_registry.routers.teg_integration import _to_internal_mtls_url
        base_url = _to_internal_mtls_url(peer.base_url.rstrip('/'))
        # Use the sync endpoint — already proxied by nginx and authenticated via mTLS
        endpoint_url = f"{base_url}/api/v1/federation/agent-cards"

        # Build query params — no 'since' param means "return recent cards up to limit"
        params: Dict[str, Any] = {"limit": limit}

        # Build httpx client config — mirror federation_sync.py logic exactly
        client_config: Dict[str, Any] = {"timeout": 4.0}
        extra_headers: Dict[str, str] = {}

        if base_url.startswith("https://"):
            # mTLS only — attach SPIRE SVID client certificates
            cert_config = svid_client.get_client_cert_config(target_url=endpoint_url)
            if cert_config:
                client_config.update(cert_config)
                logger.info(f"[FEDERATION QUERY] Using mTLS for query to {peer.name}")
            else:
                logger.error(f"[FEDERATION QUERY] No mTLS certs available for HTTPS peer {peer.name}")
                return []
        else:
            # Mode 2: Internal secret (HTTP on trusted Docker network)
            our_spiffe_id = svid_client.get_spiffe_id() or ""
            fed_secret = os.environ.get(
                "FEDERATION_INTERNAL_SECRET",
                ""
            )
            extra_headers = {
                "X-Federation-Secret": fed_secret,
                "X-Federation-SPIFFE-ID": our_spiffe_id
            }
            logger.info(f"[FEDERATION QUERY] Using internal auth for query to {peer.name} (HTTP)")

        if extra_headers:
            client_config["headers"] = extra_headers

        logger.info(f"[FEDERATION QUERY] GET {endpoint_url} params={params}")

        async with httpx.AsyncClient(**client_config) as client:
            response = await client.get(endpoint_url, params=params)

            logger.info(f"[FEDERATION QUERY] Response: {response.status_code} from {peer.name}")

            if response.status_code != 200:
                logger.error(
                    f"[FEDERATION QUERY] Failed to query peer {peer.name}: "
                    f"HTTP {response.status_code} — {response.text[:300]}"
                )
                # Reachability: keep the WHY, not just the fact. A bare 401 is what hid the
                # frame-c trust-domain gap for seven weeks; the body names the cause.
                if outcomes is not None:
                    outcomes[peer.id] = (False, f"HTTP {response.status_code} — {response.text[:200]}")
                return []

            # Response is List[AgentCardSyncData] — a JSON array
            data = response.json()
            if not isinstance(data, list):
                logger.warning(f"[FEDERATION QUERY] Unexpected response type from {peer.name}: {type(data).__name__}")
                return []

            logger.info(f"[FEDERATION QUERY] Received {len(data)} agent cards from {peer.name}")

            # Map AgentCardSyncData → AgentCardSummary-compatible dicts
            items: List[Dict[str, Any]] = []
            for card in data:
                try:
                    card_id = card.get("id", "")
                    # Validate UUID format
                    try:
                        uuid.UUID(card_id)
                    except (ValueError, AttributeError):
                        logger.warning(f"[FEDERATION QUERY] Skipping card with invalid UUID: {card_id}")
                        continue

                    # Filter by active_only if requested
                    if active_only and not card.get("is_active", True):
                        continue
                    # §DARKSYNC (2026-09-22): a peer's dark (unlisted) agent is not a search result
                    if card.get("unlisted") or any(
                        isinstance(e, dict) and e.get("uri") == "https://theprotocol.cloud/extensions/v1/listing"
                        and (e.get("params") or {}).get("unlisted")
                        for e in ((card.get("card_data") or {}).get("extensions") or [])
                    ):
                        continue

                    if not peer_card_matches(card, search=search, tags=tags, has_tee=has_tee, tee_type=tee_type):
                        continue
                    items.append(peer_card_summary(card, peer.name))
                except Exception as e:
                    logger.warning(f"[FEDERATION QUERY] Error mapping card from {peer.name}: {e}")

            if stats is not None:
                stats["fetched"] = stats.get("fetched", 0) + len(data)
                stats["matched"] = stats.get("matched", 0) + len(items)
            if items:
                logger.info(f"[FEDERATION QUERY] First item: {items[0]}")
            logger.info(f"[FEDERATION QUERY] Successfully queried peer {peer.name}: {len(items)} results")
            if outcomes is not None:
                outcomes[peer.id] = (True, None)
            return items

    except httpx.RequestError as e:
        logger.error(f"[FEDERATION QUERY] Network error querying peer {peer.name}: {type(e).__name__}: {e}")
        if outcomes is not None:
            outcomes[peer.id] = (False, f"{type(e).__name__}: {e}")
        return []
    except Exception as e:
        logger.error(f"[FEDERATION QUERY] Unexpected error querying peer {peer.name}: {type(e).__name__}: {e}")
        if outcomes is not None:
            outcomes[peer.id] = (False, f"{type(e).__name__}: {e}")
        import traceback
        logger.error(f"[FEDERATION QUERY] Traceback: {traceback.format_exc()}")
        return []


async def query_all_peers(
    db: AsyncSession,
    search: Optional[str] = None,
    tags: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
    active_only: bool = True,
    has_tee: Optional[bool] = None,
    tee_type: Optional[str] = None,
    stats: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Query all active peer registries for agent cards.
    
    Args:
        db: Database session
        search: Search term for agent discovery
        tags: List of tags to filter by
        limit: Maximum number of results per registry
        offset: Number of results to skip
        active_only: Only return active agents
        has_tee: Filter for TEE-enabled agents
        tee_type: Filter by TEE type
        
    Returns:
        Aggregated list of agent card summaries from all peers
    """
    # Ensure SVID client is initialized for mTLS (same as federation_sync.py:351-353)
    if not svid_client.is_initialized():
        svid_client.initialize()

    # Get all active peer registries
    stmt = select(models.PeerRegistry).filter(models.PeerRegistry.status == "ACTIVE")
    result = await db.execute(stmt)
    peers = result.scalars().all()
    
    logger.info(f"[FEDERATION QUERY] Found {len(peers)} active peer registries")
    for peer in peers:
        logger.info(f"[FEDERATION QUERY] Peer: {peer.name} - URL: {peer.base_url} - Status: {peer.status}")
    
    all_results = []

    # Reachability (2026-07-24): this fan-out already learns, per peer, whether the corridor
    # works and why not. It used to only log that. Now it is recorded, which is what makes
    # "this peer has never answered" a reportable state instead of a seven-week blind spot.
    outcomes: Dict[Any, Any] = {}

    # Query all peers in parallel — one slow/unreachable peer doesn't block the rest
    import asyncio
    tasks = [
        query_peer_registry(
            peer=peer, search=search, tags=tags, limit=limit,
            offset=offset, active_only=active_only,
            has_tee=has_tee, tee_type=tee_type, outcomes=outcomes, stats=stats
        )
        for peer in peers
    ]
    if stats is not None:
        stats["peers"] = len(peers)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, list):
            all_results.extend(r)

    # Best-effort persistence: discovery must never fail because bookkeeping did.
    try:
        from agentvault_registry.services import federation_reachability
        for peer_id, (ok, err) in outcomes.items():
            await federation_reachability.record_outcome(db, peer_id, ok=ok, error=err)
        # Refresh the gauges here as well, so reachability stays honest even when nobody
        # opens the compliance view.
        await federation_reachability.build_report(db, include_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[FEDERATION QUERY] reachability recording skipped: {exc}")

    logger.info(f"[FEDERATION QUERY] Complete: {len(all_results)} total results from {len(peers)} peers")
    return all_results
