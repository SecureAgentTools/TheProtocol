"""§FRAMEMAIL-4 — parent-side outbound mail relay for nodes that hold no token.

A registry whose admin credential is held outside this org must never carry an SMTP
submission token (PART 11b): a credential inside a container somebody else
administers is a credential we have given away. But such a node still has to send
verification mail, or `REQUIRE_EMAIL_VERIFICATION=true` locks every self-registered
account out permanently (the §OPGUIDE-2 lockout).

So it does not speak SMTP. It asks its parent to send:

    hetzner-frame ──HTTPS + federation license──▶ registry-a ──SMTP──▶ recipient
       (no token)                                (holds the token)

WHY THIS SHAPE IS SAFE. Five properties, all load-bearing; drop any one and this
becomes an open relay wearing our From: address.

1. **The From: is ours, never the caller's.** The caller cannot express a sender.
   It is resolved on this side from the parent's own configuration.

2. **No free-form content — and no free-form URL either.** The caller picks a
   template KEY from a closed allowlist and supplies a few typed variables. It
   never sends a subject, a body, or a link. Crucially it does not even send the
   verification URL: it sends the opaque TOKEN, and this side builds the link from
   the caller's OWN registered base URL. There is therefore no attacker-controlled
   string anywhere in the message — a compromised child cannot put a phishing link
   in an email that goes out over our domain. A relay that accepts a body, or a
   URL, is not this design.

3. **Being licensed is not being allowed to send.** Federation licenses are minted
   for ordinary federation. Mail relay additionally requires the caller to appear
   in `MAIL_RELAY_CALLERS` on this node, which is also where its base URL and
   display label come from. Two independent grants, so a federation license can
   never silently become a mail credential.

4. **Rate limited per caller, and it fails CLOSED.** A send cap and a distinct-
   recipient cap bound the blast radius of a stolen child credential to a nuisance.
   If the counter store is unreachable we refuse rather than send uncounted: this is
   a credential-bearing path to the public internet in our name, and if we cannot
   count we do not send. (Redis being down on this node is already a major incident
   — leader election and WS fan-out are gone too — so this is not the failure mode
   that keeps a healthy frame from mailing.)

5. **Every attempt is audited**, accepted or refused, with the recipient stored as
   a salted-in-place hash rather than an address.

Config on the PARENT (all absent by default — this endpoint ships dark):

    MAIL_RELAY_ENABLED=true
    MAIL_RELAY_CALLERS={"<did-or-spiffe>": {"base_url": "...", "label": "..."}}
    MAIL_RELAY_MAX_PER_HOUR=60
    MAIL_RELAY_MAX_RECIPIENTS_PER_DAY=200
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from agentvault_registry.core.federation_auth import require_peer_registry_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/federation", tags=["mail-relay"])

try:  # metrics are best-effort; never let observability break the gate
    from prometheus_client import Counter

    _RELAY_TOTAL = Counter(
        "mail_relay_requests_total",
        "Parent-side mail relay requests",
        ["caller", "template", "outcome"],
    )
except Exception:  # pragma: no cover
    _RELAY_TOTAL = None


def _count(caller: str, template: str, outcome: str) -> None:
    if _RELAY_TOTAL is not None:
        try:
            _RELAY_TOTAL.labels(caller=caller, template=template, outcome=outcome).inc()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# The closed template allowlist. THIS is property 2.
#
# `link` is a format string filled with the CALLER'S OWN base_url plus the opaque
# token — the caller never supplies a URL. `subject` and `theme` are ours. Only
# the keys in `vars` are accepted, and each is validated by type below.
# ---------------------------------------------------------------------------
_TEMPLATES: dict[str, dict] = {
    # §MAILIDENT: {registry} is filled with the CALLER's allowlist label at send
    # time, never with anything the caller transmits — one shared sender means the
    # subject line has to say which node the mail is really about.
    "verification": {
        "subject": "Verify your email for {registry}",
        "theme": "neural",
        "link_var": "verification_link",
        "link_path": "/api/v1/auth/verify-email?token={token}",
        "expiry_hours_default": 24,
    },
    "password_reset": {
        "subject": "Password Reset Request for {registry}",
        "theme": "sovereign",
        "link_var": "reset_link",
        "link_path": "/ui#/reset-password?token={token}",
        "expiry_hours_default": 1,
    },
}

# An opaque credential-bearing token. Deliberately strict: this string is spliced
# into a URL we send in our own name, so anything that is not a plain token is a
# reason to refuse rather than to sanitise.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]{16,512}$")
# A display name. Control characters and angle brackets are refused outright so a
# username can never inject markup or a second header line.
_USERNAME_RE = re.compile(r"^[^\x00-\x1f<>\r\n]{1,120}$")


class MailRelayRequest(BaseModel):
    """What a child may ask for. Note what is ABSENT: subject, body, sender, URL."""

    template: str = Field(..., description="Template key from the parent's allowlist.")
    recipient: EmailStr = Field(..., description="Single recipient. One send, one address.")
    username: str = Field(..., description="Display name for the greeting line.")
    token: str = Field(..., description="Opaque token; the PARENT builds the link around it.")
    expiry_hours: Optional[int] = Field(
        default=None, ge=1, le=168, description="Stated validity in the body."
    )


def _relay_enabled() -> bool:
    return (os.getenv("MAIL_RELAY_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def _callers() -> dict:
    """Parsed `MAIL_RELAY_CALLERS`. A malformed map is an EMPTY map, never a wildcard."""
    raw = (os.getenv("MAIL_RELAY_CALLERS") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("MAIL_RELAY_CALLERS must be a JSON object")
        return parsed
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[mail-relay] MAIL_RELAY_CALLERS is not parseable (%s) — treating as EMPTY. "
            "No caller is authorised; this refuses rather than opening the relay.",
            exc,
        )
        return {}


def _resolve_caller(identity: str) -> Optional[dict]:
    """Match an authenticated federation identity to a relay-authorised caller.

    Accepts the full SPIFFE id or the operator DID tail, because a license-authed
    caller arrives as the synthetic `spiffe://…/service/registry-<did>` while an
    mTLS caller arrives as its real SVID. Matching both means the allowlist does
    not have to encode which auth mode a node happens to use.
    """
    callers = _callers()
    if not callers:
        return None
    candidates = {identity}
    path = urlparse(identity).path or ""
    tail = path.rsplit("/", 1)[-1] if path else ""
    if tail:
        candidates.add(tail)
        if tail.startswith("registry-"):
            candidates.add(tail[len("registry-"):])
    for key in candidates:
        entry = callers.get(key)
        if isinstance(entry, dict) and str(entry.get("base_url") or "").strip():
            return {
                "key": key,
                "base_url": str(entry["base_url"]).strip().rstrip("/"),
                "label": str(entry.get("label") or key).strip(),
            }
    return None


def _rcpt_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


async def _check_and_count(caller_key: str, rcpt: str) -> tuple[bool, str]:
    """Per-caller send + distinct-recipient caps. FAILS CLOSED (property 4).

    Returns (allowed, reason). Redis unreachable => (False, "counter_unavailable").
    """
    try:
        max_hour = int(os.getenv("MAIL_RELAY_MAX_PER_HOUR") or "60")
        max_rcpt_day = int(os.getenv("MAIL_RELAY_MAX_RECIPIENTS_PER_DAY") or "200")
    except ValueError:
        max_hour, max_rcpt_day = 60, 200

    try:
        from agentvault_registry.background_tasks.leader import get_redis

        r = await get_redis()
    except Exception as exc:  # noqa: BLE001
        logger.error("[mail-relay] counter store unavailable (%s) — refusing", exc)
        return False, "counter_unavailable"

    if r is None:
        logger.error(
            "[mail-relay] no REDIS_URL on this node — refusing. The relay must be able to "
            "count what it sends in our name."
        )
        return False, "counter_unavailable"

    safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", caller_key)[:64]
    send_key = f"registry:mailrelay:sends:{safe}"
    rcpt_key = f"registry:mailrelay:rcpts:{safe}"
    try:
        sends = await r.incr(send_key)
        if sends == 1:
            await r.expire(send_key, 3600)
        if sends > max_hour:
            return False, f"rate_limit_sends({sends}>{max_hour})"

        await r.sadd(rcpt_key, _rcpt_hash(rcpt))
        # Set the TTL every time: a rolling day whose window cannot be reset by the
        # caller, and which self-heals if a prior EXPIRE was lost.
        await r.expire(rcpt_key, 86400)
        distinct = await r.scard(rcpt_key)
        if distinct > max_rcpt_day:
            return False, f"rate_limit_recipients({distinct}>{max_rcpt_day})"
    except Exception as exc:  # noqa: BLE001
        logger.error("[mail-relay] counter operation failed (%s) — refusing", exc)
        return False, "counter_unavailable"

    return True, "ok"


async def _audit(
    *,
    caller: str,
    template: str,
    rcpt: str,
    outcome: str,
    reason: str = "",
    actor_ip: Optional[str] = None,
) -> None:
    """Property 5. Never raises, and never records the address itself."""
    try:
        from agentvault_registry.database import AsyncSessionLocal
        from agentvault_registry.services.admin_audit import log_admin_action

        async with AsyncSessionLocal() as db:
            await log_admin_action(
                db,
                action="mail_relay.send",
                actor_id=caller,
                actor_ip=actor_ip,
                target_type="mail_relay",
                target_id=f"{template}:{_rcpt_hash(rcpt)}",
                outcome=outcome,
                severity="info" if outcome == "success" else "warning",
                details={"template": template, "recipient_sha256_16": _rcpt_hash(rcpt), "reason": reason},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[mail-relay] audit write failed (non-fatal): %s", exc)


@router.post(
    "/mail-relay",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a templated email on behalf of a peer registry that holds no SMTP token",
)
async def relay_mail(
    payload: MailRelayRequest,
    request: Request,
    identity: str = Depends(require_peer_registry_identity),
):
    client_ip = request.client.host if request.client else None
    tmpl_key = (payload.template or "").strip()

    if not _relay_enabled():
        _count("unknown", tmpl_key or "none", "disabled")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail relay is not enabled on this registry",
        )

    caller = _resolve_caller(identity)
    if caller is None:
        # Authenticated for federation, NOT authorised to send mail (property 3).
        logger.warning(
            "[mail-relay] REFUSED: '%s' is a valid federation peer but is not in "
            "MAIL_RELAY_CALLERS. A federation license is not a mail credential.",
            identity,
        )
        _count("unauthorised", tmpl_key or "none", "not_allowlisted")
        await _audit(
            caller=identity, template=tmpl_key or "none", rcpt=str(payload.recipient),
            outcome="denied", reason="not_allowlisted", actor_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This peer is not authorised to relay mail",
        )

    spec = _TEMPLATES.get(tmpl_key)
    if spec is None:
        logger.warning("[mail-relay] REFUSED: caller '%s' asked for unknown template '%s'",
                       caller["key"], tmpl_key)
        _count(caller["key"], tmpl_key or "none", "unknown_template")
        await _audit(
            caller=caller["key"], template=tmpl_key or "none", rcpt=str(payload.recipient),
            outcome="denied", reason="unknown_template", actor_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown template. Allowed: {sorted(_TEMPLATES)}",
        )

    if not _TOKEN_RE.match(payload.token or ""):
        _count(caller["key"], tmpl_key, "bad_token")
        await _audit(
            caller=caller["key"], template=tmpl_key, rcpt=str(payload.recipient),
            outcome="denied", reason="bad_token", actor_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed token")

    if not _USERNAME_RE.match(payload.username or ""):
        _count(caller["key"], tmpl_key, "bad_username")
        await _audit(
            caller=caller["key"], template=tmpl_key, rcpt=str(payload.recipient),
            outcome="denied", reason="bad_username", actor_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed username")

    allowed, reason = await _check_and_count(caller["key"], str(payload.recipient))
    if not allowed:
        logger.error("[mail-relay] REFUSED: caller '%s' %s", caller["key"], reason)
        _count(caller["key"], tmpl_key, "rate_limited")
        await _audit(
            caller=caller["key"], template=tmpl_key, rcpt=str(payload.recipient),
            outcome="denied", reason=reason, actor_ip=client_ip,
        )
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if reason == "counter_unavailable"
            else status.HTTP_429_TOO_MANY_REQUESTS
        )
        raise HTTPException(status_code=code, detail=f"Mail relay refused: {reason}")

    # The link is built HERE, from the caller's own registered base URL plus the
    # opaque token. Nothing the caller sent is a URL (property 2).
    link = caller["base_url"] + spec["link_path"].format(token=payload.token)

    from agentvault_registry.email_utils import send_themed_email

    # §MAILIDENT: the parent renders this mail, but the mail is ABOUT the child —
    # so the child's allowlist identity overrides the parent's injected defaults
    # (registry_name/registry_ui_url), exactly like the link already did. The label
    # and base_url both come from OUR MAIL_RELAY_CALLERS config, never the wire.
    _caller_label = str(caller.get("label") or "").strip() or "TheProtocol"
    ok = await send_themed_email(
        subject=spec["subject"].format(registry=_caller_label),
        recipients=[str(payload.recipient)],
        template=tmpl_key,
        context={
            "username": payload.username,
            spec["link_var"]: link,
            "expiry_hours": payload.expiry_hours or spec["expiry_hours_default"],
            "registry_label": _caller_label,
            "registry_name": _caller_label,
            "registry_base_url": caller["base_url"],
            "registry_ui_url": caller["base_url"] + "/ui",
        },
        theme=spec["theme"],
    )

    _count(caller["key"], tmpl_key, "sent" if ok else "send_failed")
    await _audit(
        caller=caller["key"], template=tmpl_key, rcpt=str(payload.recipient),
        outcome="success" if ok else "failure",
        reason="" if ok else "smtp_send_failed", actor_ip=client_ip,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Relay accepted the request but the upstream send failed",
        )

    logger.info(
        "[mail-relay] sent template=%s on behalf of %s to %s",
        tmpl_key, caller["key"], _rcpt_hash(str(payload.recipient)),
    )
    return {"status": "accepted", "template": tmpl_key, "on_behalf_of": caller["label"]}
