"""§OURSTATE-5c — the fiat door, and the three locks it stays behind.

The Commander's ruling has not moved since the program began (strategy §12):
**onramp only, forever; no fiat-out, no custody.** So the `topup.offer` card
exists, and it is DARK unless all three of these are true at once:

  1. `FIAT_ONRAMP_ENABLED` — the kill switch the fiat lane already has.
  2. `FIAT_GENESIS_REGISTRY` — this node actually origniates purchases, rather
     than a cloud-op that has no lane of its own.
  3. A §REGAUTH jurisdictional profile carrying an ACTIVE `fiat.lane`
     authorization — the operator's own legal declaration, verified against the
     `regulatory_authorizations` rows, not a flag someone set.

Two properties are deliberate and load-bearing:

  * **There is no Stripe code here, and there never will be.** This module
    answers one question — may the door be shown — and the door, when open,
    routes to FLOW 12, the fiat lane that already exists, with its own
    webhooks, idempotency and audit. OurChat contributes zero money code.
  * **A closed door says which lock is shut.** An operator who has enabled the
    lane but not declared the authorization needs to know that, and a user who
    cannot top up needs the honest alternative — the earn surfaces — rather
    than a greyed-out button that explains nothing.

⚠ The fail direction is CLOSED. An unreadable authorization is not an open
door: §REGAUTH's own rule is that a declared-but-unverifiable requirement
refuses, and money in is exactly where that matters.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

FIAT_ACTION = "fiat.lane"


def _flag(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in ("1", "true", "yes", "on")


async def door_state(db: AsyncSession) -> dict:
    """May the fiat door be shown here, and if not, which lock is shut?

    Returns a shape safe to hand to any authenticated caller: booleans and
    reasons, never keys, never provider configuration.
    """
    locks = []

    onramp = _flag("FIAT_ONRAMP_ENABLED")
    if not onramp:
        locks.append({"lock": "onramp_disabled",
                      "says": "this registry does not run a fiat onramp"})

    genesis = _flag("FIAT_GENESIS_REGISTRY")
    if not genesis:
        locks.append({"lock": "not_genesis_registry",
                      "says": "this node does not originate fiat purchases"})

    declared, authorized, note = await _regauth_state(db)
    if declared and not authorized:
        locks.append({"lock": "no_regulatory_authorization",
                      "says": note or "the declared fiat.lane authorization is not active"})

    open_ = not locks
    out = {
        "open": open_,
        "locks": locks,
        # Stated even when open, because "we take card payments" and "we hold
        # your money" are different claims and only the first is true here.
        "posture": ("onramp only — money in, never out; this registry never "
                    "holds a fiat balance for you"),
    }
    if not open_:
        # The honest alternative. A door that cannot open should point at the
        # ones that can, rather than leaving a dead control on screen.
        out["alternative"] = ("earn it instead: guild work, services and staking "
                              "all pay in this registry's own currency")
    return out


async def _regauth_state(db: AsyncSession) -> tuple[bool, bool, Optional[str]]:
    """(declared, authorized, note) for `fiat.lane` under §REGAUTH.

    A registry that declares nothing is not blocked by this lock — the
    declaration is the operator's, and inventing one for them would be this
    module deciding their jurisdiction.
    """
    try:
        from . import jurisdiction as _juris
        from . import regulatory_auth as _regauth
        if _juris.mode() == "off":
            return False, True, None
        profile = await _juris.get_profile(db)
        req = _regauth.declared_requirement(profile, FIAT_ACTION)
        if req is None:
            return False, True, None
        auth = await _regauth.active_authorization(db, FIAT_ACTION, None)
        if auth is None:
            return True, False, ("this registry declares that the fiat lane requires a "
                                 "regulatory authorization, and none is active")
        return True, True, None
    except Exception as e:  # noqa: BLE001
        # Fail CLOSED and say so: an unreadable authorization is not permission.
        logger.error("[FIATDOOR] authorization unreadable: %s", e)
        return True, False, ("the declared fiat.lane authorization could not be read — "
                             "refusing rather than guessing")


async def may_offer_topup(db: AsyncSession) -> tuple[bool, Optional[str]]:
    """The card gate. Returns (allowed, refusal_sentence).

    Refusal names the FIRST shut lock rather than a generic 'unsupported card',
    because the sender is usually the person who could fix it (an operator) or
    the person who deserves the alternative (a user).
    """
    st = await door_state(db)
    if st["open"]:
        return True, None
    first = st["locks"][0]
    return False, (f"the fiat door is closed here — {first['says']}. "
                   f"{st.get('alternative', '')}").strip()
