"""§SPAWN-ANCHOR — a spawned sub-agent draws from its PARENT's wallet.

WHY (the §CENSUS-BLINDSPOT hygiene half, 2026-08-12): ``/agents/spawn`` today gives
every child its OWN TEG wallet (``create_teg_profile_for_agent``). Under sim load
(``--spawn-subagents --xreg-delegation``) that proliferates thousands of short-lived
cloud-op wallets whose momentary ES-projection vs TEG-truth skew is the "ghost churn"
the daily census oscillates on. The measurement fix already made the books TRUE; this
removes the CHURN by never minting the separate wallet in the first place.

WHAT: when ``SPAWN_WALLET_ANCHOR_MODE=on``, ``/agents/spawn`` creates the child with
NO own wallet and stamps its birth capability token caveats with ``anchored=true``.
When that child later spends (presenting the birth token on ``X-Capability-Token``),
the money-drawing path resolves the PURSE to the nearest wallet-holding ancestor — the
birth-token issuer chain — instead of the walletless child.

SAFETY — Δ-neutral by construction:
  * The child's own IRONKEY/L4 caveats (max_per_tx / budget / currency) STILL bind the
    spend: ``enforce_agent_spend`` runs on the ACTING child, so a draw is always ≤ the
    caveats, and the parent's live balance is a hard floor (the TEG rejects an overdraw).
  * The money leg (TEG debit + fee + the emitted ``TokensTransferred.from``) is entirely
    the purse's, so the EventStore projection decrements the account that actually lost
    the money — a transfer between two in-circulation accounts. No mint; no new wallet
    to drift.
  * Suspending the parent empties the birth token (``resolve_capability`` = caveats ∩
    issuer-CURRENT authority → ∅), so the child cannot resolve a purse and is denied.

FAIL-CLOSED: if anchoring cannot be resolved to a real wallet-holding ancestor (unknown
issuer, chain too deep, purse agent row missing, any error), the purse falls back to the
acting child (walletless) → the spend hits an empty account and fails as insufficient
funds. The resolver NEVER silently picks a wrong purse, and NEVER 500s a money path.

Default OFF = byte-inert (the IRONKEY flag pattern): spawns get wallets exactly as today
and no spend is ever redirected. Canary-gated on frame-c + its ops first.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# birth-token caveat key marking a walletless (anchored) child. Lives on the token
# the child presents, so the spend path reads it with zero extra lookups.
ANCHOR_CAVEAT = "anchored"
# guard against a pathological issuer cycle — a straight chain is only ever a few deep.
_MAX_CHAIN_DEPTH = 8


def spawn_wallet_anchor_mode() -> str:
    """``SPAWN_WALLET_ANCHOR_MODE`` — ``off`` (default, byte-inert) | ``on``."""
    return os.getenv("SPAWN_WALLET_ANCHOR_MODE", "off").strip().lower()


def anchor_enabled() -> bool:
    return spawn_wallet_anchor_mode() == "on"


def _cap_is_anchored(cap: Any) -> bool:
    """True iff the presented, already-resolved capability is an anchored birth token."""
    if not isinstance(cap, dict):
        return False
    caveats = cap.get("caveats") or {}
    return bool(isinstance(caveats, dict) and caveats.get(ANCHOR_CAVEAT))


async def _birth_token_of(db: AsyncSession, did: str) -> Optional[dict]:
    """The agent's own BIRTH token (the one where it is the HOLDER). Returns
    ``{"issuer": <did>, "anchored": <bool>}`` or ``None`` if it was not spawned
    (i.e. a root / normally-onboarded agent — which therefore HOLDS a wallet)."""
    row = (await db.execute(text(
        "SELECT issuer_agent_did, caveats FROM agent_capability_tokens "
        "WHERE holder_agent_did = :d AND status IN ('issued','active') "
        "AND (caveats ->> 'birth') = 'true' "
        "ORDER BY id ASC LIMIT 1"
    ), {"d": did})).first()
    if not row:
        return None
    cav = row.caveats or {}
    if not isinstance(cav, dict):
        cav = {}
    return {"issuer": row.issuer_agent_did, "anchored": bool(cav.get(ANCHOR_CAVEAT))}


async def _walk_to_wallet_holder(db: AsyncSession, start_did: Optional[str]) -> Optional[str]:
    """Walk the birth-token issuer chain upward to the first ancestor that HOLDS a
    wallet — i.e. one that was NOT itself spawned anchored. Returns its DID, or
    ``None`` if the chain breaks or runs deeper than ``_MAX_CHAIN_DEPTH`` (fail-closed).

    A depth-1 spawn (the common case: parent is a normal wallet-holding agent) resolves
    in one hop; a grandchild anchored under an anchored child walks to the grandparent.
    """
    cur = start_did
    for _ in range(_MAX_CHAIN_DEPTH):
        if not cur:
            return None
        bt = await _birth_token_of(db, cur)
        if bt is None or not bt["anchored"]:
            return cur            # holds a real wallet → this is the purse
        cur = bt["issuer"]        # itself anchored → keep climbing
    return None


async def resolve_spend_purse_agent(db: AsyncSession, acting_agent, request) -> Tuple[Any, str]:
    """Resolve the MONEY-LEG funding account for a spend.

    Returns ``(purse_agent, purse_did)``. The default — and the result whenever the
    feature is off, the request presents no anchored birth token, or resolution fails —
    is ``(acting_agent, acting_agent.did)``: the acting agent funds its own spend exactly
    as today. Only an anchored child presenting its anchored birth token is redirected to
    the wallet-holding ancestor. Fail-CLOSED and never raises.
    """
    try:
        if not anchor_enabled():
            return acting_agent, acting_agent.did
        cap = getattr(getattr(request, "state", None), "ironkey_capability", None)
        if not _cap_is_anchored(cap):
            return acting_agent, acting_agent.did
        purse_did = await _walk_to_wallet_holder(db, cap.get("issuer_did"))
        if not purse_did or purse_did == acting_agent.did:
            logger.warning("[SPAWN-ANCHOR] no wallet-holding ancestor for anchored acting=%s "
                           "(issuer=%s) — fail-closed to self", acting_agent.did, cap.get("issuer_did"))
            return acting_agent, acting_agent.did
        from agentvault_registry.crud.agent import get_agent_by_did
        purse = await get_agent_by_did(db, purse_did)
        if purse is None:
            logger.warning("[SPAWN-ANCHOR] purse agent row missing for %s — fail-closed to self", purse_did)
            return acting_agent, acting_agent.did
        logger.info("[SPAWN-ANCHOR] money-leg purse redirect: acting=%s → purse=%s", acting_agent.did, purse_did)
        # §SUBAGENT-LIABILITY P0 — a walletless HAND is spending on the PRINCIPAL's account; record
        # the attribution (the principal is the party of record, the hand is evidence). This is the
        # ONE seam that already knows a redirect happened, so every anchored-hand spend is attributed
        # with zero handler edits. record_hand_action is gated by LIABILITY_MODE + never raises +
        # never poisons this money-leg txn (savepoint-isolated evidence write).
        try:
            _action = getattr(getattr(request, "url", None), "path", None) or "spend"
            from agentvault_registry.services import liability as _liab
            await _liab.record_hand_action(db, principal_did=purse_did, hand_did=acting_agent.did,
                                           action=_action, action_ref=_action)
        except Exception:  # noqa: BLE001 — attribution is best-effort; NEVER break a money path
            pass
        return purse, purse_did
    except Exception as exc:  # noqa: BLE001 — a resolver error must NEVER 500 a money path
        logger.warning("[SPAWN-ANCHOR] purse resolve error acting=%s: %r — fail-closed to self",
                       getattr(acting_agent, "did", "?"), exc)
        return acting_agent, acting_agent.did
