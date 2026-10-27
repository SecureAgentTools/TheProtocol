"""D6-272 (2026-10-17): the delivery of a cross-registry delegation revoke to the delegate's registry, made durable.

The issuer's revoke (DELETE /api/v1/agents/delegate-cross-registry/{credential_id}) is recorded on the issuer's registry
first (its `ironkey.xreg_delegation_revoke` audit row), and that record is the source of truth: the delegate's registry
asks the issuer's at use (services/xreg_issuer_authority) and is told the delegation is revoked whatever became of the
message. The message tells the delegate's registry to revoke the credential and the grant made from it at once (POST
/api/v1/federation/ironkey/delegation-revoke, idempotent there: a second delivery answers that nothing is left to
revoke). It was sent once: a delegate registry that was down kept its grant row live until its next check, and one that
does not check (XREG_ISSUER_AUTHORITY_MODE shadow or off, or an older image) kept honouring it until it expired.

Now a send that did not land leaves a row in xreg_revokes_owed, written in the transaction of the issuer-side record, and
background_tasks/xreg_revoke_retry sends it again under leadership with the same request:

  * delivered: the delegate's registry answered 2xx; the row closes with done_at;
  * sent again later: no answer, a 5xx, 429, 401, 403, 404, or this registry not counting it an active peer right now
    (the peer down, its identity or its federation with this registry recovering, an older image without the route):
    after 1, 5 and 15 minutes, 1, 3, 6 and 12 hours, then every 24 hours;
  * parked (dead_at): a 400 or 422 (the delegate's registry refuses this request as it stands, so sending it again
    cannot change the answer), the attempt budget spent (XREG_REVOKE_RETRY_MAX_ATTEMPTS, 40 sends: about a month, the
    longest a delegation lives), or the delegation expired (its grant at the delegate's registry expired with it, so
    nothing is left to revoke there).

A parked row is kept and logged; the revoke still stands at the delegate registry's next check. The issuer sees each
revoke's delivery (GET /api/v1/agents/delegate-cross-registry, `revoke_delivery`) and so does an admin
(GET /api/v1/admin/agents/delegation/report, `xreg_revoke_delivery`). Revoking again re-opens a parked row with a fresh
budget. Delta-irrelevant: permission bookkeeping only.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models

logger = logging.getLogger(__name__)

REVOKE_PATH = "/api/v1/federation/ironkey/delegation-revoke"
BACKOFF_SEC = (60, 300, 900, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 24 * 3600)
FINAL_STATUSES = (400, 422)   # the delegate's registry refuses this request as it stands
DEFAULT_MAX_ATTEMPTS = 40
EXPIRED_NOTE = "the delegation expired before its registry took the revoke; its grant there expired with it"
STATES = ("delivered", "retrying", "given_up", "expired")


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def max_attempts() -> int:
    try:
        return max(1, int(os.getenv("XREG_REVOKE_RETRY_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ATTEMPTS


def backoff_seconds(attempts: int) -> int:
    """The wait after the `attempts`-th send that did not land."""
    if attempts <= 0:
        return BACKOFF_SEC[0]
    return BACKOFF_SEC[min(attempts, len(BACKOFF_SEC)) - 1]


def parse_expiry(value: Any) -> Optional[_dt.datetime]:
    """A delegation's expiry from its issue record (ISO 8601), or None when it names none or cannot be read."""
    if not value:
        return None
    try:
        t = _dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=_dt.timezone.utc)


async def send_revoke(db: AsyncSession, credential_id: str, delegate_registry: str) -> Dict[str, Any]:
    """Send the revoke of `credential_id` to `delegate_registry` once, over the federation channel.

    Returns {"delivered", "status" (the delegate registry's HTTP answer or None), "body", "error", "error_class",
    "final"}; never raises. A registry this one does not count an active peer right now answers no status and is sent
    again later (a peer can be reactivated)."""
    import httpx as _httpx
    from fastapi import HTTPException
    from agentvault_registry.routers.guild import _fed_client_config, _resolve_peer_url, _self_public_url
    try:
        target = await _resolve_peer_url(db, delegate_registry)
    except HTTPException as e:
        return {"delivered": False, "status": None, "body": None, "final": False, "error_class": "NotAnActivePeer",
                "error": f"not an active peer of this registry right now ({e.detail})"}
    except Exception as e:  # noqa: BLE001
        return {"delivered": False, "status": None, "body": None, "final": False, "error_class": type(e).__name__,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}
    try:
        cfg, fed_headers = _fed_client_config(target)
        async with _httpx.AsyncClient(**cfg) as client:
            r = await client.post(f"{target}{REVOKE_PATH}",
                                  json={"credential_id": credential_id, "issuer_registry": _self_public_url()},
                                  headers=fed_headers)
    except Exception as e:  # noqa: BLE001 — the transport class: nothing reached the delegate's registry
        return {"delivered": False, "status": None, "body": None, "final": False, "error_class": type(e).__name__,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}
    status = int(r.status_code)
    body = (r.text or "")[:200]
    if 200 <= status < 300:
        return {"delivered": True, "status": status, "body": body, "final": False, "error_class": None, "error": None}
    return {"delivered": False, "status": status, "body": body, "final": status in FINAL_STATUSES,
            "error_class": None, "error": f"HTTP {status}: {body}"}


def next_state(attempts_before: int, outcome: Dict[str, Any], now: _dt.datetime, *, budget: int,
               credential_expires_at: Optional[_dt.datetime]) -> Dict[str, Any]:
    """The pure decision after one send: the columns to write on the owed row."""
    attempts = int(attempts_before or 0) + 1
    status = outcome.get("status")
    if outcome.get("delivered"):
        return {"attempts": attempts, "last_status": status, "last_error": None, "done_at": now}
    err = str(outcome.get("error") or "no answer")[:500]
    if credential_expires_at is not None and credential_expires_at <= now:
        return {"attempts": attempts, "last_status": status, "last_error": EXPIRED_NOTE, "dead_at": now}
    if outcome.get("final") or attempts >= budget:
        return {"attempts": attempts, "last_status": status, "last_error": err, "dead_at": now}
    return {"attempts": attempts, "last_status": status, "last_error": err,
            "next_attempt_at": now + _dt.timedelta(seconds=backoff_seconds(attempts))}


def _apply(row: "models.XRegRevokeOwed", cols: Dict[str, Any]) -> None:
    for k, v in cols.items():
        setattr(row, k, v)


async def record_send(db: AsyncSession, *, credential_id: str, issuer_did: str, delegate_registry: str,
                      credential_expires_at: Optional[_dt.datetime], outcome: Dict[str, Any],
                      now: Optional[_dt.datetime] = None) -> Optional["models.XRegRevokeOwed"]:
    """The route's bookkeeping of its own send, added to the session and committed by the caller (with the issuer-side
    record, in one transaction). A delivered send closes an open row; one that did not land opens the row, or re-opens
    a closed one with a fresh budget (the issuer asked again). Returns the row, or None when nothing is owed."""
    now = now or utcnow()
    row = await db.get(models.XRegRevokeOwed, credential_id)
    if outcome.get("delivered"):
        if row is not None and row.done_at is None:
            row.dead_at = None
            _apply(row, next_state(row.attempts, outcome, now, budget=max_attempts(),
                                   credential_expires_at=row.credential_expires_at))
        return row
    if row is None:
        row = models.XRegRevokeOwed(credential_id=credential_id, issuer_did=issuer_did,
                                    delegate_registry=delegate_registry, attempts=0, created_at=now,
                                    next_attempt_at=now, credential_expires_at=credential_expires_at)
        db.add(row)
    elif row.done_at is not None or row.dead_at is not None:
        row.attempts, row.done_at, row.dead_at = 0, None, None
    row.issuer_did, row.delegate_registry = issuer_did, delegate_registry
    row.credential_expires_at = credential_expires_at
    _apply(row, next_state(row.attempts, outcome, now, budget=max_attempts(),
                           credential_expires_at=credential_expires_at))
    return row


def state_of(row: Optional["models.XRegRevokeOwed"]) -> Optional[str]:
    if row is None:
        return None
    if row.done_at is not None:
        return "delivered"
    if row.dead_at is not None:
        exp = row.credential_expires_at
        return "expired" if (exp is not None and exp <= row.dead_at) else "given_up"
    return "retrying"


def _iso(t: Optional[_dt.datetime]) -> Optional[str]:
    return t.isoformat() if t is not None else None


def delivery_view(row: Optional["models.XRegRevokeOwed"], *, delivered_at_first_send: bool = False) -> Dict[str, Any]:
    """What an answer says about a revoke's delivery. No row: delivered at its first send, or (a revoke recorded before
    this registry kept them) never sent again."""
    if row is None:
        return {"state": "delivered" if delivered_at_first_send else "not_queued", "attempts": None,
                "next_attempt_at": None, "last_status": None, "last_error": None}
    st = state_of(row)
    return {"state": st, "attempts": int(row.attempts or 0),
            "next_attempt_at": _iso(row.next_attempt_at) if st == "retrying" else None,
            "last_status": row.last_status, "last_error": row.last_error,
            "delivered_at": _iso(row.done_at), "stopped_at": _iso(row.dead_at)}


async def owed_by_credential(db: AsyncSession, issuer_did: str) -> Dict[str, "models.XRegRevokeOwed"]:
    """The owed rows of one issuer, by credential id (its own list's view of each revoke's delivery)."""
    M = models.XRegRevokeOwed
    rows = (await db.execute(select(M).where(M.issuer_did == issuer_did))).scalars().all()
    return {r.credential_id: r for r in rows}


async def due_rows(db: AsyncSession, now: _dt.datetime, limit: int) -> List["models.XRegRevokeOwed"]:
    M = models.XRegRevokeOwed
    return list((await db.execute(
        select(M).where(M.done_at.is_(None), M.dead_at.is_(None), M.next_attempt_at <= now)
        .order_by(M.next_attempt_at).limit(limit)
    )).scalars().all())


async def open_count(db: AsyncSession) -> int:
    M = models.XRegRevokeOwed
    return int((await db.execute(
        select(func.count()).select_from(M).where(M.done_at.is_(None), M.dead_at.is_(None))
    )).scalar() or 0)


async def admin_summary(db: AsyncSession, limit: int = 50) -> Dict[str, Any]:
    """The admin's view (the delegation report): how many revokes are in each state, and the ones not delivered (still
    sent again, or parked), oldest first, at most `limit`."""
    M = models.XRegRevokeOwed
    state = case(
        (M.done_at.isnot(None), "delivered"),
        (and_(M.dead_at.isnot(None), M.credential_expires_at.isnot(None), M.credential_expires_at <= M.dead_at),
         "expired"),
        (M.dead_at.isnot(None), "given_up"),
        else_="retrying",
    )
    counts = {s: 0 for s in STATES}
    for st, n in (await db.execute(select(state, func.count()).group_by(state))).all():
        counts[str(st)] = int(n or 0)
    rows = (await db.execute(
        select(M).where(M.done_at.is_(None)).order_by(M.created_at).limit(limit))).scalars().all()
    undelivered = [{"credential_id": r.credential_id, "issuer_did": r.issuer_did,
                    "delegate_registry": r.delegate_registry, "queued_at": _iso(r.created_at), **delivery_view(r)}
                   for r in rows]
    return {"counts": counts, "undelivered": undelivered, "max_attempts": max_attempts()}
