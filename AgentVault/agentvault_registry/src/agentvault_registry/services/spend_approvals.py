"""B3 (RBAC plan) — the step-up approval queue behind ``require_approval_above``.

Before this module, an amount over the agent's approval threshold was a DEAD-END deny
("no approval flow exists — amounts above this limit are refused"). Now the deny PARKS:

  1. the gate calls :func:`step_up`; with no usable approval it creates a PENDING row,
     pushes to the owning human (``security.spend_approval``), and the request is still
     denied — but with an actionable ``approval_pending:<id>`` reason;
  2. the human approves or denies from the Approvals panel (Settings → Approvals, also
     rendered in Pocket) via the rails in ``routers/agent_authz_api.py``;
  3. the agent RETRIES the same spend; :func:`step_up` consumes the APPROVED row
     atomically (single UPDATE … WHERE status='approved' RETURNING) and the spend
     proceeds. One approval authorizes exactly ONE spend of exactly that shape.

Money rules honored:
- Deny-only / pre-escrow: nothing here moves value — Δ-irrelevant by construction.
- The parked row is written through an ISOLATED session (fresh sessionmaker session),
  because the request that triggered it is about to 403 and roll its own transaction
  back — the same problem the liability gate solves with commit-before-raise, solved
  here without committing any of the caller's half-done state.
- Consume-then-allow, never allow-then-consume: if the spend later fails, the human
  re-approves a fresh request; the failure mode is a second ask, never a double spend.
- Expiry is lazy (every query filters ``expires_at``), so no sweeper — B2's pattern.
- Matching is deliberately STRICT: same agent, exact amount, and when both sides carry
  a counterparty/currency they must match. An approval is not a blank cheque.
"""
from __future__ import annotations

import datetime as _dt
import logging
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

PENDING_TTL_MIN = 30    # how long a parked ask waits for the human
APPROVED_TTL_MIN = 15   # how long an approval stays usable before it self-expires


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _dec(v) -> Optional[Decimal]:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


class StepUpVerdict:
    __slots__ = ("allowed", "reason", "approval_id")

    def __init__(self, allowed: bool, reason: str, approval_id: Optional[str] = None):
        self.allowed = allowed
        self.reason = reason
        self.approval_id = approval_id


async def _isolated() -> AsyncSession:
    from agentvault_registry.database import get_async_session_maker
    return get_async_session_maker()()


async def step_up(*, agent_did: str, amount, currency: Optional[str],
                  counterparty_did: Optional[str], policy_reason: str) -> StepUpVerdict:
    """Decide the over-threshold spend: consume a matching approval, or park a new ask.

    Runs entirely on its OWN session/transaction so the caller's inevitable 403 cannot
    roll the parked row away, and never raises — a step-up failure degrades to the
    original hard deny, never to a 500 on a money path.
    """
    amt = _dec(amount)
    if amt is None:
        return StepUpVerdict(False, policy_reason)
    s = await _isolated()
    try:
        # Lazy expiry sweep for this agent (cheap, indexed, keeps the queue honest).
        await s.execute(text(
            "UPDATE agent_spend_approvals SET status='expired', resolved_at=now() "
            "WHERE agent_did=:d AND status IN ('pending','approved') AND expires_at <= now()"
        ), {"d": agent_did})

        # 1. Atomic consume of ONE matching approval. NULL counterparty/currency on the
        #    approval means the ask itself carried none — then the retry must carry none
        #    either for those axes to match (strict, never a wildcard).
        row = (await s.execute(text(
            "UPDATE agent_spend_approvals SET status='consumed', consumed_at=now() "
            "WHERE id = (SELECT id FROM agent_spend_approvals "
            "            WHERE agent_did=:d AND status='approved' AND expires_at > now() "
            "              AND amount = CAST(:a AS NUMERIC) "
            "              AND counterparty_did IS NOT DISTINCT FROM CAST(:c AS VARCHAR) "
            "              AND currency IS NOT DISTINCT FROM CAST(:cur AS VARCHAR) "
            "            ORDER BY resolved_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED) "
            "RETURNING id"
        ), {"d": agent_did, "a": str(amt), "c": counterparty_did, "cur": currency})).first()
        if row:
            await s.commit()
            await _audit("spend_approval_consumed", agent_did, row[0],
                         {"amount": str(amt), "currency": currency})
            logger.info("[B3-STEPUP] approval CONSUMED id=%s did=%s amount=%s",
                        row[0], agent_did, amt)
            return StepUpVerdict(True, f"approval_consumed:{row[0]}", row[0])

        # 2. A live pending twin? Don't spam a second row/push for the same retry loop.
        pend = (await s.execute(text(
            "SELECT id, status FROM agent_spend_approvals "
            "WHERE agent_did=:d AND status IN ('pending','denied') AND expires_at > now() "
            "  AND amount = CAST(:a AS NUMERIC) "
            "  AND counterparty_did IS NOT DISTINCT FROM CAST(:c AS VARCHAR) "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"d": agent_did, "a": str(amt), "c": counterparty_did})).first()
        if pend:
            await s.commit()
            kind = "approval_pending" if pend[1] == "pending" else "approval_denied"
            return StepUpVerdict(False, f"{kind}:{pend[0]}", pend[0])

        # 3. Park a fresh ask + push to the owning human.
        dev_id = (await s.execute(text(
            "SELECT creator_developer_id FROM agents WHERE did=:d"), {"d": agent_did})).scalar()
        if dev_id is None:
            await s.rollback()
            return StepUpVerdict(False, policy_reason)
        spa = f"spa_{secrets.token_hex(18)}"
        await s.execute(text(
            "INSERT INTO agent_spend_approvals "
            "(id, agent_did, developer_id, action, amount, currency, counterparty_did, "
            " status, reason, expires_at) VALUES "
            "(:id, :d, :dev, 'spend', CAST(:a AS NUMERIC), :cur, :c, 'pending', :r, "
            " now() + make_interval(mins => :ttl))"
        ), {"id": spa, "d": agent_did, "dev": int(dev_id), "a": str(amt), "cur": currency,
            "c": counterparty_did, "r": policy_reason[:200], "ttl": PENDING_TTL_MIN})
        await s.commit()
        await _audit("spend_approval_requested", agent_did, spa,
                     {"amount": str(amt), "currency": currency,
                      "counterparty": counterparty_did, "developer_id": int(dev_id)})
        await _push(int(dev_id), spa, agent_did, str(amt), currency)
        logger.info("[B3-STEPUP] approval PARKED id=%s did=%s amount=%s dev=%s",
                    spa, agent_did, amt, dev_id)
        return StepUpVerdict(False, f"approval_pending:{spa}", spa)
    except Exception:  # noqa: BLE001 — degrade to the original deny, never 500 a money path
        logger.warning("[B3-STEPUP] step-up failed did=%s — falling back to hard deny",
                       agent_did, exc_info=True)
        try:
            await s.rollback()
        except Exception:  # noqa: BLE001
            pass
        return StepUpVerdict(False, policy_reason)
    finally:
        await s.close()


async def _push(dev_id: int, approval_id: str, agent_did: str,
                amount: str, currency: Optional[str]) -> None:
    """Best-effort Pocket/desktop push — the human's phone is the whole point of B3."""
    try:
        from agentvault_registry.background_tasks.push_notify import notify
        from agentvault_registry.config import settings
        base = str(getattr(settings, "PUSH_APP_BASE_URL", "")
                   or getattr(settings, "BASE_URL", "") or "").rstrip("/")
        cur = f" {currency}" if currency else ""
        await notify("security.spend_approval", [dev_id],
                     title="Spend approval needed",
                     message=f"Agent {agent_did[:28]}… asks to spend {amount}{cur} "
                             f"(over its approval threshold). Approve or deny in Settings → Approvals.",
                     tags="moneybag", priority="high",
                     click=f"{base}/ui/#/settings?tab=approvals" if base else None)
    except Exception:  # noqa: BLE001
        logger.debug("[B3-STEPUP] push skipped", exc_info=True)


async def _audit(action: str, actor_id: str, approval_id: str, details: Dict[str, Any],
                 actor_type: str = "agent") -> None:
    """Durable lifecycle row on an ISOLATED session (the B1 pattern, rollback-proof)."""
    try:
        s = await _isolated()
        try:
            from agentvault_registry.services.admin_audit import log_ironkey_action
            await log_ironkey_action(
                s, action=action, actor_type=actor_type, actor_id=actor_id,
                target_type="spend_approval", target_id=approval_id,
                outcome="success", severity="info", details=details,
            )
            await s.commit()
        finally:
            await s.close()
    except Exception as e:  # noqa: BLE001
        # §S4: log_ironkey_action guards its own write, but the commit above does
        # not — a failure here means the spend decision happened and its IRONKEY
        # audit row does not exist. Best-effort stays best-effort; silent does not.
        logger.warning(
            "[B3-STEPUP] audit row NOT written for approval=%s action=%s: %s",
            approval_id, action, e,
        )


# ─────────────────────── developer-facing queue operations ───────────────────────

async def list_for_dev(db: AsyncSession, developer_id: int,
                       status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    q = ("SELECT id, agent_did, action, amount, currency, counterparty_did, status, reason, "
         "created_at, expires_at, resolved_at, consumed_at FROM agent_spend_approvals "
         "WHERE developer_id=:dev ")
    p: Dict[str, Any] = {"dev": developer_id, "lim": max(1, min(int(limit), 200))}
    if status:
        q += "AND status=:st "
        p["st"] = status
    q += "ORDER BY created_at DESC LIMIT :lim"
    rows = (await db.execute(text(q), p)).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["amount"] = str(d["amount"])
        for k in ("created_at", "expires_at", "resolved_at", "consumed_at"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        out.append(d)
    return out


async def resolve(db: AsyncSession, developer, approval_id: str, decision: str) -> Dict[str, Any]:
    """Owner (or platform admin) approves/denies ONE pending ask. Raises HTTPException."""
    from fastapi import HTTPException, status as http_status
    if decision not in ("approved", "denied"):
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="decision must be approve|deny")
    row = (await db.execute(text(
        "SELECT id, developer_id, status, expires_at FROM agent_spend_approvals WHERE id=:id"
    ), {"id": approval_id})).first()
    if not row:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="Approval not found")
    if row[1] != developer.id and not bool(getattr(developer, "is_admin", False)):
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, detail="Not your agent's approval")
    if row[2] != "pending":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Approval is {row[2]}")
    # approve → the approval itself gets a FRESH short fuse; deny → resolved terminally.
    # ⚠ asyncpg deduces ONE type per parameter: reusing :st for the varchar SET and a
    # text comparison raises AmbiguousParameterError — so the branch is its own boolean.
    upd = (await db.execute(text(
        "UPDATE agent_spend_approvals SET status=:st, resolved_at=now(), "
        "resolved_by_developer_id=:by, "
        "expires_at = CASE WHEN CAST(:appr AS BOOLEAN) "
        "  THEN now() + make_interval(mins => :ttl) ELSE expires_at END "
        "WHERE id=:id AND status='pending' AND expires_at > now() RETURNING id"
    ), {"st": decision, "appr": decision == "approved", "by": developer.id,
        "id": approval_id, "ttl": APPROVED_TTL_MIN})).first()
    if not upd:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="Approval expired")
    await db.commit()
    await _audit(f"spend_approval_{decision}",
                 str(developer.id), approval_id,
                 {"by_developer_id": developer.id}, actor_type="developer")
    return {"id": approval_id, "status": decision,
            "usable_for_minutes": APPROVED_TTL_MIN if decision == "approved" else 0}
