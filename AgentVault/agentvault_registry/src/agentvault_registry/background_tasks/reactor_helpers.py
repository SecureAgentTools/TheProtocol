"""
Shared helpers for reactor handlers.

Multiple reactors call the same downstream operations (e.g., calling TEG
admin endpoints). Centralizing them keeps the per-event reactor modules
thin: extract → dispatch → call helper.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from agentvault_registry.es_ssl_helper import get_es_ssl_context, spire_trust_loaded, svid_stamp

logger = logging.getLogger(__name__)


# §pass63 follow-up (2026-05-22) — silence stale event replays for
# notification-style reactors.
#
# Container restarts trigger EventStore "replay_last_15" on WS subscribe
# AND the polling-backstop initial lookback. For SupplyInvariantBreach /
# BalanceCorrected reactors that means every restart re-emits historic
# events (e.g., the 2026-04-11 breach) as a CRITICAL log + WS toast + email
# as if they just happened — noisy and erodes alert trust.
#
# `is_notification_stale` lets a notification reactor short-circuit when
# the event's application-level timestamp is older than
# REACTOR_NOTIFICATION_MAX_AGE_SEC (default 3600 = 1h, comfortably above
# the auditor's 60s cycle). Fail-open on parse failure — when in doubt,
# dispatch.
#
# IMPORTANT: only apply to notification reactors. Reactors that update
# derived state (balance projections, agent counts, etc.) MUST process
# every event regardless of age — those should not call this helper.
_REACTOR_NOTIFICATION_MAX_AGE_SEC = int(
    os.getenv("REACTOR_NOTIFICATION_MAX_AGE_SEC", "3600")
)


def is_notification_stale(
    event_data: Dict[str, Any],
    *,
    timestamp_fields: Tuple[str, ...] = (
        "detected_at",
        "recorded_at",
        "timestamp",
        "_envelope_timestamp",  # ES-injected fallback (reactor_base._dispatch_event)
    ),
    max_age_sec: Optional[int] = None,
) -> Tuple[bool, Optional[float]]:
    """Return (is_stale, age_seconds_or_None) for an event payload.

    Pulls the first present field from `timestamp_fields`, parses ISO-8601,
    compares to UTC now. Stale = age > `max_age_sec` (or env default).
    Fail-open: parse failures / missing timestamps return (False, None) so
    handlers still dispatch.

    The `_envelope_timestamp` fallback is injected by reactor_base when ES
    delivers an event whose payload `data` lacks its own application-level
    timestamps (e.g., hand-crafted historical compensating events). The
    envelope timestamp is the ES insert time which is always set.
    """
    threshold = max_age_sec if max_age_sec is not None else _REACTOR_NOTIFICATION_MAX_AGE_SEC
    raw_ts = None
    for field in timestamp_fields:
        v = event_data.get(field)
        if isinstance(v, str) and v and v not in ("?", "—"):
            raw_ts = v
            break
    if not raw_ts:
        return False, None
    try:
        s = raw_ts.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        return age > threshold, age
    except (ValueError, TypeError):
        return False, None


# Single shared aiohttp session reused across helpers to avoid per-call
# TCP+TLS handshake. Lazily initialized; closed on registry shutdown is not
# strictly required (event loop cleanup handles it).
_shared_session: Optional[aiohttp.ClientSession] = None
_shared_session_stamp: tuple = ()


def _get_session() -> aiohttp.ClientSession:
    """§MTLSHOPS V0378: _post_federation_admin posts through this session to a peer's federation terminator, which
    verifies client certificates and refuses a bare session at the handshake. The session presents the SVID and is
    rebuilt when the SVID file changes, because it binds its TLS context at construction (the rule of
    teg_integration._get_teg_client)."""
    global _shared_session, _shared_session_stamp
    stamp = svid_stamp()   # §SVIDRACE (V0639): the cert, the key and the bundle; recorded only for a SPIRE context
    if stamp and stamp != _shared_session_stamp and _shared_session is not None:
        try:
            asyncio.get_running_loop().create_task(_shared_session.close())
        except RuntimeError:
            pass
        _shared_session = None
    if _shared_session is None or _shared_session.closed:
        ctx = get_es_ssl_context()
        _shared_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ctx) if ctx is not None else None,
            timeout=aiohttp.ClientTimeout(total=10),
        )
        _shared_session_stamp = stamp if spire_trust_loaded(ctx, stamp) else ()
    return _shared_session


async def _post_teg_admin(
    path: str,
    body: Dict[str, Any],
    *,
    source_label: str,
    op_name: str,
) -> Optional[dict]:
    """POST to TEG with admin auth. Shared scaffolding for cross_teg admin
    endpoints (add-partner, remove-partner, block-agent, unblock-agent).

    Returns parsed JSON on 2xx, None on missing creds / 4xx+ / network error.
    `op_name` appears in the warning log so callers are distinguishable.
    """
    teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080").rstrip("/")
    teg_key = os.getenv("TEG_ADMIN_API_KEY", "")
    if not teg_key:
        logger.warning(
            f"[ReactorHelper:{source_label}] TEG_ADMIN_API_KEY not set — cannot "
            f"call {op_name}"
        )
        return None

    url = f"{teg_url}{path}"
    headers = {"Authorization": f"Bearer {teg_key}", "Content-Type": "application/json"}

    # §2026-06-16 TEG-mTLS Phase 0: present the registry SVID client cert on this hop.
    # TEG_API_BASE_URL is the nginx-teg sidecar (e.g. https://nginx-teg-a:8443) whose
    # `ssl_verify_client on` REJECTS a certless TLS handshake — the old bare-aiohttp
    # session here was failing silently on mainframes. Reuse the registry's pooled,
    # SVID-self-healing httpx client (the same channel the TEG proxy calls already use).
    # The Bearer key is still sent for app-level auth (unchanged) until the unified mTLS
    # dependency lands in Phase 1 — so this change is non-breaking (it only ADDS the cert).
    try:
        from agentvault_registry.routers.teg_integration import _get_teg_client
        resp = await _get_teg_client().post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            text = resp.text[:300]
            logger.warning(
                f"[ReactorHelper:{source_label}] TEG {op_name} returned "
                f"{resp.status_code}: {text}"
            )
            return None
        return resp.json()
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] TEG {op_name} network error: {e}"
        )
        return None


async def remove_partner_on_teg(
    teg_id: str,
    *,
    source_label: str = "reactor",
) -> Optional[dict]:
    """POST {TEG}/api/v1/cross-teg/config/remove-partner.

    Caller logs and proceeds — drift_monitor remains the safety net.
    `source_label` identifies the reactor in shared log lines.
    """
    return await _post_teg_admin(
        path="/api/v1/cross-teg/config/remove-partner",
        body={"teg_id": teg_id},
        source_label=source_label,
        op_name=f"remove-partner({teg_id})",
    )


async def add_partner_on_teg(
    teg_id: str,
    *,
    registry_id: str = "",
    url: str = "",
    source_label: str = "reactor",
) -> Optional[dict]:
    """POST {TEG}/api/v1/cross-teg/config/add-partner.

    Symmetric mirror of `remove_partner_on_teg` for the
    FederationLicenseReinstated path. The TEG endpoint requires `url`; if
    none is in the event payload, BFS lazy-discovery overrides on first
    cross-tx, so a placeholder satisfies validation.
    """
    placeholder_url = url or f"https://{teg_id}.placeholder:8443"
    return await _post_teg_admin(
        path="/api/v1/cross-teg/config/add-partner",
        body={"teg_id": teg_id, "registry_id": registry_id, "url": placeholder_url},
        source_label=source_label,
        op_name=f"add-partner({teg_id})",
    )


async def register_peer_partner_on_teg(db, peer_name: str, *, source_label: str) -> Optional[dict]:
    """Add the ACTIVE peer row `peer_name` names to this frame's TEG partners, as the first fund sent to it used to:
    `teg-<safe name>`, the safe name as registry id, the row's base_url.

    The TEG partner rule (agentvault2-5b's ledgergate3 TEG): a cross-TEG leg runs only with a peer the TEG holds as a
    current partner, and nothing adds one but add-partner. Before it, the TEG added a peer from the target URL of a
    fund sent to it (an operator's genesis funding) and a removed peer came back with its next leg; now this frame
    adds one where it starts or resumes trusting a peer: an operator's provisioning, a quarantine lift, a peer's
    reactivation. Nothing moves. None when the row or the TEG's answer is missing (logged); this frame's next leg to
    the peer adds it too (routers/teg_integration.py, the cross-registry transfer's partner step)."""
    from agentvault_registry.routers.teg_integration import _resolve_peer_target_for_cross_teg_fund
    from agentvault_registry.services.cloud_provisioner import _safe_name

    safe = _safe_name(peer_name or "")
    resolved = await _resolve_peer_target_for_cross_teg_fund(peer_name, db) if safe else None
    if not resolved:
        logger.warning(f"[ReactorHelper:{source_label}] no ACTIVE peer row with a base_url for '{peer_name}': "
                       f"not registered as a TEG partner here")
        return None
    url, _cache_key = resolved
    result = await add_partner_on_teg(f"teg-{safe}", registry_id=safe, url=url, source_label=source_label)
    if result is not None:
        logger.info(f"[ReactorHelper:{source_label}] TEG partner teg-{safe} registered "
                    f"(status={result.get('status', '?')})")
    return result


async def _agent_blocklist_call(
    action: str,
    agent_did: str,
    *,
    reason: str,
    source_label: str,
) -> Optional[dict]:
    """Shared scaffolding for the block/unblock pair. `action` is "block" or
    "unblock"; both endpoints have identical body shape and auth."""
    return await _post_teg_admin(
        path=f"/api/v1/cross-teg/admin/agents/{agent_did}/{action}",
        body={"reason": reason, "actor": source_label},
        source_label=source_label,
        op_name=f"{action}-agent({agent_did})",
    )


async def block_agent_on_teg(
    agent_did: str,
    *,
    reason: str = "AgentSuspended reactor dispatch",
    source_label: str = "reactor",
) -> Optional[dict]:
    """Add DID to local TEG's external blocklist via cross_teg admin endpoint.

    When AgentSuspended fires, the reactor adds the DID so any cross-TEG
    transfer targeting it is refused at the protocol-edge. Idempotent at
    TEG side (returns `already_blocked` if DID is on the list).
    """
    return await _agent_blocklist_call(
        "block", agent_did, reason=reason, source_label=source_label,
    )


async def unblock_agent_on_teg(
    agent_did: str,
    *,
    reason: str = "AgentReinstated reactor dispatch",
    source_label: str = "reactor",
) -> Optional[dict]:
    """Remove DID from local TEG's external blocklist. Mirror of
    `block_agent_on_teg`. Idempotent (returns `not_blocked` if DID not
    on the list).
    """
    return await _agent_blocklist_call(
        "unblock", agent_did, reason=reason, source_label=source_label,
    )


async def _post_federation_admin(
    peer_base_url: str,
    path: str,
    body: Dict[str, Any],
    *,
    source_label: str,
    op_name: str,
) -> Optional[dict]:
    """POST to a peer registry's /api/v1/federation/admin/* endpoint over
    Mode 2 federation auth (X-Federation-Secret + X-Federation-SPIFFE-ID).

    Best-effort — returns None on missing creds / 4xx+ / network error;
    drift_monitor + the local block path are the safety nets.
    """
    secret = os.getenv("FEDERATION_INTERNAL_SECRET", "")
    if not secret:
        logger.debug(
            f"[ReactorHelper:{source_label}] FEDERATION_INTERNAL_SECRET not set "
            f"— cannot call peer {op_name}"
        )
        return None

    try:
        from agentvault_registry.identity.svid_client import svid_client
        our_spiffe_id = svid_client.get_spiffe_id() or ""
    except Exception:
        our_spiffe_id = ""
    if not our_spiffe_id:
        our_spiffe_id = os.getenv("FEDERATION_INTERNAL_SPIFFE_ID", "")
    if not our_spiffe_id:
        logger.debug(
            f"[ReactorHelper:{source_label}] No SPIFFE ID resolvable — cannot "
            f"call peer {op_name}"
        )
        return None

    url = peer_base_url.rstrip("/") + path
    headers = {
        "X-Federation-Secret": secret,
        "X-Federation-SPIFFE-ID": our_spiffe_id,
        "Content-Type": "application/json",
    }
    try:
        async with _get_session().post(url, headers=headers, json=body) as resp:
            if resp.status >= 400:
                text = (await resp.text())[:300]
                logger.info(
                    f"[ReactorHelper:{source_label}] Peer {op_name} returned "
                    f"{resp.status}: {text} (peer={peer_base_url})"
                )
                return None
            return await resp.json()
    except Exception as e:
        logger.info(
            f"[ReactorHelper:{source_label}] Peer {op_name} network error "
            f"({peer_base_url}): {e}"
        )
        return None


async def _post_federation_admin_mtls(
    peer_base_url: str,
    path: str,
    body: Dict[str, Any],
    *,
    source_label: str,
    op_name: str,
) -> Optional[dict]:
    """POST to a peer's /api/v1/federation/admin/* over **mTLS** using THIS
    registry's SPIRE SVID client cert — the exact channel federation_sync uses
    (the peer authenticates Mode-1 via the client cert; NO shared secret). This
    is the production federation auth; the secret-header path (_post_federation_admin)
    is a dev fallback that prod (mTLS-only) cannot use.

    Best-effort: returns None on no-cert / 4xx+ / network error. A 404 from a peer
    that lacks the receiver (or holds no shadow of the op) is an expected no-op."""
    import httpx
    try:
        from agentvault_registry.identity import svid_client
        from agentvault_registry.routers.teg_integration import _to_internal_mtls_url
    except Exception as e:
        logger.warning(f"[ReactorHelper:{source_label}] mTLS import failed for {op_name}: {e}")
        return None
    # Mainframe callers use the internal-alias rewrite (cert-SAN match on the
    # agentvault_identity_network); cloud-op callers dial the parent frame's
    # :8443 federation gateway directly (federation_sync §2026-06-05 pattern).
    base = peer_base_url.rstrip("/")
    if not os.getenv("REGISTRY_NAME", "").startswith("cloud-op-"):
        try:
            base = _to_internal_mtls_url(base)
        except Exception:
            pass
    url = base + path
    client_config: Dict[str, Any] = {"timeout": 12.0}
    if url.startswith("https://"):
        cert_config = svid_client.get_client_cert_config(target_url=url)
        if not cert_config:
            logger.debug(f"[ReactorHelper:{source_label}] no mTLS cert resolvable; skip {op_name}")
            return None
        client_config.update(cert_config)
    try:
        async with httpx.AsyncClient(**client_config) as client:
            resp = await client.post(url, json=body)
            if resp.status_code >= 400:
                logger.info(
                    f"[ReactorHelper:{source_label}] Peer {op_name} returned "
                    f"{resp.status_code}: {resp.text[:200]} (peer={url})"
                )
                return None
            return resp.json()
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.info(f"[ReactorHelper:{source_label}] Peer {op_name} connect/timeout ({url}): {e}")
        return None
    except Exception as e:
        logger.info(f"[ReactorHelper:{source_label}] Peer {op_name} mTLS error ({url}): {e}")
        return None


async def block_agent_on_remote_frames(
    agent_did: str,
    *,
    reason: str = "AgentSuspended reactor cross-frame propagation",
    source_label: str = "reactor",
) -> Dict[str, Any]:
    """Walk ACTIVE peer registries and ask each to block `agent_did` on its
    local TEG via the federation blocklist proxy endpoint.

    Phase 10 #4: closes the gap where AgentSuspendedReactor only blocks the
    LOCAL TEG, leaving peer-frame TEGs unaware of the suspension. In
    shared-EventStore topologies (sandbox), peer reactors handle this
    independently and the calls here are redundant-but-safe (TEG is
    idempotent). In separate-EventStore topologies (production Frame B),
    these calls are load-bearing.

    Returns a per-peer summary suitable for logging:
        {"attempted": N, "successful": M, "results": [...]}
    """
    return await _fanout_blocklist_to_peers(
        action="block", agent_did=agent_did, reason=reason,
        source_label=source_label,
    )


async def unblock_agent_on_remote_frames(
    agent_did: str,
    *,
    reason: str = "AgentReinstated reactor cross-frame propagation",
    source_label: str = "reactor",
) -> Dict[str, Any]:
    """Mirror of `block_agent_on_remote_frames` for unblock."""
    return await _fanout_blocklist_to_peers(
        action="unblock", agent_did=agent_did, reason=reason,
        source_label=source_label,
    )


async def _fanout_blocklist_to_peers(
    *,
    action: str,
    agent_did: str,
    reason: str,
    source_label: str,
) -> Dict[str, Any]:
    """Shared scaffolding for block/unblock fan-out. Walks ACTIVE peers and
    calls each one's federation blocklist proxy in parallel."""
    import asyncio as _asyncio
    try:
        from agentvault_registry.database import get_db_context
        from agentvault_registry.models import PeerRegistry
        from sqlalchemy import select
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] cross-frame fanout setup failed: {e}"
        )
        return {"attempted": 0, "successful": 0, "results": []}

    try:
        async with get_db_context() as db:
            result = await db.execute(
                select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
            )
            peers = result.scalars().all()
            peers_snapshot = [
                {"id": p.id, "name": p.name, "base_url": p.base_url}
                for p in peers if p.base_url
            ]
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] cross-frame peer query failed: {e}"
        )
        return {"attempted": 0, "successful": 0, "results": []}

    if not peers_snapshot:
        return {"attempted": 0, "successful": 0, "results": []}

    body = {"reason": reason, "actor": source_label}
    path = f"/api/v1/federation/admin/agents/{agent_did}/{action}"
    op_name = f"{action}-agent({agent_did[:30]})"

    async def _one_peer(p):
        resp = await _post_federation_admin(
            p["base_url"], path, body,
            source_label=source_label, op_name=f"{op_name}@{p['name']}",
        )
        return {
            "peer_id": p["id"],
            "peer_name": p["name"],
            "ok": resp is not None,
            "status": (resp or {}).get("status"),
            "blocklist_size": (resp or {}).get("blocklist_size"),
        }

    results = await _asyncio.gather(*[_one_peer(p) for p in peers_snapshot])
    successful = sum(1 for r in results if r["ok"])
    logger.info(
        f"[ReactorHelper:{source_label}] cross-frame {action} fanout: "
        f"{successful}/{len(results)} peers OK for agent={agent_did[:40]}"
    )
    return {
        "attempted": len(results),
        "successful": successful,
        "results": results,
    }


async def fanout_operator_rename_to_peers(
    *,
    old_slug: str,
    new_slug: str,
    new_base_url: str = "",
    new_operator_did: str = "",
    source_label: str = "reactor_operator_renamed",
) -> Dict[str, Any]:
    """§2026-06-14 — Walk ACTIVE peer registries and ask each to apply an
    operator IDENTITY rename to ITS OWN local rows (peer_registries +
    agent_cards origin) via `/api/v1/federation/admin/operators/rename`.

    Same shape as `_fanout_blocklist_to_peers`: Mode-2 federation auth,
    parallel, best-effort, idempotent (peers that hold no shadow of the op
    no-op). This is the cross-frame propagation channel for the event-sourced
    rename — each peer mutates only its OWN DB; no direct cross-frame SQL."""
    import asyncio as _asyncio
    try:
        from agentvault_registry.database import get_db_context
        from agentvault_registry.models import PeerRegistry
        from sqlalchemy import select
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] op-rename fanout setup failed: {e}"
        )
        return {"attempted": 0, "successful": 0, "results": []}

    try:
        async with get_db_context() as db:
            result = await db.execute(
                select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
            )
            peers = result.scalars().all()
            peers_snapshot = [
                {"id": p.id, "name": p.name, "base_url": p.base_url}
                for p in peers if p.base_url
            ]
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] op-rename peer query failed: {e}"
        )
        return {"attempted": 0, "successful": 0, "results": []}

    if not peers_snapshot:
        return {"attempted": 0, "successful": 0, "results": []}

    body = {
        "old_slug": old_slug, "new_slug": new_slug,
        "new_base_url": new_base_url or None,
        "new_operator_did": new_operator_did or None,
        "actor": source_label,
    }
    path = "/api/v1/federation/admin/operators/rename"
    op_name = f"op-rename({old_slug}->{new_slug})"

    async def _one_peer(p):
        # mTLS (Mode-1, SVID client cert) — the prod federation channel. NO secret.
        resp = await _post_federation_admin_mtls(
            p["base_url"], path, body,
            source_label=source_label, op_name=f"{op_name}@{p['name']}",
        )
        return {
            "peer_id": p["id"], "peer_name": p["name"],
            "ok": resp is not None,
            "peer_rows": (resp or {}).get("peer_rows"),
            "card_rows": (resp or {}).get("card_rows"),
        }

    results = await _asyncio.gather(*[_one_peer(p) for p in peers_snapshot])
    successful = sum(1 for r in results if r["ok"])
    logger.info(
        f"[ReactorHelper:{source_label}] op-rename fanout: "
        f"{successful}/{len(results)} peers OK ({old_slug}->{new_slug})"
    )
    return {"attempted": len(results), "successful": successful, "results": results}


async def dispatch_supply_breach_alert(
    event_data: dict,
    *,
    source_label: str = "reactor",
) -> None:
    """Fan out a supply-invariant-breach alert to all configured channels:
    1. Registered webhooks subscribed to `supply.invariant_breach` (via
       `WebhookService.emit_event`).
    2. Email to `SUPPLY_ALERT_RECIPIENTS` if configured.

    Each channel is best-effort and isolated: failure in one does not block
    the others. Caller (the reactor) has already logged at CRITICAL level
    before invoking this helper, so log capture is independent of dispatch.
    """
    try:
        from agentvault_registry.database import get_db_context
        from agentvault_registry.services.webhook_service import WebhookService

        async with get_db_context() as db:
            svc = WebhookService()
            count = await svc.emit_event(
                event_type="supply.invariant_breach",
                data=event_data,
                db=db,
            )
            logger.info(
                f"[ReactorHelper:{source_label}] supply.invariant_breach webhook "
                f"dispatched to {count} subscriber(s)"
            )
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] Webhook dispatch failed: {e}"
        )

    try:
        from agentvault_registry.config import settings
        recipients_csv = getattr(settings, "SUPPLY_ALERT_RECIPIENTS", None) or ""
        recipients: List[str] = [
            r.strip() for r in recipients_csv.split(",") if r.strip()
        ]
        if not recipients:
            return
        await _send_supply_breach_email(recipients, event_data)
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] Email dispatch failed: {e}"
        )


async def dispatch_webhook_event(
    event_type: str,
    event_data: dict,
    *,
    source_label: str = "reactor",
    developer_id: Optional[int] = None,
) -> int:
    """Fire registered webhooks for a given event_type via WebhookService.

    `developer_id` (A1, 2026-07-24) scopes delivery to ONE developer's webhooks —
    use it for owner-private events (agent/staking/contract/dispute lifecycle) so
    one tenant's activity never lands in another tenant's webhook. Omit for
    platform-public events (governance, federation, supply).

    Returns the count of webhook subscriptions matched (0 if none registered
    or if event_type isn't in SUPPORTED_EVENTS).
    """
    try:
        from agentvault_registry.database import get_db_context
        from agentvault_registry.services.webhook_service import WebhookService
        async with get_db_context() as db:
            svc = WebhookService()
            count = await svc.emit_event(
                event_type=event_type, data=event_data, db=db,
                developer_id=developer_id,
            )
            logger.info(
                f"[ReactorHelper:{source_label}] {event_type} webhook dispatched to {count} subscriber(s)"
            )
            return count
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] {event_type} webhook dispatch failed: {e}"
        )
        return 0


def local_developer_id(event_data: dict, key: str = "target_developer_id") -> Optional[int]:
    """The developer an owner-private developer event belongs to, on THIS registry, or None.

    §TWOAGENT #34 (2026-09-23): the §TRUSTWIRE bridge feeds a peer frame's events into the same reactors (they carry
    `_foreign_frame_id`), and a developer id is only unique per database: a peer's developer 12 is not ours. So a
    bridged event names no local developer, and its webhooks go to nobody here. Scope with this, never with the raw id.
    """
    if (event_data or {}).get("_foreign_frame_id"):
        return None
    try:
        return int((event_data or {}).get(key))
    except (TypeError, ValueError):
        return None


async def dispatch_webhook_for_agents(
    event_type: str,
    event_data: dict,
    agent_dids: List[str],
    *,
    source_label: str = "endpoint",
) -> int:
    """Owner-scoped webhook fan-out (A1, 2026-07-24): resolve the creator developer
    of each DID and emit the event scoped to each distinct owner. The standard
    primitive for the per-tenant lifecycle events (agent.*, staking.*, contract.*,
    dispute.*) that used to be subscribable-but-never-fired. Best-effort — a
    lookup/dispatch failure logs and never disturbs the calling flow."""
    total = 0
    try:
        from agentvault_registry.database import get_db_context
        from sqlalchemy import text as _text
        dids = [d for d in dict.fromkeys(agent_dids or []) if d]
        if not dids:
            return 0
        async with get_db_context() as db:
            rows = (await db.execute(_text(
                "SELECT DISTINCT creator_developer_id FROM agents WHERE did = ANY(:d) "
                "AND creator_developer_id IS NOT NULL"
            ), {"d": dids})).scalars().all()
        for dev_id in rows:
            total += await dispatch_webhook_event(
                event_type, event_data, source_label=source_label, developer_id=int(dev_id))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ReactorHelper:{source_label}] {event_type} owner-scoped dispatch failed: {e}")
    return total


async def _send_supply_breach_email(recipients: List[str], event_data: dict) -> None:
    """Send the sovereign-themed supply-breach alert via the unified email pipeline."""
    try:
        from agentvault_registry.email_utils import send_themed_email
    except ImportError as e:
        logger.warning(f"[ReactorHelper:Supply] email_utils not available: {e}")
        return

    delta = event_data.get("delta", "?")
    context = {
        "delta": delta,
        "net_supply": event_data.get("net_supply", "?"),
        "circulating": event_data.get("total_circulating", "?"),
        "detected_at": event_data.get("detected_at", "?"),
        "audit_type": event_data.get("audit_type", "?"),
        "auto_lockdown": event_data.get("auto_lockdown", False),
    }
    sent = await send_themed_email(
        subject=f"⚠ SUPPLY INVARIANT BREACH — delta={delta}",
        recipients=recipients,
        template="supply_breach",
        context=context,
        theme="sovereign",
    )
    if sent:
        logger.info(
            f"[ReactorHelper:Supply] Breach alert email dispatched to {len(recipients)} recipient(s)"
        )
    else:
        logger.warning(
            f"[ReactorHelper:Supply] Breach alert email FAILED to dispatch ({len(recipients)} recipient(s))"
        )


# ---------------------------------------------------------------------------
# Reactor batch 2 helpers (Phase 9.3)
# ---------------------------------------------------------------------------


async def get_developer_email(developer_id: int) -> Optional[str]:
    """Look up a developer's email by id. Returns None if not found / DB error.

    Used by reactors #14 (webhook exhausted) and #19 (balance corrected) to
    notify the responsible developer.
    """
    try:
        from agentvault_registry.database import get_db_context
        from agentvault_registry.models import Developer
        from sqlalchemy import select

        async with get_db_context() as db:
            result = await db.execute(
                select(Developer.email).where(Developer.id == developer_id)
            )
            email = result.scalar_one_or_none()
            return email
    except Exception as e:
        logger.warning(f"[ReactorHelper] get_developer_email({developer_id}) failed: {e}")
        return None


async def get_developer_email_for_agent(agent_did: str) -> Optional[str]:
    """Look up the creator developer's email for a given agent DID.

    Used by reactors #15 (slashed) and #16 (bridge expired).
    """
    try:
        from agentvault_registry.database import get_db_context
        from agentvault_registry.models import Agent, Developer
        from sqlalchemy import select

        async with get_db_context() as db:
            result = await db.execute(
                select(Developer.email)
                .join(Agent, Agent.creator_developer_id == Developer.id)
                .where(Agent.did == agent_did)
            )
            email = result.scalar_one_or_none()
            return email
    except Exception as e:
        logger.warning(
            f"[ReactorHelper] get_developer_email_for_agent({agent_did}) failed: {e}"
        )
        return None


async def send_reactor_email(
    *,
    subject: str,
    recipients: List[str],
    template: str,
    context: Dict[str, Any],
    theme: str = "neural",
    source_label: str = "reactor",
) -> bool:
    """Thin wrapper around send_themed_email with consistent reactor logging.

    Returns True on success, False on render/SMTP failure (caller continues —
    webhook fan-out is independent).
    """
    if not recipients:
        return False
    try:
        from agentvault_registry.email_utils import send_themed_email
    except ImportError as e:
        logger.warning(f"[ReactorHelper:{source_label}] email_utils not available: {e}")
        return False
    try:
        sent = await send_themed_email(
            subject=subject,
            recipients=recipients,
            template=template,
            context=context,
            theme=theme,
        )
        if sent:
            logger.info(
                f"[ReactorHelper:{source_label}] {template} email dispatched to "
                f"{len(recipients)} recipient(s)"
            )
        return bool(sent)
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] {template} email FAILED: {e}"
        )
        return False
