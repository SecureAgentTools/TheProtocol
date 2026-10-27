"""
AGORA exchange — escrow mover (admin), 2026-06-12.

ONE endpoint moves every AVT/BVT leg of the org stock exchange:
    • buyer        → exchange_escrow   (order/IPO deposit)
    • exchange_escrow → seller         (trade payout)
    • exchange_escrow → fee_collector  (protocol fee)
    • exchange_escrow → org treasury   (org fee / IPO proceeds)
    • exchange_escrow → buyer          (cancel / expiry / soldout refund)
    • org treasury → exchange_escrow   (dividend pot funding)
    • exchange_escrow → holder         (dividend payout legs)

Faithful clone of /admin/fx/move (endpoints_treasury.py — WS-D primitive), with the
exchange escrow account in place of the FX reserve:

  Hard constraint: `teg:system:exchange_escrow` MUST be one side → this endpoint can
  move value into/out of the exchange escrow only, never between arbitrary agents.
  Floor-aware when the escrow is the source (solvency gate) + idempotent via
  attached_message == "exref:{idempotency_key}" replay lookup (namespace disjoint
  from fx's "fxref:"). The ledger move is the standard TransferService.execute_transfer
  (fee=0, sorted FOR-UPDATE lock ordering, audited_balance integrity) → the balance
  journal trigger + outbox emit LedgerBalanceChanged(kind→transit_net) → per-frame
  Δ=0 by construction (a transfer nets to zero). No teg.entry_type GUC is set here:
  execute_transfer commits internally, so a SET LOCAL from this scope would not reach
  the balance-mutating transaction — same as fx/move; the TEG-side audit label is the
  post-commit transaction_type retag ("exchange_{reason}").

  The `teg:system:` DID prefix is load-bearing: is_system_account() exempts it from
  the home-frame guard, so get_or_create works on every frame.

Caller: the registry's exchange service (services/exchange_service.py) with
TEG_ADMIN_API_KEY — agents never call this directly; their consent is the
authenticated order/IPO/dividend action on the registry.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Security
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_409_CONFLICT

from ...core.security import verify_admin_token
from ...core.error_handling import TEGException, ErrorCode
from ...core.ledger_gate import require_ledger
from ...database.db_session import get_db
from ...database.crud import AgentCRUD, TransferService, SystemConfigCRUD
from ...database.models import TEGTransaction, TransactionStatus

logger = logging.getLogger(__name__)

router = APIRouter()

EXCHANGE_ESCROW_DID = "teg:system:exchange_escrow"


class ExchangeMoveRequest(BaseModel):
    from_did: str = Field(..., description="Source DID, or sentinel @exchange_escrow/@fee_collector")
    to_did: str = Field(..., description="Target DID, or sentinel @exchange_escrow/@fee_collector")
    amount: Decimal = Field(..., gt=0)
    reason: str = Field("move", max_length=48)
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    floor: Optional[Decimal] = Field(default=None, ge=0)


class ExchangeMoveResponse(BaseModel):
    transaction_id: str
    status: str
    from_did: str
    to_did: str
    amount: Decimal
    # Optional: a post-commit balance read may fail; the transfer still succeeded.
    from_balance: Optional[Decimal] = None
    to_balance: Optional[Decimal] = None
    idempotent_replay: bool = False


@router.post("/exchange/move", response_model=ExchangeMoveResponse)
async def exchange_move(
    request: ExchangeMoveRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """Move value into/out of the AGORA exchange escrow for ONE money leg."""
    def _resolve(did: str) -> str:
        d = (did or "").strip()
        if d == "@exchange_escrow":
            return EXCHANGE_ESCROW_DID
        if d == "@fee_collector":
            return SystemConfigCRUD.get_fee_collection_address(db)
        return d

    from_did = _resolve(request.from_did)
    to_did = _resolve(request.to_did)

    if EXCHANGE_ESCROW_DID not in (from_did, to_did):
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="exchange/move requires the exchange_escrow system account on one side",
        )
    if from_did == to_did:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="exchange/move from_did and to_did must differ",
        )

    ref = f"exref:{request.idempotency_key}"

    def _replay(txn: TEGTransaction) -> ExchangeMoveResponse:
        return ExchangeMoveResponse(
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
    # Status filter matters (2026-06-13 incident follow-up): a FAILED row moved
    # no money and must NOT satisfy the replay — the worker retry has to
    # re-execute that leg. A PENDING row is an attempt mid-flight: too recent →
    # tell the caller to come back (its money may still move); stale → the
    # process died between create_transfer and the balance commit, no money
    # moved, write it down to failed so the key frees up for this attempt.
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
                message="exchange/move leg in flight for this idempotency key — retry shortly",
            )
        pending.status = TransactionStatus.FAILED
        pending.error_message = "stale pending exref leg written down (no balance movement)"
        db.commit()

    # §LEDGERGATE: money INTO the escrow starts a movement (an order, an IPO, a dividend pot) and waits for a ledger
    # that can record it; a leg OUT of the escrow (a payout, a fee, a refund) finishes one and always runs.
    if to_did == EXCHANGE_ESCROW_DID:
        await require_ledger("/api/v1/admin/exchange/move")

    # Ensure both accounts exist (system rows are ordinary profiles).
    AgentCRUD.get_or_create(db, from_did)
    AgentCRUD.get_or_create(db, to_did)

    # Solvency / floor — only meaningful when the escrow is the SOURCE.
    if from_did == EXCHANGE_ESCROW_DID:
        escrow_bal = AgentCRUD.get_balance(db, EXCHANGE_ESCROW_DID)
        floor = request.floor if request.floor is not None else Decimal("0")
        if (escrow_bal - request.amount) < floor:
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                message=(
                    f"exchange_escrow solvency gate: balance {escrow_bal} - {request.amount} "
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
            entry_type=f"exchange_{request.reason}",   # §2026-06-18 → ES kind 'exchange_<reason>' (not 'unknown'); Δ-neutral (transit_net)
        )
    except IntegrityError:
        # uq_teg_tx_exref_live (migration 0004): a concurrent attempt with the
        # same key already holds the row — this attempt rolled back and moved
        # NO money. Serve the winner if it completed, else signal in-flight.
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
            message="exchange/move leg in flight for this idempotency key — retry shortly",
        )
    except ValueError as e:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message=f"exchange/move transfer failed: {e}",
        )

    # §ESCROWSCAR-2 (2026-07-29) — PAST THIS LINE THE MONEY HAS ALREADY MOVED.
    # execute_transfer() committed the balance change and marked the row COMPLETED,
    # so from here nothing may turn a settled transfer into a 5xx. It used to:
    # `db.commit()` (relabel), `db.refresh(txn)` and BOTH get_balance() reads were
    # unguarded, and a connection reset under lock convoy in any of them escaped as
    # HTTP 500 "A database error occurred". The caller then believed the deposit had
    # failed and rejected the order without refunding — 997.38 AVT stranded in escrow
    # on 2026-07-29T12:08Z while teg_transactions said `completed`. Same family as the
    # §TEG-IDEMPFIX F1 fix to crud.py::execute_transfer, which never covered this path.
    #
    # Everything the response needs is captured BEFORE the post-commit work, and each
    # post-commit step degrades to a warning. A cosmetic relabel or a stale balance
    # read is worth far less than an accurate answer about whether money moved.
    _txid = txn.transaction_id
    _status = txn.status.value if hasattr(txn.status, "value") else str(txn.status)

    txn.transaction_type = f"exchange_{request.reason}"[:50]
    try:
        db.commit()
        try:
            db.refresh(txn)
            _status = txn.status.value if hasattr(txn.status, "value") else str(txn.status)
        except Exception as _e:  # noqa: BLE001 — post-commit, money already moved
            logger.warning(
                "[exchange/move] post-commit refresh failed for %s (%s) — money is committed, "
                "reporting success", _txid, _e,
            )
    except Exception as _e:  # noqa: BLE001 — the relabel is cosmetic, the transfer is not
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "[exchange/move] transaction_type relabel failed for %s (%s) — money is committed, "
            "reporting success", _txid, _e,
        )

    # Balance reads are informational; a failure here must not mask a settled transfer.
    def _safe_balance(did: str):
        try:
            return AgentCRUD.get_balance(db, did)
        except Exception as _e:  # noqa: BLE001
            logger.warning("[exchange/move] balance read failed for %s (%s) — returning None", did, _e)
            return None

    return ExchangeMoveResponse(
        transaction_id=_txid,
        status=_status,
        from_did=from_did,
        to_did=to_did,
        amount=request.amount,
        from_balance=_safe_balance(from_did),
        to_balance=_safe_balance(to_did),
    )


class ExchangeEscrowResponse(BaseModel):
    escrow_did: str
    balance: Decimal


@router.get("/exchange/escrow", response_model=ExchangeEscrowResponse)
async def exchange_escrow_info(
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """Escrow account balance — the registry's I-X3 solvency check reads this."""
    AgentCRUD.get_or_create(db, EXCHANGE_ESCROW_DID)
    return ExchangeEscrowResponse(
        escrow_did=EXCHANGE_ESCROW_DID,
        balance=AgentCRUD.get_balance(db, EXCHANGE_ESCROW_DID),
    )


class ExchangeBalanceResponse(BaseModel):
    did: str
    balance: Decimal


@router.get("/exchange/balance/{did}", response_model=ExchangeBalanceResponse)
async def exchange_balance(
    did: str,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
):
    """Balance probe for AGORA system rails (Passport gateway solvency sweep)."""
    AgentCRUD.get_or_create(db, did)
    return ExchangeBalanceResponse(did=did, balance=AgentCRUD.get_balance(db, did))
