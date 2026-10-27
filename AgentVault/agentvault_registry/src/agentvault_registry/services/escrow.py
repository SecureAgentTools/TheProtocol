"""THE SHARED ESCROW RAIL (P1, 2026-07-25) — extracted verbatim from ``guild_escrow`` so THE GUILD
and the CONTRACT SPINE move money through ONE mover instead of two.

Escrow = the TEG **treasury**, using the EXACT fee-free, Δ=0 primitives that eval_runner and the
reward waterfall already use — NO new money path (rule-13), NO TEG change, NO AGORA-escrow (I-X3)
interference:

  • DEPOSIT:  <source> ── TEG /admin/treasury/receive ──▶ treasury   (agent debited, fee-free)
  • PAYOUT :  treasury ── _fund_agent_from_treasury_internal ──▶ agent

Every leg is a zero-sum move between real balance accounts → the supply invariant is untouched
(Δ=0 by construction). Each domain's claim on the treasury is tracked authoritatively in its OWN
table (`guild_work_orders` Σ open bounties · `contracts` Σ escrowed-unreleased); the treasury is a
shared pool and each domain is net-neutral on it (deposits == payouts+refunds per ref).

The caller composes the FULL reference string and passes it as ``ref``:

    guildref:{order_id}:{leg}      (THE GUILD — unchanged on the wire)
    ctrref:{contract_id}:{leg}     (the contract spine)

Idempotency (two layers — the 2026-07-24 hardening, verbatim):
  1. STATE MACHINE (primary): every caller CLAIMS its status transition first (a guarded
     ``UPDATE … WHERE status=<prev>``, committed BEFORE the money leg) so a concurrent/retried call
     cannot re-pay. **Never add a money leg without a status claim in front of it.**
  2. TEG DURABLE RAIL (backstop): every leg carries ``Idempotency-Key: <ref>`` — the TEG
     treasury/reward-fund rails claim it in ``teg_idempotency_records`` in the same txn as the
     balance move, so a replayed leg returns the cached result and moves NOTHING. A replay with a
     DIFFERENT amount for the same key 409s (param-hash mismatch) instead of double-paying — which
     is what lets reapers safely RE-DRIVE crash-stranded money states exactly-once.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)


def _teg():
    """Lazy import of TEG plumbing (avoids import cycles with teg_integration at module load)."""
    from agentvault_registry.routers.teg_integration import (
        TEG_API_BASE_URL, TEG_API_V1_PREFIX, TEG_ADMIN_API_KEY, get_httpx_verify,
    )
    return TEG_API_BASE_URL, TEG_API_V1_PREFIX, TEG_ADMIN_API_KEY, get_httpx_verify


async def escrow_deposit(source_did: str, amount: Decimal, ref: str, *,
                         reason: str = "escrow_hold") -> dict:
    """<source> → treasury. Holds funds under ``ref`` (the FULL reference, caller-composed).
    Fee-free admin move (TEG admin/treasury/receive). Raises ``EscrowError`` on failure so the
    caller aborts (and, if it claimed a status first, reverts its claim)."""
    if amount <= 0:
        return {"status": "skipped_zero"}
    base, pfx, key, verify = _teg()
    async with httpx.AsyncClient(verify=verify()) as client:
        resp = await client.post(
            f"{base}{pfx}/admin/treasury/receive",
            json={"source_agent_id": source_did, "amount": str(amount),
                  "reason": reason, "reference_id": ref},
            headers={"Authorization": f"Bearer {key}",
                     "Idempotency-Key": ref}, timeout=20.0,
        )
    if resp.status_code != 200:
        # §LEDGERGATE (V0598): the TEG's ledger gate refused the deposit (nothing moved): its sentence, as it came
        from agentvault_registry.services.ledger_unavailable import ledger_refusal
        _refusal = ledger_refusal(resp)
        if _refusal is not None:
            raise EscrowError(503, _refusal.detail, headers=_refusal.headers)
        detail = _detail(resp)
        raise EscrowError(resp.status_code, f"escrow deposit failed: {detail}")
    return resp.json()


async def escrow_payout(db, target_did: str, amount: Decimal, ref: str, *,
                        reason: str) -> dict:
    """Treasury → agent (settle / refund / split leg). Reuses the blessed reward-funding waterfall
    helper (fee-free, Δ=0). ``reason`` must be one of the waterfall-known families
    (guild_settle / guild_refund / contract_settle / contract_refund)."""
    if amount <= 0:
        return {"status": "skipped_zero"}
    from agentvault_registry.routers.teg_integration import (
        _fund_agent_from_treasury_internal, TreasuryFundAgentRequest,
    )
    req = TreasuryFundAgentRequest(
        target_agent_did=target_did, amount=str(amount),
        reason=reason, reference_id=ref,
    )
    return await _fund_agent_from_treasury_internal(
        db, req, actor_label=reason.split("_", 1)[0], idempotency_key=ref)


def _detail(resp) -> str:
    try:
        return resp.json().get("detail", resp.text[:200])
    except Exception:  # noqa: BLE001
        return resp.text[:200]


class EscrowError(Exception):
    def __init__(self, status_code: int, message: str, headers=None):
        self.status_code = status_code
        self.message = message
        self.headers = headers   # §LEDGERGATE (V0598): the TEG's Retry-After when its ledger refused
        super().__init__(message)
