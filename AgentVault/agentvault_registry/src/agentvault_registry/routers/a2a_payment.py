"""
A2A Payment Authorization System — f045

Registry-issued payment tokens that enforce payment before A2A service delivery.
Agents verify tokens via SDK middleware; settlement happens through TEG.

Endpoints:
  POST /api/v1/a2a-payment/authorize      — Get a payment token (agent JWT)
  POST /api/v1/a2a-payment/verify          — Verify a token (no auth — agents call this)
  POST /api/v1/a2a-payment/settle          — Settle after task completion (agent JWT)
  POST /api/v1/a2a-payment/release         — Cancel an unused token (agent JWT)
  GET  /api/v1/a2a-payment/my-tokens       — List caller's tokens (agent JWT)
"""
import asyncio
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status, Query, Security
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, AsyncSessionLocal
from ..models import Agent, A2APaymentAuthorization, A2APaymentStatus
from .utils import get_current_agent
from agentvault_registry.security import require_agent_permission, enforce_agent_spend  # IRONKEY
from ..event_emitter import get_event_emitter, emit_or_report
from ..config import settings
from agentvault_registry.services import reputation_bond as _rb
from agentvault_registry.services import enforcement_propagation as _ep  # §ENFPROP

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Prometheus instrumentation (added 2026-04-30 — Grafana A2A funnel dash)
# ----------------------------------------------------------------------
import os as _os_a2a
try:
    from prometheus_client import Counter as _A2ACounter

    A2A_PAYMENT_AUTHORIZED_TOTAL = _A2ACounter(
        "a2a_payment_authorized_total",
        "A2A payment tokens authorized (TEG funds reserved)",
        labelnames=["registry"],
    )
    A2A_PAYMENT_VERIFIED_TOTAL = _A2ACounter(
        "a2a_payment_verified_total",
        "A2A payment token verifications by outcome",
        labelnames=["outcome", "registry"],  # outcome: valid|invalid|wrong_target|expired
    )
    A2A_PAYMENT_SETTLED_TOTAL = _A2ACounter(
        "a2a_payment_settled_total",
        "A2A payment settlements by result",
        labelnames=["result", "registry"],  # result: success|failed
    )
    A2A_PAYMENT_RELEASED_TOTAL = _A2ACounter(
        "a2a_payment_released_total",
        "A2A payment tokens explicitly released by caller",
        labelnames=["registry"],
    )
    A2A_BUY_LEG_FAILED_TOTAL = _A2ACounter(
        "a2a_buy_leg_failed_total",
        "buy_service best-effort legs that failed AFTER the call (§S4 pass 3): the release of a reservation the caller never used. Money is not lost (an unreleased token expires and the expiry worker releases it); a rising rate is a self-call path breaking silently",
        labelnames=["leg", "registry"],  # leg: release_by_id|release_via_settle
    )
    _A2A_PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _A2A_PROM_AVAILABLE = False
    A2A_PAYMENT_AUTHORIZED_TOTAL = None  # type: ignore[assignment]
    A2A_PAYMENT_VERIFIED_TOTAL = None  # type: ignore[assignment]
    A2A_PAYMENT_SETTLED_TOTAL = None  # type: ignore[assignment]
    A2A_PAYMENT_RELEASED_TOTAL = None  # type: ignore[assignment]
    A2A_BUY_LEG_FAILED_TOTAL = None  # type: ignore[assignment]


def _a2a_registry_label() -> str:
    return _os_a2a.getenv("REGISTRY_NAME", "registry")


# Shared httpx client for settlement calls (avoids TCP churn under concurrent load)
_settle_client: Optional[httpx.AsyncClient] = None

def _get_settle_client() -> httpx.AsyncClient:
    global _settle_client
    if _settle_client is None or _settle_client.is_closed:
        _settle_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=httpx.Timeout(35.0, connect=5.0),
        )
    return _settle_client

router = APIRouter(prefix="/api/v1/a2a-payment", tags=["A2A Payment"])

# ── Constants ─────────────────────────────────────────────────────────────

TOKEN_PREFIX = "apt_"  # a2a payment token
DEFAULT_TTL_SECONDS = 900  # 15 minutes
MAX_TTL_SECONDS = 3600  # 1 hour
MAX_PENDING_PER_CALLER = 20
_SIX_PLACES = Decimal("0.000001")  # a token's amount: a2a_payment_authorizations.amount is Numeric(30, 6)


# ── Schemas ───────────────────────────────────────────────────────────────

class AuthorizeRequest(BaseModel):
    target_agent_did: str = Field(..., description="DID of the agent to pay")
    amount: str = Field(..., description="Amount to authorize, in the unit this registry settles in (its frame's unit, ECU on the EU frame; every answer names it in `currency`)")
    contract_id: Optional[int] = Field(None, description="Optional contract ID for contract-bound payments")
    ttl_seconds: int = Field(DEFAULT_TTL_SECONDS, ge=60, le=MAX_TTL_SECONDS)

    @field_validator("amount")
    @classmethod
    def _amount_is_a_finite_number(cls, v: str) -> str:
        # §MCPTEST30 (V0525, 2026-10-01): the route parsed the string with Decimal() and compared it, so "NaN" raised
        # InvalidOperation at `amount <= 0` and a word raised at the parse: both answered 500 (round 8 on sbx-alpha, the
        # amount_bounds probe). The caller's 422 now, before the route; the route's own 400 for a non-positive amount
        # stays. V0522 did the same for the nine TEG transfer validators.
        try:
            val = Decimal(str(v))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Amount must be a valid number")
        if not val.is_finite():
            raise ValueError("Amount must be a finite number")
        return v


# B4 (2026-06-03): a payment token is denominated in its OWNING frame's settlement
# currency (FRAME_CURRENCY env — A/B=AVT, C=BVT). Surfaced as a DERIVED response
# field — no migration (currency is not a per-record variable today; same frame-
# derived pattern as B7-local / teg_integration._local_frame_currency). FastAPI's
# response_model coercion applies this default even to dict-style returns, so the
# field appears on every authorize/verify/settle response. The FE labels the amount.
_FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"


class AuthorizeResponse(BaseModel):
    token: str
    token_id: str
    amount: str
    currency: str = _FRAME_CCY
    target_agent_did: str
    expires_at: str
    contract_id: Optional[int] = None
    # §BUYSERVICE: WHO minted this token. A foreign agent verifies at the ISSUER
    # (X-Payment-Issuer); without it it asks its own registry, which never saw the
    # token and answers "Token not found" — the 402 every cross-registry buyer hit.
    # Returning it here means a caller never has to know to construct it.
    issuer: Optional[str] = None
    issuer_header: str = "X-Payment-Issuer"


class VerifyRequest(BaseModel):
    token: str = Field(..., description="The payment token to verify")
    target_agent_did: Optional[str] = Field(None, description="Expected target DID (optional extra check)")


class VerifyResponse(BaseModel):
    valid: bool
    token_id: Optional[str] = None
    caller_did: Optional[str] = None
    target_agent_did: Optional[str] = None
    amount: Optional[str] = None
    currency: str = _FRAME_CCY
    contract_id: Optional[int] = None
    expires_at: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None


class SettleRequest(BaseModel):
    token: str = Field(..., description="The payment token to settle")
    task_id: Optional[str] = Field(None, description="A2A task ID for audit trail")
    success: bool = Field(True, description="Whether the task completed successfully")


class SettleResponse(BaseModel):
    token_id: str
    status: str
    settlement_tx_id: Optional[str] = None
    amount: str
    currency: str = _FRAME_CCY
    caller_did: str
    target_agent_did: str


class TokenListItem(BaseModel):
    token_id: str
    target_agent_did: str
    amount: str
    currency: str = _FRAME_CCY
    status: str
    contract_id: Optional[int] = None
    created_at: str
    expires_at: str
    settled_at: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_hex(32)}"


async def _get_agent_balance(agent: Agent) -> Decimal:
    """Get agent's liquid balance from the registry DB (synced from TEG)."""
    return Decimal(str(agent.liquid_balance or 0))


async def _local_settlement_fee(db: AsyncSession, purse_did: str, target_did: str, amount: Decimal) -> Decimal:
    """§DOCSFIX CB-440: the intra-registry fee a settlement to `target_did` charges the paying wallet on top of
    `amount` (/teg/transfer asks the same fee service), or 0 for a payee on another registry, whose registry keeps the
    cross-registry fee out of the amount. An estimate (the fee is velocity-scaled when the settlement runs); a fee that
    cannot be read is left out, and the settlement's own transfer stays the authority."""
    try:
        if not await _is_local_agent(db, target_did):
            return Decimal("0")
        from ..services.transaction_fee_service import get_transaction_fee_service
        fee, _rate = await get_transaction_fee_service().get_fee_for_transfer(
            db=db, sender_did=purse_did, transfer_amount=amount)
        return Decimal(str(fee or 0))
    except Exception as exc:  # noqa: BLE001 — admission falls back to the amount alone, as before this estimate
        logger.warning("[A2APay] fee estimate unavailable at authorize (%s); admitting on the amount alone", exc)
        return Decimal("0")


# ── §TWOAGENT G5 (2026-09-23): a walletless (anchored) hand pays for a service from the wallet it spends from ──────
# Measured on EU (finding 32): a spawned child with its birth token asked to authorize 2.04 ECU and was told
# "Insufficient balance: 0 ECU available" while its parent held 749; `authorize` read the CALLER's balance and
# `settle` transferred with the caller's JWT, and neither asked the spawn anchor that /teg/send, contracts and the
# exchange already honour. The shape here:
#   * authorize is the whole admission: the child's own caveats (enforce_agent_spend on the ACTING child, which also
#     debits the birth token's budget), then the PURSE's balance, and the purse's own gates for the rail settle
#     will use (its transfer permission, its spend policy, its org ceiling), asked read-only so a refusal comes
#     BEFORE the service is delivered (§BUYSERVICE: a provider that delivered must be paid);
#   * settle moves exactly the admitted amount AS THE PURSE (a registry-minted token for the purse whose `act`
#     names the service and the hand), because forwarding the birth token would debit its budget a second time and
#     refuse the settlement of delivered work.
# The purse is only ever reached through the hand's own BIRTH token (the `anchored` caveat cannot be written by
# issue or attenuate, `_caveats_dict` whitelists), so authorize and settle resolve the same wallet.

async def _payer_purse(db: AsyncSession, current_agent: Agent, request: Request):
    """``(purse_agent, purse_did)`` — the acting agent itself unless it is an anchored hand presenting its birth
    token (spawn_anchor's rule; fail-closed to self, never raises)."""
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    return await resolve_spend_purse_agent(db, current_agent, request)


async def _settle_permission_refusal(db: AsyncSession, payer_did: str, target_did: str,
                                     act_principal: Optional[str] = None) -> Optional[str]:
    """CB-457: would the paying wallet's settlement transfer pass its permission gate? ``None`` = yes; otherwise the
    reason, in words. The settlement is an ordinary transfer from the paying wallet: `teg.transfer` to a payee on this
    registry, `teg.transfer_xreg` to one on another (the split _settle_via_transfer and /teg/send make). Asked for every
    payer at authorize, so a payment the settlement would refuse is refused before the service works. Only under RBAC
    enforce, the only mode in which the transfer rails refuse. ``act_principal``: the on-behalf-of principal of the
    caller's token (its delegated grants count at settle too)."""
    from agentvault_registry.agent_authz import agent_rbac_mode, resolve_agent_permissions
    if agent_rbac_mode() != "enforce":
        return None
    local = await _is_local_agent(db, target_did)
    need = "teg.transfer" if local else "teg.transfer_xreg"
    try:
        perms = await resolve_agent_permissions(db, payer_did, act_principal)
    except Exception as exc:  # noqa: BLE001 — cannot read it: say so rather than admit a payment that may not settle
        logger.warning("[A2APay] payer permission read failed for %s: %r", payer_did, exc)
        return "its permissions could not be read"
    if need not in perms:
        return f"it does not hold {need}, which the settlement to this agent needs"
    return None


async def _purse_refusal(db: AsyncSession, purse_did: str, amount: Decimal, target_did: str) -> Optional[str]:
    """Would the purse's own settlement go through? ``None`` = yes; otherwise the reason, in words. Read-only: the
    policy verdict is ``check_spend_policy`` (not ``enforce_agent_spend``, which would consume an approval here that
    settle then asks for again). Only under RBAC enforce, the only mode in which the settle rail refuses."""
    from agentvault_registry.agent_authz import agent_rbac_mode, check_spend_policy
    if agent_rbac_mode() != "enforce":
        return None
    refusal = await _settle_permission_refusal(db, purse_did, target_did)
    if refusal:
        return refusal
    local = await _is_local_agent(db, target_did)
    allowed, reason = await check_spend_policy(db, purse_did, amount, counterparty_did=target_did,
                                               same_registry=local)
    if not allowed:
        return f"its own spend policy refuses it ({reason})"
    from agentvault_registry.services.org_policy import get_org_settings, org_spend_ceiling
    try:
        ceiling = org_spend_ceiling(await get_org_settings(db, purse_did))
    except Exception as exc:  # noqa: BLE001 — cannot read it: say so, as for the permissions above (§SECFIX D6-491)
        logger.warning("[A2APay] purse org settings read failed for %s: %r", purse_did, exc)
        return "its organization's spend ceiling could not be read"
    if ceiling is not None and amount > Decimal(str(ceiling)):
        return f"its organization's spend ceiling ({ceiling}) is below {amount}"
    return None


def _purse_settle_bearer(purse_agent: Agent, hand_did: str) -> str:
    """A short-lived token for the PURSE, used once for the settlement's inner transfer and never returned. The
    ``act`` claim records why the registry acts as it (attribution, not extra authority — the exchange gateway's
    and the canary hub's pattern); ``service:`` is no agent principal, so no delegated grant can ride it."""
    from datetime import timedelta as _td
    from agentvault_registry.security import create_access_token
    return create_access_token(
        {"sub": purse_agent.did, "type": "agent", "agent_id": str(purse_agent.id),
         "act": {"sub": "service:a2a-settle", "reason": "anchored-hand", "hand": hand_did}},
        expires_delta=_td(minutes=10),
    )


def _caller_headers(request: Request, caller_jwt: str) -> Dict[str, str]:
    """The caller's credentials for a call this registry makes ON the caller's behalf (the /buy rail's authorize,
    release and settle): the bearer, and the capability token when one was presented. Without the latter a walletless
    hand passed /buy's own gate and was refused at every inner step (/teg/send forwards it the same way)."""
    h = {"Authorization": f"Bearer {caller_jwt}"}
    cap = request.headers.get("x-capability-token")
    if cap:
        h["X-Capability-Token"] = cap
    return h


# §BUYSERVICE — this registry's outside address, for X-Payment-Issuer.
_SELF_BASE = os.getenv("REGISTRY_SELF_URL", "http://localhost:8000").rstrip("/")


def _issuer_url(request: Request) -> str:
    """The URL a foreign agent should verify this token against.

    Must be the PUBLIC address (the loopback-rejecting helper), never
    REGISTRY_SELF_URL: an agent on another host cannot verify at our localhost,
    and the baked `http://localhost:8000` default is truthy enough to look fine
    right up until the purchase fails (§OPGUIDE-6).
    """
    try:
        from ..core.public_url import public_base_url
        u = (public_base_url(request) or "").strip()
        # ⚠ public_base_url loopback-rejects only its BASE_URL branch; its final
        # fallback is the REQUEST's own Host header, which for a loopback purchase
        # is "http://localhost:8000" — truthy, and meaningless to a foreign agent.
        # Guard it here or the card fallback below can never be reached.
        if u and "localhost" not in u and "127.0.0.1" not in u:
            return u.rstrip("/")
    except Exception:  # noqa: BLE001
        pass
    # 🔴 A purchase that ORIGINATES inside this registry dials loopback (the chat's
    # /call posts to http://localhost:8000/a2a-payment/buy), so the request-derived
    # helper has nothing to work from and correctly refuses to guess — leaving the
    # header off entirely. A foreign agent then falls back to ITS OWN registry,
    # where our token was never minted, and answers "Token not found". Measured
    # 2026-08-27 on op-berlin: authorize 200, agent 402, reservation released, so
    # nobody was ever charged — the call simply could not work from a cloud-op,
    # which is why this only ever worked through the §SHOWCASEFED relay.
    # The card already publishes the right answer; use the SAME source, so the
    # issuer we send can never disagree with the public_url the agents trust.
    try:
        from ..services.registry_card_builder import _public_web_url
        return (_public_web_url() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


async def _is_local_agent(db: AsyncSession, agent_did: str) -> bool:
    """Check if an agent DID exists in the local registry DB."""
    result = await db.execute(select(Agent.id).where(Agent.did == agent_did).limit(1))
    return result.scalar_one_or_none() is not None


def _failed_answer(data) -> Optional[str]:
    """§DOCSFIX D6-436: the reason a transfer's 200 answer gives when its status says it failed, else None. The
    cross-registry transfer answers a transfer the TEG refused with HTTP 200 and "status": "failed", and /teg/send passes
    that status on (its inner answer under `detail`): such an answer is no payment."""
    if not isinstance(data, dict) or str(data.get("status") or "").strip().lower() != "failed":
        return None
    inner = data.get("detail") if isinstance(data.get("detail"), dict) else data
    return str(inner.get("error_message") or "the transfer answered status failed")


def _settlement_key(token_id: str, token_hash: str) -> str:
    """§DOCSFIX D6-437 / CB-442: the Idempotency-Key of a token's settlement transfer, one per token. The transfer
    endpoint keeps its answer under it (services/idempotency/cache.run_kept), so the stale-settlement sweep
    (background_tasks/a2a_payment_expiry) can ask whether the transfer completed before it calls the token failed.

    §DOCSFIX review: the key carries a digest of the token's hash, not the token id alone. The id is public (the
    A2APaymentAuthorized event carries it, and a frame's public event feed shows it), and a transfer endpoint keeps a key
    for whoever sends it first: a key built from the id let anyone occupy it with a transfer of their own, so the
    settlement was refused as a different request (and failed), and the sweep could read that stranger's transfer as the
    payment. Only the registry and the holders of the plain token can derive the digest."""
    secret = hashlib.sha256(f"a2a-settle|{token_hash}".encode()).hexdigest()[:32]
    return f"a2a-settle-{token_id}-{secret}"


def _settlement_scope(local: bool) -> str:
    """The idempotency scope the settlement transfer keeps its answer under: /teg/transfer's for a payee on this
    registry, /teg/cross-registry-transfer's otherwise (/teg/send forwards the key to the same endpoint for the same
    payee: services/smart_transfer.derive_route decides locality from the agents table, as _is_local_agent does)."""
    return "teg.transfer" if local else "teg.cross-registry-transfer"


def _settlement_message(token_id: str, task_id: Optional[str]) -> str:
    """The message a token's settlement transfer carries (settle_payment). The transfer endpoint keeps its record of
    the transfer under a hash of the request body, this message included, so the stale-settlement sweep rebuilds it
    from the token's row (its id, and the task id the settlement that claimed the token wrote) to know which record
    under the settlement key is the settlement's own (_settlement_record_bodies)."""
    return f"A2A service payment (token={token_id[:8]}, task={task_id or 'n/a'})"


def _settlement_record_bodies(receiver_did: str, amount, message: str, local: bool) -> list:
    """The bodies the transfer endpoint keeps a token's settlement record under (its idempotency body: the request
    model's dump, and on the cross-registry endpoint the backend it ran with). _settle_via_transfer sends the payee,
    the amount and the message to /teg/transfer for a payee on this registry, else to /teg/cross-registry-transfer
    without a backend; through /teg/send (A2A_SETTLE_VIA_SMART_SEND) the same fields reach the same endpoint, a
    same-currency payee's with backend 2pc. A body the endpoint would have refused (so it kept no record of it) gives
    none. The sweep trusts a record under the settlement key only when it is one of these, kept for the payer's side:
    a record of another body under that key (the payer can derive the key) is not the settlement."""
    from pydantic import ValidationError
    from .teg_integration import CrossRegistryTransferRequest, TEGTransferRequest
    try:
        if local:
            return [TEGTransferRequest(receiver_agent_id=receiver_did, amount=str(amount),
                                       message=message).model_dump(mode="json")]
        base = CrossRegistryTransferRequest(receiver_did=receiver_did, amount=str(amount),
                                            message=message).model_dump(mode="json")
    except ValidationError:
        return []
    return [dict(base, backend=backend) for backend in (None, "2pc")]


async def _settle_via_transfer(
    caller_jwt: str, receiver_did: str, amount: Decimal,
    db: AsyncSession, message: str = "",
    contract_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> Optional[str]:
    """
    Route settlement through existing transfer endpoints.

    Local target  → /teg/transfer (intra-registry)
      Full pipeline: fee calc, atomic TEG, balance sync, EigenTrust, fee audit, events

    Remote target → /teg/cross-registry-transfer (cross-registry 2PC)
      Full pipeline: 2PC coordination, fee (0.5% receiver TEG), balance sync, events

    `idempotency_key` (the token's _settlement_key) rides the inner transfer, which keeps its answer under it.
    """
    headers = {"Authorization": f"Bearer {caller_jwt}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    # f060 convergence (2026-06-12, FLAG-GATED, default OFF): route settlement through
    # the unified smart-send dispatcher instead of picking the rail here. /teg/send
    # derives local/2pc/async/fx from the federated card cache — which ALSO makes
    # cross-CURRENCY a2a settlements (AVT<->BVT) possible for the first time. The
    # inner rails (and therefore fees/idempotency/events/licenses) are unchanged.
    _use_smart_send = (os.getenv("A2A_SETTLE_VIA_SMART_SEND", "").strip().lower()
                       in ("1", "true", "yes", "on"))
    if _use_smart_send:
        try:
            client = _get_settle_client()
            body = {"receiver_did": receiver_did, "amount": str(amount)}
            if message:
                body["message"] = message
            resp = await client.post(
                "http://localhost:8000/api/v1/teg/send",
                json=body,
                headers=headers,   # /teg/send forwards the Idempotency-Key to the inner endpoint
            )
            if resp.status_code == 200:
                data = resp.json()
                failed = _failed_answer(data)
                if failed is not None:
                    logger.error(f"[A2APay] /teg/send settlement failed (status failed): {failed[:300]}")
                    return None
                tx_id = data.get("transfer_id", "") or data.get("transaction_id", "")
                logger.info(
                    f"[A2APay] Settlement via /teg/send: method={data.get('method')} "
                    f"tx={tx_id} status={data.get('status')}"
                )
                return tx_id or None
            try:
                detail = resp.json().get("detail", resp.text[:200])
            except Exception:
                detail = resp.text[:200]
            logger.error(f"[A2APay] /teg/send settlement failed ({resp.status_code}): {str(detail)[:300]}")
        except Exception as e:
            logger.error(f"[A2APay] /teg/send settlement error: {e}")
        return None

    local = await _is_local_agent(db, receiver_did)

    # Option D-light Phase D6 (2026-04-21): remote settlements route through
    # /teg/cross-registry-transfer which is license-gated at the TEG router.
    # No standalone check needed here — the inner HTTP call will return 403
    # with reason=peer_license_suspended|revoked and the settlement status
    # will transition to FAILED in _process_settlement_async (see resp.status
    # handling below). Agent schema does not carry a peer FK for remote agents,
    # so we cannot resolve the operator DID at this layer anyway.

    try:
        client = _get_settle_client()
        if local:
            resp = await client.post(
                "http://localhost:8000/api/v1/teg/transfer",
                json={
                    "receiver_agent_id": receiver_did,
                    "amount": str(amount),
                    "message": message,
                },
                headers=headers,
            )
            endpoint_name = "/teg/transfer"
        else:
            resp = await client.post(
                "http://localhost:8000/api/v1/teg/cross-registry-transfer",
                json={
                    "receiver_did": receiver_did,
                    "amount": str(amount),
                    "message": message,
                },
                headers=headers,
            )
            endpoint_name = "/teg/cross-registry-transfer"

        if resp.status_code == 200:
            data = resp.json()
            failed = _failed_answer(data)
            if failed is not None:
                logger.error(f"[A2APay] {endpoint_name} failed (status failed): {failed[:300]}")
                return None
            tx_id = data.get("transaction_id", data.get("transfer_id", ""))
            logger.info(f"[A2APay] Settlement via {endpoint_name}: tx={tx_id} (local={local})")
            return tx_id
        else:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text[:200])
            except Exception:
                detail = resp.text[:200]
            logger.error(f"[A2APay] {endpoint_name} failed ({resp.status_code}): {detail}")
    except Exception as e:
        logger.error(f"[A2APay] Settlement error: {e}")
    return None


async def _notify_payer(event: str, auth: A2APaymentAuthorization, tx_id: Optional[str]) -> None:
    """§TWOAGENT G3: tell the PAYER's owner how its A2A payment ended (the settle call answered only `settling`).
    Owner-scoped; the seller's owner hears `payment.received` from its own frame's ledger instead."""
    try:
        from ..background_tasks.reactor_helpers import dispatch_webhook_for_agents
        await dispatch_webhook_for_agents(event, {
            "token_id": auth.id, "caller_did": auth.caller_did, "target_agent_did": auth.target_agent_did,
            "amount": str(auth.amount), "currency": _FRAME_CCY, "status": auth.status,
            "settlement_tx_id": tx_id, "task_id": auth.task_id,
        }, [auth.caller_did], source_label="a2a_payment")
    except Exception:  # noqa: BLE001 — a notice never disturbs the settlement it reports
        logger.debug("[A2APay] %s notice skipped for %s", event, auth.id, exc_info=True)


async def _after_settled(db: AsyncSession, auth, tx_id: str, contract_id: Optional[int]) -> None:
    """What a token that settled owes beyond its own row, once its row reads SETTLED: the success count, the payer's
    `payment.settled` notice, and a contract-bound token's contract.payment_transaction_id. §DOCSFIX D6-778: the
    background settle and the stale-settlement sweep (background_tasks/a2a_payment_expiry, a token whose kept transfer
    completed) both run it; the sweep ran none of it, so such a payment told its payer nothing and stamped no contract.
    `auth` needs id, caller_did, target_agent_did, amount, status and task_id. Each part is its own try: none of them can
    undo the settlement."""
    if _A2A_PROM_AVAILABLE:
        try:
            A2A_PAYMENT_SETTLED_TOTAL.labels(result="success", registry=_a2a_registry_label()).inc()
        except Exception:  # noqa: BLE001 — a count never disturbs the settlement it counts
            pass
    await _notify_payer("payment.settled", auth, tx_id)
    if contract_id:
        try:
            from ..models import RefactoringUpgradeContract
            await db.execute(
                update(RefactoringUpgradeContract)
                .where(RefactoringUpgradeContract.id == contract_id)
                .values(payment_transaction_id=tx_id)
            )
            await db.commit()
        except Exception as _link_err:  # §S4: settled, but unlinked
            logger.warning(
                "[A2APay] settled %s tx=%s but could not stamp "
                "contract %s.payment_transaction_id: %s",
                auth.id, tx_id, contract_id, _link_err,
            )


async def _process_settlement_async(
    auth_id: str, caller_jwt: str, receiver_did: str,
    amount: Decimal, message: str, contract_id: Optional[int],
    settlement_key: Optional[str] = None,
):
    """Background task: execute TEG transfer and update token status.

    Runs after settle_payment() returns 200 to the caller.
    The caller sees status='settling'; this task moves it to 'settled' or 'failed'.
    `settlement_key` is the token's _settlement_key (settle_payment derives it from the token's hash).
    """
    try:
        async with AsyncSessionLocal() as db:
            tx_id = await _settle_via_transfer(
                caller_jwt, receiver_did, amount, db, message, contract_id,
                idempotency_key=settlement_key,
            )
            auth = await db.get(A2APaymentAuthorization, auth_id)
            if not auth:
                logger.error(f"[A2APay] Background: auth {auth_id} not found")
                return
            # §DOCSFIX CB-442: the stale-settlement sweep can end the wait while this transfer runs (its clock starts
            # at verification); a transfer that then completes is the payment, recorded, never dropped (a payer
            # reading FAILED may pay again)
            late = bool(tx_id) and auth.status == A2APaymentStatus.FAILED.value
            if auth.status != A2APaymentStatus.SETTLING.value and not late:
                logger.info(f"[A2APay] Background: auth {auth_id} already {auth.status}, skipping")
                return
            if late:
                logger.warning(f"[A2APay] Background: auth {auth_id} was marked failed while its transfer ran; "
                               f"the transfer completed (tx={tx_id}), recording the payment")
            if tx_id:
                auth.status = A2APaymentStatus.SETTLED.value
                auth.settlement_tx_id = tx_id
                auth.settled_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info(f"[A2APay] Background settled {auth_id}: tx={tx_id}")
                await _after_settled(db, auth, tx_id, contract_id)
            else:
                auth.status = A2APaymentStatus.FAILED.value
                await db.commit()
                if _A2A_PROM_AVAILABLE:
                    A2A_PAYMENT_SETTLED_TOTAL.labels(
                        result="failed", registry=_a2a_registry_label()
                    ).inc()
                logger.error(f"[A2APay] Background settlement FAILED for {auth_id}")
                await _notify_payer("payment.settlement_failed", auth, None)
    except Exception as e:
        logger.error(f"[A2APay] Background settlement error for {auth_id}: {e}")
        try:
            async with AsyncSessionLocal() as db:
                auth = await db.get(A2APaymentAuthorization, auth_id)
                if auth and auth.status == A2APaymentStatus.SETTLING.value:
                    auth.status = A2APaymentStatus.FAILED.value
                    await db.commit()
        except Exception:
            pass  # recovery worker will catch stale SETTLING tokens


async def payee_refusal(db: AsyncSession, did: str) -> Optional[str]:
    """The sentence authorize_payment refuses this payee with, or None when authorize lets it through.

    D6-831/832 (2026-10-25): the same two decisions authorize applies to the PAYEE, in its order (§REPBOND's bond,
    then §ENFPROP's enforcement), asked without counting or logging: a preview is not a gate decision. The buy door's
    quote and the public showcase ask this before they offer a paid call, so neither offers a call authorize then
    refuses (the door priced an unbonded agent and enabled Buy; the press met authorize's 403)."""
    for decide in (_rb.decide, _ep.decide):
        _decision, why = await decide(db, did, site="a2a_payee")
        if why:
            return why
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/authorize", response_model=AuthorizeResponse, summary="Get A2A payment token")
async def authorize_payment(
    req: AuthorizeRequest,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("a2a.pay")),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency."),
):
    """
    Issue a payment token (apt_) that authorizes the caller to invoke an agent's A2A endpoint; the token proves the
    caller has the balance, and settlement happens after the task. An `Idempotency-Key` header is kept for 24 hours:
    a replay answers the same plain token, never a new one. Needs an agent token with the `a2a.pay` permission.

    \f
    Issue a payment token that authorizes the caller to invoke an agent's A2A endpoint.
    The token proves the caller has sufficient balance. Settlement happens after task completion.

    §pass57: Idempotency-Key now ENFORCED via Redis (24h TTL). Note the response
    contains the plain_token — on replay we return the cached one (NOT a fresh
    token). This is intentional: idempotent retry should not issue a new token.
    """
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    # §REPBOND — the PAYEE is the provider: the bond gate applies at authorize time
    # (before the idempotent replay, so a payee that lost its bond is refused fresh).
    await _rb.gate(db, req.target_agent_did, site="a2a_payee")
    await _ep.gate(db, req.target_agent_did, site="a2a_payee")
    from agentvault_registry.services.idempotency.cache import agent_caller
    me = agent_caller(current_agent.did)   # D6-777: the key is this caller's; a replay carries the payment token
    _idem_body = req.model_dump(mode="json")
    _cached, _err = await idempotency_lookup("a2a.authorize", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    caller_did = current_agent.did
    amount = Decimal(req.amount)

    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    # §DOCSFIX CB-449: the token keeps six decimal places (the column's scale), rounded as the database rounds (half
    # up). That value is the amount from here on (the spend gate, the balance check, the row and the answer, which
    # echoed the unrounded string), and an amount that rounds to nothing is refused rather than stored as 0.
    try:
        amount = amount.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise HTTPException(400, "Amount is too large")
    if amount <= 0:
        raise HTTPException(400, "Amount must be at least 0.000001: amounts are kept to six decimal places")

    # IRONKEY L2 spend gate (pre-escrow, Δ-safe): A2A payer authorizing an outflow.
    # (request carries the resolved L4 capability for the S1 caveat/budget gate.)
    await enforce_agent_spend(db, caller_did, str(amount), counterparty_did=req.target_agent_did, request=request)

    # Verify target agent DID format (local or federated — actual existence checked at settlement)
    if not req.target_agent_did or len(req.target_agent_did) < 10:
        raise HTTPException(400, "Invalid target agent DID")

    # Check the payer's balance (from registry DB, synced from TEG). §TWOAGENT G5: the payer is the PURSE — the caller
    # itself, or for an anchored hand the wallet it spends from (see _payer_purse above).
    purse_agent, purse_did = await _payer_purse(db, current_agent, request)
    anchored = purse_did != caller_did
    balance = await _get_agent_balance(purse_agent)
    # §DOCSFIX CB-440: a payee on this registry is paid by /teg/transfer, which charges the intra-registry fee on top
    # of the amount; the admission asks for both, so a delivered service is not left unpaid by its own settlement
    fee = await _local_settlement_fee(db, purse_did, req.target_agent_did, amount)
    required = amount + fee
    if balance < required:
        raise HTTPException(
            status_code=402,
            detail=(f"Insufficient balance: {balance} {_FRAME_CCY} available, {required} {_FRAME_CCY} required"
                    + (f" ({amount} {_FRAME_CCY} and the transfer fee of {fee} {_FRAME_CCY})" if fee > 0 else "")
                    + (f" (in {purse_did}, the wallet this agent spends from)" if anchored else "")),
        )
    if anchored:
        refusal = await _purse_refusal(db, purse_did, amount, req.target_agent_did)
        if refusal:
            raise HTTPException(
                status_code=403,
                detail=(f"This agent spends from {purse_did}, and that wallet could not settle this payment: "
                        f"{refusal}. Nothing was authorized."),
            )
    else:
        # CB-457: the caller's own wallet pays, through the same transfer rails, so it is asked the same question
        # before the service works (the a2a.pay gate above set the act principal of this request's token).
        from agentvault_registry.security import _ACT_PRINCIPAL
        refusal = await _settle_permission_refusal(db, caller_did, req.target_agent_did, _ACT_PRINCIPAL.get())
        if refusal:
            raise HTTPException(
                status_code=403,
                detail=f"This agent could not settle this payment: {refusal}. Nothing was authorized.",
            )

    # Check pending token limit
    pending_count = await db.scalar(
        select(func.count(A2APaymentAuthorization.id))
        .where(A2APaymentAuthorization.caller_did == caller_did)
        .where(A2APaymentAuthorization.status == A2APaymentStatus.AUTHORIZED.value)
    )
    if pending_count and pending_count >= MAX_PENDING_PER_CALLER:
        raise HTTPException(429, f"Too many pending payment authorizations ({MAX_PENDING_PER_CALLER} max)")

    # Generate token
    plain_token = _generate_token()
    token_hash = _hash_token(plain_token)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=req.ttl_seconds)

    auth = A2APaymentAuthorization(
        caller_did=caller_did,
        target_agent_did=req.target_agent_did,
        amount=amount,
        token_hash=token_hash,
        token_prefix=plain_token[:12],
        status=A2APaymentStatus.AUTHORIZED.value,
        contract_id=req.contract_id,
        idempotency_key=f"a2a-pay-{token_hash[:16]}",
        expires_at=expires,
    )
    db.add(auth)
    await db.commit()
    await db.refresh(auth)

    # CONTRACT SPINE (P2, 2026-07-25): stamp the spine id alongside the legacy int — the RUC
    # table is frozen history, so provenance for adapter-era contracts lives on contract_ref.
    if req.contract_id is not None:
        try:
            from sqlalchemy import text as _text
            await db.execute(_text(
                "UPDATE a2a_payment_authorizations SET contract_ref = "
                "(SELECT id FROM contracts WHERE legacy_ruc_id = :l) WHERE id = :a"),
                {"l": req.contract_id, "a": auth.id})
            await db.commit()
        except Exception:  # noqa: BLE001 — provenance stamp never blocks an authorization
            logger.debug("[A2APay] contract_ref stamp skipped", exc_info=True)

    logger.info(f"[A2APay] Authorized: {caller_did} → {req.target_agent_did} for {amount} AVT (id={auth.id})")

    # Emit event (audit trail, skip in projection)
    # $10 (2026-07-24): AWAITED — emit_background is dropped on worker restart.
    await emit_or_report(  # §SILENT: logged, counted, never silent; never raised after the authorization
        get_event_emitter(), where="a2a-payment.authorize",
        event_type="A2APaymentAuthorized",
        aggregate_id=caller_did,
        data={
            "token_id": auth.id,
            "caller_did": caller_did,
            "target_agent_did": req.target_agent_did,
            "amount": str(amount),
            "contract_id": req.contract_id,
            "expires_at": expires.isoformat(),
            **({"purse_did": purse_did} if anchored else {}),  # §TWOAGENT G5: the wallet that will pay
        },
        idempotency_key=f"a2a-authorized-{auth.id}",  # §BATCH7
    )

    if _A2A_PROM_AVAILABLE:
        A2A_PAYMENT_AUTHORIZED_TOTAL.labels(registry=_a2a_registry_label()).inc()

    _resp = AuthorizeResponse(
        token=plain_token,
        token_id=auth.id,
        amount=str(amount),
        target_agent_did=req.target_agent_did,
        expires_at=expires.isoformat(),
        contract_id=req.contract_id,
        issuer=_issuer_url(request),
    )
    # §pass57: cache the AuthorizeResponse for replay. The plain_token is the
    # ONLY copy ever returned to the caller; replay returns the SAME token
    # (correct semantics — same operation, same artifact).
    await idempotency_store("a2a.authorize", idempotency_key, _idem_body, _resp.model_dump(mode="json"), principal=me)
    return _resp


@router.post("/verify", response_model=VerifyResponse, summary="Verify a payment token")
async def verify_payment(
    req: VerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify a payment token is valid. Called by agent SDK middleware.
    No authentication required: a payment token is its own credential.
    """
    token_hash = _hash_token(req.token)
    result = await db.execute(
        select(A2APaymentAuthorization).where(A2APaymentAuthorization.token_hash == token_hash)
    )
    auth = result.scalar_one_or_none()

    def _a2a_inc(outcome: str) -> None:
        if _A2A_PROM_AVAILABLE:
            A2A_PAYMENT_VERIFIED_TOTAL.labels(
                outcome=outcome, registry=_a2a_registry_label()
            ).inc()

    if not auth:
        _a2a_inc("not_found")
        return VerifyResponse(valid=False, error="Token not found")

    now = datetime.now(timezone.utc)

    # Check expiry
    if auth.expires_at.tzinfo is None:
        expires = auth.expires_at.replace(tzinfo=timezone.utc)
    else:
        expires = auth.expires_at

    if now > expires:
        if auth.status == A2APaymentStatus.AUTHORIZED.value:
            auth.status = A2APaymentStatus.EXPIRED.value
            await db.commit()
        _a2a_inc("expired")
        return VerifyResponse(valid=False, error="Token expired", status="expired")

    # Check status
    if auth.status not in (A2APaymentStatus.AUTHORIZED.value, A2APaymentStatus.CONSUMED.value):
        _a2a_inc("invalid_status")
        return VerifyResponse(valid=False, error=f"Token status: {auth.status}", status=auth.status)

    # Optional target DID check
    if req.target_agent_did and auth.target_agent_did != req.target_agent_did:
        _a2a_inc("wrong_target")
        return VerifyResponse(valid=False, error="Token not issued for this agent")

    # Mark as consumed on first verify (idempotent — already consumed is fine)
    if auth.status == A2APaymentStatus.AUTHORIZED.value:
        auth.status = A2APaymentStatus.CONSUMED.value
        auth.consumed_at = now
        await db.commit()

    _a2a_inc("valid")
    return VerifyResponse(
        valid=True,
        token_id=auth.id,
        caller_did=auth.caller_did,
        target_agent_did=auth.target_agent_did,
        amount=str(auth.amount),
        contract_id=auth.contract_id,
        expires_at=expires.isoformat(),
        status=auth.status,
    )


@router.post("/settle", response_model=SettleResponse, summary="Settle a payment token")
async def settle_payment(
    req: SettleRequest,
    request: Request,
    # §BUYSERVICE (2026-08-24): was `a2a.collect` — an UNSATISFIABLE gate. Settlement is
    # the PAYER's act (the body below refuses anyone but `auth.caller_did`, because only
    # the payer can authorize a debit from their own account), but `a2a.collect` belongs
    # to the `service-provider` role while a payer is a `client` holding `a2a.pay`. Under
    # AGENT_RBAC_MODE=enforce the two sets are disjoint, so the pair
    # (holds a2a.collect) AND (is the payer) was reachable ONLY by a `legacy-full` agent.
    # Measured live 2026-08-24: a frame-c buyer with the fleet-default roles
    # (trader,client,staker) bought a registry-a service, the agent DELIVERED the work,
    # and settle returned 403 — service rendered, money never moved. Every agent born
    # since IRONKEY enforce had this. The permission must name what the caller does: pay.
    current_agent: Agent = Security(require_agent_permission("a2a.pay")),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="Accepted and not used: a token settles at most once, and settling it again answers from the "
                    "token's own state."),
):
    """
    Settle a consumed payment token: execute the actual TEG transfer.

    Routes through the existing /teg/transfer endpoint which handles:
    fee calculation, atomic TEG transfer, balance sync (sender + receiver),
    EigenTrust trust signal, fee audit record, and event emission.

    Must be called by the CALLER agent (the payer) since only they can
    authorize a debit from their account.
    """
    token_hash = _hash_token(req.token)
    result = await db.execute(
        select(A2APaymentAuthorization).where(A2APaymentAuthorization.token_hash == token_hash)
    )
    auth = result.scalar_one_or_none()

    if not auth:
        raise HTTPException(404, "Token not found")

    # Only the CALLER (payer) can settle — they authorize the debit
    if current_agent.did != auth.caller_did:
        raise HTTPException(403, "Only the caller (payer) agent can settle this token")
    # §REPBOND — settlement pays for DELIVERED work, so it never refuses (§BUYSERVICE's
    # lesson: a provider that delivered must be paid); it only counts the decision.
    if _rb.bond_mode() != "off":
        await _rb.gate(db, auth.target_agent_did, site="a2a_payee", mode="shadow")
    if _ep.propagation_mode() != "off":
        await _ep.gate(db, auth.target_agent_did, site="a2a_payee", mode="shadow")

    # Already settled — idempotent
    if auth.status == A2APaymentStatus.SETTLED.value:
        return SettleResponse(
            token_id=auth.id, status="settled",
            settlement_tx_id=auth.settlement_tx_id,
            amount=str(auth.amount),
            caller_did=auth.caller_did,
            target_agent_did=auth.target_agent_did,
        )

    # Must be consumed (verified by agent) or authorized
    if auth.status not in (A2APaymentStatus.CONSUMED.value, A2APaymentStatus.AUTHORIZED.value):
        raise HTTPException(400, f"Cannot settle token in status: {auth.status}")

    # Record task_id, in the statement that claims the token, so only the settle (or release) that wins the claim
    # writes it: a settle that lost the claim used to rewrite the winner's task id, and the stale-settlement sweep reads
    # it back to rebuild the settlement's message (_settlement_message, _settlement_record_bodies)
    _task = {"task_id": req.task_id} if req.task_id else {}

    # If task failed, release instead of settling — atomic claim (no double-transition)
    if not req.success:
        rel = await db.execute(
            update(A2APaymentAuthorization)
            .where(A2APaymentAuthorization.id == auth.id,
                   A2APaymentAuthorization.status.in_([A2APaymentStatus.CONSUMED.value, A2APaymentStatus.AUTHORIZED.value]))
            .values(status=A2APaymentStatus.RELEASED.value, **_task)
        )
        await db.commit()
        if rel.rowcount == 0:
            await db.refresh(auth)
            raise HTTPException(409, f"Cannot release token in status: {auth.status}")
        return SettleResponse(
            token_id=auth.id, status="released",
            amount=str(auth.amount),
            caller_did=auth.caller_did,
            target_agent_did=auth.target_agent_did,
        )

    # Extract caller's JWT from the incoming request — forward to /teg/transfer
    caller_jwt = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not caller_jwt:
        raise HTTPException(401, "Caller JWT required for settlement")
    # §TWOAGENT G5: an anchored hand's payment moves from the wallet it spends from, as that wallet, for exactly the
    # amount authorize admitted (the hand's caveats and budget were charged there; forwarding its birth token here
    # would charge them twice and refuse the settlement of delivered work).
    settle_bearer = caller_jwt
    purse_agent, purse_did = await _payer_purse(db, current_agent, request)
    if purse_did != current_agent.did:
        settle_bearer = _purse_settle_bearer(purse_agent, current_agent.did)
        logger.info("[A2APay] settling %s from %s, the wallet hand %s spends from", auth.id, purse_did,
                    current_agent.did)

    # ── ASYNC FIRE-AND-FORGET SETTLEMENT ─────────────────────────────────
    # Mark token as SETTLING and return immediately (~30ms).
    # The actual TEG transfer runs as a background asyncio task.
    # The background task updates status to SETTLED or FAILED.
    # Recovery worker catches stale SETTLING tokens after 60s.
    # Atomic claim: ONLY ONE concurrent settle may flip consumed/authorized → settling.
    # Closes the double-pay race (two settles both reading CONSUMED, both firing the TEG
    # transfer). The loser gets 409 (or the settled response) and fires no transfer.
    claim = await db.execute(
        update(A2APaymentAuthorization)
        .where(A2APaymentAuthorization.id == auth.id,
               A2APaymentAuthorization.status.in_([A2APaymentStatus.CONSUMED.value, A2APaymentStatus.AUTHORIZED.value]))
        .values(status=A2APaymentStatus.SETTLING.value, **_task)
    )
    await db.commit()
    if claim.rowcount == 0:
        await db.refresh(auth)
        if auth.status == A2APaymentStatus.SETTLED.value:
            return SettleResponse(
                token_id=auth.id, status="settled",
                settlement_tx_id=auth.settlement_tx_id,
                amount=str(auth.amount),
                caller_did=auth.caller_did,
                target_agent_did=auth.target_agent_did,
            )
        raise HTTPException(409, f"Settlement already in progress (status: {auth.status})")

    asyncio.create_task(_process_settlement_async(
        auth_id=auth.id,
        caller_jwt=settle_bearer,
        receiver_did=auth.target_agent_did,
        amount=auth.amount,
        message=_settlement_message(auth.id, req.task_id),
        contract_id=auth.contract_id,
        settlement_key=_settlement_key(auth.id, token_hash),   # the token's hash: the row was found by it
    ))

    logger.info(f"[A2APay] Settling (async): {auth.caller_did} → {auth.target_agent_did} {auth.amount} AVT")

    if _A2A_PROM_AVAILABLE:
        # Track settlement *attempts*; the async worker writes the actual outcome
        # via a separate counter increment in _process_settlement_async if success/failure.
        A2A_PAYMENT_SETTLED_TOTAL.labels(
            result="attempted", registry=_a2a_registry_label()
        ).inc()

    return SettleResponse(
        token_id=auth.id, status="settling",
        settlement_tx_id=None,
        amount=str(auth.amount),
        caller_did=auth.caller_did,
        target_agent_did=auth.target_agent_did,
    )


@router.post("/release", summary="Release an unused payment token")
async def release_payment(
    req: SettleRequest,
    # §BUYSERVICE: payer action (asserts caller_did below) — see settle_payment.
    current_agent: Agent = Security(require_agent_permission("a2a.pay")),
    db: AsyncSession = Depends(get_db),
):
    """Cancel/release an authorized but unconsumed payment token."""
    token_hash = _hash_token(req.token)
    result = await db.execute(
        select(A2APaymentAuthorization).where(A2APaymentAuthorization.token_hash == token_hash)
    )
    auth = result.scalar_one_or_none()
    if not auth:
        raise HTTPException(404, "Token not found")
    if current_agent.did != auth.caller_did:
        raise HTTPException(403, "Only the caller can release a token")
    if auth.status not in (A2APaymentStatus.AUTHORIZED.value,):
        raise HTTPException(400, f"Cannot release token in status: {auth.status}")

    auth.status = A2APaymentStatus.RELEASED.value
    await db.commit()
    if _A2A_PROM_AVAILABLE:
        A2A_PAYMENT_RELEASED_TOTAL.labels(registry=_a2a_registry_label()).inc()
    return {"token_id": auth.id, "status": "released"}


@router.post("/release-by-id/{token_id}", summary="Release an authorized token by ID (UI-friendly)")
async def release_payment_by_id(
    token_id: str,
    # §BUYSERVICE: payer action (asserts caller_did below) — see settle_payment.
    current_agent: Agent = Security(require_agent_permission("a2a.pay")),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency."),
):
    """
    Release an authorized A2A payment token by its id, for a client that no longer holds the plain token (it is
    shown once, at authorize). Only the agent that authorized it may release it; a token that is not AUTHORIZED is
    refused (400). An `Idempotency-Key` header is kept for 24 hours: a replay answers the first "released" result.
    Needs an agent token with the `a2a.pay` permission.

    \f
    Build #2 (2026-05-07): UI-friendly release endpoint.

    The original POST /release requires the plaintext token (hashed lookup) which
    UI clients don't have post-creation (token shown once at authorize time).
    This endpoint takes the token_id directly and authenticates via agent JWT —
    safe because only the original caller can release their own tokens.

    §pass57: Idempotency-Key now ENFORCED via Redis cache (24h TTL). Replays
    return the original "released" response instead of the 400 "already released".
    """
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import agent_caller
    me = agent_caller(current_agent.did)   # D6-777: the key is this caller's
    _idem_body = {"token_id": token_id}
    _cached, _err = await idempotency_lookup("a2a.release-by-id", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    auth = await db.get(A2APaymentAuthorization, token_id)
    if not auth:
        raise HTTPException(404, "Token not found")
    if current_agent.did != auth.caller_did:
        raise HTTPException(403, "Only the caller can release a token")
    if auth.status not in (A2APaymentStatus.AUTHORIZED.value,):
        raise HTTPException(400, f"Cannot release token in status: {auth.status}")

    auth.status = A2APaymentStatus.RELEASED.value
    await db.commit()
    if _A2A_PROM_AVAILABLE:
        A2A_PAYMENT_RELEASED_TOTAL.labels(registry=_a2a_registry_label()).inc()
    _resp = {"token_id": auth.id, "status": "released"}
    await idempotency_store("a2a.release-by-id", idempotency_key, _idem_body, _resp, principal=me)
    return _resp


# ══════════════════════════════════════════════════════════════════════════
# §BUYSERVICE (2026-08-24) — quote a service, then buy it
#
# The rails below add NO money path. `buy_service` fires this registry's own
# /authorize and /settle over loopback with the caller's own JWT, exactly as
# _settle_via_transfer already does, so every gate (IRONKEY spend, liability,
# idempotency, events, Δ) applies unchanged and there is still ONE authorize.
# ══════════════════════════════════════════════════════════════════════════

class QuoteResponse(BaseModel):
    target_agent_did: str
    target_name: Optional[str] = None
    payment_required: bool
    price: Optional[str] = None          # what the CARD charges
    price_currency: Optional[str] = None
    price_source: Optional[str] = None   # pricing-block | a2a-extension
    pricing_model: Optional[str] = None
    your_currency: str = _FRAME_CCY
    your_amount: Optional[str] = None        # exact conversion
    recommended_amount: Optional[str] = None  # + headroom for rate drift
    headroom_pct: Optional[str] = None
    rate: Optional[str] = None
    rate_as_of: Optional[str] = None
    same_currency: bool = True
    indicative: bool = True
    endpoint: Optional[str] = None
    issuer: Optional[str] = None
    can_buy: bool = False
    reason: str = ""


class BuyRequest(BaseModel):
    target_agent_did: str = Field(..., description="DID of the service agent to buy from")
    text: Optional[str] = Field(None, description="Prompt for the agent (A2A message/send)")
    payload: Optional[dict] = Field(None, description="Raw JSON-RPC body; overrides `text`")
    amount: Optional[str] = Field(None, description="Amount to authorize in YOUR currency. Omit to use the quote.")
    token: Optional[str] = Field(None, description="Reuse an existing payment token instead of authorizing a new one")
    settle: bool = Field(True, description="Settle automatically when the agent delivers")
    ttl_seconds: int = Field(DEFAULT_TTL_SECONDS, ge=60, le=MAX_TTL_SECONDS)


class BuyResponse(BaseModel):
    ok: bool
    stage: str                       # quoted | authorized | called | settled | failed
    target_agent_did: str
    target_name: Optional[str] = None
    result: Optional[dict] = None    # the agent's A2A artifact, verbatim
    error: str = ""
    # receipt
    token_id: Optional[str] = None
    paid_amount: Optional[str] = None
    paid_currency: Optional[str] = None
    price: Optional[str] = None
    price_currency: Optional[str] = None
    rate: Optional[str] = None
    issuer: Optional[str] = None
    settlement_status: Optional[str] = None
    settlement_tx_id: Optional[str] = None
    endpoint: Optional[str] = None


async def _quote_for(db: AsyncSession, request: Request, target_agent_did: str) -> QuoteResponse:
    """Shared by GET /quote and POST /buy so the price a human is shown is
    literally the price the purchase uses."""
    from ..services import service_purchase as sp
    from .agent_cards import effective_pricing_for_did

    q = QuoteResponse(target_agent_did=target_agent_did, payment_required=False,
                      your_currency=_FRAME_CCY, issuer=_issuer_url(request))

    card = await effective_pricing_for_did(db, target_agent_did)
    if not card:
        q.reason = ("No active agent card for this DID on this registry. If the agent lives on a peer, "
                    "wait for federation card sync (or open it once in Discover) and retry.")
        return q

    q.target_name = card.get("name")
    q.endpoint = card.get("endpoint_url") or None
    pricing = card.get("pricing") or None

    if not card.get("is_paid") or not pricing:
        # Free is a real answer, not a missing one — the same door should call it.
        q.payment_required = False
        q.can_buy = bool(q.endpoint)
        q.reason = "" if q.endpoint else "This card declares no A2A endpoint to call."
        return q

    q.payment_required = True
    q.price = str(pricing.get("base_rate") or "")
    q.price_currency = (pricing.get("currency") or _FRAME_CCY).upper()
    q.price_source = pricing.get("source")
    q.pricing_model = pricing.get("model")
    q.same_currency = (q.price_currency == _FRAME_CCY)

    try:
        price_dec = Decimal(q.price)
    except (InvalidOperation, TypeError, ValueError):
        q.reason = f"This card's price is not a number ({q.price!r}) — it cannot be quoted."
        return q

    # D6-832 (2026-10-25): the payee's standing under authorize's own rule (the bond, then enforcement), before the
    # price is converted. The door showed a price and an enabled Buy for an unbonded agent and the press met
    # authorize's 403; the quote now says authorize's sentence and offers no Buy, and POST /buy, which reads this
    # quote, answers the same sentence without asking authorize.
    why = await payee_refusal(db, target_agent_did)
    if why:
        q.reason = why
        return q

    pairs, as_of = ([], "")
    if not q.same_currency:
        pairs, as_of = await sp.fetch_fx_pairs(_SELF_BASE, _get_settle_client())
    conv = sp.price_in_payer_currency(price_dec, q.price_currency, _FRAME_CCY, pairs)
    q.rate_as_of = as_of or None
    if not conv["ok"]:
        q.reason = conv["reason"]
        return q

    q.your_amount = conv["exact"]
    q.recommended_amount = conv["recommended"]
    q.headroom_pct = conv["headroom_pct"]
    q.rate = conv["rate"]
    q.can_buy = bool(q.endpoint)
    if not q.endpoint:
        q.reason = "This card declares no A2A endpoint to call."
    return q


@router.get("/quote", response_model=QuoteResponse,
            summary="What a service costs in YOUR unit, before you spend anything")
async def quote_service(
    request: Request,
    target_agent_did: str = Query(..., description="DID of the service agent"),
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    What a service on another frame costs in the caller's unit, before anything is spent. A card's price is in its
    own frame's unit, and the agent converts a payment back before comparing it to its floor, so paying the card's
    face number underpays by the FX spread and is refused. This converts in the same direction the agent will, plus
    a small headroom for the rate moving between quote and call. Indicative: the agent prices again at delivery.
    Needs an agent token.

    \f
    Price a foreign service honestly.

    A card priced `0.5 AVT` costs a BVT holder ~0.59 BVT, and the agent's own
    §PAYCHECK gate converts the payment back before comparing it to its floor —
    so paying the card's face number underpays by the whole FX spread and is
    refused. This converts in the SAME direction the agent will, and adds a small
    headroom because the rate moves between quote and call. Indicative: the agent
    re-prices at delivery.
    """
    return await _quote_for(db, request, target_agent_did)


def _note_buy_leg_failed(leg: str, token_id, exc: BaseException) -> None:
    """A best-effort leg that fails must leave a trace an operator can see: the caller already
    gets settlement_status=release_failed, but nothing counted it and nothing logged it
    (§S4 pass 3, 2026-09-05). Money is not at risk - an unreleased reservation expires and the
    expiry worker releases it - so WARNING, not ERROR."""
    logger.warning(f"[A2A buy] {leg} failed for token {token_id}: {exc.__class__.__name__}: {exc}")
    try:
        if _A2A_PROM_AVAILABLE and A2A_BUY_LEG_FAILED_TOTAL is not None:
            A2A_BUY_LEG_FAILED_TOTAL.labels(leg=leg, registry=_a2a_registry_label()).inc()
    except Exception:  # noqa: BLE001 - metrics never break the response
        pass

@router.post("/buy", response_model=BuyResponse,
             summary="Buy an agent's service: authorize, call it, settle, show the answer")
async def buy_service(
    req: BuyRequest,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("a2a.pay")),
    db: AsyncSession = Depends(get_db),
):
    """One door for a human: quote → authorize → call the agent → settle → answer.

    The registry places the call because a browser cannot: the buyer's registry and
    the agent are different origins, and the payment token must not be handed to
    page JavaScript. The endpoint is taken from the agent's OWN registered card and
    SSRF-checked; it is never caller-supplied.
    """
    from ..services import service_purchase as sp

    caller_jwt = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not caller_jwt:
        raise HTTPException(401, "Bearer token required to buy")

    q = await _quote_for(db, request, req.target_agent_did)
    resp = BuyResponse(
        ok=False, stage="quoted", target_agent_did=req.target_agent_did,
        target_name=q.target_name, price=q.price, price_currency=q.price_currency,
        rate=q.rate, issuer=q.issuer, endpoint=q.endpoint, paid_currency=_FRAME_CCY,
    )
    if not q.can_buy:
        resp.stage, resp.error = "failed", (q.reason or "This agent cannot be bought from right now.")
        return resp

    client = _get_settle_client()
    token, token_id = req.token, None

    # ── authorize (only when the card actually charges) ──
    if q.payment_required and not token:
        amount = req.amount or q.recommended_amount
        if not amount:
            resp.stage, resp.error = "failed", (q.reason or "Could not determine an amount to authorize.")
            return resp
        try:
            ar = await client.post(
                f"{_SELF_BASE}/api/v1/a2a-payment/authorize",
                json={"target_agent_did": req.target_agent_did, "amount": amount,
                      "ttl_seconds": req.ttl_seconds},
                headers=_caller_headers(request, caller_jwt), timeout=30.0,
            )
        except httpx.RequestError as e:
            resp.stage, resp.error = "failed", f"Authorization unreachable: {e.__class__.__name__}"
            return resp
        if ar.status_code != 200:
            try:
                detail = ar.json().get("detail") or ar.text[:200]
            except Exception:  # noqa: BLE001
                detail = ar.text[:200]
            resp.stage = "failed"
            resp.error = f"Authorization refused ({ar.status_code}): {str(detail)[:300]}"
            return resp
        adata = ar.json()
        token, token_id = adata.get("token"), adata.get("token_id")
        resp.token_id, resp.paid_amount = token_id, adata.get("amount")
        resp.paid_currency = adata.get("currency") or _FRAME_CCY
        resp.stage = "authorized"

    # ── call the agent ──
    payload = req.payload or sp.build_a2a_message(req.text or "")
    try:
        called = await sp.call_agent(client, q.endpoint or "", payload, token, q.issuer)
    except sp.UnsafeEndpoint as e:
        called = {"ok": False, "http_status": 0, "body": None, "error": str(e)}

    if not called["ok"]:
        resp.stage, resp.error = "failed", called["error"] or "The agent did not deliver."
        # Nothing was delivered — hand the reservation back rather than leaving it
        # to expire against the caller's pending-token budget.
        if token_id:
            # §MCPTEST30 (V0641, agentvault2-5b's console run fes-20261025T100811Z-8ef9): no settle runs on this path,
            # so nothing was paid whatever the release answers. paid_amount is set at authorize time and stayed set
            # here, so the door read "Paid 0.500000 SBXA · nothing charged" (the not_delivered path below already
            # clears it: an authorization is not a payment).
            resp.paid_amount = None
            resp.paid_currency = None
            try:
                rr = await client.post(
                    f"{_SELF_BASE}/api/v1/a2a-payment/release-by-id/{token_id}",
                    headers=_caller_headers(request, caller_jwt), timeout=20.0)
                if rr.status_code == 200:
                    resp.settlement_status = "released"
                    resp.error += " You were not charged."
                else:
                    # §BATCH4 (2026-09-05): a service's /verify CONSUMES the token before the service
                    # decides to refuse the work (SYBIL, a DataPart-only ask). release-by-id then answers
                    # 400 "Cannot release token in status: consumed" and this leg reported "released"
                    # anyway, so the caller was told a reservation was handed back that was not. Say
                    # what happened; the consumed-undelivered token expires on its own, no money moved.
                    resp.settlement_status = "release_refused"
                    _note_buy_leg_failed("release_by_id", token_id,
                                         RuntimeError(f"HTTP {rr.status_code}: {str(rr.text)[:160]}"))
            except Exception as e:  # noqa: BLE001
                resp.settlement_status = "release_failed"
                _note_buy_leg_failed("release_by_id", token_id, e)
        return resp

    # 🔴 THE AGENT'S OWN VERDICT, WHICH THIS NEVER READ. `called["ok"]` above is
    # a TRANSPORT fact — the HTTP request succeeded. Whether the WORK happened is
    # inside the body, and A2A says so explicitly. Settling a TASK_STATE_FAILED
    # charged for work the agent had just said it could not do.
    resp.result = called["body"]
    delivered, why = sp.delivery_verdict(called["body"])
    if not delivered:
        resp.ok, resp.stage = False, "not_delivered"
        resp.error = f"The agent could not answer: {why}" if why else "The agent could not answer."
        if token:
            # `success=False` is not new machinery: /settle has taken it since it
            # was written and RELEASES instead of settling. We were passing a
            # constant True over the top of it.
            try:
                sr = await client.post(
                    f"{_SELF_BASE}/api/v1/a2a-payment/settle",
                    json={"token": token, "success": False},
                    headers=_caller_headers(request, caller_jwt), timeout=30.0)
                resp.settlement_status = "released" if sr.status_code == 200 else "release_failed"
                if sr.status_code == 200:
                    resp.error += " You were not charged."
                    # 🔴 AND STOP REPORTING A PAYMENT THAT DID NOT HAPPEN.
                    # paid_amount is set at AUTHORIZE time; on a release nothing
                    # was paid, so leaving it set put "You were not charged" and
                    # "paid 0.604248 BVT" on the same card. An authorization is
                    # not a payment.
                    resp.paid_amount = None
                    resp.paid_currency = None
            except httpx.RequestError as e:
                resp.settlement_status = "release_failed"
                _note_buy_leg_failed("release_via_settle", resp.token_id, e)
        return resp

    resp.ok, resp.stage = True, "called"

    # ── settle ──
    if token and req.settle:
        try:
            sr = await client.post(
                f"{_SELF_BASE}/api/v1/a2a-payment/settle",
                json={"token": token, "success": True},
                headers=_caller_headers(request, caller_jwt), timeout=30.0)
            if sr.status_code == 200:
                sd = sr.json()
                resp.settlement_status = sd.get("status")
                resp.settlement_tx_id = sd.get("settlement_tx_id")
                resp.stage = "settled"
            else:
                # The buyer HAS the goods. Say plainly that the money did not move —
                # never let a delivered-but-unpaid purchase read as a clean success.
                resp.settlement_status = "failed"
                resp.error = (f"Service delivered, but settlement failed ({sr.status_code}). "
                              f"You owe this agent — retry settle on token {resp.token_id}.")
        except httpx.RequestError as e:
            resp.settlement_status = "failed"
            resp.error = (f"Service delivered, but settlement could not be reached "
                          f"({e.__class__.__name__}). Retry settle on token {resp.token_id}.")
    elif token:
        resp.settlement_status = "consumed"
    return resp


@router.get("/my-tokens", response_model=List[TokenListItem], summary="List my payment tokens")
async def list_my_tokens(
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),   # §DOCSFIX CB-455: 0 read as "no tokens", a negative LIMIT failed in the database
):
    """List payment tokens created by the calling agent."""
    q = (
        select(A2APaymentAuthorization)
        .where(A2APaymentAuthorization.caller_did == current_agent.did)
        .order_by(A2APaymentAuthorization.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        # §MCPTEST30: any case is the same status, and a value no token can hold is refused rather than answered with an
        # empty list (which reads exactly like "you have no such tokens")
        sf = status_filter.strip().lower()
        valid = {s.value for s in A2APaymentStatus}
        if sf not in valid:
            raise HTTPException(status_code=422, detail=f"Unknown status '{status_filter}'. Must be one of: {', '.join(sorted(valid))}")
        q = q.where(A2APaymentAuthorization.status == sf)
    result = await db.execute(q)
    tokens = result.scalars().all()
    return [
        TokenListItem(
            token_id=t.id,
            target_agent_did=t.target_agent_did,
            amount=str(t.amount),
            status=t.status,
            contract_id=t.contract_id,
            created_at=t.created_at.isoformat(),
            expires_at=t.expires_at.isoformat(),
            settled_at=t.settled_at.isoformat() if t.settled_at else None,
        )
        for t in tokens
    ]
