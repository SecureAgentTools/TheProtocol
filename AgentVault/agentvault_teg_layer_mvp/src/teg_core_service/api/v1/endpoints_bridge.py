"""SF-3: Token Bridge TEG Endpoints — lock/unlock/mint/burn

All four endpoints are idempotent. The natural idempotency primitive is
``bridge_tx_id`` from the request body (required); callers can override
by sending an explicit ``Idempotency-Key`` header. Replaying the same
operation with the same ``bridge_tx_id`` returns the cached response
rather than mutating balances twice.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status, Security
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from ...database.db_session import get_db
from ...database import models
from ...core.security import verify_admin_token
from ...core.idempotency import IdempotencyService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bridge")

class LockReq(BaseModel):
    agent_id: str
    amount: Decimal = Field(gt=0)
    bridge_tx_id: str

def _stored(amount) -> Decimal:
    """An amount as balance_ledger_journal stores it (NUMERIC(36, 18))."""
    return Decimal(str(amount)).quantize(Decimal("1e-18"), rounding=ROUND_HALF_UP)


class MintReq(BaseModel):
    agent_id: str
    amount: Decimal = Field(gt=0)
    bridge_tx_id: str
    source_frame: str


def _bridge_idem_key(op: str, bridge_tx_id: str, header_key: Optional[str]) -> str:
    """Header overrides; otherwise key on (op, bridge_tx_id)."""
    return header_key or f"bridge:{op}:{bridge_tx_id}"


def _bridge_params(req) -> dict:
    """Stable param dict for IdempotencyService request-hash comparison."""
    base = {"agent_id": req.agent_id, "amount": str(req.amount), "bridge_tx_id": req.bridge_tx_id}
    if hasattr(req, "source_frame"):
        base["source_frame"] = req.source_frame
    return base


@router.post("/lock")
def bridge_lock(
    req: LockReq,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    key = _bridge_idem_key("lock", req.bridge_tx_id, idempotency_key)
    cached = IdempotencyService.check_and_create(db, key, "bridge_lock", _bridge_params(req))
    if cached:
        logger.info(f"[Bridge] LOCK idempotent replay {req.bridge_tx_id} -> cached")
        return cached
    try:
        profile = db.execute(select(models.AgentTEGProfile).where(models.AgentTEGProfile.agent_id == req.agent_id).with_for_update()).scalar_one_or_none()
        if not profile: raise HTTPException(404, f"Agent {req.agent_id} not found")
        if profile.token_balance < req.amount: raise HTTPException(400, f"Insufficient: {profile.token_balance} < {req.amount}")
        db.execute(text("SELECT set_config('teg.entry_type','bridge_lock',true), set_config('teg.entry_ref',:r,true)"), {"r": str(req.bridge_tx_id)})
        profile.token_balance -= req.amount
        profile.locked_balance += req.amount
        profile.audited_balance = profile.token_balance
        db.commit()
        logger.info(f"[Bridge] LOCKED {req.amount} from {req.agent_id}")
        response = {"status": "locked", "tx_id": req.bridge_tx_id, "locked_balance": str(profile.locked_balance)}
        IdempotencyService.mark_completed(db, key, response)
        return response
    except HTTPException as e:
        IdempotencyService.mark_failed(db, key, {"status_code": e.status_code, "detail": e.detail})
        raise
    except Exception as e:
        IdempotencyService.mark_failed(db, key, {"error": str(e)})
        raise

@router.post("/unlock")
def bridge_unlock(
    req: LockReq,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    key = _bridge_idem_key("unlock", req.bridge_tx_id, idempotency_key)
    cached = IdempotencyService.check_and_create(db, key, "bridge_unlock", _bridge_params(req))
    if cached:
        logger.info(f"[Bridge] UNLOCK idempotent replay {req.bridge_tx_id} -> cached")
        return cached
    try:
        profile = db.execute(select(models.AgentTEGProfile).where(models.AgentTEGProfile.agent_id == req.agent_id).with_for_update()).scalar_one_or_none()
        if not profile: raise HTTPException(404, f"Agent {req.agent_id} not found")
        # SEC-03 (2026-10-17): an unlock releases one bridge lock this TEG made, once, by the lock's own record: the row
        # the balance journal's trigger wrote in the lock's transaction (entry_type 'bridge_lock', entry_ref its
        # bridge_tx_id), for this agent and this amount, with no release of it before. The admin-token caller (the
        # registry, which binds an unlock to its own lock record since V0619) is no longer the only check: an unlock can
        # no longer release units another mechanism locked, nor release one lock twice once its 24 h idempotency record
        # has expired. Read 2026-10-17 on all eleven TEG databases: no bridge operation was ever journaled, so no lock
        # made before this check is left without its record. Read with the agent's row locked: a concurrent release of
        # the same lock commits first, and this statement sees it.
        _jrows = db.execute(text(
            "SELECT entry_type, delta_locked FROM balance_ledger_journal "
            "WHERE agent_id = :a AND entry_ref = :r AND entry_type IN ('bridge_lock', 'bridge_unlock')"),
            {"a": req.agent_id, "r": str(req.bridge_tx_id)}).all()
        _locks = [d for t, d in _jrows if t == "bridge_lock"]
        if any(t == "bridge_unlock" for t, _ in _jrows):
            raise HTTPException(409, f"Bridge lock {req.bridge_tx_id} was already released on this TEG; nothing unlocked")
        if not _locks:
            raise HTTPException(404, f"No bridge lock {req.bridge_tx_id} for {req.agent_id} on this TEG; nothing unlocked")
        if len(_locks) != 1:
            raise HTTPException(409, f"Bridge lock {req.bridge_tx_id} has {len(_locks)} lock records on this TEG; nothing unlocked")
        if _stored(_locks[0]) != _stored(req.amount):
            raise HTTPException(409, f"Bridge lock {req.bridge_tx_id} locked {_stored(_locks[0])}, not {req.amount}; nothing unlocked")
        if profile.locked_balance < req.amount: raise HTTPException(400, f"Insufficient locked: {profile.locked_balance} < {req.amount}")
        db.execute(text("SELECT set_config('teg.entry_type','bridge_unlock',true), set_config('teg.entry_ref',:r,true)"), {"r": str(req.bridge_tx_id)})
        profile.locked_balance -= req.amount
        profile.token_balance += req.amount
        profile.audited_balance = profile.token_balance
        db.commit()
        logger.info(f"[Bridge] UNLOCKED {req.amount} to {req.agent_id}")
        response = {"status": "unlocked", "tx_id": req.bridge_tx_id, "locked_balance": str(profile.locked_balance)}
        IdempotencyService.mark_completed(db, key, response)
        return response
    except HTTPException as e:
        IdempotencyService.mark_failed(db, key, {"status_code": e.status_code, "detail": e.detail})
        raise
    except Exception as e:
        IdempotencyService.mark_failed(db, key, {"error": str(e)})
        raise

@router.post("/mint")
def bridge_mint(
    req: MintReq,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    key = _bridge_idem_key("mint", req.bridge_tx_id, idempotency_key)
    cached = IdempotencyService.check_and_create(db, key, "bridge_mint", _bridge_params(req))
    if cached:
        logger.info(f"[Bridge] MINT idempotent replay {req.bridge_tx_id} -> cached")
        return cached
    try:
        profile = db.execute(select(models.AgentTEGProfile).where(models.AgentTEGProfile.agent_id == req.agent_id).with_for_update()).scalar_one_or_none()
        if not profile: raise HTTPException(404, f"Agent {req.agent_id} not found")
        profile.wrapped_balance += req.amount
        db.commit()
        logger.info(f"[Bridge] MINTED {req.amount} w-AVT to {req.agent_id} from {req.source_frame}")
        response = {"status": "minted", "tx_id": req.bridge_tx_id, "wrapped_balance": str(profile.wrapped_balance)}
        IdempotencyService.mark_completed(db, key, response)
        return response
    except HTTPException as e:
        IdempotencyService.mark_failed(db, key, {"status_code": e.status_code, "detail": e.detail})
        raise
    except Exception as e:
        IdempotencyService.mark_failed(db, key, {"error": str(e)})
        raise

@router.post("/burn")
def bridge_burn(
    req: MintReq,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    key = _bridge_idem_key("burn", req.bridge_tx_id, idempotency_key)
    cached = IdempotencyService.check_and_create(db, key, "bridge_burn", _bridge_params(req))
    if cached:
        logger.info(f"[Bridge] BURN idempotent replay {req.bridge_tx_id} -> cached")
        return cached
    try:
        profile = db.execute(select(models.AgentTEGProfile).where(models.AgentTEGProfile.agent_id == req.agent_id).with_for_update()).scalar_one_or_none()
        if not profile: raise HTTPException(404, f"Agent {req.agent_id} not found")
        if profile.wrapped_balance < req.amount: raise HTTPException(400, f"Insufficient wrapped: {profile.wrapped_balance} < {req.amount}")
        profile.wrapped_balance -= req.amount
        db.commit()
        logger.info(f"[Bridge] BURNED {req.amount} w-AVT from {req.agent_id}")
        response = {"status": "burned", "tx_id": req.bridge_tx_id, "wrapped_balance": str(profile.wrapped_balance)}
        IdempotencyService.mark_completed(db, key, response)
        return response
    except HTTPException as e:
        IdempotencyService.mark_failed(db, key, {"status_code": e.status_code, "detail": e.detail})
        raise
    except Exception as e:
        IdempotencyService.mark_failed(db, key, {"error": str(e)})
        raise
