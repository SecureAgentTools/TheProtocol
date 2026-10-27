"""Registry-side reward-funding rail (§REWARDEVENTS 2026-08-11).

THE one way registry code pays a reward through the TEG waterfall
(POST /admin/reward-fund). Owns the three responsibilities every caller
used to skip or duplicate (§FUNNELSMOKE-AUDIT):

  1. Pay via TEG with a caller-supplied deterministic Idempotency-Key —
     the TEG endpoint dedups, so a retried logical operation pays exactly
     once.
  2. Emit ONE TokensTransferred per returned leg. The registry is the
     business-event emitter (f037 partition: TEG is policy-blocked for
     this type and its own emit call has been silently dropped since
     Phase 2). The deterministic event key tokens_transferred:{leg_tx_id}
     makes re-emits exactly-once at the EventStore
     (UNIQUE(idempotency_key)).
  3. Sync the registry's cached agents.liquid_balance from the TEG
     response (new_target_balance) on completed AND exhausted, so partial
     grants stop leaving the cache lying. The sync MUTATES the caller's
     session but never commits — every caller keeps its own commit
     discipline.

Waterfall source order is a per-reason TEG policy
(system_config.reward_funding_waterfall). This module is deliberately
source-agnostic: legs are emitted exactly as TEG reports them, whatever
the policy routed (Commander 2026-08-11: reasons may route treasury-only
or fee-collector-only in the future).

Exhausted (HTTP 400 + status=exhausted) is DOCUMENTED TEG behavior: the
partial legs are already committed. This helper reports it honestly
(status='exhausted' with funded_amount/shortfall) instead of raising —
the caller decides what a partial means for its flow. Hard failures
(connection errors, non-exhausted 4xx/5xx) raise TEGClientError
unchanged.
"""
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..event_emitter import get_event_emitter
from ..teg_client import TEGClientError, get_teg_client

logger = logging.getLogger(__name__)


async def _emit_leg_events(target_agent_did: str, reason: str,
                           legs: List[Dict[str, Any]]) -> int:
    """Emit TokensTransferred per leg; return how many emits succeeded.

    The money already moved when this runs — an emission failure must
    never unwind the payment. Failures are logged loudly; the
    deterministic key means a later replay of the same leg is a no-op.
    """
    emitter = get_event_emitter()
    if emitter is None:
        logger.error(
            "[RewardFunding] no event emitter — %d leg event(s) NOT emitted "
            "for %s (%s)", len(legs), target_agent_did, reason)
        return 0
    emitted = 0
    for leg in legs:
        tx_id = leg.get("transaction_id")
        if not tx_id:
            logger.error("[RewardFunding] leg without transaction_id for %s: %s",
                         target_agent_did, leg)
            continue
        try:
            ok = await emitter.emit_tokens_transferred(
                from_agent=leg.get("source_did") or leg.get("source", "unknown"),
                to_agent=target_agent_did,
                amount=str(leg.get("amount", "0")),
                transaction_id=tx_id,
                memo=f"reward_fund:{reason}:via_{leg.get('source', '?')}",
            )
            if ok:
                emitted += 1
            else:
                logger.error(
                    "[RewardFunding] TokensTransferred emit returned False "
                    "for leg %s (%s → %s)", tx_id, leg.get("source_did"),
                    target_agent_did)
        except Exception as e:  # noqa: BLE001 — payment already committed
            logger.error("[RewardFunding] TokensTransferred emit failed for "
                         "leg %s: %s", tx_id, e)
    return emitted


async def _sync_cached_balance(db: Optional[AsyncSession], target_agent_did: str,
                               new_target_balance: Optional[str]) -> bool:
    """Set the registry's cached liquid_balance to TEG truth (no commit)."""
    if db is None or new_target_balance is None:
        return False
    try:
        from ..models import Agent
        row = await db.execute(select(Agent).where(Agent.did == target_agent_did))
        agent = row.scalar_one_or_none()
        if agent is None:
            return False  # system accounts / non-local targets have no row
        agent.liquid_balance = Decimal(str(new_target_balance))
        return True
    except Exception as e:  # noqa: BLE001 — cache sync must not fail the payment
        logger.error("[RewardFunding] balance cache sync failed for %s: %s",
                     target_agent_did, e)
        return False


async def fund_reward_via_waterfall(
    db: Optional[AsyncSession],
    *,
    target_agent_did: str,
    amount: Union[Decimal, str, float],
    reason: str,
    reference_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Pay a reward via the TEG waterfall; emit per-leg events; sync cache.

    Returns a normalized dict:
      status               'completed' | 'exhausted'
      funded_amount        str — what actually moved
      shortfall            str — '0' when completed
      legs                 the TEG legs as returned (source-agnostic)
      first_transaction_id first leg's tx id (or top-level transaction_id)
      new_target_balance   TEG-truth balance after funding (str or None)
      events_emitted       int — TokensTransferred successfully emitted
      raw                  the TEG response body

    Raises TEGClientError on hard failures (connection, non-exhausted
    4xx/5xx) — in that case NO money moved and nothing is emitted.
    """
    client = get_teg_client()
    try:
        data = await client.fund_reward(
            agent_did=target_agent_did,
            amount=amount,
            reason=reason,
            reference_id=reference_id,
            idempotency_key=idempotency_key,
        )
        status = "completed"
    except TEGClientError as e:
        body = getattr(e, "teg_response", None)
        if not (isinstance(body, dict) and body.get("status") == "exhausted"):
            raise
        data, status = body, "exhausted"
        logger.error(
            "[RewardFunding] EXHAUSTED for %s (%s): funded %s of %s, "
            "shortfall %s — partial legs are COMMITTED, emitting + syncing",
            target_agent_did, reason, body.get("funded_amount"),
            body.get("total_amount"), body.get("shortfall"))

    legs = data.get("legs") or []
    emitted = await _emit_leg_events(target_agent_did, reason, legs)
    synced = await _sync_cached_balance(db, target_agent_did,
                                        data.get("new_target_balance"))

    first_tx = ((legs[0].get("transaction_id") if legs else None)
                or data.get("transaction_id"))
    result = {
        "status": status,
        "funded_amount": str(data.get("funded_amount",
                                      data.get("amount", amount))),
        "shortfall": str(data.get("shortfall", "0")),
        "legs": legs,
        "first_transaction_id": first_tx,
        "new_target_balance": data.get("new_target_balance"),
        "events_emitted": emitted,
        "balance_synced": synced,
        "raw": data,
    }
    logger.info(
        "[RewardFunding] %s %s → %s (%s): legs=%d events=%d synced=%s%s",
        result["funded_amount"],
        "funded" if status == "completed" else "PARTIALLY funded",
        target_agent_did, reason, len(legs), emitted, synced,
        f" shortfall={result['shortfall']}" if status != "completed" else "")
    return result
