"""
A2A Payment Token Expiry + Settlement Recovery Worker — f045

Runs every 60 seconds:
  1. Expires AUTHORIZED tokens past their TTL
  2. Recovers stale SETTLING tokens (background task died mid-settlement), asking first whether the transfer completed
Uses Redis leader election (same pattern as other background tasks).
"""
import asyncio
import logging
import os
import types
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal as async_session_factory
from ..models import A2APaymentAuthorization, A2APaymentStatus

logger = logging.getLogger(__name__)

_running = False

# Tokens still SETTLING this long after they were verified (or created) are recovered: settled when their transfer
# completed, failed when it did not
STALE_SETTLEMENT_TIMEOUT_SECONDS = 90


async def _settlement_callers(db, payer_did: str) -> Tuple[str, ...]:
    """D6-777: whose records the settlement's transfer kept. The transfer endpoint keeps a key as its caller's, and the
    settlement calls it as the payer, or, for an anchored hand, as the wallet the hand spends from
    (routers/a2a_payment._purse_settle_bearer): both are the payer's side. A chain that cannot be read gives the payer
    alone."""
    from ..services.idempotency.cache import agent_caller
    callers = [agent_caller(payer_did)]
    try:
        from ..services import spawn_anchor as _sa
        bt = await _sa._birth_token_of(db, payer_did)
        if bt and bt.get("anchored"):
            purse = await _sa._walk_to_wallet_holder(db, bt.get("issuer"))
            if purse and purse != payer_did:
                callers.append(agent_caller(purse))
    except Exception:  # noqa: BLE001 — the payer's own records still answer
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return tuple(callers)


async def _durable_record(key: str, scope: str, callers: Tuple[str, ...],
                          bodies: Tuple[dict, ...]) -> Tuple[str, Optional[dict]]:
    """The durable copy's record of the settlement key on `scope` (§REPATLANE-8), read when Redis keeps nothing: the
    same states as payout_outcome.stored_answer. The callers' records first (D6-777), then a row the copy kept before
    records were the caller's: the settlement key carries a digest only the token's parties can derive, so such a row is
    this settlement's when it is a record of the settlement's own request (`bodies`): the payer can derive the key, and
    a record of another body under it is not the settlement (record_is_of)."""
    from ..services.idempotency import durable
    from ..services.idempotency.cache import _durable_key, record_is_of
    if not durable.enabled():
        return "none", None
    try:
        rec = None
        for caller in callers:
            got = await durable.get(scope, _durable_key(key, caller))
            if got and record_is_of(got, caller, bodies):
                rec = got
                break
        if not rec:
            got = await durable.get(scope, key)
            if got and record_is_of(got, None, bodies):
                rec = got
        if rec:
            kept = rec.get("state")
            if kept == "answer":
                return "stored", rec.get("payload") or {}
            if kept == "error":
                return "held", rec.get("payload") or {}
            return "claimed", None
    except Exception:  # noqa: BLE001 — a read that could not be made is not an answer
        return "unknown", None
    return "none", None


async def _settlement_outcome(token_id: str, token_hash: str, scope: str,
                              callers: Tuple[str, ...], *, bodies: Tuple[dict, ...]) -> Tuple[str, Optional[str]]:
    """§DOCSFIX D6-437 / CB-442: what became of a stale settling token's transfer, asked of the registry's idempotency
    store under the settlement's own key (routers/a2a_payment._settlement_key), on the one endpoint the settlement used
    (`scope`, routers/a2a_payment._settlement_scope); read, never claimed. A record under the same key on the other
    endpoint is not this settlement's, nor one kept for a caller who is not the payer's side (`callers`,
    _settlement_callers; D6-777), nor one of another request than the settlement's own (`bodies`,
    routers/a2a_payment._settlement_record_bodies): the payer holds the plain token, so it can derive the key and keep
    a transfer of its own under it, and such a record is read as no record at all.

      ("paid", tx)      the transfer endpoint kept a success: the payment was made, tx names it
      ("failed", None)  it kept a failure, or holds nothing under the key: nothing ran, or the endpoint gave the key
                        back because nothing moved (a token settled without a key reads the same); a record of another
                        request under the key reads the same (the settlement's own transfer under the key, as the same
                        caller, is refused as a different request, so it moved nothing)
      ("wait", None)    a transfer under the key is still claimed (running, or it ended without an answer, so nobody
                        can say), or the store could not be read: the token stays settling
    """
    from ..routers.a2a_payment import _settlement_key
    from ..services.payout_outcome import PAID, classify_stored, stored_answer
    key = _settlement_key(token_id, token_hash)
    if not (os.environ.get("REDIS_URL") or "").strip():
        return "failed", None   # no store on this registry: the transfer endpoints keep nothing under any key
    # §DOCSFIX review: a Redis that cannot be reached right now (leader.get_redis answers None during an outage, too)
    # is a store that could not be read, never a store that holds nothing: the durable copy answers when it can, and
    # the token waits for the next sweep when it cannot
    # the settlement key carries a digest only the token's parties can derive: a record kept before records were the
    # caller's (D6-777) is read as it was written (unscoped_reads)
    state, rec = await stored_answer(key, scopes=(scope,), callers=callers, unscoped_reads=True, bodies=bodies)
    if state in ("none", "unknown"):
        durable_state, durable_rec = await _durable_record(key, scope, callers, bodies)
        if durable_state != "none" or state == "none":
            state, rec = durable_state, durable_rec
    if state == "stored":
        out = classify_stored(rec)
        return ("paid", out.tx or None) if out.kind == PAID else ("failed", None)
    if state in ("held", "none"):
        return "failed", None
    return "wait", None


async def _expire_stale_tokens():
    """Find and expire tokens past their TTL + recover stale settlements."""
    try:
        async with async_session_factory() as db:
            now = datetime.now(timezone.utc)

            # 1. Expire AUTHORIZED tokens past TTL
            result = await db.execute(
                update(A2APaymentAuthorization)
                .where(A2APaymentAuthorization.status == A2APaymentStatus.AUTHORIZED.value)
                .where(A2APaymentAuthorization.expires_at < now)
                .values(status=A2APaymentStatus.EXPIRED.value)
            )
            expired = result.rowcount

            # 1b. Expire CONSUMED-but-never-settled tokens past TTL. A CONSUMED token
            # (service verified + did the work) whose TTL lapsed without settlement is an
            # expired authorization — the payment window closed. NO funds were ever
            # reserved (authorize only CHECKS balance; settlement is a fresh transfer that
            # never ran), so this is Δ-NEUTRAL status hygiene. Without it these linger
            # forever (forensic finding a2a_consumed_unsettled). Mirrors AUTHORIZED→EXPIRED;
            # consumed_at stays set so "consumed-then-expired" remains auditable.
            result_consumed = await db.execute(
                update(A2APaymentAuthorization)
                .where(A2APaymentAuthorization.status == A2APaymentStatus.CONSUMED.value)
                .where(A2APaymentAuthorization.expires_at < now)
                .values(status=A2APaymentStatus.EXPIRED.value)
            )
            expired_consumed = result_consumed.rowcount
            await db.commit()   # the store reads below hold no transaction open

            # 2. Recover stale SETTLING tokens (background task died)
            # D1 fix (2026-06-12): `consumed_at < cutoff` is NULL-blind — rows that
            # reached SETTLING without a consumed_at stamp never matched and sat stuck
            # forever (63 such rows found on registry-a, Apr–May 2026). Fall back to
            # created_at for the NULL case. Status-only write; no balances touched.
            # §DOCSFIX D6-437 / CB-442: this clock starts at verification, not at settlement, so a stale token's
            # transfer may have completed (or still be running): each one's outcome is asked of the idempotency store
            # under its settlement key before the token is called failed (_settlement_outcome). A completed transfer
            # settles the token; a running or unanswerable one leaves it settling.
            # §DOCSFIX D6-778: a token this sweep settles owes what the background settle's success owes (the count,
            # the payer's payment.settled notice, the contract's payment_transaction_id): a2a_payment._after_settled.
            stale_cutoff = now - timedelta(seconds=STALE_SETTLEMENT_TIMEOUT_SECONDS)
            stale = (await db.execute(
                select(A2APaymentAuthorization.id, A2APaymentAuthorization.token_hash,
                       A2APaymentAuthorization.target_agent_did, A2APaymentAuthorization.caller_did,
                       A2APaymentAuthorization.amount, A2APaymentAuthorization.task_id,
                       A2APaymentAuthorization.contract_id)
                .where(A2APaymentAuthorization.status == A2APaymentStatus.SETTLING.value)
                .where(or_(
                    A2APaymentAuthorization.consumed_at < stale_cutoff,
                    and_(
                        A2APaymentAuthorization.consumed_at.is_(None),
                        A2APaymentAuthorization.created_at < stale_cutoff,
                    ),
                ))
            )).all()
            await db.commit()
            from ..routers import a2a_payment as _a2a
            stale_recovered = stale_settled = stale_waiting = 0
            for token_id, token_hash, target_did, caller_did, amount, task_id, contract_id in stale:
                # the endpoint the settlement used: the payee's locality, decided as the settlement decides it
                local = await _a2a._is_local_agent(db, target_did)
                scope = _a2a._settlement_scope(local)
                callers = await _settlement_callers(db, caller_did)
                await db.commit()
                # the request the settlement sent under its key, rebuilt from the token's row: only its record counts
                bodies = tuple(_a2a._settlement_record_bodies(target_did, amount,
                                                              _a2a._settlement_message(token_id, task_id), local))
                outcome, tx_id = await _settlement_outcome(token_id, token_hash, scope, callers, bodies=bodies)
                if outcome == "wait":
                    stale_waiting += 1
                    continue
                values = ({"status": A2APaymentStatus.SETTLED.value, "settlement_tx_id": tx_id, "settled_at": now}
                          if outcome == "paid" else {"status": A2APaymentStatus.FAILED.value})
                result2 = await db.execute(
                    update(A2APaymentAuthorization)
                    .where(A2APaymentAuthorization.id == token_id)
                    .where(A2APaymentAuthorization.status == A2APaymentStatus.SETTLING.value)
                    .values(**values)
                )
                await db.commit()
                if result2.rowcount and outcome == "paid":
                    stale_settled += 1
                    # the row now reads SETTLED, written here: only the writer of that row runs the follow-ups (a
                    # background settle that finishes later finds the token settled and skips them)
                    settled = types.SimpleNamespace(id=token_id, caller_did=caller_did, target_agent_did=target_did,
                                                    amount=amount, status=A2APaymentStatus.SETTLED.value,
                                                    task_id=task_id)
                    await _a2a._after_settled(db, settled, tx_id, contract_id)
                elif result2.rowcount:
                    stale_recovered += 1

            if expired or expired_consumed or stale_recovered or stale_settled or stale_waiting:
                logger.info(f"[A2APay] Sweep: {expired} authorized-expired, {expired_consumed} consumed-expired, "
                            f"{stale_recovered} stale settlements failed, {stale_settled} settled by their kept "
                            f"transfer, {stale_waiting} still waiting on their transfer")
            else:
                logger.debug("[A2APay] Expiry sweep completed (no changes)")
    except Exception as e:
        # §VITALS: re-raised so the cycle stamps `error`. The loop still catches and
        # continues, so behaviour is unchanged — a failed sweep just stops looking
        # identical to a sweep with nothing to do.
        logger.error(f"[A2APay] Expiry worker error: {e}")
        raise


async def a2a_payment_expiry_loop():
    """Background loop — runs every 60 seconds with leader election."""
    from .leader import try_acquire_leadership
    global _running
    _running = True
    logger.info("[A2APay] Payment expiry worker started (60s cycle)")
    from . import vitals as _vitals
    await _vitals.register("a2a_payment_expiry", module=__name__,
                           pattern="hand-rolled", interval_sec=60, enabled=True)
    while _running:
        try:
            if await try_acquire_leadership("a2a_payment_expiry"):
                async with _vitals.cycle("a2a_payment_expiry"):
                    await _expire_stale_tokens()
        except Exception as e:
            logger.error(f"[A2APay] Expiry cycle error: {e}")
        await asyncio.sleep(60)


def stop_a2a_payment_expiry():
    global _running
    _running = False
