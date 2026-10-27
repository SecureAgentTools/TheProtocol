"""Frame data-plane sync — WS3.5 (2026-04-21).

When admin approves (or revokes) a frame via the WS3 bilateral handshake, this
helper pokes the EventStore to register/suspend the corresponding:

  * cross_frame_peers row   — so SF-4 event replication starts/stops
  * federation_operators row — so SF-5 cross-frame votes weight correctly

Both calls are best-effort; a failure is logged + surfaced to the UI as a
"Resync needed" badge but never blocks the invitation lifecycle. The admin
can retry via the `resync-eventstore` endpoint.

Auth: X-Internal-Key (same pattern already used by event_emitter.py for
direct EventStore event POSTs).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import httpx

from agentvault_registry.es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 6.0


def _event_store_base_url() -> str:
    return os.getenv("EVENT_STORE_URL", "http://event-store:8200").rstrip("/")


def _internal_key() -> str:
    # Registry containers receive this as EVENT_STORE_API_KEY (legacy name,
    # still active in docker-compose.production.yml); fall back to the
    # canonical names for dev / other setups.
    return (
        os.getenv("EVENT_STORE_API_KEY")
        or os.getenv("EVENT_STORE_INTERNAL_API_KEY")
        or os.getenv("EVENT_STORE_INTERNAL_KEY")
        or os.getenv("INTERNAL_API_KEY", "")
    )


@dataclass
class SyncResult:
    ok: bool
    detail: str

    def __bool__(self) -> bool:
        return self.ok


async def _post(path: str, body: dict) -> Tuple[bool, str, Optional[dict]]:
    """POST to EventStore admin with internal-key auth. Never raises."""
    url = f"{_event_store_base_url()}{path}"
    key = _internal_key()
    if not key:
        return False, "INTERNAL_API_KEY not configured on registry", None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, verify=get_httpx_verify()) as client:
            r = await client.post(url, json=body, headers={"X-Internal-Key": key})
            if 200 <= r.status_code < 300:
                try:
                    return True, "ok", r.json() if r.text else None
                except Exception:
                    return True, "ok", None
            return False, f"HTTP {r.status_code}: {r.text[:300]}", None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", None


async def _get(path: str) -> Tuple[bool, str, Optional[dict]]:
    url = f"{_event_store_base_url()}{path}"
    key = _internal_key()
    if not key:
        return False, "INTERNAL_API_KEY not configured on registry", None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, verify=get_httpx_verify()) as client:
            r = await client.get(url, headers={"X-Internal-Key": key})
            if 200 <= r.status_code < 300:
                return True, "ok", r.json() if r.text else None
            return False, f"HTTP {r.status_code}: {r.text[:300]}", None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", None


# ─── SF-4: cross-frame peer ───────────────────────────────────────

async def register_cross_frame_peer(
    frame_id: str, event_store_url: str, added_by: Optional[str] = None
) -> SyncResult:
    """UPSERT a cross-frame peer on the local EventStore.

    frame_id: the SPIFFE trust domain (e.g., 'frame-b.theprotocol.cloud')
    event_store_url: the peer's EventStore base URL (NOT the registry URL)
    added_by: actor label (e.g., admin email, 'ws3-approve', 'resync')
    """
    if not frame_id or not event_store_url:
        return SyncResult(False, "frame_id and event_store_url required")
    ok, detail, _ = await _post(
        "/api/v1/admin/cross-frame-peers",
        {"frame_id": frame_id, "url": event_store_url, "added_by": added_by or "ws3-approve"},
    )
    return SyncResult(ok, detail)


async def suspend_cross_frame_peer(frame_id: str) -> SyncResult:
    if not frame_id:
        return SyncResult(False, "frame_id required")
    ok, detail, _ = await _post(f"/api/v1/admin/cross-frame-peers/{frame_id}/suspend", {})
    return SyncResult(ok, detail)


async def list_cross_frame_peers(status: str = "all") -> Tuple[bool, str, Optional[dict]]:
    return await _get(f"/api/v1/admin/cross-frame-peers?status={status}")


# ─── SF-5: federation operator ────────────────────────────────────

async def register_federation_operator(
    spiffe_id: str,
    operator_name: str,
    *,
    bayesian_discount: float,
) -> SyncResult:
    """UPSERT a federation operator row on the local EventStore.

    Idempotent on spiffe_id. Called from WS3 approve after the SPIRE bundle
    is live — ensures cross-frame votes from this frame's agents weight
    correctly per SF-5B.

    SEC-20 (2026-10-17): bayesian_discount has no default. The store's upsert writes it onto the record (an existing one
    too), so the caller passes the peer row's DERIVED trust value (services/bayesian_trust.derived_trust_for), the value
    the trust sync sends; a default of 1.0 was a claim of full trust for a peer nothing was measured about.
    """
    if not spiffe_id or not operator_name:
        return SyncResult(False, "spiffe_id and operator_name required")
    ok, detail, _ = await _post(
        "/api/v1/admin/federation-operators",
        {
            "spiffe_id": spiffe_id,
            "operator_name": operator_name,
            "bayesian_discount": bayesian_discount,
        },
    )
    return SyncResult(ok, detail)


async def suspend_federation_operator_by_spiffe(spiffe_id: str) -> SyncResult:
    """Look up the operator by spiffe_id, then suspend it by id."""
    if not spiffe_id:
        return SyncResult(False, "spiffe_id required")
    # Normalize: ensure spiffe:// prefix
    normalized = spiffe_id.strip().lower()
    if not normalized.startswith("spiffe://"):
        normalized = f"spiffe://{normalized}"
    ok, detail, body = await _get(f"/api/v1/admin/federation-operators/by-spiffe/{normalized}")
    if not ok or not body:
        return SyncResult(False, f"lookup failed: {detail}")
    op_id = body.get("id")
    if not op_id:
        return SyncResult(False, "operator id missing in lookup response")
    ok, detail, _ = await _post(f"/api/v1/admin/federation-operators/{op_id}/suspend", {})
    return SyncResult(ok, detail)


async def list_federation_operators() -> Tuple[bool, str, Optional[dict]]:
    return await _get("/api/v1/admin/federation-operators")
