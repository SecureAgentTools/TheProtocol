"""
account_deletion.py — User-initiated GDPR Art. 17 erasure (W2, 2026-05-09).

Replaces the prior "Account deletion is unavailable during the beta period"
placeholder in Settings → Danger Zone with a real, compliant flow.

Design rationale (locked decisions — see HANDOVER §3.A):
  • Anonymize-don't-hard-delete. § 147 AO (German Fiscal Code) requires
    10-year retention of financial records (`fiat_purchases`); the EventStore
    is immutable by architectural commitment. We keep the Developer row as
    an FK referent, wipe PII fields in-place, and move the buyer's email to
    an anonymized placeholder. Retention is honored for the legal-hold scope;
    erasure is honored for everything else.
  • State machine: NULL ≡ active → 'pending_deletion' (14-day cooling-off)
    → 'anonymized' (terminal). User can cancel during cooling-off; nothing
    irreversible happens during that window.
  • Required confirmations: typed `DELETE MY ACCOUNT` + password re-auth.
    Two-factor: cognitive + auth.
  • Forfeiture: liquid + staked AVT in agents owned by this dev → TEG
    treasury (via the existing /admin/treasury/receive admin endpoint
    used for slashing). The flow is recorded as `account_deletion_forfeit`
    in the audit trail. Buyer waives claim per § 13.5 (no fiat redemption).
  • Refusals (409 Conflict) for: pending fiat purchase, active dispute,
    federation operator with active downstream peers.

Endpoints (all under /api/v1/account/*):
  POST  /request-deletion   — auth: dev JWT, body: {password, confirmation}
  POST  /cancel-deletion    — auth: dev JWT (must be pending_deletion + within 14d)
  GET   /deletion-status    — auth: dev JWT — for Settings UI countdown
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..config import settings
from ..database import get_db
from ..email_utils import send_themed_email
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/account")


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

# Cooling-off window between request and anonymization. 14 days mirrors
# the EU consumer-protection withdrawal-right norm (§ 312g BGB). Tunable
# via env so a future operator could shorten it for tests; production
# default stays at 14d. Keep an integer for clean SQL interval arithmetic.
COOLING_OFF_DAYS = int(os.getenv("ACCOUNT_DELETION_COOLING_OFF_DAYS", "14"))

DELETION_STATUS_ACTIVE = None  # NULL in DB ≡ active (default)
DELETION_STATUS_PENDING = "pending_deletion"
DELETION_STATUS_ANONYMIZED = "anonymized"

CONFIRMATION_PHRASE = "DELETE MY ACCOUNT"


# ----------------------------------------------------------------------
# Request / response schemas
# ----------------------------------------------------------------------

class RequestDeletionBody(BaseModel):
    password: str = Field(
        ..., min_length=1, max_length=512,
        description="Current password — re-auth required for irreversible action."
    )
    confirmation: str = Field(
        ..., max_length=64,
        description=f"Must equal exactly: '{CONFIRMATION_PHRASE}'."
    )
    reason: Optional[str] = Field(
        None, max_length=500,
        description="Optional free-text reason; logged for our own analytics."
    )


class DeletionStatusResponse(BaseModel):
    deletion_status: Optional[str] = Field(
        None,
        description="None / null ≡ active. 'pending_deletion' during cooling-off.",
    )
    deletion_requested_at: Optional[str] = None
    anonymizes_at: Optional[str] = Field(
        None,
        description="ISO-8601 timestamp at which anonymization will run "
                    "(requested_at + COOLING_OFF_DAYS).",
    )
    cooling_off_days: int = Field(default=COOLING_OFF_DAYS)


class SimpleAck(BaseModel):
    ok: bool = True
    message: str


# ----------------------------------------------------------------------
# Helpers — TEG admin
# ----------------------------------------------------------------------

# §MONEY-R39 (2026-09-04) — a forfeiture whose drain moved no money must be a NUMBER, not a
# log line: the pre-R39 helper counted its failures into a report the next recreate erased.
try:
    from prometheus_client import Counter as _R39Counter
    ACCOUNT_DELETION_DRAIN_FAILURES = _R39Counter(
        "registry_account_deletion_drain_failures_total",
        "Account-deletion forfeitures whose treasury drain did not move money — the balance "
        "stays on a revoked agent of an anonymized developer (§MONEY-R39)",
        ["reason"],
    )
except Exception:  # noqa: BLE001 — metrics never break the money path
    ACCOUNT_DELETION_DRAIN_FAILURES = None


def _count_drain_failure(reason: str) -> None:
    try:
        if ACCOUNT_DELETION_DRAIN_FAILURES is not None:
            ACCOUNT_DELETION_DRAIN_FAILURES.labels(reason=reason).inc()
    except Exception:  # noqa: BLE001
        pass


def _forfeit_ref(deletion_id: str, agent_did: str) -> str:
    """The durable Idempotency-Key AND reference of one agent's forfeiture. The pre-R39 key
    shape, kept on purpose: a re-run after a partial anonymization must hit the same key and
    replay, never pay twice."""
    return f"acctdel-forfeit-{deletion_id}-{agent_did}"


def _owe_forfeiture(db: AsyncSession, agent_did: str, developer_id: Optional[int], amount: Decimal, deletion_id: str,
                    why: str, error: str) -> None:
    """§LEDGERGATE (V0599): a forfeiture that moved no money is OWED, in the anonymization's own session (the row commits
    with the anonymization or not at all); background_tasks/forfeiture_retry drains it with the same key."""
    db.add(models.ForfeitureOwed(
        id=_forfeit_ref(deletion_id, agent_did), agent_did=agent_did, developer_id=developer_id, deletion_id=deletion_id,
        amount=amount, reason=why or "teg_refused", last_error=(error or "")[:500],
    ))


async def _teg_drain_to_treasury(agent_did: str, total_avt: Decimal, deletion_id: str,
                                 word: Optional[dict] = None) -> bool:
    """Forfeit an agent's LIQUID AVT to the TEG treasury; True iff the money moved.

    §MONEY-R39 (2026-09-04): this used to open its OWN ``aiohttp.ClientSession()`` and POST an
    admin bearer to ``TEG_API_BASE_URL`` — which on every mainframe and operator names the
    ``ssl_verify_client on`` nginx-teg sidecar. With no SPIRE bundle and no client SVID that dial
    died ``CERTIFICATE_VERIFY_FAILED``; on the TEG's plain port the answer was 403 "mTLS identity
    required" (``TEG_MTLS_REQUIRED=true``), and the bearer it carried was the placeholder-shaped
    marker the TEG refuses since R26 anyway. Measured on frame-a: ONE ``AccountAnonymized`` ever,
    ``avt_forfeited "0"``, 1000 units stranded on a revoked agent. The rail had never moved money,
    and its "best-effort" contract hid that behind a returned False.

    It now rides the SAME mover the guild and contract escrow rails use —
    :func:`services.escrow.escrow_deposit` (httpx + ``get_httpx_verify()``: the SPIRE bundle plus
    the registry's own SVID through nginx-teg; the TEG resolves the mTLS identity first and never
    consults the bearer). The Idempotency-Key is the pre-R39 shape, so a re-run replays instead of
    paying twice. A failure is COUNTED and returned to the caller, never only logged.

    Still returns False rather than raising: anonymization is irreversibly time-bound and the
    GDPR clock must not stall on a TEG blip. The balance then stays on the (revoked) agent, the
    cycle is marked failed by the worker, and ``money_verify`` reports it as stranded.

    §LEDGERGATE (V0599): ``word``, when given, receives why the drain moved nothing (``why``: ledger_unavailable for the
    ledger gate's refusal, teg_refused for any other refusal, transport) and the error, for the owed forfeiture the
    anonymization then records (``_owe_forfeiture``); background_tasks/forfeiture_retry drains it with this same key.
    """
    if total_avt <= Decimal("0"):
        return True
    from ..services.escrow import EscrowError, escrow_deposit  # lazy: avoids an import cycle
    ref = _forfeit_ref(deletion_id, agent_did)
    try:
        await escrow_deposit(agent_did, total_avt, ref, reason="account_deletion_forfeit")
        return True
    except EscrowError as exc:
        logger.warning(
            "[AccountDeletion] TEG drain %s refused → %s: %s (balance stays on the revoked agent until the owed "
            "forfeiture is drained)", agent_did, exc.status_code, exc.message,
        )
        _count_drain_failure("teg_refused")
        if word is not None:
            from ..services.ledger_unavailable import refusal_from_error
            word.update(why="ledger_unavailable" if refusal_from_error(exc) is not None else "teg_refused",
                        error=f"{exc.status_code}: {exc.message}")
        return False
    except Exception as exc:  # noqa: BLE001 — the transport class: TLS, DNS, timeout
        logger.warning(
            "[AccountDeletion] TEG drain %s transport error: %s (balance stays on the revoked agent until the owed "
            "forfeiture is drained)", agent_did, exc,
        )
        _count_drain_failure("transport")
        if word is not None:
            word.update(why="transport", error=f"{type(exc).__name__}: {exc}")
        return False


# ----------------------------------------------------------------------
# Helpers — gating checks (refusals)
# ----------------------------------------------------------------------

async def _has_pending_fiat_purchase(db: AsyncSession, dev_id: int) -> bool:
    """A purchase row in 'pending' state — Stripe webhook hasn't resolved yet."""
    res = await db.execute(
        select(models.FiatPurchase.id)
        .where(models.FiatPurchase.developer_id == dev_id)
        .where(models.FiatPurchase.status == models.FiatPurchaseStatus.PENDING.value)
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


async def _has_active_dispute(db: AsyncSession, dev_id: int) -> bool:
    """Active = OPEN or VOTING. Match against agents owned by this developer."""
    agent_dids = (await db.execute(
        select(models.Agent.did).where(models.Agent.creator_developer_id == dev_id)
    )).scalars().all()
    if not agent_dids:
        return False
    res = await db.execute(
        select(models.Dispute.id)
        .where(models.Dispute.status.in_(("OPEN", "VOTING")))
        .where(
            (models.Dispute.complainant_did.in_(agent_dids))
            | (models.Dispute.defendant_did.in_(agent_dids))
        )
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


async def _is_federation_operator_with_downstream(db: AsyncSession, dev: models.Developer) -> bool:
    """Federation operator with active peers depending on them. Refusal branch."""
    if not getattr(dev, "is_federation_operator", False):
        return False
    res = await db.execute(
        select(models.PeerRegistry.id)
        .where(models.PeerRegistry.owner_developer_id == dev.id)
        .where(models.PeerRegistry.status == "ACTIVE")
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@router.post(
    "/request-deletion",
    response_model=SimpleAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request deletion of the caller's account",
)
async def request_deletion(
    body: RequestDeletionBody,
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Transition `active → pending_deletion`. 14-day cooling-off applies.

    Refuses (409) when:
      • Caller has a pending Stripe fiat purchase (Stripe webhook
        hasn't fired yet: wait for resolution).
      • Caller has an active dispute (OPEN/VOTING).
      • Caller is a federation operator with at least one ACTIVE peer.

    Idempotent on `pending_deletion`: a second request while pending
    returns 200 with a no-op ack.
    """
    # Idempotency: already pending → no-op
    if current_developer.deletion_status == DELETION_STATUS_PENDING:
        return SimpleAck(message="Account already scheduled for deletion.")

    # Already anonymized → cannot reach this endpoint without a valid JWT,
    # which the anonymized password wipe should make impossible. Defensive:
    if current_developer.deletion_status == DELETION_STATUS_ANONYMIZED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account already anonymized.")

    # Confirmation phrase must match exactly. Compared with constant-time
    # for symmetry, though the phrase isn't a secret — the password is.
    #
    # §pass73.1 task H finding (2026-05-26): secrets.compare_digest raises
    # TypeError on non-ASCII strings. Fuzz harness submitted "✓✗▶♥" as the
    # confirmation phrase and triggered a 500. Encoding to bytes first lets
    # compare_digest handle any unicode input safely (still constant-time,
    # still mismatch-on-non-ASCII since CONFIRMATION_PHRASE is plain ASCII).
    if not secrets.compare_digest(
        (body.confirmation or "").strip().encode("utf-8"),
        CONFIRMATION_PHRASE.encode("utf-8"),
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Confirmation phrase mismatch — type exactly: '{CONFIRMATION_PHRASE}'.",
        )

    # Password re-auth.
    if not security.verify_password(body.password, current_developer.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid password.",
        )

    # Refusal gates.
    if await _has_pending_fiat_purchase(db, current_developer.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You have a fiat purchase still pending payment confirmation. "
            "Wait for the purchase to settle (or fail) and try again.",
        )

    if await _has_active_dispute(db, current_developer.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You have an active dispute. Disputes must be resolved before "
            "an account can be deleted.",
        )

    if await _is_federation_operator_with_downstream(db, current_developer):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are a federation operator with active peer registries. "
            "Transfer your operator role or wait for downstream peers to "
            "deregister before deleting your account.",
        )

    # All clear — flip the state. Capture the email for the final
    # anonymization-confirmation email (we'll need a "last known good"
    # address since the Developer row's email gets wiped at anonymize time).
    requested_at = datetime.now(timezone.utc)
    last_known_email = current_developer.email
    current_developer.deletion_status = DELETION_STATUS_PENDING
    current_developer.deletion_requested_at = requested_at
    await db.commit()

    anonymizes_at = requested_at + timedelta(days=COOLING_OFF_DAYS)

    # Confirmation email — not blocking; we ack the user even if SMTP is down.
    email_ctx = {
        "developer_id": current_developer.id,
        "developer_name": current_developer.name,
        "developer_email": last_known_email,
        "deletion_requested_at": requested_at.strftime("%B %d, %Y %H:%M UTC"),
        "anonymizes_at_iso": anonymizes_at.isoformat(),
        "anonymizes_at_human": anonymizes_at.strftime("%B %d, %Y"),
        "cooling_off_days": COOLING_OFF_DAYS,
        "cancel_url": f"{str(settings.BASE_URL).rstrip('/')}/ui#/settings?tab=security",
        "reason": body.reason or "",
    }
    try:
        await send_themed_email(
            subject=f"Account deletion scheduled for {anonymizes_at.strftime('%B %d')}",
            recipients=[last_known_email],
            template="account_deletion_requested",
            context=email_ctx,
            theme="sovereign",
        )
    except Exception as exc:
        logger.warning("[AccountDeletion] requested-email send failed: %s", exc)

    # Audit event — emitted from the registry per the project's emission policy.
    try:
        emitter = get_event_emitter()
        if emitter:
            asyncio.create_task(emitter.emit(
                event_type="AccountDeletionRequested",
                aggregate_id=str(current_developer.id),
                data={
                    "developer_id": current_developer.id,
                    "deletion_requested_at": requested_at.isoformat(),
                    "anonymizes_at": anonymizes_at.isoformat(),
                    "cooling_off_days": COOLING_OFF_DAYS,
                },
            ))
    except Exception as exc:
        logger.warning("[AccountDeletion] emit AccountDeletionRequested failed: %s", exc)

    logger.info(
        "[AccountDeletion] dev_id=%s requested deletion at %s; anonymize at %s",
        current_developer.id, requested_at.isoformat(), anonymizes_at.isoformat(),
    )

    return SimpleAck(message=f"Account scheduled for anonymization on {anonymizes_at.strftime('%B %d, %Y')}. Cancel within {COOLING_OFF_DAYS} days to keep your account.")


@router.post(
    "/cancel-deletion",
    response_model=SimpleAck,
    summary="Cancel a pending account deletion (must be within cooling-off)",
)
async def cancel_deletion(
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    if current_developer.deletion_status != DELETION_STATUS_PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Account is not currently scheduled for deletion.",
        )
    if current_developer.deletion_requested_at:
        anonymizes_at = current_developer.deletion_requested_at + timedelta(days=COOLING_OFF_DAYS)
        if datetime.now(timezone.utc) > anonymizes_at:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Cooling-off window has expired. Anonymization will run in the "
                "next worker pass. Contact support if this is in error.",
            )

    current_developer.deletion_status = DELETION_STATUS_ACTIVE
    current_developer.deletion_requested_at = None
    await db.commit()

    logger.info("[AccountDeletion] dev_id=%s cancelled deletion", current_developer.id)
    return SimpleAck(message="Account deletion cancelled. Welcome back.")


@router.get(
    "/deletion-status",
    response_model=DeletionStatusResponse,
    summary="Get the caller's account-deletion state (for Settings UI)",
)
async def get_deletion_status(
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    requested_at_iso: Optional[str] = None
    anonymizes_at_iso: Optional[str] = None
    if current_developer.deletion_requested_at:
        requested_at_iso = current_developer.deletion_requested_at.isoformat()
        anonymizes_at_iso = (
            current_developer.deletion_requested_at + timedelta(days=COOLING_OFF_DAYS)
        ).isoformat()
    return DeletionStatusResponse(
        deletion_status=current_developer.deletion_status,
        deletion_requested_at=requested_at_iso,
        anonymizes_at=anonymizes_at_iso,
        cooling_off_days=COOLING_OFF_DAYS,
    )


# ----------------------------------------------------------------------
# Anonymization helper — called by the daily worker (and exposed for tests)
# ----------------------------------------------------------------------

# Sentinel placeholder for the wiped fields. We intentionally avoid PII
# patterns (the auto-created email is well-formed but unmistakably
# anonymized; the password hash is invalid for bcrypt verify).
ANONYMIZED_PASSWORD_SENTINEL = "anonymized:account-disabled"


async def anonymize_developer(
    db: AsyncSession,
    developer: models.Developer,
    *,
    actor_email_for_audit: Optional[str] = None,
) -> dict:
    """Wipe PII on `developer` + cascade through agents/cards/api_keys/webhooks.

    Caller is responsible for committing the session (this function flushes
    intermediate changes to the same session). Returns a small report dict
    for logging.

    Order of operations (designed for partial-failure tolerance — each
    step is idempotent and safe to re-run):

      1. Capture last-known-good email + ID for the final email.
      2. Drain liquid + staked AVT in agents → TEG treasury (best-effort).
      3. Hard-delete API keys + webhooks (no audit value).
      4. Soft-revoke agents: status=revoked, deleted_at=now, hashed_client_secret
         wiped to a known-bad sentinel.
      5. Redact agent_cards: is_active=false, card_data → minimal {did,
         capabilities} subset (PII-free).
      6. Null PII fields on the Developer row in-place + flip status to anonymized.
      7. Send final confirmation email to the captured last-known-good address.
      8. Emit AccountAnonymized event.
    """
    deletion_id = str(uuid.uuid4())
    last_known_email = developer.email
    developer_id = developer.id

    report: dict = {
        "developer_id": developer_id,
        "deletion_id": deletion_id,
        "last_known_email": last_known_email,
        "agents_revoked": 0,
        "cards_redacted": 0,
        "api_keys_deleted": 0,
        "webhooks_deleted": 0,
        "webhook_deliveries_deleted": 0,
        "avt_forfeited": "0",
        # §MONEY-R15: staked balance is NOT forfeitable by this rail (see below).
        # Reported separately rather than folded into avt_forfeited, so the number
        # a person reads is the money that actually moved.
        "avt_staked_not_forfeited": "0",
        "teg_drain_failures": 0,
        # §LEDGERGATE (V0599): the failed drains recorded as owed (forfeitures_owed, in this transaction): the
        # forfeiture_retry worker drains them; teg_drain_failures stays the count of drains that moved no money.
        "teg_drain_owed": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    # Step 1+2 — Drain AVT from agents to TEG treasury.
    agents_res = await db.execute(
        select(models.Agent).where(models.Agent.creator_developer_id == developer_id)
    )
    agents = agents_res.scalars().all()
    total_forfeit = Decimal("0")
    total_staked_left = Decimal("0")
    for agent in agents:
        liquid = agent.liquid_balance or Decimal("0")
        staked = agent.staked_balance or Decimal("0")

        # §MONEY-R15 (2026-09-04). This used to request liquid + staked in ONE
        # call to /admin/treasury/receive. That endpoint validates against
        # `token_balance`, i.e. LIQUID only:
        #     if source.token_balance < request.amount: -> 400
        # so for any agent holding stake the drain was REFUSED and the deletion
        # forfeited NOTHING — not even the liquid part — while the report counted
        # a teg_drain_failure. The comment beside it already said "drains liquid
        # only"; the code asked for both. Measured on frame-a: 11 of 4,191 agents
        # hold stake, so the path was reachable and quietly wrong.
        #
        # Δ was never at risk: a refused call moves nothing.
        if liquid > Decimal("0"):
            drain_word: dict = {}
            ok = await _teg_drain_to_treasury(agent.did, liquid, deletion_id, word=drain_word)
            if ok:
                total_forfeit += liquid
            else:
                report["teg_drain_failures"] = int(report["teg_drain_failures"]) + 1
                _owe_forfeiture(db, agent.did, developer_id, liquid, deletion_id,
                                drain_word.get("why", ""), drain_word.get("error", ""))
                report["teg_drain_owed"] = int(report["teg_drain_owed"]) + 1

        # Staked is locked behind the unstake cooldown and this rail cannot move
        # it. With the agent's secret wiped nobody can unstake either, so it is
        # stranded rather than forfeited. Reported honestly under its own key
        # instead of being counted as money that moved. A TEG admin
        # "forfeit-staked" endpoint is the real answer and is not in scope here.
        if staked > Decimal("0"):
            total_staked_left += staked
            logger.warning(
                "[acct-del] agent %s holds %s staked that this rail cannot forfeit "
                "(locked behind the unstake cooldown; the credential is being wiped)",
                agent.did, staked,
            )
    report["avt_forfeited"] = str(total_forfeit)
    report["avt_staked_not_forfeited"] = str(total_staked_left)

    # Step 3 — Hard-delete api_keys + webhooks.
    api_keys_del = await db.execute(
        delete(models.DeveloperApiKey).where(
            models.DeveloperApiKey.developer_id == developer_id
        )
    )
    report["api_keys_deleted"] = api_keys_del.rowcount or 0

    # §MCPTEST30 (2026-10-06): the webhooks' deliveries first. webhook_deliveries.webhook_id has no ON DELETE
    # CASCADE, so ONE webhook that had ever delivered made this delete raise on the foreign key, and with it the
    # whole account deletion, which runs in this one transaction.
    deliveries_del = await db.execute(
        delete(models.WebhookDelivery).where(
            models.WebhookDelivery.webhook_id.in_(
                select(models.DeveloperWebhook.id).where(
                    models.DeveloperWebhook.developer_id == developer_id
                )
            )
        )
    )
    report["webhook_deliveries_deleted"] = deliveries_del.rowcount or 0
    webhooks_del = await db.execute(
        delete(models.DeveloperWebhook).where(
            models.DeveloperWebhook.developer_id == developer_id
        )
    )
    report["webhooks_deleted"] = webhooks_del.rowcount or 0

    # Step 4 — Soft-revoke agents.
    revoke_at = datetime.now(timezone.utc)
    for agent in agents:
        agent.status = "revoked"
        agent.deleted_at = revoke_at
        # Wipe the bcrypt hash so the secret can never validate. Any
        # impostor flow that captured the cleartext secret is also locked
        # out at the model layer because /auth/agent/token compares against
        # this hash.
        agent.hashed_client_secret = ANONYMIZED_PASSWORD_SENTINEL
        report["agents_revoked"] = int(report["agents_revoked"]) + 1

    # Step 5 — Redact agent_cards. Keep DID + capabilities (non-PII protocol
    # surface), wipe everything else. Mark inactive.
    cards_res = await db.execute(
        select(models.AgentCard).where(models.AgentCard.developer_id == developer_id)
    )
    for card in cards_res.scalars().all():
        original = card.card_data or {}
        redacted = {
            "did": original.get("did") or original.get("agent_did"),
            "capabilities": original.get("capabilities", []),
            "anonymized": True,
        }
        card.card_data = redacted
        card.name = f"deleted-card-{card.id}"
        card.description = None
        card.is_active = False
        report["cards_redacted"] = int(report["cards_redacted"]) + 1

    # Step 6 — Wipe Developer PII in-place. The row stays so FKs hold.
    # Note on the email format: we use a sub-domain of theprotocol.cloud
    # (not `.invalid` — RFC 6761 reserved, rejected by pydantic.EmailStr
    # in response models) so the anonymized email is well-formed AND under
    # the operator's control (no risk of accidental delivery — there's no
    # MX record on this sub-domain).
    anon_id = str(uuid.uuid4())
    anonymized_email = f"deleted-{anon_id}@anonymized.theprotocol.cloud"
    anonymized_name = f"deleted-{developer_id}"

    developer.email = anonymized_email
    developer.name = anonymized_name
    developer.hashed_password = ANONYMIZED_PASSWORD_SENTINEL
    developer.email_verification_token = None
    developer.password_reset_token = None
    developer.password_reset_token_expires = None
    developer.hashed_recovery_key = None

    # Profile / cosmetic fields → null. Flare visuals are tied to the
    # buyer; the auditable financial trail (fiat_purchases, EventStore
    # tokens-issued from FiatPurchaseSettled) preserves the AVT motion.
    developer.display_name = None
    developer.bio = None
    developer.avatar_url = None
    developer.website_url = None
    developer.github_url = None
    developer.twitter_handle = None
    developer.company = None
    developer.timezone = None
    developer.location_label = None
    developer.latitude = None
    developer.longitude = None
    developer.notification_prefs = None

    # Flare cosmetic — anonymizes the public face but the underlying
    # FiatPurchase row keeps the financial trail.
    developer.flare_display_name = None
    developer.flare_tagline = None
    developer.flare_logo_url = None
    developer.flare_link_url = None
    developer.flare_cause = None
    developer.flare_accent_color = None

    # 2FA secrets / trusted devices.
    developer.totp_secret = None
    developer.two_fa_enabled = False
    developer.backup_codes = None
    developer.two_fa_verified_at = None
    developer.trusted_devices = None

    # Demote admin. No way an anonymized account holds operator privilege.
    developer.is_admin = False
    developer.admin_treasury = False
    developer.admin_support = False
    developer.admin_enforcement = False
    developer.admin_federation = False
    developer.admin_platform = False

    # Federation operator status — clear (we already verified there are no
    # active downstream peers at request-time; suspended/inactive peers
    # simply stay where they are with their own audit trail).
    developer.is_federation_operator = False
    developer.federation_operator_status = None

    developer.deletion_status = DELETION_STATUS_ANONYMIZED
    developer.anonymized_at = datetime.now(timezone.utc)

    # Step 7 — Final email to the captured last-known-good address.
    try:
        await send_themed_email(
            subject="Your TheProtocol account has been anonymized",
            recipients=[last_known_email],
            template="account_anonymized",
            context={
                "developer_id": developer_id,
                "anonymized_at": developer.anonymized_at.strftime("%B %d, %Y %H:%M UTC"),
                "agents_revoked": report["agents_revoked"],
                "avt_forfeited": str(total_forfeit),
                "deletion_id": deletion_id,
            },
            theme="sovereign",
        )
    except Exception as exc:
        logger.warning("[AccountDeletion] anonymized-email send failed: %s", exc)

    # Step 8 — Audit event.
    try:
        emitter = get_event_emitter()
        if emitter:
            asyncio.create_task(emitter.emit(
                event_type="AccountAnonymized",
                aggregate_id=str(developer_id),
                data={
                    "developer_id": developer_id,
                    "deletion_id": deletion_id,
                    "anonymized_at": developer.anonymized_at.isoformat(),
                    "agents_revoked": report["agents_revoked"],
                    "cards_redacted": report["cards_redacted"],
                    "api_keys_deleted": report["api_keys_deleted"],
                    "webhooks_deleted": report["webhooks_deleted"],
                    "avt_forfeited": str(total_forfeit),
                    # §MONEY-R39: the two numbers that turned "the money was forfeited" into
                    # a checkable claim. Absent from the payload until 2026-09-04, which is
                    # why a drain that never worked read as an ordinary anonymization.
                    "avt_staked_not_forfeited": report["avt_staked_not_forfeited"],
                    "teg_drain_failures": int(report["teg_drain_failures"]),
                    "teg_drain_owed": int(report["teg_drain_owed"]),
                    "actor_email_for_audit": actor_email_for_audit or "system",
                },
            ))
    except Exception as exc:
        logger.warning("[AccountDeletion] emit AccountAnonymized failed: %s", exc)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "[AccountDeletion] dev_id=%s anonymized — %s",
        developer_id, report,
    )
    return report
