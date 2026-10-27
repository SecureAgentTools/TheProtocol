"""
API Router for Cross-TEG Transfer endpoints.

Exposes HTTP endpoints for cross-TEG communication.
All incoming cross-TEG requests (accept/prepare/commit/abort) are validated
against known partner API keys from PARTNER_TEGS configuration.
"""

import asyncio
import hmac
import json
import logging
import os
import urllib.parse
import uuid
from typing import Dict, Any, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

# §pass53 PR-3: spec-side declaration of the cross-TEG auth scheme. The
# handlers extract + validate the Authorization header manually; this
# APIKeyHeader is a spec marker only — `auto_error=False` keeps the runtime
# behavior unchanged. SDK generators now see security: [{APIKeyHeader:[]}] on
# every cross-TEG route, closing 12 of the 30 TEG-mutator no-security gap
# (T-P0-3 from swagger audit).
_cross_teg_auth_header = APIKeyHeader(
    name="Authorization",
    description="Bearer <partner-TEG-JWT> or Bearer <admin-api-key>. Per-route validation in handler.",
    auto_error=False,
)
from cryptography import x509
from cryptography.x509.oid import ExtensionOID

from ..database import get_db
from .auth_enhanced import get_current_agent, AdminAuth
from ..core.cross_teg import (
    CrossTEGTransferProtocol,
    DistributedTransactionCoordinator,
    CrossTEGTransferRequest,
    CrossTEGTransferResponse,
    TransferAcceptRequest,
    TransferAcceptResponse,
    TransferStatus
)
from ..core.cross_teg.client import CrossTEGClientFactory
from ..core.cross_teg.partner_cache import (
    set_partner_in_redis,
    delete_partner_in_redis,
    list_all_partners_from_redis,
)
from ..core.config import get_settings

# Get settings instance
settings = get_settings()

logger = logging.getLogger(__name__)

# Build set of trusted API keys from PARTNER_TEGS config (loaded once at startup)
_trusted_cross_teg_keys: Set[str] = set()
for _partner in settings.parsed_partner_tegs:
    _key = _partner.get("api_key", "")
    if _key:
        _trusted_cross_teg_keys.add(_key)
from ..core.internal_auth import configured_admin_key as _configured_admin_key  # §MONEY-M3a R26
from ..core.internal_auth import is_internal_service_identity  # §MONEY-R51
_ak = _configured_admin_key()
if _ak:
    _trusted_cross_teg_keys.add(_ak)

# Runtime-added partners (hot-reload). §pass47 A4 — also mirrored to Redis
# via partner_cache so other workers can pick up additions. This local list
# remains the L1 read-path consulted by `resolve_partner_url`; the periodic
# refresh task (started in main.py lifespan) keeps it in sync with Redis.
_runtime_partners: list = []


def _mirror_partner_to_redis_async(teg_id: str, partner: Dict[str, str]) -> None:
    """Fire-and-forget mirror to Redis from a sync context (resolve_partner_url).

    Best-effort: if there's no running event loop (e.g. called during module
    import) or Redis is unavailable, just no-op. Other workers will learn via
    the periodic refresh task started in main.py lifespan.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(set_partner_in_redis(teg_id, partner))
    except RuntimeError:
        # No running event loop — caller is sync without an async context. Skip.
        return
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[PartnerCache] mirror to redis failed (non-fatal) for {teg_id}: {e}")


async def refresh_partners_from_redis(force_full: bool = False) -> int:
    """§pass47 A4 — pull the Redis HASH snapshot and merge into _runtime_partners.

    MERGE semantics:
      - For each partner present in Redis: ensure local has a matching entry.
        If local entry's URL differs, update it (Redis wins for changes
        propagated by another worker).
      - Local entries NOT in Redis are LEFT ALONE — they may be local
        discoveries that haven't been mirrored yet. The mirror call on the
        discovery path closes that gap on next discovery.

    Returns the number of local entries that changed (added or URL-updated).
    """
    snapshot = await list_all_partners_from_redis()
    if not snapshot:
        return 0
    changed = 0
    by_id = {p["teg_id"]: p for p in _runtime_partners}
    for partner in snapshot:
        tid = partner.get("teg_id")
        url = partner.get("url")
        if not tid or not url:
            continue
        local = by_id.get(tid)
        if local is None:
            _runtime_partners.append(partner)
            changed += 1
            if force_full:
                logger.info(f"[PartnerCache] seeded runtime partner from Redis: {tid} → {url}")
        elif local.get("url") != url:
            local["url"] = url
            # Carry through registry_id / api_key if Redis has them.
            for k in ("registry_id", "api_key"):
                if k in partner and partner[k]:
                    local[k] = partner[k]
            changed += 1
            logger.info(f"[PartnerCache] absorbed cross-worker partner update: {tid} → {url}")
    return changed


def resolve_partner_url(teg_id: str, url_hint: Optional[str] = None) -> str:
    """Resolve a partner TEG ID to its URL.

    Resolution order:
      1. `url_hint` from registry request body (AUTHORITATIVE — registry built it
         via `_to_internal_mtls_url` against current BFS topology + cluster-host
         shortcut, §pass44 2026-05-19). If a runtime entry exists with a stale
         URL, this self-heals it. Without this preference, stale per-worker
         `_runtime_partners` entries cause persistent 404s after registry URL
         contracts change — each TEG worker has its OWN runtime list, and
         `/cross-teg/config/add-partner` only updates the worker the registry's
         POST happens to hit, leaving other workers with stale data.
      2. `_runtime_partners` cache (in-memory, per-worker, written by add-partner).
      3. `settings.parsed_partner_tegs` (static from PARTNER_TEGS env).

    Raises KeyError if no source resolves the partner.
    """
    if url_hint:
        for p in _runtime_partners:
            if p["teg_id"] == teg_id:
                if p["url"] != url_hint:
                    logger.info(
                        f"[CrossTEG] Self-healing stale runtime partner: "
                        f"{teg_id} {p['url']} → {url_hint}"
                    )
                    p["url"] = url_hint
                    _mirror_partner_to_redis_async(teg_id, p)
                return url_hint
        logger.info(f"[CrossTEG] Dynamic partner discovery: {teg_id} → {url_hint}")
        new_p = {"teg_id": teg_id, "url": url_hint}
        _runtime_partners.append(new_p)
        _mirror_partner_to_redis_async(teg_id, new_p)
        return url_hint

    for p in _runtime_partners:
        if p["teg_id"] == teg_id:
            return p["url"]
    for p in settings.parsed_partner_tegs:
        if p["teg_id"] == teg_id:
            return p["url"]
    raise KeyError(f"Unknown partner TEG: {teg_id}")


def _extract_spiffe_from_header(request: Request) -> Optional[str]:
    """SPIFFE ID of the caller this frame's terminator verified, or None. §MTLSHOPS G1: through the TEG's ONE
    forwarded-certificate rule (core/internal_auth.extract_spiffe_from_request: X-TEG-Proxy-Auth + SUCCESS + a trusted
    domain), the same rule every other TEG site asks."""
    from ..core.internal_auth import extract_spiffe_from_request
    return extract_spiffe_from_request(request)


def _validate_cross_teg_auth(request: Request, authorization: str = "") -> str:
    """Validate incoming cross-TEG request authorization.

    Mode 1 (PRIMARY): mTLS SPIFFE identity from X-SSL-Client-Cert header.
    Mode 2 (FALLBACK): Bearer API key for internal Docker network (A↔B).
    Returns identity string on success, raises 401/403 on failure.
    """
    # Mode 1: mTLS SPIFFE identity (primary — no shared secrets)
    spiffe_id = _extract_spiffe_from_header(request)
    if spiffe_id:
        # Validate it's a TEG, registry, or operator service identity — ONE rule for the whole
        # TEG (§MONEY-R51: core/internal_auth.is_internal_service_identity, path-anchored).
        if is_internal_service_identity(spiffe_id):
            logger.info(f"[CrossTEG] Authenticated via mTLS: {spiffe_id}")
            return spiffe_id
        logger.warning(f"[CrossTEG] mTLS cert present but not an internal service identity: {spiffe_id}")

    # §2026-06-16 TEG-mTLS: under enforce (TEG_MTLS_REQUIRED), mTLS is the ONLY accepted
    # cross-TEG auth — the shared-key fallback below is disabled. Sub-30s rollback: unset + recreate.
    from ..core.internal_auth import licence_refusal_of, teg_mtls_required
    if teg_mtls_required():
        licence = licence_refusal_of(request)   # §FEDLICENCE: the caller's frame licence is refused by this frame
        logger.warning(
            f"[CrossTEG] DENY route={request.url.path} reason={'federation_licence' if licence else 'mtls_required'} "
            f"cert_present={bool(spiffe_id)}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"federation licence refused (cross-TEG): {licence}" if licence
                    else "mTLS identity required (cross-TEG)"),
        )

    # Mode 2: API key fallback (internal Docker network, no nginx) — GATED shadow fallback.
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token:
            for trusted_key in _trusted_cross_teg_keys:
                if hmac.compare_digest(token, trusted_key):
                    logger.warning(
                        "[CrossTEG-SHADOW] mode=key-fallback -- would FAIL under TEG_MTLS_REQUIRED"
                    )
                    # §SECFIX-3: a label, never the key. The treasury-fund handler logged the returned value and
                    # wrote it into the transaction's memo, so a key-authenticated call recorded the key itself.
                    return "shared-key"

    logger.warning("[CrossTEG] No valid mTLS identity or API key provided")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid cross-TEG authorization"
    )


try:
    from prometheus_client import Counter as _Counter

    CROSS_TEG_LOCAL_LEG_REFUSED_TOTAL = _Counter(
        "teg_cross_teg_local_leg_refused_total",
        "Calls to a cross-TEG leg that is local by design, refused because the caller is outside this TEG's sources",
        ["route"],
    )
except Exception:  # pragma: no cover
    CROSS_TEG_LOCAL_LEG_REFUSED_TOTAL = None


def _local_caller_dependency(route: str):
    """The same rule as a FastAPI dependency, for a leg whose body is a typed model: dependencies are resolved before
    the body is validated, so a refused caller gets 403 before its body is read (a check inside the handler runs only
    after validation, which lets an empty body answer 422 and hides whether the caller was admitted)."""
    def _dep(request: Request, authorization: Optional[str] = Security(_cross_teg_auth_header)) -> str:
        return _require_local_caller(request, authorization, route)
    return _dep


def _require_local_caller(request: Request, authorization: str, route: str) -> str:
    """§SECFIX-11 (2026-09-25): authenticate like every cross-TEG route, then admit only this TEG's own trust domain
    (core/internal_auth.local_leg_caller_ok, widened by CROSS_TEG_LOCAL_LEG_SOURCES). For the legs that are local by
    design: the async lock, credit, bulk credit, refund and reverse, and the unused one-shot accept."""
    from ..core.internal_auth import local_leg_caller_ok, local_leg_sources
    caller = _validate_cross_teg_auth(request, authorization)
    if local_leg_caller_ok(caller):
        return caller
    if CROSS_TEG_LOCAL_LEG_REFUSED_TOTAL is not None:
        try:
            CROSS_TEG_LOCAL_LEG_REFUSED_TOTAL.labels(route=route).inc()
        except Exception:  # pragma: no cover
            pass
    logger.warning(f"[CrossTEG] REFUSED local leg route={route} caller={caller} sources={local_leg_sources()}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="cross_teg_local_leg_refused: this leg is called only by this TEG's own frame "
               "(CROSS_TEG_LOCAL_LEG_SOURCES, default its own trust domain)",
    )

# Router instance
router = APIRouter(
    prefix="/api/v1/cross-teg",
    tags=["cross-teg"],
    responses={404: {"description": "Not found"}},
)

# Global instances (initialized in main.py)
transfer_protocol: Optional[CrossTEGTransferProtocol] = None
transaction_coordinator: Optional[DistributedTransactionCoordinator] = None
teg_client_factory: Optional[CrossTEGClientFactory] = None


def init_cross_teg_router(
    protocol: CrossTEGTransferProtocol,
    coordinator: DistributedTransactionCoordinator,
    client_factory: CrossTEGClientFactory
):
    """Initialize the router with required dependencies."""
    global transfer_protocol, transaction_coordinator, teg_client_factory
    transfer_protocol = protocol
    transaction_coordinator = coordinator
    teg_client_factory = client_factory


@router.post("/transfer", response_model=CrossTEGTransferResponse)
async def initiate_cross_teg_transfer(
    http_request: Request,
    request: CrossTEGTransferRequest,
    current_agent_id: str = Security(get_current_agent),
    db: AsyncSession = Depends(get_db)
):
    """
    Initiate a cross-TEG transfer.

    This endpoint is called by agents (via their registry) to initiate
    a transfer to an agent in a different registry/TEG.

    The request must include a valid cross-registry OAuth token.
    """
    # §SECFIX-13 (2026-09-25): the agent's JWT alone started a transfer here, a peer received that JWT on every remote
    # prepare, commit and abort (now a placeholder, core/cross_teg/coordinator.PEER_BEARER_PLACEHOLDER), and a peer can
    # reach this route through this frame's nginx-federation. The local registry calls it through nginx-teg with its own
    # SVID (measured on sbx-alpha: every /transfer arrived from nginx-teg), so under TEG_MTLS_REQUIRED the forwarded
    # certificate must be this TEG's own frame (the local-leg sources).
    from ..core.internal_auth import teg_mtls_required, local_leg_caller_ok
    if teg_mtls_required():
        _svid = _extract_spiffe_from_header(http_request)
        if not local_leg_caller_ok(_svid):
            logger.warning(f"[CrossTEG] REFUSED /transfer: caller certificate {_svid} is not this TEG's own frame")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="cross_teg_transfer_refused: a transfer is started by this TEG's own frame",
            )
    # Verify the user is authorized for this transfer
    if current_agent_id != request.source_agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to transfer from this agent"
        )

    # Verify this TEG is the source
    if settings.teg_id != request.source_teg_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This TEG ({settings.teg_id}) is not the source TEG"
        )

    # Phase 8 (2026-04-27): refuse cross-TEG transfers when sender or recipient
    # DID is on this TEG's external blocklist. Phase 7 wired the AgentSuspended
    # reactor to populate the blocklist; Phase 8 makes the blocklist
    # load-bearing at the protocol-edge.
    for did, role in (
        (request.source_agent_id, "source"),
        (request.target_agent_id, "target"),
    ):
        if await is_externally_blocked(did):
            logger.warning(
                f"[CrossTEG] /transfer refused — {role} agent {did} on external blocklist"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "AGENT_BLOCKED",
                    "role": role,
                    "agent_did": did,
                    "message": (
                        f"Cross-TEG transfer refused: {role} agent is on this TEG's "
                        f"external blocklist."
                    ),
                },
            )

    try:
        # Use the coordinator for distributed transaction
        response = await transaction_coordinator.coordinate_transfer(request)

        if not response.success:
            # Insufficient balance is a client/business condition → 402, NOT a 500.
            # (Previously every failure here raised 400 and was then swallowed by the
            #  broad `except Exception` below → re-raised as 500 "Failed to process
            #  transfer" — which is what surfaced cross-frame/FX/passport funding
            #  shortfalls as alarming 5xx. The `except HTTPException: raise` guard
            #  below now lets these intended 4xx through unchanged.)
            if (getattr(response, "error_code", "") or "") == "INSUFFICIENT_BALANCE":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=response.message or "Insufficient balance",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response.message
            )

        return response

    except HTTPException:
        # Intended 4xx (insufficient-balance 402, business 400, blocklist 403) must NOT
        # be re-wrapped as a 500 by the generic handler below.
        raise
    except Exception as e:
        logger.error(f"Failed to initiate cross-TEG transfer: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process transfer"
        )


@router.post("/accept", response_model=TransferAcceptResponse)
async def accept_cross_teg_transfer(
    http_request: Request,
    request: TransferAcceptRequest,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
    local_caller: str = Depends(_local_caller_dependency("accept")),
    db: AsyncSession = Depends(get_db)
):
    """
    Accept an incoming cross-TEG transfer.

    This endpoint is called by the source TEG to request this TEG
    to accept an incoming transfer. Authenticated via mTLS SPIFFE identity
    or partner API key.
    """

    # Phase 8 (2026-04-27): refuse incoming cross-TEG transfer when the
    # recipient DID is on this TEG's external blocklist.
    if await is_externally_blocked(request.recipient_agent_id):
        logger.warning(
            f"[CrossTEG] /accept refused — recipient {request.recipient_agent_id} "
            f"on external blocklist"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AGENT_BLOCKED",
                "role": "recipient",
                "agent_did": request.recipient_agent_id,
                "message": (
                    "Incoming cross-TEG transfer refused: recipient is on this "
                    "TEG's external blocklist."
                ),
            },
        )

    try:
        response = await transfer_protocol.accept_transfer(request)
        
        if not response.accepted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response.error
            )
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to accept cross-TEG transfer: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept transfer"
        )


# =============================================================================
# PB-2 (2026-05-10) — Cross-TEG treasury fund receiver
#
# Treasury-to-treasury internal plumbing. Mainframe TEG calls this on a
# satellite/operator TEG via mTLS through nginx-federation. Architecturally
# fee-EXEMPT: treasury-to-treasury moves are protocol primitives, not market
# transactions. Anti-abuse: mTLS-only auth (`_validate_cross_teg_auth`),
# idempotent on `correlation_id`, hardcoded sender/receiver IDs prevent
# repurposing as agent-to-agent trading bypass.
# =============================================================================
from decimal import Decimal as _Decimal
from pydantic import BaseModel as _BaseModel, Field as _Field, field_validator as _fv
from datetime import datetime as _dt, timezone as _tz


class TreasuryFundReceiveRequest(_BaseModel):
    """Cross-TEG treasury fund receive request."""
    amount: _Decimal = _Field(..., gt=0, description="AVT to credit to local treasury")
    source_teg_id: str = _Field(..., description="Source TEG identifier (caller)")
    correlation_id: str = _Field(..., description="Idempotency anchor — used as TEGTransaction.transaction_id")
    reason: str = _Field(default="cross_teg_fund", description="Reason tag for audit trail")

    @_fv("amount")
    def _validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    class Config:
        json_encoders = {_Decimal: lambda v: str(v)}


class TreasuryFundReceiveResponse(_BaseModel):
    """Cross-TEG treasury fund receive response."""
    transaction_id: str
    status: str
    amount: _Decimal
    direction: str = "credit"
    new_treasury_balance: _Decimal
    correlation_id: str
    timestamp: _dt
    idempotent_replay: bool = False

    class Config:
        json_encoders = {_Decimal: lambda v: str(v)}


@router.post("/treasury-fund", response_model=TreasuryFundReceiveResponse)
async def receive_cross_teg_treasury_fund(
    http_request: Request,
    request: TreasuryFundReceiveRequest,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
    db=Depends(get_db),  # SYNC Session (get_db is sync; type annotation kept loose)
):
    """Credit local treasury from inbound cross-TEG fund (PB-2 routed-fiat).

    Auth: mTLS SPIFFE (primary) or API key fallback for internal Docker network.
    Idempotency: correlation_id maps 1:1 to TEGTransaction.transaction_id.
    Replay returns the existing record without re-crediting.

    Used for treasury-to-treasury moves (mainframe → operator) — fee-exempt
    by architectural intent. Agent-to-agent transfers MUST use /transfer or
    /credit-async (which charge fees and gate via different auth paths).
    """
    # NOTE: db is a SYNC Session here (the `get_db` dep returns sync session).
    # Mirrors the pattern in api/v1/endpoints_treasury.py:treasury_external_credit
    # (async def + sync DB session + asyncio.create_task for event emit).
    from ..database.models import AgentTEGProfile, TEGTransaction, SystemConfig
    from ..database.crud import AgentCRUD, SystemConfigCRUD

    spiffe_id = _validate_cross_teg_auth(http_request, authorization)
    # §SECFIX-3 (2026-09-25): only this treasury's configured sources may credit it (default: its own trust domain, i.e.
    # its frame, or its parent frame for an operator). A federated peer is an internal caller on the other cross-TEG
    # routes, where it legitimately settles transfers; it is not a treasury funder.
    from ..core.internal_auth import treasury_fund_source_ok, treasury_fund_sources
    if not treasury_fund_source_ok(spiffe_id):
        logger.warning(
            f"[CrossTEG/treasury-fund] REFUSED caller={spiffe_id} src={request.source_teg_id} "
            f"amount={request.amount} corr={request.correlation_id} sources={treasury_fund_sources()}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="treasury_fund_source_refused: this treasury is funded only by its configured sources "
                   "(CROSS_TEG_TREASURY_FUND_SOURCES, default its own trust domain)",
        )
    logger.info(
        f"[CrossTEG/treasury-fund] from spiffe={spiffe_id} "
        f"src={request.source_teg_id} amount={request.amount} corr={request.correlation_id}"
    )

    # ── Idempotency: replay same correlation_id returns existing record ──
    existing = db.query(TEGTransaction).filter(
        TEGTransaction.transaction_id == request.correlation_id
    ).first()
    if existing is not None:
        treasury_did = SystemConfigCRUD.get_treasury_did(db)
        cur_bal = AgentCRUD.get_balance(db, treasury_did)
        logger.info(
            f"[CrossTEG/treasury-fund] IDEMPOTENT replay corr={request.correlation_id} "
            f"existing_status={existing.status} treasury_balance={cur_bal}"
        )
        return TreasuryFundReceiveResponse(
            transaction_id=existing.transaction_id,
            status=existing.status if isinstance(existing.status, str) else "completed",
            amount=existing.amount,
            direction="credit",
            new_treasury_balance=cur_bal,
            correlation_id=request.correlation_id,
            timestamp=existing.timestamp,
            idempotent_replay=True,
        )

    # ── Resolve treasury DID + get/create treasury account ──
    treasury_did = SystemConfigCRUD.get_treasury_did(db)
    treasury = AgentCRUD.get_or_create(db, treasury_did)

    # ── Credit treasury ──
    treasury.token_balance = (treasury.token_balance or _Decimal("0")) + request.amount
    treasury.audited_balance = treasury.token_balance

    # ── Create transaction record (idempotency anchor) ──
    transaction = TEGTransaction(
        transaction_id=request.correlation_id,
        sender_agent_id=f"cross-teg:{request.source_teg_id}",
        receiver_agent_id=treasury_did,
        amount=request.amount,
        fee_amount=_Decimal("0"),  # treasury-to-treasury fee-exempt
        status="completed",
        transaction_type=f"cross_teg_inflow_{request.reason}"[:50],
        attached_message=(
            f"Cross-TEG treasury-fund ← {request.source_teg_id} | "
            f"corr:{request.correlation_id} | spiffe:{spiffe_id[:80]}"
        ),
    )
    db.add(transaction)
    db.commit()
    db.refresh(treasury)

    new_balance = treasury.token_balance

    # ── Emit TokensTransferred event (fire-and-forget) ──
    try:
        from .v1.endpoints_treasury import _emit_treasury_transfer_event
        asyncio.create_task(_emit_treasury_transfer_event(
            sender_id=f"cross-teg:{request.source_teg_id}",
            receiver_id=treasury_did,
            amount=str(request.amount),
            transaction_id=request.correlation_id,
            memo=f"cross_teg_treasury_fund:{request.reason}",
        ))
    except Exception as e:
        logger.error(f"[CrossTEG/treasury-fund] Event emit schedule failed: {e}")

    logger.info(
        f"CROSS-TEG TREASURY-FUND CREDIT: {request.amount} AVT ← {request.source_teg_id} "
        f"(treasury now: {new_balance}, corr: {request.correlation_id})"
    )

    return TreasuryFundReceiveResponse(
        transaction_id=request.correlation_id,
        status="completed",
        amount=request.amount,
        direction="credit",
        new_treasury_balance=new_balance,
        correlation_id=request.correlation_id,
        timestamp=transaction.timestamp or _dt.now(_tz.utc),
        idempotent_replay=False,
    )


@router.post("/prepare/{transfer_id}")
async def prepare_transfer(
    request: Request,
    transfer_id: str,
    request_data: Dict[str, Any],
    authorization: Optional[str] = Security(_cross_teg_auth_header),
    db: AsyncSession = Depends(get_db)
):
    """
    Prepare for an incoming transfer (two-phase commit).

    This is part of the distributed transaction protocol.
    """
    caller = _validate_cross_teg_auth(request, authorization)
    # §SECFIX-12 (2026-09-25): a foreign trust domain's daily inbound is bounded (observe by default), counted here,
    # before anything is prepared or credited; own-domain callers are not counted (core/cross_teg/peer_inbound.py)
    from ..core.cross_teg import peer_inbound as _peer_inbound
    _ok, _detail = await _peer_inbound.admit(caller, (request_data or {}).get("amount"), transfer_id)
    if not _ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_detail)
    logger.info(f"[CrossTEG] prepare transfer={transfer_id} caller={caller} amount={(request_data or {}).get('amount')} "
                f"source_teg={(request_data or {}).get('source_teg_id')} inbound={_detail}")

    try:
        # Handle prepare request
        await transaction_coordinator.handle_incoming_message(
            "prepare_request",
            {
                "transfer_id": transfer_id,
                "data": request_data,
                "auth_token": (authorization or "")[7:]
            }
        )
        
        return {"status": "prepared", "transfer_id": transfer_id}
        
    except Exception as e:
        logger.error(f"Failed to prepare transfer {transfer_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare transfer"
        )


@router.post("/commit/{transfer_id}")
async def commit_transfer(
    request: Request,
    transfer_id: str,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
    db: AsyncSession = Depends(get_db)
):
    """
    Commit a prepared transfer (two-phase commit).

    This finalizes the transfer on this TEG.
    """
    _validate_cross_teg_auth(request, authorization)

    try:
        # Handle commit request
        await transaction_coordinator.handle_incoming_message(
            "commit_request",
            {
                "transfer_id": transfer_id,
                "auth_token": (authorization or "")[7:]
            }
        )
        
        return {"status": "committed", "transfer_id": transfer_id}
        
    except Exception as e:
        logger.error(f"Failed to commit transfer {transfer_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to commit transfer"
        )


@router.post("/abort/{transfer_id}")
async def abort_transfer(
    request: Request,
    transfer_id: str,
    reason: Dict[str, str],
    authorization: Optional[str] = Security(_cross_teg_auth_header),
    db: AsyncSession = Depends(get_db)
):
    """
    Abort a prepared transfer (two-phase commit).

    This rolls back any prepared state.
    """
    _validate_cross_teg_auth(request, authorization)

    try:
        # Handle abort request
        await transaction_coordinator.handle_incoming_message(
            "abort_request",
            {
                "transfer_id": transfer_id,
                "reason": reason.get("reason", "Unknown"),
                "auth_token": (authorization or "")[7:]
            }
        )
        
        return {"status": "aborted", "transfer_id": transfer_id}
        
    except Exception as e:
        logger.error(f"Failed to abort transfer {transfer_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to abort transfer"
        )


@router.get("/transfer/{transfer_id}")
async def get_transfer_status(
    transfer_id: str,
    current_agent_id: str = Security(get_current_agent),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the status of a cross-TEG transfer.
    
    Returns the current state and details of the transfer.
    """
    try:
        # Check coordination status
        coordination_status = await transaction_coordinator.get_coordination_status(
            transfer_id
        )
        
        if not coordination_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transfer not found"
            )
        
        # Verify the user is authorized to view this transfer
        request = coordination_status.get("request")
        if request and current_agent_id not in [
            request.source_agent_id,
            request.target_agent_id
        ]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this transfer"
            )
        
        return {
            "transfer_id": transfer_id,
            "status": coordination_status.get("phase"),
            "decision": coordination_status.get("decision"),
            "started_at": coordination_status.get("started_at"),
            "completed_at": coordination_status.get("completed_at"),
            "participants": coordination_status.get("participants")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get transfer status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get transfer status"
        )


@router.get("/health")
async def cross_teg_health_check():
    """
    Health check for cross-TEG functionality.
    
    Returns the status of cross-TEG communication capabilities.
    """
    health_status = {
        "status": "healthy",
        "teg_id": settings.teg_id,
        "cross_teg_enabled": settings.cross_teg_enabled,
        "protocol_ready": transfer_protocol is not None,
        "coordinator_ready": transaction_coordinator is not None,
        "active_coordinations": 0
    }
    
    if transaction_coordinator:
        health_status["active_coordinations"] = len(
            transaction_coordinator.active_coordinations
        )
    
    # Check connected TEGs
    if teg_client_factory and settings.parsed_partner_tegs:
        connected_tegs = []
        for partner in settings.parsed_partner_tegs:
            client = teg_client_factory.get_client(
                partner["teg_id"],
                partner["url"]
            )
            if await client.health_check():
                connected_tegs.append(partner["teg_id"])
        
        health_status["connected_tegs"] = connected_tegs
    
    return health_status


@router.get("/config")
async def get_cross_teg_config(
    admin_auth: AdminAuth
):
    """
    Get cross-TEG configuration.
    
    Returns the current configuration for cross-TEG transfers.
    Admin access required.
    """
    
    return {
        "teg_id": settings.teg_id,
        "cross_teg_enabled": settings.cross_teg_enabled,
        "partner_tegs": [
            {
                "teg_id": partner["teg_id"],
                "registry_id": partner.get("registry_id", ""),
                "status": "configured"
            }
            for partner in (settings.parsed_partner_tegs or [])
        ] + [
            {
                "teg_id": partner["teg_id"],
                "registry_id": partner.get("registry_id", ""),
                "status": "runtime"
            }
            for partner in _runtime_partners
        ],
        "transfer_timeout": 300,  # 5 minutes
        "max_transfer_amount": "10000.0",
        "supported_currencies": ["TEG"]
    }


@router.post("/config/add-partner")
async def add_partner_teg(
    partner: Dict[str, str],
    admin_auth: AdminAuth
):
    """Hot-add a partner TEG at runtime. No restart needed.

    Requires admin auth. The new partner is immediately available for
    cross-TEG transfers. mTLS authentication is used (no API key needed).

    Body: { "teg_id": "teg-layer-xyz", "registry_id": "registry-xyz", "url": "https://domain:port" }
    """
    teg_id = partner.get("teg_id")
    url = partner.get("url")
    registry_id = partner.get("registry_id", "")
    api_key = partner.get("api_key", "none")

    if not teg_id or not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="teg_id and url are required"
        )

    # Check if already exists in static config or runtime list
    all_partners = list(settings.parsed_partner_tegs) + _runtime_partners
    existing = next((p for p in _runtime_partners if p["teg_id"] == teg_id), None)
    if existing:
        existing["url"] = url
        existing["registry_id"] = registry_id
        # §pass47 A4 — mirror update so other workers see the new URL on next refresh.
        await set_partner_in_redis(teg_id, existing)
        logger.info(f"[CrossTEG] Updated runtime partner: {teg_id} → {url}")
        return {"status": "updated", "teg_id": teg_id, "total_partners": len(all_partners)}

    static_exists = any(p["teg_id"] == teg_id for p in settings.parsed_partner_tegs)
    if static_exists:
        logger.info(f"[CrossTEG] Partner {teg_id} already in static config")
        return {"status": "exists", "teg_id": teg_id, "total_partners": len(all_partners)}

    new_partner = {"teg_id": teg_id, "registry_id": registry_id, "url": url, "api_key": api_key}
    _runtime_partners.append(new_partner)

    # §pass47 A4 — mirror to Redis so other workers learn about this partner
    # on their next refresh cycle (every 30s, started in main.py lifespan).
    await set_partner_in_redis(teg_id, new_partner)

    # Pre-register client for immediate availability
    if teg_client_factory:
        teg_client_factory.get_client(teg_id, url)

    total = len(settings.parsed_partner_tegs) + len(_runtime_partners)
    logger.info(f"[CrossTEG] Hot-added partner: {teg_id} → {url} (total: {total})")
    return {"status": "added", "teg_id": teg_id, "total_partners": total}


@router.post("/config/remove-partner")
async def remove_partner_teg(
    partner: Dict[str, str],
    admin_auth: AdminAuth
):
    """Hot-remove a partner TEG from the runtime list. Idempotent — never returns 4xx
    on missing partner so reactor backlog replay does not trigger error storms.

    Body: { "teg_id": "teg-foo" }
    Tri-state response:
      - removed:          teg_id was in _runtime_partners; dropped + cached client closed
      - static_immutable: teg_id is only in env-var PARTNER_TEGS config; cannot mutate at runtime
      - not_found:        teg_id not present in either list (idempotent restart-replay safe)
    """
    teg_id = partner.get("teg_id")
    if not teg_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="teg_id is required"
        )

    # Drop from runtime list if present
    runtime_idx = next(
        (i for i, p in enumerate(_runtime_partners) if p["teg_id"] == teg_id),
        None,
    )
    # §pass47 A4 — always attempt Redis delete first; with multiple workers the
    # POST-add may have hit a different worker than this remove, so the local
    # _runtime_partners list might miss the entry even though Redis still has it.
    redis_had_entry = await delete_partner_in_redis(teg_id)

    if runtime_idx is not None:
        _runtime_partners.pop(runtime_idx)
        if teg_client_factory:
            try:
                await teg_client_factory.remove_client(teg_id)
            except Exception as e:
                logger.warning(f"[CrossTEG] Cached client close failed for {teg_id}: {e}")
        total = len(settings.parsed_partner_tegs) + len(_runtime_partners)
        logger.info(f"[CrossTEG] Removed runtime partner: {teg_id} (total: {total})")
        return {"status": "removed", "teg_id": teg_id, "total_partners": total}

    if redis_had_entry:
        # Local worker hadn't observed this partner (cross-worker race), but Redis
        # had it and we just dropped it. Treat as removed.
        total = len(settings.parsed_partner_tegs) + len(_runtime_partners)
        logger.info(
            f"[CrossTEG] Removed runtime partner from Redis only (cross-worker race): "
            f"{teg_id} (total: {total})"
        )
        return {"status": "removed", "teg_id": teg_id, "total_partners": total}

    # Static config — cannot mutate at runtime
    static_exists = any(p["teg_id"] == teg_id for p in settings.parsed_partner_tegs)
    if static_exists:
        total = len(settings.parsed_partner_tegs) + len(_runtime_partners)
        logger.warning(
            f"[CrossTEG] remove-partner called for {teg_id} but it is in static "
            f"PARTNER_TEGS env config — runtime mutation not supported"
        )
        return {"status": "static_immutable", "teg_id": teg_id, "total_partners": total}

    # Neither — idempotent no-op
    total = len(settings.parsed_partner_tegs) + len(_runtime_partners)
    logger.debug(f"[CrossTEG] remove-partner: {teg_id} not found (idempotent)")
    return {"status": "not_found", "teg_id": teg_id, "total_partners": total}


# ---------------------------------------------------------------------------
# External agent blocklist (Phase 7 + Phase 11.1 Redis migration)
# ---------------------------------------------------------------------------
# When an agent is suspended on a partner registry, the AgentSuspended reactor
# calls into this TEG to add the DID to the local blocklist. Cross-TEG
# transfers and accept/prepare/commit calls that target a blocked DID are
# refused at the protocol-edge.
#
# Phase 11.1 (2026-04-28): Redis SET as the canonical store, in-memory set as
# the fallback when Redis is unreachable. Cross-worker propagation is now
# uniform — block on any worker is visible to all workers within sub-ms via
# Redis SISMEMBER. The Phase 7-era `block 4×` workaround in the test flow
# becomes unnecessary.

_external_blocklist: Set[str] = set()  # Local fallback only — Redis is canonical


def _blocklist_key() -> str:
    """Redis key for this TEG's external blocklist SET. Namespaced by TEG_ID
    so prod + sandbox sharing the same Redis stay isolated."""
    teg_name = (os.getenv("TEG_ID") or os.getenv("TEG_NAME") or "default").lower().replace(" ", "-")
    return f"teg:blocklist:{teg_name}"


async def _redis_blocklist_add(agent_did: str) -> Optional[bool]:
    """Add to Redis SET. Returns True if newly added, False if already present,
    None if Redis unreachable. Caller falls back to local set on None."""
    try:
        from ..redis_client import get_redis
        r = await get_redis()
        if r is None:
            return None
        added = await r.sadd(_blocklist_key(), agent_did)
        return bool(added)
    except Exception as e:
        logger.warning(f"[CrossTEG] Redis SADD failed for {agent_did}: {e}")
        return None


async def _redis_blocklist_remove(agent_did: str) -> Optional[bool]:
    """Remove from Redis SET. Returns True if removed, False if not present,
    None if Redis unreachable."""
    try:
        from ..redis_client import get_redis
        r = await get_redis()
        if r is None:
            return None
        removed = await r.srem(_blocklist_key(), agent_did)
        return bool(removed)
    except Exception as e:
        logger.warning(f"[CrossTEG] Redis SREM failed for {agent_did}: {e}")
        return None


async def _redis_blocklist_contains(agent_did: str) -> Optional[bool]:
    """Check Redis SET. Returns True/False, or None if Redis unreachable."""
    try:
        from ..redis_client import get_redis
        r = await get_redis()
        if r is None:
            return None
        present = await r.sismember(_blocklist_key(), agent_did)
        return bool(present)
    except Exception as e:
        logger.warning(f"[CrossTEG] Redis SISMEMBER failed for {agent_did}: {e}")
        return None


async def _redis_blocklist_members() -> Optional[Set[str]]:
    """Return all members. None if Redis unreachable."""
    try:
        from ..redis_client import get_redis
        r = await get_redis()
        if r is None:
            return None
        members = await r.smembers(_blocklist_key())
        return set(members) if members else set()
    except Exception as e:
        logger.warning(f"[CrossTEG] Redis SMEMBERS failed: {e}")
        return None


@router.post("/admin/agents/{agent_did:path}/block")
async def block_external_agent(
    agent_did: str,
    admin_auth: AdminAuth,
    body: Optional[Dict[str, Any]] = None,
):
    """Add a DID to the external blocklist. Idempotent — never 4xx on
    already-blocked so reactor backlog replay is safe.

    Storage: Redis SET (canonical, cross-worker visible) with in-memory set as
    fallback if Redis is unreachable.

    Body (optional): { "reason": "...", "actor": "..." } — logged for audit.
    Response: { "status": "blocked"|"already_blocked", "agent_did": "...",
                "blocklist_size": N, "backend": "redis"|"local" }
    """
    if not agent_did:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_did path param required",
        )
    body = body or {}
    reason = body.get("reason", "unspecified")
    actor = body.get("actor", "reactor")

    redis_added = await _redis_blocklist_add(agent_did)
    if redis_added is not None:
        # Mirror in local set so is_externally_blocked() has a hot path even
        # if Redis blips before the next call.
        _external_blocklist.add(agent_did)
        members = await _redis_blocklist_members()
        size = len(members) if members is not None else len(_external_blocklist)
        if redis_added:
            logger.info(
                f"[CrossTEG] block_agent: added {agent_did} (Redis)"
                f" reason={reason!r} actor={actor!r} total={size}"
            )
            return {
                "status": "blocked",
                "agent_did": agent_did,
                "blocklist_size": size,
                "backend": "redis",
            }
        return {
            "status": "already_blocked",
            "agent_did": agent_did,
            "blocklist_size": size,
            "backend": "redis",
        }

    # Redis offline — degrade to per-worker local set
    if agent_did in _external_blocklist:
        return {
            "status": "already_blocked",
            "agent_did": agent_did,
            "blocklist_size": len(_external_blocklist),
            "backend": "local",
        }
    _external_blocklist.add(agent_did)
    logger.info(
        f"[CrossTEG] block_agent: added {agent_did} (LOCAL — Redis offline)"
        f" reason={reason!r} actor={actor!r} total={len(_external_blocklist)}"
    )
    return {
        "status": "blocked",
        "agent_did": agent_did,
        "blocklist_size": len(_external_blocklist),
        "backend": "local",
    }


@router.post("/admin/agents/{agent_did:path}/unblock")
async def unblock_external_agent(
    agent_did: str,
    admin_auth: AdminAuth,
    body: Optional[Dict[str, Any]] = None,
):
    """Remove a DID from the external blocklist. Idempotent.

    Body (optional): { "reason": "...", "actor": "..." } — audit-only.
    Response: { "status": "unblocked"|"not_blocked", "agent_did": "...",
                "blocklist_size": N, "backend": "redis"|"local" }
    """
    if not agent_did:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_did path param required",
        )
    body = body or {}
    reason = body.get("reason", "unspecified")
    actor = body.get("actor", "reactor")

    redis_removed = await _redis_blocklist_remove(agent_did)
    if redis_removed is not None:
        _external_blocklist.discard(agent_did)
        members = await _redis_blocklist_members()
        size = len(members) if members is not None else len(_external_blocklist)
        if redis_removed:
            logger.info(
                f"[CrossTEG] unblock_agent: removed {agent_did} (Redis)"
                f" reason={reason!r} actor={actor!r} total={size}"
            )
            return {
                "status": "unblocked",
                "agent_did": agent_did,
                "blocklist_size": size,
                "backend": "redis",
            }
        return {
            "status": "not_blocked",
            "agent_did": agent_did,
            "blocklist_size": size,
            "backend": "redis",
        }

    # Redis offline
    if agent_did not in _external_blocklist:
        return {
            "status": "not_blocked",
            "agent_did": agent_did,
            "blocklist_size": len(_external_blocklist),
            "backend": "local",
        }
    _external_blocklist.discard(agent_did)
    logger.info(
        f"[CrossTEG] unblock_agent: removed {agent_did} (LOCAL — Redis offline)"
        f" reason={reason!r} actor={actor!r} total={len(_external_blocklist)}"
    )
    return {
        "status": "unblocked",
        "agent_did": agent_did,
        "blocklist_size": len(_external_blocklist),
        "backend": "local",
    }


@router.get("/admin/agents/blocklist")
async def list_external_blocklist(admin_auth: AdminAuth):
    """List all DIDs on the external blocklist. Reads from Redis if available,
    falls back to local set."""
    members = await _redis_blocklist_members()
    if members is not None:
        return {
            "size": len(members),
            "agents": sorted(members),
            "backend": "redis",
        }
    return {
        "size": len(_external_blocklist),
        "agents": sorted(_external_blocklist),
        "backend": "local",
    }


async def is_externally_blocked(agent_did: str) -> bool:
    """Public async predicate used at the cross-TEG protocol edge to refuse
    transfers for blocked DIDs. Reads canonically from Redis SISMEMBER; falls
    back to per-worker local set if Redis is unreachable."""
    redis_present = await _redis_blocklist_contains(agent_did)
    if redis_present is not None:
        return redis_present
    return agent_did in _external_blocklist


# ---------------------------------------------------------------------------
# Emission policy cache refresh (Phase 9.2 — reactor-driven invalidation)
# ---------------------------------------------------------------------------
# When an admin updates an event_emission_policies row via the registry's PUT
# endpoint, the registry emits `EventEmissionPolicyUpdated`. The Phase 9.2
# reactor calls this endpoint to force TEG's `_teg_policy_cache` to refresh
# immediately (vs waiting up to 120s for the next TTL-driven refresh).
#
# Per-worker semantic (matches `_external_blocklist` and `_runtime_partners`):
# the call lands on one TEG worker and refreshes that worker's cache. Other
# workers self-heal at their next 120s TTL boundary. Multiple calls cover
# more workers; Redis-backed cache would make this fully uniform (Phase 10).

@router.post("/admin/emission-policy/refresh")
async def refresh_emission_policy_cache(admin_auth: AdminAuth):
    """Force-refresh emission policy cache from Registry API.

    Phase 11.1: This worker fetches fresh policies, then publishes a Redis
    invalidation so every OTHER TEG worker drops its local cache and refetches
    on next emit(). Net result: a single call propagates to all workers within
    sub-second.

    Response: { status, policy_count, refreshed_at, worker_pid, fanout: bool }
    """
    from ..event_emitter import _fetch_teg_policies, _teg_policy_cache, _teg_policy_cache_ts
    from ..event_emitter import publish_emission_policy_invalidation

    await _fetch_teg_policies()

    fanout_ok = False
    try:
        await publish_emission_policy_invalidation()
        fanout_ok = True
    except Exception as e:
        logger.warning(f"[CrossTEG] emission-policy invalidation publish failed: {e}")

    return {
        "status": "refreshed",
        "policy_count": len(_teg_policy_cache),
        "refreshed_at": _teg_policy_cache_ts,
        "worker_pid": os.getpid(),
        "fanout": fanout_ok,
    }


# ---------------------------------------------------------------------------
# ASYNC CROSS-FRAME TRANSFER ENDPOINTS (TEG_CROSS_FRAME_BACKEND=async, 2026-05-03)
# ---------------------------------------------------------------------------
# 4 endpoints invoked by the registry layer and reactors (event-driven async
# cross-frame transfer path). All authenticated via TEG_ADMIN_API_KEY (matches
# accept/prepare/commit auth pattern). All idempotent on transfer_id via
# CrossTEGTransfer.merge().
#
# Sender side:
#   POST /cross-teg/lock-async    — deduct from sender (called at entry)
#   POST /cross-teg/refund-async  — restore sender (called by saga sweep)
#
# Receiver side:
#   POST /cross-teg/credit-async  — credit recipient + fee_collector
#                                    (called by reactor_cross_frame_initiated)
#   POST /cross-teg/reverse-async — debit recipient + fee_collector
#                                    (called by reactor_cross_frame_refunded)
#
# All four perform direct DB writes via transfer_protocol._get_session() —
# matches accept_transfer's pattern (no transfer_service intermediation).
# Idempotency: merged CrossTEGTransfer row by transfer_id; if already present
# in target/source-completed status, returns success without re-debit/credit.
# ---------------------------------------------------------------------------

from decimal import Decimal as _Decimal
from datetime import datetime as _datetime, timezone as _timezone, timedelta as _timedelta

from ..database.models import (
    AgentTEGProfile as _AgentTEGProfile,
    TEGTransaction as _TEGTransaction,
    TransactionType as _TransactionType,
    TransactionStatus as _TransactionStatus,
    CrossTEGTransfer as _CrossTEGTransfer,
    CrossTEGTransferStatus as _CrossTEGTransferStatus,
)
from ..database.crud import SystemConfigCRUD as _SystemConfigCRUD, AgentCRUD as _AgentCRUD
from sqlalchemy import select as _select, text as _text


_CROSS_REG_FEE_RATE = _Decimal("0.5")  # percent — matches accept_transfer


# §2026-06-17 — deterministic DISTINCT id for the cross-TEG RECEIVE (credit) leg.
# The SEND leg (lock-async / 2PC debit) keeps transaction_id = transfer_id. Forcing the
# RECEIVE leg to ALSO use transfer_id (old §PlanB-②) made the two legs collide on the
# teg_transactions PK whenever sender-home == receiver-home (same-TEG passport hairpin)
# → IntegrityError + a caller retry storm the §10 in-handler retry could NOT converge
# (the send row is permanent, not a transient race). Fix: derive a SEPARATE id for the
# receive leg.
#   • DETERMINISTIC (uuid5, NOT uuid4) is load-bearing — under a TRUE concurrent credit
#     race it preserves the PK-collision dedup that prevents a double-credit (Δ-breach);
#     a random uuid4 would let both batches commit prof.token_balance += credit.
#   • uuid5 is exactly 36 chars → fits Column(String(36)); a "{tid}:r" suffix (38) would
#     overflow → "value too long for character varying(36)".
#   • SAFE vs ES/idempotency: the ES TokensTransferred transaction_id and dedup key
#     xfer-{transfer_id} are REGISTRY-side and independent of this TEG row PK; ES supply
#     math keys on event `kind`/agent_did (never transaction_id); the async credit
#     idempotency anchor is cross_teg_transfers(role=target,COMPLETED), NOT this PK; and
#     no reader resolves the receive leg by the bare tid (getTegTransactionDetail/history
#     are ES-sourced). So this rename is invisible to Δ, ES dedup, and idempotency.
# Scope: async path only (credit-async, credit-async-bulk). The 2PC accept_transfer path
# (protocol.py) is intentionally left as-is — it is not failing and its same-TEG hairpin
# is unreachable (same-frame transfers use local /teg/transfer, never cross-TEG).
def _recv_leg_txid(transfer_id: str) -> str:
    """Deterministic, distinct teg_transactions PK for a cross-TEG receive (credit) leg."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"theprotocol:cross_teg:receive_leg:{transfer_id}"))


# Vector C (2026-05-04) — opt-in flag for async SQLAlchemy on /credit-async-bulk
# only. When true, the hot path uses AsyncSessionLocal (asyncpg driver). When
# false, the existing sync path runs unchanged. Other endpoints stay sync.
_TEG_BULK_USE_ASYNC_DB = os.environ.get("TEG_BULK_USE_ASYNC_DB", "false").lower() == "true"


@router.post("/lock-async")
async def lock_async(
    payload: Dict[str, Any],
    http_request: Request,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
):
    """Sender-side lock — deducts amount from sender's token_balance. Idempotent.

    Called by the registry's async cross-frame entry endpoint. The deduction
    is unconditional (no fee here — fee is on receiver side, matching 2PC
    accept_transfer). Refunded if saga timeout fires.
    """
    _require_local_caller(http_request, authorization, "lock-async")

    transfer_id = payload.get("transfer_id")
    sender_did = payload.get("sender_did")
    amount_str = payload.get("amount", "0")
    if not (transfer_id and sender_did):
        raise HTTPException(400, "Missing transfer_id or sender_did")
    try:
        amount = _Decimal(str(amount_str))
    except Exception:
        raise HTTPException(400, "Invalid amount")
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    # Phase 8 (2026-05-04): async session + cancel-safe rollback. Mirrors Vector C
    # pattern in `_credit_async_bulk_async`. Sync session inside async function
    # leaked idle-in-tx connections under client-cancel — wedged TEG worker
    # until pg_terminate_backend. async with + try/except BaseException +
    # asyncio.shield(session.rollback()) ensures rollback fires on cancellation.
    from ..database.db_session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            existing = (await session.execute(
                _select(_CrossTEGTransfer).where(
                    _CrossTEGTransfer.transfer_id == transfer_id
                )
            )).scalar_one_or_none()
            if existing is not None and existing.role == "source":
                logger.info(f"[CrossTEG/lock-async] {transfer_id} already locked — idempotent")
                return {"status": "already_locked", "transfer_id": transfer_id}

            profile = (await session.execute(
                _select(_AgentTEGProfile).where(_AgentTEGProfile.agent_id == sender_did)
            )).scalar_one_or_none()
            if profile is None:
                raise HTTPException(404, f"Sender {sender_did} not found on this TEG")
            if profile.token_balance < amount:
                raise HTTPException(400, f"Insufficient balance: {profile.token_balance} < {amount}")

            # §MONEY-R18 (async sibling, found 2026-09-04 by DRIVING the async backend live):
            # this is a direct-ORM balance mutation, exactly the shape R18 fixed in
            # bulk_transfer_tokens. `balance_ledger_journal.entry_type` DEFAULTS to 'unknown',
            # so an unstamped write lands in the largest, least useful bucket and
            # materialized_balances.sql files it under transit_net. Δ still reads 0.0 — which is
            # precisely why nothing caught it until a real async transfer was driven end to end.
            # Mirrors protocol.py's cross_teg_escrow_lock stamping.
            await session.execute(
                _text("SELECT set_config('teg.entry_type','cross_teg_lock_async',true),"
                      "       set_config('teg.entry_ref', :r, true)"),
                {"r": str(transfer_id)[:160]},
            )
            profile.token_balance -= amount
            profile.audited_balance = profile.token_balance

            tx = _TEGTransaction(
                transaction_id=transfer_id,  # §PlanB-②: align leg id with ES TokensTransferred.data.transaction_id
                sender_agent_id=sender_did,
                receiver_agent_id="teg:system:cross_frame_escrow",
                amount=amount,
                fee_amount=_Decimal("0"),
                transaction_type=_TransactionType.CROSS_TEG_SEND.value,
                status=_TransactionStatus.COMPLETED,
            )
            session.add(tx)

            record = _CrossTEGTransfer(
                transfer_id=transfer_id,
                correlation_id=payload.get("correlation_id", transfer_id),
                source_teg_id=settings.teg_id,
                source_registry_id=payload.get("source_registry_id", "unknown"),
                source_agent_id=sender_did,
                target_teg_id=payload.get("target_teg_id", "unknown"),
                target_registry_id=payload.get("target_registry_id", "unknown"),
                target_agent_id=payload.get("receiver_did", "unknown"),
                amount=amount,
                status=_CrossTEGTransferStatus.FUNDS_LOCKED,
                role="source",
                expires_at=_datetime.now(_timezone.utc) + _timedelta(minutes=5),
            )
            await session.merge(record)
            await session.commit()
        except HTTPException:
            # Domain errors (404/400) — let FastAPI handle; session rollback by ctxmgr
            raise
        except BaseException as exc:
            try:
                await asyncio.shield(session.rollback())
            except BaseException as rb_exc:
                logger.warning(
                    f"[CrossTEG/lock-async] rollback after "
                    f"{type(exc).__name__} failed: {type(rb_exc).__name__}"
                )
            raise

    return {"status": "locked", "transfer_id": transfer_id, "amount": str(amount)}


@router.post("/credit-async")
async def credit_async(
    payload: Dict[str, Any],
    http_request: Request,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
):
    """Receiver-side credit — credits recipient + 0.5% fee to fee_collector. Idempotent.

    Called by reactor_cross_frame_initiated after catching the cross-frame
    Initiated event. Mirrors accept_transfer's balance arithmetic.
    """
    _require_local_caller(http_request, authorization, "credit-async")

    transfer_id = payload.get("transfer_id")
    sender_did = payload.get("sender_did")
    receiver_did = payload.get("receiver_did")
    amount_str = payload.get("amount", "0")
    if not (transfer_id and sender_did and receiver_did):
        raise HTTPException(400, "Missing transfer_id / sender_did / receiver_did")
    try:
        amount = _Decimal(str(amount_str))
    except Exception:
        raise HTTPException(400, "Invalid amount")
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    fee_amount = (amount * _CROSS_REG_FEE_RATE / _Decimal("100")).quantize(_Decimal("0.000001"))
    credited_amount = amount - fee_amount

    # Phase 8 (2026-05-04): async session + cancel-safe rollback (mirrors Vector C).
    from ..database.db_session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            existing = (await session.execute(
                _select(_CrossTEGTransfer).where(
                    _CrossTEGTransfer.transfer_id == transfer_id,
                    _CrossTEGTransfer.role == "target",
                )
            )).scalar_one_or_none()
            if existing is not None and existing.status == _CrossTEGTransferStatus.COMPLETED:
                logger.info(f"[CrossTEG/credit-async] {transfer_id} already credited — idempotent")
                return {
                    "status": "already_credited",
                    "transfer_id": transfer_id,
                    "credited_amount": str(credited_amount),
                    "fee_amount": str(fee_amount),
                }

            profile = (await session.execute(
                _select(_AgentTEGProfile).where(_AgentTEGProfile.agent_id == receiver_did)
            )).scalar_one_or_none()
            if profile is None:
                # W2 guard: don't auto-create a profile for an agent whose home
                # is a different frame. Reactor-side `agents`-table check should
                # already prevent this path from being hit for cross-frame
                # receivers; the guard is defense-in-depth for sim/admin flows.
                from ..database.home_frame_resolver import async_check_home_or_raise
                await async_check_home_or_raise(receiver_did)
                profile = _AgentTEGProfile(
                    agent_id=receiver_did,
                    token_balance=_Decimal("0"),
                    locked_balance=_Decimal("0"),
                    audited_balance=_Decimal("0"),
                )
                session.add(profile)
            # §MONEY-R18 (cross-TEG credit family, 2026-09-04): balance_ledger_journal.entry_type
            # DEFAULTS to 'unknown', so an unstamped direct-ORM write lands in the largest and least
            # useful bucket and materialized_balances.sql files it under transit_net. Found by driving
            # a real cross-registry transfer: the RECEIVING teg wrote the recipient credit and its
            # 0.5% fee as 'unknown' while Δ read 0.0 throughout.
            await session.execute(_text("SELECT set_config('teg.entry_type','cross_teg_credit',true)"))
            profile.token_balance += credited_amount
            profile.audited_balance = profile.token_balance

            fee_collector_address = await _async_get_system_config_value(
                session, "fee_collection_address", "teg:system:fee_collector"
            )
            fee_profile = await _async_get_or_create_agent(session, fee_collector_address)
            fee_profile.token_balance += fee_amount
            fee_profile.audited_balance = fee_profile.token_balance

            tx = _TEGTransaction(
                transaction_id=_recv_leg_txid(transfer_id),  # §2026-06-17: distinct deterministic receive-leg id (uuid5) — see _recv_leg_txid; avoids same-TEG send/receive PK collision
                sender_agent_id=receiver_did,
                receiver_agent_id=receiver_did,
                amount=credited_amount,
                fee_amount=fee_amount,
                transaction_type=_TransactionType.CROSS_TEG_RECEIVE.value,
                status=_TransactionStatus.COMPLETED,
            )
            session.add(tx)

            record = _CrossTEGTransfer(
                transfer_id=transfer_id,
                correlation_id=payload.get("correlation_id", transfer_id),
                source_teg_id=payload.get("source_teg_id", "unknown"),
                source_registry_id="unknown",
                source_agent_id=sender_did,
                target_teg_id=settings.teg_id,
                target_registry_id="unknown",
                target_agent_id=receiver_did,
                amount=amount,
                status=_CrossTEGTransferStatus.COMPLETED,
                role="target",
                credit_transaction_id=tx.transaction_id,
                completed_at=_datetime.now(_timezone.utc),
                expires_at=_datetime.now(_timezone.utc) + _timedelta(minutes=5),
            )
            await session.merge(record)
            await session.commit()
        except HTTPException:
            raise
        except BaseException as exc:
            try:
                await asyncio.shield(session.rollback())
            except BaseException as rb_exc:
                logger.warning(
                    f"[CrossTEG/credit-async] rollback after "
                    f"{type(exc).__name__} failed: {type(rb_exc).__name__}"
                )
            raise

    return {
        "status": "credited",
        "transfer_id": transfer_id,
        "credited_amount": str(credited_amount),
        "fee_amount": str(fee_amount),
    }


def _parse_bulk_credit_payload(transfers):
    """Phase 1 — pre-flight validation + parse. Pure Python; no DB.
    Returns (parsed, results) where parsed is a list of tuples
    (idx, transfer_id, sender, receiver, amount, fee, credit, raw)
    and results is a pre-allocated per-index response list.
    """
    parsed = []
    results: list = [None] * len(transfers)
    for i, t in enumerate(transfers):
        try:
            tid = t.get("transfer_id")
            sd = t.get("sender_did")
            rd = t.get("receiver_did")
            a = t.get("amount", "0")
            if not (tid and sd and rd):
                results[i] = {"transfer_id": tid, "status": "error",
                              "error": "missing required field"}
                continue
            amt = _Decimal(str(a))
            if amt <= 0:
                results[i] = {"transfer_id": tid, "status": "error",
                              "error": "amount must be positive"}
                continue
            fee = (amt * _CROSS_REG_FEE_RATE / _Decimal("100")).quantize(_Decimal("0.000001"))
            credit = amt - fee
            parsed.append((i, tid, sd, rd, amt, fee, credit, t))
        except Exception as e:
            results[i] = {"transfer_id": t.get("transfer_id"),
                          "status": "error", "error": str(e)[:200]}
    return parsed, results


@router.post("/credit-async-bulk")
async def credit_async_bulk(
    payload: Dict[str, Any],
    http_request: Request,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
):
    """Vector B (2026-05-04) — Bulk receiver-side credit. Single transaction,
    per-row idempotent on transfer_id. Mirrors credit_async arithmetic but
    processes N rows at once using the LIGHTNING-3 Phase 1-6 transaction shape.

    Body: {"transfers": [{"transfer_id","sender_did","receiver_did",
                          "source_frame","amount","correlation_id"?,
                          "source_teg_id"?}, ...]}
    Response: {"results": [{"transfer_id","status","credited_amount"?,"fee_amount"?,"error"?}, ...]}
        status ∈ "credited" | "already_credited" | "error"

    Reactor-side caller is reactor_cross_frame_initiated's _CreditAsyncBulkProxy.

    Vector C (2026-05-04) — when TEG_BULK_USE_ASYNC_DB=true AND the async
    engine is configured (postgres URL), the DB phases run on the async engine
    (asyncpg) so each TEG worker handles many concurrent bulk-credit
    transactions. Falls back to the sync path otherwise.
    """
    _require_local_caller(http_request, authorization, "credit-async-bulk")
    transfers = payload.get("transfers") or []
    if not isinstance(transfers, list) or len(transfers) == 0:
        raise HTTPException(400, "transfers must be non-empty list")
    if len(transfers) > 200:
        raise HTTPException(400, "batch too large (max 200)")

    parsed, results = _parse_bulk_credit_payload(transfers)
    if not parsed:
        return {"results": results}

    # §2026-06-17 — concurrent-race idempotency polish (the "ON CONFLICT" ask).
    # Two in-flight bulk credits for the same transfer_id can BOTH pass the Phase-2
    # idempotency check (neither committed yet) then collide on the teg_transactions
    # PK → the loser raised IntegrityError and aborted its WHOLE batch (noisy ERROR +
    # a caller-level batch retry storm). The credit path is already exactly-once-correct
    # (the loser's transaction rolls back → nothing is double-credited), so instead of a
    # risky Core ON-CONFLICT rewrite of the money arithmetic we retry IN-HANDLER on the
    # dup-key: re-run the bulk on a FRESH session — Phase 2 now sees the winner's just-
    # committed row and returns the conflicting tid(s) as `already_credited`, so it
    # converges with NO double-credit (attempt-1 committed nothing). Δ-safe by construction.
    from sqlalchemy.exc import IntegrityError as _IntegrityError
    import copy as _copy
    _results_snapshot = _copy.deepcopy(results)
    _BULK_MAX_ATTEMPTS = 3

    async def _run_bulk():
        if _TEG_BULK_USE_ASYNC_DB:
            from ..database.db_session import AsyncSessionLocal as _ASL
            if _ASL is not None:
                return await _credit_async_bulk_async(parsed, results)
            logger.warning(
                "[CrossTEG/credit-async-bulk] TEG_BULK_USE_ASYNC_DB=true but "
                "async engine not configured (non-postgres DATABASE_URL); "
                "falling back to sync path"
            )
        return _credit_async_bulk_sync(parsed, results)

    for _attempt in range(1, _BULK_MAX_ATTEMPTS + 1):
        if _attempt > 1:
            results[:] = _copy.deepcopy(_results_snapshot)  # reset mutable per-row results
        try:
            return await _run_bulk()
        except _IntegrityError:
            if _attempt >= _BULK_MAX_ATTEMPTS:
                logger.warning(
                    f"[CrossTEG/credit-async-bulk] dup-key race unresolved after "
                    f"{_BULK_MAX_ATTEMPTS} attempts (batch={len(parsed)}) — surfacing to caller"
                )
                raise
            logger.info(
                f"[CrossTEG/credit-async-bulk] concurrent dup-key race "
                f"(attempt {_attempt}/{_BULK_MAX_ATTEMPTS}, batch={len(parsed)}) — retry on fresh session"
            )
            await asyncio.sleep(0.05 * _attempt)


def _credit_async_bulk_sync(parsed, results):
    """Synchronous bulk credit — original Vector B implementation."""
    with transfer_protocol._get_session() as session:
        # Phase 2 — bulk idempotency check (one query for the entire batch)
        tids = [p[1] for p in parsed]
        existing_rows = session.execute(
            _select(_CrossTEGTransfer).where(
                _CrossTEGTransfer.transfer_id.in_(tids),
                _CrossTEGTransfer.role == "target",
            )
        ).scalars().all()
        already_done = {r.transfer_id for r in existing_rows
                        if r.status == _CrossTEGTransferStatus.COMPLETED}

        # Phase 3 — bulk SELECT receiver profiles (one query for the receiver set)
        new_rows = [p for p in parsed if p[1] not in already_done]
        receiver_dids = sorted({p[3] for p in new_rows})
        existing_profiles: dict = {}
        if receiver_dids:
            existing_profiles = {
                prof.agent_id: prof for prof in session.execute(
                    _select(_AgentTEGProfile).where(
                        _AgentTEGProfile.agent_id.in_(receiver_dids)
                    )
                ).scalars().all()
            }

        fee_collector_address = _SystemConfigCRUD.get_fee_collection_address(session)
        fee_profile = _AgentCRUD.get_or_create(session, fee_collector_address)

        total_fee_delta = _Decimal("0")
        cross_teg_rows: list = []
        now = _datetime.now(_timezone.utc)
        expires = now + _timedelta(minutes=5)

        # Phase 4 — sequential per-row in-mem apply
        for (idx, tid, sd, rd, amt, fee, credit, raw) in new_rows:
            prof = existing_profiles.get(rd)
            if prof is None:
                # W2 guard (sync path): refuse cross-frame profile creation.
                from ..database.home_frame_resolver import check_home_or_raise
                check_home_or_raise(rd)
                prof = _AgentTEGProfile(
                    agent_id=rd,
                    token_balance=_Decimal("0"),
                    locked_balance=_Decimal("0"),
                    audited_balance=_Decimal("0"),
                )
                session.add(prof)
                existing_profiles[rd] = prof
            # §MONEY-R18 (cross-TEG credit family, 2026-09-04): balance_ledger_journal.entry_type
            # DEFAULTS to 'unknown', so an unstamped direct-ORM write lands in the largest and least
            # useful bucket and materialized_balances.sql files it under transit_net. Found by driving
            # a real cross-registry transfer: the RECEIVING teg wrote the recipient credit and its
            # 0.5% fee as 'unknown' while Δ read 0.0 throughout.
            session.execute(_text("SELECT set_config('teg.entry_type','cross_teg_credit',true)"))
            prof.token_balance += credit
            prof.audited_balance = prof.token_balance
            total_fee_delta += fee

            tx = _TEGTransaction(
                transaction_id=_recv_leg_txid(tid),  # §2026-06-17: distinct deterministic receive-leg id (uuid5) — see _recv_leg_txid; avoids same-TEG send/receive PK collision
                sender_agent_id=rd,
                receiver_agent_id=rd,
                amount=credit,
                fee_amount=fee,
                transaction_type=_TransactionType.CROSS_TEG_RECEIVE.value,
                status=_TransactionStatus.COMPLETED,
            )
            session.add(tx)

            cross_teg_rows.append(_CrossTEGTransfer(
                transfer_id=tid,
                correlation_id=raw.get("correlation_id", tid),
                source_teg_id=raw.get("source_teg_id", "unknown"),
                source_registry_id="unknown",
                source_agent_id=sd,
                target_teg_id=settings.teg_id,
                target_registry_id="unknown",
                target_agent_id=rd,
                amount=amt,
                status=_CrossTEGTransferStatus.COMPLETED,
                role="target",
                completed_at=now,
                expires_at=expires,
            ))

            results[idx] = {
                "transfer_id": tid,
                "status": "credited",
                "credited_amount": str(credit),
                "fee_amount": str(fee),
            }

        # Phase 5 — single fee_collector update (accumulated delta)
        if total_fee_delta > 0:
            fee_profile.token_balance += total_fee_delta
            fee_profile.audited_balance = fee_profile.token_balance

        # Phase 6 — merge each cross_teg_transfer row + single commit
        for row in cross_teg_rows:
            session.merge(row)

        # Already-credited rows: per-row idempotent response
        for idx, ptid, *_ in parsed:
            if ptid in already_done and results[idx] is None:
                results[idx] = {"transfer_id": ptid, "status": "already_credited"}

        session.commit()

    n_credited = sum(1 for r in results if r and r.get("status") == "credited")
    n_already = sum(1 for r in results if r and r.get("status") == "already_credited")
    n_err = sum(1 for r in results if r and r.get("status") == "error")
    logger.info(
        f"[CrossTEG/credit-async-bulk:sync] processed batch={len(parsed)+sum(1 for r in results if r and r.get('status')=='error')} "
        f"credited={n_credited} already_credited={n_already} errors={n_err}"
    )
    return {"results": results}


async def _async_get_system_config_value(session, key: str, default):
    """Async equivalent of SystemConfigCRUD.get_value — single SELECT."""
    from ..database.models import SystemConfig
    row = (await session.execute(
        _select(SystemConfig).where(SystemConfig.key == key)
    )).scalar_one_or_none()
    return row.value if row else default


async def _async_get_or_create_agent(session, agent_id: str):
    """Async equivalent of AgentCRUD.get_or_create — SELECT-then-add+flush.
    Caller controls commit; flush ensures the row is visible within the txn.

    Home-frame guard (W2 / 2026-05-05): when TEG_HOME_FRAME_GUARD_ENABLED=true,
    raises AgentNotHomeError if `agent_id`'s home is a different frame. Caller
    handles the error (typically by returning a 4xx so the saga refunds at
    timeout). System accounts bypass the guard.
    """
    row = (await session.execute(
        _select(_AgentTEGProfile).where(_AgentTEGProfile.agent_id == agent_id)
    )).scalar_one_or_none()
    if row is not None:
        return row
    # Guard against creating profiles for agents whose home is a different frame.
    from ..database.home_frame_resolver import async_check_home_or_raise
    await async_check_home_or_raise(agent_id)
    row = _AgentTEGProfile(
        agent_id=agent_id,
        token_balance=_Decimal("0"),
        locked_balance=_Decimal("0"),
        audited_balance=_Decimal("0"),
        reputation_score=0,
    )
    session.add(row)
    await session.flush()
    return row


async def _credit_async_bulk_async(parsed, results):
    """Vector C (2026-05-04) — async SQLAlchemy hot-path. Mirrors the sync
    Phase 2-6 line-for-line; differences are only the async session APIs
    (await on execute / merge / commit / flush) and the two async CRUD
    helpers above. Single transaction; identical idempotency + arithmetic.

    Cancellation safety (2026-05-04 evening fix): catches BaseException so
    asyncio.CancelledError triggers explicit rollback. Wraps rollback in
    asyncio.shield() so it survives even if our own task is being cancelled.
    Without this, asyncpg connections returned to pgbouncer's pool with the
    transaction still open server-side → idle-in-tx leak → row-lock wedge.
    """
    from ..database.db_session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            # Phase 2 — bulk idempotency check
            tids = [p[1] for p in parsed]
            existing_rows = (await session.execute(
                _select(_CrossTEGTransfer).where(
                    _CrossTEGTransfer.transfer_id.in_(tids),
                    _CrossTEGTransfer.role == "target",
                )
            )).scalars().all()
            already_done = {r.transfer_id for r in existing_rows
                            if r.status == _CrossTEGTransferStatus.COMPLETED}

            # Phase 3 — bulk SELECT receiver profiles
            new_rows = [p for p in parsed if p[1] not in already_done]
            receiver_dids = sorted({p[3] for p in new_rows})
            existing_profiles: dict = {}
            if receiver_dids:
                prof_rows = (await session.execute(
                    _select(_AgentTEGProfile).where(
                        _AgentTEGProfile.agent_id.in_(receiver_dids)
                    )
                )).scalars().all()
                existing_profiles = {p.agent_id: p for p in prof_rows}

            # W2 guard (bulk path): pre-resolve home frame for every receiver
            # that doesn't yet have a profile here. Single bulk RPC amortizes
            # the cost across the batch. Raises AgentNotHomeError on the first
            # cross-frame DID — the caller's BaseException handler rolls back.
            from ..database.home_frame_resolver import async_check_home_or_raise_bulk
            new_dids = [rd for rd in receiver_dids if rd not in existing_profiles]
            if new_dids:
                await async_check_home_or_raise_bulk(new_dids)

            fee_collector_address = await _async_get_system_config_value(
                session, "fee_collection_address", "teg:system:fee_collector"
            )
            fee_profile = await _async_get_or_create_agent(session, fee_collector_address)

            total_fee_delta = _Decimal("0")
            cross_teg_rows: list = []
            now = _datetime.now(_timezone.utc)
            expires = now + _timedelta(minutes=5)

            # Phase 4 — sequential per-row in-mem apply (identical arithmetic)
            for (idx, tid, sd, rd, amt, fee, credit, raw) in new_rows:
                prof = existing_profiles.get(rd)
                if prof is None:
                    prof = _AgentTEGProfile(
                        agent_id=rd,
                        token_balance=_Decimal("0"),
                        locked_balance=_Decimal("0"),
                        audited_balance=_Decimal("0"),
                    )
                    session.add(prof)
                    existing_profiles[rd] = prof
                # §MONEY-R18 (cross-TEG credit family, 2026-09-04): balance_ledger_journal.entry_type
                # DEFAULTS to 'unknown', so an unstamped direct-ORM write lands in the largest and least
                # useful bucket and materialized_balances.sql files it under transit_net. Found by driving
                # a real cross-registry transfer: the RECEIVING teg wrote the recipient credit and its
                # 0.5% fee as 'unknown' while Δ read 0.0 throughout.
                await session.execute(_text("SELECT set_config('teg.entry_type','cross_teg_credit',true)"))
                prof.token_balance += credit
                prof.audited_balance = prof.token_balance
                total_fee_delta += fee

                tx = _TEGTransaction(
                    transaction_id=_recv_leg_txid(tid),  # §2026-06-17: distinct deterministic receive-leg id (uuid5) — see _recv_leg_txid; avoids same-TEG send/receive PK collision
                    sender_agent_id=rd,
                    receiver_agent_id=rd,
                    amount=credit,
                    fee_amount=fee,
                    transaction_type=_TransactionType.CROSS_TEG_RECEIVE.value,
                    status=_TransactionStatus.COMPLETED,
                )
                session.add(tx)

                cross_teg_rows.append(_CrossTEGTransfer(
                    transfer_id=tid,
                    correlation_id=raw.get("correlation_id", tid),
                    source_teg_id=raw.get("source_teg_id", "unknown"),
                    source_registry_id="unknown",
                    source_agent_id=sd,
                    target_teg_id=settings.teg_id,
                    target_registry_id="unknown",
                    target_agent_id=rd,
                    amount=amt,
                    status=_CrossTEGTransferStatus.COMPLETED,
                    role="target",
                    completed_at=now,
                    expires_at=expires,
                ))

                results[idx] = {
                    "transfer_id": tid,
                    "status": "credited",
                    "credited_amount": str(credit),
                    "fee_amount": str(fee),
                }

            # Phase 5 — single fee_collector update
            if total_fee_delta > 0:
                fee_profile.token_balance += total_fee_delta
                fee_profile.audited_balance = fee_profile.token_balance

            # Phase 6 — merge each cross_teg_transfer + single commit
            for row in cross_teg_rows:
                await session.merge(row)

            for idx, ptid, *_ in parsed:
                if ptid in already_done and results[idx] is None:
                    results[idx] = {"transfer_id": ptid, "status": "already_credited"}

            await session.commit()
        except BaseException as exc:
            # asyncio.CancelledError is a BaseException since 3.8 — `except Exception`
            # does NOT catch it. Use BaseException so cancellation paths trigger
            # explicit rollback. Shield the rollback so it completes even if our
            # own task is being cancelled (otherwise asyncpg returns the connection
            # to pgbouncer's pool with the transaction still open server-side,
            # which is the idle-in-tx leak that wedges the TEG under saturation).
            try:
                await asyncio.shield(session.rollback())
            except BaseException as rb_exc:
                logger.warning(
                    f"[CrossTEG/credit-async-bulk:async] rollback after "
                    f"{type(exc).__name__} failed: {type(rb_exc).__name__}"
                )
            raise

    n_credited = sum(1 for r in results if r and r.get("status") == "credited")
    n_already = sum(1 for r in results if r and r.get("status") == "already_credited")
    n_err = sum(1 for r in results if r and r.get("status") == "error")
    logger.info(
        f"[CrossTEG/credit-async-bulk:async] processed batch={len(parsed)+sum(1 for r in results if r and r.get('status')=='error')} "
        f"credited={n_credited} already_credited={n_already} errors={n_err}"
    )
    return {"results": results}


@router.post("/refund-async")
async def refund_async(
    payload: Dict[str, Any],
    http_request: Request,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
):
    """Sender-side refund — restores sender's balance. Saga-driven. Idempotent.

    Called by the registry's saga_timeout_checker when a locked transfer
    exceeds its 5-min timeout without a Settled event. Re-credits the
    full original amount (no fee was deducted at lock time).
    """
    _require_local_caller(http_request, authorization, "refund-async")

    transfer_id = payload.get("transfer_id")
    sender_did = payload.get("sender_did")
    amount_str = payload.get("amount", "0")
    if not (transfer_id and sender_did):
        raise HTTPException(400, "Missing transfer_id or sender_did")
    try:
        amount = _Decimal(str(amount_str))
    except Exception:
        raise HTTPException(400, "Invalid amount")
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    # Phase 8 (2026-05-04): async session + cancel-safe rollback (mirrors Vector C).
    from ..database.db_session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            existing = (await session.execute(
                _select(_CrossTEGTransfer).where(
                    _CrossTEGTransfer.transfer_id == transfer_id,
                    _CrossTEGTransfer.role == "source",
                )
            )).scalar_one_or_none()
            if existing is None:
                raise HTTPException(404, f"No source-side row for {transfer_id} — nothing to refund")
            if existing.status == _CrossTEGTransferStatus.FAILED:
                logger.info(f"[CrossTEG/refund-async] {transfer_id} already refunded — idempotent")
                return {"status": "already_refunded", "transfer_id": transfer_id}

            profile = (await session.execute(
                _select(_AgentTEGProfile).where(_AgentTEGProfile.agent_id == sender_did)
            )).scalar_one_or_none()
            if profile is None:
                raise HTTPException(404, f"Sender {sender_did} not found on this TEG")
            # §MONEY-R18 (cross-TEG credit family, 2026-09-04): balance_ledger_journal.entry_type
            # DEFAULTS to 'unknown', so an unstamped direct-ORM write lands in the largest and least
            # useful bucket and materialized_balances.sql files it under transit_net. Found by driving
            # a real cross-registry transfer: the RECEIVING teg wrote the recipient credit and its
            # 0.5% fee as 'unknown' while Δ read 0.0 throughout.
            await session.execute(_text("SELECT set_config('teg.entry_type','cross_teg_refund',true)"))
            profile.token_balance += amount
            profile.audited_balance = profile.token_balance

            tx = _TEGTransaction(
                # §PlanB-②: refund leg PK = saga-supplied reversal_txid (deterministic,
                # ≠ transfer_id which the SEND leg holds on this TEG) so getTegTransactionDetail
                # resolves the listed refund leg. Absent → falls back to the column default uuid.
                **({"transaction_id": payload["reversal_txid"]} if payload.get("reversal_txid") else {}),
                sender_agent_id="teg:system:cross_frame_escrow",
                receiver_agent_id=sender_did,
                amount=amount,
                fee_amount=_Decimal("0"),
                transaction_type=_TransactionType.CROSS_TEG_RECEIVE.value,
                status=_TransactionStatus.COMPLETED,
            )
            session.add(tx)

            existing.status = _CrossTEGTransferStatus.FAILED
            existing.completed_at = _datetime.now(_timezone.utc)
            await session.commit()
        except HTTPException:
            raise
        except BaseException as exc:
            try:
                await asyncio.shield(session.rollback())
            except BaseException as rb_exc:
                logger.warning(
                    f"[CrossTEG/refund-async] rollback after "
                    f"{type(exc).__name__} failed: {type(rb_exc).__name__}"
                )
            raise

    return {"status": "refunded", "transfer_id": transfer_id, "amount": str(amount)}


@router.post("/reverse-async")
async def reverse_async(
    payload: Dict[str, Any],
    http_request: Request,
    authorization: Optional[str] = Security(_cross_teg_auth_header),
):
    """Receiver-side reverse — debits recipient + reverses fee. Saga-driven. Idempotent.

    Called by reactor_cross_frame_refunded after catching a Refunded event.
    Only fires when the receiver had previously credited (compensating
    action). Reverses both the recipient credit and the fee_collector fee.
    """
    _require_local_caller(http_request, authorization, "reverse-async")

    transfer_id = payload.get("transfer_id")
    receiver_did = payload.get("receiver_did")
    amount_str = payload.get("amount", "0")
    if not (transfer_id and receiver_did):
        raise HTTPException(400, "Missing transfer_id or receiver_did")
    try:
        amount = _Decimal(str(amount_str))
    except Exception:
        raise HTTPException(400, "Invalid amount")
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    fee_amount = (amount * _CROSS_REG_FEE_RATE / _Decimal("100")).quantize(_Decimal("0.000001"))
    credited_amount = amount - fee_amount

    # Phase 8 (2026-05-04): async session + cancel-safe rollback (mirrors Vector C).
    from ..database.db_session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            existing = (await session.execute(
                _select(_CrossTEGTransfer).where(
                    _CrossTEGTransfer.transfer_id == transfer_id,
                    _CrossTEGTransfer.role == "target",
                )
            )).scalar_one_or_none()
            if existing is None:
                logger.info(f"[CrossTEG/reverse-async] No target row for {transfer_id} — never credited, no-op")
                return {"status": "never_credited", "transfer_id": transfer_id}
            if existing.status == _CrossTEGTransferStatus.FAILED:
                logger.info(f"[CrossTEG/reverse-async] {transfer_id} already reversed — idempotent")
                return {"status": "already_reversed", "transfer_id": transfer_id}

            profile = (await session.execute(
                _select(_AgentTEGProfile).where(_AgentTEGProfile.agent_id == receiver_did)
            )).scalar_one_or_none()
            if profile is None:
                raise HTTPException(404, f"Receiver {receiver_did} not found on this TEG")
            # §MONEY-R18 (cross-TEG credit family, 2026-09-04): balance_ledger_journal.entry_type
            # DEFAULTS to 'unknown', so an unstamped direct-ORM write lands in the largest and least
            # useful bucket and materialized_balances.sql files it under transit_net. Found by driving
            # a real cross-registry transfer: the RECEIVING teg wrote the recipient credit and its
            # 0.5% fee as 'unknown' while Δ read 0.0 throughout.
            await session.execute(_text("SELECT set_config('teg.entry_type','cross_teg_reverse',true)"))
            profile.token_balance -= credited_amount
            profile.audited_balance = profile.token_balance

            fee_collector_address = await _async_get_system_config_value(
                session, "fee_collection_address", "teg:system:fee_collector"
            )
            fee_profile = await _async_get_or_create_agent(session, fee_collector_address)
            fee_profile.token_balance -= fee_amount
            fee_profile.audited_balance = fee_profile.token_balance

            tx = _TEGTransaction(
                # §PlanB-②: reverse leg PK = reactor-supplied reversal_txid (deterministic,
                # ≠ transfer_id which the credit RECEIVE leg holds on this TEG) so
                # getTegTransactionDetail resolves it. Absent → column default uuid.
                **({"transaction_id": payload["reversal_txid"]} if payload.get("reversal_txid") else {}),
                sender_agent_id=receiver_did,
                receiver_agent_id="teg:system:cross_frame_escrow",
                amount=credited_amount,
                fee_amount=fee_amount,
                transaction_type=_TransactionType.CROSS_TEG_SEND.value,
                status=_TransactionStatus.COMPLETED,
            )
            session.add(tx)

            existing.status = _CrossTEGTransferStatus.FAILED
            existing.completed_at = _datetime.now(_timezone.utc)
            await session.commit()
        except HTTPException:
            raise
        except BaseException as exc:
            try:
                await asyncio.shield(session.rollback())
            except BaseException as rb_exc:
                logger.warning(
                    f"[CrossTEG/reverse-async] rollback after "
                    f"{type(exc).__name__} failed: {type(rb_exc).__name__}"
                )
            raise

    return {
        "status": "reversed",
        "transfer_id": transfer_id,
        "debited_amount": str(credited_amount),
        "fee_reversed": str(fee_amount),
    }
