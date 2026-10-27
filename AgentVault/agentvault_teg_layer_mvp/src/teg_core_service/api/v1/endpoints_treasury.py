"""
OWL26: Treasury Transfer Endpoints
====================================
Dedicated endpoints for treasury-to-agent and agent-to-treasury transfers.

These replace the use of /admin/token/issue (minting) with proper treasury
accounting. All funding operations should flow through these endpoints.

Endpoints:
  POST /treasury/transfer  — Treasury → Agent (genesis grants, compensation, rewards)
  POST /treasury/receive   — Agent → Treasury (slashes, penalties, fees)
  GET  /treasury/info      — Real treasury balance + supply metrics
"""
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT, HTTP_422_UNPROCESSABLE_ENTITY

from ...core.security import verify_admin_token
from ...core.external_credit import external_credit_gate as _external_credit_gate
from ...core.secure_config import get_settings
from ...core.structured_logging import get_logger, LogContext, log_performance, log_transaction
from ...core.error_handling import TEGException, ErrorCode
from ...core.ledger_gate import require_ledger
from ...core.idempotency import IdempotencyService
from ...database.db_session import get_db
from ...database.crud import AgentCRUD, TransferService, SystemConfigCRUD
from ...database.models import AgentTEGProfile, TEGTransaction, TransactionStatus
from ...event_emitter import EventEmitter

logger = get_logger(__name__)
settings = get_settings()

# Direct event emitter — bypasses monkey-patch (guaranteed emission for treasury ops)
_treasury_event_emitter = EventEmitter(
    event_store_url=getattr(settings, 'event_store_url', 'http://event-store:8200'),
    internal_api_key=getattr(settings, 'event_store_api_key', ''),
    source_service="teg"
)


# --- Money-idempotency backstop (2026-07-24, theme-1 hardening) ---------------
# OPT-IN: engages only when the caller passes an `Idempotency-Key`. Additive —
# no key => behavior byte-identical to before. Claims the key in
# teg_idempotency_records (durable L2) in the same DB BEFORE the money move; a
# replay returns the cached response and moves nothing. This is the authoritative
# double-PAY guard the design (STRATEGY_2026-07-23_IDEMPOTENCY_HARDENING) calls
# layer-3 — one change protects every caller of these rails.
def _idem_claim(db: Session, key: Optional[str], op: str, params: Dict) -> Optional[Dict]:
    """Cached response dict if `key` already ran this op (→ caller returns it and
    moves no money); None on a fresh claim. Clean 409 on a concurrent in-flight
    or PK-raced duplicate. No-op when key is falsy."""
    if not key:
        return None
    try:
        return IdempotencyService.check_and_create(db, key, op, params)
    except IntegrityError:
        # Two same-key claims raced the PK insert; the loser must NOT move money.
        db.rollback()
        raise TEGException(
            status_code=HTTP_409_CONFLICT,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Duplicate request in flight",
            detail="Another request with this Idempotency-Key is being processed",
        )


def _idem_complete(db: Session, key: Optional[str], response_dict: Dict) -> None:
    if key:
        try:
            IdempotencyService.mark_completed(db, key, response_dict)
        except Exception as _e:
            logger.error(f"[Idem] mark_completed failed key={key}: {_e}")


def _idem_fail(db: Session, key: Optional[str], err: Dict) -> None:
    if key:
        try:
            IdempotencyService.mark_failed(db, key, err)
        except Exception:
            pass


def _idem_cache_partial(db: Session, key: Optional[str], content: Dict) -> None:
    """A money leg COMMITTED but a LATER step of the same operation threw. Cache the
    accumulated partial as a COMPLETED idempotency record so a same-key retry returns
    it (never re-runs → never double-pays) instead of 409-ing 'pending' for the 24h
    TTL — the §2026-08-12 mid-waterfall sharp-edge. The throwing step may have left the
    session in a failed txn, so roll it back first: committed legs are DURABLE (each
    leg self-commits) and are unaffected, and the completion write then lands on a
    clean session. Δ-irrelevant — pure idempotency-record state, moves no money."""
    if not key:
        return
    try:
        db.rollback()   # discard only the throwing step's uncommitted txn; committed legs survive
    except Exception:
        pass
    try:
        IdempotencyService.mark_completed(db, key, content)
    except Exception as _e:
        logger.error(f"[Idem] partial-cache mark_completed failed key={key}: {_e}")


def _idem_cache_single(db: Session, key: Optional[str], build_content) -> None:
    """§POCKETBRIDGE5 W-F — the single-transfer sibling of _idem_cache_partial.
    The transfer COMMITTED (durable — execute_transfer commits internally) but a
    LATER step of the same request threw. Cache the COMPLETED response under the
    key so a same-key retry REPLAYS it (never re-pays) instead of 409-ing
    'pending' for the 24h TTL. `build_content` runs AFTER the rollback so its
    balance re-reads land on a clean session; if the builder itself throws we
    cache NOTHING — the key stays pending, which is exactly the pre-fix Window B
    behavior: self-heals at TTL expiry and never double-pays."""
    if not key:
        return
    try:
        db.rollback()
    except Exception:
        pass
    try:
        content = build_content()
    except Exception as _e:
        logger.error(f"[Idem] single-transfer partial builder failed key={key}: {_e}")
        return
    try:
        IdempotencyService.mark_completed(db, key, content)
    except Exception as _e:
        logger.error(f"[Idem] single-transfer mark_completed failed key={key}: {_e}")


def _reward_partial_content(request, waterfall, legs, funded) -> Dict:
    """Exhausted-shaped body describing exactly what a reward_fund waterfall committed
    before it threw — cached under the key so a same-key retry replays this partial
    via the existing exhausted path (400 + partial legs), never re-paying."""
    remaining = request.amount - funded
    return {
        "status": "exhausted",
        "target_agent_id": request.target_agent_id,
        "total_amount": str(request.amount),
        "funded_amount": str(funded),
        "shortfall": str(remaining),
        "legs": legs,
        "waterfall_used": waterfall,
        "reason": request.reason,
        "reference_id": request.reference_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detail": (
            f"Partial reward funding cached after a mid-waterfall error: "
            f"{funded}/{request.amount} applied from {[l['source'] for l in legs]}; "
            f"{remaining} not applied. A same-key retry returns this partial (no re-pay); "
            f"fund the remainder with a NEW idempotency key."
        ),
    }


async def _emit_treasury_transfer_event(
    sender_id: str, receiver_id: str, amount: str, transaction_id: str, memo: str = ""
):
    """Emit TokensTransferred event for treasury operations. Fire-and-forget."""
    try:
        success = await _treasury_event_emitter.emit_tokens_transferred(
            from_agent=sender_id, to_agent=receiver_id,
            amount=amount, transaction_id=transaction_id, memo=memo
        )
        if success:
            logger.info(f"[TreasuryEventEmit] TokensTransferred emitted: {transaction_id}")
        else:
            logger.error(f"[TreasuryEventEmit] FAILED to emit TokensTransferred: {transaction_id}")
    except Exception as e:
        logger.error(f"[TreasuryEventEmit] Error: {e}")

router = APIRouter()


# --- Schemas ---

class TreasuryTransferRequest(BaseModel):
    """Request to transfer AVT from treasury to an agent."""
    target_agent_id: str = Field(..., description="Target agent DID to fund")
    amount: Decimal = Field(..., gt=0, description="Amount of AVT to transfer")
    reason: str = Field(..., description="Reason for transfer: genesis_grant, dispute_compensation, reward, admin_grant, tutorial_grant")
    reference_id: Optional[str] = Field(None, description="External reference (e.g., dispute ID, onboarding ID)")

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v.as_tuple().exponent < -18:
            raise ValueError("Amount has too many decimal places (max 18)")
        return v

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class TreasuryTransferResponse(BaseModel):
    """Response from a treasury transfer."""
    transaction_id: str
    status: str
    amount: Decimal
    reason: str
    reference_id: Optional[str] = None
    new_treasury_balance: Decimal
    new_target_balance: Decimal
    treasury_did: str
    target_agent_id: str
    timestamp: datetime

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class TreasuryReceiveRequest(BaseModel):
    """Request to return AVT from an agent to treasury."""
    source_agent_id: str = Field(..., description="Source agent DID (e.g., slashed defendant)")
    amount: Decimal = Field(..., gt=0, description="Amount of AVT to return to treasury")
    reason: str = Field(..., description="Reason: dispute_slash, penalty, fee_collection, admin_clawback")
    reference_id: Optional[str] = Field(None, description="External reference (e.g., dispute ID)")

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class TreasuryReceiveResponse(BaseModel):
    """Response from a treasury receive (agent → treasury)."""
    transaction_id: str
    status: str
    amount: Decimal
    reason: str
    reference_id: Optional[str] = None
    new_treasury_balance: Decimal
    new_source_balance: Decimal
    treasury_did: str
    source_agent_id: str
    timestamp: datetime

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class TreasuryInfoResponse(BaseModel):
    """Treasury balance and supply metrics."""
    treasury_did: str
    treasury_balance: Decimal
    total_supply: Decimal
    circulating_supply: Decimal
    locked_supply: Decimal
    agent_count: int
    last_updated: datetime

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


# --- Endpoints ---

@router.post(
    "/treasury/transfer",
    response_model=TreasuryTransferResponse,
    responses={
        400: {"description": "Bad Request — insufficient treasury balance or invalid agent"},
        403: {"description": "Forbidden — admin auth required"},
    }
)
@log_performance("treasury_transfer")
async def treasury_transfer(
    request: TreasuryTransferRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Transfer AVT from the system treasury to a target agent.
    
    This is the canonical way to fund agents. Used for:
    - Genesis grants (onboarding)
    - Dispute compensation
    - Rewards
    - Admin grants
    - Tutorial funding
    
    The treasury must have sufficient balance. If not, returns 400.
    Creates an auditable TEGTransaction record with the reason.
    """
    with LogContext(
        logger,
        operation="treasury_transfer",
        target_agent_id=request.target_agent_id,
        amount=str(request.amount),
        reason=request.reason,
        reference_id=request.reference_id
    ):
        try:
            _moved = False
            _cached = _idem_claim(db, idempotency_key, "treasury_transfer",
                                  {"target": request.target_agent_id, "amount": str(request.amount), "reason": request.reason})
            if _cached is not None:
                return TreasuryTransferResponse(**_cached)

            # Get treasury DID
            treasury_did = SystemConfigCRUD.get_treasury_did(db)

            # Verify target agent exists (get_or_create ensures it)
            target = AgentCRUD.get_or_create(db, request.target_agent_id)
            treasury = AgentCRUD.get_or_create(db, treasury_did)
            
            # Check treasury balance
            if treasury.token_balance < request.amount:
                raise TEGException(
                    status_code=HTTP_400_BAD_REQUEST,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message="Insufficient treasury balance",
                    detail=f"Treasury has {treasury.token_balance} AVT, requested {request.amount} AVT"
                )
            
            # Execute transfer: treasury → target agent (fee=0 for treasury ops)
            transaction = TransferService.execute_transfer(
                db=db,
                sender_id=treasury_did,
                receiver_id=request.target_agent_id,
                amount=request.amount,
                fee_amount=Decimal("0"),
                # §POCKETBRIDGE5 W-F — journal entry_type. PREFIXED so no reason
                # can ever collide with the auditor's four reserved kinds
                # (mint / dispute_comp / slash / burn are EXACT-match, and a
                # collision here is a Δ surface).
                entry_type=f"treasury_{request.reason}"[:48],
            )
            # §POCKETBRIDGE5 W-F (Window A): the money is DURABLE the moment
            # execute_transfer returns — it commits internally. _moved flips NOW.
            # Previously it flipped only after the cosmetic label commit below,
            # and a throw in that gap marked the key FAILED, which
            # check_and_create deletes-and-re-runs: a same-key retry RE-PAID.
            # Same class the reward_fund fix closed on 2026-08-12.
            _moved = True
            _txid, _txts = transaction.transaction_id, transaction.timestamp

            def _partial():
                return TreasuryTransferResponse(
                    transaction_id=_txid, status="completed", amount=request.amount,
                    reason=request.reason, reference_id=request.reference_id,
                    new_treasury_balance=AgentCRUD.get_balance(db, treasury_did),
                    new_target_balance=AgentCRUD.get_balance(db, request.target_agent_id),
                    treasury_did=treasury_did, target_agent_id=request.target_agent_id,
                    timestamp=_txts,
                ).model_dump(mode="json")

            # Tag the transaction with reason — best-effort labeling, never a
            # reason to fail (or re-run) a transfer that already happened.
            try:
                transaction.transaction_type = f"treasury_{request.reason}"[:50]
                if request.reference_id:
                    transaction.attached_message = f"ref:{request.reference_id}"
                db.commit()
                db.refresh(transaction)
            except Exception as _label_e:
                logger.error(f"[TreasuryLabel] tag commit failed (transfer stands): {_label_e}")
                try:
                    db.rollback()
                except Exception:
                    pass

            # Get updated balances
            new_treasury_balance = AgentCRUD.get_balance(db, treasury_did)
            new_target_balance = AgentCRUD.get_balance(db, request.target_agent_id)

            # Emit event to EventStore (guaranteed — not via monkey-patch)
            import asyncio
            try:
                await _emit_treasury_transfer_event(
                    sender_id=treasury_did,
                    receiver_id=request.target_agent_id,
                    amount=str(request.amount),
                    transaction_id=transaction.transaction_id,
                    memo=f"treasury:{request.reason}"
                )
            except Exception as e:
                logger.error(f"[TreasuryEventEmit] Schedule failed: {e}")

            # Log
            log_transaction(logger, "treasury_transfer", {
                "transaction_id": transaction.transaction_id,
                "treasury_did": treasury_did,
                "target_agent_id": request.target_agent_id,
                "amount": str(request.amount),
                "reason": request.reason,
                "new_treasury_balance": str(new_treasury_balance),
                "new_target_balance": str(new_target_balance),
            })

            logger.info(
                f"TREASURY TRANSFER: {request.amount} AVT → {request.target_agent_id} "
                f"(reason: {request.reason}, ref: {request.reference_id}, "
                f"tx: {transaction.transaction_id})"
            )
            
            _resp = TreasuryTransferResponse(
                transaction_id=transaction.transaction_id,
                status="completed",
                amount=request.amount,
                reason=request.reason,
                reference_id=request.reference_id,
                new_treasury_balance=new_treasury_balance,
                new_target_balance=new_target_balance,
                treasury_did=treasury_did,
                target_agent_id=request.target_agent_id,
                timestamp=transaction.timestamp
            )
            _idem_complete(db, idempotency_key, _resp.model_dump(mode="json"))
            return _resp

        except TEGException as e:
            if _moved:
                # §POCKETBRIDGE5 W-F (Window B): the transfer committed and a
                # LATER step threw — cache the completed response so a same-key
                # retry REPLAYS instead of 409-ing pending for 24h.
                _idem_cache_single(db, idempotency_key, _partial)
            elif getattr(e, "status_code", None) != HTTP_409_CONFLICT:
                _idem_fail(db, idempotency_key, {"status_code": getattr(e, "status_code", None), "detail": str(e)})
            raise
        except ValueError as e:
            # TransferService raises ValueError for insufficient balance
            if _moved:
                _idem_cache_single(db, idempotency_key, _partial)   # W-F Window B
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Treasury transfer failed",
                detail=str(e)
            )
        except Exception as e:
            if _moved:
                _idem_cache_single(db, idempotency_key, _partial)   # W-F Window B
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            logger.error(f"Treasury transfer failed: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Treasury transfer failed",
                detail=str(e) if settings.debug else None
            )


@router.post(
    "/treasury/receive",
    response_model=TreasuryReceiveResponse,
    responses={
        400: {"description": "Bad Request — insufficient agent balance"},
        403: {"description": "Forbidden — admin auth required"},
    }
)
@log_performance("treasury_receive")
async def treasury_receive(
    request: TreasuryReceiveRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Return AVT from an agent to the system treasury.
    
    Used for:
    - Dispute slashes (defendant pays penalty)
    - Fee collection
    - Admin clawback
    
    The source agent must have sufficient balance. Partial slashes
    should be calculated by the caller — this endpoint transfers exactly
    the requested amount.
    """
    with LogContext(
        logger,
        operation="treasury_receive",
        source_agent_id=request.source_agent_id,
        amount=str(request.amount),
        reason=request.reason,
        reference_id=request.reference_id
    ):
        try:
            _moved = False
            _cached = _idem_claim(db, idempotency_key, "treasury_receive",
                                  {"source": request.source_agent_id, "amount": str(request.amount), "reason": request.reason})
            if _cached is not None:
                return TreasuryReceiveResponse(**_cached)

            treasury_did = SystemConfigCRUD.get_treasury_did(db)

            # Verify source agent exists
            source = AgentCRUD.get_or_create(db, request.source_agent_id)
            
            # Check source balance
            if source.token_balance < request.amount:
                raise TEGException(
                    status_code=HTTP_400_BAD_REQUEST,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message="Insufficient agent balance for treasury receive",
                    detail=f"Agent has {source.token_balance} AVT, requested {request.amount} AVT"
                )
            
            # Execute transfer: agent → treasury (fee=0)
            transaction = TransferService.execute_transfer(
                db=db,
                sender_id=request.source_agent_id,
                receiver_id=treasury_did,
                amount=request.amount,
                fee_amount=Decimal("0"),
                entry_type=f"treasury_rcv_{request.reason}"[:48],   # W-F: prefixed, never a reserved kind
            )
            # §POCKETBRIDGE5 W-F (Window A) — see treasury_transfer; same class.
            _moved = True
            _txid, _txts = transaction.transaction_id, transaction.timestamp

            def _partial():
                return TreasuryReceiveResponse(
                    transaction_id=_txid, status="completed", amount=request.amount,
                    reason=request.reason, reference_id=request.reference_id,
                    new_treasury_balance=AgentCRUD.get_balance(db, treasury_did),
                    new_source_balance=AgentCRUD.get_balance(db, request.source_agent_id),
                    treasury_did=treasury_did, source_agent_id=request.source_agent_id,
                    timestamp=_txts,
                ).model_dump(mode="json")

            # Best-effort labeling — never a reason to re-run a done transfer.
            try:
                transaction.transaction_type = f"treasury_{request.reason}"[:50]
                if request.reference_id:
                    transaction.attached_message = f"ref:{request.reference_id}"
                db.commit()
                db.refresh(transaction)
            except Exception as _label_e:
                logger.error(f"[TreasuryLabel] tag commit failed (transfer stands): {_label_e}")
                try:
                    db.rollback()
                except Exception:
                    pass

            # Get updated balances
            new_treasury_balance = AgentCRUD.get_balance(db, treasury_did)
            new_source_balance = AgentCRUD.get_balance(db, request.source_agent_id)

            # Emit event to EventStore
            import asyncio
            try:
                await _emit_treasury_transfer_event(
                    sender_id=request.source_agent_id,
                    receiver_id=treasury_did,
                    amount=str(request.amount),
                    transaction_id=transaction.transaction_id,
                    memo=f"treasury_receive:{request.reason}"
                )
            except Exception as e:
                logger.error(f"[TreasuryEventEmit] Schedule failed: {e}")

            log_transaction(logger, "treasury_receive", {
                "transaction_id": transaction.transaction_id,
                "treasury_did": treasury_did,
                "source_agent_id": request.source_agent_id,
                "amount": str(request.amount),
                "reason": request.reason,
                "new_treasury_balance": str(new_treasury_balance),
                "new_source_balance": str(new_source_balance),
            })

            logger.info(
                f"TREASURY RECEIVE: {request.amount} AVT ← {request.source_agent_id} "
                f"(reason: {request.reason}, ref: {request.reference_id}, "
                f"tx: {transaction.transaction_id})"
            )
            
            _resp = TreasuryReceiveResponse(
                transaction_id=transaction.transaction_id,
                status="completed",
                amount=request.amount,
                reason=request.reason,
                reference_id=request.reference_id,
                new_treasury_balance=new_treasury_balance,
                new_source_balance=new_source_balance,
                treasury_did=treasury_did,
                source_agent_id=request.source_agent_id,
                timestamp=transaction.timestamp
            )
            _idem_complete(db, idempotency_key, _resp.model_dump(mode="json"))
            return _resp

        except TEGException as e:
            if _moved:
                # §POCKETBRIDGE5 W-F (Window B): the transfer committed and a
                # LATER step threw — cache the completed response so a same-key
                # retry REPLAYS instead of 409-ing pending for 24h.
                _idem_cache_single(db, idempotency_key, _partial)
            elif getattr(e, "status_code", None) != HTTP_409_CONFLICT:
                _idem_fail(db, idempotency_key, {"status_code": getattr(e, "status_code", None), "detail": str(e)})
            raise
        except ValueError as e:
            if _moved:
                _idem_cache_single(db, idempotency_key, _partial)   # W-F Window B
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Treasury receive failed",
                detail=str(e)
            )
        except Exception as e:
            if _moved:
                _idem_cache_single(db, idempotency_key, _partial)   # W-F Window B
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            logger.error(f"Treasury receive failed: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Treasury receive failed",
                detail=str(e) if settings.debug else None
            )


@router.get(
    "/treasury/info",
    response_model=TreasuryInfoResponse,
    responses={
        403: {"description": "Forbidden — admin auth required"},
    }
)
@log_performance("treasury_info")
async def treasury_info(
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """
    Get real treasury balance and supply metrics.
    
    Unlike the old computed treasury (10M - distributed), this reads
    the actual treasury profile balance after OWL26 seeding.
    """
    try:
        treasury_did = SystemConfigCRUD.get_treasury_did(db)
        treasury = AgentCRUD.get_or_create(db, treasury_did)
        
        # Total supply = treasury + all agent balances
        total_agent_balance = db.query(
            func.sum(AgentTEGProfile.token_balance)
        ).filter(
            AgentTEGProfile.agent_id != treasury_did
        ).scalar() or Decimal("0")
        
        total_supply = treasury.token_balance + total_agent_balance
        
        # Locked supply (staked tokens)
        from ...database.models import Stake
        locked_supply = db.query(
            func.sum(Stake.amount)
        ).filter(
            Stake.is_active == True
        ).scalar() or Decimal("0")
        
        # Agent count (excluding treasury and fee collector)
        fee_collector = SystemConfigCRUD.get_fee_collection_address(db)
        agent_count = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id.notin_([treasury_did, fee_collector]),
            AgentTEGProfile.token_balance > 0
        ).count()
        
        return TreasuryInfoResponse(
            treasury_did=treasury_did,
            treasury_balance=treasury.token_balance,
            total_supply=total_supply,
            circulating_supply=total_agent_balance,
            locked_supply=locked_supply,
            agent_count=agent_count,
            last_updated=datetime.now(timezone.utc)
        )
    
    except Exception as e:
        logger.error(f"Treasury info failed: {e}", exc_info=True)
        raise TEGException(
            status_code=500,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Failed to retrieve treasury info",
            detail=str(e) if settings.debug else None
        )


# =============================================================================
# FEE COLLECTOR ENDPOINTS (Phase 1, 2026-05-08)
# =============================================================================
# fee_collector accumulates fees on every intra-registry + cross-TEG transfer.
# Until Phase 1 there was no admin path to query its balance OR move funds out;
# the docs (oracle/02_tokens.md:142) describe fees-funding-rewards as
# governance-configurable, but it was never wired. These endpoints are the
# foundation for that wiring (Phase 2 builds RewardFundingService on top).


class FeeCollectorInfoResponse(BaseModel):
    """fee_collector balance + identity snapshot."""
    fee_collector_did: str
    balance: Decimal
    last_updated: datetime

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class FeeCollectorDistributeRequest(BaseModel):
    """Move AVT from fee_collector to a target agent (admin manual distribute)."""
    target_agent_id: str = Field(..., description="Target agent DID to receive funds")
    amount: Decimal = Field(..., gt=0, description="Amount of AVT to distribute")
    reason: str = Field(..., description="Reason: staking_reward, manual_payout, audit_correction, …")
    reference_id: Optional[str] = Field(None, description="External reference (e.g., distribution_id)")

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v.as_tuple().exponent < -18:
            raise ValueError("Amount has too many decimal places (max 18)")
        return v

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class FeeCollectorDistributeResponse(BaseModel):
    """Response from a fee_collector → agent distribution."""
    transaction_id: str
    status: str
    amount: Decimal
    reason: str
    reference_id: Optional[str] = None
    new_fee_collector_balance: Decimal
    new_target_balance: Decimal
    fee_collector_did: str
    target_agent_id: str
    timestamp: datetime

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


@router.get(
    "/fee-collector/info",
    response_model=FeeCollectorInfoResponse,
    responses={
        403: {"description": "Forbidden — admin auth required"},
    }
)
@log_performance("fee_collector_info")
async def fee_collector_info(
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """Get the fee_collector balance + identity.

    fee_collector is `teg:system:fee_collector` by default (resolved via
    SystemConfigCRUD.get_fee_collection_address). The fee_collector profile
    is a regular AgentTEGProfile row that bypasses home-frame guards.
    """
    try:
        fee_collector_did = SystemConfigCRUD.get_fee_collection_address(db)
        fee_collector = AgentCRUD.get_or_create(db, fee_collector_did)

        return FeeCollectorInfoResponse(
            fee_collector_did=fee_collector_did,
            balance=fee_collector.token_balance,
            last_updated=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error(f"fee_collector info failed: {e}", exc_info=True)
        raise TEGException(
            status_code=500,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Failed to retrieve fee_collector info",
            detail=str(e) if settings.debug else None,
        )


@router.post(
    "/fee-collector/distribute",
    response_model=FeeCollectorDistributeResponse,
    responses={
        400: {"description": "Bad Request — insufficient fee_collector balance"},
        403: {"description": "Forbidden — admin auth required"},
    }
)
@log_performance("fee_collector_distribute")
async def fee_collector_distribute(
    request: FeeCollectorDistributeRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Move AVT from fee_collector to a target agent (admin manual distribute).

    fee_collector → target_agent atomic transfer. fee=0 (this IS a system op,
    not a transfer that should generate further fees). Used by Phase 2's
    RewardFundingService when policy resolves source as fee_collector, AND
    by manual admin payouts via the Treasury → Fee Collector tab UI.
    """
    with LogContext(
        logger,
        operation="fee_collector_distribute",
        target_agent_id=request.target_agent_id,
        amount=str(request.amount),
        reason=request.reason,
        reference_id=request.reference_id,
    ):
        try:
            _moved = False
            _cached = _idem_claim(db, idempotency_key, "fee_collector_distribute",
                                  {"target": request.target_agent_id, "amount": str(request.amount), "reason": request.reason})
            if _cached is not None:
                return FeeCollectorDistributeResponse(**_cached)

            fee_collector_did = SystemConfigCRUD.get_fee_collection_address(db)

            target = AgentCRUD.get_or_create(db, request.target_agent_id)
            fee_collector = AgentCRUD.get_or_create(db, fee_collector_did)

            if fee_collector.token_balance < request.amount:
                raise TEGException(
                    status_code=HTTP_400_BAD_REQUEST,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message="Insufficient fee_collector balance",
                    detail=f"fee_collector has {fee_collector.token_balance} AVT, requested {request.amount} AVT",
                )

            transaction = TransferService.execute_transfer(
                db=db,
                sender_id=fee_collector_did,
                receiver_id=request.target_agent_id,
                amount=request.amount,
                fee_amount=Decimal("0"),
                entry_type=f"fee_dist_{request.reason}"[:48],   # W-F: prefixed, never a reserved kind
            )
            # §POCKETBRIDGE5 W-F (Window A) — see treasury_transfer; same class.
            _moved = True
            _txid, _txts = transaction.transaction_id, transaction.timestamp

            def _partial():
                return FeeCollectorDistributeResponse(
                    transaction_id=_txid, status="completed", amount=request.amount,
                    reason=request.reason, reference_id=request.reference_id,
                    new_fee_collector_balance=AgentCRUD.get_balance(db, fee_collector_did),
                    new_target_balance=AgentCRUD.get_balance(db, request.target_agent_id),
                    fee_collector_did=fee_collector_did, target_agent_id=request.target_agent_id,
                    timestamp=_txts,
                ).model_dump(mode="json")

            # Best-effort labeling — never a reason to re-run a done transfer.
            try:
                transaction.transaction_type = f"fee_distribute_{request.reason}"[:50]
                if request.reference_id:
                    transaction.attached_message = f"ref:{request.reference_id}"
                db.commit()
                db.refresh(transaction)
            except Exception as _label_e:
                logger.error(f"[FeeLabel] tag commit failed (transfer stands): {_label_e}")
                try:
                    db.rollback()
                except Exception:
                    pass

            new_fee_balance = AgentCRUD.get_balance(db, fee_collector_did)
            new_target_balance = AgentCRUD.get_balance(db, request.target_agent_id)

            # Emit TokensTransferred event from TEG side. The treasury endpoint
            # uses the same _emit_treasury_transfer_event helper; we reuse it
            # because this is structurally identical (system → agent).
            import asyncio
            try:
                await _emit_treasury_transfer_event(
                    sender_id=fee_collector_did,
                    receiver_id=request.target_agent_id,
                    amount=str(request.amount),
                    transaction_id=transaction.transaction_id,
                    memo=f"fee_distribute:{request.reason}",
                )
            except Exception as e:
                logger.error(f"[FeeCollectorEventEmit] Schedule failed: {e}")

            log_transaction(logger, "fee_collector_distribute", {
                "transaction_id": transaction.transaction_id,
                "fee_collector_did": fee_collector_did,
                "target_agent_id": request.target_agent_id,
                "amount": str(request.amount),
                "reason": request.reason,
                "new_fee_collector_balance": str(new_fee_balance),
                "new_target_balance": str(new_target_balance),
            })

            logger.info(
                f"FEE DISTRIBUTE: {request.amount} AVT → {request.target_agent_id} "
                f"(reason: {request.reason}, ref: {request.reference_id}, "
                f"tx: {transaction.transaction_id})"
            )

            _resp = FeeCollectorDistributeResponse(
                transaction_id=transaction.transaction_id,
                status="completed",
                amount=request.amount,
                reason=request.reason,
                reference_id=request.reference_id,
                new_fee_collector_balance=new_fee_balance,
                new_target_balance=new_target_balance,
                fee_collector_did=fee_collector_did,
                target_agent_id=request.target_agent_id,
                timestamp=transaction.timestamp,
            )
            _idem_complete(db, idempotency_key, _resp.model_dump(mode="json"))
            return _resp

        except TEGException as e:
            if _moved:
                # §POCKETBRIDGE5 W-F (Window B): the transfer committed and a
                # LATER step threw — cache the completed response so a same-key
                # retry REPLAYS instead of 409-ing pending for 24h.
                _idem_cache_single(db, idempotency_key, _partial)
            elif getattr(e, "status_code", None) != HTTP_409_CONFLICT:
                _idem_fail(db, idempotency_key, {"status_code": getattr(e, "status_code", None), "detail": str(e)})
            raise
        except ValueError as e:
            if _moved:
                _idem_cache_single(db, idempotency_key, _partial)   # W-F Window B
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="fee_collector distribute failed",
                detail=str(e),
            )
        except Exception as e:
            if _moved:
                _idem_cache_single(db, idempotency_key, _partial)   # W-F Window B
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            logger.error(f"fee_collector distribute failed: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="fee_collector distribute failed",
                detail=str(e) if settings.debug else None,
            )


# =============================================================================
# REWARD FUNDING WATERFALL (Phase 2, 2026-05-08)
# =============================================================================
# Policy-driven funding for ALL treasury-funded reward / grant flows.
# Replaces direct calls to /admin/treasury/transfer with a waterfall that
# tries fee_collector first, then treasury, per the configured policy.
#
# system_config key: "reward_funding_waterfall" — JSON dict, e.g.:
#   {
#     "default":              ["fee_collector", "treasury"],
#     "staking_reward":       ["fee_collector", "treasury"],
#     "dispute_compensation": ["fee_collector", "treasury"],
#     "tutorial_grant":       ["treasury"],          // tutorial = treasury-only
#     "achievement":          ["fee_collector"],     // achievement = fee-only
#     ...
#   }
#
# Operators (admin_treasury) configure per-reason policies. Default is
# ["fee_collector", "treasury"] for any reason without an explicit entry.
# Minting (/admin/token/issue) is NEVER auto-invoked — only used by the
# manual /teg/treasury/mint admin button.

DEFAULT_WATERFALL = ["fee_collector", "treasury"]
WATERFALL_POLICY_KEY = "reward_funding_waterfall"


def _get_waterfall_policy(db: Session) -> Dict[str, list]:
    """Read the current per-reason waterfall config from system_config.

    Returns a dict mapping reason → list of source names. Always contains
    a "default" key (falls back to DEFAULT_WATERFALL if not configured).
    """
    import json
    raw = SystemConfigCRUD.get_value(db, WATERFALL_POLICY_KEY)
    if not raw:
        return {"default": list(DEFAULT_WATERFALL)}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            logger.warning(f"[Waterfall] Invalid policy in system_config (not dict): {raw!r}")
            return {"default": list(DEFAULT_WATERFALL)}
        if "default" not in parsed:
            parsed["default"] = list(DEFAULT_WATERFALL)
        return parsed
    except json.JSONDecodeError:
        logger.warning(f"[Waterfall] Invalid policy JSON in system_config: {raw!r}")
        return {"default": list(DEFAULT_WATERFALL)}


def _resolve_waterfall_for_reason(db: Session, reason: str) -> list:
    """Resolve the source-order list for a given reason, falling back to default."""
    policy = _get_waterfall_policy(db)
    return list(policy.get(reason, policy.get("default", DEFAULT_WATERFALL)))


class RewardFundingPolicyResponse(BaseModel):
    """Current reward funding waterfall policy."""
    policy: Dict[str, list]
    default_waterfall: list
    valid_sources: list

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class RewardFundingPolicyUpdate(BaseModel):
    """Update the reward funding policy. Only "reason → [source...]" pairs.

    Pass `policy` as a full replacement dict; partial updates are not supported
    so the caller's intent is unambiguous. To revert to defaults, send
    `policy: {"default": ["fee_collector", "treasury"]}`.
    """
    policy: Dict[str, list] = Field(
        ...,
        description="Map of reason → ordered source list. Must include 'default' key.",
    )

    @field_validator('policy')
    def validate_policy(cls, v):
        if "default" not in v:
            raise ValueError("policy must include a 'default' key")
        valid_sources = {"fee_collector", "treasury"}
        for reason, sources in v.items():
            if not isinstance(sources, list) or not sources:
                raise ValueError(f"policy[{reason}] must be a non-empty list of source names")
            for s in sources:
                if s not in valid_sources:
                    raise ValueError(
                        f"policy[{reason}] contains invalid source '{s}'. "
                        f"Valid sources: {sorted(valid_sources)}"
                    )
        return v


class RewardFundRequest(BaseModel):
    """Reward funding request — resolves the waterfall internally."""
    target_agent_id: str = Field(..., description="Target agent DID to receive funds")
    amount: Decimal = Field(..., gt=0, description="Amount of AVT to fund")
    reason: str = Field(..., description="Reason — looked up in waterfall policy")
    reference_id: Optional[str] = Field(None, description="External reference (e.g., distribution_id)")

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v.as_tuple().exponent < -18:
            raise ValueError("Amount has too many decimal places (max 18)")
        return v

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class RewardFundLeg(BaseModel):
    """One leg of a waterfall execution — what was drawn from one source."""
    source: str               # "fee_collector" | "treasury"
    source_did: str
    amount: Decimal
    transaction_id: str
    new_source_balance: Decimal

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class RewardFundResponse(BaseModel):
    """Reward funding response — describes the waterfall execution."""
    status: str  # "completed" | "exhausted"
    target_agent_id: str
    total_amount: Decimal
    funded_amount: Decimal           # may be < total_amount if exhausted
    shortfall: Decimal               # total_amount - funded_amount
    legs: list                       # list of RewardFundLeg
    new_target_balance: Decimal
    waterfall_used: list             # the resolved policy list for this reason
    reason: str
    reference_id: Optional[str] = None
    timestamp: datetime

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


@router.get(
    "/reward-funding/policy",
    response_model=RewardFundingPolicyResponse,
    responses={
        403: {"description": "Forbidden — admin auth required"},
    },
)
@log_performance("reward_funding_policy_get")
async def get_reward_funding_policy(
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """Get the current reward funding waterfall policy.

    Returns the per-reason policy dict + the canonical default + the list
    of valid source names so the frontend can render the editor UI without
    a second roundtrip.
    """
    policy = _get_waterfall_policy(db)
    return RewardFundingPolicyResponse(
        policy=policy,
        default_waterfall=list(DEFAULT_WATERFALL),
        valid_sources=["fee_collector", "treasury"],
    )


@router.put(
    "/reward-funding/policy",
    response_model=RewardFundingPolicyResponse,
    responses={
        400: {"description": "Bad Request — invalid policy"},
        403: {"description": "Forbidden — admin auth required"},
    },
)
@log_performance("reward_funding_policy_put")
async def put_reward_funding_policy(
    request: RewardFundingPolicyUpdate,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """Update the reward funding waterfall policy (full replacement).

    Validates source names + presence of 'default' before persisting.
    """
    import json
    SystemConfigCRUD.set_value(db, WATERFALL_POLICY_KEY, json.dumps(request.policy))
    db.commit()
    logger.info(f"[Waterfall] Policy updated: {request.policy}")
    return RewardFundingPolicyResponse(
        policy=request.policy,
        default_waterfall=list(DEFAULT_WATERFALL),
        valid_sources=["fee_collector", "treasury"],
    )


# §REWARDRACE: how often one waterfall leg re-reads its source after a concurrent debit drained it under the leg
REWARD_LEG_ATTEMPTS = 3


@router.post(
    "/reward-fund",
    response_model=RewardFundResponse,
    responses={
        400: {"description": "Funding exhausted — neither fee_collector nor treasury can cover the request"},
        403: {"description": "Forbidden — admin auth required"},
    },
)
@log_performance("reward_fund")
async def reward_fund(
    request: RewardFundRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Fund a reward via the configured waterfall.

    Resolves the per-reason policy, drains sources in order. Each leg is an
    atomic TransferService.execute_transfer (fee=0). If a source has SOME
    but not enough, it's drained completely and the remainder rolls to the
    next source. If all sources are exhausted, returns 400 with a partial
    funded_amount + shortfall so the caller can decide how to handle it.

    Used by:
      - StakingRewardsService.distribute_rewards_to_agent (replaces issue_tokens)
      - Funding requests admin/approve
      - Dispute compensation mints (now drains pool first)
      - Tutorial / onboarding grants
      - Achievement rewards
    """
    with LogContext(
        logger,
        operation="reward_fund",
        target_agent_id=request.target_agent_id,
        amount=str(request.amount),
        reason=request.reason,
        reference_id=request.reference_id,
    ):
        try:
            _moved = False
            _cached = _idem_claim(db, idempotency_key, "reward_fund",
                                  {"target": request.target_agent_id, "amount": str(request.amount), "reason": request.reason})
            if _cached is not None:
                _c = {k: v for k, v in _cached.items() if k != "_kind"}
                if _cached.get("_kind") == "exhausted":
                    from fastapi.responses import JSONResponse
                    return JSONResponse(status_code=HTTP_400_BAD_REQUEST, content=_c)
                return RewardFundResponse(**_c)

            waterfall = _resolve_waterfall_for_reason(db, request.reason)
            treasury_did = SystemConfigCRUD.get_treasury_did(db)
            fee_collector_did = SystemConfigCRUD.get_fee_collection_address(db)
            target = AgentCRUD.get_or_create(db, request.target_agent_id)

            remaining = request.amount
            funded = Decimal("0")
            legs: list = []

            for source in waterfall:
                if remaining <= 0:
                    break

                if source == "fee_collector":
                    sender_did = fee_collector_did
                elif source == "treasury":
                    sender_did = treasury_did
                else:
                    logger.warning(f"[Waterfall] Unknown source '{source}' in policy for {request.reason} — skipping")
                    continue

                _leg_msg = (f"ref:{request.reference_id}|via:{source}"
                            if request.reference_id else f"via:{source}")
                # §REWARDRACE (2026-10-06, agentvault2-09): the balance read below takes no lock, so a funding running
                # at the same moment can drain this source between the read and the leg's debit; execute_transfer
                # then refuses "Insufficient balance" (after its own rollback) and the whole funding used to fail 400
                # although the next source could cover it (measured on sbx-alpha: two 50 fundings 7 ms apart, the
                # second refused while the treasury held plenty). The leg re-reads the source and re-sizes; a source
                # left empty hands the remainder to the next one. The transfer keeps its own sorted lock order (a
                # pre-lock of the source here would take that row out of order and can deadlock against a
                # fee-bearing transfer into the fee collector).
                transaction = None
                leg_amount = Decimal("0")
                for _attempt in range(REWARD_LEG_ATTEMPTS):
                    sender = AgentCRUD.get_or_create(db, sender_did)
                    available = sender.token_balance
                    if available <= 0:
                        break

                    # How much can this source contribute? min(available, remaining)
                    leg_amount = min(available, remaining)
                    try:
                        transaction = TransferService.execute_transfer(
                            db=db,
                            sender_id=sender_did,
                            receiver_id=request.target_agent_id,
                            amount=leg_amount,
                            fee_amount=Decimal("0"),
                            attached_message=_leg_msg,
                            # W-F: the waterfall's journal kind. Prefixed — a reason of
                            # literally "dispute_compensation" tags as
                            # "reward_dispute_compensation", which the exact-match
                            # classifiers file under TRANSIT (a transfer, not a mint).
                            entry_type=f"reward_{request.reason}"[:48],
                        )
                        break
                    except ValueError as _short:
                        if str(_short) != "Insufficient balance":
                            raise          # the integrity check and anything else: never retried
                        transaction = None
                        logger.warning(f"[RewardFund] {source} moved under the leg (attempt {_attempt + 1}): "
                                       f"read {available}, a concurrent debit left less; re-reading it")
                if transaction is None:
                    continue           # this source is empty now (or kept moving): the next source takes the remainder
                # execute_transfer commits the money atomically (it RAISES before any
                # commit on insufficient balance). The instant it returns COMPLETED a
                # same-key retry must NOT re-run this leg (double-pay), so flip _moved and
                # capture the leg accounting HERE — before the cosmetic label commit below.
                # Previously _moved flipped only AFTER that label commit, leaving a narrow
                # window where committed money read as "not moved" → the except deleted the
                # key → a retry re-paid the leg. Capturing accounting here also means a throw
                # past this point caches an ACCURATE partial (§2026-08-12 sharp-edge fix).
                if transaction.status != TransactionStatus.COMPLETED:
                    # Defensive: the waterfall pre-checks balance so this is unreachable, but
                    # never count a leg whose money did not commit.
                    logger.error(f"[RewardFund] leg via {source} status={transaction.status}; skipped")
                    continue
                _moved = True
                new_source_balance = AgentCRUD.get_balance(db, sender_did)
                legs.append({
                    "source": source,
                    "source_did": sender_did,
                    "amount": str(leg_amount),
                    "transaction_id": transaction.transaction_id,
                    "new_source_balance": str(new_source_balance),
                })
                funded += leg_amount
                remaining -= leg_amount

                # Cosmetic reason label — best-effort; the leg accounting is already captured
                # above, so a failure here loses only the label (not money, not the count) and
                # the reward keeps funding the remaining legs.
                try:
                    transaction.transaction_type = f"reward_fund_{request.reason}"[:50]
                    db.commit()
                except Exception as _label_e:
                    logger.error(f"[RewardFund] leg label commit failed (accounting intact): {_label_e}")
                    db.rollback()

                # Emit TokensTransferred event
                import asyncio
                try:
                    await _emit_treasury_transfer_event(
                        sender_id=sender_did,
                        receiver_id=request.target_agent_id,
                        amount=str(leg_amount),
                        transaction_id=transaction.transaction_id,
                        memo=f"reward_fund:{request.reason}:via_{source}",
                    )
                except Exception as e:
                    logger.error(f"[RewardFund] event emit schedule failed: {e}")

            new_target_balance = AgentCRUD.get_balance(db, request.target_agent_id)
            shortfall = request.amount - funded
            status_str = "completed" if shortfall == 0 else "exhausted"

            log_transaction(logger, "reward_fund", {
                "target_agent_id": request.target_agent_id,
                "amount": str(request.amount),
                "funded_amount": str(funded),
                "shortfall": str(shortfall),
                "reason": request.reason,
                "reference_id": request.reference_id,
                "waterfall_used": waterfall,
                "legs": legs,
                "new_target_balance": str(new_target_balance),
            })

            logger.info(
                f"REWARD FUND: {funded}/{request.amount} AVT → {request.target_agent_id} "
                f"(reason: {request.reason}, status: {status_str}, "
                f"waterfall: {waterfall}, legs: {len(legs)})"
            )

            if status_str == "exhausted":
                # Return 400 BUT include the partial-fund details in the response.
                # Callers that want best-effort partial funding can inspect the
                # response body; callers that want all-or-nothing should treat
                # any 400 as a hard failure (they need to roll back the legs).
                #
                # NOTE: legs ARE already committed at this point — partial state
                # is on chain. Caller must reconcile.
                from fastapi.responses import JSONResponse
                _content = {
                    "status": "exhausted",
                    "target_agent_id": request.target_agent_id,
                    "total_amount": str(request.amount),
                    "funded_amount": str(funded),
                    "shortfall": str(shortfall),
                    "legs": legs,
                    "new_target_balance": str(new_target_balance),
                    "waterfall_used": waterfall,
                    "reason": request.reason,
                    "reference_id": request.reference_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "detail": (
                        f"Funding exhausted. Drained {funded} AVT from "
                        f"{[l['source'] for l in legs]}, but {shortfall} AVT "
                        f"could not be sourced from {waterfall}."
                    ),
                }
                # partial legs already committed → cache so a replay never re-pays
                _idem_complete(db, idempotency_key, {"_kind": "exhausted", **_content})
                return JSONResponse(status_code=HTTP_400_BAD_REQUEST, content=_content)

            _resp = RewardFundResponse(
                status=status_str,
                target_agent_id=request.target_agent_id,
                total_amount=request.amount,
                funded_amount=funded,
                shortfall=shortfall,
                legs=legs,
                new_target_balance=new_target_balance,
                waterfall_used=waterfall,
                reason=request.reason,
                reference_id=request.reference_id,
                timestamp=datetime.now(timezone.utc),
            )
            _idem_complete(db, idempotency_key, {"_kind": "ok", **_resp.model_dump(mode="json")})
            return _resp

        except TEGException as e:
            # If any leg already committed, cache the partial as COMPLETED (retry replays
            # the partial, never re-pays) rather than leaving the key 'pending' → 24h 409.
            if _moved:
                _idem_cache_partial(db, idempotency_key,
                                    {"_kind": "exhausted", **_reward_partial_content(request, waterfall, legs, funded)})
            elif getattr(e, "status_code", None) != HTTP_409_CONFLICT:
                _idem_fail(db, idempotency_key, {"status_code": getattr(e, "status_code", None), "detail": str(e)})
            raise
        except ValueError as e:
            if _moved:
                _idem_cache_partial(db, idempotency_key,
                                    {"_kind": "exhausted", **_reward_partial_content(request, waterfall, legs, funded)})
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Reward fund failed",
                detail=str(e),
            )
        except Exception as e:
            if _moved:
                _idem_cache_partial(db, idempotency_key,
                                    {"_kind": "exhausted", **_reward_partial_content(request, waterfall, legs, funded)})
            else:
                _idem_fail(db, idempotency_key, {"error": str(e)})
            logger.error(f"reward_fund failed: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Reward fund failed",
                detail=str(e) if settings.debug else None,
            )


# =============================================================================
# Cross-TEG Treasury Endpoints (one-way: origin TEG → satellite TEGs)
# =============================================================================

class CrossTEGTreasuryDebitRequest(BaseModel):
    """Debit local treasury for outbound cross-TEG transfer."""
    amount: Decimal = Field(..., gt=0, description="Amount to debit from treasury")
    target_teg_id: str = Field(..., description="Destination TEG identifier")
    reason: str = Field(default="cross_teg_fund", description="Reason for debit")
    correlation_id: Optional[str] = Field(None, description="Correlation ID for audit trail")

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class CrossTEGTreasuryCreditRequest(BaseModel):
    """Credit local treasury from inbound cross-TEG transfer."""
    amount: Decimal = Field(..., gt=0, description="Amount to credit to treasury")
    source_teg_id: str = Field(..., description="Source TEG identifier (must be origin TEG)")
    reason: str = Field(default="cross_teg_fund", description="Reason for credit")
    correlation_id: Optional[str] = Field(None, description="Correlation ID for audit trail")

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class CrossTEGTreasuryResponse(BaseModel):
    """Response from cross-TEG treasury operation."""
    transaction_id: str
    status: str
    amount: Decimal
    direction: str  # "debit" or "credit"
    new_treasury_balance: Decimal
    correlation_id: Optional[str] = None
    timestamp: datetime

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


@router.post(
    "/treasury/external-debit",
    response_model=CrossTEGTreasuryResponse,
    responses={
        400: {"description": "Insufficient treasury balance"},
        403: {"description": "Admin auth required"},
    }
)
@log_performance("treasury_external_debit")
async def treasury_external_debit(
    request: CrossTEGTreasuryDebitRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """
    Debit local treasury for outbound cross-TEG fund transfer.

    Called by the origin registry (Registry-A) when sending treasury
    funds to a satellite TEG. Deducts from treasury balance and creates
    an auditable transaction record.
    """
    import uuid as _uuid
    with LogContext(logger, operation="treasury_external_debit",
                    amount=str(request.amount), target_teg=request.target_teg_id):
        try:
            treasury_did = SystemConfigCRUD.get_treasury_did(db)
            treasury = AgentCRUD.get_or_create(db, treasury_did)

            if treasury.token_balance < request.amount:
                raise TEGException(
                    status_code=HTTP_400_BAD_REQUEST,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message="Insufficient treasury balance for cross-TEG debit",
                    detail=f"Treasury has {treasury.token_balance} AVT, requested {request.amount} AVT"
                )

            # Debit treasury directly
            treasury.token_balance -= request.amount
            # Keep audited_balance in sync (treasury debit is a legitimate operation)
            treasury.audited_balance = treasury.token_balance

            # Create transaction record for audit
            tx_id = str(_uuid.uuid4())
            transaction = TEGTransaction(
                transaction_id=tx_id,
                sender_agent_id=treasury_did,
                receiver_agent_id=f"cross-teg:{request.target_teg_id}",
                amount=request.amount,
                fee_amount=Decimal("0"),
                status="completed",
                transaction_type=f"cross_teg_outflow_{request.reason}"[:50],
                attached_message=f"Cross-TEG debit → {request.target_teg_id} | corr:{request.correlation_id or 'none'}"
            )
            db.add(transaction)
            db.commit()
            db.refresh(treasury)

            new_balance = treasury.token_balance

            # Emit event for cross-TEG debit
            import asyncio
            try:
                await _emit_treasury_transfer_event(
                    sender_id=treasury_did,
                    receiver_id=f"cross-teg:{request.target_teg_id}",
                    amount=str(request.amount),
                    transaction_id=tx_id,
                    memo=f"cross_teg_debit:{request.reason}"
                )
            except Exception as e:
                logger.error(f"[TreasuryEventEmit] Schedule failed: {e}")

            logger.info(
                f"CROSS-TEG TREASURY DEBIT: {request.amount} AVT → {request.target_teg_id} "
                f"(treasury now: {new_balance}, corr: {request.correlation_id})"
            )

            return CrossTEGTreasuryResponse(
                transaction_id=tx_id,
                status="completed",
                amount=request.amount,
                direction="debit",
                new_treasury_balance=new_balance,
                correlation_id=request.correlation_id,
                timestamp=transaction.timestamp
            )

        except TEGException:
            raise
        except Exception as e:
            logger.error(f"Treasury external debit failed: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Treasury external debit failed",
                detail=str(e) if settings.debug else None
            )


@router.post(
    "/treasury/external-credit",
    response_model=CrossTEGTreasuryResponse,
    responses={
        403: {"description": "Admin auth required"},
    }
)
@log_performance("treasury_external_credit")
async def treasury_external_credit(
    request: CrossTEGTreasuryCreditRequest,
    http_request: Request,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    _gate: None = Depends(_external_credit_gate),
    db: Session = Depends(get_db)
):
    """
    Credit local treasury from inbound cross-TEG fund transfer.

    Called on a satellite TEG when the origin TEG (TEG-A) sends
    treasury funds. Credits the local treasury balance and creates
    an auditable transaction record.
    """
    # §SECFIX-11 (2026-09-25): RETIRED behind a positive flag. It credits the treasury by the amount the caller states,
    # with a fresh id on every call (no idempotency) and no source check, and any internal identity of any trusted domain
    # passed its auth: a federated peer's registry reached it through this frame's nginx-teg (measured on the sandbox
    # pair: the peer's certificate got as far as body validation). Nothing calls it (the registry has no caller; one
    # legacy Frame A script, scripts/consolidate_dual_teg_profiles.py). Treasury-to-treasury funding is
    # /cross-teg/treasury-fund, which is idempotent on the correlation id and checks its source (§SECFIX-3).
    # TEG_EXTERNAL_CREDIT_ENABLED=true brings it back, for this TEG's own frame only: _external_credit_gate, a dependency,
    # so both answers come before the body is validated.
    import uuid as _uuid
    with LogContext(logger, operation="treasury_external_credit",
                    amount=str(request.amount), source_teg=request.source_teg_id):
        try:
            treasury_did = SystemConfigCRUD.get_treasury_did(db)
            treasury = AgentCRUD.get_or_create(db, treasury_did)

            # Credit treasury
            treasury.token_balance += request.amount
            # Keep audited_balance in sync (treasury credit is a legitimate operation)
            treasury.audited_balance = treasury.token_balance

            # Create transaction record for audit
            tx_id = str(_uuid.uuid4())
            transaction = TEGTransaction(
                transaction_id=tx_id,
                sender_agent_id=f"cross-teg:{request.source_teg_id}",
                receiver_agent_id=treasury_did,
                amount=request.amount,
                fee_amount=Decimal("0"),
                status="completed",
                transaction_type=f"cross_teg_inflow_{request.reason}"[:50],
                attached_message=f"Cross-TEG credit ← {request.source_teg_id} | corr:{request.correlation_id or 'none'}"
            )
            db.add(transaction)
            db.commit()
            db.refresh(treasury)

            new_balance = treasury.token_balance

            # Emit event for cross-TEG credit
            import asyncio
            try:
                await _emit_treasury_transfer_event(
                    sender_id=f"cross-teg:{request.source_teg_id}",
                    receiver_id=treasury_did,
                    amount=str(request.amount),
                    transaction_id=tx_id,
                    memo=f"cross_teg_credit:{request.reason}"
                )
            except Exception as e:
                logger.error(f"[TreasuryEventEmit] Schedule failed: {e}")

            logger.info(
                f"CROSS-TEG TREASURY CREDIT: {request.amount} AVT ← {request.source_teg_id} "
                f"(treasury now: {new_balance}, corr: {request.correlation_id})"
            )

            return CrossTEGTreasuryResponse(
                transaction_id=tx_id,
                status="completed",
                amount=request.amount,
                direction="credit",
                new_treasury_balance=new_balance,
                correlation_id=request.correlation_id,
                timestamp=transaction.timestamp
            )

        except Exception as e:
            logger.error(f"Treasury external credit failed: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Treasury external credit failed",
                detail=str(e) if settings.debug else None
            )


# =============================================================================
# PB-2 (2026-05-10) — Cross-TEG treasury-fund SENDER (admin-keyed orchestrator)
#
# Architectural intent: this is the registry-orchestrator-callable primitive
# for treasury-to-treasury cross-TEG moves. It performs:
#   1. Local treasury debit (atomic DB).
#   2. mTLS-authed POST to peer's /api/v1/cross-teg/treasury-fund via the
#      existing CrossTEGClientFactory (uses SPIRE certs, prod-routed nginx
#      federation path — zero new nginx config).
#   3. Atomic rollback on peer 4xx (deterministic rejection).
#   4. Leave-pending on peer 5xx / network error (transient — caller retries
#      with same correlation_id; peer idempotency dedups on its side).
#
# Anti-abuse:
#   - Admin Bearer auth required.
#   - Sender/receiver agent_id are HARDCODED to treasury_did and
#     "cross-teg:<source_teg_id>" — caller cannot supply arbitrary endpoints.
#   - Cannot be repurposed for agent-to-agent / market trading bypass.
#   - All calls logged with sender + receiver + correlation + reason for audit.
#
# Fee posture: ARCHITECTURALLY FEE-EXEMPT. Treasury-to-treasury moves are
# internal protocol primitives, not market transactions. Trading-style
# transfers go through TransferService.execute_transfer (regular /teg/transfer)
# which charges fees. Do NOT add fee logic here.
# =============================================================================

class CrossTEGFundSendRequest(BaseModel):
    """Sender-side cross-TEG treasury fund request (registry orchestrator → local TEG)."""
    amount: Decimal = Field(..., gt=0, description="AVT to send to peer treasury")
    target_teg_id: str = Field(..., description="Target TEG identifier (must resolve via PARTNER_TEGS or target_url override)")
    target_url: Optional[str] = Field(None, description="Optional override for target TEG mTLS URL (e.g., https://nginx-federation:8443)")
    correlation_id: str = Field(..., description="Idempotency anchor — used as TEGTransaction.transaction_id on both sides")
    reason: str = Field(default="cross_teg_fund", description="Reason tag for audit trail")

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class CrossTEGFundSendResponse(BaseModel):
    """Sender-side cross-TEG treasury fund response."""
    transaction_id: str
    status: str  # "completed" | "rolled_back" | "pending_uncertain"
    amount: Decimal
    direction: str = "debit"
    new_treasury_balance: Decimal
    correlation_id: str
    target_teg_id: str
    timestamp: datetime
    peer_response: Optional[Dict] = None

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


@router.post(
    "/treasury/cross-teg-fund-send",
    response_model=CrossTEGFundSendResponse,
    responses={
        400: {"description": "Bad request (insufficient balance, unknown peer, invalid amount)"},
        403: {"description": "Admin auth required"},
        409: {"description": "Pending state conflict — same correlation_id mid-flight"},
        502: {"description": "Peer rejected (deterministic; local debit rolled back)"},
        503: {"description": "Peer unreachable / 5xx (transient; local debit pending, caller may retry with same correlation_id)"},
    }
)
@log_performance("treasury_cross_teg_fund_send")
async def treasury_cross_teg_fund_send(
    request: CrossTEGFundSendRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """PB-2 (2026-05-10): Sender-side cross-TEG treasury fund — admin orchestrator entry point.

    Flow:
      1. Idempotency: existing completed TEGTransaction → return idempotent success.
      2. Pre-flight: resolve target URL via PARTNER_TEGS or override, check balance.
      3. Phase 1: insert TEGTransaction(status='pending') + debit local treasury → commit.
      4. Phase 2: mTLS call peer's /api/v1/cross-teg/treasury-fund via CrossTEGClientFactory.
      5. Phase 3a (peer 200): update TEGTransaction → 'completed' → commit. Emit event.
      6. Phase 3b (peer 4xx): re-credit treasury + mark TEGTransaction 'reversed' → 502.
      7. Phase 3c (peer 5xx / network): leave 'pending' (transient — caller retries with same
         correlation_id; peer idempotency dedups; local commits on next attempt).
    §OPPROV (2026-09-27), a retry (the drain of an operator purge depends on it): the correlation id is bound to the
    amount and partner its row was first sent with (anything else is 409, nothing sent); resuming a 'pending' or
    'failed' row debits nothing, so it skips the balance check; and a 4xx on a resume is 409 with NO re-credit, the row
    left pending, because the first attempt may have landed (tests/test_fund_send_resume.py).
    """
    import uuid as _uuid
    import asyncio
    from ...core.cross_teg.client import CrossTEGClient
    # Local imports to avoid circular dependency at module load
    from ..cross_teg_router import resolve_partner_url, teg_client_factory

    correlation_id = request.correlation_id
    target_teg_id = request.target_teg_id

    with LogContext(
        logger,
        operation="treasury_cross_teg_fund_send",
        amount=str(request.amount),
        target_teg=target_teg_id,
        correlation_id=correlation_id,
    ):
        # ── Step 0: Idempotency replay check ──
        existing_tx = db.query(TEGTransaction).filter(
            TEGTransaction.transaction_id == correlation_id
        ).first()

        # §OPPROV (2026-09-27): a correlation id names ONE send, so a retry must name what its row was first sent with.
        # A resume paid the peer the REQUEST's amount and target, not the row's: a retry naming another amount moved a
        # value the ledger never debited, and one naming another partner paid a second peer for one debit; a replay of a
        # completed id with another amount was answered "completed" though nothing of it moved. Refused, nothing sent.
        if existing_tx is not None:
            _first_target = f"cross-teg:{target_teg_id}"
            if (existing_tx.receiver_agent_id != _first_target
                    or Decimal(str(existing_tx.amount)) != Decimal(str(request.amount))):
                logger.error(
                    f"[CROSS-TEG-FUND-SEND] REFUSED corr={correlation_id}: first sent as {existing_tx.amount} to "
                    f"{existing_tx.receiver_agent_id} ({existing_tx.status}); this request names {request.amount} to "
                    f"{_first_target}"
                )
                raise TEGException(
                    status_code=409,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message="Cross-TEG fund-send conflict: this correlation id was first used for a different send",
                    detail=(
                        f"correlation_id={correlation_id} was first sent as {existing_tx.amount} to "
                        f"{existing_tx.receiver_agent_id} (now {existing_tx.status}); this request names "
                        f"{request.amount} to {_first_target}. Nothing was sent; a different send takes a new id."
                    ),
                )

        if existing_tx is not None and existing_tx.status == "completed":
            # True idempotent replay: peer + local both succeeded last time.
            treasury_did = SystemConfigCRUD.get_treasury_did(db)
            cur_balance = AgentCRUD.get_balance(db, treasury_did)
            logger.info(
                f"[CROSS-TEG-FUND-SEND] IDEMPOTENT replay corr={correlation_id} → returning prior success"
            )
            return CrossTEGFundSendResponse(
                transaction_id=correlation_id,
                status="completed",
                amount=existing_tx.amount,
                direction="debit",
                new_treasury_balance=cur_balance,
                correlation_id=correlation_id,
                target_teg_id=target_teg_id,
                timestamp=existing_tx.timestamp,
                peer_response=None,
            )

        # ── Step 1: Resolve target URL (PARTNER_TEGS or caller override) ──
        try:
            target_url = resolve_partner_url(target_teg_id, request.target_url)
        except KeyError:
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message=f"Unknown partner TEG: {target_teg_id}",
                detail=f"Not in PARTNER_TEGS config and no target_url override provided. correlation_id={correlation_id}",
            )

        if teg_client_factory is None:
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Cross-TEG client factory not initialized (CROSS_TEG_ENABLED=false?)",
            )

        # ── Step 2: Pre-flight — balance check (a send that DEBITS) + Phase 1 atomic local debit ──
        # §OPPROV (2026-09-27): a resume ('pending', or 'failed' = written down by the stale-outflow sweeper) debits
        # nothing: its debit stands from the first attempt. It met the balance check all the same, so an operator purge's
        # drain, which sends the treasury's whole balance, could never resume its own stalled send: the treasury read 0
        # (its own debit) < the amount, and the value stayed in transit.
        treasury_did = SystemConfigCRUD.get_treasury_did(db)
        treasury = AgentCRUD.get_or_create(db, treasury_did)
        resuming = existing_tx is not None and existing_tx.status in ("pending", "failed")

        if not resuming and treasury.token_balance < request.amount:
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Insufficient treasury balance for cross-TEG fund-send",
                detail=(
                    f"Treasury has {treasury.token_balance} AVT, requested {request.amount} AVT. "
                    f"Mint-on-demand is the registry orchestrator's responsibility — call /admin/token/issue first."
                ),
            )

        # Insert pending TEGTransaction OR resume existing pending/reversed
        if existing_tx is None:
            treasury.token_balance -= request.amount
            treasury.audited_balance = treasury.token_balance
            tx = TEGTransaction(
                transaction_id=correlation_id,
                sender_agent_id=treasury_did,
                receiver_agent_id=f"cross-teg:{target_teg_id}",
                amount=request.amount,
                fee_amount=Decimal("0"),  # treasury-to-treasury fee-exempt by design
                status="pending",
                transaction_type=f"cross_teg_outflow_{request.reason}"[:50],
                attached_message=(
                    f"Cross-TEG fund-send → {target_teg_id} | corr:{correlation_id} | reason:{request.reason}"
                ),
            )
            db.add(tx)
        elif existing_tx.status in ("pending", "failed"):
            # 'failed' here means the stale-outflow sweeper wrote the row down
            # (status-only — it never re-credits), so the debit still stands and
            # a retry must NOT re-debit; it just re-attempts delivery, exactly
            # like 'pending'. Without this the `else` below would 409 and the
            # sweeper would silently make swept transfers unretryable.
            logger.warning(
                f"[CROSS-TEG-FUND-SEND] resuming {existing_tx.status} tx corr={correlation_id} — "
                f"prior peer call may have succeeded; relying on peer idempotency"
            )
            existing_tx.status = "pending"
            tx = existing_tx
        elif existing_tx.status == "reversed":
            # Caller is explicitly retrying after a prior rollback. Re-debit + flip back.
            # Was compared against "rolled_back", a value the enum cannot hold, so this
            # branch was unreachable and a retry fell through to the 409 below. (2026-07-29)
            logger.warning(
                f"[CROSS-TEG-FUND-SEND] retry after reversed corr={correlation_id} — re-debiting"
            )
            treasury.token_balance -= request.amount
            treasury.audited_balance = treasury.token_balance
            existing_tx.status = "pending"
            tx = existing_tx
        else:
            # Unknown status — fail safe
            raise TEGException(
                status_code=409,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message=f"Cross-TEG-fund-send conflict: unexpected tx status '{existing_tx.status}'",
            )

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"[CROSS-TEG-FUND-SEND] local commit failed: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Local treasury debit commit failed",
                detail=str(e) if settings.debug else None,
            )

        # ── Step 3: Phase 2 — mTLS call to peer ──
        client = teg_client_factory.get_client(target_teg_id, target_url)
        peer_result = None
        peer_status_code = None
        peer_error_text = None

        try:
            peer_result = await client.treasury_fund(
                amount=str(request.amount),
                source_teg_id=settings.teg_id,
                correlation_id=correlation_id,
                reason=request.reason,
            )
        except Exception as call_err:
            # Detect 4xx vs 5xx via the underlying httpx exception (CrossTEGClient raises raw).
            import httpx as _httpx
            err_msg = str(call_err)[:500]
            if isinstance(call_err, _httpx.HTTPStatusError):
                peer_status_code = call_err.response.status_code
                try:
                    peer_error_text = call_err.response.text[:500]
                except Exception:
                    peer_error_text = err_msg
            else:
                # Network / timeout / unknown — treat as 5xx transient
                peer_error_text = err_msg

            if peer_status_code is not None and 400 <= peer_status_code < 500 and resuming:
                # §OPPROV (2026-09-27): a 4xx on a RESUME is not a rejection of the send it resumes. The first attempt's
                # outcome is unknown (that is why the row is pending), and the receiver answers a replayed id with its
                # prior success only after its own caller checks: a check that changed since the first attempt (an
                # operator's certificate that expired after its revoke is answered 400 by nginx before any TEG sees the
                # call) refuses a send the peer may already have credited. Re-crediting here would then pay twice. The
                # row stays pending and the treasury debited, for whoever can read the peer to settle.
                logger.error(
                    f"[CROSS-TEG-FUND-SEND] peer {target_teg_id} answered {peer_status_code} to a RESUMED send "
                    f"corr={correlation_id}: NOT re-credited (the first attempt may have landed); the row stays pending"
                )
                raise TEGException(
                    status_code=409,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message=(f"Peer TEG refused a resumed send (HTTP {peer_status_code}): not re-credited, because "
                             f"the first attempt may have landed; the send stays pending"),
                    detail=(peer_error_text or "")[:300],
                )
            if peer_status_code is not None and 400 <= peer_status_code < 500:
                # Phase 3b: deterministic peer rejection → rollback local debit
                logger.error(
                    f"[CROSS-TEG-FUND-SEND] peer {target_teg_id} REJECTED {peer_status_code}: {peer_error_text}"
                )
                # Re-credit treasury (Vector C compensation)
                treasury_after_rollback = AgentCRUD.get_or_create(db, treasury_did)
                treasury_after_rollback.token_balance += request.amount
                treasury_after_rollback.audited_balance = treasury_after_rollback.token_balance
                tx_after = db.query(TEGTransaction).filter(
                    TEGTransaction.transaction_id == correlation_id
                ).first()
                if tx_after is not None:
                    # MUST be a member of the transactionstatus PG enum
                    # (pending|completed|failed|reversed). Writing a non-member
                    # ("rolled_back") raised InvalidTextRepresentation on the
                    # commit below, which ALSO discarded the treasury re-credit
                    # staged above — stranding the debit in transit and masking
                    # the peer's real 4xx behind a 500. (2026-07-29)
                    tx_after.status = "reversed"
                    # attached_message is VARCHAR(256): the appended peer error
                    # overflowed it and raised StringDataRightTruncation on the
                    # commit below — the SAME failure mode as the enum bug above,
                    # discarding the re-credit. Truncate so the compensation can
                    # always commit; the full peer error is already in the log.
                    _msg = (
                        (tx_after.attached_message or "")
                        + f" | ROLLBACK after peer 4xx: {peer_error_text}"
                    )
                    tx_after.attached_message = _msg[:256]
                db.commit()

                raise TEGException(
                    status_code=502,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message=f"Peer TEG rejected (rolled back): HTTP {peer_status_code}",
                    detail=peer_error_text[:300],
                )
            else:
                # Phase 3c: peer 5xx / network → leave pending (transient)
                logger.warning(
                    f"[CROSS-TEG-FUND-SEND] peer {target_teg_id} TRANSIENT failure "
                    f"(status={peer_status_code}, err={peer_error_text}) — leaving tx pending; "
                    f"caller may retry with same correlation_id"
                )
                raise TEGException(
                    status_code=503,
                    error_code=ErrorCode.SYS_INTERNAL_ERROR,
                    message="Peer TEG unreachable or 5xx (status uncertain — retry-safe)",
                    detail=peer_error_text[:300],
                )

        # ── Step 4: Phase 3a — peer success → mark completed ──
        tx_completed = db.query(TEGTransaction).filter(
            TEGTransaction.transaction_id == correlation_id
        ).first()
        if tx_completed is not None:
            tx_completed.status = "completed"
            # Same VARCHAR(256) ceiling as the rollback path: on a retry the
            # message already carries the prior ROLLBACK note, so appending
            # peer_tx overflowed and the commit failed AFTER the peer had
            # already taken the money — leaving a settled transfer recorded as
            # 'pending'. Truncate so the status can always be written.
            _cmsg = (
                (tx_completed.attached_message or "")
                + f" | peer_tx:{peer_result.get('transaction_id', 'unknown')[:60]}"
            )
            tx_completed.attached_message = _cmsg[:256]
        db.commit()

        # ── Step 5: Emit TokensTransferred event (fire-and-forget) ──
        try:
            await _emit_treasury_transfer_event(
                sender_id=treasury_did,
                receiver_id=f"cross-teg:{target_teg_id}",
                amount=str(request.amount),
                transaction_id=correlation_id,
                memo=f"cross_teg_treasury_fund_send:{request.reason}",
            )
        except Exception as e:
            logger.error(f"[CROSS-TEG-FUND-SEND] event schedule failed: {e}")

        # Refresh treasury balance for response
        new_balance = AgentCRUD.get_balance(db, treasury_did)

        logger.info(
            f"CROSS-TEG-FUND-SEND SUCCESS: {request.amount} AVT → {target_teg_id} "
            f"(treasury now: {new_balance}, corr: {correlation_id})"
        )

        return CrossTEGFundSendResponse(
            transaction_id=correlation_id,
            status="completed",
            amount=request.amount,
            direction="debit",
            new_treasury_balance=new_balance,
            correlation_id=correlation_id,
            target_teg_id=target_teg_id,
            timestamp=tx_completed.timestamp if tx_completed else datetime.now(timezone.utc),
            peer_response=peer_result,
        )


# ─────────────────────────────────────────────────────────────────────────
# Cross-Frame FX — reserve-leg primitive (WS-D, 2026-06-02)
#
# A single admin move the source registry's FX swap orchestrator uses to
# settle ONE leg of a cross-frame swap:
#   • agent       → fx_reserve     (source lock)
#   • fx_reserve  → recipient      (destination credit)
#   • fx_reserve  → fee_collector  (destination fee)
#   • fx_reserve  → agent          (compensation / refund)
# Hard constraint: the fx_reserve system account MUST be one side → this
# endpoint can only move value into/out of the FX reserve, never drain an
# arbitrary agent. Floor-aware (won't take the reserve below `floor`) +
# idempotent (dedup on idempotency_key). The ledger move is the standard
# execute_transfer (fee=0, exact) → emits LedgerBalanceChanged(kind=transfer)
# → transit_net → per-frame Δ=0 by construction (a transfer nets to zero).
# Used by routers/teg_integration._fx_cross_currency_swap on the registry.
# ─────────────────────────────────────────────────────────────────────────

_FX_RESERVE_DID = "did:theprotocol:teg_system_fx_reserve"


class FxMoveRequest(BaseModel):
    from_did: str = Field(..., description="Source DID, or sentinel @fx_reserve/@fee_collector/@treasury")
    to_did: str = Field(..., description="Target DID, or sentinel @fx_reserve/@fee_collector/@treasury")
    amount: Decimal = Field(..., gt=0)
    reason: str = Field("fx_swap", max_length=48)
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    floor: Optional[Decimal] = Field(default=None, ge=0)


class FxMoveResponse(BaseModel):
    transaction_id: str
    status: str
    from_did: str
    to_did: str
    amount: Decimal
    from_balance: Decimal
    to_balance: Decimal
    idempotent_replay: bool = False


@router.post("/fx/move", response_model=FxMoveResponse)
async def fx_move(
    request: FxMoveRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """Move value into/out of the FX reserve for ONE leg of a cross-frame swap (WS-D)."""
    def _resolve(did: str) -> str:
        d = (did or "").strip()
        if d == "@fx_reserve":
            return _FX_RESERVE_DID
        if d == "@fee_collector":
            return SystemConfigCRUD.get_fee_collection_address(db)
        if d == "@treasury":
            return SystemConfigCRUD.get_treasury_did(db)
        return d

    from_did = _resolve(request.from_did)
    to_did = _resolve(request.to_did)

    if _FX_RESERVE_DID not in (from_did, to_did):
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="fx/move requires the fx_reserve system account on one side",
        )
    if from_did == to_did:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="fx/move from_did and to_did must differ",
        )

    ref = f"fxref:{request.idempotency_key}"

    def _replay(txn: TEGTransaction) -> FxMoveResponse:
        return FxMoveResponse(
            transaction_id=txn.transaction_id,
            status="completed",
            from_did=from_did,
            to_did=to_did,
            amount=request.amount,
            from_balance=AgentCRUD.get_balance(db, from_did),
            to_balance=AgentCRUD.get_balance(db, to_did),
            idempotent_replay=True,
        )

    # Idempotency: replay a prior COMPLETED move with the same key (no re-move).
    # §2026-06-13 (fxref hardening, mirrors the exref backstop): a plain lookup
    # protects sequential retries but NOT concurrent/queued ones — under a TEG
    # pool-lock convoy a timed-out attempt can still commit later while the retry
    # lookup-misses and fires again. The status filter matters: a FAILED row moved
    # no money and must NOT satisfy the replay (the caller's retry must re-execute);
    # a PENDING row is mid-flight — too recent → tell the caller to retry; stale →
    # the process died between create_transfer and the balance commit (no money
    # moved), write it down to failed so the key frees up. uq_teg_tx_fxref_live
    # (migration 0006) is the real backstop for the concurrent case below.
    rows = (
        db.query(TEGTransaction)
        .filter(TEGTransaction.attached_message == ref)
        .order_by(TEGTransaction.timestamp.desc())
        .all()
    )
    completed = next((r for r in rows if r.status == TransactionStatus.COMPLETED), None)
    if completed is not None:
        return _replay(completed)
    pending = next((r for r in rows if r.status == TransactionStatus.PENDING), None)
    if pending is not None:
        age = datetime.now(timezone.utc) - (pending.timestamp or datetime.now(timezone.utc))
        if age < timedelta(seconds=120):
            raise TEGException(
                status_code=HTTP_409_CONFLICT,
                error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                message="fx/move leg in flight for this idempotency key — retry shortly",
            )
        pending.status = TransactionStatus.FAILED
        pending.error_message = "stale pending fxref leg written down (no balance movement)"
        db.commit()

    # §LEDGERGATE: money INTO the reserve starts a movement (a swap's first leg, the keeper's top-up) and waits for a
    # ledger that can record it; a leg OUT of the reserve finishes a swap already paid for and always runs.
    if to_did == _FX_RESERVE_DID:
        await require_ledger("/api/v1/admin/fx/move")

    # Ensure both accounts exist (system rows are ordinary profiles).
    AgentCRUD.get_or_create(db, from_did)
    AgentCRUD.get_or_create(db, to_did)

    # Solvency / floor — only meaningful when the reserve is the SOURCE.
    if from_did == _FX_RESERVE_DID:
        reserve_bal = AgentCRUD.get_balance(db, _FX_RESERVE_DID)
        floor = request.floor if request.floor is not None else Decimal("0")
        if (reserve_bal - request.amount) < floor:
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                message=(
                    f"fx_reserve solvency gate: balance {reserve_bal} - {request.amount} "
                    f"< floor {floor}"
                ),
            )

    try:
        txn = TransferService.execute_transfer(
            db=db,
            sender_id=from_did,
            receiver_id=to_did,
            amount=request.amount,
            fee_amount=Decimal("0"),
            attached_message=ref,
        )
    except IntegrityError:
        # uq_teg_tx_fxref_live (migration 0006): a concurrent attempt with the same
        # key already holds the row — this attempt rolled back and moved NO money.
        # Serve the winner if it completed, else signal in-flight.
        db.rollback()
        winner = (
            db.query(TEGTransaction)
            .filter(
                TEGTransaction.attached_message == ref,
                TEGTransaction.status == TransactionStatus.COMPLETED,
            )
            .order_by(TEGTransaction.timestamp.desc())
            .first()
        )
        if winner is not None:
            return _replay(winner)
        raise TEGException(
            status_code=HTTP_409_CONFLICT,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="fx/move leg in flight for this idempotency key — retry shortly",
        )
    except ValueError as e:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=f"fx/move transfer failed: {e}",
        )

    txn.transaction_type = f"fx_{request.reason}"[:50]
    db.commit()
    db.refresh(txn)

    _status = txn.status.value if hasattr(txn.status, "value") else str(txn.status)
    return FxMoveResponse(
        transaction_id=txn.transaction_id,
        status=_status,
        from_did=from_did,
        to_did=to_did,
        amount=request.amount,
        from_balance=AgentCRUD.get_balance(db, from_did),
        to_balance=AgentCRUD.get_balance(db, to_did),
    )


class FxReserveResponse(BaseModel):
    fx_reserve_did: str
    balance: Decimal


@router.get("/fx/reserve", response_model=FxReserveResponse)
async def fx_reserve_balance(
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """Read the FX reserve balance — used by the Phase-2 cross-frame AMM, which
    prices off BOTH frames' reserve balances (the source reads its local reserve
    + this endpoint on the dest frame's TEG for the counterparty reserve)."""
    return FxReserveResponse(
        fx_reserve_did=_FX_RESERVE_DID,
        balance=AgentCRUD.get_balance(db, _FX_RESERVE_DID),
    )
