"""D6-850 — how a device credential joins (and leaves) an account.

A device credential (a WebAuthn key with user verification) answers every `webauthn_uv` presence challenge: the
Cockpit's confirms, governance presence, the credential-reset step-up, a chat approval's presence, a phone-approved
sign-in. So adding one is held to the standard of what it unlocks:

  1. a person signed in (a session, never an API key, whatever its scopes);
  2. a registration challenge THIS server issued, used once and within REGISTRATION_TTL_SECONDS, echoed back in the
     clientDataJSON the authenticator saw (services.webauthn.verify_registration checks the rest of the ceremony);
  3. once the account holds an enrolled device, the approval of one of them: a step-up challenge on the existing rail
     (services.stepup, Pocket's Approvals), answered with that device's fingerprint (method `webauthn_uv`), bound to
     this registration and this credential. A code is not a device.

Removing a live credential takes the account's second factor (stepup.require: an enrolled device or a code), so a
removal cannot be the way back to "no device yet". When every factor is lost, the maintainer's account recovery path
revokes the keys (routers.liability, the admin route) and the person enrols afresh.

The registration challenge rides `liability_challenges` (mig 0132/0154) under its own action type and status
(`issued`, then `consumed` or `expired`), so it never appears among the presence challenges a person approves.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import secrets
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.services import liability as liab
from agentvault_registry.services import stepup

logger = logging.getLogger(__name__)

REGISTER_ACTION = "device_register"      # the registration challenge (status issued -> consumed | expired)
CONFIRM_ACTION = "device_add"            # the step-up that approves a new device (an enrolled one, or a first one's code)
REMOVE_ACTION = "device_key_remove"      # removing a live device credential
REGISTRATION_TTL_SECONDS = 600           # the ceremony plus the walk to an enrolled device
KEEP_ISSUED = 5                          # unused registration challenges kept per account
DEVICE_METHODS = ("webauthn_uv",)        # what may approve a new device
PROMPTS_PER_HOUR = 3                     # new-device prompts an account receives in an hour (then 429): no tired yes
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"   # no 0/O, 1/I/L


class StepUpProofIn(BaseModel):
    """The account's second factor for removing a live key: a code, or a challenge an enrolled device approved.
    In the body, never the query (a query string lands in the access log)."""
    totp_code: Optional[str] = Field(None, max_length=12)
    challenge_id: Optional[str] = Field(None, max_length=64)


def match_code(credential_id: str) -> str:
    """Six characters both screens show (the new device's waiting note, the enrolled phone's facts), so the person
    approves the device in front of them and not another one asking at the same time."""
    digest = hashlib.sha256(credential_id.encode()).digest()
    chars = "".join(_CODE_ALPHABET[b % len(_CODE_ALPHABET)] for b in digest[:6])
    return f"{chars[:3]}-{chars[3:]}"


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def refuse_api_key(what: str = "A device credential is added or removed") -> None:
    """403 when an API key authenticated this request (presented_api_key_* is None for a session)."""
    from agentvault_registry.security import presented_api_key_id, presented_api_key_scopes
    if presented_api_key_id() is not None or presented_api_key_scopes() is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail=f"{what} signed in, in the console or in Pocket; an API key cannot do it.")


# ── the registration challenge ──────────────────────────────────────────────────────────────────

async def issue_registration_challenge(db: AsyncSession, dev: Any, *, scope: str = "self") -> models.LiabilityChallenge:
    """Mint the challenge a registration must echo. Older unused ones of this account beyond KEEP_ISSUED (and any
    past their time) are retired first, so asking for options again and again holds a handful of rows, not a pile."""
    await db.execute(text(
        "UPDATE liability_challenges SET status = 'expired', resolved_at = now() "
        "WHERE developer_id = :d AND action_type = :a AND status = 'issued' AND (expires_at <= now() OR id IN ("
        "SELECT id FROM liability_challenges WHERE developer_id = :d AND action_type = :a AND status = 'issued' "
        "ORDER BY created_at DESC OFFSET :k))"),
        {"d": dev.id, "a": REGISTER_ACTION, "k": KEEP_ISSUED - 1})
    nonce = secrets.token_hex(16)
    facts = {"action": "register_device_credential", "scope": scope}
    ch = models.LiabilityChallenge(
        id=liab.new_id("lch"), mandate_id=None, developer_id=dev.id,
        action_type=REGISTER_ACTION, action_ref=scope, facts=facts, nonce=nonce,
        challenge_hash=liab.challenge_hash_for(facts, nonce), status="issued",
        expires_at=_now() + _dt.timedelta(seconds=REGISTRATION_TTL_SECONDS),
    )
    db.add(ch)
    await db.flush()
    return ch


def webauthn_challenge_of(ch: Any) -> str:
    """The challenge as the browser receives and echoes it: the hash's bytes, base64url (as every presence challenge)."""
    return liab.b64u_from_hex(ch.challenge_hash)


async def find_registration_challenge(db: AsyncSession, dev: Any, echoed_b64u: Optional[str], *,
                                      scope: str = "self") -> Optional[Any]:
    """The issued, unexpired registration challenge of this account the clientDataJSON echoed, or None."""
    from agentvault_registry.services.webauthn import b64u_decode
    if not echoed_b64u:
        return None
    try:
        hex_hash = b64u_decode(echoed_b64u).hex()
    except Exception:
        return None
    row = (await db.execute(text(
        "SELECT id, developer_id, challenge_hash, action_ref, expires_at, status FROM liability_challenges "
        "WHERE developer_id = :d AND action_type = :a AND challenge_hash = :h AND status = 'issued' LIMIT 1"),
        {"d": dev.id, "a": REGISTER_ACTION, "h": hex_hash})).first()
    if row is None or (getattr(row, "action_ref", None) or "") != scope:
        return None
    exp = getattr(row, "expires_at", None)
    if exp is None or exp <= _now():
        return None
    return row


async def spend_registration_challenge(db: AsyncSession, ch: Any) -> bool:
    """Single use, by a guarded UPDATE: two racing registrations cannot both spend it."""
    res = await db.execute(text(
        "UPDATE liability_challenges SET status = 'consumed', resolved_at = now() "
        "WHERE id = :c AND status = 'issued' RETURNING id"), {"c": ch.id})
    return res.first() is not None


# ── who already holds a device ──────────────────────────────────────────────────────────────────

async def live_row_for_credential(db: AsyncSession, dev_id: int, credential_id: str,
                                  public_key: str) -> Optional[int]:
    """The device row on which THIS credential (its id AND its public key) is already enrolled and live: re-enrolling
    it adds no new trust. The id alone is not enough: ids are listed to the account (/devices/mine), so a known id
    carrying another key is a new credential."""
    row = (await db.execute(text(
        "SELECT id FROM device_push_registrations WHERE developer_id = :d AND webauthn_credential_id = :c "
        "AND webauthn_public_key = :k AND key_revoked_at IS NULL LIMIT 1"),
        {"d": dev_id, "c": credential_id, "k": public_key})).first()
    return int(row[0]) if row is not None else None


async def holds_enrolled_device(db: AsyncSession, dev: Any) -> bool:
    """The step-up rail's own answer (an unrevoked WebAuthn key), so 'has a device' means one thing everywhere."""
    return bool((await stepup.available_factors(db, dev)).get("device"))


# ── an enrolled device approves a new one ───────────────────────────────────────────────────────

def confirm_action_ref(registration_id: str, credential_id: str) -> str:
    """Binds the approval to THIS registration and THIS credential: it cannot be spent on another device."""
    return f"device_add:{registration_id}:{hashlib.sha256(credential_id.encode()).hexdigest()[:24]}"


def _step_up_body(ch: Any, reason: str, *, methods: Tuple[str, ...] = ("device",)) -> Dict[str, Any]:
    by_code = "device" not in methods
    return {
        "error": "step_up_required",
        "message": ("Enter a current code from your authenticator app to add this first device." if by_code else
                    "Approve this new device on one of your enrolled devices (Pocket, Approvals); check that it shows "
                    f"the code {(ch.facts or {}).get('code', '')}. This device finishes the enrolment once it is "
                    "approved."),
        "step_up": {
            "reason": reason,
            "challenge_id": ch.id,
            "challenge_hash": ch.challenge_hash,
            "facts": ch.facts,
            "expires_at": ch.expires_at.isoformat() if hasattr(ch.expires_at, "isoformat") else str(ch.expires_at),
            "ttl_seconds": stepup.CHALLENGE_TTL_SECONDS,
            "methods": list(methods),
            "how": ("Send this enrolment again with totp_code." if by_code else
                    "Approve it with the fingerprint of an enrolled device, then send this enrolment again with "
                    "confirm_challenge_id."),
        },
    }


async def prompt_cap(db: AsyncSession, dev: Any) -> None:
    """429 once this account received PROMPTS_PER_HOUR new-device prompts in the last hour: someone holding a stolen
    session must not be able to ask again and again until a tired person taps approve."""
    n = (await db.execute(text(
        "SELECT count(*) FROM liability_challenges WHERE developer_id = :d AND action_type = :a "
        "AND created_at > now() - interval '1 hour'"), {"d": dev.id, "a": CONFIRM_ACTION})).scalar() or 0
    if int(n) >= PROMPTS_PER_HOUR:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": "3600"},
                            detail=f"This account was asked to approve {PROMPTS_PER_HOUR} new devices in the last "
                                   "hour; try again later.")


async def refuse_after_denial(db: AsyncSession, registration: Any) -> None:
    """The account's own device said no: this registration ends here (403) and asks nobody again. A new attempt
    needs new options and is held to the hourly cap."""
    await db.execute(text(
        "UPDATE liability_challenges SET status = 'expired', resolved_at = now() WHERE id = :c AND status = 'issued'"),
        {"c": registration.id})
    await db.commit()
    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        detail="An enrolled device declined this new device. Nothing was added.")


def _device_facts(credential_id: str, rp_id: str) -> Dict[str, Any]:
    return {
        "action": "Add a new device to your account",
        "code": match_code(credential_id),
        "site": rp_id,
        "asked_at": _now().strftime("%Y-%m-%d %H:%M UTC"),
        "consequence": "Approve only if you are adding this device yourself and it shows the same code: it will "
                       "confirm actions as you.",
    }


async def device_approval(db: AsyncSession, dev: Any, *, registration: Any, credential_id: str, rp_id: str,
                          confirm_challenge_id: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]], bool]:
    """(approved, step_up_body, minted). Approved: the challenge was approved by an enrolled device's fingerprint and
    is now spent. Otherwise the body to answer 428 with; `minted` says a fresh challenge exists that the caller must
    commit and announce. A challenge still waiting is answered again as it is (a client may resend while it waits:
    each resend must not light the phone up anew). A DENIED challenge ends the registration (403); every new prompt
    passes the hourly cap first (429)."""
    action_ref = confirm_action_ref(registration.id, credential_id)
    reason = "an enrolled device approves a new one"
    if confirm_challenge_id:
        ch = await db.get(models.LiabilityChallenge, confirm_challenge_id)
        if ch is None or ch.developer_id != dev.id:
            reason = "challenge not found"
        elif ch.action_type != CONFIRM_ACTION or (ch.action_ref or "") != action_ref:
            reason = "the challenge was minted for a different device"
        elif ch.status == "denied":
            await refuse_after_denial(db, registration)
        elif ch.status == "pending" and ch.expires_at > _now():
            return False, _step_up_body(ch, "waiting for an enrolled device to approve"), False
        elif ch.status == "approved" and ch.method not in DEVICE_METHODS:
            reason = (f"the challenge was answered with {ch.method or 'an unknown method'}; a new device needs the "
                      "fingerprint of an enrolled device, not a code")
        else:
            ok, why = await stepup.consume_approved(db, dev, confirm_challenge_id, action_type=CONFIRM_ACTION,
                                                    action_ref=action_ref)
            if ok:
                return True, None, False
            reason = why
    await prompt_cap(db, dev)
    ch = await stepup.mint_challenge(db, dev, action_type=CONFIRM_ACTION, action_ref=action_ref,
                                     facts=_device_facts(credential_id, rp_id))
    return False, _step_up_body(ch, reason), True


def has_code_factor(dev: Any) -> bool:
    """2FA is on: the account has an authenticator code to give (stepup.available_factors' own test)."""
    return bool(getattr(dev, "two_fa_enabled", False) and getattr(dev, "totp_secret", None))


async def first_device_code(db: AsyncSession, dev: Any, *, registration: Any, credential_id: str, rp_id: str,
                            totp_code: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """The FIRST device of an account with 2FA on takes a current authenticator code (no device exists yet to
    approve it). Without 2FA the signed-in session and the server's challenge stand alone, as stepup's doctrine
    says: a factor the account does not have is not asked for."""
    if totp_code and await stepup.verify_totp(dev, totp_code):
        return True, None
    await prompt_cap(db, dev)
    ch = await stepup.mint_challenge(db, dev, action_type=CONFIRM_ACTION,
                                     action_ref=confirm_action_ref(registration.id, credential_id),
                                     facts=_device_facts(credential_id, rp_id))
    # No device approves a first device: its code is the whole step. The challenge was left pending, and Pocket lists
    # an account's pending challenges, so a stale "Add a new device" card stayed in Approvals once the code had
    # enrolled the device. It is resolved as it is minted. The hourly cap (prompt_cap) still counts it, which is what
    # bounds the codes this step can be asked with, and the 428 keeps the challenge id the console reads.
    ch.status = "expired"
    ch.resolved_at = _dt.datetime.now(_dt.timezone.utc)
    reason = "that code is not current" if totp_code else "a first device takes a code from your authenticator app"
    return False, _step_up_body(ch, reason, methods=("totp",))


def tell_the_account(dev_id: int, *, title: str, message: str) -> None:
    """Post-commit, best effort: the account hears it on the channels its owner chose for security.device_enrolled
    (the catalog's type for a device joining; security notices send no mail by default, the maintainer's call)."""
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify
        _aio.create_task(notify("security.device_enrolled", [int(dev_id)], title=title, message=message,
                                tags="iphone", priority="high", click="/ui/#/pocket/approvals"))
    except Exception:  # noqa: BLE001 — a notice never undoes the change it reports
        logger.debug("[DEVICE-ENROL] notice skipped for dev %s", dev_id, exc_info=True)


async def announce_device_challenge(dev_id: int, challenge_id: str) -> None:
    """Light the enrolled phones (the same cue and push a member's vote uses). Call AFTER the commit."""
    from agentvault_registry.services.governance_presence import announce_challenge
    await announce_challenge(int(dev_id), challenge_id, action_type=CONFIRM_ACTION,
                             title="A new device asks to be added",
                             message="Approve it only if you are adding a device yourself.")


# ── removal ─────────────────────────────────────────────────────────────────────────────────────

def holds_live_credential(row: Any) -> bool:
    """A device row whose credential still answers presence (WebAuthn or the legacy signing key)."""
    return bool(row is not None and getattr(row, "key_revoked_at", None) is None
                and (getattr(row, "webauthn_public_key", None) or getattr(row, "pubkey_jwk", None)))


async def removal_step_up(db: AsyncSession, dev: Any, row: Any, *, totp_code: Optional[str],
                          challenge_id: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """The account's second factor before a live credential goes (stepup.require: an enrolled device or a code; an
    account with no factor at all has nothing a removal could reopen)."""
    ok, payload = await stepup.require(
        db, dev, action_type=REMOVE_ACTION, action_ref=f"device:{row.id}",
        facts={
            "action": "Remove a device's signing key",
            "device": getattr(row, "label", None) or f"device {row.id}",
            "consequence": "That device stops confirming actions for you.",
        },
        totp_code=totp_code, challenge_id=challenge_id)
    if ok:
        return True, None
    return False, {
        "error": "step_up_required",
        "message": "Confirm this on an enrolled device (Pocket, Approvals), or send a current authenticator code.",
        "step_up": payload,
    }


def local_target() -> str:
    """The target of a credential-only row (rail 'local', never a push rail): what a push row becomes when its push
    subscription goes but its credential stays."""
    return f"device:{secrets.token_hex(8)}"


LIVE_CREDENTIAL_SQL = "(webauthn_public_key IS NOT NULL OR pubkey_jwk IS NOT NULL) AND key_revoked_at IS NULL"


async def drop_push_keep_credential(db: AsyncSession, row_id: int) -> bool:
    """A push subscription that ends (unsubscribed, or gone at the push service) takes only the push half of its row:
    a row that also holds a live credential becomes a credential-only row. True when the credential was kept."""
    res = await db.execute(text(
        "UPDATE device_push_registrations SET rail = 'local', target = :t, p256dh = NULL, auth = NULL "
        f"WHERE id = :i AND {LIVE_CREDENTIAL_SQL} RETURNING id"), {"t": local_target(), "i": row_id})
    if res.first() is not None:
        return True
    await db.execute(text(f"DELETE FROM device_push_registrations WHERE id = :i AND NOT ({LIVE_CREDENTIAL_SQL})"),
                     {"i": row_id})
    return False
