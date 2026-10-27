"""§MEMBERSHIP (2026-10-02): agents cast votes, humans sign them (design § 12, S4).

A member's vote is cast by an agent, but it counts as the member's decision, so where
GOVERNANCE_PRESENCE_MODE asks for it, the human confirms it on a device they enrolled. No new mechanism:
this is the step-up rail the credential reset already uses (services/stepup.py: a mandate-less
`liability_challenges` row with server-built facts, approved in Pocket → Approvals with the device's
WebAuthn key or, as the floor, an authenticator code; single-use, 120 s, expiry is a denial).

    off          votes need nothing beyond the agent token (today's behaviour)
    conditional  a member WITH a second factor must use it; a member without one votes as before
                 (the credential-reset rule: never lock someone out of their own account)
    required     a member without a second factor cannot cast a binding vote until they enroll one;
                 every vote then costs a human and a device, which is the point on an open network

The answer when a step-up is needed is HTTP 428 with the credential reset's body
({"error": "step_up_required", "message", "step_up": {...}}), not its 401: on an agent token a 401 means
"this token is no good" to every client, and the console must not treat a vote waiting for a fingerprint
as an expired credential.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from . import membership as _membership
from . import stepup as _stepup

logger = logging.getLogger(__name__)

STEP_UP_STATUS = 428
NO_FACTOR_STATUS = 403


def registry_label() -> str:
    return (os.getenv("REGISTRY_NAME") or os.getenv("REGISTRY_DISPLAY_NAME") or "this registry").strip()


async def require_presence(db: AsyncSession, developer: Any, *, action_type: str, action_ref: str,
                           facts: Dict[str, Any], totp_code: Optional[str] = None,
                           challenge_id: Optional[str] = None) -> Tuple[bool, int, Optional[Dict[str, Any]]]:
    """(ok, http_status, body) for one binding member action.

    `ok` True means proceed. Otherwise `body` is the JSON to return with `http_status`; when a challenge
    was minted the CALLER must commit before answering, or the phone lights up for a row that was
    rolled back (the credential reset learned that first).
    """
    mode = _membership.presence_mode()
    if mode == "off":
        return True, 200, None
    if developer is None:
        return False, NO_FACTOR_STATUS, {
            "error": "no_developer",
            "message": "This vote has no developer behind it, so nobody can confirm it.",
        }
    if mode == "required":
        factors = await _stepup.available_factors(db, developer)
        if not factors["any"]:
            return False, NO_FACTOR_STATUS, {
                "error": "second_factor_required",
                "message": ("On this registry a member's vote is confirmed on a device. Enroll your phone "
                            "(Pocket, Approvals) or an authenticator app, then vote again."),
                "presence_mode": mode,
            }
    ok, payload = await _stepup.require(
        db, developer, action_type=action_type, action_ref=action_ref, facts=facts,
        totp_code=totp_code, challenge_id=challenge_id,
    )
    if ok:
        return True, 200, None
    return False, STEP_UP_STATUS, {
        "error": "step_up_required",
        "message": "Confirm this vote on your phone, or send a current authenticator code.",
        "presence_mode": mode,
        "step_up": payload,
    }


def vote_facts(*, proposal_id: Any, title: str, in_favor: bool, points: int) -> Dict[str, Any]:
    """What the phone shows before the fingerprint, as separate fields it can lay out and translate.
    Server-side truth only; nothing the client sent. The challenge hash is taken over exactly these."""
    return {
        "action": "Cast a governance vote",
        "kind": "governance.vote",
        "registry": registry_label(),
        "proposal_id": proposal_id,
        "proposal_title": (title or "")[:200],
        "choice": "for" if in_favor else "against",
        "weight": f"{points / _membership.POINTS_PER_WEIGHT:.2f}",
    }


async def announce_challenge(developer_id: int, challenge_id: str, *, action_type: str, title: str,
                             message: str) -> None:
    """Light the member's phone: the same cue the mandate challenges send (`liability.cue` to the member's
    sockets) and a push on the Pocket rail. Best-effort and called only AFTER the commit that stored the
    challenge: a cue that arrives before the row it names is worse than one that never arrives."""
    try:
        from agentvault_registry.routers.websocket import manager as _ws
        await _ws.broadcast({"type": "liability.cue", "challenge_id": challenge_id, "action_type": action_type},
                            audience=f"user_{developer_id}")
    except Exception:  # noqa: BLE001 — the vote waits on the phone's poll instead
        logger.debug("[MEMBERSHIP] cue for challenge %s not delivered", challenge_id, exc_info=True)
    try:
        from agentvault_registry.background_tasks.push_notify import notify
        from agentvault_registry.config import settings
        base = str(getattr(settings, "PUSH_APP_BASE_URL", "") or getattr(settings, "BASE_URL", "") or "").rstrip("/")
        await notify("security.liability_challenge", [developer_id], title=title, message=message,
                     tags="ballot_box_with_check", priority="high",
                     click=f"{base}/ui/#/pocket/approvals" if base else None)
    except Exception:  # noqa: BLE001
        logger.debug("[MEMBERSHIP] push for challenge %s skipped", challenge_id, exc_info=True)


def vote_action_ref(proposal_id: Any, in_favor: bool) -> str:
    """Binds the approval to THIS proposal and THIS choice: a FOR approval cannot be spent on AGAINST."""
    return f"proposal:{proposal_id}:{'for' if in_favor else 'against'}"
