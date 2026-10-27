"""
TEG Smart Send — `POST /api/v1/teg/send` (f060, 2026-06-12)

ONE agent-facing endpoint for moving value to ANY receiver. Auto-detects the
route (local | 2pc | async | fx) from the federated agent-card cache — the same
derivation the IRONHAND probe panel proved fleet-wide (V0028/V0029) — then fires
the EXISTING canonical endpoint with the caller's own JWT:

    local  → /api/v1/teg/transfer
    2pc    → /api/v1/teg/cross-registry-transfer?backend=2pc   (sync completed)
    async  → /api/v1/teg/cross-registry-transfer?backend=async (locked → settled)
    fx     → /api/v1/teg/cross-registry-transfer               (WS-C router → FX booth /
                                                                 Model-C gateway delegation)

Pure dispatcher: NO new money path (Rule 13 by construction), no new event
types, no DB writes. Fees / idempotency / supply events are all the inner
endpoint's. `dry_run=true` returns the route decision and moves NOTHING.

Self-call pattern mirrors a2a_payment._settle_via_transfer (battle-tested):
http://localhost:8000 + caller bearer + forwarded Idempotency-Key.
"""
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response, Security, status
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent
from .utils import get_current_agent
from ..services.smart_transfer import derive_route
from ..services.idempotency.cache import REPLAYED_HEADER

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/teg", tags=["TEG Smart Send"])

_SELF_BASE = os.getenv("REGISTRY_SELF_URL", "http://localhost:8000").rstrip("/")

# Shared httpx client (a2a settle-client pattern — avoids TCP churn under load).
_send_client: Optional[httpx.AsyncClient] = None


def _get_send_client() -> httpx.AsyncClient:
    global _send_client
    if _send_client is None or _send_client.is_closed:
        _send_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=httpx.Timeout(90.0, connect=5.0),
        )
    return _send_client


class SmartSendRequest(BaseModel):
    receiver_did: str = Field(..., min_length=8, description="Receiver agent DID — local or federated")
    amount: str = Field(..., description="Amount in the SENDER frame's currency (decimal string)")
    message: str = Field("", max_length=500, description="Optional transfer memo")
    backend: Optional[str] = Field(
        None, description="Optional same-currency remote backend hint: 2pc (default, sync) | async (locked→settled). Ignored for local and cross-currency routes."
    )
    dry_run: bool = Field(False, description="Preview the route decision without moving anything")


class SmartSendResponse(BaseModel):
    ok: bool
    method: str                       # local | 2pc | async | fx
    status: str                       # completed | locked | initiated | settled | dry_run
    transfer_id: str = ""
    sender_did: str = ""
    receiver_did: str = ""
    receiver_registry: str = ""
    currency_sent: str = ""
    currency_received: str = ""
    currency_source: str = ""         # local | card | resolver | heuristic (preview provenance)
    amount: str = ""
    dry_run: bool = False
    via: str = ""                     # inner endpoint fired (or previewed)
    latency_ms: int = 0
    notes: list = []
    fx_quote: Optional[dict] = None   # dry-run fx only: indicative {rate, est_received, fee_rate, rate_mode, as_of}
    detail: Optional[dict] = None     # inner endpoint response passthrough


async def _indicative_fx_quote(currency_sent: str, amount: str) -> Optional[dict]:
    """Dry-run-only indicative FX quote from the public keyless /fx/rate (30s-cached
    upstream; operators proxy their gateway's rate). NEVER gates the route — the booth
    re-prices at execution. Returns None on any failure (preview degrades gracefully)."""
    try:
        client = _get_send_client()
        r = await client.get(f"{_SELF_BASE}/api/v1/teg/fx/rate", timeout=8.0)
        if r.status_code != 200:
            return None
        d = r.json()
        if not isinstance(d, dict) or not d.get("available"):
            return None
        rate = d.get("bvt_per_avt") if currency_sent == "AVT" else d.get("avt_per_bvt")
        if not rate:
            return None
        from decimal import Decimal
        fee_rate = Decimal(os.getenv("FX_FEE_RATE", "0.005") or "0.005")
        gross = Decimal(str(amount)) * Decimal(str(rate))
        est = gross * (Decimal("1") - fee_rate)
        return {
            "rate": str(rate),
            "est_received": f"{est:.6f}",
            "fee_rate": str(fee_rate),
            "rate_mode": d.get("rate_mode", ""),
            "as_of": d.get("as_of", ""),
            "indicative": True,
        }
    except Exception as e:
        logger.debug(f"[SMART-SEND] indicative quote unavailable: {e}")
        return None


async def _receiver_fx_quote(receiver_did: str, amount: str, bearer: str) -> Optional[dict]:
    """§FESUITE (2026-10-10): the dry run's FX preview from the receiver-aware quote (POST /teg/fx/quote, the one the
    Forex desk shows), asked with the caller's own token. The keyless /fx/rate reading above prices only the old AVT/BVT
    pair (it picks bvt_per_avt or avt_per_bvt by whether the sender's currency is "AVT"), so on every frame since
    (SBXB/SBXA on the sandbox, ECU/ACU in production) it found no rate and the preview carried no quote: Pocket then said
    what arrives in the SENDER's currency. Same shape as above; None on any failure (the booth re-prices at execution)."""
    if not bearer:
        return None
    try:
        from decimal import Decimal
        client = _get_send_client()
        r = await client.post(f"{_SELF_BASE}/api/v1/teg/fx/quote",
                              json={"receiver_did": receiver_did, "amount": str(amount)},
                              headers={"Authorization": f"Bearer {bearer}"}, timeout=10.0)
        if r.status_code != 200:
            return None
        d = r.json()
        if not isinstance(d, dict) or d.get("same_currency") or d.get("amount_out") in (None, ""):
            return None
        fee_pct = d.get("fee_pct")
        return {
            "rate": str(d.get("rate", "")),
            "est_received": str(d.get("amount_out")),
            "fee_rate": str(Decimal(str(fee_pct)) / Decimal("100")) if fee_pct not in (None, "") else "",
            "rate_mode": d.get("rate_mode", ""),
            "as_of": d.get("expires_at", ""),
            "indicative": True,
        }
    except Exception as e:
        logger.debug(f"[SMART-SEND] receiver quote unavailable: {e}")
        return None


def _bearer_from_request(request: Request) -> str:
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _inner_replayed(resp) -> bool:
    """§REPATLANE-7: the inner endpoint's answer is an earlier request's own, given again under its key."""
    headers = getattr(resp, "headers", None) or {}
    try:
        return str(headers.get(REPLAYED_HEADER) or headers.get(REPLAYED_HEADER.lower()) or "").lower() == "true"
    except Exception:  # noqa: BLE001
        return False


def _extract_transfer_id(data: dict) -> str:
    for k in ("transfer_id", "transaction_id", "swap_id", "id"):
        v = data.get(k)
        if v:
            return str(v)
    return ""


def _map_status(method: str, data: dict, http_status: int) -> str:
    inner = str(data.get("status", "")).lower()
    if inner:
        return inner
    if method in ("local", "2pc"):
        return "completed"
    if method == "async":
        return "initiated"
    return "settled" if http_status in (200, 201) else "unknown"


@router.post(
    "/send",
    response_model=SmartSendResponse,
    summary="Smart transfer: auto-routes local, cross-registry (2PC or async) or cross-frame FX",
)
async def smart_send(
    req: SmartSendRequest,
    request: Request,
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(
        default=None, alias="Idempotency-Key",
        description="Forwarded to the inner endpoint, which owns the 24h replay cache.",
    ),
    http_response: Response = None,   # §REPATLANE-7 (not "response": slowapi fills that one)
):
    if req.receiver_did == current_agent.did:
        raise HTTPException(status_code=400, detail="receiver_did is the sender — self-transfer refused")

    dec = await derive_route(
        db, sender_did=current_agent.did, receiver_did=req.receiver_did,
        amount=req.amount, message=req.message, backend_hint=req.backend,
    )

    if dec.method == "refused":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=dec.refusal_detail)

    base_resp = dict(
        method=dec.method, sender_did=current_agent.did, receiver_did=req.receiver_did,
        receiver_registry=dec.target_registry, currency_sent=dec.currency_sent,
        currency_received=dec.currency_received, currency_source=dec.currency_source,
        amount=req.amount, via=dec.endpoint, notes=dec.notes,
    )

    if req.dry_run:
        fx_quote = None
        if dec.method == "fx":
            fx_quote = (await _receiver_fx_quote(req.receiver_did, req.amount, _bearer_from_request(request))
                        or await _indicative_fx_quote(dec.currency_sent, req.amount))
        return SmartSendResponse(ok=True, status="dry_run", dry_run=True,
                                 fx_quote=fx_quote, **base_resp)

    caller_jwt = _bearer_from_request(request)
    if not caller_jwt:
        # get_current_agent already authenticated; missing raw header means a non-bearer
        # auth path we cannot forward — refuse rather than fire unauthenticated.
        raise HTTPException(status_code=401, detail="Bearer token required to dispatch the transfer")

    headers = {"Authorization": f"Bearer {caller_jwt}"}
    # §SUBAGENT-LIABILITY-V3 — propagate the anchored birth token to the inner rail so a WALLETLESS
    # hand's cross-frame/local send draws from its PRINCIPAL's purse (resolve_spend_purse_agent runs on
    # the inner endpoint). Byte-inert when absent (a normal agent presents no capability token).
    _cap = request.headers.get("x-capability-token")
    if _cap:
        headers["X-Capability-Token"] = _cap
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    t0 = time.time()
    try:
        client = _get_send_client()
        resp = await client.post(f"{_SELF_BASE}{dec.endpoint}", json=dec.body, headers=headers)
    except Exception as e:
        logger.error(f"[SMART-SEND] dispatch error ({dec.method} {dec.endpoint}): {e}")
        # §REPATLANE (V0603): a connection never made reached nothing, and the answer says so; any other failure here
        # (a read timeout, a dropped answer) may have reached the inner endpoint, which may be moving the money now.
        from ..services.payout_outcome import NO_FUNDS_MOVED, never_sent
        _none = f" {NO_FUNDS_MOVED}" if never_sent(e) else ""
        raise HTTPException(status_code=502, detail=f"smart-send dispatch failed ({dec.method}): {str(e)[:200]}{_none}")
    latency_ms = int((time.time() - t0) * 1000)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:400]}

    if resp.status_code not in (200, 201, 202):
        detail = data.get("detail", data) if isinstance(data, dict) else data
        logger.warning(
            f"[SMART-SEND] inner {dec.endpoint} -> {resp.status_code} for "
            f"{current_agent.did} → {req.receiver_did} ({dec.method})"
        )
        # §LEDGERGATE (V0597): the TEG's ledger refusal (nothing moved) passes on as it came, its sentence with the code
        # word first and its Retry-After; wrapped in the method context below it reached the console as a JSON string
        # and the header was lost.
        from ..services.ledger_unavailable import ledger_refusal, route_came_back_refusal
        refusal = ledger_refusal(resp)
        if refusal is not None:
            raise refusal
        # §LEDGERGATE (V0605): the route's "Your payment came back to you" passes on as it came too (the sentence alone,
        # its Retry-After): wrapped below, the console could not tell it from an answer that never came
        came_back = route_came_back_refusal(resp, data)
        if came_back is not None:
            raise came_back
        # Re-raise with the INNER status (no 500-wrapping) + method context.
        # §LEDGERGATE (V0605): and with the inner answer's Retry-After when it has one (the route's "Your payment came
        # back to you. Try again shortly." said when; this re-raise dropped it, measured in drill 3 on V0603)
        from ..services.ledger_unavailable import retry_after_if_any
        _ra = retry_after_if_any(resp, data)
        _hdrs = {"Retry-After": _ra} if _ra else {}
        if _inner_replayed(resp):   # §REPATLANE-7: an earlier request's own answer, given again, says so here too
            _hdrs[REPLAYED_HEADER] = "true"
        raise HTTPException(
            status_code=resp.status_code,
            detail={"smart_send_method": dec.method, "via": dec.endpoint, "inner": detail},
            headers=(_hdrs or None),
        )

    tid = _extract_transfer_id(data if isinstance(data, dict) else {})
    st = _map_status(dec.method, data if isinstance(data, dict) else {}, resp.status_code)
    logger.info(
        f"[SMART-SEND] {dec.method} settled-path {current_agent.did} → {req.receiver_did} "
        f"amount={req.amount} {dec.currency_sent}->{dec.currency_received} tx={tid} "
        f"status={st} {latency_ms}ms"
    )
    if _inner_replayed(resp) and http_response is not None:
        # §REPATLANE-7: the inner endpoint answered from what an earlier request under this key left (the same payment)
        http_response.headers[REPLAYED_HEADER] = "true"
    return SmartSendResponse(
        ok=True, status=st, transfer_id=tid, dry_run=False,
        latency_ms=latency_ms, detail=data if isinstance(data, dict) else None,
        **base_resp,
    )
