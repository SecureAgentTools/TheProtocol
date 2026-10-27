"""STEP-UP (2026-08-23, §DISCREFINE) — a second factor on a sensitive, non-money action.

Commander's ask: "for resetting agent credentials it would be best to have 2fa enabled."

WHAT THIS IS NOT: a new confirm mechanism. Everything here rides rails that already
exist and are proven in production:

  * `liability_challenges` — server-canonical facts, a nonce, single-use status and
    "expiry is a denial". Mig 0154 made `mandate_id` nullable so an action with no
    mandate behind it can mint one.
  * `PocketApprovals.vue` — already lists pending challenges and approves them with
    a WebAuthn assertion or a TOTP code. A credential reset now simply APPEARS there.
  * `services/webauthn.py` — verifies the assertion against the developer's ENROLLED
    device key and requires the user-verification bit, so the biometric is checked
    server-side rather than asserted by the page.

WHY IT IS CONDITIONAL. Demanding a second factor from a developer who has none would
lock them out of their own agents, and the Commander was explicit that enabling 2FA is
each account's own decision ("everyone can flip enforce on his account by himself").
So the rule is: IF you have a factor, you must use it here; if you have none, the
password stands alone, exactly as before. Within that rule the gate is fail-CLOSED —
a developer WITH a factor who presents a missing, wrong or expired proof is denied,
never waved through.

WHAT BINDS A PROOF TO AN ACTION. The challenge carries server-built facts naming the
action and the agent, and the WebAuthn assertion signs that challenge, so an approval
minted for one agent cannot be replayed onto another. TOTP has no such binding — a
code is a code for 30 seconds — which is why it is the FLOOR and the phone path is
preferred. That difference is stated, not hidden.
"""
from __future__ import annotations

import datetime as _dt
import logging
import secrets
from typing import Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.services import liability as liab

logger = logging.getLogger(__name__)

CHALLENGE_TTL_SECONDS = 120


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


async def available_factors(db: AsyncSession, dev: models.Developer) -> dict:
    """Which second factors this developer can actually produce, right now.

    `device` counts only a device row with an enrolled, unrevoked WebAuthn key —
    an enrolled-but-revoked key is not a factor, and treating it as one would ask
    for a proof that can never be produced.
    """
    totp = bool(getattr(dev, "two_fa_enabled", False) and getattr(dev, "totp_secret", None))
    rows = (await db.execute(
        select(models.DevicePushRegistration.id).where(
            models.DevicePushRegistration.developer_id == dev.id,
            models.DevicePushRegistration.webauthn_public_key.isnot(None),
            models.DevicePushRegistration.key_revoked_at.is_(None),
        )
    )).scalars().all()
    device = len(rows) > 0
    return {"totp": totp, "device": device, "any": totp or device}


async def mint_challenge(db: AsyncSession, dev: models.Developer, *,
                         action_type: str, action_ref: str, facts: dict) -> models.LiabilityChallenge:
    """Create a single-use, mandate-less presence challenge and return it.

    The facts are built by the CALLER from server-side truth and are what the phone
    renders and signs. Nothing the client sent is echoed into them.
    """
    nonce = secrets.token_hex(16)
    chid = liab.new_id("lch")
    ch = models.LiabilityChallenge(
        id=chid,
        mandate_id=None,                      # mig 0154 — no mandate behind this action
        developer_id=dev.id,
        action_type=action_type,
        action_ref=action_ref,
        facts=facts,
        nonce=nonce,
        challenge_hash=liab.challenge_hash_for(facts, nonce),
        status="pending",
        expires_at=_now() + _dt.timedelta(seconds=CHALLENGE_TTL_SECONDS),
    )
    db.add(ch)
    await db.flush()
    return ch


async def consume_approved(db: AsyncSession, dev: models.Developer, challenge_id: str, *,
                           action_type: str, action_ref: str) -> Tuple[bool, str]:
    """Spend an APPROVED challenge for exactly this action. Returns (ok, reason).

    Single-use is enforced by a conditional UPDATE rather than a read-then-write, so
    two racing requests cannot both spend the same approval.
    """
    ch = await db.get(models.LiabilityChallenge, challenge_id)
    if ch is None or ch.developer_id != dev.id:
        return False, "challenge not found"
    if ch.action_type != action_type or (ch.action_ref or "") != action_ref:
        # The whole point of binding: an approval for agent A is not an approval
        # for agent B, and an approval to reset is not an approval to delete.
        return False, "challenge does not match this action"
    if ch.status != "approved":
        return False, f"challenge is {ch.status}"
    if ch.expires_at <= _now():
        return False, "challenge expired — expiry is a denial"
    spent = await db.execute(text(
        "UPDATE liability_challenges SET status='spent', resolved_at=now() "
        "WHERE id=:c AND status='approved' RETURNING id"
    ), {"c": challenge_id})
    if spent.first() is None:
        return False, "challenge already spent"
    return True, "ok"


async def verify_totp(dev: models.Developer, code: str) -> bool:
    """The floor. Reuses the account's existing 2FA secret — there is no second secret."""
    return liab.verify_totp_for_dev(dev, (code or "").strip())


async def require(db: AsyncSession, dev: models.Developer, *,
                  action_type: str, action_ref: str, facts: dict,
                  totp_code: Optional[str] = None,
                  challenge_id: Optional[str] = None) -> Tuple[bool, Optional[dict]]:
    """The gate. Returns (satisfied, step_up_payload_when_not).

    When the caller has a factor but produced no valid proof, a fresh challenge is
    minted and returned so the client can light up the phone and retry. That is why
    the failure payload is data, not just a message.
    """
    factors = await available_factors(db, dev)
    if not factors["any"]:
        # No factor to ask for. Say so in the log so an operator reading it knows
        # this reset was password-only by circumstance, not by a skipped check.
        logger.info(
            "[STEPUP] dev %s has no second factor enrolled; %s proceeding on password alone",
            dev.id, action_type,
        )
        return True, None

    if totp_code and factors["totp"] and await verify_totp(dev, totp_code):
        logger.info("[STEPUP] dev %s satisfied %s with TOTP", dev.id, action_type)
        return True, None

    if challenge_id:
        ok, reason = await consume_approved(
            db, dev, challenge_id, action_type=action_type, action_ref=action_ref
        )
        if ok:
            logger.info("[STEPUP] dev %s satisfied %s with an approved challenge", dev.id, action_type)
            return True, None
        logger.warning("[STEPUP] dev %s failed %s: %s", dev.id, action_type, reason)
        ch = await mint_challenge(db, dev, action_type=action_type, action_ref=action_ref, facts=facts)
        return False, _payload(ch, factors, reason)

    ch = await mint_challenge(db, dev, action_type=action_type, action_ref=action_ref, facts=facts)
    return False, _payload(ch, factors, "second factor required")


def _payload(ch: models.LiabilityChallenge, factors: dict, reason: str) -> dict:
    return {
        "reason": reason,
        "challenge_id": ch.id,
        "challenge_hash": ch.challenge_hash,
        "facts": ch.facts,
        "expires_at": ch.expires_at.isoformat(),
        "ttl_seconds": CHALLENGE_TTL_SECONDS,
        "methods": [m for m, on in (("device", factors["device"]), ("totp", factors["totp"])) if on],
        "how": (
            "Approve it on your phone (Pocket → Approvals), or resend this request "
            "with a current code from your authenticator app."
        ),
    }
