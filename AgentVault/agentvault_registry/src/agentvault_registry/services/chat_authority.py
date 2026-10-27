"""§OURSTATE-5b — the Bouncer's second stage: authority as a verifiable fact.

Away mode v1 could hold the line but never spend: it disclosed, quoted, staged,
and woke you with a digest. Stage 2 is the sentence *"authorized up to 500 BVT"*
becoming something a stranger can CHECK rather than something a chat app claims.

The whole design is one rule:

    **OurChat DISPLAYS authority. IRONKEY DEFINES it.**

So there is no authority table here, no ceiling column, no "chat spend limit"
setting. An away designation names a capability token by its **id** — a number,
never the bearer secret — and every read re-derives the truth from
`agent_capability_tokens` through `agent_delegation.issuer_effective()`, the
same intersection-with-the-issuer's-current-authority that makes an IRONKEY L4
token confused-deputy-safe. Revoke the grant and the next read is empty,
because there was never a copy to go stale.

Two facts must BOTH hold before this module will say an agent may act:

  1. **A live capability**: unexpired, not revoked, budget remaining, held by
     that agent, carrying an explicit spend permission after the intersection.
  2. **A liability mandate naming a human**: the person underwriting it. A
     ceiling with nobody behind it is a number, not authority — the Cockpit
     Card's whole argument, applied to a stand-in that answers while you sleep.

Anything less resolves to *not authorized*, WITH the reason named, and the
thread keeps the v1 sentence: it cannot accept work, sign anything, or move
money. A stand-in that overstates itself is worse than one that stays quiet.
"""
from __future__ import annotations

import decimal
import logging
from typing import Any, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The permissions that mean "may move value". A capability whose caveats carry
# none of these is a read/act grant, not a spending one, and the away line says
# so rather than implying a wallet.
SPEND_PERMISSIONS = ("wallet.spend", "a2a.pay", "contract.accept")


def _dec(v: Any) -> Optional[decimal.Decimal]:
    if v is None:
        return None
    try:
        return decimal.Decimal(str(v))
    except (decimal.InvalidOperation, ValueError):
        return None


def money_str(d: Optional[decimal.Decimal]) -> Optional[str]:
    """`500`, not `500.000000000000000000`. Budgets are numeric(36,18)."""
    if d is None:
        return None
    return format(d.normalize(), 'f')


async def _mandate_for(db: AsyncSession, developer_id: int, agent_did: str) -> Optional[dict]:
    """The live liability mandate naming this human for this agent, if any.

    Read, never cached: a mandate that was revoked a second ago must stop
    counting on the next request, which is the same property the capability has
    and for the same reason.
    """
    row = (await db.execute(sa_text("""
        SELECT id, tier, status, issued_at, expires_at
        FROM liability_mandates
        WHERE developer_id = :d AND agent_did = :a
          AND status = 'signed' AND revoked_at IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        ORDER BY issued_at DESC
        LIMIT 1
    """), {"d": int(developer_id), "a": agent_did})).first()
    if row is None:
        return None
    return {"mandate_id": row[0], "tier": row[1],
            "issued_at": row[3].isoformat() if row[3] else None,
            "expires_at": row[4].isoformat() if row[4] else None}


async def authority_snapshot(db: AsyncSession, *, developer_id: int, agent_did: str,
                             token_id: Optional[int]) -> dict:
    """What this stand-in may actually do, right now.

    Returns a shape that is safe to render to the COUNTERPARTY in a thread:
    the ceiling, the currency, the expiry, the issuing agent and the mandate
    reference. Never the token, never the hash, never the owner's balances —
    a counterparty is entitled to know the limit they are dealing inside, not
    to inventory the other side's wallet.
    """
    out: dict = {"authorized": False, "agent_did": agent_did, "reason": None,
                 "ceiling": None, "currency": None, "expires_at": None,
                 "permissions": [], "issuer_did": None, "mandate": None}

    if not token_id:
        out["reason"] = "no capability is named in the away designation"
        return out

    row = (await db.execute(sa_text("""
        SELECT id, issuer_agent_did, holder_agent_did, status, caveats,
               budget_total, budget_spent, currency, expires_at,
               (expires_at <= now()) AS is_expired
        FROM agent_capability_tokens WHERE id = :i
    """), {"i": int(token_id)})).first()
    if row is None:
        out["reason"] = "the named capability does not exist"
        return out
    if row[2] and str(row[2]) != agent_did:
        # Naming someone else's grant must never lend you its ceiling.
        out["reason"] = "the named capability belongs to a different agent"
        return out
    if str(row[3]) not in ("issued", "active"):
        out["reason"] = f"the capability is {row[3]}"
        return out
    if row[9]:
        out["reason"] = "the capability has expired"
        return out

    total, spent = _dec(row[5]), _dec(row[6]) or decimal.Decimal(0)
    remaining = (total - spent) if total is not None else None
    if remaining is not None and remaining <= 0:
        out["reason"] = "the capability's budget is spent"
        return out

    # The confused-deputy killer: what the caveats ASK for, intersected with
    # what the issuer may CURRENTLY do. Clamping the issuer empties every token
    # it ever issued, and this line is why.
    from ..agent_delegation import issuer_effective
    caveats = row[4] or {}
    asked = {p for p in (caveats.get("permissions") or [])}
    effective = sorted(asked & await issuer_effective(db, str(row[1])))

    out.update({"issuer_did": row[1], "permissions": effective,
                "ceiling": money_str(remaining), "currency": row[7],
                "expires_at": row[8].isoformat() if row[8] else None})

    if not any(p in effective for p in SPEND_PERMISSIONS):
        out["reason"] = ("the capability carries no spending permission the issuer "
                         "can still delegate")
        return out
    if remaining is None or not row[7]:
        # A ceiling without a currency is the §FOREIGNACT defect wearing a
        # capability's clothes: three currencies live here, and "up to 500" is
        # not a limit until it says 500 of what.
        out["reason"] = "the capability sets no bounded amount in a named currency"
        return out

    mandate = await _mandate_for(db, developer_id, agent_did)
    out["mandate"] = mandate
    if mandate is None:
        out["reason"] = "no liability mandate names a human behind this agent"
        return out

    out["authorized"] = True
    return out


def authority_sentence(snap: dict, agent_name: str, owner_name: str) -> str:
    """One line, in the register a stranger reads — and it never overstates.

    Unauthorized is not silence: the stand-in says plainly that it cannot
    commit anything, because the alternative is a counterparty who assumes it
    can.
    """
    if not snap.get("authorized"):
        return (f"{agent_name} cannot accept work, sign anything or move money "
                f"on {owner_name}'s behalf.")
    return (f"{agent_name} is authorized up to {snap['ceiling']} {snap['currency']}, "
            f"underwritten by {owner_name} (mandate {snap['mandate']['mandate_id']}), "
            f"until {snap['expires_at']}. Ask for /audit to check it against the "
            f"registry yourself.")


def within_ceiling(snap: dict, amount: Any, currency: Optional[str]) -> tuple[bool, Optional[str]]:
    """Would this specific commitment fit inside the live grant?

    Pure, so both the card and any caller decide with the same arithmetic. It
    answers a question — it does not authorize anything: the money still moves
    on the money rail, where IRONKEY checks the same token again.
    """
    if not snap.get("authorized"):
        return False, snap.get("reason") or "not authorized"
    amt = _dec(amount)
    if amt is None or amt <= 0:
        return False, "the amount is not a positive number"
    if currency and snap.get("currency") and str(currency).upper() != str(snap["currency"]).upper():
        return False, (f"the grant is in {snap['currency']}, this is in "
                       f"{str(currency).upper()}")
    ceiling = _dec(snap.get("ceiling"))
    if ceiling is None:
        return False, "the grant has no bounded amount"
    if amt > ceiling:
        return False, (f"{money_str(amt)} {snap['currency']} is above the remaining "
                       f"{snap['ceiling']} {snap['currency']}")
    return True, None
