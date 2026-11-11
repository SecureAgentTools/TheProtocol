"""
OWL25: Federation Dispute Settlement Router
============================================
Sovereign Settlement Protocol endpoints for cross-registry dispute compensation.

Endpoints:
1. POST /slash-request   — Receives request from origin registry, auto-slashes local defendant
2. POST /slash-confirmation: receives confirmation from defendant's registry, pays the local complainant from this
   registry's payout funding (a transfer, never an issuance)
3. POST /settlements/{id}/close (V0660 (k)): an administrator closes a settlement no peer holds
"""

import logging
import uuid
import httpx
from ..es_ssl_helper import get_httpx_verify  # noqa: F401 (V0658 (k): the TEG moves are services/slash_order's now)
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException, status, Security
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from agentvault_registry.database import get_db
from agentvault_registry.models import Agent, CrossRegistrySettlement, PeerRegistry, Developer
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.config import settings
from agentvault_registry.identity import svid_client
from agentvault_registry import security
from agentvault_registry.core.federation_auth import get_federation_identity
from agentvault_registry.core import settlement_origin as _origin   # V0660 (k): the end states of a settlement
# D6-060 (2026-10-25): a slash or a settlement message names the unit of the registry that writes it (the defendant's home
# slashes in its own unit, the origin pays the complainant in its own), never a literal AVT: EU and ASIA settle in ECU and ACU.
from agentvault_registry.core.frame_currency import frame_currency
# TITANIUM VAULT D3: Settlement Saga integration
from agentvault_registry.services.settlement_saga import get_settlement_saga, SAGA_TIMEOUT_HOURS
from datetime import timedelta
from agentvault_registry.core.log_identity import email_for_log   # V0653 (am) item 7: no address in a log

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/federation/disputes",
    tags=["Federation Disputes"]
)


# --- SF-5A: Bayesian Discount Computation ---

async def _update_peer_trust_metrics(
    db: AsyncSession,
    peer_registry_url: str,
    outcome: str,  # "settled", "failed", "rejected"
) -> None:
    """
    Record a dispute the peer LOST: on the complainant's registry, the defendant's registry confirmed it slashed its
    agent ("settled"). One negative observation through BayesianTrustService (the trust value is then derived from the
    record, services/bayesian_trust.derived_trust).

    SEC-20 (2026-10-17): nothing else is evidence about a peer, so any other outcome records nothing. The defendant's
    registry used to record here too: an administrator's approval of the peer's slash request counted a lost dispute
    against the PEER (whose claim was upheld), and a rejection or an approval that slashed nothing counted a clean
    interaction for it, so an administrator's decision on a request moved the peer's trust value either way. The
    decision is about this registry's own agent, not about the peer.
    """
    if outcome != "settled":
        logger.debug(f"SF-5A: outcome {outcome!r} is not a dispute the peer lost; no trust observation")
        return
    peer_result = await db.execute(
        select(PeerRegistry).where(
            PeerRegistry.base_url == peer_registry_url,
            PeerRegistry.status == "ACTIVE"
        )
    )
    peer = peer_result.scalar_one_or_none()
    if not peer:
        logger.debug(f"No active peer found for URL {peer_registry_url}, skipping trust update")
        return

    # 🔴 ONE MODEL, ONE IMPLEMENTATION. This function used to carry its own formula,
    # `1 - lost/(total + PRIOR)`, while services/bayesian_trust.py carried a Beta(a,b) point
    # estimate for the same column on the same rows. Two formulas writing one field is the shape
    # where the answer depends on which code path happened to touch it last. The service is the
    # model; this is a call site.
    from ..services.bayesian_trust import get_bayesian_trust_service
    await get_bayesian_trust_service().record_interaction(
        db, peer.id, success=(outcome != "settled")
    )
    logger.info(
        f"SF-5A: Peer '{peer.name}' trust updated via BayesianTrustService "
        f"(outcome={outcome}, success={outcome != 'settled'})"
    )


# --- Request/Response Models ---

class SlashRequest(BaseModel):
    settlement_id: str = Field(..., max_length=200)
    dispute_id: int
    ruling: str = Field(..., max_length=100)
    amount: int = Field(..., gt=0)
    complainant_did: str = Field(..., max_length=120)
    defendant_did: str = Field(..., max_length=120)
    origin_registry_url: str = Field(..., max_length=500)
    callback_url: str = Field(..., max_length=500)


class SlashConfirmation(BaseModel):
    settlement_id: str
    status: str  # "slashed" or "failed"
    amount: int
    slash_event_id: str = ""
    slash_tx_id: str = ""
    error_message: str = ""


class SettlementApproveBody(BaseModel):
    """Optional body for approve/reject — admin can attach a reason note (S15, 2026-05-06)."""
    reason: str | None = Field(None, max_length=500, description="Admin note explaining decision")


class SettlementCloseBody(BaseModel):
    """V0660 (k): closing a settlement needs the administrator's reason; it is kept on the row and in the audit log."""
    reason: str = Field(..., min_length=1, max_length=500, description="Why the settlement is closed")

    @field_validator("reason")
    @classmethod
    def _reason_has_words(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("a reason is required")
        return v.strip()


# V0660 (k): a confirmation never claims a settlement that is completed, being compensated, or ended without a peer
# holding it (core/settlement_origin.ENDED): the claim excluded only SETTLED and COMPENSATING, so a confirmation would
# have paid a closed settlement.
UNCLAIMABLE = ("SETTLED", "COMPENSATING", *_origin.ENDED)
# A settlement an administrator may not close: it moved money, is moving it, or is closed already. Nor one a peer
# holds (its defendant_registry_url is set): that home may still slash and confirm.
NOT_CLOSABLE = ("SETTLED", "COMPENSATING", "SLASHED", "SLASHING", _origin.CLOSED)


# V0660 (k) review: the states in which no slash request reached any peer (none went out, or every peer refused it):
# these close without asking the event store. Any other closable settlement closes only after it shows no slash.
NO_REQUEST_TAKEN = (_origin.NOT_DELIVERED, _origin.REFUSED)


def closable(s) -> bool:
    """Whether close_settlement takes this settlement (the console offers Close only where it does)."""
    return (s.status not in NOT_CLOSABLE) and not (getattr(s, "defendant_registry_url", "") or "").strip()


# --- The addresses a slash route names are its caller's own ---

def _norm_addr(url) -> str:
    return (url or "").strip().rstrip("/").lower()


def _is_under(url, base) -> bool:
    u, b = _norm_addr(url), _norm_addr(base)
    return bool(b) and (u == b or u.startswith(b + "/"))


def _bind_slash_request_to_caller(request: "SlashRequest", presenter: str, origin_peer) -> None:
    """A slash request names its origin and the callback by address; a peer may name only itself. The origin must be the
    peer row of the registry presenting the request (its ACTIVE row at origin_registry_url, core/federation_auth
    .identity_is_peer_row), and the callback must go back under that origin's address. This frame's own registry
    (its own trust domain, a frame-class identity) may name another peer. 403 otherwise, before anything is recorded."""
    from agentvault_registry.core.federation_auth import identity_is_peer_row, is_own_frame_identity
    if is_own_frame_identity(presenter):
        return
    if origin_peer is None or not identity_is_peer_row(presenter, origin_peer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A slash request names its own registry as the origin: origin_registry_url is not the address of "
                   "the registry presenting it",
        )
    if not _is_under(request.callback_url, request.origin_registry_url):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A slash request's callback goes back to its origin: callback_url is not under origin_registry_url",
        )


def _bind_confirmation_to_caller(confirmation: "SlashConfirmation", settlement, presenter: str, defendant_peer) -> None:
    """A slash confirmation comes from the registry this settlement's slash request was sent to (the peer row at the
    settlement's defendant_registry_url, recorded before the request went out: crud_disputes
    ._process_cross_registry_compensation), or from this frame's own registry; and it reports at most the amount the
    settlement requested. 403 or 422 otherwise, before the settlement is claimed and before anyone is paid."""
    from agentvault_registry.core.federation_auth import identity_is_peer_row, is_own_frame_identity
    if not is_own_frame_identity(presenter) and not identity_is_peer_row(presenter, defendant_peer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the registry this settlement's slash request was sent to may confirm it",
        )
    if confirmation.status == "slashed" and confirmation.amount > settlement.requested_amount:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A slash confirmation cannot report more than the settlement requested "
                   f"({settlement.requested_amount})",
        )


# --- V0658 (k): what a slash drained, in the settlement's words ---

def _slash_outcome(drained, requested) -> Tuple[int, str, str, int]:
    """(units slashed, the slash type, the TEG's words for the moves it did not confirm, the units it did not confirm)
    for a drain of this registry's slash order (services/slash_order). A slash amount is a whole number of units."""
    moved = int(drained.moved)
    if moved >= int(requested):
        kind = "full"
    elif moved > 0:
        kind = "partial"
    elif drained.failed:
        kind = "unconfirmed"
    else:
        kind = "insufficient"
    return moved, kind, drained.teg_error, int(drained.unconfirmed)


def _partial_words(drained, moved: int, requested) -> str:
    """The record of a partial slash: what the order took, from which steps, and the shortfall."""
    words = (f"Partial slash: {moved}/{requested} {frame_currency()} after the slash order ({drained.sources()}): "
             f"shortfall {int(drained.shortfall)}.")
    if drained.failed:
        words += f" Not confirmed by the TEG: {drained.teg_error}."
    if drained.cascade_on and drained.cascade_refused:
        words += f" No cascade: {drained.cascade_refused}."
    return words


# --- Endpoint 1: Receive Slash Request (defendant's home registry) ---

@router.post("/slash-request", response_model=Dict[str, Any])
async def receive_slash_request(
    request: SlashRequest,
    federation_identity: str = Security(get_federation_identity),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    This registry is the defendant's home. It records a settlement for a slash the complainant's home registry
    requests (a replayed request answers 409). When the requesting peer allows auto-slash and the amount is within
    its threshold, the amount is drained in this registry's slash order (its bond, its locked units, its liquid units,
    and the owner's other agents where the order lists the cascade) into this registry's treasury (the whole amount,
    or what the order holds) and the origin is called back; otherwise the settlement waits for an administrator's
    approval.
    Auth: the origin registry's federation identity (mTLS). The request names its own registry: `origin_registry_url`
    must be the address of the registry presenting it, and `callback_url` must lie under it (403 otherwise).

    \f
    Receive a slash request from the origin registry.
    
    This registry is the DEFENDANT'S HOME. We have jurisdiction over
    the defendant's AVT. We verify the request, auto-slash, and callback.
    
    Flow:
    1. Verify defendant exists locally
    2. Verify ruling is valid
    3. Drain this registry's slash order (services/slash_order: bond, locks, liquid, and the cascade where the order
       lists it), each step's capacity read from the TEG, each move to the treasury on the TEG (V0658 (k))
    4. Emit DisputeSlash event to EventStore (an audit record under the single writer)
    5. Callback origin registry with confirmation
    """
    logger.info(
        f"Received slash request: settlement={request.settlement_id}, "
        f"dispute={request.dispute_id}, defendant={request.defendant_did}, "
        f"amount={request.amount}"
    )
    
    # Step 0: Validate callback_url against known peer registry base URLs (SSRF prevention)
    from agentvault_registry.input_validators import validate_webhook_url
    try:
        # literal checks only: the peer allowlist below is the authority, and a peer may sit on our own network
        validate_webhook_url(request.callback_url, resolve=False)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid callback URL: {e}"
        )
    # Verify callback_url is under a registered peer's base URL
    peer_urls_result = await db.execute(
        select(PeerRegistry.base_url).where(PeerRegistry.status == "ACTIVE")
    )
    known_peer_urls = [row[0].rstrip("/") for row in peer_urls_result.all()]
    # V0653 (am) item 9: under a peer's base URL with a '/' boundary (_is_under, as the slash routes check their caller's
    # own addresses): a bare prefix let https://peer.example.evil.test/... pass for the peer https://peer.example
    if not any(_is_under(request.callback_url, p) for p in known_peer_urls):
        logger.warning(
            f"Callback URL {request.callback_url} does not match any known peer. "
            f"Known peers: {known_peer_urls}"
        )
        # §MCPTEST30 V0639: the answer names what it compared, so the next mismatch names itself (dispute 50: an origin
        # naming its internal proxy, refused by every peer with the bare sentence). V0653 (am) item 9: the address (host
        # and port, never a path or a user part), since the '/' boundary also refuses a matching host on another port
        from urllib.parse import urlsplit

        def _address(u):
            netloc = urlsplit(u).netloc.rsplit("@", 1)[-1]
            return netloc.lower() or "(none)"
        _cb_addr = _address(request.callback_url)
        _peer_addrs = sorted({_address(p) for p in known_peer_urls})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Callback URL must belong to a registered peer registry: its address {_cb_addr} is under no "
                    f"active peer's base URL (active peer addresses: {', '.join(_peer_addrs) or 'none'})")
        )

    # Step 1: Verify defendant is a local agent
    defendant_result = await db.execute(
        select(Agent).where(Agent.did == request.defendant_did)
    )
    defendant = defendant_result.scalar_one_or_none()

    if not defendant:
        logger.warning(f"Defendant {request.defendant_did} not found locally")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Defendant is not registered on this registry"
        )
    
    # Step 2: Verify ruling
    if request.ruling != "IN_FAVOR_OF_COMPLAINANT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ruling for slash: {request.ruling}"
        )
    
    if request.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slash amount must be positive"
        )
    
    # Step 2b: OWL25 Phase 3 — Check auto-slash threshold for this peer
    peer_result = await db.execute(
        select(PeerRegistry).where(
            PeerRegistry.base_url == request.origin_registry_url,
            PeerRegistry.status == "ACTIVE"
        )
    )
    origin_peer = peer_result.scalar_one_or_none()

    # D6-801 (wave 6, 2026-10-17): no slash with a registry this one holds in quarantine, soft quarantine or
    # blacklisted: neither the registry presenting the request nor the origin it names (a row of any status). Asked
    # before the settlement is recorded and before the defendant's units move; 503 when the state cannot be read.
    from agentvault_registry.services.federation_license_gate import assert_federation_peer_not_quarantined
    await assert_federation_peer_not_quarantined(db, presenter=federation_identity,
                                                 peer_urls=(request.origin_registry_url,), context="slash_request")

    # Option D-light Phase D6 (2026-04-21): if the origin peer exists, verify
    # its federation license is active. A suspended/revoked origin registry
    # must not be allowed to initiate new slashes against our local defendants.
    if origin_peer is not None:
        from agentvault_registry.services.federation_license_gate import (
            assert_peer_license_active, resolve_peer_operator_did,
        )
        origin_operator_did = await resolve_peer_operator_did(db, origin_peer)
        if origin_operator_did:
            await assert_peer_license_active(
                db=db,
                operator_did=origin_operator_did,
                context="slash_request",
                actor_registry_did=origin_operator_did,
            )

    # The origin and the callback the request names are the caller's own (a peer names only itself), before anything
    # is recorded: the origin's row decides the auto-slash below, and the callback is called with this registry's SVID.
    _bind_slash_request_to_caller(request, federation_identity, origin_peer)

    auto_approved = False
    if origin_peer and origin_peer.auto_slash_enabled:
        if request.amount <= origin_peer.auto_slash_max_avt:
            auto_approved = True
            logger.info(
                f"Auto-slash APPROVED for peer '{origin_peer.name}': "
                f"{request.amount} AVT <= threshold {origin_peer.auto_slash_max_avt} AVT"
            )
        else:
            logger.info(
                f"Auto-slash DENIED for peer '{origin_peer.name}': "
                f"{request.amount} AVT > threshold {origin_peer.auto_slash_max_avt} AVT. "
                f"Requires admin approval."
            )
    elif origin_peer and not origin_peer.auto_slash_enabled:
        logger.info(
            f"Auto-slash DISABLED for peer '{origin_peer.name}'. "
            f"All slash requests require admin approval."
        )
    else:
        # Unknown peer — require admin approval (do NOT auto-slash without trust)
        auto_approved = False
        logger.warning(
            f"Slash request from unknown peer URL {request.origin_registry_url}. "
            f"Requires admin approval (no peer config found)."
        )
    
    # Step 3: Create local settlement record for tracking
    initial_status = "SLASHING" if auto_approved else "PENDING_ADMIN_APPROVAL"
    settlement = CrossRegistrySettlement(
        id=request.settlement_id,
        dispute_id=request.dispute_id,
        origin_registry_url=request.origin_registry_url,
        defendant_registry_url=str(settings.BASE_URL),
        complainant_did=request.complainant_did,
        defendant_did=request.defendant_did,
        requested_amount=request.amount,
        slashed_amount=0,
        minted_amount=0,
        status=initial_status,
        ruling=request.ruling,
        # S2 (2026-05-06): evidence_hash column dropped via migration 0030.
        callback_url=request.callback_url,
        # TITANIUM VAULT D3: Saga state tracking
        saga_state="INITIATED",
        saga_timeout_at=datetime.now(timezone.utc) + timedelta(hours=SAGA_TIMEOUT_HOURS),
        saga_last_step_at=datetime.now(timezone.utc),
        saga_retry_count=0
    )
    db.add(settlement)
    # CLAIM the settlement id BEFORE any money moves (2026-07-24 $-audit): a replayed
    # slash-request trips the PK HERE — clean 409 — instead of slashing the defendant a
    # second time and only then colliding at the tail commit.
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Settlement {request.settlement_id} already received (duplicate slash request)"
        )

    # If NOT auto-approved, park it for admin review
    if not auto_approved:
        peer_name = origin_peer.name if origin_peer else "unknown"
        threshold = origin_peer.auto_slash_max_avt if origin_peer else 0
        settlement.error_message = (
            f"Awaiting admin approval. Peer '{peer_name}' auto-slash threshold: "
            f"{threshold} {frame_currency()}, requested: {request.amount} {frame_currency()}."
        )
        await db.commit()
        logger.info(
            f"Settlement {request.settlement_id} parked as PENDING_ADMIN_APPROVAL "
            f"(amount {request.amount} exceeds threshold {threshold} for peer '{peer_name}')"
        )
        return {
            "settlement_id": request.settlement_id,
            "status": "pending_admin_approval",
            "slash_type": "awaiting_approval",
            "requested_amount": request.amount,
            "slashed_amount": 0,
            "shortfall": request.amount,
            "slash_tx_id": "",
            "defendant_new_balance": defendant.liquid_balance,
            "message": (
                f"Slash request for {request.amount} {frame_currency()} requires admin approval. "
                f"Auto-slash threshold for this peer is {threshold} {frame_currency()}."
            )
        }
    
    # Step 4: Auto-slash. V0658 (k): the request drains this registry's slash order (services/slash_order, the order a
    # local ruling drains: bond, then locks, then liquid by default, and a cascade to the owner's other agents where
    # the order lists one), each step's capacity read from the TEG, each move to the treasury through the TEG's
    # treasury receive under its own key. It took only the defendant's cached liquid balance before. The defendant's
    # own liquid move keeps the key it always had (dispute-slash-<settlement>), and its D6-441 rule holds for every
    # move: a lost answer is asked once more under the same key, and a move the TEG did not confirm is not counted.
    from agentvault_registry.services import slash_order
    drained = await slash_order.drain(
        db, defendant, request.amount, ref=f"dispute-slash-{request.settlement_id}",
        liquid_key=f"dispute-slash-{request.settlement_id}", reason="dispute_slash",
        reference_id=f"dispute-{request.dispute_id}", actor="federation_slash_request",
        why=f"dispute {request.dispute_id} slash requested by {request.origin_registry_url}")
    actual_slash, slash_type, teg_error, unconfirmed = _slash_outcome(drained, request.amount)
    if slash_type == "partial":
        logger.warning(
            f"Partial slash for {request.defendant_did}: requested {request.amount}, "
            f"slashed {actual_slash} (shortfall: {drained.shortfall})"
        )
    elif slash_type == "insufficient":
        logger.warning(f"Cannot slash {request.defendant_did}: nothing in the slash order, requested {request.amount}")

    settlement.slashed_amount = actual_slash
    
    await db.commit()
    
    logger.info(
        f"Auto-slashed {actual_slash} AVT from {request.defendant_did} "
        f"(type: {slash_type}, plan={drained.plan()}, "
        f"new balance: {defendant.liquid_balance})"
    )
    
    # Step 5: Emit DisputeSlash event to EventStore (balance-affecting)
    event_emitter = get_event_emitter()
    slash_tx_id = f"dispute-slash-{request.dispute_id}-{uuid.uuid4().hex[:8]}"
    
    try:
        success = await event_emitter.emit_dispute_slash(
            dispute_id=request.dispute_id,
            defendant_did=request.defendant_did,
            amount=int(actual_slash),
            origin_registry_url=request.origin_registry_url,
            slash_tx_id=slash_tx_id
        )
        
        if success:
            logger.info(f"Emitted DisputeSlash event: {actual_slash} AVT from {request.defendant_did}")
        else:
            logger.error("Failed to emit DisputeSlash event to EventStore")
    except Exception as e:
        logger.error(f"Error emitting DisputeSlash event: {e}")
    
    # Step 6: Update settlement status
    settlement.status = "SLASHED" if actual_slash > 0 else "FAILED"
    settlement.slashed_at = datetime.now(timezone.utc)
    settlement.slash_tx_id = slash_tx_id if actual_slash > 0 else ""
    # TITANIUM VAULT D3: Update saga state
    if actual_slash > 0:
        settlement.saga_state = "SLASH_CONFIRMED"
        settlement.saga_last_step_at = datetime.now(timezone.utc)
    else:
        settlement.saga_state = "SLASH_FAILED"
        settlement.saga_last_step_at = datetime.now(timezone.utc)
    if slash_type == "partial":
        settlement.error_message = _partial_words(drained, actual_slash, request.amount)
    elif slash_type == "insufficient":
        settlement.error_message = (
            f"Slash failed: the slash order ({drained.sources()}) held nothing of the defendant's. "
            f"Requested {request.amount} {frame_currency()}."
        )
    elif slash_type == "unconfirmed":
        settlement.error_message = (
            f"Slash failed: the TEG did not confirm moving {unconfirmed} from the defendant ({teg_error}). "
            f"Nothing is reported slashed."
        )
    await db.commit()
    
    # Step 7: Callback origin registry with confirmation via mTLS
    callback_status = "slashed" if actual_slash > 0 else "failed"
    confirmation = {
        "settlement_id": request.settlement_id,
        "status": callback_status,
        "amount": int(actual_slash),
        "slash_event_id": "",
        "slash_tx_id": slash_tx_id if actual_slash > 0 else "",
        "error_message": "" if slash_type == "full" else (
            f"Partial slash: {actual_slash}/{request.amount} {frame_currency()} available"
            if slash_type == "partial" else
            f"The defendant's TEG did not confirm the slash ({teg_error})"
            if slash_type == "unconfirmed" else
            f"Insufficient balance: defendant has 0 {frame_currency()}"
        )
    }
    
    # Build mTLS client config (same pattern as federation_sync.py)
    callback_client_config = {'timeout': 15.0}
    if request.callback_url.startswith('https://'):
        cert_config = svid_client.get_client_cert_config()
        if cert_config:
            callback_client_config.update(cert_config)
            logger.info("Using mTLS certificates for slash confirmation callback")
        else:
            logger.warning("mTLS certs not available for callback — will attempt anyway")
    
    try:
        async with httpx.AsyncClient(**callback_client_config) as client:
            resp = await client.post(
                request.callback_url,
                json=confirmation,
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code in (200, 201, 202):
                logger.info(
                    f"Slash confirmation callback sent via mTLS to {request.callback_url}: "
                    f"status={resp.status_code}"
                )
            else:
                logger.warning(
                    f"Slash confirmation callback returned {resp.status_code}: {resp.text[:200]}. "
                    f"Origin registry can still verify via EventStore."
                )
    except Exception as e:
        logger.warning(
            f"Failed to send slash confirmation callback: {e}. "
            f"Origin registry can still verify via EventStore periodic check."
        )
    
    return {
        "settlement_id": request.settlement_id,
        "status": callback_status,
        "slash_type": slash_type,
        "requested_amount": request.amount,
        "slashed_amount": actual_slash,
        "shortfall": request.amount - actual_slash if actual_slash < request.amount else 0,
        "slash_tx_id": slash_tx_id if actual_slash > 0 else "",
        "defendant_new_balance": defendant.liquid_balance,
        "message": (
            f"Auto-slashed {actual_slash} {frame_currency()} from {request.defendant_did}"
            if slash_type == "full" else
            f"Partial slash: {actual_slash}/{request.amount} {frame_currency()} from {request.defendant_did}"
            if slash_type == "partial" else
            f"Slash failed: the TEG did not confirm moving {unconfirmed} from {request.defendant_did} ({teg_error})"
            if slash_type == "unconfirmed" else
            f"Slash failed: {request.defendant_did} has insufficient balance"
        )
    }


# --- Endpoint 2: Receive Slash Confirmation (origin registry) ---

@router.post("/slash-confirmation", response_model=Dict[str, Any])
async def receive_slash_confirmation(
    confirmation: SlashConfirmation,
    federation_identity: str = Security(get_federation_identity),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    This registry is the complainant's home. Once the defendant's home confirms the slash, the complainant is paid
    the compensation through this registry's payout funding (the fee collector, then the treasury): a transfer,
    never an issuance. A replay pays nothing twice. Auth: the defendant's home registry's federation identity (mTLS): only
    the registry this settlement's slash request was sent to may confirm it (403), and a confirmation reports at most
    the amount requested (422).

    \f
    Receive slash confirmation from the defendant's home registry.
    
    This registry is the COMPLAINANT'S HOME. Now that the defendant has been slashed, the complainant is paid from this
    registry's payout funding (services/reward_funding: the fee collector, then the treasury; a transfer, never an
    issuance).

    Flow:
    1. Find the local settlement record
    2. Verify the slash confirmation
    3. Pay the complainant through the reward funding waterfall
    4. Update complainant's Agent.liquid_balance in DB
    5. Emit DisputeCompensationMinted event to EventStore (the record's name is historical: it records the transfer)
    6. Mark settlement as SETTLED
    """
    logger.info(
        f"Received slash confirmation: settlement={confirmation.settlement_id}, "
        f"status={confirmation.status}, amount={confirmation.amount}"
    )
    
    # Step 1: Find local settlement record
    settlement_result = await db.execute(
        select(CrossRegistrySettlement).where(
            CrossRegistrySettlement.id == confirmation.settlement_id
        )
    )
    settlement = settlement_result.scalar_one_or_none()
    
    if not settlement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Settlement {confirmation.settlement_id} not found"
        )

    # D6-801 (wave 6, 2026-10-17): no compensation with a registry this one holds in quarantine, soft quarantine or
    # blacklisted: neither the registry presenting the confirmation nor either registry of the settlement (rows of any
    # status). Asked before the settlement is claimed and before the complainant is paid.
    from agentvault_registry.services.federation_license_gate import assert_federation_peer_not_quarantined
    await assert_federation_peer_not_quarantined(
        db, presenter=federation_identity,
        peer_urls=(settlement.origin_registry_url, settlement.defendant_registry_url),
        context="slash_confirmation")

    # Option D-light Phase D6 (2026-04-21): gate slash-confirmation on peer
    # licenses. Both ends (origin + defendant registries) must have active
    # licenses before we mint compensation. Protects against accepting
    # stale/spoofed callbacks from registries that have since been suspended.
    from agentvault_registry.services.federation_license_gate import (
        assert_peer_license_active, resolve_peer_operator_did,
    )
    _settlement_peers = {}
    for _url_key, _ctx in (
        ("origin_registry_url", "slash_confirmation_origin"),
        ("defendant_registry_url", "slash_confirmation_defendant"),
    ):
        _url = getattr(settlement, _url_key, None)
        if not _url:
            continue
        _peer_result = await db.execute(
            select(PeerRegistry).where(PeerRegistry.base_url == _url)
        )
        _peer = _peer_result.scalar_one_or_none()
        _settlement_peers[_url_key] = _peer
        if _peer is None:
            continue
        _operator_did = await resolve_peer_operator_did(db, _peer)
        if _operator_did:
            await assert_peer_license_active(
                db=db, operator_did=_operator_did, context=_ctx,
                actor_registry_did=_operator_did,
            )

    # The confirmation comes from the registry the slash request was sent to, for at most the amount requested
    _bind_confirmation_to_caller(confirmation, settlement, federation_identity,
                                 _settlement_peers.get("defendant_registry_url"))

    if settlement.status == "SETTLED":
        return {
            "settlement_id": confirmation.settlement_id,
            "status": "already_settled",
            "message": "This settlement has already been completed"
        }
    if settlement.status in _origin.ENDED:
        # V0660 (k): no peer held its slash request (never delivered, refused by every peer, or closed by an
        # administrator): it pays nothing
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Settlement {confirmation.settlement_id} is {settlement.status}: no peer held its slash request, "
                    f"so it pays nothing"),
        )

    # Atomic claim (2026-07-24 $-audit): only ONE concurrent confirmation reaches the money
    # leg. The NOT-IN guard lets a FAILED/mint-pending settlement retry; SETTLED/COMPENSATING
    # block. The prior status is restored on mint failure so the retry path is unchanged.
    _prev_status = settlement.status
    claimed = await db.execute(
        update(CrossRegistrySettlement)
        .where(
            CrossRegistrySettlement.id == confirmation.settlement_id,
            CrossRegistrySettlement.status.notin_(UNCLAIMABLE),
        )
        .values(status="COMPENSATING")
    )
    if getattr(claimed, "rowcount", 0) == 0:
        await db.rollback()
        return {
            "settlement_id": confirmation.settlement_id,
            "status": "already_settled",
            "message": "This settlement is already completed or being compensated"
        }
    await db.commit()

    # Step 2: Verify the confirmation
    if confirmation.status != "slashed":
        settlement.status = "FAILED"
        settlement.error_message = confirmation.error_message or "Slash was not confirmed"
        await db.commit()
        return {
            "settlement_id": confirmation.settlement_id,
            "status": "failed",
            "message": f"Slash failed: {confirmation.error_message}"
        }
    
    slashed_amount = confirmation.amount
    
    # Step 3: Phase 2 (2026-05-08) — Fund complainant via reward waterfall.
    # Replaces direct treasury/transfer with /admin/reward-fund — fees are
    # drained first per the configured reward_funding_waterfall policy
    # (default: ["fee_collector", "treasury"]). Operators can configure
    # dispute_compensation specifically to e.g. ["treasury"] only if they
    # don't want fee pool used for compensation.
    mint_tx_id = f"dispute-comp-{settlement.dispute_id}-{uuid.uuid4().hex[:8]}"
    teg_mint_success = False

    try:
        # §REWARDEVENTS: shared rail — per-leg TokensTransferred emission + cache
        # sync; same durable Idempotency-Key AND the historical str(float(...))
        # amount format, so pre-roll idempotency cache entries stay body-hash
        # compatible (the reconciliation retry after a timed-out-but-committed
        # mint replays from cache — the complainant is paid exactly once).
        from ..services.reward_funding import fund_reward_via_waterfall
        res = await fund_reward_via_waterfall(
            db,
            target_agent_did=settlement.complainant_did,
            amount=str(float(slashed_amount)),
            reason="dispute_compensation",
            reference_id=f"dispute-{settlement.dispute_id}-comp",
            idempotency_key=f"dispute-{settlement.dispute_id}-comp",
        )
        if res["status"] == "completed":
            resp_data = res["raw"]
            teg_mint_success = True
            mint_tx_id = res["first_transaction_id"] or mint_tx_id
            logger.info(
                f"TEG treasury compensation: {slashed_amount} AVT to {settlement.complainant_did}, "
                f"tx={resp_data.get('transaction_id', 'unknown')}, "
                f"new_balance={resp_data.get('new_target_balance', 'unknown')}, "
                f"treasury_remaining={resp_data.get('new_treasury_balance', 'unknown')}"
            )
        else:
            # Partial legs are committed + emitted + synced by the rail; the
            # saga still treats this as not-fully-paid (reconciliation retries,
            # deduped by the Idempotency-Key — a cached 'exhausted' replays
            # until the shortfall is resolved by an operator).
            logger.error(
                f"TEG treasury compensation PARTIAL ({res['funded_amount']} of "
                f"{slashed_amount}, shortfall {res['shortfall']}) — legs "
                f"committed + emitted; settlement stays unsettled"
            )
    except Exception as e:
        logger.error(f"TEG treasury compensation request failed: {e}")
    
    # Step 4: Update complainant's Agent.liquid_balance from TEG response
    # S6 FIX (2026-05-06): if TEG mint fails, do NOT fall back to direct DB add.
    # TEG is source of truth — silent DB-only credit drifts the supply invariant.
    # Instead, leave settlement in PENDING_SLASH/SLASHED so reconciliation worker
    # retries the mint, and surface the failure to caller via the saga state.
    if not teg_mint_success:
        settlement.error_message = (
            f"TEG mint failed (slash succeeded). Balance NOT credited to complainant. "
            f"Reconciliation worker will retry. dispute_id={settlement.dispute_id}"
        )
        settlement.saga_state = "SLASH_CONFIRMED"  # slash done but mint pending
        settlement.saga_last_step_at = datetime.now(timezone.utc)
        # Release the COMPENSATING claim so the reconciliation retry can claim again;
        # the TEG Idempotency-Key above keeps the retry exactly-once regardless.
        settlement.status = _prev_status
        await db.commit()
        logger.error(
            f"Settlement {settlement.id} mint FAILED via TEG. "
            f"Slash succeeded ({slashed_amount} AVT from {settlement.defendant_did}) "
            f"but complainant {settlement.complainant_did} not credited. "
            f"Reconciliation worker will retry."
        )
        # Return 502 — slash succeeded, mint failed, retry pending
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Settlement partially complete: slash succeeded but the payment failed. "
                f"Reconciliation worker will retry."
            )
        )

    complainant_result = await db.execute(
        select(Agent).where(Agent.did == settlement.complainant_did)
    )
    complainant = complainant_result.scalar_one_or_none()

    if complainant and resp_data:
        # Sync from TEG response (single source of truth)
        from decimal import Decimal
        complainant.liquid_balance = Decimal(str(resp_data.get('new_target_balance', complainant.liquid_balance or 0)))
        logger.info(
            f"DB balance updated: complainant {settlement.complainant_did} "
            f"liquid_balance={complainant.liquid_balance}"
        )
    
    # Step 5: Emit DisputeCompensationMinted event to EventStore
    event_emitter = get_event_emitter()
    try:
        await event_emitter.emit_dispute_compensation_minted(
            dispute_id=settlement.dispute_id,
            complainant_did=settlement.complainant_did,
            amount=slashed_amount,
            slash_evidence_event_id=confirmation.slash_tx_id,
            mint_tx_id=mint_tx_id
        )
        logger.info(
            f"Emitted DisputeCompensationMinted: {slashed_amount} AVT "
            f"to {settlement.complainant_did}"
        )
    except Exception as e:
        logger.error(f"Failed to emit DisputeCompensationMinted event: {e}")
    
    # Step 6: Mark settlement as SETTLED
    settlement.status = "SETTLED"
    settlement.slashed_amount = slashed_amount
    settlement.minted_amount = slashed_amount
    settlement.mint_tx_id = mint_tx_id
    settlement.slash_tx_id = confirmation.slash_tx_id
    settlement.settled_at = datetime.now(timezone.utc)
    # TITANIUM VAULT D3: Finalize saga
    settlement.saga_state = "FINALIZED"
    settlement.saga_last_step_at = datetime.now(timezone.utc)

    # SF-5A: Update Bayesian trust metrics for the defendant's registry
    try:
        await _update_peer_trust_metrics(
            db, settlement.defendant_registry_url, outcome="settled"
        )
    except Exception as e:
        logger.error(f"SF-5A: Failed to update peer trust metrics: {e}")

    await db.commit()

    logger.info(
        f"Settlement {confirmation.settlement_id} SETTLED: "
        f"slashed {slashed_amount} AVT from {settlement.defendant_did}, "
        f"minted {slashed_amount} AVT for {settlement.complainant_did}"
    )
    
    return {
        "settlement_id": confirmation.settlement_id,
        "status": "settled",
        "slashed_amount": slashed_amount,
        "minted_amount": slashed_amount,
        "mint_tx_id": mint_tx_id,
        "teg_mint_success": teg_mint_success,
        "message": (
            f"Settlement complete: {slashed_amount} {frame_currency()} paid to "
            f"{settlement.complainant_did} (evidence: slash {confirmation.slash_tx_id})"
        )
    }


# --- Admin Endpoints: Settlement Management ---

@router.get("/settlements", response_model=Dict[str, Any])
async def list_settlements(
    status_filter: str = None,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """List all cross-registry settlements for this registry."""
    query = select(CrossRegistrySettlement).order_by(
        CrossRegistrySettlement.requested_at.desc()
    )
    if status_filter:
        query = query.where(CrossRegistrySettlement.status == status_filter)
    
    result = await db.execute(query.limit(100))
    settlements = list(result.scalars().all())
    
    # Compute summary stats
    stats = {
        "total": len(settlements),
        "pending": sum(1 for s in settlements if s.status in ("PENDING_SLASH", "SLASHING")),
        "settled": sum(1 for s in settlements if s.status == "SETTLED"),
        "slashed": sum(1 for s in settlements if s.status == "SLASHED"),
        "failed": sum(1 for s in settlements if s.status == "FAILED"),
        "expired": sum(1 for s in settlements if s.status == "EXPIRED"),
        # V0660 (k): the end states of a settlement no peer holds
        "not_delivered": sum(1 for s in settlements if s.status == _origin.NOT_DELIVERED),
        "refused": sum(1 for s in settlements if s.status == _origin.REFUSED),
        "closed": sum(1 for s in settlements if s.status == _origin.CLOSED),
        "total_requested_avt": sum(s.requested_amount or 0 for s in settlements),
        "total_slashed_avt": sum(s.slashed_amount or 0 for s in settlements),
        "total_minted_avt": sum(s.minted_amount or 0 for s in settlements),
    }
    
    return {
        "count": len(settlements),
        "stats": stats,
        "settlements": [
            _serialize_settlement(s) for s in settlements
        ]
    }


@router.get("/settlements/{settlement_id}", response_model=Dict[str, Any])
async def get_settlement(
    settlement_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(security.require_admin_flag("admin_enforcement"))
) -> Dict[str, Any]:
    """Get a specific settlement by ID."""
    result = await db.execute(
        select(CrossRegistrySettlement).where(
            CrossRegistrySettlement.id == settlement_id
        )
    )
    settlement = result.scalar_one_or_none()
    
    if not settlement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Settlement {settlement_id} not found"
        )
    
    return {"settlement": _serialize_settlement(settlement)}


def _serialize_settlement(s: CrossRegistrySettlement) -> Dict[str, Any]:
    """Serialize a settlement to a dict."""
    is_partial = (
        s.slashed_amount is not None
        and s.requested_amount is not None
        and 0 < s.slashed_amount < s.requested_amount
    )
    return {
        "id": s.id,
        "dispute_id": s.dispute_id,
        "status": s.status,
        "complainant_did": s.complainant_did,
        "defendant_did": s.defendant_did,
        "requested_amount": s.requested_amount,
        "slashed_amount": s.slashed_amount,
        "minted_amount": s.minted_amount,
        "shortfall": max((s.requested_amount or 0) - (s.slashed_amount or 0), 0),
        "is_partial": is_partial,
        "ruling": s.ruling,
        "origin_registry_url": s.origin_registry_url,
        "defendant_registry_url": s.defendant_registry_url,
        "callback_url": s.callback_url,
        "slash_tx_id": s.slash_tx_id,
        "mint_tx_id": s.mint_tx_id,
        "requested_at": s.requested_at.isoformat() if s.requested_at else None,
        "slashed_at": s.slashed_at.isoformat() if s.slashed_at else None,
        "settled_at": s.settled_at.isoformat() if s.settled_at else None,
        "error_message": s.error_message,
        # V0660 (k): whether close_settlement takes it (the console offers Close only then)
        "closable": closable(s),
        # TITANIUM VAULT D3: Saga state tracking
        "saga_state": getattr(s, 'saga_state', 'LEGACY'),
        "saga_timeout_at": (
            s.saga_timeout_at.isoformat()
            if getattr(s, 'saga_timeout_at', None) else None
        ),
    }


# --- OWL25 Phase 3: Admin Approve/Reject Pending Settlements ---

async def _tell_origin(settlement: CrossRegistrySettlement, payload: Dict[str, Any], what: str) -> Tuple[bool, str]:
    """§MCPTEST30 (V0639, agentvault2-aa): calls the origin's slash confirmation back and says whether it was taken.

    Only a 2xx is delivered. The reject route answered "Origin registry notified." whatever happened, and a refusal
    (a non-2xx) was not even logged as a failure; the origin of a confirmation it never heard ends the settlement at its
    saga timeout. Returns (delivered, what happened, in a few words); never raises."""
    if not settlement.callback_url:
        return False, "the settlement names no callback address"
    config: Dict[str, Any] = {'timeout': 15.0}
    if settlement.callback_url.startswith('https://'):
        cert_config = svid_client.get_client_cert_config()
        if cert_config:
            config.update(cert_config)
    try:
        async with httpx.AsyncClient(**config) as client:
            resp = await client.post(settlement.callback_url, json=payload, headers={"Content-Type": "application/json"})
    except Exception as e:  # noqa: BLE001 (an unreachable origin is an answer here, never a 500)
        logger.warning(f"{what} callback failed: {e}")
        return False, f"it could not be reached: {type(e).__name__}"
    if 200 <= resp.status_code < 300:
        logger.info(f"{what} callback sent: {resp.status_code}")
        return True, f"HTTP {resp.status_code}"
    logger.warning(f"{what} callback refused: HTTP {resp.status_code}")
    return False, f"it answered HTTP {resp.status_code}"


def _saga_decided(settlement: CrossRegistrySettlement, saga_state: str) -> None:
    """An administrator's decision moves the saga off INITIATED, as the automatic slash (receive_slash_request) does.

    The admin approve and reject left saga_state at INITIATED with its 72 h deadline, so the saga sweep
    (SettlementSaga.check_timeouts) later rewrote the decided settlement as EXPIRED, replaced the administrator's words
    with "Saga timeout after 72h in state INITIATED" and emitted SettlementTimeout asking for an admin review: on
    sbx-beta every settlement the nightly federation suite had rejected read EXPIRED three days later (V0649,
    agentvault2-13). An approved slash would have read EXPIRED after its units had moved."""
    settlement.saga_state = saga_state
    settlement.saga_last_step_at = datetime.now(timezone.utc)


@router.post("/settlements/{settlement_id}/approve", response_model=Dict[str, Any])
async def approve_settlement(
    settlement_id: str,
    body: SettlementApproveBody | None = None,
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Admin approves a PENDING_ADMIN_APPROVAL settlement.
    Triggers the actual slash + callback flow.

    S4: SELECT FOR UPDATE prevents the race where approve + reject fire
    concurrently. S15: optional `reason` body field is persisted in event metadata.
    """
    admin_reason = (body.reason if body else None) or ""

    # S4: lock the settlement row
    result = await db.execute(
        select(CrossRegistrySettlement).where(
            CrossRegistrySettlement.id == settlement_id
        ).with_for_update()
    )
    settlement = result.scalar_one_or_none()
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    if settlement.status != "PENDING_ADMIN_APPROVAL":
        return {"settlement_id": settlement_id, "status": settlement.status,
                "message": f"Settlement is not pending approval (current: {settlement.status})"}
    
    # Find defendant
    defendant_result = await db.execute(
        select(Agent).where(Agent.did == settlement.defendant_did)
    )
    defendant = defendant_result.scalar_one_or_none()
    if not defendant:
        settlement.status = "FAILED"
        settlement.error_message = "Defendant no longer exists locally"
        _saga_decided(settlement, "SLASH_FAILED")
        await db.commit()
        raise HTTPException(status_code=404, detail="Defendant agent not found")
    
    # Execute the slash. V0658 (k): the request drains this registry's slash order (services/slash_order), as an
    # automatic one does: its bond, its locked units, its liquid units and, where the order lists it, the owner's other
    # agents, each step's capacity read from the TEG, each move under its own key (settlement-approve-<id>-...), so an
    # approval the administrator retries moves nothing twice. S6 FIX (2026-05-06): TEG is source of truth, no DB write
    # stands in for a move.
    from agentvault_registry.services import slash_order
    drained = await slash_order.drain(
        db, defendant, settlement.requested_amount, ref=f"settlement-approve-{settlement.id}",
        reason="dispute_slash", reference_id=f"dispute-{settlement.dispute_id}",
        actor=f"admin:{getattr(current_admin, 'id', '') or ''}",
        why=f"dispute {settlement.dispute_id} slash approved by an administrator")
    actual_slash, slash_type, _teg_error, _unconfirmed = _slash_outcome(drained, settlement.requested_amount)
    if slash_type == "unconfirmed":
        # nothing moved and the TEG did not confirm a move: bail out with a clear error, the admin can retry
        logger.error(f"TEG approve-slash unconfirmed: {_teg_error}. Settlement stays PENDING_ADMIN_APPROVAL for retry.")
        settlement.error_message = (
            f"Approve failed: TEG slash unsuccessful. Settlement remains "
            f"PENDING_ADMIN_APPROVAL. Admin {current_admin.email} attempted "
            f"approval, reason={admin_reason or '(none)'}"
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TEG slash failed; settlement still pending. Retry possible."
        )

    settlement.slashed_amount = actual_slash
    settlement.status = "SLASHED" if actual_slash > 0 else "FAILED"
    settlement.slashed_at = datetime.now(timezone.utc)
    _saga_decided(settlement, "SLASH_CONFIRMED" if actual_slash > 0 else "SLASH_FAILED")

    slash_tx_id = f"dispute-slash-{settlement.dispute_id}-{uuid.uuid4().hex[:8]}"
    settlement.slash_tx_id = slash_tx_id if actual_slash > 0 else ""
    settlement.error_message = (
        f"Approved by admin {current_admin.email}. "
        f"Slash type: {slash_type}, amount: {actual_slash}/{settlement.requested_amount}"
        + (f". {_partial_words(drained, actual_slash, settlement.requested_amount)}" if slash_type == "partial" else "")
        + (f". Reason: {admin_reason}" if admin_reason else "")
    )

    # SF-5A (SEC-20): no trust observation here. The administrator's decision on the origin's request is about this
    # registry's own agent, not evidence about the origin; the origin records the dispute its peer lost when this
    # registry confirms the slash (receive_slash_confirmation there).

    await db.commit()

    # Emit DisputeSlash event (convert Decimal to int for JSON)
    event_emitter = get_event_emitter()
    try:
        await event_emitter.emit_dispute_slash(
            dispute_id=settlement.dispute_id,
            defendant_did=settlement.defendant_did,
            amount=int(actual_slash),
            origin_registry_url=settlement.origin_registry_url,
            slash_tx_id=slash_tx_id
        )
    except Exception as e:
        logger.error(f"Failed to emit DisputeSlash: {e}")
    
    # Callback origin registry (convert Decimals to int for JSON serialization)
    confirmation = {
        "settlement_id": settlement.id,
        "status": "slashed" if actual_slash > 0 else "failed",
        "amount": int(actual_slash),
        "slash_event_id": "",
        "slash_tx_id": slash_tx_id if actual_slash > 0 else "",
        "error_message": "" if slash_type == "full" else f"Partial: {int(actual_slash)}/{int(settlement.requested_amount)}"
    }
    told, how = await _tell_origin(settlement, confirmation, "Approval")

    return {
        "settlement_id": settlement_id,
        "status": settlement.status,
        "slashed_amount": actual_slash,
        "slash_type": slash_type,
        "approved_by": current_admin.email,
        "origin_notified": told,
        "message": ("" if told else "origin_not_notified: ")
        + f"Settlement approved. Slashed {actual_slash} {frame_currency()} from {settlement.defendant_did}"
        + ("" if told else f". The origin registry was not told ({how}); it ends the settlement at its own timeout")
    }


@router.post("/settlements/{settlement_id}/reject", response_model=Dict[str, Any])
async def reject_settlement(
    settlement_id: str,
    body: SettlementApproveBody | None = None,
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Admin rejects a pending settlement.

    S4: SELECT FOR UPDATE prevents the race where approve + reject fire
    concurrently. S15: optional `reason` body field is persisted.
    """
    admin_reason = (body.reason if body else None) or ""

    # S4: lock the settlement row
    result = await db.execute(
        select(CrossRegistrySettlement).where(
            CrossRegistrySettlement.id == settlement_id
        ).with_for_update()
    )
    settlement = result.scalar_one_or_none()
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    if settlement.status != "PENDING_ADMIN_APPROVAL":
        return {"settlement_id": settlement_id, "status": settlement.status,
                "message": f"Settlement is not pending approval (current: {settlement.status})"}

    settlement.status = "REJECTED"
    settlement.error_message = (
        f"Rejected by admin {current_admin.email}"
        + (f". Reason: {admin_reason}" if admin_reason else "")
    )
    _saga_decided(settlement, "SLASH_FAILED")   # the saga's own word for "the defendant's home rejected it"

    # SF-5A (SEC-20): no trust observation here; a rejected request is not evidence about the peer that sent it.

    await db.commit()

    # Callback origin with rejection
    rejection = {
        "settlement_id": settlement.id,
        "status": "failed",
        "amount": 0,
        "slash_event_id": "",
        "slash_tx_id": "",
        "error_message": "Slash request rejected by receiving registry admin"
    }
    told, how = await _tell_origin(settlement, rejection, "Rejection")

    return {
        "settlement_id": settlement_id,
        "status": "REJECTED",
        "rejected_by": current_admin.email,
        "origin_notified": told,
        "message": "Settlement rejected. Origin registry notified." if told else
                   f"origin_not_notified: Settlement rejected. The origin registry was not told ({how}); it ends the "
                   "settlement at its own timeout."
    }


@router.post("/settlements/{settlement_id}/close", response_model=Dict[str, Any])
async def close_settlement(
    settlement_id: str,
    body: SettlementCloseBody,
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """An administrator closes a cross-registry settlement no peer holds (V0660 (k), Guild order
    gwo_9230be3d156cc3ce58699aaf): one never delivered, refused by every peer, or left waiting or expired with no peer
    holding its slash request (sbx-beta 24ca7222). It moves to CLOSED with who, when and why, on the row and in the
    admin audit log. Nothing moves. Review of 0d6b7ff9e: NOT_DELIVERED and REFUSED close at once (no peer took a
    request); any other state closes only once the reconciliation's event store check finds no DisputeSlash for it
    (one found: 409; a store that cannot be read: 503). The close is committed before its audit row. Refused (409, in
    words): a settlement a peer holds (that home may still slash and confirm), and one that moved money, is moving it,
    or is closed already. The confirmation's claim refuses CLOSED, so a late confirmation pays nothing.

    S4: SELECT FOR UPDATE, as approve and reject: a retry that records the registry it asks waits for this lock, and
    sends nothing once the settlement no longer waits (crud_disputes.record_registry_asked).
    """
    result = await db.execute(
        select(CrossRegistrySettlement).where(
            CrossRegistrySettlement.id == settlement_id
        ).with_for_update()
    )
    settlement = result.scalar_one_or_none()
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    if settlement.status in NOT_CLOSABLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Settlement {settlement_id} is {settlement.status}: a settlement that moved money, is moving it, or "
                    f"is closed already is not closed"),
        )
    held = (settlement.defendant_registry_url or "").strip()
    if held:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"{held} holds this settlement's slash request and may still slash and confirm it, so it is not "
                    f"closed here (its home's administrator approves or rejects it)"),
        )

    if settlement.status not in NO_REQUEST_TAKEN:
        # V0660 (k) review: a request may have reached a peer (its answer lost, or a peer took it and the settlement
        # outlived it): the reconciliation's own event store check first, and never a close blind
        await _refuse_close_if_a_peer_may_have_slashed(settlement)

    previous = settlement.status
    now = datetime.now(timezone.utc)
    who = getattr(current_admin, "email", None) or f"developer {getattr(current_admin, 'id', '')}"
    settlement.status = _origin.CLOSED
    settlement.error_message = (
        f"Closed by admin {who} at {now.isoformat()} (was {previous}). Reason: {body.reason}. Nothing moved."
        + (f" Before: {settlement.error_message}" if settlement.error_message else "")
    )[:2000]
    settlement.saga_state = "ROLLED_BACK"
    settlement.saga_last_step_at = now

    # V0660 (k) review: the close is committed first and read back; the audit row is written after it, so an audit
    # write that fails never undoes the close nor answers for a close that did not happen
    await db.commit()
    await db.refresh(settlement)
    stored = settlement.status
    logger.warning(f"Settlement {settlement_id} {stored} by {email_for_log(who)} (was {previous})")

    from agentvault_registry.services import admin_audit
    audit_recorded = True
    try:
        await admin_audit.log_admin_action(
            db, action="federation.settlement.closed", actor_id=str(getattr(current_admin, "id", "") or ""),
            target_type="cross_registry_settlement", target_id=str(settlement_id), severity="warning",
            details={"reason": body.reason, "previous_status": previous, "dispute_id": settlement.dispute_id,
                     "requested_amount": str(settlement.requested_amount)},
        )
    except Exception as e:  # noqa: BLE001: the close is committed; the missing audit row is said, not raised
        audit_recorded = False
        logger.error(f"Settlement {settlement_id} closed, but its admin audit row was not written: {type(e).__name__}")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    return {
        "settlement_id": settlement_id,
        "status": stored,
        "previous_status": previous,
        "closed_by": who,
        "closed_at": now.isoformat(),
        "reason": body.reason,
        "audit_recorded": audit_recorded,
        "message": (("Settlement closed. Nothing moved, and the complainant is not paid through this settlement."
                     if stored == _origin.CLOSED else f"The settlement reads {stored} after the close.")
                    + ("" if audit_recorded else " Its admin audit row could not be written; the close stands.")),
    }


async def _refuse_close_if_a_peer_may_have_slashed(settlement) -> None:
    """409 when the event store holds this settlement's DisputeSlash (a peer slashed the defendant: the complainant is
    owed, so it is not closed), 409 when it records no origin (no slash of it can be matched), 503 when the event store
    cannot be read (whether a peer slashed is not known). The check is the reconciliation's own
    (tasks/settlement_reconciliation.find_slash_on_eventstore)."""
    from agentvault_registry.tasks import settlement_reconciliation as _rec
    sid = settlement.id
    if not (getattr(settlement, "origin_registry_url", "") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Settlement {sid} records no origin address, so the event store cannot show whether a peer "
                    f"slashed the defendant for it: it is not closed"),
        )
    try:
        slash = await _rec.find_slash_on_eventstore(settlement)
    except Exception as e:  # noqa: BLE001: EventStoreUnreadable, or anything else that kept the answer away
        why = str(e) if isinstance(e, _rec.EventStoreUnreadable) else type(e).__name__
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(f"The event store cannot be read now ({why}), so whether a peer slashed the defendant for "
                    f"settlement {sid} is not known: it is not closed. Try again when the event store answers."),
        )
    if slash:
        then = ("The periodic reconciliation pays the complainant from that slash."
                if settlement.status in ("PENDING_SLASH", "SLASHING") else
                f"A {settlement.status} settlement is not reconciled again: an administrator settles it from that "
                f"evidence.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"The event store holds a DisputeSlash for settlement {sid} (slash "
                    f"{slash.get('slash_tx_id') or slash.get('event_id') or 'recorded'}): a peer slashed the "
                    f"defendant, so it is not closed. {then}"),
        )


# --- OWL25 Phase 3: Per-Peer Auto-Slash Configuration ---

class PeerSlashConfigUpdate(BaseModel):
    auto_slash_enabled: bool
    auto_slash_max_avt: int = 0


@router.get("/peer-slash-config", response_model=Dict[str, Any])
async def list_peer_slash_config(
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """List all peers with their auto-slash configuration."""
    
    result = await db.execute(
        select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
    )
    peers = list(result.scalars().all())
    
    return {
        "peers": [
            {
                "id": p.id,
                "name": p.name,
                "base_url": p.base_url,
                "status": p.status,
                "auto_slash_enabled": p.auto_slash_enabled,
                "auto_slash_max_avt": p.auto_slash_max_avt,
                # SF-5A: Bayesian trust metrics
                "bayesian_discount": p.bayesian_discount,
                "total_interactions": p.total_interactions,
                "disputes_lost_with": p.disputes_lost_with,
                "last_interaction_at": p.last_interaction_at.isoformat() if p.last_interaction_at else None,
            }
            for p in peers
        ]
    }


@router.put("/peer-slash-config/{peer_id}", response_model=Dict[str, Any])
async def update_peer_slash_config(
    peer_id: int,
    config: PeerSlashConfigUpdate,
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Update auto-slash configuration for a specific peer."""
    
    result = await db.execute(
        select(PeerRegistry).where(PeerRegistry.id == peer_id)
    )
    peer = result.scalar_one_or_none()
    if not peer:
        raise HTTPException(status_code=404, detail="Peer not found")
    
    old_enabled = peer.auto_slash_enabled
    old_max = peer.auto_slash_max_avt
    # One key per update, made once here so the emitter's own retries stay deduplicated. A key made of the resulting
    # config (§BATCH7) recorded a later update back to an earlier config as a duplicate of the first and the store
    # dropped it: enable, disable, enable left two events, and every repeat of the same update left none.
    update_ref = uuid.uuid4().hex

    peer.auto_slash_enabled = config.auto_slash_enabled
    peer.auto_slash_max_avt = max(config.auto_slash_max_avt, 0)
    await db.commit()

    logger.info(
        f"Peer '{peer.name}' auto-slash config updated by {email_for_log(current_admin.email)}: "
        f"enabled {old_enabled}->{config.auto_slash_enabled}, "
        f"max_avt {old_max}->{peer.auto_slash_max_avt}"
    )

    # S16: Emit PeerSlashConfigUpdated event for audit trail
    # NB: auto_slash_max_avt is Numeric on the model → Decimal at runtime. Convert
    # to str so JSON serialization doesn't silently fail. Same bug pattern as
    # VoteCast in governance.py — emit's 3-retry loop logs
    # "Failed to emit event after 3 attempts: Decimal is not JSON serializable"
    # and the event is lost. Bug observed 2026-05-07.
    try:
        event_emitter = get_event_emitter()
        await event_emitter.emit(
            event_type="PeerSlashConfigUpdated",
            aggregate_id=f"peer:{peer.id}",
            aggregate_type="PeerRegistry",
            data={
                "peer_id": peer.id,
                "peer_name": peer.name,
                "peer_base_url": peer.base_url,
                "auto_slash_enabled_before": old_enabled,
                "auto_slash_enabled_after": config.auto_slash_enabled,
                "auto_slash_max_avt_before": str(old_max) if old_max is not None else None,
                "auto_slash_max_avt_after": str(peer.auto_slash_max_avt) if peer.auto_slash_max_avt is not None else None,
                "updated_by_email": current_admin.email,
            },
            idempotency_key=f"peerslash-{peer.id}-{update_ref}",  # §BATCH7: one per update (above)
        )
    except Exception as e:
        logger.warning(f"Failed to emit PeerSlashConfigUpdated for peer {peer.id}: {e}")

    return {
        "peer_id": peer.id,
        "name": peer.name,
        "auto_slash_enabled": peer.auto_slash_enabled,
        "auto_slash_max_avt": peer.auto_slash_max_avt,
        "updated_by": current_admin.email,
        "message": f"Auto-slash config updated for '{peer.name}'"
    }
