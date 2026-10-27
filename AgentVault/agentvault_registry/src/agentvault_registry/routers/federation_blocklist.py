"""Cross-frame agent blocklist propagation (Phase 10 #4).

Federation peers reach this endpoint over internal/SPIRE auth and ask us to
add or remove a DID on our LOCAL TEG's external blocklist. The proxy keeps
the TEG admin API key private to each frame — peers never see it.

Why we need this:
  AgentSuspendedReactor blocks the DID on the LOCAL TEG only. In a topology
  where peer frames have SEPARATE EventStores (e.g., production Frame A ↔
  Frame B), the AgentSuspended event on Frame A doesn't reach Frame B's
  reactors, so Frame B's TEG stays unaware of the suspension. A cross-frame
  transfer targeting the suspended DID would still succeed.

  This endpoint is the bridge: Frame A's reactor calls each peer's
  /api/v1/federation/admin/agents/{did}/block over Mode 2 federation auth.
  The peer registry receives, validates federation identity, then proxies to
  its OWN local TEG using its OWN admin key. Same pattern for unblock.

Idempotency:
  TEG's underlying block/unblock endpoints are idempotent (already_blocked /
  not_blocked are 200 OK). Replays are safe.

Sandbox vs production:
  In a shared-EventStore topology (sandbox), every operator's reactor sees
  the AgentSuspended event independently and blocks its own TEG — making
  this endpoint redundant but harmless (TEG is idempotent). The endpoint
  earns its keep on production cross-frame topologies.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import aiohttp  # noqa: F401 (legacy; _proxy_to_local_teg now uses the SVID httpx client)
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status, Security
from pydantic import BaseModel, Field

from ..core.federation_auth import get_federation_identity
from ..es_ssl_helper import get_es_ssl_context, get_httpx_verify, spire_trust_loaded, svid_stamp
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/federation/admin/agents",
    tags=["Federation Blocklist"],
)


class BlocklistBody(BaseModel):
    reason: str = Field("federation peer request", max_length=500)
    actor: str = Field("remote_frame_reactor", max_length=200)


_shared_session: Optional[aiohttp.ClientSession] = None
_shared_session_stamp: tuple = ()


def _get_session() -> aiohttp.ClientSession:
    """§MTLSHOPS V0378: nothing in this router posts through this session today (_proxy_to_local_teg uses the SVID
    httpx client); it is built like reactor_helpers._get_session, so a future caller presents the SVID and follows
    its rotation."""
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


async def _proxy_to_local_teg(
    action: str,
    agent_did: str,
    body: BlocklistBody,
    federation_identity: str,
) -> Dict[str, Any]:
    """Forward to local TEG's cross-teg admin block/unblock endpoint."""
    # §2026-06-17 Phase-4 registry-tail: dial the local TEG over mTLS (SVID) instead of
    # certless aiohttp. The TEG's cross-teg/admin route authorizes via the registry's
    # SPIFFE client cert (resolve_internal_caller) at enforce; the legacy Bearer key is
    # attached ONLY if still configured (transitional) and is ignored by the TEG under
    # mTLS. This also FIXES a latent enforce bug: the old certless aiohttp session could
    # not pass nginx-teg's `ssl_verify_client on`, so block/unblock propagation was failing.
    teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080").rstrip("/")
    teg_key = os.getenv("TEG_ADMIN_API_KEY", "")

    url = f"{teg_url}/api/v1/cross-teg/admin/agents/{seg(agent_did)}/{seg(action)}"
    headers = {"Content-Type": "application/json"}
    if teg_key:
        headers["Authorization"] = f"Bearer {teg_key}"
    payload = {
        "reason": (
            f"federation:{federation_identity[:80]} | {body.reason}"
        )[:500],
        "actor": body.actor[:200],
    }
    try:
        async with httpx.AsyncClient(verify=get_httpx_verify(), timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            text = resp.text[:500]
            if resp.status_code >= 400:
                logger.warning(
                    f"[FedBlocklist] Local TEG {action}({agent_did}) returned "
                    f"{resp.status_code}: {text}"
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Local TEG returned {resp.status_code}: {text}",
                )
            return resp.json()
    except httpx.HTTPError as e:
        logger.warning(
            f"[FedBlocklist] Local TEG {action}({agent_did}) network error: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Local TEG unreachable: {e}",
        )


@router.post("/{agent_did:path}/block")
async def federation_block_agent(
    agent_did: str,
    body: Optional[BlocklistBody] = None,
    request: Request = None,
    federation_identity: str = Security(get_federation_identity),
) -> Dict[str, Any]:
    """Add `agent_did` to the local TEG's external blocklist on behalf of a
    federation peer. Idempotent. Mode 2 federation auth required."""
    if not agent_did:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_did path param required",
        )
    body = body or BlocklistBody()
    logger.info(
        f"[FedBlocklist] Block request from {federation_identity[:80]} for "
        f"agent={agent_did[:60]} reason={body.reason[:60]!r}"
    )
    teg_response = await _proxy_to_local_teg(
        "block", agent_did, body, federation_identity
    )
    return {
        "status": teg_response.get("status", "blocked"),
        "agent_did": agent_did,
        "blocklist_size": teg_response.get("blocklist_size"),
        "federation_identity": federation_identity,
    }


@router.post("/{agent_did:path}/unblock")
async def federation_unblock_agent(
    agent_did: str,
    body: Optional[BlocklistBody] = None,
    request: Request = None,
    federation_identity: str = Security(get_federation_identity),
) -> Dict[str, Any]:
    """Remove `agent_did` from the local TEG's external blocklist on behalf
    of a federation peer. Idempotent. Mode 2 federation auth required."""
    if not agent_did:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_did path param required",
        )
    body = body or BlocklistBody()
    logger.info(
        f"[FedBlocklist] Unblock request from {federation_identity[:80]} for "
        f"agent={agent_did[:60]} reason={body.reason[:60]!r}"
    )
    teg_response = await _proxy_to_local_teg(
        "unblock", agent_did, body, federation_identity
    )
    return {
        "status": teg_response.get("status", "unblocked"),
        "agent_did": agent_did,
        "blocklist_size": teg_response.get("blocklist_size"),
        "federation_identity": federation_identity,
    }
