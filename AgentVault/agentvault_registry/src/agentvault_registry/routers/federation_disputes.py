"""
OWL25: Federation Dispute Settlement Router
============================================
Sovereign Settlement Protocol endpoints for cross-registry dispute compensation.

Two endpoints:
1. POST /slash-request   — Receives request from origin registry, auto-slashes local defendant
2. POST /slash-confirmation — Receives confirmation from defendant's registry, auto-mints for local complainant
"""

import logging
import uuid
import httpx
from ..es_ssl_helper import get_httpx_verify
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
# D6-060 (2026-10-25): a slash or a settlement message names the unit of the registry that writes it (the defendant's home
# slashes in its own unit, the origin pays the complainant in its own), never a literal AVT: EU and ASIA settle in ECU and ACU.
from agentvault_registry.core.frame_currency import frame_currency
# TITANIUM VAULT D3: Settlement Saga integration
from agentvault_registry.services.settlement_saga import get_settlement_saga, SAGA_TIMEOUT_HOURS
from datetime import timedelta

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
    its threshold, the defendant's units are moved to this registry's treasury (the whole amount, or what the
    balance holds) and the origin is called back; otherwise the settlement waits for an administrator's approval.
    Auth: the origin registry's federation identity (mTLS). The request names its own registry: `origin_registry_url`
    must be the address of the registry presenting it, and `callback_url` must lie under it (403 otherwise).

    \f
    Receive a slash request from the origin registry.
    
    This registry is the DEFENDANT'S HOME. We have jurisdiction over
    the defendant's AVT. We verify the request, auto-slash, and callback.
    
    Flow:
    1. Verify defendant exists locally
    2. Verify ruling is valid
    3. Deduct from defendant's Agent.liquid_balance in DB
    4. Emit DisputeSlash event to EventStore (real, balance-affecting)
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
    callback_lower = request.callback_url.lower().rstrip("/")
    if not any(callback_lower.startswith(p.lower()) for p in known_peer_urls):
        logger.warning(
            f"Callback URL {request.callback_url} does not match any known peer. "
            f"Known peers: {known_peer_urls}"
        )
        # §MCPTEST30 V0639: the answer names what it compared, hosts only, so the next mismatch names itself (dispute
        # 50: an origin naming its internal proxy, refused by every peer with the bare sentence)
        from urllib.parse import urlsplit
        _cb_host = urlsplit(request.callback_url).hostname or "(none)"
        _peer_hosts = sorted({urlsplit(p).hostname or "(none)" for p in known_peer_urls})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Callback URL must belong to a registered peer registry: its host {_cb_host} is under no "
                    f"active peer's base URL (active peer hosts: {', '.join(_peer_hosts) or 'none'})")
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
    
    # Step 4: Auto-slash — OWL26: Route through TEG treasury/receive
    # OWL25 Phase 2: Proper partial slash handling (logic preserved)
    available_balance = max(defendant.liquid_balance or 0, 0)
    
    if available_balance >= request.amount:
        # Full slash — defendant has sufficient funds
        actual_slash = request.amount
        slash_type = "full"
    elif available_balance > 0:
        # Partial slash — defendant has some but not enough
        actual_slash = available_balance
        slash_type = "partial"
        logger.warning(
            f"Partial slash for {request.defendant_did}: "
            f"requested {request.amount}, available {available_balance}, "
            f"slashing {actual_slash} (shortfall: {request.amount - actual_slash})"
        )
    else:
        # Zero balance — cannot slash, report failure
        actual_slash = 0
        slash_type = "insufficient"
        logger.warning(
            f"Cannot slash {request.defendant_did}: "
            f"balance is {defendant.liquid_balance}, requested {request.amount}"
        )
    
    # OWL26: Route slash through TEG treasury/receive (agent -> treasury)
    teg_slash_success = False
    teg_error = ""
    teg_unknown = False   # §DOCSFIX review: the TEG's answer was lost, so it may have moved the units
    if actual_slash > 0:
        from ..services.payout_outcome import never_sent
        teg_url = settings.TEG_API_BASE_URL.rstrip('/')
        teg_admin_key = settings.TEG_ADMIN_API_KEY
        # §DOCSFIX review (D6-441): an answer other than a confirmation does not say the slash failed once the request
        # reached the TEG: a lost answer (a timeout after the request went out, a 5xx, the key still held by the first
        # request) says nothing, and /treasury/receive answers 400 "Treasury receive failed" for an error that came
        # after its transfer committed. The TEG is asked once more under the same key, which answers a slash it already
        # made from its record (it never debits twice), refuses again what it refused, and makes a slash that never
        # ran; only a slash still unconfirmed after that is a failed slash, and a lost answer says its outcome is not
        # known. A request that never reached the TEG (no connection) is not asked again.
        for _ask in (1, 2):
            reached = True
            try:
                async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as teg_client:
                    teg_resp = await teg_client.post(
                        f"{teg_url}/api/v1/admin/treasury/receive",
                        json={
                            "source_agent_id": request.defendant_did,
                            # §MONEY-R15: str(float(Decimal)) truncates; the TEG takes a Decimal.
                            "amount": str(actual_slash),
                            "reason": "dispute_slash",
                            "reference_id": f"dispute-{request.dispute_id}"
                        },
                        headers={
                            "Authorization": f"Bearer {teg_admin_key}",
                            "Content-Type": "application/json",
                            # Durable TEG-rail dedup: a retried slash with this key returns the
                            # cached result and debits the defendant exactly once.
                            "Idempotency-Key": f"dispute-slash-{request.settlement_id}"
                        }
                    )
            except Exception as e:  # noqa: BLE001
                reached = not never_sent(e)
                if reached or _ask == 1:
                    teg_error = type(e).__name__
                if reached:
                    teg_unknown = True
                # a second ask that never reached the TEG learns nothing: a first answer that was lost stays unknown
                logger.error(
                    f"TEG slash connection failed (ask {_ask}): {e}. "
                    f"Not falling back to direct DB balance update — TEG is source of truth."
                )
            else:
                if teg_resp.status_code in (200, 201):
                    teg_slash_success, teg_unknown = True, False
                    try:
                        from decimal import Decimal
                        defendant.liquid_balance = Decimal(str(
                            (teg_resp.json() or {}).get("new_source_balance", 0)
                        ))
                    except Exception as e:  # noqa: BLE001 — the TEG moved the units; the cached balance can wait
                        logger.warning(f"TEG slash answer unreadable after the move ({e}); cached balance not updated")
                    break
                teg_error = f"HTTP {teg_resp.status_code}"
                teg_unknown = teg_resp.status_code >= 500 or teg_resp.status_code == 409
                logger.error(
                    f"TEG slash failed ({teg_resp.status_code}, ask {_ask}): "
                    f"{teg_resp.text[:200]}. "
                    f"Not falling back to direct DB balance update — TEG is source of truth."
                )
            if not reached:
                break
        if teg_unknown:
            teg_error = f"{teg_error}; outcome not known, it may have moved the units"
    # §DOCSFIX D6-441: a slash the TEG did not confirm is a failed slash: FAILED, no DisputeSlash for its amount and
    # "failed" to the origin. It was reported SLASHED, and the complainant's registry paid compensation for units that
    # never moved.
    unconfirmed = 0
    if actual_slash > 0 and not teg_slash_success:
        unconfirmed, actual_slash, slash_type = actual_slash, 0, "unconfirmed"

    settlement.slashed_amount = actual_slash
    
    await db.commit()
    
    logger.info(
        f"Auto-slashed {actual_slash} AVT from {request.defendant_did} "
        f"(type: {slash_type}, teg={teg_slash_success}, "
        f"new balance: {defendant.liquid_balance})"
    )
    
    # Step 5: Emit DisputeSlash event to EventStore (balance-affecting)
    event_emitter = get_event_emitter()
    slash_tx_id = f"dispute-slash-{request.dispute_id}-{uuid.uuid4().hex[:8]}"
    
    try:
        success = await event_emitter.emit_dispute_slash(
            dispute_id=request.dispute_id,
            defendant_did=request.defendant_did,
            amount=actual_slash,
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
        settlement.error_message = (
            f"Partial slash: {actual_slash}/{request.amount} {frame_currency()}. "
            f"Defendant had insufficient balance ({available_balance} available)."
        )
    elif slash_type == "insufficient":
        settlement.error_message = (
            f"Slash failed: defendant has 0 available balance. "
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
        "amount": actual_slash,
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
    
    This registry is the COMPLAINANT'S HOME. Now that the defendant
    has been slashed, we auto-mint compensation for our local complainant.
    
    Flow:
    1. Find the local settlement record
    2. Verify the slash confirmation
    3. Mint AVT for complainant via TEG admin endpoint
    4. Update complainant's Agent.liquid_balance in DB
    5. Emit DisputeCompensationMinted event to EventStore
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

    # Atomic claim (2026-07-24 $-audit): only ONE concurrent confirmation reaches the money
    # leg. The NOT-IN guard lets a FAILED/mint-pending settlement retry; SETTLED/COMPENSATING
    # block. The prior status is restored on mint failure so the retry path is unchanged.
    _prev_status = settlement.status
    claimed = await db.execute(
        update(CrossRegistrySettlement)
        .where(
            CrossRegistrySettlement.id == confirmation.settlement_id,
            CrossRegistrySettlement.status.notin_(["SETTLED", "COMPENSATING"]),
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
                f"Settlement partially complete: slash succeeded but the issuance failed. "
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
            f"Settlement complete: {slashed_amount} {frame_currency()} issued for "
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
    
    # Execute the slash (OWL26: via TEG treasury/receive)
    available_balance = max(defendant.liquid_balance or 0, 0)
    if available_balance >= settlement.requested_amount:
        actual_slash = settlement.requested_amount
        slash_type = "full"
    elif available_balance > 0:
        actual_slash = available_balance
        slash_type = "partial"
    else:
        actual_slash = 0
        slash_type = "insufficient"
    
    # OWL26: Route through TEG treasury/receive
    # S6 FIX (2026-05-06): no fallback to direct DB add — TEG is source of truth.
    teg_slash_succeeded = False
    if actual_slash > 0:
        try:
            teg_url = settings.TEG_API_BASE_URL.rstrip('/')
            teg_admin_key = settings.TEG_ADMIN_API_KEY
            async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as tc:
                tr = await tc.post(
                    f"{teg_url}/api/v1/admin/treasury/receive",
                    json={
                        "source_agent_id": settlement.defendant_did,
                        # §MONEY-R15: str(float(Decimal)) truncates; the TEG takes a Decimal.
                        "amount": str(actual_slash),
                        "reason": "dispute_slash",
                        "reference_id": f"dispute-{settlement.dispute_id}"
                    },
                    headers={
                        "Authorization": f"Bearer {teg_admin_key}",
                        "Idempotency-Key": f"settlement-approve-{settlement.id}"
                    }
                )
                if tr.status_code in (200, 201):
                    from decimal import Decimal
                    td = tr.json()
                    defendant.liquid_balance = Decimal(
                        str(td.get("new_source_balance", 0))
                    )
                    teg_slash_succeeded = True
                else:
                    logger.error(
                        f"TEG approve-slash failed: HTTP {tr.status_code} {tr.text[:200]}. "
                        f"Settlement will stay PENDING_ADMIN_APPROVAL for retry."
                    )
        except Exception as e:
            logger.error(f"TEG approve-slash exception: {e}")

        if not teg_slash_succeeded:
            # Bail out with clear error — admin can retry
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
        f"Peer '{peer.name}' auto-slash config updated by {current_admin.email}: "
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
