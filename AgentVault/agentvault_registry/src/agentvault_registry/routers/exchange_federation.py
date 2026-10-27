"""
AGORA PASSPORT — venue-side federation endpoints (peer-mTLS, 2026-06-12).

The agent's HOME registry calls these over the federation channel (same gate
class as canary-fire / the GCC relay): the peer registry IS the voucher —
require_peer_registry_identity authenticates the registry, the home has
already authenticated its agent. Flag: EXCHANGE_PASSPORT_ENABLED.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.core.federation_auth import require_peer_registry_identity
from agentvault_registry.database import get_db
from agentvault_registry.services import exchange_passport as passport
from agentvault_registry.services import exchange_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/federation", tags=["exchange-federation"])


class FederatedOrderRequest(BaseModel):
    agent_did: str = Field(..., max_length=120)
    listing: str = Field(..., max_length=64)
    side: str = Field("buy", pattern="^(buy|sell)$")
    qty: int = Field(..., gt=0)
    price: str = Field(..., description="decimal string (limit only)")
    dev_card: Optional[Dict[str, Any]] = Field(default=None, description="home-signed DevCard envelope (pushed consent)")


class FundedNotice(BaseModel):
    order_id: str
    sent_amount: Optional[str] = None
    send_tx_id: Optional[str] = None
    note: Optional[str] = None


@router.post("/agora-order", summary="Relay a federated agent's order (peer registries only)")
async def federated_order(
    body: FederatedOrderRequest,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return await passport.accept_federated_order(db, peer_spiffe, body.model_dump())
    except svc.ExchangeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


class FederatedVoteRequest(BaseModel):
    proposal_id: str = Field(..., max_length=36)
    voter_did: str = Field(..., max_length=120)
    in_favor: bool
    reason: Optional[str] = Field(default=None, max_length=255)


@router.post("/agora-vote", summary="Relay a federated holder's vote (peer registries only)")
async def federated_vote(
    body: FederatedVoteRequest,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    The voter's home registry relays a federated holder's vote to the listing's home market. The relaying frame's
    identity is recorded as the voter's registry, and the vote is checked against this market's frozen snapshot.
    Peer registries only (mTLS).

    \f
    §2026-06-22 cross-frame governance: the voter's HOME registry relays here (the listing's
    home market). peer_spiffe = the home frame's identity → stamped as voter_registry_id. The
    vote is validated against this market's frozen snapshot. Mirrors /agora-order.
    """
    try:
        return await passport.accept_federated_vote(db, peer_spiffe, body.model_dump())
    except svc.ExchangeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/agora-order-funded", summary="Funding notice for a relayed order (informational)")
async def federated_order_funded(
    body: FundedNotice,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    # The sweeper settles against gateway solvency regardless; this notice is
    # the audit breadcrumb tying home-side send → venue order.
    logger.info(
        "[AGORA-passport] funded-notice from %s: order=%s sent=%s tx=%s",
        peer_spiffe, body.order_id, body.sent_amount, body.send_tx_id,
    )
    return {"ok": True, "order_id": body.order_id, "note": "sweeper opens the order when gateway solvency covers it"}


# ═══ §PASSPORTSELL P1 (2026-08-22) — read-only views for the home's fill poller ═══

class FederatedOrderStatusRequest(BaseModel):
    agent_did: str = Field(..., max_length=120)
    order_ids: list[str] = Field(..., min_length=1, max_length=50)


@router.post("/agora-order-status", summary="Read a federated agent's order status (peer registries only)")
async def federated_order_status(
    body: FederatedOrderStatusRequest,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Batched and read-only, scoped to the vouched agent: the status of its orders on this market. A passport buy's
    200 means accepted, not filled; this is where the home learns of a fill. Peer registries only (mTLS).

    \f
    Batched, read-only, scoped to the vouched agent_did. The truth source for the
    home side's fill-tracking (§PASSPORTSELL): a passport buy's 200 is acceptance, not
    a fill — this is where a fill becomes a fact the home may act on.
    """
    try:
        return await passport.federated_order_status(db, peer_spiffe, body.model_dump())
    except svc.ExchangeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


class FederatedCertificateRequest(BaseModel):
    agent_did: str = Field(..., max_length=120)
    symbol: str = Field(..., max_length=16)


@router.post("/agora-certificate", summary="Sign a federated holder's holding certificate (peer registries only)")
async def federated_certificate(
    body: FederatedCertificateRequest,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    The market signs a holding certificate for its own register: a passport buy lands the points here, so the
    certificate is issued here. 404 while the relayed order has not filled yet. Peer registries only (mTLS).

    \f
    §CERTEVERYBUY: the market signs for its OWN register.

    A passport buy lands the points here, so the certificate has to be minted
    here: the buyer's home registry holds no such position and must not sign a
    claim about books it does not keep. 404 while the relayed order has not
    filled yet — the home polls, and "not yet" is an honest answer.
    """
    try:
        return await passport.federated_certificate(db, peer_spiffe, body.model_dump())
    except svc.ExchangeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


class FederatedPortfolioRequest(BaseModel):
    agent_did: str = Field(..., max_length=120)


@router.post("/agora-portfolio", summary="Read a federated agent's market holdings (peer registries only)")
async def federated_portfolio(
    body: FederatedPortfolioRequest,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Read-only market positions of the vouched agent: the source for rebuilding the home's holdings after a restart.
    Peer registries only (mTLS).

    \f
    Read-only market positions for the vouched agent: the restart-proof rebuild
    source for the home side's holdings ledger (§PASSPORTSELL).
    """
    try:
        return await passport.federated_portfolio(db, peer_spiffe, body.model_dump())
    except svc.ExchangeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
