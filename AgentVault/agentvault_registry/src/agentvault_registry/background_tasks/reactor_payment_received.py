"""
Reactor: LedgerBalanceChanged → `payment.received` (owner-scoped webhook)
=========================================================================
§TWOAGENT G3 (2026-09-23). Two findings of the two-agent trial:
  * 6  — the webhook vocabulary had nothing for money: a payment received, an A2A settlement or a transfer could
         never be pushed, so a runtime that sells a service had to poll its balance to learn it was paid;
  * 24 — an FX-pool arrival leaves exactly ONE event on the receiver's own store (a `LedgerBalanceChanged`, the
         fx reserve −x and the agent +x); the business event naming the sender lives on the SENDING frame's store.

Source: this frame's own ledger of record. Every credit to a wallet here is exactly one `LedgerBalanceChanged`
written by the TEG balance outbox, whatever rail moved it:
    transfer          a local transfer, an A2A settlement to a local seller, an FX-pool arrival (the reserve is
                      the other leg); the sender is the other agent entry, or unknown for the pool
    cross_teg_credit  a same-currency arrival from another frame's TEG; the sender is recorded on the sending
                      frame's ledger, so this frame says it does not know it rather than guessing
Trading, escrow, staking and reward kinds are not payments between parties and do not fire.

Exactly once: the store replays recent events on reconnect, the polling backstop rescans five minutes, and a restart
empties the in-process dedup ring; a Redis claim on (TEG, transaction, agent) makes each credit announce once (24 h).
If Redis cannot answer, the reactor does NOT dispatch (a duplicate payment notice is worse than a late poll).

Owner-scoped (the #34 rule): the receiving agent's LOCAL owner only, through dispatch_webhook_for_agents. A bridged
peer copy is skipped outright: a credit to an agent of this frame is always recorded on this frame's store, and an
operator's credits reach the operator's own registry, which resolves its own owners. Nothing here emits an event
(CQRS: a reactor's side effects are commands, never further events).

Volume: a cached (30 s) probe asks whether any active webhook subscribes to `payment.received` before any per-event
work, the same guard the transfer push reactor uses on sim-heavy frames.
"""
from __future__ import annotations

import logging
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_for_agents, is_notification_stale

logger = logging.getLogger(__name__)

EVENT = "payment.received"
PAYMENT_KINDS = {"transfer", "cross_teg_credit"}
FX_RESERVE = "did:theprotocol:teg_system_fx_reserve"
_CLAIM_TTL_SEC = int(os.getenv("PAYMENT_RECEIVED_CLAIM_TTL_SEC", "86400"))
_SUB_CACHE: Dict[str, Any] = {}


def _is_system(did: str) -> bool:
    d = (did or "").lower()
    return d.startswith("teg:system:") or "teg_system_" in d


def _dec(v: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def payments_in(event_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The credits one ledger change carries, as `payment.received` payloads (pure; no I/O).

    One per agent entry with a positive liquid delta, in a payment kind, that is not a platform account. The sender
    is named only when the ledger names it: the single other agent entry that lost money (the fee collector and the
    pool are platform legs, never the payer)."""
    kind = event_data.get("kind")
    if kind not in PAYMENT_KINDS:
        return []
    entries = [e for e in (event_data.get("entries") or []) if isinstance(e, dict) and e.get("agent_did")]
    debited = [e["agent_did"] for e in entries if (_dec(e.get("delta_liquid")) or 0) < 0]
    senders = [d for d in debited if not _is_system(d)]
    out = []
    for e in entries:
        did, amt = e["agent_did"], _dec(e.get("delta_liquid"))
        if amt is None or amt <= 0 or _is_system(did):
            continue
        if kind == "cross_teg_credit":
            via, sender = "cross_frame", None
        elif FX_RESERVE in debited:
            via, sender = "fx_pool", None
        else:
            via, sender = "transfer", (senders[0] if len(senders) == 1 and senders[0] != did else None)
        out.append({
            "agent_did": did,
            "amount": format(amt.normalize(), "f"),
            "currency": (os.getenv("FRAME_CURRENCY", "") or "").strip().upper() or None,
            "from_did": sender,
            "sender_known": sender is not None,
            "via": via,
            "ledger_kind": kind,
            "ledger_txid": event_data.get("txid"),
            "teg": event_data.get("frame"),
            "note": (None if sender else
                     "the sender is recorded on the sending frame's ledger" if via == "cross_frame" else
                     "arrived through the FX pool; the sender is recorded on the sending frame's ledger"
                     if via == "fx_pool" else "the ledger names no single paying agent"),
        })
    return out


async def _any_subscribers() -> bool:
    now = time.monotonic()
    if "v" in _SUB_CACHE and now - _SUB_CACHE.get("t", 0) < 30:
        return _SUB_CACHE["v"]
    val = False
    try:
        from sqlalchemy import text
        from agentvault_registry.database import get_db_context
        async with get_db_context() as db:
            val = (await db.execute(text(
                "SELECT 1 FROM developer_webhooks WHERE is_active AND events @> CAST(:e AS jsonb) LIMIT 1"),
                {"e": f'["{EVENT}"]'})).first() is not None
    except Exception as exc:  # noqa: BLE001 — a probe failure reads as "someone may listen"; the claim still guards
        logger.debug("[PaymentReceived] subscriber probe failed: %s", exc)
        val = True
    _SUB_CACHE.update(v=val, t=now)
    return val


async def _claim(key: str) -> Optional[bool]:
    """True = first to announce this credit; False = already announced; None = cannot tell (do not dispatch)."""
    try:
        from .leader import get_redis
        r = await get_redis()
        if r is None:
            return None
        return bool(await r.set(key, "1", nx=True, ex=_CLAIM_TTL_SEC))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PaymentReceived] claim store unavailable (%s); not announcing %s", exc, key)
        return None


async def _release(key: str) -> None:
    try:
        from .leader import get_redis
        r = await get_redis()
        if r is not None:
            await r.delete(key)
    except Exception:  # noqa: BLE001
        pass


class PaymentReceivedReactor(EventStoreReactor):
    event_type = "LedgerBalanceChanged"
    leader_key = "reactor_payment_received"
    name = "PaymentReceived"

    async def handle_event(self, event_data: dict) -> None:
        if event_data.get("_foreign_frame_id"):
            return  # a peer's copy: a credit to one of OUR agents is recorded on our own store
        credits = payments_in(event_data)
        if not credits or not await _any_subscribers():
            return
        stale, _age = is_notification_stale(event_data)
        if stale:
            return
        for p in credits:
            key = f"payrcv:{p['teg']}:{p['ledger_txid']}:{p['agent_did']}"
            claimed = await _claim(key)
            if not claimed:
                continue
            try:
                await dispatch_webhook_for_agents(EVENT, p, [p["agent_did"]], source_label=self.name)
            except Exception:  # noqa: BLE001 — hand the claim back so the base's retry can announce it
                await _release(key)
                raise


_instance: Optional[PaymentReceivedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = PaymentReceivedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
