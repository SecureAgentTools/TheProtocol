"""THE GUILD — bounty escrow. **Compatibility shim since P1 (2026-07-25).**

The mover itself lives in ``services/escrow.py`` (the shared rail — THE GUILD and the contract
spine move money through ONE mover). This module keeps the ORIGINAL guild-facing signatures and
composes the guild reference strings EXACTLY as before (``guildref:{order_id}:{leg}``, deposit
default leg ``hold``), so ``routers/guild.py`` and ``background_tasks/guild_order_reaper.py`` are
byte-identical callers and every leg keeps its historic wire key — idempotency continuity for
in-flight orders included.

Full doctrine (claim-first state machine + TEG durable rail) is documented in ``services/escrow.py``
and in this module's original docstring, preserved in git history. Nothing about guild money
semantics changed in P1.
"""
from __future__ import annotations

from decimal import Decimal

from agentvault_registry.services import escrow as _rail

# Callers catch GuildEscrowError; the rail raises EscrowError — one class, two names.
GuildEscrowError = _rail.EscrowError
EscrowError = _rail.EscrowError


async def escrow_deposit(source_did: str, amount: Decimal, order_id: str, leg: str = "hold") -> dict:
    """<source> → treasury under ``guildref:{order_id}:{leg}`` (original wire format, unchanged)."""
    return await _rail.escrow_deposit(
        source_did, amount, f"guildref:{order_id}:{leg}", reason="guild_escrow")


async def escrow_payout(db, target_did: str, amount: Decimal, order_id: str, leg: str) -> dict:
    """Treasury → agent under ``guildref:{order_id}:{leg}``. ``leg`` ∈ {settle, refund,
    split_worker, split_poster, settle_roy*, xf_stage*, …} — reason derives exactly as before."""
    reason = "guild_settle" if leg.startswith("settle") or leg.startswith("split") else "guild_refund"
    return await _rail.escrow_payout(
        db, target_did, amount, f"guildref:{order_id}:{leg}", reason=reason)
