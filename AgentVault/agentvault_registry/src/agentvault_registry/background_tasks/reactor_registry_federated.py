"""
Reactor: RegistryFederated → policy-hash refresh + webhook fan-out
===================================================================
`POST /federation/admission/{id}/complete` activates a peer registry and
emits `RegistryFederated` (federation_admission.py:262-317). This reactor
pre-warms the federation by:

1. **Refetching the peer's authoritative policy hash** via
   `GET /api/v1/federation/policy-compliance` (the new mTLS-gated
   federation endpoint added in Phase 9). If the value differs from the
   admission-time hash, update `FederatedRegistryCompliance.policy_hash`
   so subsequent compliance polls don't immediately fire drift.
2. **Webhook fan-out** (`federation.peer_added`) — single canonical
   federation lifecycle event for integrators.

Intraregistry consequences (Pattern C — DB write + side effects):
- Updates `FederatedRegistryCompliance.policy_hash` and bumps
  `last_poll_at` if the refresh succeeds.
- BFS topology (`_compute_trusted_registries`) reads from DB on every
  cross-tx, so no cache invalidation needed — the next cross-tx sees
  the fresh peer record naturally.
- Idempotent: hash refresh is read-modify-write on a unique compliance
  row; replay just re-confirms the same value.
"""
import asyncio
import logging
import os
import ssl
from datetime import datetime, timezone
from typing import Optional, Tuple

import aiohttp
from sqlalchemy import select

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event

logger = logging.getLogger(__name__)


def _build_mtls_ssl_context() -> Optional[ssl.SSLContext]:
    """Build an SSL context using SPIRE SVID certs for outbound mTLS to peer.

    Mirrors the pattern in event_emitter._build_ssl_context. Returns None
    if certs aren't on disk (tested-allowed plain HTTP fallback for sandbox).
    """
    cert_dir = os.getenv("SVID_CERT_DIR", "/certs")
    cert = os.path.join(cert_dir, "svid.0.pem")
    key = os.path.join(cert_dir, "svid.0.key")
    bundle = os.path.join(cert_dir, "bundle.0.pem")
    if not (os.path.exists(cert) and os.path.exists(key) and os.path.exists(bundle)):
        return None
    try:
        ctx = ssl.create_default_context(cafile=bundle)
        try:
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)  # §BATCH7: + public roots (eb's class)
        except Exception:
            pass
        ctx.load_cert_chain(cert, key)
        return ctx
    except Exception as e:
        logger.warning(f"[Reactor:RegistryFederated] SSL ctx build failed: {e}")
        return None


async def _fetch_peer_policy_hash(peer_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Call peer's /api/v1/federation/policy-compliance to fetch fresh hash.

    Returns (policy_hash, error). Either field may be set on success/failure
    respectively. Uses SPIRE mTLS for HTTPS, falls back to internal Mode 2
    headers for HTTP (Docker network, sandbox).
    """
    url = peer_url.rstrip("/") + "/api/v1/federation/policy-compliance"
    headers = {}
    ssl_ctx = None
    if url.startswith("https://"):
        ssl_ctx = _build_mtls_ssl_context()
    else:
        # Internal HTTP — use Mode 2 federation auth headers (mirrors
        # compliance_poller's pattern: shared secret from env + this
        # registry's SPIFFE ID from svid_client).
        secret = os.getenv("FEDERATION_INTERNAL_SECRET", "")
        if secret:
            headers["X-Federation-Secret"] = secret
            try:
                from agentvault_registry.identity.svid_client import svid_client
                our_spiffe_id = svid_client.get_spiffe_id() or ""
            except Exception:
                our_spiffe_id = ""
            if not our_spiffe_id:
                # Last-resort fallback for sandbox without SVID
                our_spiffe_id = os.getenv("FEDERATION_INTERNAL_SPIFFE_ID", "")
            if our_spiffe_id:
                headers["X-Federation-SPIFFE-ID"] = our_spiffe_id

    try:
        connector = aiohttp.TCPConnector(ssl=ssl_ctx) if ssl_ctx else None
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as sess:
            async with sess.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    text = (await resp.text())[:200]
                    return None, f"HTTP {resp.status}: {text}"
                body = await resp.json()
                ph = body.get("policy_hash") or body.get("hash")
                return ph, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def _refresh_compliance_row(peer_id: int, fresh_hash: str) -> None:
    """Update FederatedRegistryCompliance.policy_hash if it differs from
    the admission-time value. Idempotent."""
    try:
        from agentvault_registry.database import get_db_context
        from agentvault_registry.models import FederatedRegistryCompliance

        async with get_db_context() as db:
            result = await db.execute(
                select(FederatedRegistryCompliance).where(
                    FederatedRegistryCompliance.peer_registry_id == peer_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                logger.warning(
                    f"[Reactor:RegistryFederated] No compliance row for peer={peer_id}"
                )
                return
            now = datetime.now(timezone.utc)
            row.last_poll_at = now
            if fresh_hash and row.policy_hash != fresh_hash:
                logger.info(
                    f"[Reactor:RegistryFederated] peer={peer_id} hash refreshed: "
                    f"{row.policy_hash[:12]}… → {fresh_hash[:12]}…"
                )
                row.policy_hash = fresh_hash
            await db.commit()
    except Exception as e:
        logger.warning(
            f"[Reactor:RegistryFederated] DB refresh failed for peer={peer_id}: {e}"
        )


class RegistryFederatedReactor(EventStoreReactor):
    event_type = "RegistryFederated"
    leader_key = "reactor_registry_federated"
    name = "RegistryFederated"

    async def handle_event(self, event_data: dict) -> None:
        peer_id_raw = event_data.get("peer_registry_id")
        peer_url = event_data.get("peer_url") or ""
        peer_name = event_data.get("peer_name", "?")

        logger.info(
            f"[Reactor:{self.name}] peer={peer_name} (id={peer_id_raw}) "
            f"url={peer_url} — fanning out"
        )

        # Side effect 1: webhook fanout (always fires)
        await dispatch_webhook_event(
            event_type="federation.peer_added",
            event_data=event_data,
            source_label=self.name,
        )

        # Side effect 2: pre-warm peer policy hash. Only runs if peer_url
        # was in the event payload.
        if not peer_url or peer_id_raw is None:
            return
        try:
            peer_id = int(peer_id_raw)
        except (TypeError, ValueError):
            return

        fresh_hash, err = await _fetch_peer_policy_hash(peer_url)
        if err is not None:
            logger.info(
                f"[Reactor:{self.name}] Peer policy fetch failed for "
                f"peer={peer_name}: {err} (ok — drift_monitor is the safety net)"
            )
            return
        if fresh_hash:
            await _refresh_compliance_row(peer_id, fresh_hash)


_instance: Optional[RegistryFederatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = RegistryFederatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
