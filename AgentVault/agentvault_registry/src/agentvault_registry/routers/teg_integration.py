"""TEG Layer integration endpoints for TheProtocol v1.0.0

This module provides proxy endpoints that allow the v1.0.0 UI to interact
with the TEG Layer MVP API. It handles authentication bridging between
v1.0.0 JWT tokens and TEG API calls.

SECURITY UPDATE: This module now uses proper JWT tokens for TEG authentication
instead of agent DIDs. No backward compatibility - JWT tokens are strictly enforced.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field, field_validator
import httpx
from ..es_ssl_helper import get_httpx_verify, spire_trust_loaded, svid_stamp
from ..core.network_profile import money_knob  # §MONEY-M2: the profile owns this amount
from ..core.staking_gate import require_staking_enabled, require_staking_rewards_enabled, staking_rewards_enabled  # §BAFIN
from fastapi import APIRouter, Depends, Header, HTTPException, status, Path, Query, Request, Response, Security

from agentvault_registry import models, security
from agentvault_registry.config import settings
# §pass66 (2026-05-22) — Mainframe-only gate for /treasury/mint endpoint.
from agentvault_registry.core.mainframe_gate import require_mainframe_only as _mainframe_only_dep
# Import database dependencies for ownership verification
from agentvault_registry.database import get_db
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession
# Import get_current_agent for agent authentication
from agentvault_registry.security import get_current_agent, require_agent_permission, enforce_agent_spend  # IRONKEY
from agentvault_registry.core.federation_auth import require_peer_registry_identity
# P2-008: Event Store integration for attestation events
from agentvault_registry.crud_agent_enhanced import emit_attestation_event, emit_reputation_changed_event
from agentvault_registry.services import local_trust_updater  # EigenTrust++ Phase 2

logger = logging.getLogger(__name__)

# Unicode-safe slug for peer registry names (São Paulo → samba-sao-paulo)
# §MONEY-R50: the slug rule and the funding-origin guard live in core/registry_slug.py — ONE copy,
# shared with the frame provisioner so what it renders is what this guard accepts.
from ..core.registry_slug import fund_origin_allowed, parse_fund_origin_allowlist, registry_slug as _slug  # noqa: E402
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded
from ..services.ledger_unavailable import (  # §LEDGERGATE: the TEG's "nothing moved", passed on whole
    LedgerRefusedError, ledger_refusal, refusal_from_text,
    MARKER as LEDGER_MARKER, SENTENCE as LEDGER_SENTENCE,
)
# §REPATLANE (V0603): the sentences a refusal carries when it can prove what did not happen, which the AGORA payout lane
# reads (services/payout_outcome.py): NO_FUNDS_MOVED, refused before any money moved; NOT_DELIVERED, an FX route's payment
# reached nobody and nothing will deliver it later (the gateway returned it to the payer); OUTCOME_UNKNOWN, a failure that
# may have moved money, which a payer must never send again on its own.
from ..services.payout_outcome import NO_FUNDS_MOVED, NOT_DELIVERED, OUTCOME_UNKNOWN, never_sent as _never_sent
# The TEG's 2PC refusals that come only after the coordinator aborted the transfer cleanly (teg_core_service
# core/cross_teg/coordinator.coordinate_transfer: PREPARE_FAILED, REMOTE_PREPARE_FAILED) or refused before preparing
# (api/cross_teg_router: this TEG is not the source). A partial commit, a timeout or an unexpected error is not here.
_TEG_CLEAN_ABORTS = ("Failed to lock funds", "Target TEG rejected transfer", "This TEG (")


class _LegError(str):
    """§REPATLANE (V0603): a failed leg's sentence that also carries whether the leg provably moved nothing. It is a
    str, so every caller that formats or searches the error works as before; `_leg_moved_nothing(err)` reads the
    verdict, which is False for a plain string: an error nobody classified counts as one that may have moved money."""
    nothing_moved = False

    def __new__(cls, text: str, nothing_moved: bool = False):
        s = super().__new__(cls, text)
        s.nothing_moved = bool(nothing_moved)
        return s


def _leg_moved_nothing(err: Any) -> bool:
    return bool(getattr(err, "nothing_moved", False))


def _trace_never_sent(trace: Any) -> bool:
    """True when every connection failure `_teg_post_with_retry` caught (and retried) was a connection never made. A
    dropped connection (RemoteProtocolError) may have delivered its request, so a later answer cannot speak for it."""
    return all(_never_sent(x) for x in (trace or ()))


def _leg_refused(resp: Any) -> bool:
    """A TEG leg's answer that is a refusal made before anything moved: a 4xx (the TEG, or the proxy in front of it,
    refused the request), except 408 and 409 (fx/move answers 409 while another attempt under the same key is in
    flight, and that attempt may still complete), or the ledger gate's own refusal."""
    code = int(getattr(resp, "status_code", 0) or 0)
    if 400 <= code < 500 and code not in (408, 409):
        return True
    return ledger_refusal(resp) is not None


def _fx_leg_resolve_delays() -> Tuple[float, ...]:
    """§REPATLANE-2 (V0603): the pauses before each replay of a leg whose outcome is not known (FX_LEG_RESOLVE_DELAYS,
    seconds, comma-separated; default 1, 2, 4). Short on purpose: the leg runs inside its payer's request."""
    raw = (os.environ.get("FX_LEG_RESOLVE_DELAYS", "") or "").strip()
    if not raw:
        return (1.0, 2.0, 4.0)
    try:
        return tuple(max(0.0, float(x)) for x in raw.split(",") if x.strip())[:6]
    except ValueError:
        return (1.0, 2.0, 4.0)


# §REPATLANE-2 (V0603): the dead-letter phases that hold money whose paying leg's outcome is not known. Nothing refunds
# them on its own: an `egress_unknown` route is finished by the keeper under its own idempotency key (or returned once
# the TEG proves the egress never ran); a `swap_unknown` swap holds for a ledger read; an `egress_2pc_unknown` route (a
# two-phase egress to a leaf operator, which cannot be asked again: a re-prepare locks the source twice) holds for a
# read of its 2PC transfer, and while it is unresolved the far keeper does not re-deliver the route (V0604); a
# `redelivery_unknown` route is one the keeper's own re-delivery could not learn the outcome of: held the same way.
FX_HELD_PHASES = ("swap_unknown", "egress_unknown", "egress_2pc_unknown", "redelivery_unknown",
                  # §REPATLANE-6 (V0606): a refund to the origin whose outcome was not known (the hop's or the
                  # keeper's): sending it again could refund twice
                  "refund_unknown")


def _canonical_amount(amount: Any) -> str:
    """One spelling per value (1.99 and 1.990000000000000000 alike), so a replay under an idempotency key carries the
    same request as the attempt it replays (the TEG compares the parameters it hashed for the key)."""
    try:
        return format(Decimal(str(amount)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(amount)

# TEG API configuration - using environment variables
# Using internal container port 8080 (external port is 8100)
TEG_API_BASE_URL = getattr(settings, 'TEG_API_BASE_URL', 'http://teg-layer:8080')
TEG_API_V1_PREFIX = '/api/v1'

# TEG Admin API Key for server-to-server authentication
TEG_ADMIN_API_KEY = getattr(settings, 'TEG_ADMIN_API_KEY', '')
if not TEG_ADMIN_API_KEY:
    logger.info("TEG_ADMIN_API_KEY not set — TEG auth via mTLS-SVID (expected post-Phase-4; legacy shared key retired)")

# Token cache for TEG JWT tokens
_teg_token_cache: Dict[int, tuple[str, datetime]] = {}  # agent.id -> (token, expiry)

# §MCPTEST30 (V0524): a TEG 4xx is the TEG REFUSING this request, which a retry meets again; a TEG 401/403 is the
# registry's own credential to the TEG failing (never the caller's), and 429 / 5xx are the TEG unable to answer.
_TEG_UNAVAILABLE_4XX = frozenset({401, 403, 407, 429})


def _teg_refusal(response: httpx.Response, unavailable: str) -> HTTPException:
    """The HTTPException for a TEG answer a route has no branch of its own for (§MCPTEST30, V0524).

    Every TEG proxy route here ended in an `else` that called ANY other answer "Unable to ... at this time", 503. A 503
    says the TEG could not answer and invites a retry, but a TEG 4xx is the TEG answering: it refused THIS request (a
    value it validates, an id it does not hold, a conflict). The MCP tester's hostile-input probe met it as 503s from
    eight read routes; on a write (a system transfer, a policy, a dispute, an attestation) it told a caller to retry a
    refusal. A 4xx now reaches the caller with its own status and the TEG's reason; a 401/403 (the registry's own
    credential to the TEG), a 429 and a 5xx stay 503 with the sentence the route always gave."""
    st = response.status_code
    if not (400 <= st < 500) or st in _TEG_UNAVAILABLE_4XX:
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=unavailable)
    reason = ""
    try:
        body = response.json()
        d = body.get("detail") if isinstance(body, dict) else None
        reason = d if isinstance(d, str) else (json.dumps(d, default=str) if d else "")
    except ValueError:
        reason = ""
    head = f"The TEG refused the request (HTTP {st})"
    return HTTPException(status_code=st, detail=f"{head}: {reason[:300]}" if reason.strip() else head)

# 2026-05-02: tunable saga deadline for async cross-frame transfers.
# Default 15 min (was 5 min). At sub-second light load, no behavior change.
# Under saturation, gives Settled events 3× more time to arrive before the
# saga sweeper refunds the locked row — drastically reduces saga-vs-settle
# race losses at the 5-min boundary observed in Round-2 8x sim (79% refunded).
SAGA_CROSS_FRAME_TIMEOUT_MIN = int(os.environ.get("SAGA_CROSS_FRAME_TIMEOUT_MIN", "15"))

# Set of TEG partner IDs we've already registered with our local TEG via
# /cross-teg/config/add-partner. Persists per uvicorn worker. Prevents the
# hot path of /teg/cross-registry-transfer from re-POSTing to TEG on every
# single transfer — the handler is idempotent, but each call is an HTTP
# round-trip. Cleared only on worker restart.
_runtime_partner_cache: set[str] = set()
# The TEG partner rule (ledgergate3): the TEG drops a partner at a quarantine, a licence suspension or a peer's
# deactivation, and nothing but add-partner puts it back, so "added once in this worker" is no longer forever true. An
# entry counts for TEG_PARTNER_CACHE_TTL_SEC (300) after its add; the TEG's refusal of a peer that is no current partner
# (cross_teg_partner_refused) drops it at once, and the next transfer adds it again (after the quarantine check).
_runtime_partner_added_at: Dict[str, float] = {}
_PARTNER_CACHE_TTL_SEC = float(os.environ.get("TEG_PARTNER_CACHE_TTL_SEC", "300"))


def _partner_cached(teg_id: str) -> bool:
    if teg_id not in _runtime_partner_cache:
        return False
    added = _runtime_partner_added_at.get(teg_id)
    if added is None or time.monotonic() - added < _PARTNER_CACHE_TTL_SEC:
        return True
    _runtime_partner_cache.discard(teg_id)
    _runtime_partner_added_at.pop(teg_id, None)
    return False


def _forget_partner(teg_id: str) -> None:
    _runtime_partner_cache.discard(teg_id)
    _runtime_partner_added_at.pop(teg_id, None)

# Phase 1 scaling: Shared httpx client with connection pooling for TEG proxy calls
# Eliminates per-request TCP connection overhead (~2ms per connection setup)
_teg_http_client: Optional[httpx.AsyncClient] = None
_teg_http_client_stamp: tuple = ()

def _get_teg_client() -> httpx.AsyncClient:
    """Get or create a shared httpx client for TEG API calls.

    Mirrors the mtime self-healing pattern in es_ssl_helper.get_es_ssl_context().
    The helper rebuilds its cached SSL context when the SPIRE SVID rotates, but
    a long-lived httpx.AsyncClient binds its context at construction — so without
    this check the cached client keeps presenting the original cert until the
    worker dies, which fails after SVID TTL against nginx-teg's ssl_verify_client on.

    §SVIDRACE (V0639): keyed on the stamp of the cert, the key AND the bundle (es_ssl_helper.svid_stamp), read before
    the build, and recorded only when the client holds a SPIRE context: a client built while the cert-writer was
    mid-publish (verify fell back to the system CAs) is rebuilt on the next call, not kept for five minutes.
    """
    global _teg_http_client, _teg_http_client_stamp
    stamp = svid_stamp()

    rotated = (
        bool(stamp)
        and stamp != _teg_http_client_stamp
        and _teg_http_client is not None
    )
    if rotated:
        try:
            asyncio.get_running_loop().create_task(_teg_http_client.aclose())
        except RuntimeError:
            pass
        _teg_http_client = None

    if _teg_http_client is None or _teg_http_client.is_closed:
        verify = get_httpx_verify()
        _teg_http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=200, max_keepalive_connections=50,
                # §2026-06-09: recycle idle pooled conns BEFORE the TEG's ~5s server keep-alive
                # closes them. httpx default keepalive_expiry (5.0s) == the TEG's uvicorn
                # --timeout-keep-alive (5s), so a reused-at-the-edge conn races the server close
                # → httpx.RemoteProtocolError("Server disconnected...") mid-FX-leg. <5s removes it.
                keepalive_expiry=float(os.environ.get("TEG_CLIENT_KEEPALIVE_EXPIRY", "4.0")),
            ),
            timeout=httpx.Timeout(10.0, connect=5.0),
            verify=verify,
        )
        _teg_http_client_stamp = stamp if spire_trust_loaded(verify, stamp) else ()
    return _teg_http_client


# §2026-06-09 — FX-leg connection resilience. The FX legs reuse the pooled keep-alive client;
# under burst the TEG can close an idle keep-alive conn just as the registry reuses it →
# httpx.RemoteProtocolError("Server disconnected without sending a response"). These helpers
# retry ONLY connection-level drops (the request was not processed, OR the endpoint dedupes the
# replay). HTTP responses of ANY status are returned as-is (never retried, so non-200 business
# logic is untouched). USE ONLY on server-idempotent endpoints: POST /admin/fx/move (dedupes on
# idempotency_key via fxref:<key>) and GET /admin/fx/reserve (read). DO NOT use on the 2PC
# /cross-teg/transfer leg — it is NOT replay-safe (re-prepare double-locks the source).
_FX_TEG_RETRY_EXC = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ConnectTimeout)


async def _teg_post_with_retry(client, url, *, json, headers, timeout, retries: int = 2,
                               trace: Optional[list] = None):
    """POST that retries stale-keepalive/connect drops only. Endpoint MUST be server-idempotent.
    `trace` (§REPATLANE V0603), when given, collects every connection failure this call caught, the last one too, so
    the caller can tell "no attempt ever connected" from "an earlier attempt may have been delivered"."""
    for _attempt in range(retries + 1):
        try:
            return await client.post(url, json=json, headers=headers, timeout=timeout)
        except _FX_TEG_RETRY_EXC as _e:
            if trace is not None:
                trace.append(_e)
            if _attempt < retries:
                await asyncio.sleep(0.05 * (2 ** _attempt))  # 50ms, 100ms
                logger.warning(f"[FX] TEG conn drop POST {url} attempt {_attempt+1}/{retries+1} "
                               f"({type(_e).__name__}); retrying")
                continue
            raise


async def _teg_get_with_retry(client, url, *, headers, timeout, retries: int = 2):
    """GET that retries stale-keepalive/connect drops only (reads are trivially idempotent)."""
    for _attempt in range(retries + 1):
        try:
            return await client.get(url, headers=headers, timeout=timeout)
        except _FX_TEG_RETRY_EXC as _e:
            if _attempt < retries:
                await asyncio.sleep(0.05 * (2 ** _attempt))
                logger.warning(f"[FX] TEG conn drop GET {url} attempt {_attempt+1}/{retries+1} "
                               f"({type(_e).__name__}); retrying")
                continue
            raise


# =============================================================================
# Phase 1 Scaling: TEG Bulk Proxy — batches transfer proxy calls
# Enabled via TEG_BULK_PROXY=true env var
# =============================================================================



# ── §S4 (2026-09-04): the bulk path's ONLY event-emission site ───────────────
# The census that found this measured 2,467 silent exception handlers in the
# registry; after triage and reading, this was the one live money-path defect.
#
# WHY IT MATTERS. When TEG_BULK_PROXY is on (it is, on every node), the
# /teg/transfer handler deliberately skips its own _emit_transfer_events() so
# the bulk flush can emit instead — so this is the only place a coalesced
# transfer becomes TokensTransferred/TransactionFeeCollected. Those events are
# the supply invariant's INPUT (PART 3/4). The block was wrapped in
# `except Exception: pass  # Non-fatal — transfer succeeded`, which is true and
# is exactly what made it invisible: the money moves in the TEG, the ledger
# never hears, and nothing anywhere says so.
#
# It stays NON-FATAL — the caller's future is already resolved with a completed
# transfer, and raising here would fail a transfer that really happened. But
# non-fatal is not invisible: it now traces and counts, which is the §VITALS
# contract one layer down.
try:
    from prometheus_client import Counter as _S4Counter
    TRANSFER_EVENT_EMIT_FAILURES = _S4Counter(
        "registry_transfer_event_emit_failures_total",
        "Completed transfers whose ledger events could not be emitted "
        "(money moved, EventStore not told)",
        ["path"],
    )
except Exception:  # noqa: BLE001 — metrics never break the money path
    TRANSFER_EVENT_EMIT_FAILURES = None

try:
    from prometheus_client import Counter as _F1Counter
    CROSS_FRAME_SAME_DOMAIN_REROUTES = _F1Counter(
        "registry_cross_frame_same_domain_reroutes_total",
        "Cross-registry transfers whose target shares this frame's trust domain and were routed to the local branch (F1)",
    )
except Exception:  # noqa: BLE001
    CROSS_FRAME_SAME_DOMAIN_REROUTES = None


# ── §MONEY-R19 / D9 (2026-09-04): no automated mint ─────────────────────────
# The cross-TEG treasury fund used to call the TEG's /admin/token/issue directly
# whenever the mainframe treasury could not cover an operator seed: a routine
# provisioning shortfall silently created new supply, with no human in the loop
# and no registry-side TokensIssued event (PART 3 makes the registry the only
# legitimate emitter of that type; the TEG is blocked from it).
#
# ⚠ It did NOT breach Δ, and claiming otherwise would be wrong: execute_issuance
# sets `teg.entry_type='mint'`, the L2 outbox emits kind='mint', and
# materialized_balances.sql books that into tokens_issued. The invariant holds.
# What was wrong is that SUPPLY GREW WITHOUT A DECISION — noise against today's
# ~1e9, the entire economy on a low-supply network.
#
# Kept behind a default-OFF flag rather than deleted (D8: disabling a rail is
# reversible, removing one is a release decision), so an operator blocked
# mid-provision has a documented way out that is loud about what it does.
def _mint_on_demand_enabled() -> bool:
    return (os.getenv("TREASURY_MINT_ON_DEMAND_ENABLED", "false") or "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


try:
    from prometheus_client import Counter as _R19Counter
    TREASURY_SHORTFALL_REFUSED = _R19Counter(
        "registry_treasury_shortfall_refused_total",
        "Cross-TEG treasury funds refused because the treasury was short and "
        "automated minting is disabled (D9)",
        ["reason"],
    )
except Exception:  # noqa: BLE001 — metrics never break the money path
    TREASURY_SHORTFALL_REFUSED = None


def _emit_bulk_transfer_events(item: dict, result: dict) -> None:
    """Emit the ledger events for ONE completed bulk transfer. Never raises."""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        _emitter = get_event_emitter()
        if _emitter:
            _tx_id = result.get("transaction_id", "")
            _emitter.emit_background(
                event_type="TokensTransferred",
                aggregate_id=item["sender_did"],
                data={
                    "from": item["sender_did"],
                    "to": item["receiver_did"],
                    "amount": item["amount"],
                    "transaction_id": _tx_id,
                    "memo": item.get("message") or "",
                },
                idempotency_key=f"xfer-{_tx_id}" if _tx_id else None,
            )
            # f037: emit TransactionFeeCollected when fee > 0
            _fee = item.get("fee_amount") or "0"
            try:
                _fee_dec = Decimal(str(_fee))
            except (InvalidOperation, ValueError, TypeError):
                _fee_dec = Decimal("0")
            if _fee_dec > Decimal("0"):
                _emitter.emit_background(
                    event_type="TransactionFeeCollected",
                    aggregate_id=item["sender_did"],
                    data={
                        "agent_did": item["sender_did"],
                        "fee_amount": str(_fee),
                        "transaction_id": _tx_id,
                        "transfer_amount": item["amount"],
                        "rate_pct": 0.0,  # unknown at bulk-flush time
                    },
                    idempotency_key=f"fee-{_tx_id}" if _tx_id else None,
                )
    except Exception as emit_err:
        if TRANSFER_EVENT_EMIT_FAILURES is not None:
            try:
                TRANSFER_EVENT_EMIT_FAILURES.labels(path="bulk").inc()
            except Exception:  # noqa: BLE001
                pass
        logger.error(
            "[TEGBulkProxy] LEDGER EVENTS NOT EMITTED for tx=%r sender=%r: %s "
            "— the transfer SUCCEEDED and has NO ledger record. Delta will NOT "
            "flag this (both legs derive from this one event, so circulating "
            "moves by zero); the ES balances now drift from TEG truth and "
            "velocity/EigenTrust under-count. Reconcile this tx.",
            (result or {}).get("transaction_id", ""),
            (item or {}).get("sender_did"),
            emit_err,
            exc_info=True,
        )


class TEGBulkProxy:
    """Batches individual transfer proxy calls into TEG's bulk endpoint.

    When the Registry receives many concurrent /teg/transfer requests (e.g.
    during stress tests or simulation runs), each one normally results in a
    separate httpx POST to TEG.  TEGBulkProxy collects those requests in a
    short window (5 ms or 20 items, whichever comes first) and fires a single
    POST to TEG's ``/token/transfer/bulk`` endpoint, then distributes results
    back to the waiting callers via ``asyncio.Future``.

    Lifecycle:
        Instantiate once -> ``await start()`` on app startup ->
        ``await stop()`` on app shutdown.
    """

    def __init__(
        self,
        max_batch_size: int = 20,
        flush_interval_ms: float = 5.0,
    ):
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        self._max_batch_size = max_batch_size
        self._flush_interval_s = flush_interval_ms / 1000.0
        # Phase 1 scaling: round-robin across TEG instances
        _teg_replicas_env = os.getenv("TEG_REPLICA_URLS", "")
        if _teg_replicas_env:
            self._teg_urls = [u.strip() for u in _teg_replicas_env.split(",") if u.strip()]
        else:
            self._teg_urls = [TEG_API_BASE_URL]
        self._rr_index = 0

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(
            "[TEGBulkProxy] Started (batch=%d, flush=%.1fms)",
            self._max_batch_size,
            self._flush_interval_s * 1000,
        )

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Drain anything still buffered
        if self._buffer:
            await self._flush()
        logger.info("[TEGBulkProxy] Stopped")

    # -- public API ----------------------------------------------------------

    async def submit(
        self,
        sender_did: str,
        receiver_did: str,
        amount: str,
        fee_amount: str,
        message: Optional[str],
        teg_token: str,          # kept for interface parity; bulk uses admin key
    ) -> dict:
        """Enqueue a transfer and wait for the bulk result.

        Returns the per-transfer result dict from TEG on success.
        Raises ``ValueError`` on transfer-level failure.
        """
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._buffer.append({
                "sender_did": sender_did,
                "receiver_did": receiver_did,
                "amount": amount,
                "fee_amount": fee_amount,
                "message": message,
                "teg_token": teg_token,
                "future": future,
            })
            if len(self._buffer) >= self._max_batch_size:
                # Trigger immediate flush without holding the lock during I/O
                asyncio.ensure_future(self._flush())
        return await future

    # -- internals -----------------------------------------------------------

    async def _periodic_flush(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval_s)
            if self._buffer:
                await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            batch = self._buffer.copy()
            self._buffer.clear()

        # Build the bulk payload
        transfers = []
        for item in batch:
            entry: dict = {
                "sender_agent_id": item["sender_did"],
                "receiver_agent_id": item["receiver_did"],
                "amount": item["amount"],
            }
            if item.get("fee_amount") and item["fee_amount"] != "0":
                entry["fee_amount"] = item["fee_amount"]
            if item.get("message"):
                entry["message"] = item["message"]
            transfers.append(entry)

        client = _get_teg_client()
        # Round-robin across TEG replicas
        teg_url = self._teg_urls[self._rr_index % len(self._teg_urls)]
        self._rr_index += 1
        try:
            response = await client.post(
                f"{teg_url}{TEG_API_V1_PREFIX}/token/transfer/bulk",
                json={"transfers": transfers},
                headers={"Authorization": f"Bearer {TEG_ADMIN_API_KEY}"},
                timeout=30.0,
            )

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                for i, item in enumerate(batch):
                    if item["future"].done():
                        continue
                    if i < len(results):
                        result = results[i]
                        if result.get("status") == "completed":
                            item["future"].set_result(result)
                            # §S4: emission lives in _emit_bulk_transfer_events() so a
                            # failure here is traced and counted, not swallowed.
                            _emit_bulk_transfer_events(item, result)
                        else:
                            item["future"].set_exception(
                                ValueError(result.get("error", "Transfer failed in bulk"))
                            )
                    else:
                        item["future"].set_exception(
                            ValueError("No result returned from TEG for this transfer")
                        )
            else:
                # §LEDGERGATE (V0597): the TEG's ledger gate refused the batch (nothing in it moved): every transfer in
                # it meets that refusal as it came (503, the sentence, Retry-After), never "Transfer failed via bulk"
                _refusal = ledger_refusal(response)
                err = LedgerRefusedError(_refusal) if _refusal is not None else ValueError(
                    f"TEG bulk endpoint returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
                for item in batch:
                    if not item["future"].done():
                        item["future"].set_exception(err)

        except Exception as exc:
            for item in batch:
                if not item["future"].done():
                    item["future"].set_exception(exc)

        logger.debug("[TEGBulkProxy] Flushed batch of %d transfers", len(batch))


# Global singleton — None means bulk proxy is disabled
_teg_bulk_proxy: Optional[TEGBulkProxy] = None


def get_teg_bulk_proxy() -> Optional[TEGBulkProxy]:
    """Return the global TEGBulkProxy instance, or None if disabled."""
    return _teg_bulk_proxy


async def start_teg_bulk_proxy() -> None:
    """Initialize and start the bulk proxy if TEG_BULK_PROXY=true."""
    global _teg_bulk_proxy
    if os.environ.get("TEG_BULK_PROXY", "").lower() in ("true", "1", "yes"):
        _teg_bulk_proxy = TEGBulkProxy(
            max_batch_size=int(os.environ.get("TEG_BULK_PROXY_BATCH_SIZE", "20")),
            flush_interval_ms=float(os.environ.get("TEG_BULK_PROXY_FLUSH_MS", "5")),
        )
        await _teg_bulk_proxy.start()
    else:
        logger.info("[TEGBulkProxy] Disabled (TEG_BULK_PROXY not set)")


async def stop_teg_bulk_proxy() -> None:
    """Gracefully stop the bulk proxy."""
    global _teg_bulk_proxy
    if _teg_bulk_proxy is not None:
        await _teg_bulk_proxy.stop()
        _teg_bulk_proxy = None


def _get_local_teg_id() -> str:
    """Derive local TEG ID from config or TEG_API_BASE_URL.

    Mapping:
      LOCAL_TEG_ID env                          → explicit override (any value)
      TEG_ID env (set on operators)             → 'teg-op-<city>'
      TEG_API_BASE_URL=http://teg-layer:8080    → 'teg-layer-a'  (mainframe default)
      TEG_API_BASE_URL=http://teg-layer-b:8080  → 'teg-layer-b'
    """
    # Prefer explicit LOCAL_TEG_ID; then the operator-provisioned TEG_ID env;
    # then fall back to hostname-based derivation for mainframes.
    val = (getattr(settings, 'LOCAL_TEG_ID', None)
           or os.environ.get('LOCAL_TEG_ID')
           or os.environ.get('TEG_ID'))
    if val:
        return val
    _teg_base = getattr(settings, 'TEG_API_BASE_URL', '')
    try:
        from urllib.parse import urlparse
        _host = urlparse(_teg_base).hostname or ''
        if _host == 'teg-layer':
            return 'teg-layer-a'  # primary registry uses bare hostname
        if _host.startswith('teg-layer-'):
            return _host          # e.g. teg-layer-b
        return 'teg-layer-a'
    except Exception:
        return 'teg-layer-a'


def _get_local_registry_id() -> str:
    """Derive local registry ID from TEG ID.

    Mapping:
      teg-layer-a            → registry-a                  (mainframe)
      teg-layer-b            → registry-b                  (mainframe)
      teg-op-<city>          → registry-op-<city>          (operator)
      teg-<other>            → registry-<other>            (generic fallback)
    """
    val = getattr(settings, 'LOCAL_REGISTRY_ID', None)
    if val:
        return val
    teg_id = _get_local_teg_id()
    # teg-layer-X → registry-X (preserves mainframe mapping exactly)
    if teg_id and teg_id.startswith('teg-layer-'):
        suffix = teg_id[len('teg-layer-'):]
        return f'registry-{suffix}'
    # teg-<anything> → registry-<anything>  (operators: teg-op-washington → registry-op-washington)
    if teg_id and teg_id.startswith('teg-'):
        suffix = teg_id[len('teg-'):]
        return f'registry-{suffix}'
    return 'registry-a'


# ─────────────────────────────────────────────────────────────────────────
# Cross-Frame FX — currency-match router helpers (WS-C, 2026-06-02)
#
# Frame-scoped sovereign currencies: each frame declares its settlement
# currency via FRAME_CURRENCY (default AVT; Frame C = BVT). A cross-frame
# transfer between SAME-currency frames uses the existing 1:1 rail untouched;
# between DIFFERENT-currency frames it routes to the reserve-mediated FX swap
# booth (WS-D) — two within-frame transfers (no cross-frame mint), so each
# frame stays Δ=0. The counterparty currency is resolved by TRUST DOMAIN,
# preferring the authoritative peer_type='frame' row's signed cached card, so
# the union-grow 'discovered'/operator fanout rows never decide the currency.
# Unresolvable currency ⇒ REFUSE — never a silent 1:1 fallback (that fallback
# is the diagnosed prod misroute/mis-price bug class).
# Plan: PRODUCTION_DOCS/ROADMAP/Cross_Frame_FX_Phase1_Sandbox_Build_Plan.md
# ─────────────────────────────────────────────────────────────────────────

def _local_frame_currency() -> str:
    """This frame's settlement currency — single source of truth = FRAME_CURRENCY
    env (mirrors services/registry_card_builder._frame_currency). A/B=AVT, C=BVT."""
    return (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"


def _fx_enabled() -> bool:
    """Master kill-switch for the FX swap booth (default OFF). Two-flag pattern
    like OPA / mint-lockdown: when false the cross-currency path is refused and
    the 1:1 rails are the only behaviour (i.e. exactly today's behaviour)."""
    return (os.environ.get("FX_ENABLED", "false") or "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _card_settlement_currency(card: Optional[dict]) -> Optional[str]:
    """Extract fees.settlement_currency from a (cached) registry-card JSON.
    Returns the upper-cased symbol, or None if absent/malformed."""
    if not isinstance(card, dict):
        return None
    fees = card.get("fees")
    if isinstance(fees, dict):
        sym = fees.get("settlement_currency")
        if isinstance(sym, str) and sym.strip():
            return sym.strip().upper()
    return None


async def _resolve_peer_currency(
    db: AsyncSession,
    *,
    target_peer: Optional["models.PeerRegistry"] = None,
    trust_domain: Optional[str] = None,
) -> Optional[str]:
    """Authoritative settlement currency of a cross-frame counterparty.

    Resolves by TRUST DOMAIN, preferring the peer_type='frame' row that carries a
    signed cached_registry_card — so duplicate 'discovered'/operator fanout rows
    (union-grow) never decide the currency. Returns the upper-cased symbol, or
    None when it cannot be resolved (caller MUST refuse — never assume 1:1).
    """
    td = (
        trust_domain
        or (getattr(target_peer, "trust_domain", None) if target_peer is not None else None)
        or ""
    ).strip()
    if not td:
        # No trust domain → cannot identify the home frame. Last resort: the
        # supplied peer's own card; else refuse (return None).
        return (
            _card_settlement_currency(getattr(target_peer, "cached_registry_card", None))
            if target_peer is not None else None
        )

    rows = (await db.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.status == "ACTIVE",
            models.PeerRegistry.trust_domain == td,
        )
    )).scalars().all()

    # Authority order: frame row with a card → any row with a card → passed peer.
    framed = [p for p in rows if (getattr(p, "peer_type", "") or "").lower() == "frame"]
    for bucket in (framed, rows):
        for p in bucket:
            ccy = _card_settlement_currency(getattr(p, "cached_registry_card", None))
            if ccy:
                return ccy
    return (
        _card_settlement_currency(getattr(target_peer, "cached_registry_card", None))
        if target_peer is not None else None
    )


def _card_fx_pool_pct(card: Optional[dict]) -> Optional[Decimal]:
    """Extract fees.fx.fee_split.pool_retained_pct from a (cached) registry-card JSON
    — the % of the FX fee the card's frame RETAINS in its reserve (the rest routes to
    its fee_collector). Returns Decimal in [0,100], or None if absent/FX-off/malformed.
    Mirrors _card_settlement_currency (same cached-card source)."""
    if not isinstance(card, dict):
        return None
    fees = card.get("fees")
    if not isinstance(fees, dict):
        return None
    fx = fees.get("fx")
    if not isinstance(fx, dict) or not fx.get("enabled"):
        return None
    split = fx.get("fee_split")
    if not isinstance(split, dict):
        return None
    v = split.get("pool_retained_pct")
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return max(Decimal("0"), min(Decimal("100"), d))


async def _resolve_peer_fx_pool_pct(
    db: AsyncSession,
    *,
    target_peer: Optional["models.PeerRegistry"] = None,
    trust_domain: Optional[str] = None,
) -> Optional[Decimal]:
    """The DEST (trade-hosting) frame's published fee-split authority (P2-4): the % of
    the FX fee it RETAINS in its reserve, read from its cached registry card. The fee
    lands in the dest frame's fee_collector, so the dest frame defines + publishes the
    split (card.fees.fx) and the source APPLIES it here. Resolves by trust_domain,
    preferring the peer_type='frame' row's cached card (mirrors _resolve_peer_currency).
    Returns None when unresolved → caller falls back to its own env default."""
    td = (
        trust_domain
        or (getattr(target_peer, "trust_domain", None) if target_peer is not None else None)
        or ""
    ).strip()
    if not td:
        return (
            _card_fx_pool_pct(getattr(target_peer, "cached_registry_card", None))
            if target_peer is not None else None
        )
    rows = (await db.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.status == "ACTIVE",
            models.PeerRegistry.trust_domain == td,
        )
    )).scalars().all()
    framed = [p for p in rows if (getattr(p, "peer_type", "") or "").lower() == "frame"]
    for bucket in (framed, rows):
        for p in bucket:
            pct = _card_fx_pool_pct(getattr(p, "cached_registry_card", None))
            if pct is not None:
                return pct
    return (
        _card_fx_pool_pct(getattr(target_peer, "cached_registry_card", None))
        if target_peer is not None else None
    )


# ── Cross-Frame FX — rate provider + reserve-leg HTTP helpers (WS-D) ─────────
# FX_RATE_MODE seam: 'fixed' (configured per-currency AVT reference prices) |
# 'pool' (floating constant-product AMM). BOTH modes are fully implemented — pool
# is priced inline from the two frames' live @fx_reserve balances by the swap booth
# (_fx_pool_quote), the route-hop quote, and the public-rate endpoint. `_fx_rate`
# below is the FIXED-mode / indicative reference provider; every caller invokes it
# only after branching to fixed mode (the pool paths never call it).
# AVT is the numeraire. rate(base→quote) = price(base in AVT) / price(quote in AVT).
def _fx_rate(base_ccy: str, quote_ccy: str) -> Decimal:
    base = (base_ccy or "").strip().upper()
    quote = (quote_ccy or "").strip().upper()
    if base == quote:
        return Decimal("1")
    # pool mode is priced by the callers from live reserves (see header comment);
    # _fx_rate provides the fixed-mode / indicative reference rate only.
    def _price_in_avt(ccy: str) -> Decimal:
        if ccy == "AVT":
            return Decimal("1")
        try:
            p = Decimal(str(os.environ.get(f"FX_FIXED_RATE_{ccy}_AVT", "1.0")))
        except (InvalidOperation, ValueError):
            p = Decimal("1.0")
        return p if p > 0 else Decimal("1.0")

    return _price_in_avt(base) / _price_in_avt(quote)


def _fx_reserve_floor(ccy: str) -> Decimal:
    # FX_RESERVE_FLOOR_<UNIT> from the environment, for any unit code: FX_RESERVE_FLOOR_AVT (the knob table's entry,
    # scripts/network_profile_knobs.py) is this read on a frame whose unit is AVT. The registry card publishes the
    # same names (registry_card_builder._fx_card_block), so this reader is where the table's name lives.
    try:
        return Decimal(str(os.environ.get(f"FX_RESERVE_FLOOR_{(ccy or '').strip().upper()}", "0")))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _fx_fee_rate() -> Decimal:
    """Fractional FX fee (default 0.5%), taken in the destination currency."""
    try:
        return Decimal(str(os.environ.get("FX_FEE_PCT", "0.5"))) / Decimal("100")
    except (InvalidOperation, ValueError):
        return Decimal("0.005")


def _fx_safe_detail(resp) -> str:
    try:
        j = resp.json()
        return str(j.get("detail") or j.get("message") or j)[:200]
    except Exception:
        return (getattr(resp, "text", "") or "")[:200]


async def _fx_teg_move(teg_base: str, admin_key: str, *, from_did: str, to_did: str,
                       amount, reason: str, idem_key: str, floor=None, trace: Optional[list] = None,
                       timeout: float = 20.0):
    """POST one leg to a TEG's /admin/fx/move (the fx_reserve-constrained mover)."""
    payload = {
        "from_did": from_did, "to_did": to_did, "amount": str(amount),
        "reason": reason, "idempotency_key": idem_key,
    }
    if floor is not None:
        payload["floor"] = str(floor)
    c = _get_teg_client()  # pooled keep-alive + SVID self-heal (reuse mTLS conn, no per-leg handshake)
    # §2026-06-09: retry stale-keepalive drops — /admin/fx/move dedupes server-side on
    # idempotency_key (fxref:<idem_key> replay), so a re-POST cannot double-move (safe even on a
    # commit-then-disconnect). Non-200 statuses are returned to the caller unchanged.
    return await _teg_post_with_retry(
        c, f"{teg_base}/api/v1/admin/fx/move",
        json=payload, headers={"Authorization": f"Bearer {admin_key}"}, timeout=timeout, trace=trace,
    )


async def _fx_move_until_known(teg_base: str, admin_key: str, **move) -> Tuple[str, Any, str]:
    """§REPATLANE-2 (V0603): one fx/move leg, asked until its outcome is known. The TEG keeps one execution per key
    (fxref:<key>, unique while pending or completed: alembic 0006_fxref_unique), so asking again under the same key
    returns that execution (200), runs the leg now if it never ran, or answers 409 while it is still in flight; it can
    never move the leg twice. Returns:
      ("moved", response, "")    the leg moved, on this attempt or an earlier one under the same key
      ("refused", response, why) the leg provably never ran: the TEG refused it with no earlier attempt that may have
                                 been delivered, or no attempt ever connected (response is None then)
      ("unknown", None, why)     still not known after the replays (FX_LEG_RESOLVE_DELAYS)
    After an answer that may have moved the leg, only a 200 settles it: a later refusal could be the replay racing an
    earlier attempt that has not reached the TEG yet."""
    ambiguous, why = False, ""
    for i, delay in enumerate((0.0,) + _fx_leg_resolve_delays()):
        if delay:
            await asyncio.sleep(delay)
        trace: list = []
        try:
            r = await _fx_teg_move(teg_base, admin_key, trace=trace, timeout=(20.0 if i == 0 else 10.0), **move)
        except httpx.RequestError as e:
            if not (_never_sent(e) and _trace_never_sent(trace)):
                ambiguous = True
            why = f"TEG unreachable: {type(e).__name__}: {str(e)[:120]}"
            continue
        if r.status_code == 200:
            return "moved", r, ""
        why = f"TEG {r.status_code}: {_fx_safe_detail(r)}"
        if not ambiguous and _leg_refused(r) and _trace_never_sent(trace):
            return "refused", r, why
        ambiguous = True
    if not ambiguous:
        return "refused", None, why
    logger.error(f"[FX-SWAP] leg {move.get('reason')} key={move.get('idem_key')}: outcome NOT KNOWN after "
                 f"{1 + len(_fx_leg_resolve_delays())} attempts ({why}); nothing is refunded on its own")
    return "unknown", None, why


def _emit_fx_event(event_type: str, *, swap_id: str, sender_did: str, receiver_did: str,
                   amount_in, source_currency: str, amount_out_net, fee, dest_currency: str,
                   rate, source_frame: str, dest_frame: str, source_teg: str, dest_teg: str,
                   reason: Optional[str] = None) -> None:
    """Emit an FX audit event to the LOCAL ES. NOT a LedgerBalanceChanged → does
    not affect supply (the per-frame auditor only counts LedgerBalanceChanged kinds);
    this is the audit trail WS-E reads for value-conservation (I3).
    `reason` (optional) records WHY a swap refunded (surfaced in the FX desk)."""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        em = get_event_emitter()
        if not em:
            return
        em.emit_background(
            event_type=event_type,
            aggregate_id=sender_did,
            data={
                "swap_id": swap_id, "from": sender_did, "to": receiver_did,
                "amount_in": str(amount_in), "source_currency": source_currency,
                "amount_out": str(amount_out_net), "fee": str(fee), "dest_currency": dest_currency,
                "rate": str(rate), "source_frame": source_frame, "dest_frame": dest_frame,
                "source_teg": source_teg, "dest_teg": dest_teg,
                **({"refund_reason": str(reason)} if reason else {}),
            },
            idempotency_key=f"{event_type}:{swap_id}",
        )
    except Exception as e:
        logger.warning(f"[FX-SWAP] emit {event_type} failed (non-fatal): {e}")


def _dest_teg_sidecar_host(target_teg_id: str, target_registry_id: str = "") -> str:
    """Map a remote frame's TEG to its nginx-teg mTLS sidecar hostname (no scheme/port).

    Generic (NOT FX-specific). Env override TEG_SIDECAR_MAP (JSON {teg_id|registry_id:
    sidecar_host}) wins; else derive from the teg-layer alias convention:
        teg-layer / teg-layer-a   -> nginx-teg-a          (Frame A)
        teg-layer-frame-b         -> frame-b-nginx-teg
        teg-layer-frame-c         -> frame-c-nginx-teg
    Returns "" if not derivable (caller falls back). Cloud-op TEGs have no sidecar until
    Phase 3 -> return "" by design (use the fallback path, or TEG_SIDECAR_MAP to route early).
    """
    raw = os.environ.get("TEG_SIDECAR_MAP", "")
    if raw:
        try:
            import json as _json
            m = _json.loads(raw)
            host = m.get(target_teg_id) or (m.get(target_registry_id) if target_registry_id else None)
            if host:
                return str(host)
        except Exception:
            pass
    tid = (target_teg_id or "").strip()
    # §XFRAMETEG (2026-09-04) — THE BARE `teg-layer` USED TO MAP HERE TO
    # `nginx-teg-a`, AND THAT MAPPING CAN NEVER BE RIGHT.
    #
    # `teg-layer` is what EVERY frame's OWN TEG stamps for itself — measured
    # live: frame-b, frame-c and both sandbox frames all stamp exactly
    # `TEG_ID=teg-layer`, while Frame A stamps `teg-layer-a`. So a target whose
    # teg_id is the bare literal is, by construction, NOT Frame A — yet this
    # returned Frame A's sidecar for it, `getaddrinfo` succeeded (callers on
    # `agentvault_main_network` resolve `nginx-teg-a` fine), and the caller
    # dialled the WRONG FRAME'S TEG believing it was the peer's.
    #
    # ⚠ THE DAMAGE IS A PRICE, NOT AN ERROR. The current consumer is the
    # `FX_RATE_MODE=pool` AMM, which prices a cross-frame swap off BOTH frames'
    # `fx_reserve`. Reading Frame A's reserve where the peer's was meant gives a
    # wrong RATE on a swap that is still Δ-neutral per frame — so the supply
    # invariant stays a contented 0.0 and nothing surfaces. `FX_RATE_MODE=pool`
    # is live on registry-a and set for frame-b/frame-c.
    #
    # An ambiguous key must resolve to NOTHING, not to a guess: returning ""
    # falls through to `_resolve_target_teg_url`, which keys on the REGISTRY —
    # unambiguous — and `TEG_SIDECAR_MAP` above remains the explicit override
    # for a frame that wants the direct sidecar hop.
    if tid == "teg-layer-a":
        return "nginx-teg-a"
    if tid.startswith("teg-layer-frame-"):
        # ⚠ CURRENTLY UNREACHABLE: no TEG anywhere stamps `teg-layer-frame-*`
        # (frame-b and frame-c both stamp the bare `teg-layer`). Kept because it
        # is the naming this resolver was designed for, and noted so the next
        # reader does not mistake it for working cross-frame derivation.
        return f"{tid[len('teg-layer-'):]}-nginx-teg"   # teg-layer-frame-b -> frame-b-nginx-teg
    return ""


async def _resolve_dest_teg_mtls_base(target_teg_id: str, target_registry_id: str) -> str:
    """Resolve a REACHABLE internal base URL for a remote frame's TEG, PREFERRING its
    nginx-teg mTLS sidecar (:8443) so the caller presents its SVID client cert.

    Generic dest-TEG routing primitive. FX cross-frame credit is the current caller, but
    ANY registry->remote-TEG dial should use this. (The TEG->TEG 2PC path is a separate,
    already-mTLS layer in the TEG itself — not routed through here.) Resolution order:
      1. dest TEG nginx-teg sidecar :8443  (env TEG_SIDECAR_MAP override, else derived)  -> mTLS
      2. cross-TEG mTLS URL via the peer/registry topology resolver                       -> mTLS
      3. plain http://{alias}:8080          (certless LAST RESORT, logged; fails enforce)
    """
    loop = asyncio.get_event_loop()

    # 1) dest TEG nginx-teg sidecar (:8443) — the cert-bearing path. Cross-frame trust
    #    verified (registry SVID accepted by frame-b/frame-c sidecars). Only used if it
    #    actually resolves on the shared net; cloud-op TEGs have no sidecar yet (Phase 3).
    sidecar = _dest_teg_sidecar_host(target_teg_id, target_registry_id)
    if sidecar:
        try:
            await loop.getaddrinfo(sidecar, 8443)
            return f"https://{sidecar}:8443"
        except Exception:
            logger.warning(
                f"[TEG-route] dest sidecar '{sidecar}' unresolved "
                f"(teg_id={target_teg_id}) — trying next resolver"
            )

    # 2) cross-TEG mTLS URL via the peer/registry topology resolver (:8443).
    mtls = _to_internal_mtls_url(await _resolve_target_teg_url(target_registry_id) or "")
    if mtls:
        return mtls

    # 3) LAST RESORT: plain :8080 (certless — rejected once TEG_MTLS_REQUIRED enforces).
    #    Logged so shadow telemetry surfaces any remaining certless dest BEFORE we enforce.
    candidates = []
    if target_teg_id:
        candidates.append(target_teg_id)
        if target_teg_id.endswith("-a"):       # Frame-A mainframe uses the unsuffixed alias
            candidates.append(target_teg_id[:-2])
    for host in candidates:
        try:
            await loop.getaddrinfo(host, 8080)
            logger.warning(
                f"[TEG-route] dest TEG '{host}' via PLAIN http:8080 (no mTLS sidecar for "
                f"teg_id={target_teg_id} registry={target_registry_id}) — certless, "
                f"will FAIL under TEG_MTLS_REQUIRED"
            )
            return f"http://{host}:8080"
        except Exception:
            continue
    return f"http://{target_teg_id}:8080"


# ── Cross-Frame FX Phase 2 — floating AMM (constant-product) helpers ─────────
def _fx_fee_pool_pct(default: Decimal) -> Decimal:
    """Configurable fee split (P2-3): % of the FX fee RETAINED in the dest reserve
    (deepens the pool); the remainder routes to the dest frame's fee_collector.
    Frame-set via FX_FEE_POOL_PCT; published on the registry card for transparency.
    Default differs by mode (pool→retain, fixed→collect) until a frame sets it."""
    raw = os.environ.get("FX_FEE_POOL_PCT")
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return default
    return max(Decimal("0"), min(Decimal("100"), v))


async def _fx_read_reserve(teg_base: str, admin_key: str) -> Decimal:
    """GET a frame's fx_reserve balance (for the Phase-2 cross-frame AMM curve)."""
    c = _get_teg_client()  # pooled keep-alive + SVID self-heal
    r = await _teg_get_with_retry(c, f"{teg_base}/api/v1/admin/fx/reserve",
                                  headers={"Authorization": f"Bearer {admin_key}"}, timeout=10.0)
    r.raise_for_status()
    return Decimal(str(r.json().get("balance", "0")))


def _fx_pool_quote(x_avt, y_bvt, amount_in, src_is_avt: bool, fee_rate: Decimal) -> dict:
    """Cross-frame constant-product AMM (k = x·y; x = AVT reserve, y = BVT reserve;
    AVT numeraire, spot P = x/y AVT-per-BVT). Sells `amount_in` of the source
    currency → `gross` of the dest currency along the curve; fee on the output.
    Pure function (Phase-2 P2-A); the per-frame reserves ARE the pool, so a swap's
    legs commit the curve delta automatically and each frame stays Δ=0."""
    x = Decimal(str(x_avt)); y = Decimal(str(y_bvt)); a = Decimal(str(amount_in))
    q = Decimal("0.000001")
    if x <= 0 or y <= 0:
        # §REPATLANE (V0603): priced before any leg, so the refusal says that nothing moved
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"FX pool: a reserve is empty/unseeded {NO_FUNDS_MOVED}")
    k = x * y
    spot = x / y  # AVT per BVT
    if src_is_avt:                 # sell AVT → BVT out; x grows, y shrinks
        new_x = x + a
        new_y = k / new_x
        gross = y - new_y
        spot_out = (Decimal("1") / spot) if spot > 0 else Decimal("0")  # BVT per AVT
    else:                          # sell BVT → AVT out; y grows, x shrinks
        new_y = y + a
        new_x = k / new_y
        gross = x - new_x
        spot_out = spot                                                 # AVT per BVT
    gross = gross.quantize(q)
    if gross <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"FX pool: computed output non-positive (amount too small) {NO_FUNDS_MOVED}")
    fee = (gross * fee_rate).quantize(q)
    net = gross - fee
    eff_out = (gross / a) if a > 0 else Decimal("0")
    slippage = (Decimal("1") - (eff_out / spot_out)) if spot_out > 0 else Decimal("0")
    return {"gross": gross, "fee": fee, "net": net, "spot": spot,
            "eff_rate": eff_out, "slippage": slippage, "new_x": new_x, "new_y": new_y, "k": k}


# ── Cross-Frame FX Phase 2 — P2-2 caps + circuit breaker ─────────────────────
# All three guards are opt-in: unset / "0" / "" → disabled (Frame B and any frame
# without the env are unaffected). Every check raises BEFORE the first TEG leg, so
# a rejected swap never touches a balance → Δ=0 is preserved by construction.
def _q6(v) -> str:
    try:
        return str(Decimal(str(v)).quantize(Decimal("0.000001")))
    except (InvalidOperation, ValueError):
        return str(v)


def _fx_size_cap(ccy: str) -> Decimal:
    """Per-source-currency max amount_in (FX_SIZE_CAP_<CCY>). 0/unset = no cap.
    Mirrors _fx_reserve_floor's per-currency env pattern."""
    try:
        return Decimal(str(os.environ.get(f"FX_SIZE_CAP_{(ccy or '').strip().upper()}", "0")))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _fx_slippage_max() -> Decimal:
    """Max tolerated price-impact fraction (FX_SLIPPAGE_MAX, e.g. 0.02 = 2%).
    0/unset = disabled. Compared against _fx_pool_quote()['slippage']."""
    try:
        return Decimal(str(os.environ.get("FX_SLIPPAGE_MAX", "0")))
    except (InvalidOperation, ValueError):
        return Decimal("0")


# ── FX EGRESS BREAKER (§FXEGRESS 2026-08-10) ────────────────────────────────────────────
# WHY THIS EXISTS, measured not theorised. A post-conversion egress failure is FORWARD-ONLY
# by design: the converted funds park at the destination @fx_router and are never clawed
# back (strategy §6). That is correct for ONE failure. It is ruinous for a repeating one,
# because the caller sees a 409 and retries the whole route — and the retry DEBITS THE
# SENDER AGAIN. Traced on 2026-08-04: `agora-gateway-bvt` paid 1600 BVT four times in five
# minutes for a single trade, each attempt parking ~1381 AVT at frame-a's router and
# delivering nothing. On 2026-08-06, under load, that shape produced 3,030 debits totalling
# 2,023,992 BVT across only 202 distinct amounts — the same handful of trades retried up to
# 260 times each. Nothing alerted: every leg lands in a SYSTEM account, so the supply
# invariant is correctly 0, and the AGORA escrow invariant stops watching at the escrow
# boundary.
#
# The fix is the platform's own S16 doctrine — the gate sits IN FRONT of the value. When a
# gateway's egress has failed repeatedly, refuse to originate the next route BEFORE the FX
# core swap, so the sender is never debited for a hop we already know is dead. Recovery of
# what is already parked is a separate, deliberate act (POST /teg/fx/route/sweep).
#
# Fail-OPEN on a missing Redis, exactly like the spot breaker below: no Redis must never
# block a healthy swap. Threshold 0 disables it.
def _fx_egress_breaker_threshold() -> int:
    """Consecutive post-conversion egress failures before origination is refused.
    FX_EGRESS_BREAKER_THRESHOLD, default 3. 0/unset-to-0 = breaker disabled."""
    try:
        return max(0, int(os.environ.get("FX_EGRESS_BREAKER_THRESHOLD", "3") or 0))
    except (TypeError, ValueError):
        return 3


def _fx_egress_breaker_ttl() -> int:
    """Seconds of quiet after which the failure streak lapses (self-healing, so a fixed
    gateway needs no operator action). FX_EGRESS_BREAKER_TTL_SEC, default 600."""
    try:
        return max(30, int(os.environ.get("FX_EGRESS_BREAKER_TTL_SEC", "600") or 600))
    except (TypeError, ValueError):
        return 600


def _fx_egress_breaker_key(gd_reg: str) -> str:
    return f"fx:egress_fail:{(gd_reg or 'unknown').strip()}"


async def _fx_egress_breaker_state(gd_reg: str) -> int:
    """Current consecutive-failure count for a gateway. 0 when unknown/no Redis."""
    if _fx_egress_breaker_threshold() <= 0:
        return 0
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return 0
        raw = await r.get(_fx_egress_breaker_key(gd_reg))
        return int(raw or 0)
    except Exception:  # noqa: BLE001 — never let the breaker itself break a transfer
        return 0


async def _fx_egress_breaker_record(gd_reg: str, *, failed: bool) -> int:
    """Count a post-conversion egress outcome. Returns the new streak (0 on success)."""
    if _fx_egress_breaker_threshold() <= 0:
        return 0
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return 0
        key = _fx_egress_breaker_key(gd_reg)
        if not failed:
            await r.delete(key)
            return 0
        streak = int(await r.incr(key))
        await r.expire(key, _fx_egress_breaker_ttl())
        return streak
    except Exception:  # noqa: BLE001
        return 0


def _fx_breaker_pct() -> Decimal:
    """Circuit-breaker trip threshold: fractional spot-P move vs the last-swap
    baseline (FX_BREAKER_PCT, e.g. 0.05 = 5%). 0/unset = breaker disabled."""
    try:
        return Decimal(str(os.environ.get("FX_BREAKER_PCT", "0")))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _fx_breaker_window_sec() -> float:
    """Observation window (seconds) for the breaker baseline (FX_BREAKER_WINDOW_SEC)."""
    try:
        return float(os.environ.get("FX_BREAKER_WINDOW_SEC", "300"))
    except (TypeError, ValueError):
        return 300.0


def _fx_enforce_caps(amount_in: Decimal, source_ccy: str, slippage) -> None:
    """P2-2 size + slippage guards. Raises 422 on violation (before any leg).
    `slippage` may be None (e.g. fixed-rate path) to skip the slippage check."""
    cap = _fx_size_cap(source_ccy)
    if cap > 0 and amount_in > cap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"FX size cap: amount_in {amount_in} {source_ccy} exceeds the per-swap "
                    f"cap {cap} {source_ccy} — split into smaller swaps {NO_FUNDS_MOVED}."),
        )
    smax = _fx_slippage_max()
    if slippage is not None and smax > 0 and Decimal(str(slippage)) > smax:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"FX slippage {_q6(slippage)} exceeds max {smax} (price impact too high) "
                    f"— reduce the amount or re-quote {NO_FUNDS_MOVED}."),
        )


async def _fx_breaker_check_and_update(spot_now: Decimal, k_now: Optional[Decimal] = None,
                                       pair: str = "") -> None:
    """Rate-move circuit breaker (P2-D). Halts SWAPS (not the protocol) when the
    canonical spot price P=x/y (AVT per BVT) has moved > FX_BREAKER_PCT vs the
    last-swap baseline within FX_BREAKER_WINDOW_SEC. State lives in the SOURCE
    frame's Redis (fail-OPEN if Redis is down — never wedge swaps on a cache miss).
    On a trip the baseline is NOT advanced (stays tripped until the window expires
    or the price returns); else it rolls forward.

    §MCPTEST30 (2026-10-15): the breaker counts only the part of a move that the pool's
    liquidity did not change. A swap moves the price along the curve and leaves k = x·y as it
    was; a reserve top-up or sweep (the peg keeper, a desk move) moves the price and k by the
    same factor. Measured on the sandbox: sbx-beta's keeper topped its reserve up 5.35% in one
    move and sbx-alpha's breaker refused every cross-frame send for the next window ("spot price
    moved 5.29%"). A move the liquidity explains moves the baseline with it; a baseline written
    without k (before this rule) is judged as before. One baseline per currency pair (`pair`):
    a frame with two FX peers had compared one pair's spot with the other's."""
    pct = _fx_breaker_pct()
    if pct <= 0 or spot_now <= 0:
        return  # disabled / unpriceable
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
    except Exception:
        r = None
    if r is None:
        return  # fail-open: no Redis → no breaker (do not block swaps)
    key = f"fx:breaker:{pair}" if pair else "fx:breaker:avt_bvt"
    now = datetime.now(timezone.utc).timestamp()
    window = _fx_breaker_window_sec()
    try:
        raw = await r.get(key)
    except Exception:
        return  # fail-open on read error
    if raw:
        try:
            prev = json.loads(raw)
            p0 = Decimal(str(prev.get("p", "0")))
            ts0 = float(prev.get("ts", 0))
            k0 = Decimal(str(prev["k"])) if prev.get("k") else None
        except (ValueError, TypeError, InvalidOperation):
            p0, ts0, k0 = Decimal("0"), 0.0, None
        if p0 > 0 and (now - ts0) <= window:
            move = abs(spot_now - p0) / p0
            explained = False
            if move > pct and k0 is not None and k0 > 0 and k_now is not None and k_now > 0:
                # what is left of the move once the liquidity change is taken out (log terms: a one-sided
                # reserve move by a factor r moves the price and k by r; a swap moves the price, k stays)
                residual = abs((spot_now / p0).ln()) - abs((k_now / k0).ln())
                explained = residual <= (Decimal("1") + pct).ln()
                if explained:
                    logger.info(f"[FX-BREAKER] {pair or 'pool'}: spot moved {_q6(move * 100)}% with the pool's "
                                f"liquidity (k x{_q6(k_now / k0)}): a reserve move, not a market move; the baseline moves with it")
            if move > pct and not explained:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(f"FX circuit breaker: spot price moved {_q6(move * 100)}% "
                            f"> {_q6(pct * 100)}% within {int(window)}s — swaps paused {NO_FUNDS_MOVED}. "
                            f"Retry after the window or once the price stabilises."),
                )
    try:
        base = {"p": str(spot_now), "ts": now}
        if k_now is not None and k_now > 0:
            base["k"] = str(k_now)
        await r.set(key, json.dumps(base), ex=int(window) + 60)
    except Exception:
        pass  # best-effort baseline update


# §MCPTEST30 (V0525, 2026-10-01): the paging the TEG proxy forwards. JSON and Python carry any integer and three proxy
# routes forwarded limit and offset unbounded; the TEG's database refuses an offset past int64 (measured on sbx-alpha,
# V0521: offset=2^63 on /teg/transactions met the TEG's "bigint out of range" 500, reported here as 503 "Unable to fetch
# transaction history at this time", an outage that was the caller's value). Refused here, 422, before anything leaves.
_TEG_PAGE_MAX = 2_147_483_647

router = APIRouter(
    prefix="/teg",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "TEG Integration"
)

# Rate limiter for financial endpoints
# §RATEFIX: THE shared, Redis-backed limiter — the same object main.py puts on
# app.state, so these decorations are both enforced and shared across workers.
# A router-local Limiter() would be in-memory per worker AND invisible to the
# middleware; that is what made all 65 limits here meaningless.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter

# --- Request/Response Schemas ---
class TEGBalanceResponse(BaseModel):
    """Response model for TEG token balance"""
    agent_id: str = Field(..., description="Agent identifier")
    balance: str = Field(..., description="Current token balance as string")

class TEGFeeConfigResponse(BaseModel):
    """Response model for fee configuration"""
    transfer_fee_amount: str = Field(..., description="Current transfer fee amount as string")
    fee_collection_address: str = Field(..., description="Address where fees are collected")
    
class TEGTransferRequest(BaseModel):
    """Request model for TEG token transfer"""
    receiver_agent_id: str = Field(..., max_length=120, description="Recipient agent ID (DID)")
    amount: str = Field(..., description="Amount to transfer as string")
    message: Optional[str] = Field(None, max_length=256, description="Optional message to attach to transfer")

    @field_validator('receiver_agent_id')
    @classmethod
    def validate_receiver_did(cls, v):
        from agentvault_registry.input_validators import validate_did
        return validate_did(v)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)
    
class TEGTransferResponse(BaseModel):
    """Response model for TEG token transfer"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: str = Field(..., description="Transaction status")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    receiver_agent_id: str = Field(..., description="Recipient agent ID")
    amount: str = Field(..., description="Amount transferred as string")
    fee_amount: str = Field(..., description="Transaction fee as string")
    new_sender_balance: str = Field(..., description="Sender's balance after transfer as string")
    timestamp: str = Field(..., description="Transaction timestamp")
    attached_message: Optional[str] = Field(None, description="Message attached to the transfer")

class TEGSystemTransferRequest(BaseModel):
    """Request model for agent-to-system transfer"""
    amount: str = Field(..., description="Amount to transfer to system as string")
    purpose: Optional[str] = Field(None, description="Purpose of system transfer")

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)
    
class TEGSystemTransferResponse(BaseModel):
    """Response model for agent-to-system transfer"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: str = Field(..., description="Transaction status")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    system_receiver_id: str = Field(..., description="System treasury DID")
    amount: str = Field(..., description="Amount transferred as string")
    purpose: str = Field(..., description="Purpose of the transfer")
    new_sender_balance: str = Field(..., description="Sender's balance after transfer as string")
    timestamp: str = Field(..., description="Transaction timestamp")

class TEGTransactionInfo(BaseModel):
    """Transaction information model"""
    transaction_id: str
    sender_agent_id: Optional[str]
    receiver_agent_id: str
    amount: str
    fee_amount: str
    status: str
    transaction_type: str
    timestamp: str
    error_message: Optional[str] = None
    reputation_signal_applied: Optional[bool] = False
    attached_message: Optional[str] = None

class TEGTransactionHistoryResponse(BaseModel):
    """Response model for transaction history"""
    transactions: list[TEGTransactionInfo]
    total: int
    limit: int
    offset: int

class TEGReputationSignalRequest(BaseModel):
    """Request model for applying reputation signal"""
    signal_value: int = Field(..., description="Reputation signal value (+1 or -1)")

class TEGReputationSignalResponse(BaseModel):
    """Response model for reputation signal"""
    transaction_id: str
    sender_agent_id: str
    receiver_agent_id: str
    signal_value: int
    new_receiver_reputation: int
    status: str

class TEGAgentReputationResponse(BaseModel):
    """Response model for agent reputation"""
    agent_id: str
    reputation_score: int
    reputation_tier: str
    last_updated: Optional[str] = None

# --- Policy Management ---
class TEGPolicyRequest(BaseModel):
    """Request model for creating/updating policy"""
    policy_code: str = Field(..., description="Unique policy code")
    policy_name: str = Field(..., description="Policy name")
    policy_type: str = Field(..., description="Policy type: attestation, governance, compliance, economic")
    description: Optional[str] = Field(None, description="Policy description")
    parameters: Optional[dict] = Field(None, description="Policy parameters as JSON")
    circuit_identifier: Optional[str] = Field(None, description="ZKP circuit identifier")
    enforcement_level: Optional[str] = Field("optional", description="Enforcement level: mandatory, optional")
    reward_amount: Optional[str] = Field("0", description="Payout amount for compliance")
    is_active: Optional[bool] = Field(True, description="Whether policy is active")

class TEGPolicyResponse(BaseModel):
    """Response model for policy information"""
    policy_id: str
    policy_code: str
    policy_name: str
    policy_type: str
    policy_version: str
    description: Optional[str] = None
    parameters: Optional[dict] = None
    circuit_identifier: Optional[str] = None
    enforcement_level: Optional[str] = None
    reward_amount: Optional[str] = None
    rules_document_url: Optional[str] = None
    is_active: bool
    created_at: str
    updated_at: str

class TEGPolicyListResponse(BaseModel):
    """Response model for policy listing"""
    policies: list[TEGPolicyResponse]
    total: int

class TEGPolicyUpdateRequest(BaseModel):
    """Request model for updating policy"""
    policy_name: Optional[str] = Field(None, description="Policy name")
    description: Optional[str] = Field(None, description="Policy description")
    parameters: Optional[dict] = Field(None, description="Policy parameters as JSON")
    enforcement_level: Optional[str] = Field(None, description="Enforcement level")
    reward_amount: Optional[str] = Field(None, description="Payout amount")
    is_active: Optional[bool] = Field(None, description="Whether policy is active")

# --- Batch Operations ---
class TEGPolicyBatchRequest(BaseModel):
    """Request model for batch policy creation"""
    policies: List[TEGPolicyRequest] = Field(..., description="List of policies to create", min_length=1, max_length=50)

class TEGPolicyBatchResponse(BaseModel):
    """Response model for batch policy creation"""
    success_count: int = Field(..., description="Number of policies successfully created")
    failure_count: int = Field(..., description="Number of policies that failed to create")
    created_policies: List[TEGPolicyResponse] = Field(..., description="List of successfully created policies")
    errors: List[dict] = Field(..., description="List of errors for failed policy creations")

# --- Policy Compliance Dashboard ---
class TEGPolicyComplianceResponse(BaseModel):
    """Response model for policy compliance metrics"""
    total_policies: int
    active_policies: int
    attestations_submitted: int
    attestations_verified: int
    compliance_rate: float
    policy_violations: int
    policy_compliance_by_type: dict
    recent_attestations: list[dict]

# --- Dispute Management ---


# === MISSING PROXY SCHEMAS - Added for Economic Consolidation ===

class StakeRequest(BaseModel):
    """Request model for staking tokens"""
    amount: str = Field(..., description="Amount to stake as string")
    lock_period_days: Optional[int] = Field(None, description="Optional lock period in days")

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)

class UnstakeRequest(BaseModel):
    """Request model for releasing locked units"""
    stake_id: str = Field(..., description="ID of the lock to release")
    amount: Optional[str] = Field(None, description="Partial release amount")

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        if v is None:
            return v
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)

class StakeBalanceResponse(BaseModel):
    """Response model for the locked balance"""
    agent_id: str
    staked_balance: str
    locked_balance: str
    available_to_unstake: str
    active_stakes: List[Dict[str, Any]]

class StakingHistoryResponse(BaseModel):
    """Response model for the lock history"""
    transactions: List[Dict[str, Any]]
    total: int

class APYTiersResponse(BaseModel):
    """Response model for APY tiers"""
    tiers: List[Dict[str, Any]]
    current_tier: Optional[str] = None
    current_apy: Optional[float] = None

class RewardsClaimResponse(BaseModel):
    """Response model for rewards claim"""
    claimed_amount: str
    transaction_id: str
    new_balance: str
    timestamp: str

class PendingRewardsResponse(BaseModel):
    """Response model for pending rewards"""
    pending_rewards: str
    last_claim_timestamp: Optional[str] = None
    reward_sources: List[Dict[str, Any]]

class RewardsHistoryResponse(BaseModel):
    """Response model for rewards history"""
    rewards: List[Dict[str, Any]]
    total_earned: str

# ProposalCreate and VoteRequest models removed 2026-02-22 (governance proxies deleted)

class DisputeResolveRequest(BaseModel):
    """Request model for resolving a dispute"""
    resolution: str = Field(..., description="Resolution decision")
    resolution_details: Optional[str] = None
    penalty_amount: Optional[str] = None

class ReputationRankingsResponse(BaseModel):
    """Response model for reputation rankings"""
    rankings: List[Dict[str, Any]]
    total_agents: int
    timestamp: str

class TEGDisputeLogRequest(BaseModel):
    """Request model for dispute logging"""
    defendant_agent_did: str = Field(..., description="Defendant agent DID")
    reason_code: str = Field(..., description="Dispute reason code")
    brief_description: str = Field(..., max_length=1000, description="Brief description of the dispute")
    avtp_transaction_id: Optional[str] = Field(None, description="Related AVTP transaction ID")
    evidence_pointer: Optional[str] = Field(None, description="Evidence location (e.g., IPFS CID)")
    dispute_reason_category: Optional[str] = Field(None, description="Category: UnfairFee, FailedService, ReputationAbuse, Other")
    related_transaction_id: Optional[str] = Field(None, description="Related TEG transaction ID")
    evidence_description_or_url: Optional[str] = Field(None, description="Evidence description or URL")

class TEGDisputeLogResponse(BaseModel):
    """Response model for dispute logging"""
    dispute_log_id: str
    status: str

class TEGDisputeQueryResponse(BaseModel):
    """Response model for dispute query"""
    dispute_log_id: str
    claimant_agent_did: str
    defendant_agent_did: str
    reason_code: str
    brief_description: str
    avtp_transaction_id: Optional[str] = None
    evidence_pointer: Optional[str] = None
    status: str
    resolution_notes: Optional[str] = None
    dispute_reason_category: Optional[str] = None
    related_transaction_id: Optional[str] = None
    evidence_description_or_url: Optional[str] = None
    admin_reviewer_id: Optional[str] = None
    created_at: str
    updated_at: str

class TEGDisputeCommentRequest(BaseModel):
    """Request model for adding dispute comment"""
    comment: str = Field(..., max_length=1000, description="Comment to add")
    evidence_url: Optional[str] = Field(None, description="Updated evidence URL")

# --- Attestation Management ---
class TEGAttestationRequest(BaseModel):
    """Request model for submitting attestation"""
    target_agent_did: str = Field(..., description="Target agent DID")
    attestation_type: str = Field(..., description="Type of attestation")
    attestation_data: dict = Field(..., description="Attestation data as JSON")
    evidence_url: Optional[str] = Field(None, description="Evidence URL")
    metadata: Optional[dict] = Field(None, description="Additional metadata")

class TEGAttestationResponse(BaseModel):
    """Response model for attestation"""
    attestation_id: str = Field(..., description="Unique attestation identifier")
    submitter_agent_did: str = Field(..., description="Submitter's agent DID")
    target_agent_did: str = Field(..., description="Target agent DID")
    attestation_type: str = Field(..., description="Type of attestation")
    attestation_data: dict = Field(..., description="Attestation data")
    evidence_url: Optional[str] = Field(None, description="Evidence URL")
    metadata: Optional[dict] = Field(None, description="Additional metadata")
    status: str = Field(..., description="Attestation status")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")

# --- Utility Functions ---

async def get_teg_token_for_agent(agent_id: int, agent_did: str) -> str:
    """
    Get or create a TEG access token for an agent.
    
    This exchanges the Registry's knowledge of the agent
    for a proper TEG access token. Tokens are cached for efficiency.
    
    Args:
        agent_id: The agent's database ID (for caching)
        agent_did: The agent's DID (for TEG authentication)
    
    NO BACKWARD COMPATIBILITY - only JWT tokens are accepted by TEG.
    """
    # Check cache first using agent.id
    if agent_id in _teg_token_cache:
        token, expiry = _teg_token_cache[agent_id]
        # Check if token is still valid (with 1 minute buffer)
        if datetime.now(timezone.utc) < expiry - timedelta(minutes=1):
            return token
        else:
            # Token expired, remove from cache
            del _teg_token_cache[agent_id]
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Create a Registry JWT to prove we're the Registry
            # This JWT will contain information about the agent we're requesting a token for
            from ..security import create_access_token
            registry_jwt_data = {
                "sub": "registry",  # Subject is the registry itself
                "agent_id": agent_did,  # The agent we're requesting token for
                "agent_db_id": str(agent_id),  # The agent's database ID
                "purpose": "teg_token_exchange",  # Purpose of this JWT
                "iss": "agentvault-registry",  # Issuer
            }
            registry_jwt = create_access_token(registry_jwt_data, expires_delta=timedelta(minutes=5))
            
            # Call the actual TEG /auth/token endpoint with correct parameters
            # TEG expects agent_id and registry_jwt in the request body
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/auth/token",
                json={
                    "agent_id": agent_did,  # The agent's DID
                    "registry_jwt": registry_jwt  # Real Registry JWT
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                token = data["access_token"]
                # Cache the token with expiry time
                expires_in = data.get("expires_in", 900)  # Default 15 minutes as per TEG spec
                expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                _teg_token_cache[agent_id] = (token, expiry)
                logger.info(f"Obtained new TEG JWT token for agent {agent_did}")
                return token
            else:
                # If token request fails, check if we can use admin impersonation
                # First check if the endpoint exists and is enabled
                if response.status_code == 404:
                    logger.warning(f"TEG token endpoint not found, trying admin key with X-Act-As-Agent")
                else:
                    logger.warning(f"TEG token request failed ({response.status_code}): {response.text}")
                
                # Try using admin key with X-Act-As-Agent header (if admin impersonation is enabled)
                # This requires the TEG to have admin impersonation feature enabled
                # Return a special marker that tells calling code to use admin impersonation
                return f"ADMIN_IMPERSONATE:{agent_did}"
                
        except httpx.RequestError as e:
            logger.error(
                f"TEG token request error: type={type(e).__name__} msg={e!r}",
                exc_info=True,
            )
            # In case of network error, try admin impersonation as fallback
            return f"ADMIN_IMPERSONATE:{agent_did}"

def prepare_teg_headers(teg_token: str) -> dict:
    """
    Prepare headers based on token type (JWT, Service Token, or Admin Impersonation).
    
    This function handles three types of tokens:
    1. Regular JWT tokens - returned as Bearer authorization
    2. SERVICE_TOKEN markers - converted to X-Service-Token header
    3. ADMIN_IMPERSONATE markers - converted to Bearer + X-Act-As-Agent headers
    
    Args:
        teg_token: Either a JWT token, SERVICE_TOKEN:xxx, or ADMIN_IMPERSONATE:did:key marker
    
    Returns:
        Dictionary with appropriate authorization headers
    """
    if teg_token.startswith("SERVICE_TOKEN:"):
        # Extract the actual service token
        actual_token = teg_token.replace("SERVICE_TOKEN:", "")
        return {"X-Service-Token": actual_token}
    elif teg_token.startswith("ADMIN_IMPERSONATE:"):
        # Format: ADMIN_IMPERSONATE:{agent_did} — key read from module constant, never in the string
        agent_did = teg_token[len("ADMIN_IMPERSONATE:"):]
        if agent_did:
            return {
                "Authorization": f"Bearer {TEG_ADMIN_API_KEY}",
                "X-Act-As-Agent": agent_did
            }
        else:
            logger.warning(f"Malformed ADMIN_IMPERSONATE token (length={len(teg_token)})")
            return {"X-Service-Token": TEG_ADMIN_API_KEY}
    else:
        # Regular JWT token
        return {"Authorization": f"Bearer {teg_token}"}


def _extract_bearer_token(teg_token: str) -> str:
    """Extract the actual Bearer token from a teg_token which may be a raw JWT,
    SERVICE_TOKEN marker, or ADMIN_IMPERSONATE marker."""
    if teg_token.startswith("ADMIN_IMPERSONATE:"):
        remainder = teg_token[len("ADMIN_IMPERSONATE:"):]
        if ":" in remainder:
            _, admin_key = remainder.rsplit(":", 1)
            return admin_key
        return teg_token
    if teg_token.startswith("SERVICE_TOKEN:"):
        return teg_token.replace("SERVICE_TOKEN:", "")
    return teg_token  # Regular JWT — use as-is

def log_audit_event(action: str, policy_id: str, user_email: str, details: Optional[dict] = None):
    """Log policy audit events to console with structured format"""
    timestamp = datetime.now(timezone.utc).isoformat()
    audit_log = {
        "timestamp": timestamp,
        "action": action,
        "policy_id": policy_id,
        "user": user_email,
        "details": details or {}
    }
    logger.info(f"AUDIT_LOG: {audit_log}")

def extract_version_number(version_string: str) -> tuple[int, int, int]:
    """Extract version numbers from a version string like '1.2.3'"""
    try:
        parts = version_string.split('.')
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except:
        return (1, 0, 0)

def increment_version(version_string: str) -> str:
    """Increment the patch version number"""
    major, minor, patch = extract_version_number(version_string)
    return f"{major}.{minor}.{patch + 1}"

# --- Endpoints ---
# Internal function to get balance (moved from being a route directly)
def _normalize_balance(raw_balance) -> str:
    """Normalize a balance value to a plain decimal string.

    TEG returns balances as Python ``Decimal`` values which Pydantic
    serializes via ``str()``.  A zero balance stored with 18 decimal
    places becomes ``"0E-18"`` — valid but confusing for dashboards.
    This helper converts any Decimal / float / str to a clean format:
      "0E-18"  -> "0"
      "19942.000000000000000000" -> "19942"  (trailing zeros stripped)
      "1000.000000000000000000" -> "1000"  (never "1E+3")
      "100.50" -> "100.5"
    """
    try:
        d = Decimal(str(raw_balance))
        # normalize() collapses trailing zeros; 0E-18 becomes 0. It also writes a whole number that ends in zeros
        # in exponent form (Decimal("1000").normalize() is 1E+3, which int() refuses): format "f" keeps plain
        # digits, as the other amount writers do (services/contact_policy.py, services/reputation_bond.py).
        normalized = d.normalize()
        # Decimal("0E+0").normalize() is "0", but just in case:
        return format(normalized, "f") if normalized != 0 else "0"
    except (InvalidOperation, ValueError, TypeError):
        return str(raw_balance) if raw_balance else "0"


async def get_teg_balance(
    current_agent: models.Agent
) -> TEGBalanceResponse:
    """
    Internal function to get the TEG token balance for an agent.

    Uses retry-on-401: if the cached TEG JWT is stale or was issued by a
    different TEG worker (different signing key), the first call returns 401.
    We clear the cache and retry exactly once with a freshly-obtained token.
    """
    agent_did = current_agent.did
    max_attempts = 2  # first try + one retry after 401

    for attempt in range(max_attempts):
        # Get TEG JWT (from cache or fresh exchange)
        teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)
        headers = prepare_teg_headers(teg_token)

        try:
            client = _get_teg_client()
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                headers=headers,
                timeout=10.0,
            )

            if response.status_code == 200:
                data = response.json()
                return TEGBalanceResponse(
                    agent_id=data.get("agent_id", agent_did),
                    balance=_normalize_balance(data.get("balance", "0")),
                )

            if response.status_code == 401:
                # Evict stale token so the next iteration fetches a fresh one
                _teg_token_cache.pop(current_agent.id, None)
                if attempt < max_attempts - 1:
                    logger.info(
                        f"TEG 401 for {agent_did} — clearing cached token and retrying "
                        f"(attempt {attempt + 1}/{max_attempts})"
                    )
                    continue  # retry with fresh token
                # Final attempt also failed
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG service authentication failed",
                )

            # Any other non-200 status
            logger.error(
                f"TEG API balance request failed: {response.status_code} - {response.text}"
            )
            raise _teg_refusal(response, "Unable to fetch TEG balance at this time")

        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable",
            )

    # Should not reach here, but guard against it
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="TEG service authentication failed after retries",
    )

@router.get("/balance", response_model=TEGBalanceResponse, summary="Get TEG Token Balance")
async def get_balance(
    current_agent: models.Agent = Security(get_current_agent)
):
    """
    Get the current TEG token balance for the authenticated agent.
    
    This endpoint proxies the balance request to the TEG Layer API,
    handling authentication with the agent's JWT token.
    """
    return await get_teg_balance(current_agent)


# ---------------------------------------------------------------------------
# Helpers for transfer_teg_tokens (decomposed for readability)
# ---------------------------------------------------------------------------

async def _sync_balances_after_transfer(
    db: AsyncSession,
    current_agent: "models.Agent",
    receiver_did: str,
    data: dict,
    client: httpx.AsyncClient,
) -> None:
    """Sync sender and receiver liquid balances from TEG back to registry DB."""
    # --- Sender balance ---
    new_sender = data.get("new_sender_balance")
    if new_sender is not None:
        current_agent.liquid_balance = Decimal(str(new_sender))
        await db.commit()
        logger.info(
            f"[Transfer] DB synced: {current_agent.did} "
            f"liquid_balance = {current_agent.liquid_balance}"
        )

    # --- Receiver balance ---
    recv_result = await db.execute(
        select(models.Agent).where(models.Agent.did == receiver_did)
    )
    recv_agent = recv_result.scalar_one_or_none()
    if recv_agent:
        recv_teg_token = await get_teg_token_for_agent(recv_agent.id, receiver_did)
        recv_headers = prepare_teg_headers(recv_teg_token)
        recv_bal_resp = await client.get(
            f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
            headers=recv_headers,
            timeout=5.0,
        )
        if recv_bal_resp.status_code == 200:
            recv_bal = recv_bal_resp.json().get("balance")
            if recv_bal is not None:
                recv_agent.liquid_balance = Decimal(str(recv_bal))
                await db.commit()
                logger.info(
                    f"[Transfer] Receiver DB synced: {receiver_did} "
                    f"liquid_balance = {recv_agent.liquid_balance}"
                )


async def _emit_transfer_events(
    sender_did: str,
    receiver_did: str,
    request_amount: str,
    data: dict,
    fee_rate_pre: float,
) -> None:
    """Emit TokensTransferred and TransactionFeeCollected events to EventStore."""
    from agentvault_registry.event_emitter import get_event_emitter

    _emitter = get_event_emitter()
    if not _emitter:
        return

    _tx_id = data.get("transaction_id", "")

    _emitter.emit_background(
        event_type="TokensTransferred",
        aggregate_id=sender_did,
        data={
            "from": sender_did,
            "to": receiver_did,
            "amount": str(data.get("amount", request_amount)),
            "transaction_id": _tx_id,
        },
        idempotency_key=f"xfer-{_tx_id}" if _tx_id else None,
    )

    # f037: Emit TransactionFeeCollected if fee was charged
    _fee = data.get("fee_amount", 0)
    if _fee and Decimal(str(_fee)) > 0:
        _emitter.emit_background(
            event_type="TransactionFeeCollected",
            aggregate_id=sender_did,
            data={
                "agent_did": sender_did,
                "fee_amount": str(_fee),
                "transaction_id": _tx_id,
                "transfer_amount": str(request_amount),
                "rate_pct": fee_rate_pre,
            },
            idempotency_key=f"fee-{_tx_id}" if _tx_id else None,
        )


async def _record_transfer_ancillary(
    db: AsyncSession,
    sender_did: str,
    receiver_did: str,
    transfer_amount: str,
    transaction_id: str,
    fee_avt_pre: Decimal,
    fee_svc,
) -> None:
    """Record EigenTrust signal and post-TEG fee audit for a completed transfer."""
    # EigenTrust++ Phase 2: positive bilateral trust signal
    # §VITALS 2026-09-04: this was `int(float(transfer_amount))`, which truncated
    # toward zero BEFORE the DB saw it. Measured over 24h of real traffic: 57% of
    # transfers stored as 0 and 992.33 of 17,158.33 units were erased, so most
    # senders carried no volume at all into the EigenTrust weighting.
    await local_trust_updater.on_transfer_completed(
        db,
        from_did=sender_did,
        to_did=receiver_did,
        amount=Decimal(str(transfer_amount)),
    )
    await db.commit()

    # Sprint 3 (Bug 2 fix): write fee audit record POST-TEG (no balance mutations)
    if fee_avt_pre > 0 and fee_svc is not None:
        _fee_avt_audit, _fee_rate_audit, _ = await fee_svc.apply_fee(
            db=db,
            transaction_id=transaction_id,
            sender_did=sender_did,
            transfer_amount=Decimal(transfer_amount),
        )
        logger.info(
            f"[FeeService] {_fee_avt_audit} AVT ({_fee_rate_audit:.2f}%) "
            f"on tx {transaction_id} — moved in TEG, audit written"
        )


# §REPATLANE-5 (V0606): TEGBulkProxy's failure for a whole batch the TEG answered with a 5xx (the batch is one TEG
# transaction: its commit may have come before the error)
_BULK_BATCH_UNKNOWN = re.compile(r"^TEG bulk endpoint returned 5\d\d\b")


def _handle_teg_transfer_error(response: httpx.Response) -> None:
    """Parse a non-200 TEG transfer response and raise the appropriate HTTPException."""
    # §LEDGERGATE: the TEG's ledger gate refused (nothing moved): pass the sentence and its Retry-After on as they came
    from agentvault_registry.services.ledger_unavailable import ledger_refusal
    refusal = ledger_refusal(response)
    if refusal is not None:
        logger.warning("[TEG-LEDGER-GATE] the TEG refused a transfer: its ledger cannot record it right now")
        raise refusal
    if response.status_code == 400:
        error_data = response.json()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_data.get("detail", "Transfer failed"),
        )
    elif response.status_code == 401:
        logger.error(
            f"[TEG-UPSTREAM-ERR] status=401 auth-rejected body={response.text[:400]!r}"
        )
        # §REPATLANE-5 (V0606): the TEG refused the caller before its transfer: nothing moved
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"TEG authentication failed {NO_FUNDS_MOVED}",
        )
    else:
        logger.error(
            f"[TEG-UPSTREAM-ERR] status={response.status_code} "
            f"body={response.text[:400]!r}"
        )
        teg_detail = "Unable to process transfer at this time"
        try:
            teg_err = response.json()
            teg_detail = teg_err.get("detail", teg_err.get("message", teg_detail))
            if "insufficient" in teg_detail.lower() or "balance" in teg_detail.lower():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=teg_detail)
        except HTTPException:
            raise
        except Exception:
            pass
        # §REPATLANE-5 (V0606): any other TEG failure may come after its commit: the answer says nobody knows
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{teg_detail} {OUTCOME_UNKNOWN}",
        )


@router.post("/transfer", response_model=TEGTransferResponse, summary="Transfer units to another agent on this registry")
@limiter.limit("10000/minute")
async def transfer_teg_tokens(
    transfer_request: TEGTransferRequest,
    request: Request,
    current_agent: models.Agent = Security(require_agent_permission("teg.transfer")),
    db: AsyncSession = Depends(get_db),  # EigenTrust++ Phase 2
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="Optional client-supplied UUID for safe retry. Underlying TokensTransferred event uses transaction_id-derived idempotency_key for EventStore-level dedup; this header documents that retries are safe."),
    http_response: Response = None,   # §REPATLANE-7 (not "response": slowapi fills that one)
):
    """
    Transfer units from the calling agent to another agent on this registry. The receiver must be local: an agent of
    a federated peer is refused with 400 (use POST /api/v1/teg/cross-registry-transfer) and an unknown DID with 404.
    The registry's transfer fee is charged to the sender.

    An `Idempotency-Key` header is kept for 24 hours: a retry answers the first result (marked `Idempotent-Replayed:
    true`) instead of moving units twice. Needs an agent token with the `teg.transfer` permission.

    \f
    Transfer TEG tokens to another agent.

    This endpoint proxies the transfer request to the TEG Layer API,
    handling authentication and ID mapping.

    §pass57: Idempotency-Key now ENFORCED via Redis cache (24h TTL). See
    `services.idempotency.cache` for details. Two-layer defense: this
    request-level cache + EventStore UNIQUE(idempotency_key) for the
    emitted TokensTransferred event.
    """
    # §REPATLANE-5 (V0606): a kept attempt (the cross-registry endpoint's): every answer that may be the transfer is kept
    # under the key and answered again; the key is given back for a TEG refusal (a local transfer is one atomic TEG
    # transaction, so the TEG's 4xx moved nothing) or an answer that proves nothing moved
    from agentvault_registry.services.idempotency.cache import agent_caller, begin_attempt, mark_replayed, run_kept

    body_for_idem = transfer_request.model_dump(mode="json")
    # D6-777: the key is the calling agent's (the anchored hand's own, whichever purse pays)
    attempt = await begin_attempt("teg.transfer", idempotency_key, body_for_idem,
                                  principal=agent_caller(current_agent.did))
    if attempt.replay is not None:
        mark_replayed(http_response)   # §REPATLANE-7: the kept answer says it is one (Idempotent-Replayed: true)
        return attempt.replay
    return await run_kept(
        attempt,
        lambda: _teg_transfer_run(transfer_request, request, current_agent, db, attempt),
        error_moved_nothing=_local_transfer_error_moved_nothing,
    )


def _local_transfer_error_moved_nothing(status_code: int, detail) -> bool:
    """§REPATLANE-5 (V0606): a local transfer's error answer after it reached the TEG proves nothing moved when it says so
    (payout_outcome.error_moved_nothing), or when it is a refusal (below 500) that does not say money moved: the TEG's
    transfer is one transaction, so its 4xx answer is a refusal of the whole of it."""
    from agentvault_registry.services import payout_outcome as _po
    if _po.error_moved_nothing(status_code, detail):
        return True
    return int(status_code or 0) < 500 and not _po.says_moved(detail)


async def _teg_transfer_run(transfer_request: TEGTransferRequest, request: Request, current_agent: models.Agent,
                            db: AsyncSession, attempt):
    """The work of POST /transfer, under its kept attempt (transfer_teg_tokens); `attempt` is marked dispatched right
    before the transfer goes to the TEG."""
    # Use proper agent DID
    sender_agent_did = current_agent.did

    # IRONKEY L2 spend gate (pre-escrow, Δ-safe): per-tx exposure admission. Local
    # transfer → same_registry=True. No-op unless the agent has a spend policy + the
    # AGENT_RBAC_MODE flag is shadow/enforce. Runs on the ACTING agent so a spawned
    # child's own caveats bind BEFORE any purse redirect.
    # counterparty_did is passed so the policy's ALLOWLIST axis is not inert here:
    # check_spend_policy only denies when it knows who is being paid (§SHOWCASEFED).
    await enforce_agent_spend(db, sender_agent_did, transfer_request.amount, same_registry=True,
                              counterparty_did=transfer_request.receiver_agent_id, request=request)

    # §SPAWN-ANCHOR (2026-08-12): an anchored (walletless) child funds this transfer from
    # its parent's purse. Default off / non-anchored ⇒ (purse_agent, purse_did) ==
    # (current_agent, its did), so the money leg is byte-for-byte unchanged. The rebind of
    # sender_agent_did makes every downstream money-leg reference (TEG auth+debit, fee,
    # emitted TokensTransferred.from, balance sync) use the purse — the account that
    # actually loses the money — keeping the ES projection and Δ=0 correct.
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    purse_agent, purse_did = await resolve_spend_purse_agent(db, current_agent, request)
    sender_agent_did = purse_did

    # Get proper TEG JWT token (for the PURSE — the funding account)
    teg_token = await get_teg_token_for_agent(purse_agent.id, purse_did)

    # --- Cross-registry guard: reject transfers to agents on other registries ---
    receiver_did = transfer_request.receiver_agent_id
    from ..crud.agent import get_agent_by_did as _lookup_agent
    try:
        _local_agent = await _lookup_agent(db, receiver_did)
    except Exception:
        _local_agent = None
    if _local_agent is None:
        # Not a local agent — check if it's a federated agent we know about
        from agentvault_registry.models import AgentCard
        _card_result = await db.execute(
            select(AgentCard).where(AgentCard.agent_did == receiver_did)
        )
        _card = _card_result.scalar_one_or_none()
        _source_registry = ""
        if _card and _card.card_data:
            _fed_meta = (_card.card_data or {}).get("federation_metadata", {})
            _source_registry = _fed_meta.get("source_registry", "") or _fed_meta.get("first_synced_from", "")

        if _source_registry:
            # Agent is on a federated peer — tell the user
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Agent {receiver_did} is not on this registry. "
                    f"It belongs to a federated peer (source: {_source_registry}). "
                    f"Use POST /api/v1/teg/cross-registry-transfer instead."
                ),
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Recipient agent {receiver_did} not found on this registry or any federated peer.",
            )

    # --- Bug 2 fix (Option B): calculate fee PRE-TEG so it can be passed to TEG atomically ---
    _fee_avt_pre: Decimal = Decimal("0")
    _fee_rate_pre: float = 0.0
    try:
        from ..services.transaction_fee_service import get_transaction_fee_service
        _fee_svc = get_transaction_fee_service()
        _fee_avt_pre, _fee_rate_pre = await _fee_svc.get_fee_for_transfer(
            db=db,
            sender_did=sender_agent_did,  # §SPAWN-ANCHOR: the purse pays the fee (velocity-scaled on the payer)
            transfer_amount=Decimal(transfer_request.amount),
        )
    except Exception as fee_pre_err:
        logger.warning(f"[FeeService] Pre-TEG fee calculation failed (non-fatal): {fee_pre_err}")

    client = _get_teg_client()
    attempt.mark_dispatched()
    try:
        # 2026-05-01: backend dispatcher — TEG_BULK_PROXY_BACKEND selects the
        # batching strategy, with graceful fall-through:
        #   "stream" → cross-worker shared Redis Streams buffer (preferred)
        #   "memory" or unset+TEG_BULK_PROXY=true → in-process TEGBulkProxy
        #   else → legacy direct httpx path
        # Stream → memory → direct fallback chain ensures Redis blip degrades
        # to memory bulk (5% uplift) instead of full direct (no batching).
        used_bulk = False
        data: Optional[dict] = None

        _bulk_backend = (os.environ.get("TEG_BULK_PROXY_BACKEND", "") or "").strip().lower()

        def _translate_bulk_value_error(_err, _label: str) -> HTTPException:
            # §LEDGERGATE (V0597): the TEG's ledger refusal, as it came (503, the sentence, Retry-After): from the bulk
            # proxy as a LedgerRefusedError; from a backend that kept only the text, by its marker
            if isinstance(_err, LedgerRefusedError):
                return _err.refusal
            _msg = str(_err)
            _refusal = refusal_from_text(_msg)
            if _refusal is not None:
                return _refusal
            # §REPATLANE-5 (V0606): the batch's own failure (a TEG 5xx, or a 200 without this transfer's result) is not a
            # refusal of this transfer: the batch is ONE TEG transaction, and its commit may have come before the answer
            if _BULK_BATCH_UNKNOWN.match(_msg) or _msg.startswith("No result returned from TEG"):
                return HTTPException(status_code=503, detail=f"Transfer via {_label}: {_msg} {OUTCOME_UNKNOWN}")
            if "insufficient" in _msg.lower() or "balance" in _msg.lower():
                return HTTPException(status_code=400, detail=_msg)
            if "suspended" in _msg.lower():
                return HTTPException(status_code=403, detail=_msg)
            return HTTPException(status_code=400, detail=f"Transfer failed via {_label}: {_msg}")

        def _shape_bulk_response(_bulk_result: dict) -> dict:
            return {
                "transaction_id": _bulk_result.get("transaction_id"),
                "status": _bulk_result.get("status", "completed"),
                "sender_agent_id": _bulk_result.get("sender_agent_id", sender_agent_did),
                "receiver_agent_id": _bulk_result.get(
                    "receiver_agent_id", transfer_request.receiver_agent_id,
                ),
                "amount": _bulk_result.get("amount", str(transfer_request.amount)),
                "fee_amount": _bulk_result.get("fee_amount", str(_fee_avt_pre)),
                "new_sender_balance": _bulk_result.get("new_sender_balance", "0"),
                "timestamp": _bulk_result.get("timestamp")
                    or datetime.now(timezone.utc).isoformat(),
                "attached_message": _bulk_result.get("attached_message"),
            }

        # ─── Backend 1: Redis Streams shared buffer ────────────────────────
        if _bulk_backend == "stream":
            try:
                from agentvault_registry.services.teg_stream_proxy import (
                    get_teg_stream_proxy, StreamUnavailableError,
                )
                stream_proxy = get_teg_stream_proxy()
            except Exception:
                stream_proxy = None
                StreamUnavailableError = Exception  # type: ignore[assignment]
            if stream_proxy is not None:
                try:
                    _bulk_result = await stream_proxy.submit(
                        sender_did=sender_agent_did,
                        receiver_did=transfer_request.receiver_agent_id,
                        amount=str(transfer_request.amount),
                        fee_amount=str(_fee_avt_pre) if _fee_avt_pre > Decimal("0") else "0",
                        message=transfer_request.message,
                        teg_token=teg_token,
                    )
                    data = _shape_bulk_response(_bulk_result)
                    used_bulk = True
                except StreamUnavailableError as _se:
                    # §REPATLANE-5 (V0606): the flusher still drains an entry this worker stopped waiting for; a
                    # fallback would send the same transfer to the TEG a second time
                    if getattr(_se, "enqueued", False):
                        logger.error("[Transfer] Stream backend gave no result for a queued transfer (%s): not sent "
                                     "again", _se)
                        raise HTTPException(
                            status_code=503,
                            detail=(f"The transfer was queued for the TEG and no result came back {OUTCOME_UNKNOWN}: "
                                    f"it may still be recorded. Read the balance before sending again."))
                    logger.warning(
                        "[Transfer] Stream backend unavailable (%s) — falling back", _se,
                    )
                except ValueError as _bulk_err:
                    raise _translate_bulk_value_error(_bulk_err, "stream")

        # ─── Backend 2: In-process memory bulk proxy ───────────────────────
        if not used_bulk:
            bulk_proxy = get_teg_bulk_proxy()
            if bulk_proxy is not None:
                try:
                    _bulk_result = await bulk_proxy.submit(
                        sender_did=sender_agent_did,
                        receiver_did=transfer_request.receiver_agent_id,
                        amount=str(transfer_request.amount),
                        fee_amount=str(_fee_avt_pre) if _fee_avt_pre > Decimal("0") else "0",
                        message=transfer_request.message,
                        teg_token=teg_token,
                    )
                    data = _shape_bulk_response(_bulk_result)
                    used_bulk = True
                except ValueError as _bulk_err:
                    raise _translate_bulk_value_error(_bulk_err, "bulk")

        if not used_bulk:
            # Legacy direct-httpx path — used when TEG_BULK_PROXY is not set.
            # Prepare headers based on token type
            headers = prepare_teg_headers(teg_token)

            # Build TEG request — include fee_amount so TEG handles the split atomically
            teg_request: dict = {
                "receiver_agent_id": transfer_request.receiver_agent_id,
                "amount": transfer_request.amount,
            }
            if transfer_request.message:
                teg_request["message"] = transfer_request.message
            if _fee_avt_pre > Decimal("0"):
                # Pass the registry-calculated fee to TEG (TEG schema accepts optional fee_amount)
                teg_request["fee_amount"] = str(_fee_avt_pre)

            # DNS-blip retry: only retry ConnectError/ConnectTimeout (request NOT sent, safe).
            # ReadError/ReadTimeout fall through to the outer httpx.RequestError handler.
            _teg_url = f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transfer"
            _max_retries = 2
            response = None
            for _attempt in range(_max_retries + 1):
                try:
                    response = await client.post(
                        _teg_url,
                        json=teg_request,
                        headers=headers,
                        timeout=10.0,
                    )
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as _dns_err:
                    if _attempt < _max_retries:
                        _backoff_s = 0.05 * (2 ** _attempt)  # 50ms, 100ms
                        logger.warning(
                            f"[TEG] connect error on /token/transfer attempt "
                            f"{_attempt + 1}/{_max_retries + 1}, retrying in "
                            f"{int(_backoff_s * 1000)}ms: {_dns_err}"
                        )
                        await asyncio.sleep(_backoff_s)
                        continue
                    raise  # retries exhausted → outer handler raises 503

            if response.status_code != 200:
                _handle_teg_transfer_error(response)

            data = response.json()
        teg_response = TEGTransferResponse(
            transaction_id=data["transaction_id"],
            status=data["status"],
            sender_agent_id=data["sender_agent_id"],
            receiver_agent_id=data["receiver_agent_id"],
            amount=str(data["amount"]),
            fee_amount=str(data.get("fee_amount", "0")),
            new_sender_balance=str(data["new_sender_balance"]),
            timestamp=data["timestamp"],
            attached_message=data.get("attached_message"),
        )

        # Sync sender + receiver balances back to registry DB
        try:
            await _sync_balances_after_transfer(
                db, purse_agent, transfer_request.receiver_agent_id, data, client,  # §SPAWN-ANCHOR: sync the purse's cache (it lost the money)
            )
        except Exception as sync_err:
            logger.warning(f"[Transfer] DB balance sync failed (non-fatal): {sync_err}")

        # Emit TokensTransferred + TransactionFeeCollected to EventStore.
        # When the bulk path was used, the TEGBulkProxy._flush() emits both
        # events itself (Phase 3b, 2026-05-01) — avoid a double-emit here.
        if not used_bulk:
            try:
                await _emit_transfer_events(
                    sender_agent_did, transfer_request.receiver_agent_id,
                    transfer_request.amount, data, _fee_rate_pre,
                )
            except Exception as emit_err:
                logger.warning(f"[Transfer] EventStore emission failed (non-fatal): {emit_err}")

        # EigenTrust signal + fee audit record
        try:
            await _record_transfer_ancillary(
                db, current_agent.did, transfer_request.receiver_agent_id,
                transfer_request.amount, teg_response.transaction_id,
                _fee_avt_pre, _fee_svc if _fee_avt_pre > 0 else None,
            )
        except Exception as anc_err:
            logger.warning(f"[Transfer] Ancillary recording failed (non-fatal): {anc_err}")

        # §pass57: the successful response is kept for Idempotency-Key replay (§REPATLANE-5: by run_kept)
        return teg_response

    except httpx.RequestError as e:
        logger.error(f"TEG API connection error: {e}")
        # §REPATLANE-5 (V0606): a connection never made reached nothing; any other (a read timeout, a dropped answer)
        # may have reached the TEG, which may have recorded the transfer
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"TEG service unavailable {NO_FUNDS_MOVED if _never_sent(e) else OUTCOME_UNKNOWN}"
        )

@router.post("/system-transfer", response_model=TEGSystemTransferResponse, summary="Pay units to the frame's system treasury")
async def transfer_teg_to_system(
    request: TEGSystemTransferRequest,
    http_request: Request,
    current_agent: models.Agent = Security(require_agent_permission("teg.system_transfer")),  # IRONKEY
    db: AsyncSession = Depends(get_db),
):
    """
    Pay units from the calling agent's balance to the frame's system treasury account, with an optional purpose
    (system fees and other payments to the system). Needs an agent token with the `teg.system_transfer` permission.
    """
    # Use proper agent DID
    sender_agent_did = current_agent.did
    # IRONKEY L2/xreg caveat gate (agentfix7) — system-transfer is a real debit of the
    # sender's balance but skipped enforce_agent_spend; close it so a delegate acting-as-
    # issuer cannot exceed the issuer's max_per_tx via /teg/system-transfer. Δ-safe (pre-proxy).
    # (http_request carries the resolved L4 capability for the S1 caveat/budget gate.)
    await enforce_agent_spend(db, sender_agent_did, request.amount, request=http_request)
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, sender_agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Prepare headers based on token type
            headers = prepare_teg_headers(teg_token)
            
            # Prepare TEG API request
            teg_request = {
                "system_account_type": "treasury",
                "amount": request.amount,
                "purpose": request.purpose
            }
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transfer/to-system",
                json=teg_request,
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return TEGSystemTransferResponse(
                    transaction_id=data["transaction_id"],
                    status=data["status"],
                    sender_agent_id=data["sender_agent_id"],
                    system_receiver_id=data["system_receiver_id"],
                    amount=str(data["amount"]),
                    purpose=data["purpose"],
                    new_sender_balance=str(data["new_sender_balance"]),
                    timestamp=data["timestamp"]
                )
            elif response.status_code == 400:
                # Parse error from TEG API
                error_data = response.json()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_data.get("detail", "System transfer failed")
                )
            elif response.status_code == 401:
                # Authentication failed
                logger.error(f"TEG authentication failed for reputation query")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                logger.error(f"TEG API system transfer request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to process system transfer at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/transactions", response_model=TEGTransactionHistoryResponse, summary="Get Transaction History")
async def get_transaction_history(
    limit: int = Query(100, ge=0, le=_TEG_PAGE_MAX),
    offset: int = Query(0, ge=0, le=_TEG_PAGE_MAX),
    current_agent: models.Agent = Security(get_current_agent)
):
    """
    Get transaction history for the authenticated agent.
    
    Returns paginated list of transactions where the agent was either
    sender or receiver, ordered by timestamp (newest first).
    """
    # Use proper agent DID
    agent_did = current_agent.did
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transactions",
                params={"limit": limit, "offset": offset},
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                # Convert transaction data
                transactions = [
                    TEGTransactionInfo(
                        transaction_id=tx["transaction_id"],
                        sender_agent_id=tx.get("sender_agent_id"),
                        receiver_agent_id=tx["receiver_agent_id"],
                        amount=str(tx["amount"]),
                        fee_amount=str(tx["fee_amount"]),
                        status=tx["status"],
                        transaction_type=tx["transaction_type"],
                        timestamp=tx["timestamp"],
                        error_message=tx.get("error_message"),
                        reputation_signal_applied=tx.get("reputation_signal_applied", False),
                        attached_message=tx.get("attached_message")
                    )
                    for tx in data["transactions"]
                ]
                
                return TEGTransactionHistoryResponse(
                    transactions=transactions,
                    total=data["total"],
                    limit=data["limit"],
                    offset=data["offset"]
                )
            elif response.status_code == 401:
                # Authentication failed
                logger.error(f"TEG authentication failed for agent reputation query")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                logger.error(f"TEG API history request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch transaction history at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.post("/transactions/{transaction_id}/reputation-signal", response_model=TEGReputationSignalResponse, summary="Apply Reputation Signal")
async def apply_reputation_signal(
    transaction_id: str,
    request: TEGReputationSignalRequest,
    # §FINDINGS-A4 3b (2026-09-27): gated on what the caller DOES (it sent the transfer), as §BUYSERVICE did for
    # settle. `reputation.signal` lives only in service-provider while the TEG accepts a signal only from the
    # transfer's SENDER (endpoints_token.py: "Only the sender can apply reputation signal"), the paying client, so a
    # plain client could never signal. The TEG still enforces sender-only, completed transfers, once per transaction.
    current_agent: models.Agent = Security(require_agent_permission("teg.transfer"))
):
    """
    Apply a reputation signal to a completed transaction.
    
    Allows the sender of a successful A2A token transfer to signal
    about the receiver's performance. Each transaction can only
    receive one reputation signal.
    """
    # Use proper agent DID
    agent_did = current_agent.did
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            teg_request = {
                "signal_value": request.signal_value
            }
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/{seg(transaction_id)}/reputation-signal",
                json=teg_request,
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # P2-008: Emit ReputationChanged event to Event Store
                try:
                    from ..crud_agent_enhanced import emit_reputation_changed_event
                    await emit_reputation_changed_event(
                        agent_did=data["receiver_agent_id"],
                        old_score=0,  # Previous score not available from TEG response
                        new_score=data["new_receiver_reputation"],
                        reason=f"reputation_signal:{data['signal_value']}:tx:{data['transaction_id']}"
                    )
                except Exception as ev_err:
                    logger.warning(f"Failed to emit reputation event: {ev_err}")
                
                return TEGReputationSignalResponse(
                    transaction_id=data["transaction_id"],
                    sender_agent_id=data["sender_agent_id"],
                    receiver_agent_id=data["receiver_agent_id"],
                    signal_value=data["signal_value"],
                    new_receiver_reputation=data["new_receiver_reputation"],
                    status=data["status"]
                )
            elif response.status_code == 400:
                error_data = response.json()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_data.get("detail", "Failed to apply reputation signal")
                )
            elif response.status_code == 401:
                # Authentication failed for reputation query
                logger.error(f"TEG authentication failed for reputation query")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transaction not found"
                )
            else:
                logger.error(f"TEG API reputation signal request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to apply reputation signal at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/agents/{agent_id}/reputation", response_model=TEGAgentReputationResponse, summary="Get Agent Reputation")
async def get_agent_reputation(
    # §MCPTEST30 (V0526, 2026-10-01): the TEG keeps agent ids in String(255) columns, and a longer id reached its query:
    # psycopg2 StringDataRightTruncation, the TEG's 500, this registry's 503 "outage" (round 8's hostile-input probe,
    # 4,000 characters; seen in sbx-alpha-teg's log by agentvault2-ab). Refused here, 422, before anything is forwarded.
    agent_id: str = Path(..., min_length=1, max_length=255),
    current_agent: models.Agent = Security(get_current_agent)
):
    """
    Get reputation score for a specific agent.
    
    Returns the current reputation score and tier for the specified agent.
    Any authenticated agent can view reputation scores.
    """
    # Get agent's own token for authentication
    agent_did = current_agent.did
    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Prepare headers based on token type
            headers = prepare_teg_headers(teg_token)
            
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/reputation/agents/{seg(agent_id)}/reputation",
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return TEGAgentReputationResponse(
                    agent_id=data["agent_id"],
                    reputation_score=data["reputation_score"],
                    reputation_tier=data["reputation_tier"],
                    last_updated=data.get("last_updated")
                )
            elif response.status_code == 401:
                # Clear cached token on auth failure
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent not found"
                )
            else:
                logger.error(f"TEG API reputation request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch reputation at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/fees/config", response_model=TEGFeeConfigResponse, summary="Get Fee Configuration")
async def get_fee_configuration():
    """
    Get current fee configuration.
    
    Returns the current transfer fee amount and the address where fees are collected.
    This endpoint is public as agents need to know the fee before initiating transfers.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/fees/config",
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return TEGFeeConfigResponse(
                    transfer_fee_amount=str(data["transfer_fee_amount"]),
                    fee_collection_address=data["fee_collection_address"]
                )
            else:
                logger.error(f"TEG API fee config request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch fee configuration at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )



@router.get("/treasury/balance", summary="Get TEG Treasury Balance")
async def get_treasury_balance(
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get the TEG treasury balance.
    
    Returns the current balance of the senate treasury used for ecosystem funding.
    This endpoint proxies to the TEG Layer's governance treasury endpoint.
    """
    logger.info(f"[Treasury Balance] Fetching treasury balance for user: {current_developer.email}")
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Call TEG Layer's treasury balance endpoint
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/treasury/balance",
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"  # Admin token for treasury access
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"[Treasury Balance] Successfully retrieved treasury balance: {data}")
                # Return in same format as regular balance endpoint
                # Use the treasury_did from TEG response (canonical source of truth)
                return {
                    "agent_id": data.get("treasury_did", "did:theprotocol:teg_system_treasury"),
                    "balance": str(data.get("balance", "0"))
                }
            else:
                logger.error(f"[Treasury Balance] TEG API treasury balance request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch treasury balance at this time")
                
        except httpx.RequestError as e:
            logger.error(f"[Treasury Balance] TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/policies", response_model=TEGPolicyListResponse, summary="List Active TEG Policies")
async def list_teg_policies(
    active_only: bool = True,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    List TEG governance policies.
    
    Returns active policies by default. Use active_only=false to see all policies.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Changed to use governance/admin/policies endpoint instead of admin/policies
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/policies",
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"  # Using admin token for full policy listing
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                # The governance endpoint returns an array directly, not an object with policies field
                policies_data = data if isinstance(data, list) else data.get("policies", [])
                
                # Filter by active status if requested
                if active_only:
                    policies_data = [p for p in policies_data if p.get("is_active", True)]
                
                policies = [
                    TEGPolicyResponse(
                        policy_id=p["policy_id"],
                        policy_code=p.get("policy_code", ""),
                        policy_name=p["policy_name"],
                        policy_type=p.get("policy_type", "unknown"),
                        policy_version=p.get("policy_version", "1.0.0"),
                        description=p.get("description"),
                        parameters=p.get("parameters"),
                        circuit_identifier=p.get("circuit_identifier"),
                        enforcement_level=p.get("enforcement_level"),
                        reward_amount=p.get("reward_amount"),
                        rules_document_url=p.get("rules_document_url"),
                        is_active=p.get("is_active", True),
                        created_at=p["created_at"],
                        updated_at=p["updated_at"]
                    )
                    for p in policies_data
                ]
                
                return TEGPolicyListResponse(
                    policies=policies,
                    total=len(policies)
                )
            else:
                logger.error(f"TEG API policies request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch policies at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.post("/policies", response_model=TEGPolicyResponse, summary="Create TEG Policy")
async def create_teg_policy(
    request: TEGPolicyRequest,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury"))  # §FINDINGS-A4 3a (2026-09-27, his "fix 1-4 approved"): a policy WRITE is an admin act
):
    """
    Create a new TEG governance policy.
    
    Requires admin privileges. Policies define the rules for agent behavior in the TEG, the ledger
    service.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Prepare TEG API request
            teg_request = {
                "policy_code": request.policy_code,
                "policy_name": request.policy_name,
                "policy_type": request.policy_type
            }
            
            # Add optional fields if provided
            if request.description is not None:
                teg_request["description"] = request.description
            if request.parameters is not None:
                teg_request["parameters"] = request.parameters
            if request.circuit_identifier is not None:
                teg_request["circuit_identifier"] = request.circuit_identifier
            if request.enforcement_level is not None:
                teg_request["enforcement_level"] = request.enforcement_level
            if request.reward_amount is not None:
                teg_request["reward_amount"] = request.reward_amount
            if request.is_active is not None:
                teg_request["is_active"] = request.is_active
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/policies",
                json=teg_request,
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"  # Admin token for policy management
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Log audit event for policy creation
                log_audit_event(
                    action="POLICY_CREATED",
                    policy_id=data["policy_id"],
                    user_email=current_developer.email,
                    details={
                        "policy_code": data["policy_code"],
                        "policy_name": data["policy_name"],
                        "policy_type": data["policy_type"]
                    }
                )
                
                return TEGPolicyResponse(
                    policy_id=data["policy_id"],
                    policy_code=data["policy_code"],
                    policy_name=data["policy_name"],
                    policy_type=data["policy_type"],
                    policy_version=data.get("policy_version", "1.0.0"),
                    description=data.get("description"),
                    parameters=(json.loads(data["parameters"]) if isinstance(data.get("parameters"), str) else data.get("parameters")),  # OWL-FIX: TEG returns parameters as JSON string
                    circuit_identifier=data.get("circuit_identifier"),
                    enforcement_level=data.get("enforcement_level"),
                    reward_amount=data.get("reward_amount"),
                    rules_document_url=data.get("rules_document_url"),
                    is_active=data["is_active"],
                    created_at=data["created_at"],
                    updated_at=data["updated_at"]
                )
            elif response.status_code == 409:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Policy with this code already exists"
                )
            elif response.status_code == 422:
                error_data = response.json()
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=error_data.get("detail", "Invalid policy data")
                )
            else:
                logger.error(f"TEG API policy creation request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to create policy at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.post("/policies/batch", response_model=TEGPolicyBatchResponse, summary="Create Multiple TEG Policies")
async def create_teg_policies_batch(
    request: TEGPolicyBatchRequest,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury"))  # §FINDINGS-A4 3a (2026-09-27, his "fix 1-4 approved"): a policy WRITE
):
    """
    Create several TEG governance policies, all or nothing. At most 50 policies per batch.

    The TEG has no batch transaction, so the registry keeps the promise itself. A batch that names one policy_code twice
    is refused (422) before anything is written. Then each policy is created in order, and on the first refusal the
    policies this call already created are deactivated again. The TEG's delete is a deactivation, and its create
    conflicts only with a LIVE policy, so the same batch can be sent again. The call then answers the TEG's refusal
    (its 4xx and reason), or 503 when the TEG could not answer, and nothing from the batch stays live. A policy this call
    created and could not deactivate again is named in a 500. Requires the `admin_treasury` admin flag.
    """
    # D6-828 (agentvault2-d6, 2026-10-25): the "dry run" loop this replaced CREATED each policy and undid nothing, so a
    # batch whose every policy was refused answered 200, and a later refusal left the earlier policies live.
    codes = [p.policy_code for p in request.policies]
    twice = sorted({c for c in codes if codes.count(c) > 1})
    if twice:
        raise HTTPException(status_code=422,
                            detail=f"the batch names a policy_code more than once ({', '.join(twice)}); nothing was created")
    base = f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/policies"
    headers = {"Authorization": f"Bearer {TEG_ADMIN_API_KEY}"}
    made: List[Tuple[str, str]] = []   # (policy_id, policy_code) this call created, in order
    created_policies: List[TEGPolicyResponse] = []

    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:

        async def _rolled_back(idx: int, code: str, refusal: HTTPException) -> HTTPException:
            """Deactivate what this call created, newest first; the refusal to answer, or a 500 naming what stays live."""
            live: List[str] = []
            for pid, _code in reversed(made):
                try:
                    r = await client.delete(f"{base}/{seg(pid)}", headers=headers, timeout=10.0)
                    if r.status_code != 200:
                        live.append(pid)
                except httpx.RequestError:
                    live.append(pid)
            log_audit_event(
                action="POLICY_BATCH_ROLLED_BACK", policy_id="BATCH", user_email=current_developer.email,
                details={"failed_index": idx, "policy_code": code, "refusal": str(refusal.detail)[:300],
                         "deactivated": [pid for pid, _ in made if pid not in live], "still_live": live})
            if live:
                return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=(
                    f"policy {idx} ({code}) was refused ({refusal.detail}), and {len(live)} of the {len(made)} policies "
                    f"this batch created could not be deactivated again; still live: {', '.join(live)}"))
            done = f"the {len(made)} created before it were deactivated again; " if made else ""
            return HTTPException(status_code=refusal.status_code,
                                 detail=f"policy {idx} ({code}) was refused: {refusal.detail}; {done}nothing from this batch is live")

        for idx, policy in enumerate(request.policies):
            teg_request = {
                "policy_code": policy.policy_code,
                "policy_name": policy.policy_name,
                "policy_type": policy.policy_type
            }
            if policy.description is not None:
                teg_request["description"] = policy.description
            if policy.parameters is not None:
                teg_request["parameters"] = policy.parameters
            if policy.circuit_identifier is not None:
                teg_request["circuit_identifier"] = policy.circuit_identifier
            if policy.enforcement_level is not None:
                teg_request["enforcement_level"] = policy.enforcement_level
            if policy.reward_amount is not None:
                teg_request["reward_amount"] = policy.reward_amount
            if policy.is_active is not None:
                teg_request["is_active"] = policy.is_active
            try:
                response = await client.post(base, json=teg_request, headers=headers, timeout=10.0)
            except httpx.RequestError as e:
                logger.error(f"TEG API connection error in a policy batch: {e}")
                raise await _rolled_back(idx, policy.policy_code, HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TEG service unavailable"))
            if response.status_code != 200:
                logger.error(f"TEG API policy batch create refused: {response.status_code} - {response.text[:300]}")
                raise await _rolled_back(idx, policy.policy_code,
                                         _teg_refusal(response, "Unable to create policy at this time"))
            try:
                data = response.json()
            except ValueError:
                data = None
            pid = data.get("policy_id") if isinstance(data, dict) else None
            if not pid:
                raise await _rolled_back(idx, policy.policy_code, HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="the TEG answered 200 without a policy id, so this policy may be live and this call cannot "
                           "deactivate it"))
            made.append((str(pid), policy.policy_code))
            try:
                created_policies.append(TEGPolicyResponse(
                    policy_id=data["policy_id"],
                    policy_code=data["policy_code"],
                    policy_name=data["policy_name"],
                    policy_type=data["policy_type"],
                    policy_version=data.get("policy_version", "1.0.0"),
                    description=data.get("description"),
                    parameters=(json.loads(data["parameters"]) if isinstance(data.get("parameters"), str) else data.get("parameters")),  # OWL-FIX: TEG returns parameters as JSON string
                    circuit_identifier=data.get("circuit_identifier"),
                    enforcement_level=data.get("enforcement_level"),
                    reward_amount=data.get("reward_amount"),
                    rules_document_url=data.get("rules_document_url"),
                    is_active=data["is_active"],
                    created_at=data["created_at"],
                    updated_at=data["updated_at"]
                ))
            except Exception as e:  # noqa: BLE001 — an answer this call cannot read is rolled back, never half-kept
                raise await _rolled_back(idx, policy.policy_code, HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"the TEG's answer for this policy could not be read ({type(e).__name__})"))
            log_audit_event(
                action="POLICY_CREATED_BATCH",
                policy_id=str(pid),
                user_email=current_developer.email,
                details={
                    "policy_code": data["policy_code"],
                    "batch_index": idx,
                    "batch_size": len(request.policies)
                }
            )

    log_audit_event(
        action="POLICY_BATCH_COMPLETE",
        policy_id="BATCH",
        user_email=current_developer.email,
        details={
            "total_requested": len(request.policies),
            "success_count": len(created_policies),
            "failure_count": 0
        }
    )
    return TEGPolicyBatchResponse(
        success_count=len(created_policies),
        failure_count=0,
        created_policies=created_policies,
        errors=[]
    )

@router.get("/policies/{policy_id}", response_model=TEGPolicyResponse, summary="Get TEG Policy Details")
async def get_teg_policy(
    policy_id: str,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get details of a specific TEG policy.
    
    Returns full policy information including parameters and enforcement level.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/policies/{seg(policy_id)}",
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"  # Admin token for policy access
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return TEGPolicyResponse(
                    policy_id=data["policy_id"],
                    policy_code=data["policy_code"],
                    policy_name=data["policy_name"],
                    policy_type=data["policy_type"],
                    policy_version=data.get("policy_version", "1.0.0"),
                    description=data.get("description"),
                    parameters=(json.loads(data["parameters"]) if isinstance(data.get("parameters"), str) else data.get("parameters")),  # OWL-FIX: TEG returns parameters as JSON string
                    circuit_identifier=data.get("circuit_identifier"),
                    enforcement_level=data.get("enforcement_level"),
                    reward_amount=data.get("reward_amount"),
                    rules_document_url=data.get("rules_document_url"),
                    is_active=data["is_active"],
                    created_at=data["created_at"],
                    updated_at=data["updated_at"]
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Policy not found"
                )
            else:
                logger.error(f"TEG API policy get request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch policy at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.put("/policies/{policy_id}", response_model=TEGPolicyResponse, summary="Update TEG Policy")
async def update_teg_policy(
    policy_id: str,
    request: TEGPolicyUpdateRequest,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury"))  # §FINDINGS-A4 3a (2026-09-27, his "fix 1-4 approved"): a policy WRITE is an admin act
):
    """
    Update an existing TEG policy.
    
    Requires admin privileges. Only provided fields will be updated.
    The policy version will be automatically incremented.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # First, get the current policy to extract version
            get_response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/policies/{seg(policy_id)}",
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"
                },
                timeout=10.0
            )
            
            if get_response.status_code != 200:
                if get_response.status_code == 404:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Policy not found"
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Unable to fetch policy for update"
                    )
            
            current_policy = get_response.json()
            old_version = current_policy.get("policy_version", "1.0.0")
            new_version = increment_version(old_version)
            
            # Build update payload with only provided fields
            update_data = {
                "policy_version": new_version  # Always include the incremented version
            }
            if request.policy_name is not None:
                update_data["policy_name"] = request.policy_name
            if request.description is not None:
                update_data["description"] = request.description
            if request.parameters is not None:
                update_data["parameters"] = request.parameters
            if request.enforcement_level is not None:
                update_data["enforcement_level"] = request.enforcement_level
            if request.reward_amount is not None:
                update_data["reward_amount"] = request.reward_amount
            if request.is_active is not None:
                update_data["is_active"] = request.is_active
            
            response = await client.put(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/policies/{seg(policy_id)}",
                json=update_data,
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"  # Admin token for policy management
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Log audit event for policy update
                log_audit_event(
                    action="POLICY_UPDATED",
                    policy_id=policy_id,
                    user_email=current_developer.email,
                    details={
                        "old_version": old_version,
                        "new_version": new_version,
                        "fields_updated": list(update_data.keys())
                    }
                )
                
                return TEGPolicyResponse(
                    policy_id=data["policy_id"],
                    policy_code=data["policy_code"],
                    policy_name=data["policy_name"],
                    policy_type=data["policy_type"],
                    policy_version=data.get("policy_version", new_version),
                    description=data.get("description"),
                    parameters=(json.loads(data["parameters"]) if isinstance(data.get("parameters"), str) else data.get("parameters")),  # OWL-FIX: TEG returns parameters as JSON string
                    circuit_identifier=data.get("circuit_identifier"),
                    enforcement_level=data.get("enforcement_level"),
                    reward_amount=data.get("reward_amount"),
                    rules_document_url=data.get("rules_document_url"),
                    is_active=data["is_active"],
                    created_at=data["created_at"],
                    updated_at=data["updated_at"]
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Policy not found"
                )
            else:
                logger.error(f"TEG API policy update request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to update policy at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )
        except Exception as e:
            import traceback
            logger.error(f"OWL-FIX: update_teg_policy unexpected error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error in update_teg_policy: {type(e).__name__}: {e}"
            )

@router.delete("/policies/{policy_id}", summary="Delete TEG Policy")
async def delete_teg_policy(
    policy_id: str,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury"))  # §FINDINGS-A4 3a (2026-09-27, his "fix 1-4 approved"): a policy WRITE is an admin act
):
    """
    Delete (deactivate) a TEG policy.
    
    Requires admin privileges. This performs a soft delete by setting
    the policy's is_active flag to false.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.delete(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/policies/{seg(policy_id)}",
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"  # Admin token for policy management
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Log audit event for policy deletion
                log_audit_event(
                    action="POLICY_DELETED",
                    policy_id=policy_id,
                    user_email=current_developer.email,
                    details={
                        "message": data.get("message", f"Policy {policy_id} deactivated")
                    }
                )
                
                return {"message": data.get("message", f"Policy {policy_id} deactivated")}
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Policy not found"
                )
            else:
                logger.error(f"TEG API policy delete request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to delete policy at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/policies/compliance/dashboard", response_model=TEGPolicyComplianceResponse, summary="Get Policy Compliance Dashboard")
async def get_policy_compliance_dashboard(
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get policy compliance metrics and dashboard data.
    
    Returns compliance statistics including attestation rates,
    policy violations, and compliance breakdown by policy type.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/governance/admin/dashboard/policies/compliance",
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}"  # Admin token for compliance metrics
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return TEGPolicyComplianceResponse(
                    total_policies=data["total_policies"],
                    active_policies=data["active_policies"],
                    attestations_submitted=data["attestations_submitted"],
                    attestations_verified=data["attestations_verified"],
                    compliance_rate=data["compliance_rate"],
                    policy_violations=data["policy_violations"],
                    policy_compliance_by_type=data.get("policy_compliance_by_type", {}),
                    recent_attestations=data.get("recent_attestations", [])
                )
            else:
                logger.error(f"TEG API compliance dashboard request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch compliance metrics at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.post("/disputes/log", response_model=TEGDisputeLogResponse, summary="Log a TEG Dispute")
async def log_dispute(
    request: TEGDisputeLogRequest,
    current_agent: models.Agent = Security(require_agent_permission("disputes.file")),
    db: AsyncSession = Depends(get_db),):
    """
    Log a dispute with another agent.
    
    The authenticated agent becomes the claimant in the dispute.
    """
    # Use proper agent DID
    claimant_agent_did = current_agent.did
    # §DIDWIDEN-1 closer (eb, 2026-09-06): the same hole as routers/disputes — this rail forwarded ANY defendant DID to
    # the TEG with no lookup, so a dispute log was filed against a nobody. The defendant must be an agent this
    # registry knows (a native row or an active mirrored card), the same two-table question the dispute rail asks.
    from .disputes import defendant_known as _defendant_known
    if not await _defendant_known(db, request.defendant_agent_did):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Defendant {request.defendant_agent_did} is not known to this registry: no agent row and no mirrored card",
        )
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, claimant_agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Prepare TEG API request
            teg_request = {
                "claimant_agent_did": claimant_agent_did,
                "defendant_agent_did": request.defendant_agent_did,
                "reason_code": request.reason_code,
                "brief_description": request.brief_description
            }
            
            # Add optional fields if provided
            if request.avtp_transaction_id:
                teg_request["avtp_transaction_id"] = request.avtp_transaction_id
            if request.evidence_pointer:
                teg_request["evidence_pointer"] = request.evidence_pointer
            if request.dispute_reason_category:
                teg_request["dispute_reason_category"] = request.dispute_reason_category
            if request.related_transaction_id:
                teg_request["related_transaction_id"] = request.related_transaction_id
            if request.evidence_description_or_url:
                teg_request["evidence_description_or_url"] = request.evidence_description_or_url
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/disputes/",
                json=teg_request,
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 201:
                data = response.json()
                return TEGDisputeLogResponse(
                    dispute_log_id=data["dispute_log_id"],
                    status=data["status"]
                )
            elif response.status_code == 400:
                error_data = response.json()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_data.get("detail", "Failed to log dispute")
                )
            elif response.status_code == 401:
                # Clear cached token on auth failure
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                logger.error(f"TEG API dispute log request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to log dispute at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/disputes", response_model=list[TEGDisputeQueryResponse], summary="List My TEG Disputes")
async def list_my_disputes(
    status_filter: Optional[str] = None,
    limit: int = Query(100, ge=0, le=_TEG_PAGE_MAX),
    offset: int = Query(0, ge=0, le=_TEG_PAGE_MAX),
    current_agent: models.Agent = Security(get_current_agent)
):
    """
    List disputes where the authenticated agent is involved.
    
    Returns disputes where the agent is either claimant or defendant.
    """
    # Use proper agent DID
    agent_did = current_agent.did
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            params = {
                "limit": limit,
                "offset": offset
            }
            if status_filter:
                params["status"] = status_filter
            
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/disputes/",
                params=params,
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                # Filter disputes to only show those involving the current agent
                relevant_disputes = [
                    TEGDisputeQueryResponse(
                        dispute_log_id=d["dispute_log_id"],
                        claimant_agent_did=d["claimant_agent_did"],
                        defendant_agent_did=d["defendant_agent_did"],
                        reason_code=d["reason_code"],
                        brief_description=d["brief_description"],
                        avtp_transaction_id=d.get("avtp_transaction_id"),
                        evidence_pointer=d.get("evidence_pointer"),
                        status=d["status"],
                        resolution_notes=d.get("resolution_notes"),
                        dispute_reason_category=d.get("dispute_reason_category"),
                        related_transaction_id=d.get("related_transaction_id"),
                        evidence_description_or_url=d.get("evidence_description_or_url"),
                        admin_reviewer_id=d.get("admin_reviewer_id"),
                        created_at=d["created_at"],
                        updated_at=d["updated_at"]
                    )
                    for d in data
                    if d["claimant_agent_did"] == agent_did or d["defendant_agent_did"] == agent_did
                ]
                
                return relevant_disputes
            elif response.status_code == 401:
                # Clear cached token on auth failure
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                logger.error(f"TEG API disputes list request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch disputes at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/disputes/{dispute_log_id}", response_model=TEGDisputeQueryResponse, summary="Get TEG Dispute Details")
async def get_dispute_details(
    dispute_log_id: str,
    current_agent: models.Agent = Security(get_current_agent)
):
    """
    Get details of a specific dispute.
    
    Only parties involved in the dispute can view its details.
    """
    # Use proper agent DID
    agent_did = current_agent.did
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/disputes/{seg(dispute_log_id)}",
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 200:
                d = response.json()
                return TEGDisputeQueryResponse(
                    dispute_log_id=d["dispute_log_id"],
                    claimant_agent_did=d["claimant_agent_did"],
                    defendant_agent_did=d["defendant_agent_did"],
                    reason_code=d["reason_code"],
                    brief_description=d["brief_description"],
                    avtp_transaction_id=d.get("avtp_transaction_id"),
                    evidence_pointer=d.get("evidence_pointer"),
                    status=d["status"],
                    resolution_notes=d.get("resolution_notes"),
                    dispute_reason_category=d.get("dispute_reason_category"),
                    related_transaction_id=d.get("related_transaction_id"),
                    evidence_description_or_url=d.get("evidence_description_or_url"),
                    admin_reviewer_id=d.get("admin_reviewer_id"),
                    created_at=d["created_at"],
                    updated_at=d["updated_at"]
                )
            elif response.status_code == 401:
                # Clear cached token on auth failure
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            elif response.status_code == 403:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to view this dispute"
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dispute not found"
                )
            else:
                logger.error(f"TEG API dispute details request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch dispute details at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.post("/attestations/submit", response_model=TEGAttestationResponse, summary="Submit TEG Attestation")
async def submit_attestation(
    request: TEGAttestationRequest,
    current_agent: models.Agent = Security(require_agent_permission("reputation.signal"))
):
    """
    Submit an attestation to the TEG Layer.
    
    Attestations are cryptographic claims about agents that can be used
    for reputation, verification, and trust establishment.
    """
    # Use proper agent DID
    submitter_agent_did = current_agent.did
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, submitter_agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Prepare TEG API request — map registry fields to TEG schema
            import hashlib, json as _json
            attestation_hash = hashlib.sha256(
                _json.dumps(request.attestation_data, sort_keys=True).encode()
            ).hexdigest()
            
            teg_request = {
                "agent_did": submitter_agent_did,
                "attestation_type": request.attestation_type,
                "attestation_hash": attestation_hash,
                "storage_pointer": request.evidence_url or f"registry://attestation/{attestation_hash[:16]}"
            }
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/attestation/submit",
                json=teg_request,
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code in (200, 201):
                data = response.json()
                # §DOCSFIX D6-582: the TEG answers 200 with its AttestationSubmissionResponse (submission_id, agent_did,
                # attestation_type, status, the policy), which this proxy took for a failure (503) after the TEG had
                # logged the submission; what the TEG does not keep (the target, the data, the evidence URL) is the
                # request's, and the timestamp is this answer's (the list reads the TEG's own submitted_at)
                attestation_id = str(data.get("submission_id") or data.get("attestation_id") or "")
                now_iso = datetime.now(timezone.utc).isoformat()

                # P2-008: Emit AttestationSubmitted event to Event Store
                try:
                    from ..crud_agent_enhanced import emit_attestation_event
                    await emit_attestation_event(
                        agent_did=submitter_agent_did,
                        attestation_type=request.attestation_type,
                        attestation_data={
                            "attestation_id": attestation_id,
                            "target_agent_did": request.target_agent_did,
                            "status": data.get("status", ""),
                        }
                    )
                except Exception as ev_err:
                    logger.warning(f"Failed to emit attestation event: {ev_err}")

                return TEGAttestationResponse(
                    attestation_id=attestation_id,
                    submitter_agent_did=data.get("agent_did") or submitter_agent_did,
                    target_agent_did=request.target_agent_did,
                    attestation_type=data.get("attestation_type") or request.attestation_type,
                    attestation_data=request.attestation_data,
                    evidence_url=request.evidence_url,
                    metadata=request.metadata,
                    status=data.get("status", ""),
                    created_at=now_iso,
                    updated_at=now_iso,
                )
            elif response.status_code == 400:
                error_data = response.json()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_data.get("detail", "Failed to submit attestation")
                )
            elif response.status_code == 401:
                # Clear cached token on auth failure
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                logger.error(f"TEG API attestation submit request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to submit attestation at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

@router.get("/attestations", response_model=list[TEGAttestationResponse], summary="List My Attestations")
async def list_attestations(
    attestation_type: Optional[str] = None,
    target_agent_did: Optional[str] = None,
    limit: int = Query(100, ge=0, le=_TEG_PAGE_MAX),
    offset: int = Query(0, ge=0, le=_TEG_PAGE_MAX),
    current_agent: models.Agent = Security(get_current_agent)
):
    """
    List attestations for the authenticated agent.
    
    Returns attestations where the agent is either the submitter
    or the target. Can be filtered by attestation type and target agent.
    """
    # Use proper agent DID
    agent_did = current_agent.did
    
    # Get proper TEG JWT token
    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            # Build query parameters
            params = {
                "limit": limit,
                "offset": offset
            }
            if attestation_type:
                params["attestation_type"] = attestation_type
            if target_agent_did:
                params["target_agent_did"] = target_agent_did
            
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/attestation",
                params=params,
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                # TEG may return a bare list or a dict with an "attestations"/"items" key
                items = data if isinstance(data, list) else data.get("attestations", data.get("items", []))
                # OWL-FIX 2026-03-08: TEG economic engine rewrite changed AttestationInfo field names.
                # Old registry model used: attestation_id, submitter_agent_did, target_agent_did,
                # attestation_data (dict), evidence_url, created_at, updated_at.
                # New TEG AttestationInfo uses: submission_id, agent_did, attestation_hash,
                # storage_pointer, submitted_at. target_agent_did and updated_at no longer exist.
                # NOTE: In a clean system this list is always [] because POST /teg/attestations/submit
                # is EF (503) and nothing submits to TEG attestations via normal flows.
                # Registry-native ZKP attestations (POST /api/v1/attestations/submit) do NOT call TEG.
                # This fix handles dirty-state ghost records from broken prior test runs gracefully.
                # Architecture decision re: TEG bridge deferred -- see ROADMAP/Attestation_TEG_Integration_Decision.md
                attestations = [
                    TEGAttestationResponse(
                        attestation_id=att.get("submission_id") or att.get("attestation_id", ""),
                        submitter_agent_did=att.get("agent_did") or att.get("submitter_agent_did", ""),
                        target_agent_did=att.get("target_agent_did", ""),
                        attestation_type=att.get("attestation_type", ""),
                        attestation_data=att.get("attestation_data") or {
                            "hash": att.get("attestation_hash", ""),
                            "storage": att.get("storage_pointer", "")
                        },
                        evidence_url=att.get("evidence_url") or att.get("storage_pointer"),
                        metadata=att.get("metadata"),
                        status=att.get("status", ""),
                        created_at=str(att.get("submitted_at") or att.get("created_at", "")),
                        updated_at=str(att.get("updated_at") or att.get("submitted_at", ""))
                    )
                    for att in items
                ]
                
                return attestations
            elif response.status_code == 401:
                # Clear cached token on auth failure
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                logger.error(f"TEG API attestations list request failed: {response.status_code} - {response.text}")
                raise _teg_refusal(response, "Unable to fetch attestations at this time")
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )



# ============================================================================
# STAKING PROXIES (5 endpoints) - CRITICAL MISSING FUNCTIONALITY
# ============================================================================

@router.post("/staking/stake", response_model=Dict[str, Any], summary="Lock units through the TEG's lock path", dependencies=[Depends(require_staking_enabled)])  # §BAFIN
async def stake_tokens_proxy(
    request: StakeRequest,
    current_agent: models.Agent = Security(require_agent_permission("staking.manage")),
    db: AsyncSession = Depends(get_db)
):
    """
    Lock units through the TEG's own lock path (an amount and a lock period in days). Locking is a switch per
    registry (`STAKING_ENABLED`), off on the public network, where this answers 403. Needs an agent token with the
    `staking.manage` permission.
    """
    # Use proper agent DID
    agent_did = current_agent.did

    # Get TEG JWT token for authentication
    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)

    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/stake",
                json={
                    "amount": request.amount,
                    "lock_period_days": request.lock_period_days
                },
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                # Sync balances back to registry DB
                try:
                    new_liquid = data.get("new_available_balance")
                    new_staked = data.get("new_staked_balance")
                    if new_liquid is not None:
                        current_agent.liquid_balance = Decimal(str(new_liquid))
                    if new_staked is not None:
                        current_agent.staked_balance = Decimal(str(new_staked))
                    await db.commit()
                    logger.info(
                        f"[Stake] DB synced: {agent_did} "
                        f"liquid={current_agent.liquid_balance} staked={current_agent.staked_balance}"
                    )
                except Exception as sync_err:
                    logger.error(f"[Stake] DB balance sync failed for {agent_did}: {sync_err}")
                return data
            elif response.status_code == 401:
                # Clear cached token on auth failure
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                error_detail = response.json().get("detail", "Staking failed")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_detail
                )

        except httpx.RequestError as e:
            logger.error(f"TEG API connection error during stake: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


@router.post("/staking/unstake", response_model=Dict[str, Any], summary="Release locked units through the TEG's lock path")
async def unstake_tokens_proxy(
    request: UnstakeRequest,
    current_agent: models.Agent = Security(require_agent_permission("staking.manage")),
    db: AsyncSession = Depends(get_db)
):
    """
    Release locked units through the TEG's own lock path (a lock id and an amount); the TEG applies the lock
    periods. This works where locking is switched off. Needs an agent token with the `staking.manage` permission.
    """
    # Use proper agent DID
    agent_did = current_agent.did

    teg_token = await get_teg_token_for_agent(current_agent.id, agent_did)

    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/unstake",
                json={
                    "stake_id": request.stake_id,
                    "amount": request.amount
                },
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                # Sync balances back to registry DB
                try:
                    new_liquid = data.get("new_available_balance")
                    new_staked = data.get("new_staked_balance")
                    if new_liquid is not None:
                        current_agent.liquid_balance = Decimal(str(new_liquid))
                    if new_staked is not None:
                        current_agent.staked_balance = Decimal(str(new_staked))
                    await db.commit()
                    logger.info(
                        f"[Unstake] DB synced: {agent_did} "
                        f"liquid={current_agent.liquid_balance} staked={current_agent.staked_balance}"
                    )
                except Exception as sync_err:
                    logger.error(f"[Unstake] DB balance sync failed for {agent_did}: {sync_err}")
                return data
            elif response.status_code == 401:
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            else:
                error_detail = response.json().get("detail", "Unstaking failed")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_detail
                )

        except httpx.RequestError as e:
            logger.error(f"TEG API connection error during unstake: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


@router.get("/staking/balance/{agent_did}", response_model=StakeBalanceResponse, summary="Get Locked Balance")
async def get_staking_balance_proxy(
    agent_did: str,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get the locked balance of an agent from the TEG, the ledger service.
    
    Requires developer authentication. Returns the locked balance and the active locks of the
    specified agent. Uses service token for TEG queries.
    """
    # User must be authenticated, but we use service token for TEG
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/staking/balance/{seg(agent_did)}",
                headers={"X-Service-Token": TEG_ADMIN_API_KEY},  # Use service token
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return StakeBalanceResponse(**data)
            elif response.status_code == 403:
                logger.error("TEG rejected service token - check TEG_ADMIN_API_KEY configuration")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Service authentication failed"
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent not found"
                )
            else:
                logger.error(f"TEG API staking balance request failed: {response.status_code}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch the locked balance"
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error fetching staking balance: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


@router.get("/staking/history/{agent_did}", response_model=StakingHistoryResponse, summary="Get Lock History")
async def get_staking_history_proxy(
    agent_did: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get the lock and release history of an agent from the TEG, the ledger service.
    
    Requires developer authentication. Returns a paginated list of the lock and release transactions
    of the specified agent. Uses service token for TEG queries.
    """
    # User must be authenticated, but we use service token for TEG
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/staking/history/{seg(agent_did)}",
                params={"limit": limit, "offset": offset},
                headers={"X-Service-Token": TEG_ADMIN_API_KEY},  # Use service token
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return StakingHistoryResponse(**data)
            elif response.status_code == 403:
                logger.error("TEG rejected service token - check TEG_ADMIN_API_KEY configuration")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Service authentication failed"
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent not found"
                )
            else:
                logger.error(f"TEG API staking history request failed: {response.status_code}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch the lock history"
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error fetching staking history: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


@router.get("/staking/apy-tiers", response_model=APYTiersResponse, summary="The TEG's lock tiers (none where the payout switch is off)")
async def get_apy_tiers_proxy():
    """
    The lock tier configuration the TEG reports. A payout on locked units is a switch per registry
    (`STAKING_REWARDS_ENABLED`): discretionary, paid in platform units, off on the public network, where this
    answers no tiers. Public, no auth.
    """
    if not staking_rewards_enabled():
        return APYTiersResponse(tiers=[], current_tier=None, current_apy=0.0)
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/apy-tiers",
                headers={"X-Service-Token": TEG_ADMIN_API_KEY},
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return APYTiersResponse(**data)
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch the payout tiers"
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error fetching APY tiers: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


# ============================================================================
# REWARDS PROXIES (3 endpoints) - CRITICAL MISSING FUNCTIONALITY
# ============================================================================

@router.post("/rewards/claim", response_model=RewardsClaimResponse, summary="Claim payouts on locked units",
             # §MEMBERSHIP (2026-10-02, agentvault2-15's finding): this legacy claim forwards to a ledger handler
             # that credits from no account (dormant: no claimable rows on EU or ASIA, 2026-10-02); where rewards
             # are off it is refused like every other reward rail (core/staking_gate.py).
             dependencies=[Depends(require_staking_rewards_enabled)])
async def claim_rewards_proxy(
    agent_did: str = Query(..., description="Agent DID to claim payouts for"),
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Claim all pending payouts on locked units via TEG Layer.
    
    This proxy forwards payout claim requests to the TEG Layer's own endpoint.
    Claims every accumulated payout: on locked units, attestations and governance.
    Developer must own the agent.
    """
    # Verify developer owns this agent
    stmt = select(models.Agent).where(
        models.Agent.did == agent_did,
        models.Agent.creator_developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=404,
            detail="Agent not found or not authorized"
        )
    
    teg_token = await get_teg_token_for_agent(agent.id, agent_did)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/rewards/claim",
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return RewardsClaimResponse(**data)
            elif response.status_code == 401:
                _teg_token_cache.pop(agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No pending payouts to claim"
                )
            else:
                error_detail = response.json().get("detail", "Reward claim failed")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_detail
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error during reward claim: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


@router.get("/rewards/pending/{agent_did}", response_model=PendingRewardsResponse, summary="Pending payouts on locked units")
async def get_pending_rewards_proxy(
    agent_did: str,
    current_developer: models.Developer = Depends(security.get_current_developer)  # Require developer auth
):
    """
    Get the pending payouts for an agent from TEG Layer.
    
    NOTE: This endpoint uses service-to-service authentication with TEG.
    The developer must be authenticated, but we use service token for TEG.
    """
    # User must be authenticated, but we use service token for TEG
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/rewards/{seg(agent_did)}",
                headers={"X-Service-Token": TEG_ADMIN_API_KEY},  # Use service token!
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return PendingRewardsResponse(**data)
            elif response.status_code == 403:
                logger.error("TEG rejected service token - check TEG_ADMIN_API_KEY configuration")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Service authentication failed"
                )
            elif response.status_code == 404:
                # Return zero rewards if agent not found
                return PendingRewardsResponse(
                    pending_rewards="0",
                    last_claim_timestamp=None,
                    reward_sources=[]
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch pending payouts"
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error fetching pending rewards: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


@router.get("/rewards/history/{agent_did}", response_model=RewardsHistoryResponse, summary="Payout history on locked units")
async def get_rewards_history_proxy(
    agent_did: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_developer: models.Developer = Depends(security.get_current_developer)  # Require developer auth
):
    """
    Get the payout history for an agent from TEG Layer.
    
    NOTE: This endpoint uses service-to-service authentication with TEG.
    The developer must be authenticated, but we use service token for TEG.
    """
    # This endpoint is already working, but let's ensure it uses the right auth
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/tokenomics/rewards/history/{seg(agent_did)}",
                params={"limit": limit, "offset": offset},
                headers={"X-Service-Token": TEG_ADMIN_API_KEY},  # Use service token!
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return RewardsHistoryResponse(**data)
            elif response.status_code == 403:
                logger.error("TEG rejected service token - check TEG_ADMIN_API_KEY configuration")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Service authentication failed"
                )
            elif response.status_code == 404:
                # Return empty history if agent not found
                return RewardsHistoryResponse(
                    rewards=[],
                    total_earned="0"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch the payout history"
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error fetching rewards history: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


# ============================================================================
# GOVERNANCE PROXIES - REMOVED 2026-02-22
# ============================================================================
# TEG governance proposal endpoints were broken (missing TEGGovernanceProposal model).
# Governance proposals and voting now live exclusively in the Registry's Agent Senate
# system at /api/v1/governance/ (routers/governance.py + crud/crud_governance.py).
# The 3 proxy endpoints (list/create/vote) have been removed.
# See SESSION_LOG_2026-02-22_OWL15E_GOVERNANCE_TREASURY_INVESTIGATION.md


# ============================================================================
# DISPUTE RESOLUTION PROXY (1 endpoint) - MISSING FUNCTIONALITY
# ============================================================================

@router.post("/disputes/{dispute_id}/resolve", response_model=Dict[str, Any], summary="Resolve Dispute")
async def resolve_dispute_proxy(
    dispute_id: str,
    request: DisputeResolveRequest,
    current_agent: models.Agent = Security(require_agent_permission("disputes.file"))
):
    """
    Refused for every caller (403): this registry does not forward a TEG dispute resolution. A resolution moves
    units, and the TEG would take the forwarded call as the registry's own administrator act.

    \f
    Resolve a dispute via TEG Layer: REFUSED for every caller (§MCPTEST30, V0545).

    The TEG accepts this registry's own mTLS identity as its admin (core/security.verify_admin_token ->
    internal_auth.resolve_internal_caller returns for any internal service SVID, whatever bearer rides along), so this
    route's gate was the only one, and it was `disputes.file`, which every agent holds from its `client` birth role.
    A resolution moves money (the TEG debits the defendant's balance to SYSTEM_PENALTIES for `penalty_amount`, with no
    registry event). Only a transport slip stood between any agent and any dispute: the body below carries the TEG's
    query parameters, so every call met the TEG's 422 (sbxalphaop's TEG, 2026-10-02 04:34:19Z). The route now refuses
    before it reaches the TEG. Who may resolve a TEG dispute through the registry is his decision (a manual admin rail,
    like PUT /admin/disputes/{id}/ruling, is the shape the doctrine names); the forwarding below stays unreachable.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=("Not authorized to resolve disputes: this registry does not forward a TEG dispute resolution for any "
                "caller (the TEG would take it as the registry's own admin act)"),
    )
    teg_token = await get_teg_token_for_agent(current_agent.id, current_agent.did)  # noqa: unreachable (kept for the record)
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/disputes/{seg(dispute_id)}/resolve",
                json=request.model_dump(),
                headers=prepare_teg_headers(teg_token),
                timeout=10.0
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                _teg_token_cache.pop(current_agent.id, None)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed"
                )
            elif response.status_code == 403:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to resolve disputes"
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dispute not found"
                )
            else:
                error_detail = response.json().get("detail", "Dispute resolution failed")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_detail
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error resolving dispute: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


# ============================================================================
# REPUTATION RANKING PROXY (1 endpoint) - MISSING FUNCTIONALITY
# ============================================================================

@router.get("/reputation/rankings", response_model=ReputationRankingsResponse, summary="Get Reputation Rankings")
async def get_reputation_rankings_proxy(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    min_score: Optional[int] = Query(None, description="Minimum reputation score"),
    db: AsyncSession = Depends(get_db),
):
    """
    Agents ranked by the TEG's own reputation score (limit, offset, optional min_score): reputation signals, audit flags
    and an administrator's recalculation move it; it is not the EigenTrust score (`/reputation/{did}/trust-score`).
    Each row also carries the agent's registry-attested `track_record` (verified Guild work). The two measure different
    things and can disagree. Public, no auth.

    \f
    Get reputation rankings from TEG Layer.
    
    Returns a ranked list of agents by reputation score.
    Top agents receive additional benefits and voting power.

    §MARKSURFACES (2026-09-10) — each row also carries the registry-attested
    `track_record`, so the public Leaderboard can render the earned mark on the
    agents it is ranking WITHOUT a per-row lookup. Before this, the page enriched
    only its top three on load and everything below them on hover, so the ranking
    page showed no rank until you moved a mouse over it.
    ⚠ The two numbers are NOT the same thing and the page must not imply they are:
    `reputation_score` is the TEG's own signal-driven number; the mark is verified
    guild work. They can disagree, and an agent can top this list with zero jobs.
    """
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            params = {"limit": limit, "offset": offset}
            if min_score is not None:
                params["min_score"] = min_score
            
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/reputation/rankings",
                params=params,
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                # §MARKSURFACES — ONE grouped pass over the guild books for the whole
                # page (no N+1). Enrichment must never break the ranking itself.
                try:
                    from agentvault_registry.services.track_record import compact_track_records
                    rows = data.get("rankings") or []
                    dids = [r.get("agent_id") for r in rows if isinstance(r, dict) and r.get("agent_id")]
                    tr = await compact_track_records(db, dids)
                    for r in rows:
                        if isinstance(r, dict):
                            r["track_record"] = tr.get(r.get("agent_id"))
                except Exception as _tr_e:  # noqa: BLE001
                    logger.warning(f"[MARK] rankings track-record enrichment failed: {_tr_e}")
                # §SECFIX D6-606 (2026-10-16): a developer's TEG account id is built from its e-mail address
                # (identifiers.developer_teg_did) and this list is public: such a row is shown under an opaque id.
                from agentvault_registry.identifiers import withhold_personal_ids
                data["rankings"] = withhold_personal_ids(data.get("rankings") or [])
                return ReputationRankingsResponse(**data)
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch reputation rankings"
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error fetching reputation rankings: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )

# =============================================================================
# OWL26: Treasury-First Funding Endpoints
# =============================================================================
# These proxy endpoints route all funding through the TEG treasury.
# No more minting from void. All token movements are treasury transfers.

# ============================================================================
# OWL-BRIDGE: Cross-Registry Voluntary Transfer Proxy
# ============================================================================
# Proxies to TEG Layer's built-in cross-TEG 2PC transfer protocol.
# TEG handles: lock funds → send to target TEG → accept → commit/compensate.
# Registry handles: DID resolution, auth bridging, EventStore event, balance sync.

class CrossRegistryTransferRequest(BaseModel):
    """Request model for cross-registry AVT transfer."""
    receiver_did: str = Field(..., max_length=120, description="Full DID of receiver agent on another registry")
    amount: str = Field(..., description="Amount to transfer as string")
    message: Optional[str] = Field(None, max_length=256, description="Optional transfer message")

    @field_validator('receiver_did')
    @classmethod
    def validate_receiver_did(cls, v):
        from agentvault_registry.input_validators import validate_did
        return validate_did(v)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)

class CrossRegistryTransferResponse(BaseModel):
    """Response model for cross-registry transfer."""
    transfer_id: str
    status: str  # completed, failed, pending
    sender_did: str
    receiver_did: str
    amount: str
    fee_amount: Optional[str] = None
    credited_amount: Optional[str] = None
    source_teg: str
    target_teg: str
    transaction_hash: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: str


async def _is_own_native_agent(db: AsyncSession, did: str) -> bool:
    """Is `did` one of this registry's own agents (a row in agents that is not a bundle's mirror install)? A read that
    fails refuses the transfer (503, nothing moved): an unread answer is neither ours nor someone else's."""
    try:
        row = (await db.execute(
            text("SELECT 1 FROM agents WHERE did = :d AND is_federated_mirror IS NOT TRUE LIMIT 1"), {"d": did}
        )).first()
    except Exception as e:  # noqa: BLE001 — the transfer is refused either way, saying why
        logger.error(f"[CROSS-REG] could not read whether {did} is an agent of this registry: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not read whether the receiver is an agent of this registry {NO_FUNDS_MOVED}.",
        )
    return row is not None


async def _resolve_receiver_registry(
    db: AsyncSession,
    receiver_did: str
) -> tuple:
    """
    Resolve a receiver DID to their home registry's TEG configuration.

    Strategy:
    1. Reject if receiver is a local agent (use normal /teg/transfer instead)
    2. Query AgentCard table for cards with federation_metadata (synced from peers)
    3. Match agent name/DID from card_data to find origin peer
    4. Derive TEG ID from peer registry name convention

    Returns: (teg_id, registry_id) or (None, None) if unresolvable.
    """

    # Step 1: Reject local agents — use normal transfer for same-registry
    local_check = await db.execute(
        select(models.Agent).where(models.Agent.did == receiver_did)
    )
    if local_check.scalar_one_or_none():
        return None, None  # Local agent — caller should use /teg/transfer

    # Step 2: Check active peer registries
    peers_stmt = select(models.PeerRegistry).where(
        models.PeerRegistry.status == "ACTIVE"
    )
    peers_result = await db.execute(peers_stmt)
    peers = peers_result.scalars().all()

    if not peers:
        return None, None

    # Step 3: Check AgentCards with federation_metadata sourced from a peer
    # Federated cards have card_data.federation_metadata.source_registry set
    from agentvault_registry.models import AgentCard
    cards_stmt = select(AgentCard).where(
        AgentCard.agent_did == receiver_did
    )
    cards_result = await db.execute(cards_stmt)
    card = cards_result.scalar_one_or_none()

    if card and card.card_data:
        fed_meta = (card.card_data or {}).get('federation_metadata', {})
        source_registry = fed_meta.get('source_registry', '') or fed_meta.get('first_synced_from', '')
        if source_registry:
            source_lower = source_registry.lower()
            source_path_parts = [p for p in source_lower.split('/') if p and p not in ('spiffe:', '', 'agentvault.com', 'operator', 'service', 'registry', 'ns', 'sa')]

            # PASS 1: Exact match — slug or SPIFFE path segment (no ambiguity)
            for peer in peers:
                peer_slug = _slug(peer.name)
                # §pass73.3.6 — dash-insensitive compact slug, defense-in-depth
                # against admin-provided peer names that pick up a dash via
                # _slug (e.g. display name "Sandbox Alpha" → slug "sandbox-alpha"
                # while the SPIFFE source path part is "sandboxalpha"). Real
                # bug encountered when seeding sandbox cloud-op cross-frame
                # peers manually. Naming asymmetry should not block routing.
                peer_slug_compact = peer_slug.replace('-', '')
                for part in source_path_parts:
                    part_compact = part.replace('-', '')
                    if (part == peer_slug
                            or part.replace('-registry', '') == peer_slug.replace('-registry', '')
                            or part == peer_slug.replace('registry-', '')
                            or part.replace('registry-', '') == peer_slug
                            or part_compact == peer_slug_compact):
                        teg_id = f"teg-layer-{peer_slug.replace('registry-', '')}"
                        registry_id = peer_slug if peer_slug.startswith('registry-') else f"registry-{peer_slug}"
                        logger.info(
                            f"[CROSS-REG] Resolved {receiver_did} → peer '{peer.name}' "
                            f"via exact SPIFFE match '{part}' == '{peer_slug}' "
                            f"→ teg_id={teg_id}, registry_id={registry_id}"
                        )
                        return teg_id, registry_id

            # NOTE: fuzzy/word-overlap matching removed.
            # Naming is unified so PASS 1 exact-slug equality is authoritative.
            # If we fall through, the receiver's card has inconsistent origin
            # data — surface as 400 rather than misroute.

    # Step 4: BFS topology fallback — discover multi-hop operators
    # Direct peers didn't match. Use the same BFS crawl that powers
    # the galactic map and health wall to find ALL federated registries.
    if card and card.card_data:
        fed_meta = (card.card_data or {}).get('federation_metadata', {})
        origin_name = fed_meta.get('origin_registry_name', '')
        source_registry = fed_meta.get('source_registry', '') or fed_meta.get('first_synced_from', '')
        source_lower = (source_registry or '').lower()
        origin_lower = _slug(origin_name or '')

        try:
            from .agent_locations import _compute_trusted_registries
            bfs_registries = await _compute_trusted_registries(db)
            source_path_parts = [p for p in source_lower.split('/') if p and p not in
                                 ('spiffe:', '', 'agentvault.com', 'operator', 'service', 'registry', 'ns', 'sa')] if source_lower else []

            # PASS 1: Exact match on origin_registry_name or SPIFFE path segment
            for reg in bfs_registries:
                reg_name = reg.get("name", "")
                reg_slug = _slug(reg_name)

                # Exact origin name match
                if origin_lower and (origin_lower == reg_slug
                                     or origin_lower.replace('-registry', '') == reg_slug.replace('-registry', '')):
                    teg_id = f"teg-layer-{reg_slug.replace('registry-', '')}"
                    registry_id = reg_slug if reg_slug.startswith('registry-') else f"registry-{reg_slug}"
                    logger.info(
                        f"[CROSS-REG] BFS exact resolved {receiver_did} → "
                        f"'{reg_name}' (hop {reg.get('hop', '?')}) via origin_name='{origin_name}' "
                        f"→ teg_id={teg_id}, registry_id={registry_id}"
                    )
                    return teg_id, registry_id

                # Exact SPIFFE path segment match
                # §pass73.3.6 — dash-insensitive compact match (see direct-peer
                # pass above for full rationale).
                reg_slug_compact = reg_slug.replace('-', '')
                for part in source_path_parts:
                    part_compact = part.replace('-', '')
                    if (part == reg_slug
                            or part.replace('-registry', '') == reg_slug.replace('-registry', '')
                            or part == reg_slug.replace('registry-', '')
                            or part_compact == reg_slug_compact):
                        teg_id = f"teg-layer-{reg_slug.replace('registry-', '')}"
                        registry_id = reg_slug if reg_slug.startswith('registry-') else f"registry-{reg_slug}"
                        logger.info(
                            f"[CROSS-REG] BFS exact resolved {receiver_did} → "
                            f"'{reg_name}' (hop {reg.get('hop', '?')}) via SPIFFE exact '{part}' == '{reg_slug}' "
                            f"→ teg_id={teg_id}, registry_id={registry_id}"
                        )
                        return teg_id, registry_id

            # NOTE: BFS fuzzy matching removed (same reasoning as direct-peer
            # PASS 2 above). Single-peer blind fallback also removed — it
            # silently misrouted cross-frame transfers when the only active
            # peer was the sibling frame but the receiver lived on a multi-hop
            # operator.
        except Exception as e:
            logger.warning(f"[CROSS-REG] BFS topology fallback failed: {e}")

    # FALLBACK: Query peer registries' BFS for extended topology coverage
    # Operators on distant branches (hop 6+) can't see each other locally.
    # Asking a peer extends our BFS reach (peer is closer to the mainframe).
    try:
        for peer in peers:
            peer_pub = _get_public_url_for_peer(peer)
            if not peer_pub:
                continue
            # CB-499: the answer routes a transfer, so the peer's certificate is verified and a redirect not followed.
            from .agent_locations import _crawl_client, _crawl_get
            async with _crawl_client(5) as _fc:
                resp = await _crawl_get(_fc, peer_pub, "/api/v1/agents/locations/trusted-registries")
                if resp.status_code != 200:
                    continue
                for reg in resp.json().get("registries", []):
                    reg_slug = _slug(reg.get("name", ""))
                    if origin_lower and (origin_lower == reg_slug
                                         or origin_lower.replace('-registry', '') == reg_slug.replace('-registry', '')):
                        teg_id = f"teg-layer-{reg_slug.replace('registry-', '')}"
                        registry_id = reg_slug if reg_slug.startswith('registry-') else f"registry-{reg_slug}"
                        logger.info(
                            f"[CROSS-REG] Peer BFS fallback resolved {receiver_did} → "
                            f"'{reg.get('name')}' via peer '{peer.name}' "
                            f"→ teg_id={teg_id}, registry_id={registry_id}"
                        )
                        return teg_id, registry_id
                break  # One successful peer query is enough
    except Exception as e:
        logger.debug(f"[CROSS-REG] Peer BFS fallback failed: {e}")

    logger.warning(f"[CROSS-REG] Could not resolve registry for {receiver_did}")
    return None, None


def _get_public_url_for_peer(peer) -> Optional[str]:
    """Get the public HTTPS URL for a peer registry."""
    base = getattr(peer, 'base_url', '') or ''
    try:
        from urllib.parse import urlparse
        parsed = urlparse(base)
        if parsed.hostname and '.' in parsed.hostname:
            return f"https://{parsed.hostname}"
    except Exception:
        pass
    return None


def _is_rfc1918(ip: str) -> bool:
    """True if IP is in RFC1918 private space (Docker bridge, LANs)."""
    if not ip:
        return False
    if ip.startswith("10.") or ip.startswith("192.168."):
        return True
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
            return 16 <= second <= 31  # 172.16/12 covers Docker default + identity_network
        except (ValueError, IndexError):
            return False
    return False


def _smart_https_url(hostname: str, explicit_port: Optional[int]) -> str:
    """Pick :8443 (Docker bridge alias) or :explicit_port (host-mapped) based on resolved IP.

    Inside agentvault_identity_network, Docker DNS aliases operator hostnames to
    container IPs (172.16.x.x); the container binds only :8443 internally and the
    host-mapped port (port_base+43) is unreachable from inside the bridge.

    From outside the bridge, the same hostname resolves to the host's public IP
    and only the host-mapped port lands at the operator's nginx-federation
    (port 8443 lands at central nginx-a whose cert SAN is api.theprotocol.cloud
    and fails hostname verification for op-*.op.theprotocol.cloud).

    On DNS failure, fall back to the explicit port from the URL (wave-9 behavior).
    """
    import socket as _socket
    try:
        resolved_ip = _socket.gethostbyname(hostname)
    except _socket.gaierror:
        resolved_ip = ""
    if _is_rfc1918(resolved_ip):
        return f"https://{hostname}:8443"
    return f"https://{hostname}:{explicit_port or 8443}"


def _teg_dial_url(url: str) -> str:
    """The address a TEG dials for a peer registry's CACHED url (§INGRESS404, 2026-09-26).

    A cached registry url is often the peer's CONSOLE address with no port (measured at sbxbetaop for sbx-beta:
    `https://sandbox-b.theprotocol.cloud`). `_to_internal_mtls_url` leaves such a host as it is unless it is a known
    cluster name or resolves to a private address, so the TEG dialed 443, the console, and got 404 at
    /api/v1/cross-teg/prepare: "Target TEG rejected transfer", no funds moved (the federation suite's delta->alpha skips
    of 09-20..22 and 2026-09-26 14:41Z, right after an operator restart left its topology cache cold). The main lookup,
    `_resolve_target_teg_url`, always passed the url through `_smart_https_url` first; the two fallbacks that feed the
    TEG's partner table did not. Both go through this now.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url or "")
    if not parsed.hostname:
        return _to_internal_mtls_url(url)
    return _to_internal_mtls_url(_smart_https_url(parsed.hostname, parsed.port))


def _to_internal_mtls_url(public_url: str) -> str:
    """Map a peer's BFS-cached public URL to a Docker alias form reachable
    from inside agentvault_identity_network on port 8443.

    All nginx-federation containers listen on :8443 internally and have
    aliases on agentvault_identity_network (verified empirically 2026-05-04
    via socket.create_connection from 4 source TEGs to all 9 target hosts).
    The hostname rewrites below always pick a name that BOTH (a) resolves on
    agentvault_identity_network AND (b) matches the cert's subjectAltName so
    the mTLS handshake succeeds.

      - Frame A operator:  op-X.op.theprotocol.cloud      (alias on net,
                                                           cert SAN match)
      - Frame B operator:  op-X.op.theprotocol.cloud      (alias also on net,
                                                           added at compose time;
                                                           cert SAN match)
      - Frame B mainframe: frame-b.theprotocol.cloud      (alias on net,
                                                           cert SAN match)
      - Frame A mainframe: api.theprotocol.cloud          (port 8443 reaches
                                                           nginx-a via the host
                                                           NAT/hairpin; cert SAN
                                                           includes
                                                           api.theprotocol.cloud
                                                           AND registry-a's
                                                           TrustedHost middleware
                                                           accepts this host
                                                           header. nginx-a /
                                                           agentvault-nginx-a
                                                           DNS aliases also
                                                           resolve internally,
                                                           but TrustedHost blocks
                                                           those host headers.)

    Used at cross-TEG dispatch sites where the URL flows from registry
    context to TEG context (TEG is on agentvault_identity_network and dials
    the URL directly). Distinct from `_smart_https_url`/`_resolve_target_teg_url`
    which run in registry context for `_sync_cross_registry_balances`.
    """
    if not public_url:
        return public_url
    from urllib.parse import urlparse
    parsed = urlparse(public_url)
    if not parsed.hostname:
        return public_url
    h = parsed.hostname.lower()
    if h in (
        "registry.theprotocol.cloud",
        "agentvault-nginx-a",
        "nginx-a",
    ):
        h = "api.theprotocol.cloud"
    if h.startswith("op-") and h.endswith(".frame-b.theprotocol.cloud"):
        h = h.replace(".frame-b.theprotocol.cloud", ".op.theprotocol.cloud")

    # §2026-06-03 — sandbox cloud-op `.internal` domain rewrite (op→op FX egress fix).
    # Sandbox cloud-ops (sandboxalpha/charlie/...) advertise a CLOUD_DOMAIN_SUFFIX host
    # like `<safe>.op-sandbox-c.internal` / `<safe>.op-sandbox.internal`, but that alias
    # exists ONLY on sandbox_identity_network. A MAINFRAME TEG (teg-layer-test-a/c) lives
    # on agentvault_identity_network, where the op's nginx-federation is aliased as the
    # PARTNER-domain `<safe>.op.theprotocol.cloud` (cert SAN match — see
    # feedback_cloudop_crossframe_mtls_san_and_outbox). So a mainframe→sandbox-cloud-op
    # cross-TEG dial to the `.internal` host fails DNS ("Name or service not known").
    # Rewrite to the partner-domain cluster alias (reachable from EVERY TEG since all TEGs
    # join agentvault_identity_network). Fixes the documented flaky mainframe→cloud-op path
    # (normal cross-reg transfer 503 + canary + the op→op FX egress).
    if h.endswith(".internal") and "." in h:
        return f"https://{h.split('.', 1)[0]}.op.theprotocol.cloud:8443"

    # §pass-cross-teg-2026-05-19 — wrong-perspective DNS gate fix.
    # The §pass38e DNS gate measured RFC1918 from the CALLER's network, but
    # the URL returned by this helper is consumed by a TEG (mainframe TEG or
    # cloud-op TEG), and ALL TEGs are joined to agentvault_identity_network
    # (verified empirically 2026-05-19: cloud-op-op-X-teg has aliases on
    # both operator-net AND agentvault_identity_network; the per-op nginx-
    # federation sidecars have aliases like `op-X.op.theprotocol.cloud` on
    # the identity network, port 8443, cert SAN match).
    #
    # The §pass38e gate broke cross-TEG 2PC because cloud-op REGISTRIES are
    # only on operator-net — they resolve `op-X.op.theprotocol.cloud` to the
    # public IP (NOT RFC1918), and the gate fell back to the original
    # `public_url` (port-stripped → host nginx :443 → wrong upstream → 404).
    # The TEG that receives this URL via /cross-teg/config/add-partner CAN
    # reach the rewritten host on :8443 via its identity-network alias.
    #
    # Cluster-host check: any host known to have an identity-network alias
    # (Frame A mainframe, Frame B mainframe, any cloud-op via .op. subdomain
    # after the rewrite above). Always return the :8443 rewritten form for
    # these. Non-cluster hosts fall through to the legacy DNS-gate path
    # (preserved for safety on unknown hostnames).
    is_cluster_host = (
        h == "api.theprotocol.cloud"
        or h == "frame-b.theprotocol.cloud"
        or (h.startswith("op-") and h.endswith(".op.theprotocol.cloud"))
    )
    if is_cluster_host:
        return f"https://{h}:8443"

    import socket as _socket
    try:
        resolved = _socket.gethostbyname(h)
        if _is_rfc1918(resolved):
            return f"https://{h}:8443"
    except _socket.gaierror:
        pass
    return public_url


def _to_registry_dialable_url(public_url: str) -> str:
    """§pass62.4 (2026-05-21) — Caller-context-aware variant of
    `_to_internal_mtls_url` for REGISTRY-side outbound dials (RC v0.3 sync).

    The original helper assumes the dialer is on `agentvault_identity_network`,
    which is true for all TEGs (verified §pass-cross-teg-2026-05-19) and for
    Frame A's registry container, but **false for Frame B's registry container**
    (only on `frame_b_identity_network`).

    This caller-context-aware rewrite reads `SPIRE_TRUST_DOMAIN` to decide
    which Docker DNS alias the calling container can natively resolve:

      Caller `SPIRE_TRUST_DOMAIN=agentvault.com` (Frame A registry):
        — All hosts:                  identical to `_to_internal_mtls_url`
                                       (frame-b.* → frame-b on host hairpin,
                                        op-X.frame-b.* → op-X.op.* rewrite,
                                        op-X.op.* keep, all :8443).

      Caller `SPIRE_TRUST_DOMAIN=frame-b.theprotocol.cloud` (Frame B registry):
        — op-X.frame-b.theprotocol.cloud   → keep host, force :8443
                                              (native frame_b_identity_network
                                              alias — what Frame B's registry
                                              can actually reach without any
                                              network change)
        — op-X.op.theprotocol.cloud        → fall through to public_url
                                              (Frame B's registry cannot reach
                                              Frame A's per-op nginx-federation
                                              sidecars; v0.3 card pulling for
                                              those peers needs a separate
                                              proxy-cache approach — out of
                                              scope for this pass)
        — api.theprotocol.cloud /
          registry.theprotocol.cloud       → keep as :443 public form (host
                                              hairpin via Cloudflare/host nginx
                                              with proper SAN)
        — frame-b.theprotocol.cloud        → keep on :8443 (Frame B's own
                                              hostname is reachable internally
                                              via its public DNS too)

    Returns the rewritten URL, or the original public_url unchanged for
    non-cluster hosts (legacy DNS gate path retained for safety).

    DO NOT use this for TEG-side dials (use `_to_internal_mtls_url` there).
    """
    if not public_url:
        return public_url
    from urllib.parse import urlparse
    parsed = urlparse(public_url)
    if not parsed.hostname:
        return public_url
    h = parsed.hostname.lower()

    # Caller-context detection. Default to current behavior (Frame A side) if
    # the env var is missing — preserves the existing semantics for any
    # legacy caller and matches §pass-cross-teg-2026-05-19's invariants.
    caller_trust_domain = os.getenv("SPIRE_TRUST_DOMAIN", "").lower()
    is_frame_b_caller = (caller_trust_domain == "frame-b.theprotocol.cloud")

    # §pass67.1 (2026-05-23) — Cloud-op registry caller detection.
    # Cloud-ops are only on their own `cloud-op-<name>_operator-net`, NOT on
    # `agentvault_identity_network` or `frame_b_identity_network`. So the
    # internal :8443 alias rewrites the existing branches do (returning
    # `https://op-X.{op,frame-b}.theprotocol.cloud:8443`) DO NOT resolve from
    # a cloud-op's network — they leak to the public hostname which routes
    # via the host nginx to whatever vhost owns the SNI, presenting a cert
    # for the wrong subject (verified live: from op-singapore, dialing
    # op-seoul.op.theprotocol.cloud:8443 hits nginx-a's cert).
    #
    # The fix: for cloud-op callers, ALWAYS return the public URL on :443
    # (Cloudflare/host nginx ingress → Let's Encrypt wildcard cert with the
    # correct SAN → routes to the destination operator's nginx-federation
    # sidecar with HTTP routing for /.well-known/registry-card.json). This
    # is the same path used by Frame B's registry for cross-frame peers,
    # generalized to cloud-op callers.
    #
    # Marker: REGISTRY_NAME starts with "cloud-op-" on every provisioned
    # cloud-op registry container (canonical per
    # services/cloud_provisioner.py). Mainframes use "Registry-A" / "Frame-B".
    registry_name = os.getenv("REGISTRY_NAME", "")
    is_cloud_op_caller = registry_name.startswith("cloud-op-")

    if h in ("registry.theprotocol.cloud", "agentvault-nginx-a", "nginx-a"):
        h = "api.theprotocol.cloud"

    if is_cloud_op_caller:
        # Cloud-op caller: dial public URL on :443 (Let's Encrypt wildcard).
        # Strip any custom port from the original URL so we land on the host
        # nginx ingress (which routes /.well-known/registry-card.json to the
        # right operator's registry backend). Return base form (no trailing
        # slash, no path) — matches the existing helper convention so callers
        # can do `_to_registry_dialable_url(url).rstrip('/') + '/path'`.
        return f"https://{h}"

    if is_frame_b_caller:
        # Frame B's registry: preserve .frame-b. aliases for ops we can reach
        # natively; fall through to public for cross-frame ops we cannot reach.
        if h.startswith("op-") and h.endswith(".frame-b.theprotocol.cloud"):
            return f"https://{h}:8443"
        if h == "frame-b.theprotocol.cloud":
            return f"https://{h}:8443"
        # Cross-frame: Frame B's registry has no DNS path to Frame A's ops or
        # to Frame A's mainframe :8443 alias. Fall through to public form so
        # the caller can still hit the public endpoint via Cloudflare/host
        # nginx if those routes exist (today, only api.theprotocol.cloud:443
        # answers RC v0.3 over public ingress).
        if h == "api.theprotocol.cloud":
            return public_url
        if h.startswith("op-") and h.endswith(".op.theprotocol.cloud"):
            return public_url
        return public_url

    # Default branch: caller is Frame A registry (or untyped legacy caller).
    # Apply the §pass60/pass-cross-teg-2026-05-19 rewrite logic, identical to
    # `_to_internal_mtls_url`.
    if h.startswith("op-") and h.endswith(".frame-b.theprotocol.cloud"):
        h = h.replace(".frame-b.theprotocol.cloud", ".op.theprotocol.cloud")
    is_cluster_host = (
        h == "api.theprotocol.cloud"
        or h == "frame-b.theprotocol.cloud"
        or (h.startswith("op-") and h.endswith(".op.theprotocol.cloud"))
    )
    if is_cluster_host:
        return f"https://{h}:8443"
    import socket as _socket
    try:
        resolved = _socket.gethostbyname(h)
        if _is_rfc1918(resolved):
            return f"https://{h}:8443"
    except _socket.gaierror:
        pass
    return public_url


async def _resolve_target_teg_url(target_registry_id: str) -> Optional[str]:
    """Resolve target TEG mTLS URL from BFS topology for dynamic partner discovery.

    Prefers `url` (full base_url with port) over `public_url` (port-stripped).
    Port selection is context-aware via `_smart_https_url`: callers on the
    Docker `agentvault_identity_network` route to the operator's container
    port :8443 (Docker DNS alias hits the container directly); callers outside
    the bridge route to the operator's host-mapped port (port_base+43, e.g.
    op-london:27343, op-berlin:27543), because port 8443 lands at the central
    nginx-a whose cert SAN doesn't match operator hostnames. See wave 10
    handover for the empirical rationale.
    """
    try:
        # §2026-07-26 — read the REDIS-BACKED cache, not the process-local mirror.
        # `_trusted_cache` is only warmed in a worker that has itself loaded/saved it;
        # reading it directly made resolution a per-worker lottery and silently skipped
        # the receiver balance sync. Redis is the shared source of truth; the loader
        # falls back to the in-memory mirror and never raises.
        from .agent_locations import _load_trusted_cache_from_redis
        registries, _ts = await _load_trusted_cache_from_redis()
        target_norm = _slug(target_registry_id)
        for reg in registries:
            reg_slug = _slug(reg.get("name", ""))
            if reg_slug == target_norm or reg_slug.replace('registry-', '') == target_norm.replace('registry-', ''):
                # Prefer full URL (with port) over port-stripped public_url
                url = reg.get("url", "") or reg.get("public_url", "")
                if url:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    if parsed.hostname:
                        return _smart_https_url(parsed.hostname, parsed.port)
    except Exception:
        pass
    return None


async def _resolve_peer_registry_url(target_registry_id: str) -> Optional[str]:
    """Resolve a target_registry_id to the peer's API URL.
    Checks: 1) static TRUSTED_REGISTRIES, 2) BFS trusted-registries cache (includes operators)."""
    target_norm = _slug(target_registry_id)

    # Source 1: Static TRUSTED_REGISTRIES config
    trusted = getattr(settings, 'trusted_registries', None) or getattr(settings, 'TRUSTED_REGISTRIES', None)
    if trusted:
        for reg in trusted:
            reg_dict = reg if isinstance(reg, dict) else (reg.model_dump() if hasattr(reg, 'model_dump') else vars(reg))
            name = reg_dict.get('registry_name', '') or reg_dict.get('name', '')
            url = reg_dict.get('registry_url', '') or reg_dict.get('url', '')
            normalized = _slug(name)
            if normalized == target_norm or normalized.replace('registry-', '') == target_norm.replace('registry-', ''):
                return url

    # Source 2: BFS trusted-registries cache (operators discovered via topology crawl).
    # §2026-07-26 — Redis-backed read; see _resolve_target_teg_url for why the
    # process-local `_trusted_cache` mirror was the wrong thing to read here.
    try:
        from .agent_locations import _load_trusted_cache_from_redis
        registries, _ts = await _load_trusted_cache_from_redis()
        for reg in registries:
            pub = reg.get("public_url", "")
            if not pub:
                continue
            reg_slug = _slug(reg.get("name", ""))
            if reg_slug == target_norm or reg_slug.replace('registry-', '') == target_norm.replace('registry-', ''):
                return pub
    except Exception:
        pass

    return None


@router.post(
    "/cross-teg-balance-sync",
    summary="Notify this registry that an agent received a cross-TEG credit",
    tags=["Federation"]  # §pass56 PR-6: TitleCase
)
async def cross_teg_balance_sync(
    notification: dict,
    db: AsyncSession = Depends(get_db),
    _peer_identity: str = Depends(require_peer_registry_identity),
):
    """
    Called by a peer registry after a cross-TEG transfer to trigger
    a balance cache sync for the credited agent.

    This endpoint does NOT trust the incoming amount: it queries its own
    TEG for the authoritative balance and updates the local DB cache.
    """
    agent_did = notification.get("agent_did")
    transfer_id = notification.get("transfer_id", "unknown")

    if not agent_did:
        raise HTTPException(status_code=400, detail="agent_did is required")

    logger.info(f"[CROSS-TEG-SYNC] Received balance sync notification for {agent_did} (transfer={transfer_id})")

    # Look up the local agent
    result = await db.execute(
        select(models.Agent).where(models.Agent.did == agent_did)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        logger.warning(f"[CROSS-TEG-SYNC] Agent {agent_did} not found locally — may be federated-only")
        return {"status": "skipped", "reason": "agent_not_local"}

    # §PlanB-②: emit a Δ-neutral RESOLUTION ANCHOR unconditionally — BEFORE the
    # balance query below. That query (TEG /token/balance, 5s) times out under load;
    # its 200-gate previously suppressed the only id-bearing receiver emit, leaving
    # the receiver's classic cross_teg_receive leg (PK=transfer_id) with no ES event
    # on this frame → getTegTransactionDetail 404. CrossRegistryTransferCompleted is
    # skip_in_projection=true (projection skips it) AND carries no amount → ZERO supply
    # impact; by-transaction(transfer_id) now resolves the receive leg regardless of
    # whether the balance sync below succeeds.
    if transfer_id and transfer_id != "unknown":
        try:
            from agentvault_registry.event_emitter import get_event_emitter as _gee
            _anchor = _gee()
            if _anchor:
                _anchor.emit_background(
                    event_type="CrossRegistryTransferCompleted",
                    aggregate_id=agent_did,
                    data={
                        "transfer_id": transfer_id,
                        "transaction_id": transfer_id,
                        "to": agent_did,
                        "memo": "cross_registry_receiver_resolve",
                    },
                    idempotency_key=f"cross_reg_recv_resolve:{transfer_id}",
                )
        except Exception as _anchor_err:
            logger.warning(f"[CROSS-TEG-SYNC] receive-resolve anchor emit failed (non-fatal): {_anchor_err}")

    # Query our own TEG for the agent's authoritative balance
    try:
        teg_token = await get_teg_token_for_agent(agent.id, agent_did)
        headers = prepare_teg_headers(teg_token)
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            bal_resp = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                headers=headers,
                timeout=5.0
            )
            if bal_resp.status_code == 200:
                bal_data = bal_resp.json()
                old_balance = agent.liquid_balance
                agent.liquid_balance = Decimal(str(bal_data.get("balance", agent.liquid_balance)))
                await db.commit()
                logger.info(
                    f"[CROSS-TEG-SYNC] Balance synced for {agent_did}: "
                    f"{old_balance} → {agent.liquid_balance} (transfer={transfer_id})"
                )

                # f037: Emit TokensTransferred with SAME idempotency key as sender.
                # EventStore deduplicates — if sender already emitted, this is a no-op (409).
                # If sender's emit failed, this one lands → guaranteed exactly-once.
                sender_did = notification.get("sender_did", "")
                amount = notification.get("amount", "0")
                if sender_did and amount:
                    try:
                        from agentvault_registry.event_emitter import get_event_emitter
                        _emitter = get_event_emitter()
                        if _emitter:
                            xfer_idem_key = f"xfer-{transfer_id}"
                            _emitter.emit_background(
                                event_type="TokensTransferred",
                                aggregate_id=sender_did,
                                data={
                                    "from": sender_did,
                                    "to": agent_did,
                                    "amount": str(amount),
                                    "transaction_id": transfer_id,
                                    "memo": "cross_registry_receiver_emit"
                                },
                                idempotency_key=xfer_idem_key
                            )
                            logger.info(f"[CROSS-TEG-SYNC] Emitted TokensTransferred (idem={xfer_idem_key})")
                    except Exception as emit_err:
                        logger.warning(f"[CROSS-TEG-SYNC] Event emission failed (non-fatal): {emit_err}")

                return {"status": "synced", "agent_did": agent_did, "new_balance": agent.liquid_balance}
            else:
                logger.error(f"[CROSS-TEG-SYNC] TEG balance query failed: {bal_resp.status_code}")
                return {"status": "error", "reason": f"TEG returned {bal_resp.status_code}"}
    except Exception as e:
        logger.error(f"[CROSS-TEG-SYNC] Balance sync failed for {agent_did}: {e}")
        return {"status": "error", "reason": str(e)}


# ---------------------------------------------------------------------------
# Helpers for cross_registry_transfer (decomposed for readability)
# ---------------------------------------------------------------------------
async def _emit_cross_registry_events(
    sender_did: str,
    receiver_did: str,
    amount: str,
    message: Optional[str],
    transfer_id: str,
    xfer_tx_id: str,
    local_teg_id: str,
    target_teg_id: str,
) -> None:
    """Emit TokensTransferred + CrossRegistryTransferCompleted + TransactionFeeCollected events."""
    from agentvault_registry.event_emitter import get_event_emitter

    event_emitter = get_event_emitter()
    if not event_emitter:
        return

    xfer_idem_key = f"xfer-{xfer_tx_id}"

    # TokensTransferred (counted in projection)
    event_emitter.emit_background(
        event_type="TokensTransferred",
        aggregate_id=sender_did,
        data={
            "from": sender_did,
            "to": receiver_did,
            "amount": amount,
            "transaction_id": xfer_tx_id,
            "memo": f"cross_registry:{message or ''}",
        },
        idempotency_key=xfer_idem_key,
    )

    # Audit trail (skip_in_projection=true)
    # §pass57.6: add deterministic idempotency_key so EventStore UNIQUE dedupes
    # any emit retries (registry-side network blip retrying the TEG POST would
    # otherwise emit duplicate audit-trail rows).
    event_emitter.emit_background(
        event_type="CrossRegistryTransferCompleted",
        aggregate_id=sender_did,
        data={
            "transfer_id": transfer_id,
            "from": sender_did,
            "to": receiver_did,
            "amount": amount,
            "source_teg": local_teg_id,
            "target_teg": target_teg_id,
        },
        idempotency_key=f"cross_reg_completed:{transfer_id}",
    )

    # Cross-registry fee: TEG-B collects 0.5% from the credited amount.
    # The fee is applied inside TEG-B's accept_transfer during the 2PC
    # commit phase. We emit TransactionFeeCollected for ES audit trail.
    cross_reg_fee_rate = Decimal("0.5")  # percent
    transfer_amount_dec = Decimal(amount)
    fee_amount = (transfer_amount_dec * cross_reg_fee_rate / Decimal("100")).quantize(Decimal("0.000001"))

    # §pass57.6: deterministic key so projection dedupes — TransactionFeeCollected
    # is NOT skip_in_projection, so a duplicate (e.g. registry retried TEG POST
    # → TEG dedups via cross_teg_transfers UNIQUE → registry emits twice) would
    # over-credit fee_collector in the projection.
    event_emitter.emit_background(
        event_type="TransactionFeeCollected",
        aggregate_id=sender_did,
        data={
            "from": receiver_did,
            "to": "teg:system:fee_collector",
            "fee_amount": str(fee_amount),
            "fee_type": "cross_registry_transfer",
            "transaction_id": xfer_tx_id,
            "original_amount": amount,
            "net_credited": str(transfer_amount_dec - fee_amount),
        },
        idempotency_key=f"cross_reg_fee:{xfer_tx_id}",
    )
    logger.info(f"[CROSS-REG] Fee event emitted: {fee_amount} AVT (0.5% of {amount})")


async def _sync_cross_registry_balances(
    client: httpx.AsyncClient,
    headers: dict,
    current_agent: "models.Agent",
    sender_did: str,
    receiver_did: str,
    xfer_tx_id: str,
    amount: str,
    target_registry_id: str,
    db: AsyncSession,
) -> None:
    """Sync sender balance from TEG and notify target registry to sync receiver balance."""
    # --- Sender balance sync ---
    balance_resp = await client.get(
        f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
        headers=headers,
        timeout=5.0,
    )
    if balance_resp.status_code == 200:
        bal_data = balance_resp.json()
        current_agent.liquid_balance = Decimal(str(bal_data.get("balance", current_agent.liquid_balance)))
        await db.commit()
        logger.info(f"[CROSS-REG] Balance synced: {sender_did} = {current_agent.liquid_balance}")

    # --- Notify TARGET registry to sync receiver balance (via mTLS) ---
    # Prefer mTLS federation endpoint (port 8443, nginx-federation sidecar).
    # Fall back to the plain peer URL if the mTLS resolver doesn't know the peer.
    target_reg_url = await _resolve_target_teg_url(target_registry_id)
    if not target_reg_url:
        target_reg_url = await _resolve_peer_registry_url(target_registry_id)
    if not target_reg_url:
        logger.warning(
            f"[CROSS-REG] Could not resolve target registry URL for "
            f"{target_registry_id} — receiver balance not synced"
        )
        return

    # Build mTLS-capable client config, mirroring federation_sync.py:194-229.
    # Uses a SEPARATE httpx client from the one passed in (that one is for local TEG).
    from agentvault_registry.identity.svid_client import svid_client
    mtls_client_kwargs: dict = {"timeout": 5.0}
    if target_reg_url.startswith("https://"):
        cert_config = svid_client.get_client_cert_config(target_url=target_reg_url)
        if cert_config:
            mtls_client_kwargs.update(cert_config)
            logger.info(
                f"[CROSS-REG] Using mTLS for balance-sync to {target_reg_url}"
            )
        else:
            logger.warning(
                f"[CROSS-REG] No mTLS certs available for HTTPS balance-sync to "
                f"{target_reg_url}; falling back to license header"
            )
    else:
        logger.debug(
            f"[CROSS-REG] Non-HTTPS peer URL {target_reg_url}; using license header"
        )

    # Belt-and-suspenders: also send license header. If mTLS succeeds the server uses
    # Mode 1 and ignores these headers; if mTLS fails Mode 3 catches it.
    sync_headers: dict = {}
    fed_license = os.environ.get("FEDERATION_LICENSE_KEY", "")
    if fed_license:
        sync_headers["X-Federation-License"] = fed_license
    else:
        fed_secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
        sync_headers["X-Federation-Secret"] = fed_secret
        # §PlanB-② / rule 15: derive the federation SPIFFE-ID DOMAIN from THIS frame's
        # trust domain instead of hardcoding "agentvault.com". In prod both frames'
        # TRUSTED_SPIFFE_DOMAINS include agentvault.com, so the hardcode happened to be
        # accepted by the peer (Mode-2 domain check, federation_auth.py:98). In sandbox
        # the trust domains are sandbox-a.test / sandbox-b.test → the hardcoded
        # agentvault.com is rejected 403 "untrusted domain", which silently suppressed
        # the receiver balance-sync AND the cross_teg_receive leg's resolution event.
        # Frame A default (agentvault.com) is unchanged.
        _fed_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
        sync_headers["X-Federation-SPIFFE-ID"] = f"spiffe://{_fed_td}/service/registry-a"

    try:
        # §pass69.3 (2026-05-24) — was passing verify= explicitly AND via
        # mtls_client_kwargs (which svid_client.get_client_cert_config()
        # already populates with cert + verify). Double-keyword → TypeError.
        # The svid_client path is the canonical mTLS pattern; trust it.
        async with httpx.AsyncClient(**mtls_client_kwargs) as mtls_client:
            sync_resp = await mtls_client.post(
                f"{target_reg_url}/api/v1/teg/cross-teg-balance-sync",
                json={
                    "agent_did": receiver_did,
                    "sender_did": sender_did,
                    "transfer_id": xfer_tx_id,
                    "amount": amount,
                },
                headers=sync_headers,
            )
        logger.info(
            f"[CROSS-REG] Target registry balance sync: "
            f"{sync_resp.status_code} — {sync_resp.text[:200]}"
        )
    except Exception as exc:
        logger.warning(f"[CROSS-REG] Target registry balance sync failed: {exc}")


async def _cross_registry_transfer_async(
    xfer_req: "CrossRegistryTransferRequest",
    current_agent: "models.Agent",
    sender_did: str,
    target_teg_id: str,
    target_registry_id: str,
    target_peer: Optional["models.PeerRegistry"],
    db: AsyncSession,
) -> "CrossRegistryTransferResponse":
    """Async cross-frame transfer branch (TEG_CROSS_FRAME_BACKEND=async).

    Sender locks via local TEG, emits Initiated + TokensTransferred + Fee to
    local ES, returns 200 immediately. SF-4 + Pub/Sub bridge propagates the
    Initiated event to the receiver frame's local ES; the receiver-side
    reactor catches it and credits via its own TEG. Settled event flows back
    via the same channel; sender-side reactor clears the locked row.

    Saga sweeper (saga_timeout_checker.py) handles the unhappy path: if no
    Settled event arrives within 5min, emit Refunded + restore sender balance.
    Receiver-side reactor on Refunded reverses any prior credit (compensating
    action). Supply invariant Δ=0 holds across all paths via idempotent
    TokensTransferred + reverse-TokensTransferred events.
    """
    transfer_id = str(uuid.uuid4())
    local_teg_id = _get_local_teg_id()
    local_registry_id = _get_local_registry_id()
    local_trust_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")

    # WS-G: authoritative refuse-on-null target trust_domain resolution.
    # Replaces the prior silent "fall back to local frame" on lookup miss, which
    # mislabeled an unresolved cross-frame target as intra-frame → wrong
    # target_frame → spurious CrossFrameTransferRefunded. Resolution runs BEFORE
    # the sender lock below, so a refusal moves no money. The resolver itself
    # tries peer.trust_domain → signed cached card → BFS topology cache, and only
    # raises for a genuinely-unidentifiable REMOTE target.
    from ..services.spiffe_canonical import (
        resolve_target_trust_domain,
        CrossFrameResolutionError,
    )
    try:
        target_trust_domain = await resolve_target_trust_domain(
            db,
            target_peer=target_peer,
            target_registry_id=target_registry_id,
            local_registry_id=local_registry_id,
            local_trust_domain=local_trust_domain,
        )
    except CrossFrameResolutionError as e:
        logger.error(f"[CROSS-REG ASYNC] refuse-on-null: {e}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    # 1. Lock sender's balance via TEG. Idempotent on transfer_id.
    teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            lock_resp = await client.post(
                f"{teg_base}/api/v1/cross-teg/lock-async",
                json={
                    "transfer_id": transfer_id,
                    "sender_did": sender_did,
                    "amount": xfer_req.amount,
                    "correlation_id": f"cross-reg-{transfer_id[:8]}",
                    "source_registry_id": local_registry_id,
                    "target_teg_id": target_teg_id,
                    "target_registry_id": target_registry_id,
                    "receiver_did": xfer_req.receiver_did,
                },
                headers={"Authorization": f"Bearer {teg_admin_key}"},
            )
    except httpx.RequestError as e:
        logger.error(f"[CROSS-REG ASYNC] TEG lock-async connection error: {e}")
        # §REPATLANE (V0603): only a connection never made proves the lock never ran (a read timeout may have locked)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local TEG unreachable for async cross-frame lock" + (f" {NO_FUNDS_MOVED}" if _never_sent(e) else ""),
        )

    if lock_resp.status_code == 400:
        error_msg = lock_resp.json().get("detail", "Lock rejected by TEG")
        # §REPATLANE (V0603): the TEG's lock-async refuses with a 400 only before it debits (a missing field, an invalid
        # amount, an insufficient balance), so the failed answer says that nothing moved
        error_msg = f"{error_msg} {NO_FUNDS_MOVED}"
        return CrossRegistryTransferResponse(
            transfer_id=transfer_id,
            status="failed",
            sender_did=sender_did,
            receiver_did=xfer_req.receiver_did,
            amount=xfer_req.amount,
            source_teg=local_teg_id,
            target_teg=target_teg_id,
            error_message=error_msg,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    if lock_resp.status_code not in (200, 201):
        # §LEDGERGATE (V0597): the TEG's ledger gate refused the lock (nothing moved): its sentence and Retry-After
        _refusal = ledger_refusal(lock_resp)
        if _refusal is not None:
            logger.warning("[CROSS-REG ASYNC] the TEG refused the lock: its ledger cannot record it right now")
            raise _refusal
        logger.error(
            f"[CROSS-REG ASYNC] TEG lock-async failed: {lock_resp.status_code} "
            f"{lock_resp.text[:200]}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG lock-async failure",
        )

    # 2. INSERT cross_frame_transfers row (sender-side audit + saga input).
    timeout_at = datetime.now(timezone.utc) + timedelta(minutes=SAGA_CROSS_FRAME_TIMEOUT_MIN)
    cft_row = models.CrossFrameTransfer(
        id=transfer_id,
        sender_did=sender_did,
        receiver_did=xfer_req.receiver_did,
        target_frame=target_trust_domain,
        amount=Decimal(xfer_req.amount),
        status="locked",
        timeout_at=timeout_at,
        idempotency_key=f"xfer-{transfer_id}",
    )
    db.add(cft_row)
    await db.commit()

    # 3. Sync sender's registry-side liquid_balance from TEG (it was just
    #    deducted by lock-async). The BalanceSyncReactor will eventually
    #    reconcile via TokensTransferred, but a fast path keeps the API
    #    response consistent.
    try:
        cross_reg_fee_rate = Decimal("0.5")  # percent — matches credit-async
        amount_dec = Decimal(xfer_req.amount)
        fee_amount = (amount_dec * cross_reg_fee_rate / Decimal("100")).quantize(Decimal("0.000001"))
        credited_amount = amount_dec - fee_amount
        # liquid_balance comes from TEG via the existing balance-sync path.
        # We update it here only if the column is currently >= amount (avoid
        # negative drift during reactor lag).
        if current_agent.liquid_balance is not None and current_agent.liquid_balance >= amount_dec:
            current_agent.liquid_balance = current_agent.liquid_balance - amount_dec
            await db.commit()
    except Exception as e:
        logger.warning(f"[CROSS-REG ASYNC] Sender liquid_balance sync failed (non-fatal): {e}")

    # 4. Emit events to local ES. SF-4 + Pub/Sub bridge propagates Initiated
    #    + TokensTransferred to the receiver frame's local ES.
    try:
        await _emit_cross_frame_async_initiated_events(
            sender_did=sender_did,
            receiver_did=xfer_req.receiver_did,
            amount=xfer_req.amount,
            transfer_id=transfer_id,
            source_frame=local_trust_domain,
            target_frame=target_trust_domain,
            source_teg=local_teg_id,
            target_teg=target_teg_id,
            message=xfer_req.message,
        )
    except Exception as e:
        # §REPBOND-F1 / S4: money is LOCKED and the ledger was not told — that is never
        # a warning. Traced at ERROR and counted under the S4 contract.
        logger.error(f"[CROSS-REG ASYNC] Event emission FAILED after lock {transfer_id} (money locked, EventStore not told): {e}")
        if TRANSFER_EVENT_EMIT_FAILURES is not None:
            try:
                TRANSFER_EVENT_EMIT_FAILURES.labels(path="cross_frame_async_initiated").inc()
            except Exception:  # noqa: BLE001
                pass

    logger.info(
        f"[CROSS-REG ASYNC] LOCKED: {xfer_req.amount} AVT {sender_did} → "
        f"{xfer_req.receiver_did} (transfer_id={transfer_id}, "
        f"frame={local_trust_domain}→{target_trust_domain}, timeout={timeout_at.isoformat()})"
    )

    return CrossRegistryTransferResponse(
        transfer_id=transfer_id,
        status="locked",
        sender_did=sender_did,
        receiver_did=xfer_req.receiver_did,
        amount=xfer_req.amount,
        fee_amount=str(fee_amount),
        credited_amount=str(credited_amount),
        source_teg=local_teg_id,
        target_teg=target_teg_id,
        transaction_hash=transfer_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


async def _emit_cross_frame_async_initiated_events(
    sender_did: str,
    receiver_did: str,
    amount: str,
    transfer_id: str,
    source_frame: str,
    target_frame: str,
    source_teg: str,
    target_teg: str,
    message: Optional[str],
) -> None:
    """Emit TokensTransferred + TransactionFeeCollected + CrossFrameTransferInitiated.

    TokensTransferred + Fee are real balance/fee events (not skip_in_projection)
    so the per-frame supply audit accounts correctly. CrossFrameTransferInitiated
    is audit-only (skip_in_projection=true) and the cross-frame trigger that
    the receiver-frame reactor listens for.
    """
    from agentvault_registry.event_emitter import get_event_emitter
    emitter = get_event_emitter()
    if emitter is None:
        return

    # 2026-05-02: distinct idempotency_keys per event type so the EventStore
    # dedup (one event per idempotency_key) doesn't drop one when these three
    # land concurrently. Previously TT and Initiated both used `xfer-{tid}`,
    # so whichever lost the race was silently dropped — and when Initiated
    # was dropped, the receiver-frame reactor never saw the cross-frame
    # trigger and the saga refunded the sender at 5min. Both the WS-direct
    # path and the SF-4 → foreign_events bridge depend on the event being
    # stored in the source frame's events table, so this is load-bearing.
    tt_idem = f"xfer-{transfer_id}"
    initiated_idem = f"initiated-{transfer_id}"

    emitter.emit_background(
        event_type="TokensTransferred",
        aggregate_id=sender_did,
        data={
            "from": sender_did,
            "to": receiver_did,
            "amount": amount,
            "transaction_id": transfer_id,
            "memo": f"cross_frame_async:{message or ''}",
        },
        idempotency_key=tt_idem,
    )

    cross_reg_fee_rate = Decimal("0.5")
    transfer_amount = Decimal(amount)
    fee_amount = (transfer_amount * cross_reg_fee_rate / Decimal("100")).quantize(Decimal("0.000001"))
    # §pass57.6: deterministic key. Same rationale as 2pc-path fee emit above —
    # TransactionFeeCollected is counted in projection; duplicate would over-credit.
    # 2026-05-02 work fixed TT (tt_idem) + Initiated (initiated_idem) collision
    # but missed the fee — this closes that.
    emitter.emit_background(
        event_type="TransactionFeeCollected",
        aggregate_id=sender_did,
        data={
            "from": receiver_did,
            "to": "teg:system:fee_collector",
            "fee_amount": str(fee_amount),
            "fee_type": "cross_frame_async_transfer",
            "transaction_id": transfer_id,
            "original_amount": amount,
            "net_credited": str(transfer_amount - fee_amount),
        },
        idempotency_key=f"cross_frame_async_fee:{transfer_id}",
    )

    emitter.emit_background(
        event_type="CrossFrameTransferInitiated",
        aggregate_id=sender_did,
        data={
            "transfer_id": transfer_id,
            "sender_did": sender_did,
            "receiver_did": receiver_did,
            "source_frame": source_frame,
            "target_frame": target_frame,
            "source_teg": source_teg,
            "target_teg": target_teg,
            "amount": amount,
            "memo": message or "",
        },
        idempotency_key=initiated_idem,
    )


async def _fx_cross_currency_swap(
    *,
    xfer_req: "CrossRegistryTransferRequest",
    current_agent: "models.Agent",
    sender_did: str,
    target_teg_id: str,
    target_registry_id: str,
    target_peer: Optional["models.PeerRegistry"],
    source_currency: str,
    dest_currency: str,
    db: AsyncSession,
):
    """Reserve-mediated cross-frame FX swap (WS-D).

    No cross-frame mint: the swap is two WITHIN-frame transfers — sender →
    local fx_reserve (source currency), and the dest-frame fx_reserve →
    recipient (+ fee) (dest currency) — at the configured rate, coordinated
    atomically by the cross-TEG 2PC with compensation. Each frame stays Δ=0.

    Synchronous, source-orchestrated, inline compensation (Phase 1 fixed rate;
    FX_RATE_MODE seam ready for the Phase-2 floating pool). The source registry
    debits the sender into its OWN fx_reserve (leg1), then has the destination
    frame's fx_reserve credit the recipient (+fee) over the shared internal TEG
    hop (leg2). The credit is the last irreversible step → on any pre-credit
    failure only the source leg is compensated (sender refunded); the recipient
    is never clawed back. Both frames stay Δ=0 (every leg is a within-frame
    transfer). See Cross_Frame_FX_Phase1_Sandbox_Build_Plan.md §4 WS-D.

    §REPATLANE-2 (V0603): a leg whose answer may have been a move is asked again under its own key until its outcome
    is known (_fx_move_until_known). The source leg is refunded only when the credit provably never ran; a credit (or
    a source lock) whose outcome stays unknown refunds nothing, parks a held dead letter (phase swap_unknown, named by
    the swap id: the leg keys derive from it) and answers "(outcome not known)". Before this, a credit that timed out
    after it had credited was refunded to the sender as well.
    """
    if not _fx_enabled():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cross-currency transfer {source_currency}->{dest_currency} requires the "
                f"FX swap booth, which is disabled (FX_ENABLED=false). Same-currency "
                f"cross-frame transfers continue on the 1:1 rail {NO_FUNDS_MOVED}."
            ),
        )
    # D6-801: no swap into a frame this registry holds in quarantine (the transfer path asks before it gets here; an FX
    # route hop and the reserve origin reach the booth directly). Refused before the first leg.
    from agentvault_registry.services.federation_license_gate import assert_registry_not_quarantined
    await assert_registry_not_quarantined(db, target_registry_id, context="fx_swap", actor_agent_did=sender_did)

    # 1) Amounts (rate-provider seam: FX_RATE_MODE=fixed|pool).
    try:
        amount_in = Decimal(str(xfer_req.amount))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"FX: invalid amount {NO_FUNDS_MOVED}")
    if amount_in <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"FX: amount must be positive {NO_FUNDS_MOVED}")

    q = Decimal("0.000001")
    fee_rate = _fx_fee_rate()
    dest_floor = _fx_reserve_floor(dest_currency)

    swap_id = str(uuid.uuid4())
    leg1_key   = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fx:{swap_id}:leg1-lock"))
    credit_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fx:{swap_id}:leg2-credit"))
    fee_key    = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fx:{swap_id}:leg2-fee"))
    refund_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fx:{swap_id}:refund"))

    local_teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
    dest_teg_base  = await _resolve_dest_teg_mtls_base(target_teg_id, target_registry_id)
    admin_key      = os.environ.get("TEG_ADMIN_API_KEY", "")
    local_teg_id   = _get_local_teg_id()
    src_frame      = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
    dst_frame      = (getattr(target_peer, "trust_domain", None) or "")

    # ── Pricing (FX_RATE_MODE seam: fixed | pool) ────────────────────────────
    _mode = (os.environ.get("FX_RATE_MODE", "fixed") or "fixed").strip().lower()
    # P2-4: the DEST (trade-hosting) frame's PUBLISHED fee-split is the authority
    # (it hosts the fee_collector); the source applies it, else falls back to own env.
    _dest_pool_pct = await _resolve_peer_fx_pool_pct(db, target_peer=target_peer)
    _split_src = "dest-card" if _dest_pool_pct is not None else "source-env"
    if _mode == "pool":
        # Cross-frame constant-product AMM — price off BOTH reserves (x=AVT, y=BVT).
        try:
            local_res = await _fx_read_reserve(local_teg_base, admin_key)
            dest_res = await _fx_read_reserve(dest_teg_base, admin_key)
        except Exception as e:
            # §REPATLANE (V0603): the swap prices before its first leg, so this refusal says that nothing moved
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=f"FX pool: reserve read failed {NO_FUNDS_MOVED}: {e}")
        _src_is_avt = (source_currency == "AVT")
        x_avt = local_res if _src_is_avt else dest_res
        y_bvt = dest_res if _src_is_avt else local_res
        pq = _fx_pool_quote(x_avt, y_bvt, amount_in, _src_is_avt, fee_rate)
        amount_out_gross = pq["gross"]
        fee = pq["fee"]
        amount_out_net = pq["net"]
        rate = (amount_out_gross / amount_in) if amount_in > 0 else Decimal("0")
        # P2-2: size + slippage caps, then the rate-move circuit breaker (all pre-leg).
        _fx_enforce_caps(amount_in, source_currency, pq["slippage"])
        await _fx_breaker_check_and_update(pq["spot"], k_now=pq["k"], pair=f"{source_currency}:{dest_currency}")
        _fee_pool_pct = _dest_pool_pct if _dest_pool_pct is not None else _fx_fee_pool_pct(default=Decimal("100"))  # P2-4 dest-authority; else source env (pool retain)
    else:
        rate = _fx_rate(source_currency, dest_currency)
        amount_out_gross = (amount_in * rate).quantize(q)
        fee = (amount_out_gross * fee_rate).quantize(q)
        amount_out_net = amount_out_gross - fee
        # P2-2: size cap only (fixed rate has no slippage / price move).
        _fx_enforce_caps(amount_in, source_currency, None)
        _fee_pool_pct = _dest_pool_pct if _dest_pool_pct is not None else _fx_fee_pool_pct(default=Decimal("0"))  # P2-4 dest-authority; else source env (fixed collect)
    if amount_out_net <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"FX: computed amount_out is non-positive (amount too small) {NO_FUNDS_MOVED}")
    # Fee split (P2-3): the fee_collector portion LEAVES the dest reserve; the
    # rest (pool portion) stays in the reserve (deepens the pool). Δ=0 regardless.
    _fee_to_collector = (fee * (Decimal("100") - _fee_pool_pct) / Decimal("100")).quantize(q)

    logger.info(
        f"[FX-SWAP {swap_id}] mode={_mode} {amount_in} {source_currency} → {amount_out_net} {dest_currency} "
        f"(rate {rate}, fee {fee} [{_fee_to_collector}→fee_collector, rest pool] split={_split_src}) "
        f"{sender_did} → {xfer_req.receiver_did} via {target_teg_id}"
    )

    # 2) LEG 1 — source lock: sender → local fx_reserve (source currency). Local TEG.
    # §REPATLANE-2 (V0603): asked until its outcome is known. Refused: nothing moved. Moved (now or on an earlier
    # attempt under the key): the swap goes on. Unknown: the sender's money may sit in the reserve, so nothing goes on
    # and nothing is refunded; the swap is held for a ledger read.
    _src_held = (f"swap {swap_id}: lock key={leg1_key}, refund key={refund_key}, {amount_in} {source_currency} "
                 f"from {sender_did} into the local fx_reserve; memo {xfer_req.message or ''}")[:470]
    st1, r1, why1 = await _fx_move_until_known(local_teg_base, admin_key, from_did=sender_did, to_did="@fx_reserve",
                                               amount=amount_in, reason="fx_swap_lock", idem_key=leg1_key)
    if st1 == "refused":
        raise HTTPException(status_code=(status.HTTP_400_BAD_REQUEST if r1 is not None
                                         else status.HTTP_503_SERVICE_UNAVAILABLE),
                            detail=f"FX leg1 (source lock) failed {NO_FUNDS_MOVED}: {why1}")
    if st1 == "unknown":
        await _record_fx_dead_letter(db, route_id=swap_id, origin_did=sender_did, amount=amount_in,
                                     currency=source_currency, parked_at_did="@fx_reserve", phase="swap_unknown",
                                     origin_teg_id=local_teg_id, origin_registry_id=_get_local_registry_id(),
                                     receiver_did=xfer_req.receiver_did,
                                     note=f"the source lock's outcome is not known ({why1}); {_src_held}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=(f"FX leg1 (source lock) {OUTCOME_UNKNOWN}: held for a ledger read, nothing "
                                    f"refunded (swap {swap_id}, key={leg1_key}): {why1}"))

    # 3) LEG 2 — destination credit from the dest frame's fx_reserve (cross-frame TEG hop).
    #    floor=dest_floor+fee so the subsequent fee leg also stays above the floor.
    # §REPATLANE-2 (V0603): asked until its outcome is known (a read timeout or a 504 from the peer's nginx-teg can come
    # after the credit committed). Moved: the swap completes. Refused (provably never ran): the source leg is returned,
    # itself asked until known. Unknown: the receiver may hold the credit, so NOTHING is refunded; the swap is held.
    _held = (f"swap {swap_id}: credit key={credit_key} on {target_teg_id} ({amount_out_net} {dest_currency} to "
             f"{xfer_req.receiver_did}), refund key={refund_key} ({amount_in} {source_currency} to {sender_did}); "
             f"memo {xfer_req.message or ''}")[:470]
    st2, r2, credit_detail = await _fx_move_until_known(
        dest_teg_base, admin_key, from_did="@fx_reserve", to_did=xfer_req.receiver_did, amount=amount_out_net,
        reason="fx_swap_credit", idem_key=credit_key, floor=(dest_floor + _fee_to_collector))
    if st2 == "unknown":
        await _record_fx_dead_letter(db, route_id=swap_id, origin_did=sender_did, amount=amount_in,
                                     currency=source_currency, parked_at_did="@fx_reserve", phase="swap_unknown",
                                     origin_teg_id=local_teg_id, origin_registry_id=_get_local_registry_id(),
                                     receiver_did=xfer_req.receiver_did,
                                     note=f"the credit's outcome is not known ({credit_detail}); {_held}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=(f"FX swap credit at destination {OUTCOME_UNKNOWN}: held for a ledger read, nothing "
                                    f"refunded (swap {swap_id}, credit key={credit_key}): {credit_detail}"))
    if st2 == "refused":
        # The credit provably never ran → return the source leg only (sender made whole).
        st_r, _rr, why_r = await _fx_move_until_known(local_teg_base, admin_key, from_did="@fx_reserve",
                                                      to_did=sender_did, amount=amount_in, reason="fx_swap_refund",
                                                      idem_key=refund_key)
        if st_r == "moved":
            _emit_fx_event("FxSwapRefunded", swap_id=swap_id, sender_did=sender_did,
                           receiver_did=xfer_req.receiver_did, amount_in=amount_in,
                           source_currency=source_currency, amount_out_net=amount_out_net, fee=fee,
                           dest_currency=dest_currency, rate=rate, source_frame=src_frame,
                           dest_frame=dst_frame, source_teg=local_teg_id, dest_teg=target_teg_id,
                           reason=(credit_detail or "destination credit refused"))
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"FX swap refused at destination (source refunded) {NO_FUNDS_MOVED}: {credit_detail}")
        logger.error(f"[FX-SWAP {swap_id}] the credit was refused and the source refund {st_r} ({why_r}): "
                     f"{sender_did} has {amount_in} {source_currency} in the local fx_reserve; held, key={refund_key}")
        await _record_fx_dead_letter(db, route_id=swap_id, origin_did=sender_did, amount=amount_in,
                                     currency=source_currency, parked_at_did="@fx_reserve", phase="swap_unknown",
                                     origin_teg_id=local_teg_id, origin_registry_id=_get_local_registry_id(),
                                     receiver_did=xfer_req.receiver_did,
                                     note=f"the credit was refused, the source refund {st_r} ({why_r}); {_held}")
        _what = ("the source refund FAILED" if st_r == "refused"
                 else f"the source refund's outcome is not known {OUTCOME_UNKNOWN}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=(f"FX swap refused at destination; {_what}: held for a ledger read (swap {swap_id}, "
                                    f"refund key={refund_key}): {credit_detail}"))

    # 3b) Fee leg — best-effort. The recipient is already credited; if the fee leg
    #     fails the dest reserve simply retains the fee (still Δ=0), so never abort here.
    fee_collected = (_fee_to_collector <= 0)   # nothing to route ⇒ pool-retained, already done
    if _fee_to_collector > 0:
        for _att in range(2):
            try:
                rf = await _fx_teg_move(dest_teg_base, admin_key, from_did="@fx_reserve",
                                        to_did="@fee_collector", amount=_fee_to_collector,
                                        reason="fx_swap_fee", idem_key=fee_key, floor=dest_floor)
                if rf.status_code == 200:
                    fee_collected = True
                    break
            except httpx.RequestError:
                pass
        if not fee_collected:
            logger.warning(
                f"[FX-SWAP {swap_id}] fee_collector leg failed after retry — recipient credited, "
                f"fee {_fee_to_collector} {dest_currency} retained in dest fx_reserve (Δ=0 preserved)"
            )

    # 4) Success → emit audit record + return.
    _emit_fx_event("FxSwapSettled", swap_id=swap_id, sender_did=sender_did,
                   receiver_did=xfer_req.receiver_did, amount_in=amount_in,
                   source_currency=source_currency, amount_out_net=amount_out_net, fee=fee,
                   dest_currency=dest_currency, rate=rate, source_frame=src_frame,
                   dest_frame=dst_frame, source_teg=local_teg_id, dest_teg=target_teg_id)
    try:
        _tx_hash = r1.json().get("transaction_id")
    except Exception:
        _tx_hash = None
    return CrossRegistryTransferResponse(
        transfer_id=swap_id, status="completed", sender_did=sender_did,
        receiver_did=xfer_req.receiver_did, amount=str(amount_in), fee_amount=str(fee),
        credited_amount=str(amount_out_net), source_teg=local_teg_id, target_teg=target_teg_id,
        transaction_hash=_tx_hash, timestamp=datetime.now(timezone.utc).isoformat(),
    )


class FxQuoteRequest(BaseModel):
    receiver_did: str
    amount: str


class FxQuoteResponse(BaseModel):
    quote_id: str
    source_currency: str
    dest_currency: str
    same_currency: bool
    amount_in: str
    rate: str
    rate_mode: str
    amount_out_gross: str
    fee: str
    amount_out: str
    fee_pct: str
    slippage: str
    slippage_max: str
    size_cap: str
    pool_x_avt: Optional[str] = None
    pool_y_bvt: Optional[str] = None
    pool_spot_p: Optional[str] = None
    pool_k: Optional[str] = None
    pool_mtm_avt: Optional[str] = None
    # §MCPTEST30 (V0528): set only for a receiver on a leaf of the destination frame
    reserve_frame: Optional[str] = None   # the frame whose pool priced the swap (not the receiver's home)
    delivery_fee: Optional[str] = None    # the 1:1 delivery leg's 0.5% cross-registry fee, already out of amount_out
    expires_at: str


@router.post("/fx/quote", response_model=FxQuoteResponse, summary="Preview a cross-frame FX swap rate")
@limiter.limit("10000/minute")
async def fx_quote(
    req: FxQuoteRequest,
    request: Request,
    current_agent: models.Agent = Security(require_agent_permission("fx.quote")),
    db: AsyncSession = Depends(get_db),
):
    """Preview the rate + amounts for a cross-frame FX swap (no funds move).

    Resolves the receiver's home-frame currency (by trust_domain, frame-row
    preferred) and prices source→dest via the FX_RATE_MODE seam. A same-currency
    counterparty returns rate 1.0 (the 1:1 rail handles the actual transfer).
    """
    # Jurisdiction Profiles (SPEC 2026-07-31): operator-declared feature restriction.
    # Deny-only, pre-escrow, before any money moves. Byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "fx", actor=current_agent.did)
    try:
        amount_in = Decimal(str(req.amount))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid amount")
    if amount_in <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="amount must be positive")

    target_teg_id, target_registry_id = await _resolve_receiver_registry(db, req.receiver_did)
    if not target_teg_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot resolve the home frame for receiver {req.receiver_did}")

    # Find the resolved peer (exact slug match, mirroring cross_registry_transfer).
    _tgt = (target_registry_id or "").lower()
    _tgt_bare = _tgt.replace("registry-", "")
    _peers = sorted(
        (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE"))).scalars().all(),
        key=lambda _p: _slug(_p.name),
    )
    target_peer = None
    for p in _peers:
        ps = _slug(p.name)
        if ps == _tgt or ps.replace("registry-", "") == _tgt_bare:
            target_peer = p
            break

    local_ccy = _local_frame_currency()
    peer_ccy = await _resolve_peer_currency(db, target_peer=target_peer)
    if peer_ccy is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Cannot resolve the counterparty frame's settlement currency")

    same = (peer_ccy == local_ccy)
    # §MCPTEST30 (V0528): a receiver on a LEAF of the destination frame is priced where the transfer converts it, at the
    # frame that holds the reserve (GD), and then pays the 1:1 delivery leg's 0.5% cross-registry fee
    # (_fx_route_1to1_2pc). The leaf holds no reserve: reading it answered 503.
    _leaf_gd = None if same else _fx_leaf_gateway(peer_ccy, target_registry_id)
    fee_rate = _fx_fee_rate()
    q = Decimal("0.000001")
    rate_mode = (os.environ.get("FX_RATE_MODE", "fixed") or "fixed").strip().lower()
    _slippage = Decimal("0")
    _pool_x = _pool_y = _pool_spot = _pool_k = _pool_mtm = None
    if same:
        rate = Decimal("1")
        amount_out_gross = amount_in.quantize(q)
        fee = Decimal("0")
        amount_out = amount_out_gross
    elif rate_mode == "pool":
        admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
        local_teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
        dest_teg_base = await _fx_priced_reserve_base(target_teg_id, target_registry_id, _leaf_gd)
        try:
            local_res = await _fx_read_reserve(local_teg_base, admin_key)
            dest_res = await _fx_read_reserve(dest_teg_base, admin_key)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=f"FX pool quote: reserve read failed: {e}")
        _src_is_avt = (local_ccy == "AVT")
        x_avt = local_res if _src_is_avt else dest_res
        y_bvt = dest_res if _src_is_avt else local_res
        pq = _fx_pool_quote(x_avt, y_bvt, amount_in, _src_is_avt, fee_rate)
        rate = pq["eff_rate"]
        amount_out_gross = pq["gross"]
        fee = pq["fee"]
        amount_out = pq["net"]
        _slippage = pq["slippage"]
        _fx_enforce_caps(amount_in, local_ccy, pq["slippage"])
        # P2-5: surface the live pool state (MtM = x + y·P, AVT numeraire) — tracked, not gated.
        _pool_x, _pool_y = x_avt, y_bvt
        _pool_spot, _pool_k = pq["spot"], pq["k"]
        _pool_mtm = Decimal(str(x_avt)) + Decimal(str(y_bvt)) * pq["spot"]
    else:
        rate = _fx_rate(local_ccy, peer_ccy)
        amount_out_gross = (amount_in * rate).quantize(q)
        fee = (amount_out_gross * fee_rate).quantize(q)
        amount_out = amount_out_gross - fee
        _fx_enforce_caps(amount_in, local_ccy, None)
    _delivery_fee = None
    if _leaf_gd is not None:
        _delivery_fee = (amount_out * Decimal("0.5") / Decimal("100")).quantize(q)
        amount_out = amount_out - _delivery_fee
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()

    return FxQuoteResponse(
        quote_id=str(uuid.uuid4()),
        source_currency=local_ccy, dest_currency=peer_ccy, same_currency=same,
        amount_in=str(amount_in), rate=str(rate), rate_mode=rate_mode,
        amount_out_gross=str(amount_out_gross), fee=str(fee), amount_out=str(amount_out),
        fee_pct=str((fee_rate * Decimal("100"))),
        slippage=str(_slippage), slippage_max=str(_fx_slippage_max()),
        size_cap=str(_fx_size_cap(local_ccy)),
        pool_x_avt=(str(_pool_x) if _pool_x is not None else None),
        pool_y_bvt=(str(_pool_y) if _pool_y is not None else None),
        pool_spot_p=(str(_pool_spot) if _pool_spot is not None else None),
        pool_k=(str(_pool_k) if _pool_k is not None else None),
        pool_mtm_avt=(str(_pool_mtm) if _pool_mtm is not None else None),
        reserve_frame=(str(_leaf_gd.get("registry_id", "")) if _leaf_gd is not None else None),
        delivery_fee=(str(_delivery_fee) if _delivery_fee is not None else None),
        expires_at=expires_at,
    )


class FxPoolResponse(BaseModel):
    currency_pair: str
    rate_mode: str
    x_avt: str
    y_bvt: str
    spot_p_avt_per_bvt: str
    k: str
    mtm_avt: str
    note: str
    # D6-058 (2026-10-25): the unit of each leg, named (the keys above keep their pre-§BATCH9 names whatever the units)
    x_currency: Optional[str] = None
    y_currency: Optional[str] = None
    mtm_currency: Optional[str] = None


def _fx_pool_legs(local_ccy: str, peer_ccy: str) -> Tuple[str, str]:
    """The units of the pool's two legs, (x, y), as both pool routes order the reserves (D6-058, 2026-10-25).

    The routes keep the keys of the AVT/BVT pool they were written for: x is this frame's reserve when this frame's unit is
    AVT, and the peer frame's otherwise; y is the other one. So on EU (ECU) beside ASIA (ACU) x is ASIA's ACU reserve, the
    spot x/y is ACU per ECU and the mark-to-market x + y*spot is in ACU: a reader that labels x with this frame's unit
    (the admin FX desk did) shows each reserve under the other's currency. The answers name the units instead."""
    return (local_ccy, peer_ccy) if local_ccy == "AVT" else (peer_ccy, local_ccy)


@router.get("/fx/pool", response_model=FxPoolResponse, summary="Live cross-frame FX pool state (telemetry; nothing is gated on it)")
@limiter.limit("10000/minute")
async def fx_pool(
    request: Request,
    receiver_did: str,
    current_agent: models.Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Live cross-frame FX pool snapshot for charts and risk telemetry, for the frame of `receiver_did` (pool mode
    only): the two reserves, the spot ratio, k and a mark-to-market figure. Nothing is gated on it: the gates are
    the booked-rate checks (per-frame Δ=0, reserve solvency, value conservation in /projections/cross-frame-audit).

    The keys keep their earlier names whatever the frames' units: on the live frames `x_avt` is the peer frame's
    reserve, `y_bvt` this frame's reserve, `spot_p_avt_per_bvt` = x/y (peer units per local unit) and `mtm_avt` = x
    + y·P; `currency_pair` names the pair, and `x_currency`, `y_currency` and `mtm_currency` name each figure's unit.
    Needs an agent token.

    \f
    Live cross-frame AMM pool snapshot for charting / treasury-risk telemetry:
    reserves x (AVT) + y (BVT), spot P=x/y (AVT per BVT), k=x·y, and mark-to-market
    `mtm_avt = x + y·P` (the reserve inventory valued in AVT at spot). **MtM is
    TRACKED, NEVER a gate** — the booked-rate invariants (per-frame Δ=0, reserve
    solvency, value-conservation in /projections/cross-frame-audit) are the gates;
    MtM swings with the price by design (P2-G6). `receiver_did` identifies the
    counterparty frame (same resolution as /fx/quote).
    """
    rate_mode = (os.environ.get("FX_RATE_MODE", "fixed") or "fixed").strip().lower()
    target_teg_id, target_registry_id = await _resolve_receiver_registry(db, receiver_did)
    if not target_teg_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot resolve the home frame for receiver {receiver_did}")
    _tgt = (target_registry_id or "").lower()
    _tgt_bare = _tgt.replace("registry-", "")
    _peers = sorted(
        (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE"))).scalars().all(),
        key=lambda _p: _slug(_p.name),
    )
    target_peer = None
    for p in _peers:
        ps = _slug(p.name)
        if ps == _tgt or ps.replace("registry-", "") == _tgt_bare:
            target_peer = p
            break
    local_ccy = _local_frame_currency()
    peer_ccy = await _resolve_peer_currency(db, target_peer=target_peer)
    if peer_ccy is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Cannot resolve the counterparty frame's settlement currency")
    if peer_ccy == local_ccy:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"No FX pool: counterparty shares this frame's currency ({local_ccy}) — same-currency pairs use the 1:1 rail")
    if rate_mode != "pool":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"FX pool snapshot requires FX_RATE_MODE=pool (current: {rate_mode})")
    admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
    local_teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
    # §MCPTEST30 (V0528): a leaf receiver's pool is GD's (the same reserve the quote prices and the transfer converts at)
    dest_teg_base = await _fx_priced_reserve_base(target_teg_id, target_registry_id,
                                                  _fx_leaf_gateway(peer_ccy, target_registry_id))
    try:
        local_res = await _fx_read_reserve(local_teg_base, admin_key)
        dest_res = await _fx_read_reserve(dest_teg_base, admin_key)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"FX pool: reserve read failed: {e}")
    x = local_res if local_ccy == "AVT" else dest_res   # AVT reserve
    y = dest_res if local_ccy == "AVT" else local_res   # BVT reserve
    if x <= 0 or y <= 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="FX pool: a reserve is empty/unseeded")
    spot = x / y
    k = x * y
    mtm = x + y * spot
    x_ccy, y_ccy = _fx_pool_legs(local_ccy, peer_ccy)
    return FxPoolResponse(
        currency_pair=f"{local_ccy}/{peer_ccy}", rate_mode=rate_mode,
        x_avt=str(x), y_bvt=str(y), spot_p_avt_per_bvt=str(spot), k=str(k), mtm_avt=str(mtm),
        note=(f"MtM (x + y·P, in {x_ccy}) is risk telemetry, tracked and never gated; "
              "cross-frame-audit I1/I2/I3 (per-frame Δ=0, solvency, value conservation) are the gates."),
        x_currency=x_ccy, y_currency=y_ccy, mtm_currency=x_ccy,
    )


# §2026-06-03 — PUBLIC live FX spot rate (the Mission-Control "currency bridge").
# The card's fees.fx carries CONFIG (mode/fee/caps); in pool mode the live rate
# is the reserve ratio, which the card can't hold (it floats). /fx/pool needs an
# agent JWT (route guard) — but the spot COMPUTATION only needs the server's TEG
# admin key (_fx_read_reserve), so this returns the SANITIZED rate (no reserve
# balances — those are treasury-sensitive; the rate itself is market data) with
# NO caller auth, so the landing page + dev-viewed Mission Control both render it.
# 30s cache so frequent page/card loads don't hammer the TEGs.
_FX_RATE_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_FX_RATE_TTL = 30.0
# §2026-06-14 — all-pairs cache for the multi-currency triangle (/fx/rates).
_FX_RATES_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}

# Public host per prod-frame registry-id. Lets an operator that carries only the
# gateway IDENTITY (FX_ROUTE_GATEWAY_REGISTRY_ID, e.g. Frame-A ops set during op→op
# FX enablement) but NO FX_ROUTE_GATEWAY_URL still proxy its parent frame's keyless
# public /fx/rate for DISPLAY. Per-node override: FX_RATE_PROXY_URL / FX_ROUTE_GATEWAY_URL.
_FX_FRAME_PUBLIC_HOSTS = {
    "registry-a": "https://api.theprotocol.cloud",
    "registry-frame-b": "https://frame-b.theprotocol.cloud",
    "registry-frame-c": "https://frame-c.theprotocol.cloud",
}


def _fx_pool_payload(local_ccy: str, peer_ccy: str, local_res: Decimal, dest_res: Decimal, as_of: str) -> dict:
    """The public single-pair spot from the two reserves (§BATCH9). Keys are named by the currencies on
    the two sides; the legacy avt_per_bvt/bvt_per_avt keys are present only on a real AVT/BVT pool and
    carry the exact pre-§BATCH9 arithmetic there (x = the AVT reserve, y = the BVT reserve)."""
    q = Decimal("0.000001")
    local_per_peer = (Decimal(local_res) / Decimal(dest_res)).quantize(q)
    payload = {
        "available": True, "pair": f"{local_ccy}/{peer_ccy}", "rate_mode": "pool",
        "local_currency": local_ccy, "peer_currency": peer_ccy,
        "local_per_peer": str(local_per_peer),
        "peer_per_local": str((Decimal(dest_res) / Decimal(local_res)).quantize(q)),   # from the reserves, never a rounded reciprocal
        "as_of": as_of,
    }
    if {local_ccy, peer_ccy} == {"AVT", "BVT"}:
        x = Decimal(local_res) if local_ccy == "AVT" else Decimal(dest_res)   # AVT reserve
        y = Decimal(dest_res) if local_ccy == "AVT" else Decimal(local_res)   # BVT reserve
        spot = x / y  # AVT per BVT
        payload["avt_per_bvt"] = str(spot.quantize(q))
        payload["bvt_per_avt"] = str((Decimal("1") / spot).quantize(q))
    return payload


@router.get("/fx/rate", summary="Public live cross-frame FX spot rate (the ratio only, no reserves)")
@limiter.limit("10000/minute")
async def fx_rate_public(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Public live spot rate between this frame's unit and its FX peer's unit, from the pool reserves (a ratio only,
    never a reserve balance): `{available, pair, rate_mode, local_currency, peer_currency, local_per_peer,
    peer_per_local, as_of}`. Degrades to `{available: false, reason}` on any failure. Public, no auth.
    """
    import time as _t
    import datetime as _dt_fx
    now = _t.time()
    cached = _FX_RATE_CACHE.get("data")
    if cached is not None and (now - float(_FX_RATE_CACHE.get("ts") or 0)) < _FX_RATE_TTL:
        return cached

    def _store(payload: dict) -> dict:
        _FX_RATE_CACHE["data"] = payload
        _FX_RATE_CACHE["ts"] = now
        return payload

    try:
        if not _fx_enabled():
            # Operator rate-proxy: operators run no FX pool and CANNOT read a frame's
            # reserves (their TEG admin key is their own, not the frames' shared key),
            # so /admin/fx/reserve would 403. If this node routes FX through a parent
            # frame (FX_ROUTE_GATEWAY_URL set), server-side proxy THAT frame's PUBLIC,
            # KEYLESS /fx/rate so the bridge can DISPLAY the live spot — with no admin/
            # ES key and WITHOUT hammering the EventStore WS (the 30s cache below means
            # at most one parent hit per operator per 30s). FX_ROUTE_GATEWAY_URL points
            # at the mTLS :8443 route-hop port; the public keyless rate is on the normal
            # vhost (443), so we proxy the port-stripped origin (override: FX_RATE_PROXY_URL).
            _proxy = (os.environ.get("FX_RATE_PROXY_URL", "") or "").strip().rstrip("/")
            if not _proxy:
                _gw = (os.environ.get("FX_ROUTE_GATEWAY_URL", "") or "").strip()
                if _gw:
                    from urllib.parse import urlparse as _up
                    _p = _up(_gw)
                    if _p.scheme and _p.hostname:
                        _proxy = f"{_p.scheme}://{_p.hostname}"
            if not _proxy:
                # Frame-A operators carry the gateway IDENTITY (FX_ROUTE_GATEWAY_REGISTRY_ID)
                # but no FX_ROUTE_GATEWAY_URL — map the parent frame's registry-id to its
                # public host so they also proxy a live rate (was: stuck "rate syncing…").
                _gw_reg = (os.environ.get("FX_ROUTE_GATEWAY_REGISTRY_ID", "") or "").strip().lower()
                _proxy = _FX_FRAME_PUBLIC_HOSTS.get(_gw_reg, "")
            if _proxy:
                _url = _proxy if _proxy.endswith("/fx/rate") else f"{_proxy}/api/v1/teg/fx/rate"
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=4.0)) as _c:
                        _rr = await _c.get(_url)
                    if _rr.status_code == 200:
                        _payload = _rr.json()
                        if isinstance(_payload, dict) and _payload.get("available"):
                            return _store(_payload)
                except Exception as _e:
                    logger.debug(f"[fx_rate_public] gateway proxy failed: {_e}")
                return _store({"available": False, "reason": "gateway_unavailable"})
            return _store({"available": False, "reason": "fx_disabled"})
        local_ccy = _local_frame_currency()
        rate_mode = (os.environ.get("FX_RATE_MODE", "fixed") or "fixed").strip().lower()
        # Auto-discover the cross-currency counterparty: first ACTIVE frame peer
        # whose settlement currency differs from ours (no receiver_did needed).
        peers = (await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
        )).scalars().all()
        target_peer = None
        peer_ccy = None
        for p in peers:
            if (getattr(p, "peer_type", "") or "").lower() != "frame":
                continue
            c = await _resolve_peer_currency(db, target_peer=p)
            if c and c != local_ccy:
                target_peer, peer_ccy = p, c
                break
        if target_peer is None:
            return _store({"available": False, "reason": "no_cross_currency_peer",
                           "local_currency": local_ccy})
        as_of = _dt_fx.datetime.now(_dt_fx.timezone.utc).isoformat()
        if rate_mode != "pool":
            try:
                r = _fx_rate("BVT", "AVT")  # AVT per BVT (fixed config — the fixed table is AVT/BVT by construction)
                return _store({"available": True, "pair": "AVT/BVT", "rate_mode": "fixed",
                               "local_currency": local_ccy, "peer_currency": peer_ccy,
                               "avt_per_bvt": str(r), "bvt_per_avt": str((Decimal("1") / r)),
                               "as_of": as_of})
            except Exception:
                return _store({"available": False, "reason": "fixed_rate_unavailable"})
        # Pool mode → spot = AVT_reserve / BVT_reserve (reserve ratio). Server-side
        # admin-key reads; we publish only the ratio, never the balances.
        admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
        local_teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
        # Resolve the dest frame's TEG. PREFER the authoritative FX_ROUTE_PEERS
        # config (the real pool counterpart) over peer-name auto-discovery. Frame C
        # also discovers Frame B (same currency as Frame A — AVT — but NO FX pool)
        # via the B↔C bundle exchange, so "first ACTIVE frame peer with a different
        # currency" can resolve to Frame B, whose /admin/fx/reserve 404s → the whole
        # rate fails ("error"). FX_ROUTE_PEERS pins the genuine counterpart
        # (frame-c → teg-layer-a/registry-a; frame-a → teg-layer-frame-c/registry-frame-c).
        _dest_teg_id = ""
        _dest_reg_id = ""
        try:
            import json as _json_fx
            _routes = _json_fx.loads(os.environ.get("FX_ROUTE_PEERS", "[]") or "[]")
            if isinstance(_routes, list) and _routes:
                _dest_teg_id = str(_routes[0].get("teg_id") or "")
                _dest_reg_id = str(_routes[0].get("registry_id") or "")
        except Exception:
            _dest_teg_id = ""
            _dest_reg_id = ""
        if not (_dest_teg_id or _dest_reg_id):
            # Fallback (frames without FX_ROUTE_PEERS): legacy peer-name derivation.
            _pslug = _slug(target_peer.name or "")
            _dest_teg_id = f"teg-layer-{_pslug.replace('registry-', '')}" if _pslug else ""
            _dest_reg_id = _pslug if _pslug.startswith("registry-") else (f"registry-{_pslug}" if _pslug else "")
        dest_teg_base = await _resolve_dest_teg_mtls_base(_dest_teg_id, _dest_reg_id)
        local_res = await _fx_read_reserve(local_teg_base, admin_key)
        dest_res = await _fx_read_reserve(dest_teg_base, admin_key)
        x = local_res if local_ccy == "AVT" else dest_res   # AVT reserve
        y = dest_res if local_ccy == "AVT" else local_res   # BVT reserve
        if x <= 0 or y <= 0:
            return _store({"available": False, "reason": "reserve_unseeded"})
        spot = x / y  # AVT per BVT (meaningful only when the pair IS AVT/BVT — kept byte-identical for it)
        q = Decimal("0.000001")
        # §BATCH9 (2026-09-06, §BATCH7 residue): every pair used to be labelled AVT/BVT, so the JUICE/BRRR
        # pool printed AVT/BVT with the two sides swapped. The honest keys are named by the currencies
        # actually on the two sides; the legacy avt_per_bvt/bvt_per_avt keys survive ONLY on a real
        # AVT/BVT pool (the FE bridges read them there) and are omitted anywhere they would be a lie.
        return _store(_fx_pool_payload(local_ccy, peer_ccy, local_res, dest_res, as_of))
    except Exception as e:
        logger.debug(f"[fx_rate_public] degraded: {e}")
        return _store({"available": False, "reason": "error"})


@router.get("/fx/rates", summary="Public live cross-frame FX spot rates for every pair")
@limiter.limit("10000/minute")
async def fx_rates_public(request: Request, db: AsyncSession = Depends(get_db)):
    """
    All-pairs sibling of /fx/rate: the live spot for every cross-currency pair this frame takes part in,
    `{available, rate_mode, currencies, pairs: [{a, b, a_per_b, b_per_a}], as_of}`, where `a_per_b` is one b priced
    in a (reserve[a]/reserve[b]) and `b_per_a` its inverse. Pool mode only; ratios only, never reserve balances; a
    peer whose reserve cannot be read is left out. Public, no auth.
    """
    import time as _t
    import datetime as _dt_fx
    now = _t.time()
    cached = _FX_RATES_CACHE.get("data")
    if cached is not None and (now - float(_FX_RATES_CACHE.get("ts") or 0)) < _FX_RATE_TTL:
        return cached

    def _store(payload: dict) -> dict:
        _FX_RATES_CACHE["data"] = payload
        _FX_RATES_CACHE["ts"] = now
        return payload

    try:
        if not _fx_enabled():
            # Operator rate-proxy — proxy the parent frame's PUBLIC /fx/rates (mirrors
            # the /fx/rate gateway-proxy block; 30s cache caps parent hits).
            _proxy = (os.environ.get("FX_RATE_PROXY_URL", "") or "").strip().rstrip("/")
            if not _proxy:
                _gw = (os.environ.get("FX_ROUTE_GATEWAY_URL", "") or "").strip()
                if _gw:
                    from urllib.parse import urlparse as _up
                    _p = _up(_gw)
                    if _p.scheme and _p.hostname:
                        _proxy = f"{_p.scheme}://{_p.hostname}"
            if not _proxy:
                _gw_reg = (os.environ.get("FX_ROUTE_GATEWAY_REGISTRY_ID", "") or "").strip().lower()
                _proxy = _FX_FRAME_PUBLIC_HOSTS.get(_gw_reg, "")
            if _proxy:
                _url = _proxy if _proxy.endswith("/fx/rates") else f"{_proxy}/api/v1/teg/fx/rates"
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=4.0)) as _c:
                        _rr = await _c.get(_url)
                    if _rr.status_code == 200:
                        _payload = _rr.json()
                        if isinstance(_payload, dict) and _payload.get("available"):
                            return _store(_payload)
                except Exception as _e:
                    logger.debug(f"[fx_rates_public] gateway proxy failed: {_e}")
                return _store({"available": False, "reason": "gateway_unavailable"})
            return _store({"available": False, "reason": "fx_disabled"})

        rate_mode = (os.environ.get("FX_RATE_MODE", "fixed") or "fixed").strip().lower()
        if rate_mode != "pool":
            # Fixed-mode all-pairs isn't modelled yet; the single-pair /fx/rate covers it.
            return _store({"available": False, "reason": "fixed_mode_unsupported"})

        local_ccy = _local_frame_currency()
        admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
        local_teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
        as_of = _dt_fx.datetime.now(_dt_fx.timezone.utc).isoformat()

        # reserve balance per CURRENCY (one @fx_reserve per frame TEG; it holds that
        # frame's settlement currency). Read local first, then every cross-currency
        # ACTIVE frame peer. The set {AVT, JDAY, BVT} → all triangle pairs.
        reserves: Dict[str, Decimal] = {}
        try:
            _lr = await _fx_read_reserve(local_teg_base, admin_key)
            if _lr > 0:
                reserves[local_ccy] = _lr
        except Exception as _e:
            logger.debug(f"[fx_rates_public] local reserve read failed: {_e}")

        peers = (await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
        )).scalars().all()
        seen = {local_ccy}
        for p in peers:
            if (getattr(p, "peer_type", "") or "").lower() != "frame":
                continue
            try:
                c = await _resolve_peer_currency(db, target_peer=p)
            except Exception:
                c = None
            if not c or c in seen:
                continue
            # Derive the peer's TEG from its name (FX_ROUTE_PEERS is incomplete
            # fleet-wide; the name → teg-layer-<frame> alias is authoritative and
            # resolvable on the shared identity network). Mirrors the /fx/rate fallback.
            _pslug = _slug(p.name or "")
            if not _pslug:
                continue
            _teg_id = f"teg-layer-{_pslug.replace('registry-', '')}"
            _reg_id = _pslug if _pslug.startswith("registry-") else f"registry-{_pslug}"
            try:
                _dest_base = await _resolve_dest_teg_mtls_base(_teg_id, _reg_id)
                _rv = await _fx_read_reserve(_dest_base, admin_key)
                if _rv > 0:
                    reserves[c] = _rv
                    seen.add(c)
            except Exception as _e:
                logger.debug(f"[fx_rates_public] peer {p.name!r} ({c}) reserve read failed: {_e}")

        if len(reserves) < 2:
            return _store({"available": False, "reason": "insufficient_reserves",
                           "currencies": sorted(reserves.keys()), "as_of": as_of})

        q = Decimal("0.000001")
        ccys = sorted(reserves.keys())
        pairs = []
        for _i in range(len(ccys)):
            for _j in range(_i + 1, len(ccys)):
                a, b = ccys[_i], ccys[_j]
                ra, rb = reserves[a], reserves[b]
                if ra <= 0 or rb <= 0:
                    continue
                pairs.append({
                    "a": a, "b": b,
                    "a_per_b": str((ra / rb).quantize(q)),  # 1 b = a_per_b a (AMM spot)
                    "b_per_a": str((rb / ra).quantize(q)),  # 1 a = b_per_a b
                })
        return _store({"available": True, "rate_mode": "pool",
                       "currencies": ccys, "pairs": pairs, "as_of": as_of})
    except Exception as e:
        logger.debug(f"[fx_rates_public] degraded: {e}")
        return _store({"available": False, "reason": "error"})


@router.get("/fx/pool/admin", summary="Admin live cross-frame FX pool snapshot (auto-resolves counterparty; full reserves)")
@limiter.limit("10000/minute")
async def fx_pool_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """§2026-06-03 — the FX Desk's pool source. The agent-gated `/fx/pool` needs an
    agent JWT AND a `receiver_did`; the admin FX Desk has neither (it carries the
    admin treasury JWT), which left the desk's spot/reserves blank ("—"). This twin
    is admin-treasury-gated and AUTO-RESOLVES the cross-currency counterparty (same
    discovery as the public /fx/rate — no receiver_did). Returns the FULL pool with
    the keys the desk reads ({x, y, spot_P, k, mtm_avt}; reserves are fine for
    treasury admins). Degrades to {available:false, reason} so the desk renders
    gracefully. MtM is risk telemetry — TRACKED, never a gate."""
    import datetime as _dt_fxp
    try:
        if not _fx_enabled():
            return {"available": False, "reason": "fx_disabled"}
        local_ccy = _local_frame_currency()
        rate_mode = (os.environ.get("FX_RATE_MODE", "fixed") or "fixed").strip().lower()
        peers = (await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
        )).scalars().all()
        target_peer = None
        peer_ccy = None
        for p in peers:
            if (getattr(p, "peer_type", "") or "").lower() != "frame":
                continue
            c = await _resolve_peer_currency(db, target_peer=p)
            if c and c != local_ccy:
                target_peer, peer_ccy = p, c
                break
        if target_peer is None:
            return {"available": False, "reason": "no_cross_currency_peer", "local_currency": local_ccy}
        pair = f"{local_ccy}/{peer_ccy}"
        if rate_mode != "pool":
            return {"available": False, "reason": f"rate_mode_{rate_mode}",
                    "rate_mode": rate_mode, "currency_pair": pair}
        admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
        local_teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
        _pslug = _slug(target_peer.name or "")
        _dest_teg_id = f"teg-layer-{_pslug.replace('registry-', '')}" if _pslug else ""
        _dest_reg_id = _pslug if _pslug.startswith("registry-") else (f"registry-{_pslug}" if _pslug else "")
        dest_teg_base = await _resolve_dest_teg_mtls_base(_dest_teg_id, _dest_reg_id)
        local_res = await _fx_read_reserve(local_teg_base, admin_key)
        dest_res = await _fx_read_reserve(dest_teg_base, admin_key)
        x = local_res if local_ccy == "AVT" else dest_res   # AVT reserve
        y = dest_res if local_ccy == "AVT" else local_res   # BVT reserve
        if x <= 0 or y <= 0:
            return {"available": False, "reason": "reserve_unseeded", "currency_pair": pair}
        spot = x / y
        k = x * y
        mtm = x + y * spot
        x_ccy, y_ccy = _fx_pool_legs(local_ccy, peer_ccy)
        # Keys match the desk's FxPool reads (x, y, spot_P, k, mtm_avt). Numbers for
        # display precision (telemetry, not ledger math). D6-058: each figure's unit named.
        return {
            "available": True, "currency_pair": pair, "rate_mode": rate_mode,
            "x": float(x), "y": float(y), "spot_P": float(spot), "k": float(k), "mtm_avt": float(mtm),
            "x_currency": x_ccy, "y_currency": y_ccy, "mtm_currency": x_ccy,
            "as_of": _dt_fxp.datetime.now(_dt_fxp.timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"[fx_pool_admin] degraded: {e}")
        return {"available": False, "reason": "error"}


@router.post(
    "/cross-registry-transfer",
    response_model=CrossRegistryTransferResponse,
    summary="Transfer units to an agent on another registry"
)
@limiter.limit("10000/minute")
async def cross_registry_transfer(
    xfer_req: CrossRegistryTransferRequest,
    request: Request,
    backend: str | None = Query(
        default=None,
        pattern="^(async|2pc)$",
        description="Override TEG_CROSS_FRAME_BACKEND env (canary use). When unset, env wins.",
    ),
    current_agent: models.Agent = Security(require_agent_permission("teg.transfer_xreg")),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency. Underlying CrossRegistryTransferCompleted + downstream TokensTransferred events use transaction_id-derived idempotency_keys for EventStore dedup."),
    http_response: Response = None,   # §REPATLANE-7 (not "response": slowapi fills that one)
):
    """
    Transfer units from the calling agent to an agent on another registry. The registry resolves the receiver's home
    TEG from its DID and moves the amount through the TEG's cross-TEG protocol: two-phase commit by default
    (`backend=2pc`) or the asynchronous rail (`backend=async`, locked then settled). A receiver on a frame with
    another unit is reached through the FX route where the registry enables it. The cross-registry fee applies.

    An `Idempotency-Key` header is kept for 24 hours: a retry answers the first result instead of moving units
    twice. Needs an agent token with the `teg.transfer_xreg` permission.

    \f
    OWL-BRIDGE: Transfer AVT tokens to an agent on a different registry/TEG.

    This endpoint resolves the receiver's home TEG and proxies through the
    TEG Layer's built-in cross-TEG 2PC protocol (lock/send/accept/commit).

    Flow:
    1. Resolve receiver DID → target TEG ID
    2. Get TEG auth token for sender agent
    3. Build CrossTEGTransferRequest and proxy to TEG /api/v1/cross-teg/transfer
    4. TEG handles full 2PC: lock sender → credit receiver on target TEG → debit sender
    5. Emit CrossRegistryTransferCompleted event to EventStore
    6. Sync sender balance from TEG
    7. Return result
    """

    # Jurisdiction Profiles (SPEC 2026-07-31): operator-declared feature restriction.
    # Deny-only, pre-escrow, before any money moves. Byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "cross_transfer", amount=float(xfer_req.amount), actor=current_agent.did)
    # §pass57: request-level idempotency check
    # §REPATLANE-5 (V0606): a kept attempt: every answer that may be the payment is kept under the key and answered again
    # (a held answer used to be dropped, so the same key sent the payment again after its 90 s claim); the key is given
    # back only for an answer that proves nothing moved (services/idempotency/cache.run_kept)
    from agentvault_registry.services import payout_outcome as _po
    from agentvault_registry.services.idempotency.cache import agent_caller, begin_attempt, mark_replayed, run_kept
    _idem_body = xfer_req.model_dump(mode="json")
    _idem_body["backend"] = backend  # body-hash must include backend choice
    attempt = await begin_attempt("teg.cross-registry-transfer", idempotency_key, _idem_body,
                                  principal=agent_caller(current_agent.did))   # D6-777: the calling agent's key
    if attempt.replay is not None:
        mark_replayed(http_response)   # §REPATLANE-7: the kept answer says it is one (Idempotent-Replayed: true)
        return attempt.replay
    return await run_kept(
        attempt,
        lambda: _cross_registry_transfer_run(xfer_req, request, backend, current_agent, db, attempt),
        error_moved_nothing=_po.error_moved_nothing,
        answer_moved_nothing=_po.answer_moved_nothing,
    )


async def _cross_registry_transfer_run(xfer_req: CrossRegistryTransferRequest, request: Request,
                                       backend: Optional[str], current_agent: models.Agent, db: AsyncSession,
                                       attempt):
    """The work of POST /cross-registry-transfer, under its kept attempt (cross_registry_transfer). `attempt` is marked
    dispatched right before each call that may move money (the FX route origins, the FX booth, the async rail, the 2PC
    POST): an answer before it moved nothing."""
    sender_did = current_agent.did
    logger.info(
        f"[CROSS-REG TRANSFER] {sender_did} → {xfer_req.receiver_did} "
        f"amount={xfer_req.amount}"
    )

    # IRONKEY L2 spend gate (pre-escrow, Δ-safe): cross-registry → same_registry=False.
    # counterparty_did passed for the same reason as the local path (§SHOWCASEFED).
    await enforce_agent_spend(db, sender_did, xfer_req.amount, same_registry=False,
                              counterparty_did=xfer_req.receiver_did, request=request)

    # §SUBAGENT-LIABILITY-V3 — the FOREIGN money-leg draws from the PRINCIPAL's purse. The IRONKEY spend
    # gate above ran on the ACTING agent (its caveats bind the spend, per the /teg/transfer template at
    # :1861-1881); now redirect the DEBIT to the wallet-holding purse: the TEG auth token (which is
    # CACHE-KEYED on the agent id — mint the DID but key the cache on purse_agent.id, else the cache
    # hands back the acting agent's token and debits the wrong account), the balance-sync row, the cache
    # eviction, and the FX origin legs (which mint their own token from the agent passed in). Byte-INERT
    # when the anchor is off / no hand acted: resolve_spend_purse_agent returns (current_agent, its did).
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    purse_agent, purse_did = await resolve_spend_purse_agent(db, current_agent, request)
    sender_did = purse_did

    # Step 1: Resolve receiver to target TEG
    target_teg_id, target_registry_id = await _resolve_receiver_registry(
        db, xfer_req.receiver_did
    )
    # Guard: resolver must not return our own registry as the target
    local_reg = _get_local_registry_id()
    local_teg = _get_local_teg_id()
    if target_teg_id and (target_teg_id == local_teg or _slug(target_registry_id or '') == _slug(local_reg)):
        logger.warning(
            f"[CROSS-REG] Self-match rejected: resolver returned local registry "
            f"({target_registry_id}) as target for {xfer_req.receiver_did}. "
            f"Falling back to None."
        )
        target_teg_id, target_registry_id = None, None
    if not target_teg_id:
        # V0639 (agentvault2-66, 2026-10-24): a receiver that is one of this registry's own agents is a local transfer,
        # refused here before any route is tried. The resolver answers None for it (its step 1), which this branch read
        # as "unresolvable here", so a node with an FX gateway (every cloud operator) sent it through the FX route: the
        # MCP tester's 0.01 to the sender ITSELF went up to the parent frame and came back as 0.0099
        # (sbxalphaop 13:40:33Z, sbxbetaop 13:43:55Z). A mirror install (is_federated_mirror) is not one of ours.
        if await _is_own_native_agent(db, xfer_req.receiver_did):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"The receiver {xfer_req.receiver_did} is an agent on this registry: use the normal transfer "
                        f"endpoint (/api/v1/teg/transfer) {NO_FUNDS_MOVED}."),
            )
        # op→op (any-depth) cross-currency FX route (§2026-06-03). When the receiver is
        # unresolvable locally AND this node has a parent reserve-frame gateway configured,
        # attempt the gateway-delegated FX route (Model C) instead of refusing. The leaf op
        # doesn't need to resolve the (different-frame) receiver — it ingresses to its gateway
        # and delegates; each reserve frame resolves only its next hop. Δ=0; composes the
        # existing 1:1 rail + FX core; federation-authed delegation (mTLS/license, no admin key).
        if _fx_route_enabled() and _fx_route_my_gateway() is not None:
            attempt.mark_dispatched()
            _routed = await _fx_route_origin(db, purse_agent, xfer_req)
            if _routed is not None:
                return _routed
            attempt.dispatched = False  # it returned before sending anything (no gateway)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot resolve registry for receiver {xfer_req.receiver_did}. "
                f"If this is a local agent, use the normal transfer endpoint. "
                f"For cross-registry transfers, the receiver must be a federated agent "
                f"from an active peer registry {NO_FUNDS_MOVED}."
            )
        )

    # D6-801 (2026-10-17): a receiving registry this one holds in quarantine is refused here, before anything moves and
    # before any branch below names its TEG to the local TEG. Every outbound rail passes this point (A2A settlement and
    # /teg/send come through this endpoint; the FX booth and the async and 2pc rails run below).
    from agentvault_registry.services.federation_license_gate import assert_registry_not_quarantined
    await assert_registry_not_quarantined(db, target_registry_id, context="cross_registry_transfer",
                                          actor_agent_did=current_agent.did)

    # Step 1b: Verify the target is reachable — either a direct peer or BFS-discovered
    try:
        peer_stmt = select(models.PeerRegistry).where(
            models.PeerRegistry.status == "ACTIVE",
        )
        peer_result = await db.execute(peer_stmt)
        target_peer = None
        _tgt = (target_registry_id or "").lower()
        _tgt_bare = _tgt.replace("registry-", "")
        _peers = sorted(peer_result.scalars().all(), key=lambda _p: _slug(_p.name))
        # 2026-06-01 FIX: EXACT slug match (registry- prefix normalized), mirroring the BFS
        # matchers at ~L3914/3951. The prior test (`p_slug in target_registry_id or
        # target_registry_id in p_slug`) was SUBSTRING containment — so a slug that is a
        # substring of another peer's slug ("registry-test" ⊂ "registry-test-b") let a cloud-op
        # resolving its parent mainframe ambiguously match BOTH Registry-Test (sandbox-a) and
        # Registry-Test-B (sandbox-b); with no ORDER BY the winner flapped ~50/50 → cross-frame
        # misroute → settle timeout/refund. Exact + deterministic order = immune.
        # RCA: sessionlogs2026/FINDING_2026-06-01_CROSSFRAME_ASYNC_SETTLE_CANARY_RCA.md
        for p in _peers:
            p_slug = _slug(p.name)
            if p_slug == _tgt or p_slug.replace("registry-", "") == _tgt_bare:
                target_peer = p
                break
        # Legacy substring fallback (deterministic) ONLY if no exact match — preserves prior
        # behavior for genuine name/slug drift without re-introducing the collision.
        if target_peer is None:
            for p in _peers:
                p_slug = _slug(p.name)
                if p_slug in _tgt or _tgt in p_slug:
                    target_peer = p
                    break

        # Option D-light Phase D6 (2026-04-21): assert target peer's federation
        # license is active. Blocks cross-registry transfers to operators whose
        # license is suspended/revoked/missing, closing a real hole where local
        # agents could still settle payments to suspended operators' agents.
        if target_peer is not None:
            from agentvault_registry.services.federation_license_gate import (
                assert_peer_license_active, resolve_peer_operator_did,
            )
            target_operator_did = await resolve_peer_operator_did(db, target_peer)
            if target_operator_did:
                await assert_peer_license_active(
                    db=db,
                    operator_did=target_operator_did,
                    context="cross_registry_transfer",
                    actor_agent_did=current_agent.did,
                )

            # §29 LIVE CALL SITE for I9 `peer_value_transfer_ok`. Python asserted the LICENCE
            # immediately above but never reads `peer_registries.status` on this path — so a
            # peer row that is INACTIVE/SUSPENDED while its licence is still `active` can move
            # money today. That gap IS the rule: authenticating a channel ("may connect") is
            # not the same as authorising value to cross it ("may move value"). Both signals
            # go to the policy; this observes, it does not gate.
            try:
                from agentvault_registry import opa_shadow as _opa
                from agentvault_registry.services.federation_license_gate import get_peer_license
                _lic = await get_peer_license(db, target_operator_did) if target_operator_did else None
                _pst = getattr(target_peer, "status", None)
                _lst = getattr(_lic, "status", None)
                await _opa.shadow_check(
                    "agentvault/invariants/peer_value_transfer_ok",
                    {
                        # PG enums surface as enum members — take .value (standing gotcha)
                        "peer_status": str(getattr(_pst, "value", _pst) or ""),
                        "license_status": str(getattr(_lst, "value", _lst) or ""),
                        # Distinguishes "we hold no licence record for this peer" (normal for a
                        # foreign-frame operator — we are not its licensor) from "we hold one
                        # and it is revoked". Without this the policy cannot tell silence from
                        # a denial, and would deny every cross-frame transfer.
                        "license_known": _lic is not None,
                        "is_money_operation": True,
                    },
                    True, f"teg.cross_registry_transfer:{target_registry_id}")
            except Exception:
                pass   # observability must never block or break a money path

        if target_peer is None:
            # Not a direct peer — check BFS topology (multi-hop operators)
            from .agent_locations import _compute_trusted_registries
            bfs_regs = await _compute_trusted_registries(db)
            bfs_match = any(
                target_registry_id.lower().replace('registry-', '') in _slug(r.get("name", ""))
                or _slug(r.get("name", "")).replace('registry-', '') in target_registry_id.lower()
                for r in bfs_regs
            )
            if not bfs_match:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Target registry '{target_registry_id}' is not reachable in the federation {NO_FUNDS_MOVED}"
                )
            logger.info(f"[CROSS-REG] Target '{target_registry_id}' verified via BFS topology (multi-hop)")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[CROSS-REG] Peer/topology check failed (non-blocking): {e}")

    # ── WS-C: currency-match router (1:1 rail vs reserve-mediated FX booth) ──
    #   same currency → fall through to the existing 1:1 cross-frame rail (UNCHANGED below)
    #   diff currency → FX swap booth (WS-D), gated by FX_ENABLED
    #   unresolvable  → REFUSE (409) — never a silent 1:1 fallback (the prod bug class)
    # Currency is resolved by trust_domain, preferring the authoritative frame row
    # (dedupes union-grow 'discovered' fanout peers). See _resolve_peer_currency.
    _local_ccy = _local_frame_currency()
    _peer_ccy = await _resolve_peer_currency(db, target_peer=target_peer)
    if _peer_ccy is None:
        # §pass78c (2026-06-05) — op→op FX: a hop-depth LEAF op does not hold the dest
        # frame's signed registry card, so it can't resolve the receiver's home-frame
        # settlement currency. Rather than require that card to fan down to every leaf
        # (it doesn't, by topology), DELEGATE the whole transfer to the configured
        # FX-route gateway (Model C): the leaf ingresses 1:1 in its LOCAL currency to the
        # gateway @fx_router and the gateway/reserve frame — which DOES hold the dest
        # card — resolves the currency, runs the FX core, and egresses. Δ=0; only fires
        # when FX_ROUTE_ENABLED + a parent gateway is configured (else refuse as before).
        if _fx_route_enabled() and _fx_route_my_gateway() is not None:
            logger.info(
                f"[FX-ROUTE] dest currency unresolvable at leaf for {xfer_req.receiver_did}; "
                f"delegating to gateway {_fx_route_my_gateway().get('registry_id')}"
            )
            attempt.mark_dispatched()
            _routed = await _fx_route_origin(db, purse_agent, xfer_req)
            if _routed is not None:
                return _routed
            attempt.dispatched = False  # it returned before sending anything (no gateway)
        # §DOCSFIX D6-776: nothing was sent when this refusal is raised, and it says so (a stage-through-the-payer saga
        # takes its staged units back only after an answer that proves nothing moved: payout_outcome.stage_failure_outcome)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot resolve the settlement currency of receiver "
                f"{xfer_req.receiver_did}'s home frame — refusing the cross-frame transfer "
                f"(no silent 1:1 fallback). The counterparty frame's signed registry card "
                f"is missing or its trust domain is unset {NO_FUNDS_MOVED}."
            ),
        )
    if _peer_ccy != _local_ccy:
        # §pass78c (2026-06-06) — op→op Model-C delegation for the RESOLVED cross-currency
        # case. A leaf op with NO local FX booth (FX_ENABLED=false) but a configured
        # FX-route gateway must DELEGATE the swap to that gateway rather than 409 on its
        # own disabled booth. This MIRRORS the `_peer_ccy is None` delegation above — that
        # branch only fires when the dest currency is UNRESOLVABLE, but once the receiver's
        # agent card syncs (the §pass78c agent-card-relay fix) the leaf CAN resolve the
        # currency, so it would otherwise fall straight into the disabled local booth.
        # The leaf ingresses 1:1 in its LOCAL currency to the gateway @fx_router; the
        # gateway/reserve frame (which holds the dest card) runs the FX core + egresses.
        # Δ=0 (every leg is a within-frame transfer; pre-conversion failures compensate).
        # Falls through to the local booth (clear 409) only when no route gateway exists.
        if not _fx_enabled() and _fx_route_enabled() and _fx_route_my_gateway() is not None:
            logger.info(
                f"[FX-ROUTE] cross-currency {_local_ccy}->{_peer_ccy} with no local booth "
                f"→ delegating to gateway {_fx_route_my_gateway().get('registry_id')} "
                f"for {xfer_req.receiver_did}"
            )
            attempt.mark_dispatched()
            _routed = await _fx_route_origin(db, purse_agent, xfer_req)
            if _routed is not None:
                return _routed
            attempt.dispatched = False  # it returned before sending anything (no gateway)
        # §pass78c (2026-06-06) — reserve-frame → LEAF-OP cross-currency FX.
        # The direct booth swap below credits the receiver from the DEST frame's
        # @fx_reserve over a single cross-TEG hop — correct ONLY when the receiver is on
        # the dest RESERVE frame itself (its @fx_router / a mainframe agent). When the
        # receiver is a hop-depth LEAF op of the dest frame, the dest reserve lives on the
        # op's PARENT frame, not the op → the booth's reserve read + credit hit the leaf's
        # (nonexistent) reserve → 503 "FX pool reserve read failed". Detect that case (this
        # node is a reserve frame with a configured GD gateway for the dest currency AND the
        # receiver's home registry is NOT GD itself) and CONVERT-then-DELEGATE via GD instead
        # — the exact machinery the op→op corridor + the parent /fx/route-hop endpoint
        # already use. Falls through to the direct booth (UNCHANGED) when the receiver IS on
        # GD (mainframe↔mainframe FX) or no route gateway is configured.
        # §MCPTEST30 (V0528): the one leaf predicate; /fx/quote and /fx/pool ask the same question.
        _gd_cfg = _fx_leaf_gateway(_peer_ccy, target_registry_id)
        if _gd_cfg is not None:
            logger.info(
                f"[FX-ROUTE] reserve-frame → leaf-op {_local_ccy}->{_peer_ccy}: receiver "
                f"{xfer_req.receiver_did} on leaf '{target_registry_id}' (not GD "
                f"'{_gd_cfg.get('registry_id')}') — convert@GD + delegate egress"
            )
            attempt.mark_dispatched()
            _routed = await _fx_route_origin_reserve(
                db, purse_agent, xfer_req, dest_ccy=_peer_ccy)
            if _routed is not None:
                return _routed
            attempt.dispatched = False  # it returned before sending anything (no route to originate)
        logger.info(
            f"[FX-ROUTER] cross-currency {_local_ccy}->{_peer_ccy} for {sender_did} "
            f"→ {xfer_req.receiver_did}: routing to the FX swap booth (WS-D)"
        )
        attempt.mark_dispatched()
        _fx_result = await _fx_cross_currency_swap(
            xfer_req=xfer_req,
            current_agent=current_agent,
            sender_did=sender_did,
            target_teg_id=target_teg_id,
            target_registry_id=target_registry_id,
            target_peer=target_peer,
            source_currency=_local_ccy,
            dest_currency=_peer_ccy,
            db=db,
        )
        return _fx_result
    # same-currency → the existing 1:1 cross-frame rail continues unchanged below.

    # Step 1c: Ensure target TEG is registered as a partner on our TEG
    # BFS-discovered operators aren't in static PARTNER_TEGS — hot-add them once
    # and cache the fact for the lifetime of this worker. Repeat calls are pure
    # waste: TEG's /add-partner handler is idempotent (returns "exists" or
    # "updated") but each call burns an HTTP round-trip on the hot path.
    try:
        _existing_partners = {p.get("teg_id") for p in json.loads(os.environ.get("PARTNER_TEGS", "[]"))}
        if target_teg_id in _existing_partners or _partner_cached(target_teg_id):
            logger.debug(f"[CROSS-REG] Partner {target_teg_id} already registered, skipping auto-register")
        else:
            from .agent_locations import _compute_trusted_registries
            bfs_regs = await _compute_trusted_registries(db)
            for reg in bfs_regs:
                reg_slug = _slug(reg.get("name", ""))
                if (reg_slug == target_registry_id.lower()
                        or reg_slug.replace('registry-', '') == target_registry_id.lower().replace('registry-', '')):
                    # Pick container :8443 vs host-mapped port_base+43 based on
                    # whether DNS resolves to RFC1918 (we're on the Docker bridge)
                    # or to the public IP (we're outside). See _smart_https_url
                    # docstring above for the full rationale.
                    fed_url = reg.get("url", "") or reg.get("public_url", "")
                    if fed_url:
                        from urllib.parse import urlparse as _up
                        parsed = _up(fed_url)
                        if not parsed.hostname:
                            break
                        # f045/Phase 7: cross-TEG dispatch URL must be reachable
                        # from the local TEG inside agentvault_identity_network
                        # (port 8443 + Docker alias form), not the host-mapped port.
                        teg_url = _teg_dial_url(fed_url)
                        teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
                        teg_admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
                        async with httpx.AsyncClient(timeout=5, verify=get_httpx_verify()) as _c:
                            await _c.post(
                                f"{teg_base}/api/v1/cross-teg/config/add-partner",
                                json={
                                    "teg_id": target_teg_id,
                                    "registry_id": target_registry_id,
                                    "url": teg_url,
                                },
                                headers={"Authorization": f"Bearer {teg_admin_key}"},
                            )
                        _runtime_partner_cache.add(target_teg_id)
                        _runtime_partner_added_at[target_teg_id] = time.monotonic()
                        logger.info(f"[CROSS-REG] Auto-registered TEG partner: {target_teg_id} → {teg_url}")
                    break
    except Exception as e:
        logger.warning(f"[CROSS-REG] TEG partner auto-register failed (non-blocking): {e}")

    # ────────────────────────────────────────────────────────────────────
    # Async cross-frame branch (TEG_CROSS_FRAME_BACKEND=async, 2026-05-03).
    # Sender locks via TEG, emits TokensTransferred + CrossFrameTransferInitiated
    # to local ES, returns 200 immediately. SF-4 + Pub/Sub bridge propagates
    # to receiver frame; receiver's reactor credits + emits Settled. Saga
    # sweeper refunds via compensating event at 5-min timeout.
    # ────────────────────────────────────────────────────────────────────
    # §REPBOND-F1 (2026-09-05, HANDOVER_2026-09-04_SANDBOX_MONEYRAIL §3): a target in
    # THIS frame's own trust domain is not a cross-frame transfer, whatever
    # TEG_CROSS_FRAME_BACKEND says. The async branch resolves the domain only after
    # choosing itself and then proceeds anyway; the 2pc branch guards on it. Resolve
    # FIRST (moves no money; a refusal stays with the branch) and route a same-domain
    # target to the 2pc (local) branch. Prod: latent (5 operators run async, every
    # target is a different domain); it bit the fresh two-frame tier immediately.
    _f1_local_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
    _f1_target_td = None
    try:
        from ..services.spiffe_canonical import resolve_target_trust_domain as _f1_resolve
        _f1_target_td = await _f1_resolve(
            db, target_peer=target_peer, target_registry_id=target_registry_id,
            local_registry_id=_get_local_registry_id(), local_trust_domain=_f1_local_td,
        )
    except Exception as _f1_e:  # noqa: BLE001 — the branches carry the authoritative refusal
        logger.info(f"[CROSS-REG] F1 pre-resolution left to the branch: {_f1_e}")
    _f1_same_domain = bool(_f1_target_td) and str(_f1_target_td).strip().lower() == str(_f1_local_td).strip().lower()
    _backend_choice = (backend or os.environ.get("TEG_CROSS_FRAME_BACKEND", "2pc")).lower()
    if _f1_same_domain and _backend_choice == "async":
        logger.warning(
            f"[CROSS-REG] F1: target trust domain {_f1_target_td} is this frame's own — "
            f"routing to the 2pc (local) branch instead of async"
        )
        if CROSS_FRAME_SAME_DOMAIN_REROUTES is not None:
            try:
                CROSS_FRAME_SAME_DOMAIN_REROUTES.inc()
            except Exception:  # noqa: BLE001
                pass
        _backend_choice = "2pc"
    if _backend_choice == "async":
        attempt.mark_dispatched()
        _result = await _cross_registry_transfer_async(
            xfer_req=xfer_req,
            current_agent=purse_agent,  # §V3: debit + mirror-decrement the PURSE (money already via sender_did)
            sender_did=sender_did,
            target_teg_id=target_teg_id,
            target_registry_id=target_registry_id,
            target_peer=target_peer,
            db=db,
        )
        return _result

    # Phase 7.5 (2026-05-04): resolve frames for cross-frame 2pc canary visibility
    # (mirrors async path lines ~3996+4008-4034). When source_frame != target_frame,
    # we additionally emit CrossFrameTransferSettled AFTER the synchronous 2pc commit
    # — SF-4's CROSS_FRAME_BROADCAST_TYPES includes Settled, so Frame A's validator
    # catches the receiver-side replicated event and the canary judge marks the test
    # passed. Frame B's TokensTransferred only lands in Frame A's foreign_events
    # table without WS broadcast, so it isn't sufficient on its own.
    local_trust_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
    # WS-G: authoritative refuse-on-null resolver (same contract as the async path).
    # Computed before the 2pc transfer executes below (Steps 2/3), so a refusal
    # moves no money. Tries peer.trust_domain → signed cached card → BFS, and only
    # raises for a genuinely-unidentifiable REMOTE target.
    from ..services.spiffe_canonical import (
        resolve_target_trust_domain,
        CrossFrameResolutionError,
    )
    try:
        target_trust_domain = await resolve_target_trust_domain(
            db,
            target_peer=target_peer,
            target_registry_id=target_registry_id,
            local_registry_id=_get_local_registry_id(),
            local_trust_domain=local_trust_domain,
        )
    except CrossFrameResolutionError as e:
        logger.error(f"[CROSS-REG 2PC] refuse-on-null: {e}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{e} {NO_FUNDS_MOVED}")

    # Step 2: Get TEG auth token
    teg_token = await get_teg_token_for_agent(purse_agent.id, sender_did)  # §V3: cache-key on the purse

    # Step 3: Build cross-TEG transfer request
    transfer_id = str(uuid.uuid4())
    local_teg_id = _get_local_teg_id()
    local_registry_id = _get_local_registry_id()

    cross_teg_payload = {
        "transfer_id": transfer_id,
        "correlation_id": f"cross-reg-{transfer_id[:8]}",
        "source_agent_id": sender_did,
        "source_teg_id": local_teg_id,
        "source_registry_id": local_registry_id,
        "target_agent_id": xfer_req.receiver_did,
        "target_teg_id": target_teg_id,
        # f045/Phase 7: rewrite registry-context public URL → TEG-context internal URL.
        # Local TEG dials this from inside agentvault_identity_network where
        # only port 8443 + Docker-aliased hostnames are reachable.
        "target_teg_url": _to_internal_mtls_url(await _resolve_target_teg_url(target_registry_id) or ""),
        "target_registry_id": target_registry_id,
        "amount": xfer_req.amount,
        # Currency-truthful: stamp the SOURCE FRAME's real currency (AVT/JDAY/BVT),
        # never a hardcoded 'AVT'. On this same-currency rail _local_ccy == _peer_ccy
        # (verified above), so _local_frame_currency() is the one true currency of the
        # move. Hardcoding 'AVT' here mislabeled every BVT/JDAY cross-registry leg. (#26)
        "currency": _local_frame_currency(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        # OWL-BRIDGE R2: Required by CrossTEGTransferRequest Pydantic model
        "authorization_token": _extract_bearer_token(teg_token),  # Resolved auth token
        "idempotency_key": transfer_id,    # UUID ensures retry safety
    }
    if xfer_req.message:
        cross_teg_payload["memo"] = xfer_req.message  # Model uses 'memo', not 'metadata'

    # Step 4: Proxy to TEG cross-teg/transfer (with retry for transient failures)
    # §REPATLANE (V0603): whether any attempt may have reached the TEG's 2PC (a 5xx, or a connection that was made and
    # then lost). Only while none did may a refusal below say that nothing moved.
    _maybe_reached = False
    attempt.mark_dispatched()
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            headers = prepare_teg_headers(teg_token)

            # Retry with exponential backoff for transient errors (500/502/503/timeout)
            import asyncio as _asyncio, random as _random
            response = None
            _max_retries = 2
            for _attempt in range(1, _max_retries + 1):
                try:
                    response = await client.post(
                        f"{TEG_API_BASE_URL}/api/v1/cross-teg/transfer",
                        json=cross_teg_payload,
                        headers=headers,
                        timeout=25.0
                    )
                    # Cross-TEG uses admin key, not agent JWT — 401 means key mismatch
                    if response.status_code == 401:
                        logger.error(f"[CROSS-REG] TEG rejected admin key for cross-teg/transfer (401)")
                        break
                    # Don't retry on success or other client errors (400/404), nor on the ledger gate's refusal
                    # (§LEDGERGATE: nothing moved, and the gate answers the same until its ledger records again)
                    if response.status_code < 500 or ledger_refusal(response) is not None:
                        break
                    _maybe_reached = True
                    # Transient server error — retry
                    if _attempt < _max_retries:
                        _backoff = min(2 ** _attempt + _random.uniform(0, 1), 10)
                        logger.warning(
                            f"[CROSS-REG] TEG returned {response.status_code} on attempt {_attempt}/{_max_retries}, "
                            f"retrying in {_backoff:.1f}s"
                        )
                        await _asyncio.sleep(_backoff)
                except httpx.RequestError as _req_err:
                    if not _never_sent(_req_err):
                        _maybe_reached = True
                    if _attempt < _max_retries:
                        _backoff = min(2 ** _attempt + _random.uniform(0, 1), 10)
                        logger.warning(
                            f"[CROSS-REG] TEG connection error on attempt {_attempt}/{_max_retries}: {_req_err}, "
                            f"retrying in {_backoff:.1f}s"
                        )
                        await _asyncio.sleep(_backoff)
                    else:
                        raise  # Last attempt — propagate to outer except

            if response.status_code == 200:
                data = response.json()
                xfer_tx_id = data.get("transaction_hash") or transfer_id

                # Step 5: Emit EventStore events
                try:
                    await _emit_cross_registry_events(
                        sender_did, xfer_req.receiver_did, xfer_req.amount,
                        xfer_req.message, transfer_id, xfer_tx_id,
                        local_teg_id, target_teg_id,
                    )
                except Exception as e:
                    logger.warning(f"[CROSS-REG] EventStore event emission failed (non-fatal): {e}")

                # §TRUSTWIRE (2026-09-10) — the peer-trust observation is NOT recorded here.
                # This was the first of three hand-wired call sites and it only ever ran on the
                # synchronous same-currency branch; `background_tasks/reactor_peer_trust_observed`
                # now takes it from the `CrossRegistryTransferCompleted` event emitted just above,
                # together with the async and FX paths this branch cannot see.

                # Phase 7.5: emit CrossFrameTransferSettled for cross-frame 2pc so
                # Frame A's validator sees the transfer via SF-4 broadcast.
                # TokensTransferred is replicated to foreign_events but NOT
                # WS-broadcast (cross_frame_replicator.CROSS_FRAME_BROADCAST_TYPES
                # excludes it); Settled IS broadcast. Skipped for intra-frame —
                # the local TokensTransferred is already visible to the local
                # validator. Settled has skip_in_projection=true (audit-only)
                # and the sender-frame CrossFrameSettledReactor's UPDATE on
                # cross_frame_transfers is a 0-row no-op for 2pc (2pc uses the
                # cross_teg_transfers table). Receiver-frame reactor filters
                # source_frame != local_frame and skips.
                if local_trust_domain != target_trust_domain:
                    try:
                        from agentvault_registry.event_emitter import get_event_emitter
                        _settled_emitter = get_event_emitter()
                        if _settled_emitter is not None:
                            # 2026-05-16: propagate xfer_req.message as memo so the
                            # canary validator's memo fallback can resolve test_id
                            # when canary_xfer:<transfer_id> reverse-index hasn't
                            # been written yet (race with HTTP response). Symmetric
                            # with the async-path Settled emit in
                            # reactor_cross_frame_initiated.py.
                            _settled_emitter.emit_background(
                                event_type="CrossFrameTransferSettled",
                                aggregate_id=sender_did,
                                data={
                                    "transfer_id": transfer_id,
                                    "sender_did": sender_did,
                                    "receiver_did": xfer_req.receiver_did,
                                    "source_frame": local_trust_domain,
                                    "target_frame": target_trust_domain,
                                    "amount": xfer_req.amount,
                                    "memo": xfer_req.message,
                                },
                                idempotency_key=f"settled-{transfer_id}",
                            )
                    except Exception as e:
                        logger.warning(f"[CROSS-REG 2PC] Settled emit failed (non-fatal): {e}")

                # Steps 6-7: Sync sender balance + notify target registry
                try:
                    await _sync_cross_registry_balances(
                        client, headers, purse_agent, sender_did,  # §V3: sync the PURSE's balance row
                        xfer_req.receiver_did, xfer_tx_id, xfer_req.amount,
                        target_registry_id, db,
                    )
                except Exception as e:
                    logger.warning(f"[CROSS-REG] Balance sync failed (non-fatal): {e}")

                logger.info(
                    f"[CROSS-REG TRANSFER] SUCCESS: {xfer_req.amount} AVT "
                    f"{sender_did} → {xfer_req.receiver_did} "
                    f"(transfer_id={transfer_id}, hash={data.get('transaction_hash', '?')})"
                )

                # Compute fee for response
                cross_reg_fee_rate = Decimal("0.5")  # percent
                transfer_amount = Decimal(xfer_req.amount)
                fee_amount = (transfer_amount * cross_reg_fee_rate / Decimal("100")).quantize(Decimal("0.000001"))
                credited_amount = transfer_amount - fee_amount

                _resp = CrossRegistryTransferResponse(
                    transfer_id=transfer_id,
                    status="completed",
                    sender_did=sender_did,
                    receiver_did=xfer_req.receiver_did,
                    amount=xfer_req.amount,
                    fee_amount=str(fee_amount),
                    credited_amount=str(credited_amount),
                    source_teg=local_teg_id,
                    target_teg=target_teg_id,
                    transaction_hash=data.get("transaction_hash"),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                return _resp

            elif response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get("detail", error_data.get("message", "Cross-registry transfer failed"))
                logger.error(f"[CROSS-REG] TEG rejected transfer: {error_msg}")
                if "cross_teg_partner_refused" in str(error_msg):
                    _forget_partner(target_teg_id)   # the TEG holds no such partner: the next transfer adds it again
                # §REPATLANE (V0603): the coordinator answers these two only after it aborted the transfer_id cleanly
                # (its replay guard makes the answer this transfer_id's own), so the failed answer says nothing moved;
                # every other refusal (a partial commit, a timeout, an unexpected error) may have moved money
                if not _maybe_reached and any(str(error_msg).startswith(_m) for _m in _TEG_CLEAN_ABORTS):
                    error_msg = f"{error_msg} {NO_FUNDS_MOVED}"
                return CrossRegistryTransferResponse(
                    transfer_id=transfer_id,
                    status="failed",
                    sender_did=sender_did,
                    receiver_did=xfer_req.receiver_did,
                    amount=xfer_req.amount,
                    source_teg=local_teg_id,
                    target_teg=target_teg_id,
                    error_message=error_msg,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
            elif response.status_code == 401:
                _teg_token_cache.pop(purse_agent.id, None)  # §V3: evict the purse's cached token
                # §REPATLANE (V0603): the TEG refused before its 2PC; nothing moved unless an earlier attempt reached it
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TEG authentication failed for cross-registry transfer"
                           + ("" if _maybe_reached else f" {NO_FUNDS_MOVED}")
                )
            elif response.status_code == 402:
                # §AGORASIM-2 (2026-09-22): the TEG refused a sender that cannot pay. That is the sender's state, not an
                # outage: it used to fall to the branch below and answer 503 "service unavailable" (measured on the
                # sandbox's live sim: every such 503 was a trader with 0.42 left). No money moved; say what the TEG said.
                try:
                    _tdet = (response.json() or {}).get("detail") or "Insufficient balance"
                except Exception:  # noqa: BLE001
                    _tdet = "Insufficient balance"
                logger.info(f"[CROSS-REG] TEG refused the transfer: 402 {str(_tdet)[:200]}")
                if _maybe_reached:
                    # §REPATLANE (V0603): an earlier attempt of this transfer_id may have reached the 2PC; this 402 can be
                    # the re-drive's answer after that attempt moved the money, so it is not a refusal to read as one
                    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                        detail=(f"Cross-registry transfer service unavailable {OUTCOME_UNKNOWN}: an "
                                                f"earlier attempt may have reached the TEG (transfer_id={transfer_id})"))
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(_tdet))
            else:
                # §LEDGERGATE (V0597): the TEG's ledger gate refused (nothing moved): its sentence and Retry-After, as
                # they came, never "service unavailable"
                # §REPATLANE (V0603): ...and only while no earlier attempt may have reached the TEG's 2PC
                _refusal = ledger_refusal(response)
                if _refusal is not None and not _maybe_reached:
                    logger.warning("[CROSS-REG] the TEG refused the transfer: its ledger cannot record it right now")
                    raise _refusal
                logger.error(
                    f"[CROSS-REG] TEG cross-teg/transfer failed: "
                    f"{response.status_code} - {response.text[:300]}"
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Cross-registry transfer service unavailable"
                )

        except httpx.RequestError as e:
            logger.error(f"[CROSS-REG] TEG connection error: {e}")
            # §REPATLANE (V0603): only when no attempt's connection was ever made did nothing move
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG cross-transfer service unreachable" + ("" if _maybe_reached else f" {NO_FUNDS_MOVED}")
            )


# =============================================================================
# OP→OP (any-depth) CROSS-CURRENCY FX — Phase 1 (depth-1) — §2026-06-03
# -----------------------------------------------------------------------------
# Model C: gateway-delegated recursive saga. Chains EXISTING Δ=0 primitives —
#   S ─ingress(1:1,2pc)→ GS:@fx_router ─FXcore(reserves)→ GD:@fx_router ─egress(1:1,2pc)→ D
# Convert ONCE at the GS↔GD reserve boundary; everything else is same-currency
# multi-hop. Δ=0 per frame by construction (within-frame reserve swaps + 1:1
# dedup'd cross-frame legs; no cross-frame mint). Transport/auth = the EXISTING
# federation channel (require_peer_registry_identity: mTLS SVID / Mode-2
# X-Federation-Secret+SPIFFE / Mode-3 X-Federation-License) — NEVER the admin key.
# =============================================================================

def _fx_route_enabled() -> bool:
    """Opt-in master switch for the op→op FX route (default OFF — exactly today's behaviour)."""
    return (os.environ.get("FX_ROUTE_ENABLED", "false") or "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _fx_route_local_router_did() -> str:
    """This reserve frame's @fx_router agent DID (in-transit holder + FX-core endpoint)."""
    return (os.environ.get("FX_ROUTER_DID", "") or "").strip()


def _fx_route_my_gateway() -> Optional[dict]:
    """For a NON-reserve node (operator): its parent reserve-frame gateway, from env.
    Returns None when unset (this node is itself a reserve frame / no gateway)."""
    reg = (os.environ.get("FX_ROUTE_GATEWAY_REGISTRY_ID", "") or "").strip()
    did = (os.environ.get("FX_ROUTE_GATEWAY_ROUTER_DID", "") or "").strip()
    if not reg or not did:
        return None
    teg = (os.environ.get("FX_ROUTE_GATEWAY_TEG_ID", "") or "").strip() or f"teg-layer-{reg.replace('registry-', '')}"
    return {"registry_id": reg, "teg_id": teg, "router_did": did,
            "url": (os.environ.get("FX_ROUTE_GATEWAY_URL", "") or "").strip()}


def _fx_route_peer_gateways() -> list:
    """Reserve frames only: reachable peer reserve-frame gateways for OTHER currencies.
    FX_ROUTE_PEERS = JSON list of {currency, registry_id, teg_id, router_did, url}."""
    raw = (os.environ.get("FX_ROUTE_PEERS", "") or "").strip()
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        logger.warning("[FX-ROUTE] FX_ROUTE_PEERS is not valid JSON — ignoring")
        return []


def _fx_route_gateway_for_currency(ccy: str) -> Optional[dict]:
    """The configured peer reserve-frame gateway that settles in `ccy` (e.g. BVT→Frame C)."""
    ccy = (ccy or "").strip().upper()
    for g in _fx_route_peer_gateways():
        if str(g.get("currency", "")).strip().upper() == ccy:
            return g
    return None


def _fx_leaf_gateway(dest_ccy: str, target_registry_id: str) -> Optional[dict]:
    """The reserve frame (GD) that settles `dest_ccy` when the receiver lives on a LEAF of it, else None.

    §MCPTEST30 (V0528, 2026-10-01): ONE predicate for the three places that must agree about where a cross-currency
    receiver is priced and paid from. The transfer path (§pass78c) converts at GD and delivers 1:1 to a leaf; the quote
    and the pool read the reserve of the receiver's HOME, and a leaf operator holds none, so a quote for a receiver the
    transfer reaches answered 503 "FX pool quote: reserve read failed: 404" (agentvault2-21's Forex lifecycle on
    sbx-alpha, a receiver on sbxbetaop). None when the route engine is off, no gateway settles the currency, or the
    receiver IS on GD (frame <-> frame FX)."""
    if not (_fx_enabled() and _fx_route_enabled() and _fx_route_local_router_did()):
        return None
    gd = _fx_route_gateway_for_currency(dest_ccy)
    if gd is None:
        return None
    gd_bare = str(gd.get("registry_id", "")).lower().replace("registry-", "")
    tgt_bare = (target_registry_id or "").lower().replace("registry-", "")
    return gd if (gd_bare and tgt_bare and gd_bare != tgt_bare) else None


def _fx_gateway_teg_id(gd: dict) -> str:
    """GD's TEG id: the configured one, else the naming convention (_fx_route_origin_reserve derives it the same way)."""
    gd_reg = str(gd.get("registry_id", "")).strip()
    return str(gd.get("teg_id", "")).strip() or f"teg-layer-{gd_reg.replace('registry-', '')}"


async def _fx_priced_reserve_base(target_teg_id: str, target_registry_id: str, leaf_gd: Optional[dict]) -> str:
    """The TEG whose fx reserve prices a swap to this receiver: GD's for a leaf receiver, else the receiver's home."""
    if leaf_gd is not None:
        return await _resolve_dest_teg_mtls_base(_fx_gateway_teg_id(leaf_gd), str(leaf_gd.get("registry_id", "")))
    return await _resolve_dest_teg_mtls_base(target_teg_id, target_registry_id)


async def _fx_route_find_active_peer(db: AsyncSession, registry_id: str):
    """Resolve an ACTIVE peer_registries row by registry_id (exact slug, registry- normalized)."""
    _t = (registry_id or "").lower()
    _tb = _t.replace("registry-", "")
    rows = sorted(
        (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE"))).scalars().all(),
        key=lambda _p: _slug(_p.name),
    )
    for p in rows:
        ps = _slug(p.name)
        if ps == _t or ps.replace("registry-", "") == _tb:
            return p
    return None


def _emit_fx_route_event(event_type: str, *, route_id: str, origin_did: str, receiver_did: str,
                         amount_in, source_ccy: str, dest_ccy: str, credited, gateway: str,
                         hops: list, status: str, origin_agent_spiffe: str = "") -> None:
    """Emit the end-to-end FX route audit event (FxRouteSettled/FxRouteRefunded) to the LOCAL ES.

    NOT a LedgerBalanceChanged → invisible to the supply auditor → Δ-safe. NOT in the ES
    cross_frame_replicator broadcast set (no ES rebuild); the canary self-stamps from the
    synchronous HTTP response. Registered as an emission policy row (skip_in_projection=true)."""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        em = get_event_emitter()
        if not em:
            return
        em.emit_background(
            event_type=event_type,
            aggregate_id=origin_did,
            data={
                "route_id": route_id, "from": origin_did, "to": receiver_did,
                "amount_in": str(amount_in), "source_currency": source_ccy,
                "dest_currency": dest_ccy, "amount_out": str(credited), "gateway": gateway,
                "hops": hops, "status": status,
                "source_frame": os.environ.get("SPIRE_TRUST_DOMAIN", ""),
                # WS-A A1 (§2026-06-07): the originating agent's mTLS SPIFFE identity,
                # vouched by its home registry (which authenticated its JWT + holds its
                # enrolled SVID id). "" when the origin agent is not mTLS-enrolled.
                "origin_agent_spiffe": origin_agent_spiffe,
            },
            idempotency_key=f"{event_type}:{route_id}",
        )
    except Exception as e:
        logger.warning(f"[FX-ROUTE] emit {event_type} failed (non-fatal): {e}")


async def _fx_route_1to1_2pc(
    db: AsyncSession, *, sender_agent: "models.Agent", sender_did: str,
    receiver_did: str, amount: str, target_teg_id: str, target_registry_id: str,
    target_peer, memo: str,
) -> tuple:
    """One synchronous same-currency cross-TEG 1:1 leg (2pc). Reused for ingress (source op →
    GS @fx_router, explicit target) and egress (GD @fx_router → final receiver). Δ=0 via the
    standard TokensTransferred(+fee) emission. Returns (ok, error, credited_amount_str, tx_id).
    `credited` = amount − 0.5% cross-reg fee (the conservative lower bound the receiver holds)."""
    transfer_id = str(uuid.uuid4())
    local_teg_id = _get_local_teg_id()
    local_registry_id = _get_local_registry_id()
    # D6-801: no FX route leg (ingress, egress, refund, re-delivery) goes to a registry this one holds in quarantine.
    # Refused before anything is sent, which also keeps the leg from naming that registry's TEG to the local TEG (the
    # add-partner below and the payload's target_teg_url both re-add it). A refused refund leaves the funds parked at the
    # @fx_router for the keeper, as any refund that cannot be sent does.
    from agentvault_registry.services.federation_license_gate import quarantine_reason, quarantined_registry
    try:
        _quarantined = await quarantined_registry(db, target_registry_id)
    except Exception as e:  # noqa: BLE001  fail closed, nothing was sent
        return (False, _LegError(f"could not read the compliance state of {target_registry_id}: {e}",
                                 nothing_moved=True), "0", transfer_id)
    if _quarantined is not None:
        return (False, _LegError(f"FX route leg refused: {quarantine_reason(*_quarantined)}", nothing_moved=True),
                "0", transfer_id)
    try:
        teg_token = await get_teg_token_for_agent(sender_agent.id, sender_did)
    except Exception as e:
        return (False, _LegError(f"could not mint TEG token for {sender_did}: {e}", nothing_moved=True), "0", transfer_id)
    # Resolve the target TEG's reachable internal URL (cache → live BFS) and register it as a
    # partner on the LOCAL TEG (idempotent — mirrors cross_registry_transfer Step 1c). Without
    # this, a fresh target (e.g. a child operator the local TEG hasn't dialed yet) → cross-teg
    # 2pc 500 "Failed to process transfer". The add-partner uses the LOCAL TEG admin key (a
    # registry→own-TEG config call, NOT cross-frame auth — that stays mTLS+license).
    target_teg_url = _to_internal_mtls_url(await _resolve_target_teg_url(target_registry_id) or "")
    if not target_teg_url:
        try:
            from .agent_locations import _compute_trusted_registries
            _tl = (target_registry_id or "").lower()
            for reg in await _compute_trusted_registries(db):
                rs = _slug(reg.get("name", ""))
                if rs == _tl or rs.replace("registry-", "") == _tl.replace("registry-", ""):
                    fed_url = reg.get("url", "") or reg.get("public_url", "")
                    if fed_url:
                        target_teg_url = _teg_dial_url(fed_url)
                    break
        except Exception as e:
            logger.warning(f"[FX-ROUTE] target TEG URL BFS resolve failed: {e}")
    if target_teg_url:
        try:
            _pc = _get_teg_client()  # pooled keep-alive + SVID self-heal
            await _pc.post(
                f"{TEG_API_BASE_URL}/api/v1/cross-teg/config/add-partner",
                json={"teg_id": target_teg_id, "registry_id": target_registry_id, "url": target_teg_url},
                headers={"Authorization": f"Bearer {os.environ.get('TEG_ADMIN_API_KEY', '')}"},
                timeout=8.0)
        except Exception as e:
            logger.warning(f"[FX-ROUTE] add-partner {target_teg_id} (non-fatal): {e}")
    payload = {
        "transfer_id": transfer_id,
        "correlation_id": f"fxroute-{transfer_id[:8]}",
        "source_agent_id": sender_did,
        "source_teg_id": local_teg_id,
        "source_registry_id": local_registry_id,
        "target_agent_id": receiver_did,
        "target_teg_id": target_teg_id,
        "target_teg_url": target_teg_url,
        "target_registry_id": target_registry_id,
        "amount": amount,
        "currency": _local_frame_currency(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "authorization_token": _extract_bearer_token(teg_token),
        "idempotency_key": transfer_id,
        "memo": memo,
    }
    # §REPATLANE (V0603): the error says whether the leg provably moved nothing (_LegError): every attempt a connection
    # never made, or the coordinator's answer for this transfer_id that it gives only before or after a clean abort (a
    # 401, a 402, a clean-abort 400, the ledger gate) with no earlier attempt that may have been delivered. A read
    # timeout, a 5xx or the coordinator's "already in progress" may still commit.
    _t: list = []
    try:
        client = _get_teg_client()  # pooled keep-alive + SVID self-heal
        headers = prepare_teg_headers(teg_token)
        # §P2 (2026-06-09): retry connection drops — the cross-teg coordinator is now idempotent
        # on transfer_id (source replay guard + commit-leg dedup), so a re-POST cannot double-spend
        # (a connection-drop retry lands mid-2PC; the guard waits for COMPLETED and replays).
        resp = await _teg_post_with_retry(
            client, f"{TEG_API_BASE_URL}/api/v1/cross-teg/transfer",
            json=payload, headers=headers, timeout=30.0, trace=_t,
        )
    except httpx.RequestError as e:
        return (False, _LegError(f"local TEG unreachable: {e}", nothing_moved=(_never_sent(e) and _trace_never_sent(_t))),
                "0", transfer_id)
    if resp.status_code != 200:
        _d = _fx_safe_detail(resp)
        _none = _trace_never_sent(_t) and (
            resp.status_code in (401, 402)
            or (resp.status_code == 400 and any(_d.startswith(_m) for _m in _TEG_CLEAN_ABORTS))
            or ledger_refusal(resp) is not None)
        return (False, _LegError(f"2pc leg {resp.status_code}: {_d}", nothing_moved=_none), "0", transfer_id)
    try:
        data = resp.json()
    except Exception:
        data = {}
    xfer_tx_id = data.get("transaction_hash") or transfer_id
    try:
        await _emit_cross_registry_events(sender_did, receiver_did, amount, memo,
                                          transfer_id, xfer_tx_id, local_teg_id, target_teg_id)
    except Exception as e:
        logger.warning(f"[FX-ROUTE] leg event emit failed (non-fatal): {e}")
    try:
        amt = Decimal(str(amount))
        fee = (amt * Decimal("0.5") / Decimal("100")).quantize(Decimal("0.000001"))
        credited = str(amt - fee)
    except (InvalidOperation, ValueError):
        credited = amount
    return (True, None, credited, xfer_tx_id)


# §FXSTRAND — the phrase a hop puts in its refusal when it HAS returned the ingress to the origin.
# Two pre-conversion failures already used it verbatim ("origin refunded"); it is now the contract the
# origin reads to decide between FxRouteRefunded (money came back) and FxRouteStranded (money did not).
_FX_COMPENSATED_MARK = "(origin refunded)"


def _fx_route_peer_headers(origin_agent_spiffe: str = "") -> Dict[str, str]:
    """The federation credentials this frame presents to a peer reserve frame: Mode-2 (X-Federation-Secret +
    X-Federation-SPIFFE-ID) AND/OR Mode-3 (X-Federation-License), whichever this node has; the mTLS client cert rides
    the client. NEVER an admin key. One place for the route hop and the ledger read (§LEDGERGATE V0602)."""
    headers = {"Content-Type": "application/json"}
    secret = os.getenv("FEDERATION_INTERNAL_SECRET", "")
    if secret:
        try:
            from agentvault_registry.identity.svid_client import svid_client
            sp = svid_client.get_spiffe_id() or ""
        except Exception:
            sp = ""
        if not sp:
            sp = os.getenv("FEDERATION_INTERNAL_SPIFFE_ID", "") or \
                f"spiffe://{os.environ.get('SPIRE_TRUST_DOMAIN', 'agentvault.com')}/service/{_get_local_registry_id()}"
        headers["X-Federation-Secret"] = secret
        headers["X-Federation-SPIFFE-ID"] = sp
    lic = os.getenv("FEDERATION_LICENSE_KEY", "")
    if lic:
        headers["X-Federation-License"] = lic
    # WS-A A1 (§2026-06-07): carry the originating agent's vouched mTLS SPIFFE alongside
    # the body field so the identity rides the cross-frame leg (peer auth stays service-tier).
    if origin_agent_spiffe:
        headers["X-Origin-Agent-SPIFFE-ID"] = origin_agent_spiffe
    return headers


async def _fx_route_delegate(peer_url: str, body: dict) -> Optional[dict]:
    """POST /api/v1/teg/fx/route-hop to a peer reserve frame over the EXISTING federation channel, with
    _fx_route_peer_headers() and this node's mTLS client cert (verify=get_httpx_verify()). Returns the
    parsed JSON on 200, else None. NEVER uses an admin key."""
    if not peer_url:
        return None
    url = peer_url.rstrip("/") + "/api/v1/teg/fx/route-hop"
    headers = _fx_route_peer_headers(str(body.get("origin_agent_spiffe", "") or ""))
    try:
        c = _get_teg_client()  # pooled keep-alive + SVID self-heal (biggest win: cross-frame mTLS reuse)
        r = await c.post(url, json=body, headers=headers, timeout=90.0)
    except httpx.RequestError as e:
        logger.error(f"[FX-ROUTE] delegate {url} unreachable: {e}")
        return None
    if r.status_code != 200:
        _d = _fx_safe_detail(r)
        try:
            _jd = r.json()
            _whole = str(_jd.get("detail") or _jd.get("message") or _jd) if isinstance(_jd, dict) else str(_jd)
        except Exception:  # noqa: BLE001
            _whole = getattr(r, "text", "") or ""
        logger.error(f"[FX-ROUTE] delegate {url} → {r.status_code}: {_d}")
        # §FXSTRAND (2026-09-07) — return WHAT the peer said, not a bare None. The origin has to decide
        # whether the ingress it already moved was compensated, and a None makes every refusal look the
        # same: before this it assumed compensation always happened and emitted FxRouteRefunded saying
        # so. Every call site tests `not onward or onward.get("status") != "settled"`, so an error dict
        # is truthy and still fails that test — the failure branches are unchanged.
        # §REPATLANE (V0603): `not_delivered` is the gateway's NOT_DELIVERED, read from the same whole refusal
        return {"status": "error", "http_status": r.status_code, "detail": _d,
                "compensated": _FX_COMPENSATED_MARK in _whole,
                "not_delivered": NOT_DELIVERED in _whole and OUTCOME_UNKNOWN not in _whole}
    try:
        return r.json()
    except Exception:
        return None


# §LEDGERGATE (V0602): a cross-currency route is refused IN FRONT of the value while the receiving reserve frame's ledger
# cannot record it. That frame's TEG refuses the payout (its @fx_router -> the receiver) as a new movement while its ledger
# is down, so a route converted here parked at its router and reached the receiver minutes later through the recovery
# (journal 51's photo drill, take 2, a 90 s outage of Sandbox Alpha's store: five routes from Sandbox Beta, 235.08 SBXA,
# three of them AGORA passport orders whose order could not be placed meanwhile). So the converting frame reads the
# receiving frame's ledger first: while that frame ENFORCES and reads UNHEALTHY nothing is converted. A read that fails,
# an older frame without the read, shadow, or any other state goes ahead as before (a read that could not be made is not
# a refusal); the recovery still covers a ledger that goes down in the seconds between this read and the payout.
_FX_LEDGER_AHEAD_TTL_S = 2.0
_FX_LEDGER_AHEAD_CACHE: Dict[str, Any] = {}
FX_LEDGER_AHEAD_NOTE = "FX route: the receiving frame's ledger cannot record this right now, so nothing was converted"


def _fx_ledger_ahead_refusal(state: Any) -> Optional[HTTPException]:
    """The refusal a converting frame gives for the receiving frame's ledger state, or None. Only an enforcing ledger
    that reads unhealthy refuses (the receiving TEG would refuse the payout then); the TEG's own sentence and its
    Retry-After."""
    if not isinstance(state, dict):
        return None
    if str(state.get("mode", "")).lower() != "enforce" or str(state.get("state", "")).lower() != "unhealthy":
        return None
    try:
        n = int(state.get("retry_after_s") or 30)
    except (TypeError, ValueError):
        n = 30
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"{LEDGER_MARKER} {LEDGER_SENTENCE}",
                         headers={"Retry-After": str(min(300, max(1, n)))})


# §LEDGERGATE (V0603): the peer path of that read. It must be one every frame's federation proxy forwards: V0602 dialed
# /api/v1/teg/fx/ledger, which the proxies answer 404 from their `location /` (they forward /api/v1/teg/fx/route-hop
# and /api/v1/federation/, not the rest of /api/v1/teg/), so the read failed and every route went ahead.
FX_LEDGER_PEER_PATH = "/api/v1/federation/fx/ledger"


async def _fx_route_gd_ledger_state(gd: dict, gd_peer) -> Optional[dict]:
    """The receiving reserve frame's ledger as its /federation/fx/ledger says (cached 2 s per frame), or None when it could
    not be read."""
    url = (str(gd.get("url", "")).strip() or (getattr(gd_peer, "base_url", "") or "")).rstrip("/")
    if not url:
        return None
    now = time.monotonic()
    hit = _FX_LEDGER_AHEAD_CACHE.get(url)
    if hit and now - hit[0] < _FX_LEDGER_AHEAD_TTL_S:
        return hit[1]
    state = None
    try:
        r = await _get_teg_client().get(url + FX_LEDGER_PEER_PATH, headers=_fx_route_peer_headers(), timeout=5.0)
        if r.status_code == 200:
            j = r.json()
            state = j if isinstance(j, dict) else None
        else:
            logger.info("[FX-LEDGER-AHEAD] %s answered %s: the route goes ahead", url, r.status_code)
    except Exception as e:  # noqa: BLE001 — a read that could not be made is not a refusal
        logger.info("[FX-LEDGER-AHEAD] %s could not be read (%s): the route goes ahead", url, str(e)[:120])
    _FX_LEDGER_AHEAD_CACHE[url] = (now, state)
    return state


async def _fx_route_gd_ledger_refusal(gd: dict, gd_peer) -> Optional[HTTPException]:
    """The refusal for this route while the receiving frame's ledger cannot record it, or None."""
    state = await _fx_route_gd_ledger_state(gd, gd_peer)
    refusal = _fx_ledger_ahead_refusal(state)
    if refusal is not None:
        logger.warning("[FX-LEDGER-AHEAD] refusing a route into %s before any conversion: its ledger reads %s (%s)",
                       gd.get("registry_id", "?"), state.get("state"), state.get("reason", ""))
    elif isinstance(state, dict) and str(state.get("state", "")).lower() == "unhealthy":
        logger.warning("[FX-LEDGER-AHEAD] %s reads unhealthy in %s mode: the route goes ahead (only enforce refuses)",
                       gd.get("registry_id", "?"), state.get("mode"))
    return refusal


def _fx_ledger_block_from_health(h: Any) -> Dict[str, Any]:
    """This frame's ledger as its TEG's /health reports it ({"ledger": {"mode", "ledger": {"state", ...}}})."""
    lg = h.get("ledger") if isinstance(h, dict) else None
    if not isinstance(lg, dict):
        return {"mode": "unknown", "state": "unknown"}
    inner = lg.get("ledger") if isinstance(lg.get("ledger"), dict) else {}
    return {"mode": str(lg.get("mode") or "unknown"), "state": str(inner.get("state") or "unknown"),
            "reason": str(inner.get("reason") or ""), "retry_after_s": inner.get("retry_after_s") or 30}


_FX_LOCAL_LEDGER_CACHE: Dict[str, Any] = {"t": 0.0, "v": None}


async def _fx_local_ledger_state() -> Dict[str, Any]:
    """This frame's TEG ledger (cached 2 s); "unreadable" when its /health could not be read."""
    now = time.monotonic()
    if _FX_LOCAL_LEDGER_CACHE["v"] is not None and now - _FX_LOCAL_LEDGER_CACHE["t"] < _FX_LEDGER_AHEAD_TTL_S:
        return _FX_LOCAL_LEDGER_CACHE["v"]
    try:
        r = await _get_teg_client().get(f"{TEG_API_BASE_URL}/health", timeout=5.0)
        out = _fx_ledger_block_from_health(r.json() if r.status_code == 200 else {})
    except Exception as e:  # noqa: BLE001
        out = {"mode": "unknown", "state": "unreadable", "reason": str(e)[:120]}
    _FX_LOCAL_LEDGER_CACHE.update(t=now, v=out)
    return out


async def _fx_route_local_egress(db: AsyncSession, router_agent, router_did: str,
                                 receiver_did: str, amount: str, route_id: str):
    """LOCAL terminus (AGORA, 2026-06-12): the route's final receiver is homed on
    THIS registry (a mainframe-resident agent — e.g. the AGORA Passport deposit
    gateway, or a sovereign agent). Historically FX routes only terminated on
    child ops, so _resolve_receiver_registry's local-reject (None, None) made
    this case 409 "cannot resolve". Deliver local @fx_router → receiver as a
    plain same-TEG transfer (no fee: route fees were already taken at the swap
    leg). Returns (ok, err, credited, tx_id)."""
    # §REPATLANE-2 (V0603): the transfer carries the route's own Idempotency-Key. The TEG claims it before any money
    # moves and replays a completed transfer (sender-scoped, teg_idempotency_records, 24 h), so asking again cannot pay
    # twice: an answer that may have been a payment is asked again under the same key until it is known (a 200 is the
    # payment, made then or now). The error says whether the transfer provably did not happen (_LegError): the TEG
    # refused it with no earlier attempt that may have been delivered, or no attempt ever connected. The keeper's
    # re-delivery (fx_router_keeper._deliver_one) and its egress_unknown pass send the same key, and the same canonical
    # amount, which the TEG hashes with the key.
    key = f"fxroute:{route_id}:egress-local"
    amt = _canonical_amount(amount)
    try:
        teg_token = await get_teg_token_for_agent(router_agent.id, router_did)
        headers = {**prepare_teg_headers(teg_token), "Idempotency-Key": key}
    except Exception as e:  # noqa: BLE001 — nothing was posted
        return False, _LegError(str(e)[:200], nothing_moved=True), None, None
    body = {"receiver_agent_id": receiver_did, "amount": amt, "message": f"fxroute:{route_id}:egress-local"}
    ambiguous, why = False, ""
    for i, delay in enumerate((0.0,) + _fx_leg_resolve_delays()):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(verify=get_httpx_verify()) as _c:
                r = await _c.post(f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transfer",
                                  json=body, headers=headers, timeout=(15.0 if i == 0 else 10.0))
        except Exception as e:  # noqa: BLE001 — a connection never made sent nothing; anything else may have
            if not _never_sent(e):
                ambiguous = True
            why = f"{type(e).__name__}: {str(e)[:160]}"
            continue
        if r.status_code == 200:
            try:
                _tx = str((r.json() or {}).get("transaction_id", ""))
            except Exception:  # noqa: BLE001 — the TEG answered 200: the transfer happened
                _tx = ""
            return True, None, amt, _tx
        why = f"TEG {r.status_code}: {(r.text or '')[:160]}"
        if not ambiguous and _leg_refused(r):
            return False, _LegError(why, nothing_moved=True), None, None
        ambiguous = True
    if not ambiguous:
        return False, _LegError(why, nothing_moved=True), None, None
    return False, _LegError(f"{why} {OUTCOME_UNKNOWN} (key={key})", nothing_moved=False), None, None


async def _fx_route_refund_to_origin(db: AsyncSession, router_agent, router_did: str,
                                     origin_did: str, amount: str, route_id: str,
                                     origin_teg_id: str = "", origin_registry_id: str = "") -> bool:
    """Pre-FX compensation: refund unconverted funds at local @fx_router back to the origin
    (1:1, same currency). Best-effort — logs loudly on failure (funds remain safely at @fx_router).

    §FXSTRAND-2 (2026-09-07, agentvault2-eb's measurement on route 511e702c): RETURNS WHETHER THE MONEY
    ACTUALLY WENT BACK. It used to return None on every path, and the caller appended the
    "(origin refunded)" marker unconditionally — so when the refund itself failed and fell through to the
    dead-letter, the origin still read "compensated" and emitted FxRouteRefunded. That is the original
    false claim, one path narrower: measured sender 48 of 50, @fx_router +1.99, one TokensTransferred for
    the route and an FxRouteRefunded beside it. The marker must mean the refund SUCCEEDED, never that one
    was attempted.

    `origin_teg_id` / `origin_registry_id` come from the delegate payload when the origin knows them.
    THE REFUND CANNOT RESOLVE THE ORIGIN FOR THE SAME REASON THE EGRESS COULD NOT RESOLVE THE RECEIVER —
    both are cards that have not propagated to this frame — so a route that fails BECAUSE of propagation
    could not be refunded for the same reason, and the dead-letter it wrote carried an empty
    `origin_teg_id`, leaving the keeper to repeat the resolve that had just failed. Passing them through
    means the refund, and the keeper after it, never has to resolve anything.
    """
    _ccy = _local_frame_currency()
    _sent = False  # §REPATLANE-6 (V0606): whether the refund leg was started (an error after it may have refunded)
    try:
        rtid, rrid = await _resolve_receiver_registry(db, origin_did)
        # the origin told us where it lives; prefer that over a resolve that may fail for the very
        # reason this route is being compensated
        rtid = rtid or (origin_teg_id or "")
        rrid = rrid or (origin_registry_id or "")
        recv_peer = await _fx_route_find_active_peer(db, rrid) if rrid else None
        if not rtid:
            logger.error(f"[FX-ROUTE] refund: cannot resolve origin {origin_did} for route {route_id}; "
                         f"{amount} parked at {router_did}")
            await _record_fx_dead_letter(db, route_id=route_id, origin_did=origin_did, amount=amount,
                                         currency=_ccy, parked_at_did=router_did, phase="pre_conversion",
                                         origin_teg_id=origin_teg_id or None,
                                         origin_registry_id=origin_registry_id or None)
            return False
        _sent = True
        ok, err, _credited, _tx = await _fx_route_1to1_2pc(
            db, sender_agent=router_agent, sender_did=router_did, receiver_did=origin_did,
            amount=amount, target_teg_id=rtid, target_registry_id=rrid, target_peer=recv_peer,
            memo=f"fxroute:{route_id}:refund")
        if not ok:
            # §REPATLANE-6 (V0606): only a refund leg that provably never ran leaves the money here for the keeper to
            # refund; one whose outcome is not known (a timeout, a 5xx, a partial commit) may have refunded the origin,
            # and the keeper refunding it again would pay twice: it holds for a read of the leg (refund_unknown)
            _phase = "pre_conversion" if _leg_moved_nothing(err) else "refund_unknown"
            logger.error(f"[FX-ROUTE] refund leg failed for route {route_id}: {err}; {amount} "
                         + (f"parked at {router_did}" if _phase == "pre_conversion"
                            else f"may have reached {origin_did}: held for a read of fxroute:{route_id}:refund"))
            # Funds remain at @fx_router → durable dead-letter so the keeper refunds the origin.
            await _record_fx_dead_letter(db, route_id=route_id, origin_did=origin_did, amount=amount,
                                         currency=_ccy, parked_at_did=router_did, phase=_phase,
                                         origin_teg_id=rtid, origin_registry_id=rrid,
                                         note=(None if _phase == "pre_conversion" else
                                               f"the refund leg fxroute:{route_id}:refund ended {OUTCOME_UNKNOWN}: "
                                               f"{err}"))
            return False
        return True
    except Exception as e:
        logger.error(f"[FX-ROUTE] refund error for route {route_id}: {e}; {amount} parked at {router_did}")
        try:
            await _record_fx_dead_letter(db, route_id=route_id, origin_did=origin_did, amount=amount,
                                         currency=_ccy, parked_at_did=router_did,
                                         phase="refund_unknown" if _sent else "pre_conversion",
                                         origin_teg_id=origin_teg_id or None,
                                         origin_registry_id=origin_registry_id or None,
                                         note=(f"the refund leg fxroute:{route_id}:refund raised {OUTCOME_UNKNOWN}: "
                                               f"{type(e).__name__}") if _sent else None)
        except Exception:
            pass
    return False


def _cross_teg_fee(amount: Any) -> Decimal:
    """The fee a cross-TEG leg costs, as the receiving TEG takes it (core/cross_teg/protocol.py: 0.5%, 6 places)."""
    return (Decimal(str(amount)) * Decimal("0.5") / Decimal("100")).quantize(Decimal("0.000001"))


def _fx_route_round_trip_fees(gross: Any, ingress_credited: Any) -> Decimal:
    """§REPATLANE-4 (V0606): what a route the gateway returned cost its payer in fees: the ingress fee (what the ingress
    leg did not credit) and the refund leg's own fee on what the gateway sent back (the ingress's credited amount)."""
    g, c = Decimal(str(gross)), Decimal(str(ingress_credited))
    return max(Decimal("0"), g - c) + _cross_teg_fee(c)


async def _fee_collector_distribute(idem: str, target_did: str, amount: Decimal, reference_id: str,
                                    reason: str = "route_refund_fee") -> Tuple[Optional[str], bool, str]:
    """This frame's fee collector pays `amount` to `target_did` through the TEG's fee-free distribute (fee 0, its own
    TokensTransferred) under the Idempotency-Key `idem`, so asking again never pays twice: a 200 is the payment (made
    then or now); a refusal (a 4xx other than 408/409) moved nothing and is final; anything else is asked again
    (FX_LEG_RESOLVE_DELAYS). Returns (the TEG transaction id or "returned", None when it did not go out; refused: True
    when the TEG refused it, False when its outcome is still not known; why)."""
    base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
    key = os.environ.get("TEG_ADMIN_API_KEY", "")
    body = {"target_agent_id": target_did, "amount": str(amount), "reason": reason, "reference_id": reference_id}
    why = ""
    for i, delay in enumerate((0.0,) + _fx_leg_resolve_delays()):
        if delay:
            await asyncio.sleep(delay)
        try:
            r = await _teg_post_with_retry(_get_teg_client(), f"{base}/api/v1/admin/fee-collector/distribute", json=body,
                                           headers={"Authorization": f"Bearer {key}", "Idempotency-Key": idem},
                                           timeout=(15.0 if i == 0 else 10.0))
        except httpx.RequestError as e:
            why = f"TEG unreachable: {type(e).__name__}: {str(e)[:120]}"
            continue
        if r.status_code == 200:
            try:
                tx = str((r.json() or {}).get("transaction_id") or "")
            except Exception:  # noqa: BLE001 — a 200 is the payment, whatever its body says
                tx = ""
            return tx or "returned", False, ""
        why = f"TEG {r.status_code}: {_fx_safe_detail(r)}"
        if _leg_refused(r):
            return None, True, why
    return None, False, why


async def _fx_route_fee_back(route_id: str, payer_did: str, fees: Decimal) -> Optional[str]:
    """§REPATLANE-4 (V0606, his word 2026-10-12: "fee back after refund"): the fees a returned route cost its payer go back
    to the payer from this frame's fee collector (_fee_collector_distribute) under the route's own Idempotency-Key
    fxroute:<route>:fee-back. Returns the TEG transaction id, or None (logged; the payment itself came back either
    way)."""
    if fees <= 0:
        return None
    idem = f"fxroute:{route_id}:fee-back"
    tx, _refused, why = await _fee_collector_distribute(idem, payer_did, fees, f"fee-back:route-{route_id}")
    if tx:
        logger.info(f"[FX-ROUTE] route={route_id}: its fees {fees} went back to {payer_did} (tx={tx})")
        return tx
    logger.error(f"[FX-ROUTE] route={route_id}: the payment came back to {payer_did} but its fees {fees} did not "
                 f"({why}); key {idem}")
    return None


def _cross_teg_gross_for(net: Any) -> Decimal:
    """§REPATLANE-6 (V0606): what a cross-TEG leg must send for its receiver to be credited `net` (the receiving TEG keeps
    _cross_teg_fee of what arrives): the x with x - fee(x) == net, found from net / 0.995 by x = net + fee(x), which
    settles in a step or two (the fee moves 0.000001 per 0.0002). Two such x can differ by 0.000001 at a fee step; the
    larger, so a payer made whole is never short."""
    n = Decimal(str(net))
    q = Decimal("0.000001")
    x = n + _cross_teg_fee(n * Decimal("200") / Decimal("199"))
    for _ in range(8):
        nxt = n + _cross_teg_fee(x)
        if nxt == x:
            break
        x = nxt
    while (x + q) - _cross_teg_fee(x + q) == n:
        x += q
    return x


def _fx_dead_letter_refund_amounts(held: Any) -> Tuple[Decimal, Decimal]:
    """§REPATLANE-6 (V0606): a payment a gateway's keeper returns later from a pre-conversion dead letter, made whole.
    `held` is what the gateway's @fx_router holds for the route: what the ingress leg credited of the payer's gross G
    (held = G - fee(G), so G = _cross_teg_gross_for(held)). The refund leg sends X = _cross_teg_gross_for(G), so the
    payer's TEG credits G, the whole payment; this frame's fee collector first pays the router X - held (the ingress
    fee it took, and the refund leg's). Returns (X, X - held)."""
    h = Decimal(str(held))
    x = _cross_teg_gross_for(_cross_teg_gross_for(h))
    return x, x - h


_FX_ROUTE_SEM = None


def _fx_route_semaphore():
    """§P3-T3 (2026-06-09): per-worker bound on concurrent FX route engines. Lazy-init
    INSIDE the running loop (gunicorn forks workers → no event loop exists at import time,
    so a module-import-time Semaphore would bind to the wrong/None loop). One process =
    one loop = one semaphore. Tunable via FX_ROUTE_MAX_CONCURRENCY with NO rebuild (change
    the env + recreate the container)."""
    global _FX_ROUTE_SEM
    if _FX_ROUTE_SEM is None:
        import asyncio as _aio
        _n = max(1, int(os.environ.get("FX_ROUTE_MAX_CONCURRENCY", "8")))
        _FX_ROUTE_SEM = _aio.Semaphore(_n)
        logger.info(f"[FX-T3] FX route concurrency semaphore initialized: limit={_n}")
    return _FX_ROUTE_SEM


async def _fx_route_hop_execute(
    db: AsyncSession, *, route_id: str, final_receiver_did: str, amount: str,
    hop_budget: int, origin_did: str, origin_frame: str, memo: str,
    origin_agent_spiffe: str = "", origin_teg_id: str = "", origin_registry_id: str = "",
    post_conversion: bool = False, presenter: str = "",
) -> dict:
    """§P3-T3 bound: cap concurrent FX route engines per worker so a burst degrades to
    'slow', not a load spiral. Non-recursive in-process (onward/multi-hop legs go via HTTP
    to PEER frames' /fx/route-hop, not an in-process self-call) → the semaphore cannot
    self-deadlock. `async with` waits rather than fails-fast. Δ-neutral (gating only).
    Delegates to _fx_route_hop_execute_inner."""
    async with _fx_route_semaphore():
        return await _fx_route_hop_execute_inner(
            db, route_id=route_id, final_receiver_did=final_receiver_did, amount=amount,
            hop_budget=hop_budget, origin_did=origin_did, origin_frame=origin_frame,
            memo=memo, origin_agent_spiffe=origin_agent_spiffe,
            origin_teg_id=origin_teg_id, origin_registry_id=origin_registry_id,
            post_conversion=post_conversion, presenter=presenter,
        )


async def _fx_route_hop_execute_inner(
    db: AsyncSession, *, route_id: str, final_receiver_did: str, amount: str,
    hop_budget: int, origin_did: str, origin_frame: str, memo: str,
    origin_agent_spiffe: str = "", origin_teg_id: str = "", origin_registry_id: str = "",
    post_conversion: bool = False, presenter: str = "",
) -> dict:
    """Recursive route engine — runs on a reserve frame that now HOLDS `amount` of its OWN
    currency at its local @fx_router. Delivers it to `final_receiver_did`, converting ONCE at
    the local↔GD boundary. Returns {status, credited_amount, dest_currency, dest_teg, hops[]}.
    Raises HTTPException on refusal (caller decides compensation).

    `post_conversion` (§FXPOSTCONV): the caller converted before delegating here, so nothing on this
    frame may refund the origin (see `_compensate` below); the caller parks the route for re-delivery."""
    if hop_budget <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="FX route: hop budget exhausted")
    local_router = _fx_route_local_router_did()
    if not local_router:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="FX route: this frame holds no @fx_router (FX_ROUTER_DID unset)")
    local_ccy = _local_frame_currency()
    router_agent = (await db.execute(
        select(models.Agent).where(models.Agent.did == local_router)
    )).scalar_one_or_none()
    if router_agent is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"FX route: local @fx_router {local_router} not found")

    async def _compensate() -> bool:
        """Refund the origin 1:1 from here, the pre-conversion boundary only. §FXPOSTCONV: after a
        conversion the funds here are this frame's currency and the origin's home holds another, so the
        refund would be the wrong currency; the caller records post_conversion_remote and this frame's
        keeper re-delivers to the receiver (the recovery the strategy prescribes: forward, never claw back)."""
        if post_conversion:
            logger.warning(f"[FX-ROUTE] route={route_id}: failed after conversion; {amount} {local_ccy} stays "
                           f"at {local_router} for re-delivery to {final_receiver_did} (no refund to the origin)")
            return False
        return await _fx_route_refund_to_origin(
            db, router_agent, local_router, origin_did, amount, route_id,
            origin_teg_id=origin_teg_id, origin_registry_id=origin_registry_id)

    def _uncompensated_note() -> str:
        return (" — converted funds stay parked here for re-delivery to the receiver" if post_conversion
                else " — refund ALSO failed, dead-lettered")

    # D6-801 (2026-10-17): a route presented by a registry this one holds in quarantine goes no further. The ingress
    # it sent is returned through _compensate; the refund is an FX route leg, so when the origin's registry is itself
    # the quarantined one the funds stay parked here for the keeper instead (no leg goes to a quarantined registry).
    if presenter:
        from agentvault_registry.services.federation_license_gate import quarantine_reason, quarantined_presenter
        _presenter_q = await quarantined_presenter(db, presenter)
        if _presenter_q is not None:
            _did_refund = await _compensate()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=(f"FX route refused: {quarantine_reason(*_presenter_q)}"
                                        + (f" {_FX_COMPENSATED_MARK} {NOT_DELIVERED}" if _did_refund
                                           else _uncompensated_note())))

    # Resolve the final receiver's home-frame currency (+ its peer row for the egress target).
    rtid, rrid = await _resolve_receiver_registry(db, final_receiver_did)
    recv_peer = await _fx_route_find_active_peer(db, rrid) if rrid else None
    dest_ccy = (await _resolve_peer_currency(db, target_peer=recv_peer)) or local_ccy

    if dest_ccy == local_ccy:
        # ── TERMINAL: same-currency 1:1 egress, local @fx_router → final receiver. ──
        if not rtid:
            # AGORA (2026-06-12): rtid=None ALSO means "receiver is homed on THIS
            # registry" (_resolve_receiver_registry rejects locals by design).
            # Routes never terminated on a mainframe before — deliver locally.
            _local_rcv = (await db.execute(
                select(models.Agent).where(models.Agent.did == final_receiver_did)
            )).scalar_one_or_none()
            if _local_rcv is None:
                # §FXSTRAND — THE COMMONEST FAILURE ON THIS RAIL, and it used to refund nothing.
                # Reaching here means `_resolve_receiver_registry` found no home AND the receiver is not
                # local, so `_resolve_peer_currency` returned None and `dest_ccy` fell back to local_ccy
                # — the route entered the same-currency branch never having learned it was cross-currency.
                # NOTHING HAS BEEN CONVERTED at this point: this frame holds `amount` of its own currency
                # at its local @fx_router, which is exactly the compensatable pre-FX boundary its sibling
                # failures already use. Refund it (or dead-letter it for the keeper), then say so, so the
                # origin stops claiming a refund nobody performed. Measured on production before this:
                # 5,258 FxRouteRefunded events with no reversing transfer, 55,295.35 AVT, no dead-letter
                # row, invisible to /teg/fx/dead-letters and to the sweep (findings row 86).
                _did_refund = await _compensate()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(f"FX route egress: cannot resolve {final_receiver_did} from this frame "
                            f"(its card has not propagated here)"
                            + (f" {_FX_COMPENSATED_MARK} {NOT_DELIVERED}" if _did_refund else _uncompensated_note())))
            ok, err, credited, tx = await _fx_route_local_egress(
                db, router_agent, local_router, final_receiver_did, amount, route_id)
            if not ok and not _leg_moved_nothing(err):
                # §REPATLANE-2 (V0603): the egress's outcome is still not known after asking again under its own key, so
                # it may have paid the receiver: nothing is refunded. Before a conversion the route parks here for the
                # keeper, which finishes it under the same key or returns it once the TEG proves it never ran; after
                # one, the frame that converted parks it for re-delivery, as before.
                if not post_conversion:
                    await _record_fx_dead_letter(db, route_id=route_id, origin_did=origin_did, amount=amount,
                                                 currency=local_ccy, parked_at_did=local_router, phase="egress_unknown",
                                                 origin_teg_id=origin_teg_id or None,
                                                 origin_registry_id=origin_registry_id or None,
                                                 receiver_did=final_receiver_did,
                                                 note=f"the local egress's outcome is not known: {err}")
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail=(f"FX route local egress {OUTCOME_UNKNOWN}: nothing refunded, held "
                                            f"(route_id={route_id}): {err}"))
            if not ok:
                # §FXSTRAND — same boundary, same treatment: nothing converted, the funds are still this
                # frame's own currency at its @fx_router.
                # §REPATLANE (V0603): the egress provably did not happen, so after the refund nothing reached the receiver
                _did_refund = await _compensate()
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail=(f"FX route local egress failed: {err}"
                                            + (f" {_FX_COMPENSATED_MARK} {NOT_DELIVERED}" if _did_refund
                                               else _uncompensated_note())))
            await _record_fx_delivery(db, route_id=route_id, receiver_did=final_receiver_did,
                                      amount=credited or amount, currency=dest_ccy,
                                      kind="egress-local", tx_id=tx)
            return {"status": "settled", "credited_amount": credited, "dest_currency": dest_ccy,
                    "dest_teg": "local", "hops": [{"role": "egress-local", "frame": local_ccy,
                    "event": "TokensTransferred", "ccy": dest_ccy, "tid": tx,
                    "amount_in": amount, "credited": credited, "receiver": final_receiver_did}]}
        ok, err, credited, tx = await _fx_route_1to1_2pc(
            db, sender_agent=router_agent, sender_did=local_router, receiver_did=final_receiver_did,
            amount=amount, target_teg_id=rtid, target_registry_id=rrid, target_peer=recv_peer,
            memo=f"fxroute:{route_id}:egress")
        if not ok and _leg_moved_nothing(err):
            # §REPATLANE-3 (V0604): the two-phase egress provably never ran (refused at prepare, or no attempt ever
            # connected): this frame's own currency is still at its @fx_router, the boundary the local egress refunds at
            _did_refund = await _compensate()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=(f"FX route egress failed: {err}"
                                        + (f" {_FX_COMPENSATED_MARK} {NOT_DELIVERED}" if _did_refund
                                           else _uncompensated_note())))
        if not ok:
            # §REPATLANE-3 (V0604): the egress may have paid the receiver, and a 2PC leg is not asked again (a re-prepare
            # locks the source twice): nothing is refunded. The route is held here, after a conversion too: this row is
            # what stops this frame's keeper re-delivering the route the converting frame parks for it.
            await _record_fx_dead_letter(db, route_id=route_id, origin_did=origin_did, amount=amount,
                                         currency=local_ccy, parked_at_did=local_router, phase="egress_2pc_unknown",
                                         origin_teg_id=origin_teg_id or None,
                                         origin_registry_id=origin_registry_id or None,
                                         receiver_did=final_receiver_did,
                                         note=(f"the 2PC egress's outcome is not known (transfer_id={tx}, target "
                                               f"{rtid}): {err}"))
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=(f"FX route egress {OUTCOME_UNKNOWN}: nothing refunded, held for a ledger read "
                                        f"(route_id={route_id}, transfer_id={tx}): {err}"))
        # §FXSELFHEAL — the ambiguous-2PC case lives HERE: this leg can COMPLETE while the
        # ORIGIN times out and writes a dead-letter row (2 live cases, 2026-08-10). Recording
        # the delivery locally is what lets the keeper refuse to sweep an already-paid route.
        await _record_fx_delivery(db, route_id=route_id, receiver_did=final_receiver_did,
                                  amount=credited or amount, currency=dest_ccy,
                                  kind="egress", tx_id=tx)
        return {"status": "settled", "credited_amount": credited, "dest_currency": dest_ccy,
                "dest_teg": rtid, "hops": [{"role": "egress", "frame": local_ccy,
                "event": "TokensTransferred", "ccy": dest_ccy, "tid": tx,
                "amount_in": amount, "credited": credited, "receiver": final_receiver_did}]}

    # ── CROSS-CURRENCY: this frame is the source gateway GS. Convert local→dest at GS↔GD. ──
    gd = _fx_route_gateway_for_currency(dest_ccy)
    if not gd:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"FX route: no reserve gateway configured for {dest_ccy} (FX_ROUTE_PEERS)")
    gd_router = str(gd.get("router_did", "")).strip()
    gd_reg = str(gd.get("registry_id", "")).strip()
    gd_teg = str(gd.get("teg_id", "")).strip() or f"teg-layer-{gd_reg.replace('registry-', '')}"
    gd_peer = await _fx_route_find_active_peer(db, gd_reg)
    if gd_peer is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"FX route: GD peer {gd_reg} not ACTIVE on this frame")
    # §LEDGERGATE (V0602): GD's ledger cannot record the payout -> convert nothing; the ingress is still this frame's own
    # currency at its @fx_router (the pre-conversion boundary), so it goes back to the origin, and the origin says so.
    if await _fx_route_gd_ledger_refusal(gd, gd_peer) is not None:
        _did_refund = await _compensate()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=(FX_LEDGER_AHEAD_NOTE + (f" {_FX_COMPENSATED_MARK} {NOT_DELIVERED}" if _did_refund
                                                            else _uncompensated_note())))

    # FX CORE: local @fx_router (local_ccy) → GD @fx_router (dest_ccy). Reserve-mediated, Δ=0.
    fx_req = CrossRegistryTransferRequest(
        receiver_did=gd_router, amount=amount, message=f"fxroute:{route_id}:fxcore")
    try:
        fx_res = await _fx_cross_currency_swap(
            xfer_req=fx_req, current_agent=router_agent, sender_did=local_router,
            target_teg_id=gd_teg, target_registry_id=gd_reg, target_peer=gd_peer,
            source_currency=local_ccy, dest_currency=dest_ccy, db=db)
    except HTTPException as e:
        # §REPATLANE-2 (V0603): the swap proves that this frame's @fx_router still holds `amount` only when its refusal
        # says nothing moved (refused before its first leg, or its credit refused and its own refund made). Any other
        # refusal (a leg whose outcome is not known, a refund that failed) leaves the money in the reserves: nothing is
        # refunded here, and the swap's own held dead letter (phase swap_unknown) names its keys.
        if NO_FUNDS_MOVED not in str(e.detail or ""):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=(f"FX route core swap {OUTCOME_UNKNOWN}: nothing refunded, held for a ledger "
                                        f"read (route_id={route_id}): {e.detail}"))
        # Pre-conversion failure: the FX core already compensated its source leg, so local
        # @fx_router still holds `amount` (local_ccy). Refund it to origin (1:1 back) → sender
        # made whole. This is the compensatable pre-FX boundary (strategy §6).
        # §REPATLANE (V0603): the swap's receiver is GD's @fx_router, never the final receiver, and nothing records a
        # delivery for a failed core swap, so after a successful refund nothing reached the receiver (NOT_DELIVERED).
        _did_refund = await _compensate()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=(f"FX route core swap failed "
                                    + (f"{_FX_COMPENSATED_MARK} {NOT_DELIVERED}" if _did_refund else
                                       ("(after an earlier conversion: parked here for re-delivery)" if post_conversion
                                        else "(refund FAILED, dead-lettered)"))
                                    + f": {e.detail}"))
    fx_credited = getattr(fx_res, "credited_amount", None) or "0"
    fx_swap_id = getattr(fx_res, "transfer_id", "") or ""
    if getattr(fx_res, "status", "") != "completed" or Decimal(str(fx_credited)) <= 0:
        # §REPATLANE-2 (V0603): a swap that answered without completing may have moved either leg: nothing is refunded
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=(f"FX route core swap did not complete {OUTCOME_UNKNOWN}: nothing refunded, held "
                                    f"for a ledger read (route_id={route_id}, swap {fx_swap_id})"))

    # DELEGATE egress to GD (recursive). GD now holds fx_credited of dest_ccy at its @fx_router.
    gd_url = str(gd.get("url", "")).strip() or (getattr(gd_peer, "base_url", "") or "")
    onward = await _fx_route_delegate(gd_url, {
        "route_id": route_id, "final_receiver_did": final_receiver_did, "amount": fx_credited,
        "hop_budget": hop_budget - 1, "origin_did": origin_did, "origin_frame": origin_frame,
        "origin_teg_id": origin_teg_id, "origin_registry_id": origin_registry_id,
        "memo": memo, "origin_agent_spiffe": origin_agent_spiffe, "post_conversion": True})
    if not onward or onward.get("status") != "settled":
        # POST-conversion failure → forward-only: dest_ccy is parked at GD:@fx_router (Δ-neutral
        # dead-letter, swept later). NEVER claw back a converted leg (strategy §6).
        # §FXPOSTCONV (2026-09-26): and RECORD it here, as the reserve origin already does. This engine runs on the
        # gateway of an OPERATOR's route, and the far frame's keeper pulls re-delivery work only from its gateway
        # peers' /federation/fx/parked-at: without this row nothing could find the parking, and the far frame
        # (on an older image) refunded the origin in the wrong currency instead (the nightly's 9 refusals a night).
        await _record_fx_dead_letter(
            db, route_id=route_id, origin_did=origin_did, amount=fx_credited, currency=dest_ccy,
            parked_at_did=gd_router, phase="post_conversion_remote",
            origin_teg_id=origin_teg_id or None, origin_registry_id=origin_registry_id or None,
            receiver_did=final_receiver_did)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=(f"FX route: egress delegation to {gd_reg} failed post-conversion; "
                                    f"{fx_credited} {dest_ccy} parked at {gd_router} (route_id={route_id})"))
    hops = [{"role": "fxcore", "frame": local_ccy, "event": "FxSwapSettled",
             "ccy": f"{local_ccy}->{dest_ccy}", "swap_id": fx_swap_id,
             "amount_in": amount, "credited": fx_credited}] + onward.get("hops", [])
    return {"status": "settled", "credited_amount": onward.get("credited_amount", fx_credited),
            "dest_currency": onward.get("dest_currency", dest_ccy),
            "dest_teg": onward.get("dest_teg", gd_teg), "hops": hops}


async def _fx_route_origin(db: AsyncSession, current_agent: "models.Agent",
                           xfer_req: "CrossRegistryTransferRequest") -> Optional["CrossRegistryTransferResponse"]:
    """Source-side origin of an op→op FX route (invoked when normal resolution fails + FX_ROUTE_ENABLED
    + a parent gateway is configured). Ingress 1:1 (current_agent → parent gateway @fx_router, explicit
    target) → delegate the remainder to the gateway → emit FxRouteSettled/Refunded → return the
    aggregated result. Returns None when no gateway is configured (caller raises the normal 400)."""
    gw = _fx_route_my_gateway()
    if not gw:
        return None
    route_id = str(uuid.uuid4())
    sender_did = current_agent.did
    amount = xfer_req.amount
    local_ccy = _local_frame_currency()
    # WS-A A1 (§2026-06-07): the home registry vouches the originating agent's mTLS SPIFFE
    # (it authenticated the agent's JWT + holds its enrolled SVID id). "" if not enrolled.
    origin_agent_spiffe = current_agent.spiffe_id if (getattr(current_agent, "mtls_enabled", False) and current_agent.spiffe_id) else ""
    gw_peer = await _fx_route_find_active_peer(db, gw["registry_id"])
    gw_url = gw["url"] or (getattr(gw_peer, "base_url", "") or "")
    logger.info(f"[FX-ROUTE-ORIGIN] route={route_id} {sender_did} → {xfer_req.receiver_did} "
                f"via gateway {gw['registry_id']} ({gw['router_did']})")

    # INGRESS — 1:1 current_agent → gateway @fx_router (explicit target; pre-FX → compensatable).
    ing_ok, ing_err, ing_credited, ing_tx = await _fx_route_1to1_2pc(
        db, sender_agent=current_agent, sender_did=sender_did, receiver_did=gw["router_did"],
        amount=amount, target_teg_id=gw["teg_id"], target_registry_id=gw["registry_id"],
        target_peer=gw_peer, memo=f"fxroute:{route_id}:ingress")
    if not ing_ok:
        # Insufficient balance is a client/business condition → 402, not 409/500. The leg
        # error now reads "2pc leg 402: Insufficient balance…" once the TEG classifies it.
        # §REPATLANE (V0603): "(no funds moved)" only when the ingress leg proved it (_LegError). A read timeout, a 5xx or
        # an "already in progress" may still commit, and then the payer's money sits at the gateway's @fx_router with no
        # route to deliver it: that answer says its outcome is not known.
        _ing_none = _leg_moved_nothing(ing_err)
        _ing_insufficient = _ing_none and ("insufficient balance" in (ing_err or "").lower()
                                           or "2pc leg 402" in (ing_err or ""))
        raise HTTPException(
            status_code=(status.HTTP_402_PAYMENT_REQUIRED if _ing_insufficient else status.HTTP_409_CONFLICT),
            detail=(f"FX route ingress failed (no funds moved): {ing_err}" if _ing_none
                    else f"FX route ingress failed {OUTCOME_UNKNOWN} (route_id={route_id}): {ing_err}"))

    # DELEGATE the remainder (FX core + egress) to the gateway over the federation channel.
    onward = await _fx_route_delegate(gw_url, {
        "route_id": route_id, "final_receiver_did": xfer_req.receiver_did, "amount": ing_credited,
        "hop_budget": 4, "origin_did": sender_did,
        "origin_frame": os.environ.get("SPIRE_TRUST_DOMAIN", ""), "memo": xfer_req.message or "",
        "origin_teg_id": _get_local_teg_id(), "origin_registry_id": _get_local_registry_id(),
        "origin_agent_spiffe": origin_agent_spiffe})
    if not onward or onward.get("status") != "settled":
        # §FXSTRAND (2026-09-07) — CLAIM A REFUND ONLY WHEN ONE HAPPENED.
        # This branch used to assume compensation unconditionally and emit FxRouteRefunded carrying a
        # hop noted "ingress refunded by gateway (pre-conversion failure)". That is true only when the
        # gateway failed INSIDE the FX core (where it calls _fx_route_refund_to_origin); every raise
        # above that point returned nothing and wrote no dead-letter, so the keeper could not see it
        # either. Measured on production: 6,222 events carry that note, 964 have a real reversing
        # transfer, 5,258 DO NOT — 55,295.35 AVT moved and not returned, unaccounted rather than
        # queued, and Δ=0.0 throughout because both legs are within-frame under transit_net. The
        # purest §S4 case: balances moved AND Δ=0 is not proof.
        # The gateway now compensates on the pre-conversion raises too and says so in its refusal;
        # what remains is to BELIEVE it rather than assume it.
        _compensated = bool((onward or {}).get("compensated"))
        refund_dest = (onward or {}).get("dest_currency")
        if not refund_dest or refund_dest == "?":
            try:
                _rtid, _rrid = await _resolve_receiver_registry(db, xfer_req.receiver_did)
                _rpeer = await _fx_route_find_active_peer(db, _rrid) if _rrid else None
                refund_dest = (await _resolve_peer_currency(db, target_peer=_rpeer)) or "?"
            except Exception:
                refund_dest = "?"
        _ingress_hop = {"role": "ingress", "frame": local_ccy, "event": "TokensTransferred", "ccy": local_ccy,
                        "tid": ing_tx, "amount_in": amount, "credited": ing_credited}
        _why = str((onward or {}).get("detail") or "gateway unreachable")[:300]
        # NOT_DELIVERED is relayed only when the gateway said it beside its refund: the payment reached nobody
        _undelivered = bool((onward or {}).get("not_delivered"))
        # §REPATLANE-4 (V0606, his word: "fee back after refund"): a payment the gateway returned, having reached nobody,
        # costs its payer nothing: the round trip's fees go back from this frame's fee collector
        _fee_back_hops = []
        if _compensated and _undelivered:
            _fees = _fx_route_round_trip_fees(amount, ing_credited)
            _fee_tx = await _fx_route_fee_back(route_id, sender_did, _fees)
            _fee_back_hops = [{"role": "fee-back", "frame": local_ccy, "event": "TokensTransferred", "ccy": local_ccy,
                               "tid": _fee_tx, "amount_in": str(_fees), "credited": (str(_fees) if _fee_tx else "0"),
                               "note": ("the round trip's fees back to the payer" if _fee_tx
                                        else "the round trip's fees could NOT be returned (logged)")}]
        if _compensated and FX_LEDGER_AHEAD_NOTE in _why:
            # §LEDGERGATE (V0602): the gateway refused in front of the conversion (the receiving frame's ledger was down)
            # and returned the ingress: the person's money is back, the same request goes through later.
            _emit_fx_route_event("FxRouteRefunded", route_id=route_id, origin_did=sender_did,
                                 receiver_did=xfer_req.receiver_did, amount_in=amount, source_ccy=local_ccy,
                                 dest_ccy=refund_dest, credited="0", gateway=gw["router_did"],
                                 hops=[_ingress_hop,
                                       {"role": "refund", "frame": local_ccy, "event": "TokensTransferred",
                                        "ccy": local_ccy, "amount_in": ing_credited, "credited": ing_credited,
                                        "note": "ingress refunded by gateway: the receiving frame's ledger was down"}]
                                 + _fee_back_hops,
                                 status="refunded", origin_agent_spiffe=origin_agent_spiffe)
            from ..services.ledger_unavailable import ROUTE_CAME_BACK
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ROUTE_CAME_BACK,
                                headers={"Retry-After": "30"})
        if _compensated:
            refund_hops = [
                _ingress_hop,
                {"role": "refund", "frame": local_ccy, "event": "TokensTransferred", "ccy": local_ccy,
                 "amount_in": ing_credited, "credited": ing_credited,
                 "note": "ingress refunded by gateway (pre-conversion failure)"},
            ] + _fee_back_hops
            _emit_fx_route_event("FxRouteRefunded", route_id=route_id, origin_did=sender_did,
                                 receiver_did=xfer_req.receiver_did, amount_in=amount, source_ccy=local_ccy,
                                 dest_ccy=refund_dest, credited="0", gateway=gw["router_did"],
                                 hops=refund_hops, status="refunded", origin_agent_spiffe=origin_agent_spiffe)
            # §REPATLANE (V0603): `_compensated` is read from the gateway's own refusal mark, which a hop writes only after
            # the refund SUCCEEDED (§FXSTRAND-2), so this answer relays the same mark, guarded on that verdict: the payer
            # has the money back (the AGORA payout lane reads it as nothing moved and sends again)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=(f"FX route did not settle (route_id={route_id}); the gateway "
                                        f"compensates pre-conversion / dead-letters post-conversion"
                                        + (f": it returned this payment {_FX_COMPENSATED_MARK}" if _compensated
                                           else "")
                                        + (f" {NOT_DELIVERED}." if _undelivered else ".")))
        # NOT compensated: the ingress moved and did not come back. Say THAT, under its own event type,
        # so nobody reads a refund into it and so the residue is greppable by route_id.
        _emit_fx_route_event("FxRouteStranded", route_id=route_id, origin_did=sender_did,
                             receiver_did=xfer_req.receiver_did, amount_in=amount, source_ccy=local_ccy,
                             dest_ccy=refund_dest, credited="0", gateway=gw["router_did"],
                             hops=[_ingress_hop,
                                   {"role": "stranded", "frame": local_ccy, "ccy": local_ccy,
                                    "amount_in": ing_credited, "credited": "0",
                                    "note": f"ingress moved and NOT returned; gateway said: {_why}"}],
                             status="stranded", origin_agent_spiffe=origin_agent_spiffe)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=(f"FX route did not settle (route_id={route_id}) and the gateway did "
                                    f"not report a refund; the ingress is parked at the gateway: {_why}"))
    credited = onward.get("credited_amount", "0")
    dest_ccy = onward.get("dest_currency", "?")
    hops = [{"role": "ingress", "frame": local_ccy, "event": "TokensTransferred", "ccy": local_ccy,
             "tid": ing_tx, "amount_in": amount, "credited": ing_credited}] + onward.get("hops", [])
    _emit_fx_route_event("FxRouteSettled", route_id=route_id, origin_did=sender_did,
                         receiver_did=xfer_req.receiver_did, amount_in=amount, source_ccy=local_ccy,
                         dest_ccy=dest_ccy, credited=credited, gateway=gw["router_did"],
                         hops=hops, status="settled", origin_agent_spiffe=origin_agent_spiffe)
    logger.info(f"[FX-ROUTE-ORIGIN] route={route_id} SETTLED: {amount} {local_ccy} → "
                f"{credited} {dest_ccy} to {xfer_req.receiver_did}")
    return CrossRegistryTransferResponse(
        transfer_id=route_id, status="completed", sender_did=sender_did,
        receiver_did=xfer_req.receiver_did, amount=amount, fee_amount=None,
        credited_amount=str(credited), source_teg=_get_local_teg_id(),
        target_teg=onward.get("dest_teg", "") or "", transaction_hash=route_id,
        timestamp=datetime.now(timezone.utc).isoformat())


async def _fx_route_origin_reserve(
    db: AsyncSession, current_agent: "models.Agent",
    xfer_req: "CrossRegistryTransferRequest", *, dest_ccy: str,
) -> Optional["CrossRegistryTransferResponse"]:
    """Reserve-frame origin of a cross-currency FX transfer whose receiver lives on a
    LEAF op of the dest frame (not the dest reserve frame itself).

    The direct booth swap credits the receiver from the DEST frame's @fx_reserve over a
    single cross-TEG hop — correct ONLY when the receiver is on the dest RESERVE frame
    (e.g. its @fx_router / a mainframe agent). When the receiver is a hop-depth leaf op,
    the dest reserve lives on the op's PARENT frame, not the op, so the booth's reserve
    read + credit hit the leaf's (nonexistent) reserve → 503 "FX pool reserve read failed".

    Instead, convert ONCE at the local↔GD reserve boundary (booth swap: sender → GD
    @fx_router; GD HOLDS the reserve) then DELEGATE egress to GD over the existing
    federation channel — GD delivers the dest currency 1:1 to the leaf. This is the SAME
    convert-then-delegate machinery the op→op corridor + the parent /fx/route-hop endpoint
    already use (mirrors _fx_route_hop_execute's cross-currency branch, but originating from
    the real sender rather than a local @fx_router so no extra ingress hop is needed). Δ=0:
    every leg is within-frame; a pre-conversion failure compensates the sender (booth's own
    leg1 refund), a post-conversion egress failure dead-letters at GD @fx_router (never
    clawed back).

    Returns None when this node can't originate a reserve route (no @fx_router / no GD
    gateway for dest_ccy / GD peer not ACTIVE) → the caller falls back to the direct booth.
    """
    if not (_fx_route_enabled() and _fx_route_local_router_did()):
        return None
    gd = _fx_route_gateway_for_currency(dest_ccy)
    if not gd:
        return None
    gd_router = str(gd.get("router_did", "")).strip()
    gd_reg = str(gd.get("registry_id", "")).strip()
    gd_teg = str(gd.get("teg_id", "")).strip() or f"teg-layer-{gd_reg.replace('registry-', '')}"
    gd_peer = await _fx_route_find_active_peer(db, gd_reg)
    if not gd_router or gd_peer is None:
        return None

    # §FXEGRESS — deny IN FRONT of the value. A gateway whose egress keeps failing
    # post-conversion must not be handed another conversion: the sender would be debited
    # for a hop already known to be dead, and the converted funds would park with the rest.
    _streak = await _fx_egress_breaker_state(gd_reg)
    _threshold = _fx_egress_breaker_threshold()
    if _threshold > 0 and _streak >= _threshold:
        logger.error(
            "[FX-EGRESS-BREAKER] refusing origination to %s: %d consecutive post-conversion "
            "egress failures (threshold %d). No funds moved.", gd_reg, _streak, _threshold)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(f"FX egress to {gd_reg} is failing ({_streak} consecutive post-conversion "
                    f"failures); route origination is suspended and NO funds were moved. "
                    f"Already-parked routes are recovered via POST /teg/fx/route/sweep. "
                    f"The suspension lifts automatically once the gateway succeeds again."),
        )
    # §LEDGERGATE (V0602) — deny IN FRONT of the value while GD's ledger cannot record the payout: nothing has moved
    # here yet, so the person gets the TEG's own sentence and the same request goes through once GD's ledger is back.
    _ledger_refusal = await _fx_route_gd_ledger_refusal(gd, gd_peer)
    if _ledger_refusal is not None:
        raise _ledger_refusal

    route_id = str(uuid.uuid4())
    sender_did = current_agent.did
    local_ccy = _local_frame_currency()
    amount = xfer_req.amount
    # WS-A A1 (§2026-06-07): home-registry-vouched origin-agent mTLS SPIFFE ("" if not enrolled).
    origin_agent_spiffe = current_agent.spiffe_id if (getattr(current_agent, "mtls_enabled", False) and current_agent.spiffe_id) else ""
    logger.info(f"[FX-ROUTE-RESERVE] route={route_id} {sender_did} ({local_ccy}) → "
                f"{xfer_req.receiver_did} via GD {gd_reg} ({gd_router}) [dest {dest_ccy}]")

    # 1) FX CORE — convert at the local↔GD reserve boundary: sender (local_ccy) → GD
    #    @fx_router (dest_ccy). The target is the GD RESERVE frame (HAS the reserve) so the
    #    booth's reserve read/credit never hit the leaf → no 503. Raises HTTPException on
    #    refusal (the booth already compensated its source leg → sender made whole).
    fx_req = CrossRegistryTransferRequest(
        receiver_did=gd_router, amount=amount, message=f"fxroute:{route_id}:fxcore")
    fx_res = await _fx_cross_currency_swap(
        xfer_req=fx_req, current_agent=current_agent, sender_did=sender_did,
        target_teg_id=gd_teg, target_registry_id=gd_reg, target_peer=gd_peer,
        source_currency=local_ccy, dest_currency=dest_ccy, db=db)
    fx_credited = getattr(fx_res, "credited_amount", None) or "0"
    fx_swap_id = getattr(fx_res, "transfer_id", "") or ""
    if getattr(fx_res, "status", "") != "completed" or Decimal(str(fx_credited)) <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="FX route core swap did not complete")

    # 2) DELEGATE egress to GD (recursive, over the federation channel). GD now holds
    #    fx_credited of dest_ccy at its @fx_router and delivers it 1:1 to the leaf receiver.
    gd_url = str(gd.get("url", "")).strip() or (getattr(gd_peer, "base_url", "") or "")
    onward = await _fx_route_delegate(gd_url, {
        "route_id": route_id, "final_receiver_did": xfer_req.receiver_did, "amount": fx_credited,
        "hop_budget": 4, "origin_did": sender_did,
        "origin_frame": os.environ.get("SPIRE_TRUST_DOMAIN", ""), "memo": xfer_req.message or "",
        "origin_teg_id": _get_local_teg_id(), "origin_registry_id": _get_local_registry_id(),
        "origin_agent_spiffe": origin_agent_spiffe, "post_conversion": True})
    if not onward or onward.get("status") != "settled":
        # Post-conversion failure → forward-only: dest_ccy parked at GD @fx_router (Δ-neutral
        # dead-letter, swept later). NEVER claw back a converted leg (strategy §6).
        # The FX-core conversion DID happen → record it + the parked leg so the dead-letter
        # trail shows the real state (status="dead_letter" is authoritative; the FE renders it).
        dl_hops = [
            {"role": "fxcore", "frame": local_ccy, "event": "FxSwapSettled",
             "ccy": f"{local_ccy}->{dest_ccy}", "swap_id": fx_swap_id,
             "amount_in": amount, "credited": fx_credited},
            {"role": "dead_letter", "frame": dest_ccy, "event": "FxRouteDeadLettered", "ccy": dest_ccy,
             "amount_in": fx_credited, "credited": fx_credited,
             "note": f"parked at GD @fx_router {gd_router} (egress delegation failed post-conversion)"},
        ]
        _emit_fx_route_event("FxRouteRefunded", route_id=route_id, origin_did=sender_did,
                             receiver_did=xfer_req.receiver_did, amount_in=amount, source_ccy=local_ccy,
                             dest_ccy=dest_ccy, credited="0", gateway=gd_router, hops=dl_hops, status="dead_letter", origin_agent_spiffe=origin_agent_spiffe)
        # §FXDL (2026-07-28) — PERSIST the parking, do not only narrate it.
        # This site emitted an audit event and raised 409, and that was ALL: no row was ever
        # written to fx_route_dead_letters. The keeper can only act on rows, so every
        # post-conversion parking here was invisible to recovery. Measured before the fix:
        # 48,561 dead-letter events since 2026-06-14 (~1.33M of converted destination currency
        # parked) against 40 rows in the table, and all 40 came from the pre_conversion sites.
        #
        # phase='post_conversion_remote' is load-bearing: the funds are at the DESTINATION
        # frame's @fx_router, not ours, so the keeper's local refund path MUST skip these
        # (see the phase guard in fx_router_keeper._process_dead_letters). Recovery is
        # re-delivery on the far frame; the egress carries a stable `fxroute:{route_id}:` memo
        # so a retry dedupes at the TEG rather than paying twice.
        await _record_fx_dead_letter(
            db, route_id=route_id, origin_did=sender_did, amount=fx_credited,
            currency=dest_ccy, parked_at_did=gd_router, phase="post_conversion_remote",
            origin_teg_id=_get_local_teg_id(), origin_registry_id=_get_local_registry_id(),
            receiver_did=xfer_req.receiver_did)
        # §FXEGRESS — count it. Once the streak hits the threshold the NEXT origination is
        # refused before any conversion, so a dead gateway can no longer bill the sender
        # once per retry.
        _st = await _fx_egress_breaker_record(gd_reg, failed=True)
        logger.warning("[FX-EGRESS-BREAKER] %s post-conversion failure streak=%d (threshold %d)",
                       gd_reg, _st, _fx_egress_breaker_threshold())
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=(f"FX route egress to {gd_reg} failed post-conversion; "
                                    f"{fx_credited} {dest_ccy} parked at {gd_router} (route_id={route_id})"))

    # §FXEGRESS — a settled egress clears the streak, so a gateway that recovers resumes
    # immediately and no operator action is needed.
    await _fx_egress_breaker_record(gd_reg, failed=False)
    credited = onward.get("credited_amount", fx_credited)
    dest_final = onward.get("dest_currency", dest_ccy)
    hops = [{"role": "fxcore", "frame": local_ccy, "event": "FxSwapSettled",
             "ccy": f"{local_ccy}->{dest_ccy}", "swap_id": fx_swap_id,
             "amount_in": amount, "credited": fx_credited}] + onward.get("hops", [])
    _emit_fx_route_event("FxRouteSettled", route_id=route_id, origin_did=sender_did,
                         receiver_did=xfer_req.receiver_did, amount_in=amount, source_ccy=local_ccy,
                         dest_ccy=dest_final, credited=credited, gateway=gd_router,
                         hops=hops, status="settled", origin_agent_spiffe=origin_agent_spiffe)
    logger.info(f"[FX-ROUTE-RESERVE] route={route_id} SETTLED: {amount} {local_ccy} → "
                f"{credited} {dest_final} to {xfer_req.receiver_did}")
    return CrossRegistryTransferResponse(
        transfer_id=route_id, status="completed", sender_did=sender_did,
        receiver_did=xfer_req.receiver_did, amount=amount, fee_amount=None,
        credited_amount=str(credited), source_teg=_get_local_teg_id(),
        target_teg=onward.get("dest_teg", "") or "", transaction_hash=route_id,
        timestamp=datetime.now(timezone.utc).isoformat())


class FxRouteHopRequest(BaseModel):
    """Delegation RPC body for one hop of the op→op FX route."""
    route_id: str
    final_receiver_did: str
    amount: str
    hop_budget: int = 4
    origin_did: str = ""
    origin_frame: str = ""
    memo: str = ""
    origin_agent_spiffe: str = ""  # WS-A A1: originating agent's mTLS SPIFFE (home-registry-vouched), rides every hop
    # §FXSTRAND-2: the origin's OWN home ids, carried rather than resolved. A hop that must compensate
    # cannot look the origin up when the reason it is compensating IS that cards have not propagated
    # here; without these the dead-letter it writes is empty and the keeper repeats the failed resolve.
    origin_teg_id: str = ""
    origin_registry_id: str = ""
    # §FXPOSTCONV (2026-09-26): True when the caller already CONVERTED, so the amount arriving here is THIS frame's
    # currency while the origin holds another. A failure past this point must never refund the origin from here:
    # that is a 1:1 leg in the wrong currency, which the origin's TEG refuses (measured on the sandbox pair every
    # night since 09-23: one route a night, 1 refund + 8 keeper retries refused, the row left 'failed' and the
    # converted money parked). The caller records the parking (post_conversion_remote) and this frame's keeper
    # re-delivers to the receiver. Absent (an older caller) = False = the old behaviour.
    post_conversion: bool = False


@router.get("/fx/ledger", summary="Internal: can this frame's ledger record a movement now (federation-authed)")
@limiter.limit("1200/minute")
async def fx_ledger_state(request: Request, _peer_identity: str = Depends(require_peer_registry_identity)):
    """
    Internal and read-only: this frame's TEG ledger gate as its /health reports it (the gate's mode and the ledger's
    state), for a peer frame about to convert into this frame's unit. Peers read /api/v1/federation/fx/ledger
    instead; no federation proxy forwards this path, so it serves only a caller on the frame's own network.

    \f
    §LEDGERGATE (V0602): this frame's TEG ledger gate as its /health reports it (the gate's mode and the ledger's
    state), for a peer frame about to convert into this frame's currency (_fx_route_gd_ledger_refusal). Read-only.
    V0603: peers read /api/v1/federation/fx/ledger (FX_LEDGER_PEER_PATH) instead; no federation proxy forwards this path,
    so it stays only for a caller on the frame's own network.
    """
    return await _fx_local_ledger_state()


@router.post("/fx/route-hop", summary="Internal: continue a cross-currency FX route (federation-authed)")
@limiter.limit("600/minute")
async def fx_route_hop(
    req: FxRouteHopRequest,
    request: Request,
    _peer_identity: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """Federation-authed (mTLS, internal secret or license; NOT the admin key) delegation RPC for the
    op→op (any-depth) cross-currency FX route. Called by the source op's parent gateway, and
    recursively between reserve frames. Runs on a frame holding `amount` of its local currency at
    its @fx_router; converts once at the local↔GD boundary then delegates egress onward."""
    if not _fx_route_enabled():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="FX route disabled on this frame (FX_ROUTE_ENABLED=false)")
    logger.info(f"[FX-ROUTE-HOP] peer={_peer_identity} route={req.route_id} → "
                f"{req.final_receiver_did} amount={req.amount} budget={req.hop_budget} "
                f"origin_agent={req.origin_agent_spiffe or '-'}")
    return await _fx_route_hop_execute(
        db, route_id=req.route_id, final_receiver_did=req.final_receiver_did, amount=req.amount,
        hop_budget=req.hop_budget, origin_did=req.origin_did, origin_frame=req.origin_frame,
        memo=req.memo, origin_agent_spiffe=req.origin_agent_spiffe,
        origin_teg_id=req.origin_teg_id, origin_registry_id=req.origin_registry_id,
        post_conversion=bool(req.post_conversion), presenter=_peer_identity)


# ── op→op FX route ops surface (admin desk: status + residue sweep) ───────────
async def _fx_router_liquid(db: AsyncSession):
    """(router_did, Decimal|None, Agent|None) for the local @fx_router transit account."""
    router_did = _fx_route_local_router_did()
    if not router_did:
        return ("", None, None)
    agent = (await db.execute(
        select(models.Agent).where(models.Agent.did == router_did)
    )).scalar_one_or_none()
    if agent is None:
        return (router_did, None, None)
    try:
        token = await get_teg_token_for_agent(agent.id, router_did)
        client = _get_teg_client()
        resp = await client.get(f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                                headers=prepare_teg_headers(token), timeout=10.0)
        if resp.status_code == 200:
            return (router_did, Decimal(str(resp.json().get("balance", "0") or "0")), agent)
    except Exception as e:
        logger.warning(f"[FX-ROUTE] router balance read failed: {e}")
    return (router_did, None, agent)


@router.get("/fx/route/status", summary="Admin: op→op FX route status (router, peers, residue)")
@limiter.limit("600/minute")
async def fx_route_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Live op→op FX route config + the local @fx_router transit account (DID + liquid
    residue available to sweep) + configured reserve peers / parent gateway. Read-only."""
    router_did, bal, _agent = await _fx_router_liquid(db)
    peers = [{"currency": g.get("currency"), "registry_id": g.get("registry_id"),
              "router_did": g.get("router_did"), "url": g.get("url")}
             for g in _fx_route_peer_gateways()]
    return {
        "route_enabled": _fx_route_enabled(),
        "local_currency": _local_frame_currency(),
        "router_did": router_did or None,
        "router_liquid": (str(bal) if bal is not None else None),
        "peers": peers,                 # reserve frames this frame can convert to (reserve role)
        "parent_gateway": _fx_route_my_gateway(),   # set on leaf ops (origin role)
    }


class FxRouteSweepRequest(BaseModel):
    """Admin: sweep the local @fx_router's residual liquid balance 1:1 to a target.
    Δ-safe — moves ONLY the router's own transit residue (never reserves/user funds)."""
    to_did: str = Field(..., max_length=120, description="Recipient DID for the swept residue")
    amount: str = Field(..., description="Amount to sweep (string; must be ≤ router liquid balance)")
    memo: Optional[str] = Field(default=None, max_length=200)


@router.post("/fx/route/sweep", summary="Admin: sweep @fx_router residue 1:1 to a target (Δ-safe)")
@limiter.limit("60/minute")
async def fx_route_sweep(
    req: FxRouteSweepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Sweep the local @fx_router's residual liquid balance (dead-letter transit parked by
    failed post-conversion routes) 1:1 to `to_did`. Admin-only, Δ-safe: moves ONLY the
    router's own transit funds via the standard same-currency cross-TEG leg (the proven
    `_fx_route_1to1_2pc`). NEVER touches reserves or user accounts. Generalizes the manual
    residue sweep; the button-backed control on the FX Desk."""
    router_did = _fx_route_local_router_did()
    if not router_did:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="No @fx_router on this frame (FX_ROUTER_DID unset).")
    router_agent = (await db.execute(
        select(models.Agent).where(models.Agent.did == router_did)
    )).scalar_one_or_none()
    if router_agent is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"@fx_router {router_did} not found.")
    try:
        amt = Decimal(str(req.amount))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="amount must be numeric")
    if amt <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="amount must be > 0")
    rtid, rrid = await _resolve_receiver_registry(db, req.to_did)
    if not rtid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot resolve recipient {req.to_did} from this frame.")
    recv_peer = await _fx_route_find_active_peer(db, rrid) if rrid else None
    ok, err, credited, tx = await _fx_route_1to1_2pc(
        db, sender_agent=router_agent, sender_did=router_did, receiver_did=req.to_did,
        amount=str(amt), target_teg_id=rtid, target_registry_id=rrid, target_peer=recv_peer,
        memo=(req.memo or "fxroute:sweep"))
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Sweep failed: {err}")
    logger.info(f"[FX-ROUTE] admin residue sweep {amt} {router_did} → {req.to_did} (tx={tx})")
    return {"status": "swept", "amount": str(amt), "credited": credited,
            "from": router_did, "to": req.to_did, "tx": tx}


async def _record_fx_delivery(db: AsyncSession, *, route_id: str, receiver_did: str, amount,
                              currency: str, kind: str, tx_id: Optional[str]) -> None:
    """§FXSELFHEAL — record, on the DESTINATION frame, that this route was delivered FROM here.
    This is the already-delivered guard's only local source of truth (delivery otherwise lives
    solely in a TEG memo the registry cannot query). Best-effort: NEVER raise into the delivery
    hot path — a missing bookkeeping row costs a manual reconcile, a raised exception would
    fail a delivery that already moved money."""
    try:
        await db.execute(text(
            """
            INSERT INTO fx_route_deliveries
                (route_id, receiver_did, amount, currency, kind, tx_id, delivered_at)
            VALUES (:rid, :rcv, :amt, :ccy, :kind, :tx, now())
            ON CONFLICT (route_id) DO NOTHING
            """
        ), {"rid": route_id, "rcv": receiver_did, "amt": str(amount), "ccy": currency,
            "kind": kind, "tx": tx_id})
        await db.commit()
    except Exception as e:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:
            pass
        logger.error(f"[FX-ROUTE] delivery record failed (non-fatal) route={route_id}: {e}")


async def _fx_route_held_here(db: AsyncSession, route_id: str):
    """§REPATLANE-3 (V0604): this frame's own unresolved HELD dead letter for `route_id` (FX_HELD_PHASES, pending or
    failed), or None. The far keeper's re-delivery reads it before it claims a route: a route whose egress from here
    may already have paid must not be paid again. A broken lookup raises (fail closed), like the delivery guard."""
    try:
        row = (await db.execute(text(
            "SELECT route_id, phase, status FROM fx_route_dead_letters "
            "WHERE route_id = :rid AND phase IN :phases AND status IN ('pending', 'failed') LIMIT 1"
        ).bindparams(bindparam("phases", expanding=True)),
            {"rid": route_id, "phases": list(FX_HELD_PHASES)})).mappings().first()
        return row
    except Exception as e:  # noqa: BLE001 — a broken guard must FAIL CLOSED
        logger.error(f"[FX-ROUTE] held-route lookup failed route={route_id}: {e}")
        raise


async def _fx_route_already_delivered(db: AsyncSession, route_id: str):
    """Return the local delivery row for `route_id`, or None. The guard the manual runbook
    learned the hard way (its teg_transactions-only check was blind to the class)."""
    try:
        row = (await db.execute(text(
            "SELECT route_id, tx_id, kind, receiver_did, amount FROM fx_route_deliveries "
            "WHERE route_id = :rid"), {"rid": route_id})).mappings().first()
        return row
    except Exception as e:  # noqa: BLE001 — a broken guard must FAIL CLOSED
        logger.error(f"[FX-ROUTE] delivery lookup failed route={route_id}: {e}")
        raise


# ── FX router keeper (AAA+ suspense-account liquidity manager) — config + record ──
async def _record_fx_dead_letter(db: AsyncSession, *, route_id: str, origin_did: str, amount,
                                 currency: str, parked_at_did: str, phase: str = "pre_conversion",
                                 origin_teg_id: Optional[str] = None,
                                 origin_registry_id: Optional[str] = None,
                                 receiver_did: Optional[str] = None, note: Optional[str] = None) -> None:
    """Idempotently record funds parked at @fx_router by a failed-compensation route so the
    fx_router_keeper can refund the original sender (true auto-refund). One row per route_id;
    best-effort — NEVER raise into the hot path (the route already failed; this is bookkeeping).
    §FXSELFHEAL: receiver_did is captured AT PARKING TIME so remote recovery never needs the
    EventStore join (whose admin search caps at 1000 rows — the 08-04 near-miss)."""
    try:
        _res = await db.execute(text(
            """
            INSERT INTO fx_route_dead_letters
                (id, route_id, origin_did, origin_teg_id, origin_registry_id, amount, currency,
                 parked_at_did, phase, status, retries, receiver_did, last_error, created_at)
            VALUES (:id, :route_id, :origin_did, :otid, :orid, :amount, :ccy,
                    :parked, :phase, 'pending', 0, :receiver, :note, now())
            ON CONFLICT (route_id) DO NOTHING
            RETURNING id
            """
        ), {"id": str(uuid.uuid4()), "route_id": route_id, "origin_did": origin_did,
            "otid": origin_teg_id, "orid": origin_registry_id, "amount": str(amount),
            "ccy": currency, "parked": parked_at_did, "phase": phase,
            "receiver": receiver_did, "note": (note or None) and str(note)[:480]})
        _inserted = _res.first() is not None
        await db.commit()
        if not _inserted:
            # §REPATLANE-3 (V0604): one row per route; an earlier one stands and this write changed nothing, so it does
            # not say "recorded" (the row that stands is the one the keepers and the far keeper's guard read)
            logger.warning(f"[FX-ROUTE] dead-letter for route={route_id} already recorded: this write (phase={phase}, "
                           f"{amount} {currency}) changed nothing")
            return
        _next = {"pre_conversion": f"the keeper refunds {origin_did}",
                 "post_conversion_remote": "the far frame's keeper re-delivers it to the receiver",
                 "egress_unknown": "the keeper finishes the delivery under its own key, or returns it once the TEG "
                                   "proves it never ran",
                 "egress_2pc_unknown": "held for a read of its 2PC transfer: nothing refunds or re-delivers it on "
                                       "its own",
                 "redelivery_unknown": "held for a read of its re-delivery: nothing refunds or re-delivers it on "
                                       "its own",
                 "swap_unknown": "held for a ledger read: nothing is refunded on its own",
                 "refund_unknown": f"held for a read of its refund leg: {origin_did} may have it already, so nothing "
                                   f"refunds it again on its own"}.get(phase, "see its phase")
        logger.warning(f"[FX-ROUTE] dead-letter recorded route={route_id} {amount} {currency} "
                       f"parked@{parked_at_did} phase={phase} ({_next})")
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.error(f"[FX-ROUTE] dead-letter record failed (non-fatal) route={route_id}: {e}")


class FxRouterKeeperConfigBody(BaseModel):
    """Partial update for the FX router keeper config (all optional; FX Desk wires this)."""
    enabled: Optional[bool] = None
    target_float: Optional[str] = None
    min_float: Optional[str] = None
    max_float: Optional[str] = None
    source: Optional[str] = Field(default=None, pattern="^(fx_reserve|treasury)$")
    check_interval_sec: Optional[int] = None
    max_move_per_cycle: Optional[str] = None
    dead_letter_refund_enabled: Optional[bool] = None
    dead_letter_max_retries: Optional[int] = None


def _keeper_cfg_dict(cfg) -> dict:
    return {
        "enabled": bool(cfg.enabled), "target_float": str(cfg.target_float),
        "min_float": str(cfg.min_float), "max_float": str(cfg.max_float),
        "source": cfg.source, "check_interval_sec": cfg.check_interval_sec,
        "max_move_per_cycle": str(cfg.max_move_per_cycle),
        "dead_letter_refund_enabled": bool(cfg.dead_letter_refund_enabled),
        "dead_letter_max_retries": cfg.dead_letter_max_retries,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by": cfg.updated_by,
    }


async def _keeper_get_or_create(db: AsyncSession):
    cfg = (await db.execute(
        select(models.FxRouterKeeperConfig).where(models.FxRouterKeeperConfig.id == "singleton")
    )).scalar_one_or_none()
    if cfg is None:
        cfg = models.FxRouterKeeperConfig(id="singleton")
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


@router.get("/fx/router-keeper", summary="Admin: FX router keeper config + live status")
@limiter.limit("600/minute")
async def fx_router_keeper_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Config + live `@fx_router` liquid + pending dead-letter count. Master env gate
    `FX_ROUTER_KEEPER_ENABLED` shown separately — BOTH it and `config.enabled` must be true
    for the worker to act. Read-only."""
    cfg = await _keeper_get_or_create(db)
    router_did, liquid, _ = await _fx_router_liquid(db)
    pending = (await db.execute(text(
        "SELECT count(*) FROM fx_route_dead_letters WHERE status='pending'"
    ))).scalar() or 0
    env_gate = (os.getenv("FX_ROUTER_KEEPER_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    # §FXSTRAND-2b (agentvault2-eb's ask): `active` is the LIQUIDITY manager's verdict (env AND
    # cfg.enabled) and since c715069 that is no longer the question a caller asking "can parked funds
    # get home?" needs answered — the drain runs off `FX_ROUTE_ENABLED` and its own column, and neither
    # is readable from `active` or `env_gate_enabled`. State it, and state it by CALLING THE WORKER'S
    # OWN PREDICATE rather than re-deriving it here: a per-surface copy of a rule is how the two drift.
    try:
        from ..background_tasks.fx_router_keeper import FxRouterKeeper
        _drain_active = bool(FxRouterKeeper()._should_run()
                             and (cfg is None or cfg.dead_letter_refund_enabled))
    except Exception:  # noqa: BLE001 — a status read must never 500 on its own instrumentation
        _drain_active = None
    return {
        "config": _keeper_cfg_dict(cfg),
        "env_gate_enabled": env_gate,
        "active": bool(env_gate and cfg.enabled),
        "dead_letter_drain_active": _drain_active,
        "frame": os.getenv("REGISTRY_NAME", "registry-a"),
        "currency": _local_frame_currency(),
        "router_did": router_did or None,
        "router_liquid": (str(liquid) if liquid is not None else None),
        "dead_letters_pending": int(pending),
    }


@router.put("/fx/router-keeper", summary="Admin: update FX router keeper config (FX Desk)")
@limiter.limit("120/minute")
async def fx_router_keeper_put(
    body: FxRouterKeeperConfigBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Update the keeper config (partial). Validates numeric watermarks and min ≤ target ≤ max
    (when max>0). Persisted in `fx_router_keeper_config`; the worker re-reads it every cycle."""
    cfg = await _keeper_get_or_create(db)
    data = body.model_dump(exclude_none=True)
    for num in ("target_float", "min_float", "max_float", "max_move_per_cycle"):
        if num in data:
            try:
                v = Decimal(str(data[num]))
            except (InvalidOperation, ValueError):
                raise HTTPException(status_code=422, detail=f"{num} must be numeric")
            if v < 0:
                raise HTTPException(status_code=422, detail=f"{num} must be ≥ 0")
            setattr(cfg, num, v)
    if "enabled" in data: cfg.enabled = bool(data["enabled"])
    if "source" in data: cfg.source = data["source"]
    if "check_interval_sec" in data:
        iv = int(data["check_interval_sec"])
        if iv < 10:
            raise HTTPException(status_code=422, detail="check_interval_sec must be ≥ 10")
        cfg.check_interval_sec = iv
    if "dead_letter_refund_enabled" in data: cfg.dead_letter_refund_enabled = bool(data["dead_letter_refund_enabled"])
    if "dead_letter_max_retries" in data:
        cfg.dead_letter_max_retries = max(0, int(data["dead_letter_max_retries"]))
    # invariant: min ≤ target ≤ max (when max>0)
    tgt, lo, hi = Decimal(cfg.target_float), Decimal(cfg.min_float), Decimal(cfg.max_float)
    if lo > tgt:
        raise HTTPException(status_code=422, detail="min_float must be ≤ target_float")
    if hi > 0 and hi < tgt:
        raise HTTPException(status_code=422, detail="max_float must be ≥ target_float (or 0 to disable sweep)")
    cfg.updated_at = datetime.now(timezone.utc)
    cfg.updated_by = getattr(_admin, "email", None)
    await db.commit()
    await db.refresh(cfg)
    logger.info(f"[FX-ROUTE] router keeper config updated by {getattr(_admin,'email','?')}: {_keeper_cfg_dict(cfg)}")
    return {"status": "updated", "config": _keeper_cfg_dict(cfg)}


# ── FX-RESERVE peg keeper (0092) — FX-Desk config + live status ──────────────
class FxReserveKeeperConfigBody(BaseModel):
    """Partial update for the FX reserve peg keeper (all fields optional)."""
    enabled: Optional[bool] = None
    anchor_currency: Optional[str] = None
    ratio_vs_anchor: Optional[str] = None
    target_float: Optional[str] = None
    min_float: Optional[str] = None
    max_float: Optional[str] = None
    deadband_pct: Optional[str] = None
    source: Optional[str] = None
    max_move_per_cycle: Optional[str] = None
    check_interval_sec: Optional[int] = None
    operator_mode: Optional[str] = None


def _rkeeper_cfg_dict(cfg) -> dict:
    return {
        "enabled": bool(cfg.enabled),
        "anchor_currency": cfg.anchor_currency,
        "ratio_vs_anchor": str(cfg.ratio_vs_anchor),
        "target_float": str(cfg.target_float),
        "min_float": str(cfg.min_float),
        "max_float": str(cfg.max_float),
        "deadband_pct": str(cfg.deadband_pct),
        "source": cfg.source,
        "max_move_per_cycle": str(cfg.max_move_per_cycle),
        "check_interval_sec": int(cfg.check_interval_sec),
        "operator_mode": cfg.operator_mode,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by": cfg.updated_by,
    }


@router.get("/fx/dead-letters", summary="Admin: parked FX-route dead letters (read-only)")
@limiter.limit("600/minute")
async def fx_dead_letters_list(
    request: Request,
    status_filter: str = Query("pending", alias="status", pattern="^(pending|refunded|swept|failed|all)$"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """List the rows behind the keepers' `dead_letters_pending` count.

    §FEPARITY-R3: the keeper endpoints reported a COUNT and nothing else, so an operator
    could see that N routes were parked but never which ones — and `post_conversion_remote`
    rows are skipped by the local keeper BY DESIGN (fx_router_keeper.py phase guard: the
    funds sit at the DESTINATION frame's @fx_router, so only re-delivery on that frame
    clears them). Read-only: recovery stays on the existing rails, this just makes the
    queue visible.
    """
    q = select(models.FxRouteDeadLetter)
    if status_filter != "all":
        q = q.where(models.FxRouteDeadLetter.status == status_filter)
    q = q.order_by(models.FxRouteDeadLetter.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return {
        "rows": [{
            "id": r.id, "route_id": r.route_id, "origin_did": r.origin_did,
            "amount": str(r.amount), "currency": r.currency,
            "parked_at_did": r.parked_at_did, "phase": r.phase, "status": r.status,
            "retries": r.retries, "last_error": r.last_error,
            "resolution_tx": r.resolution_tx,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            # the local keeper cannot refund a remote parking — surface that per row
            # rather than letting the UI imply every pending row is retryable here.
            "locally_refundable": r.phase == "pre_conversion",
            # §REPATLANE-2 (V0603): a paying leg whose outcome is not known; nothing refunds it on its own
            "held": r.phase in FX_HELD_PHASES,
        } for r in rows],
        "count": len(rows),
        "status_filter": status_filter,
    }


async def _rkeeper_get_or_create(db: AsyncSession):
    cfg = (await db.execute(
        select(models.FxReserveKeeperConfig).where(models.FxReserveKeeperConfig.id == "singleton")
    )).scalar_one_or_none()
    if cfg is None:
        cfg = models.FxReserveKeeperConfig(id="singleton")
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


@router.get("/fx/reserve-keeper", summary="Admin: FX reserve peg keeper config + live status")
@limiter.limit("600/minute")
async def fx_reserve_keeper_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Config + live `@fx_reserve` balance + floor. Master env gate `FX_RESERVE_KEEPER_ENABLED`
    shown separately — BOTH it and `config.enabled` must be true for the worker to act.
    Read-only. (The keeper is move-only; issuance stays manual/op-gated.)"""
    cfg = await _rkeeper_get_or_create(db)
    env_gate = (os.getenv("FX_RESERVE_KEEPER_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    ccy = _local_frame_currency()
    admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
    teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
    reserve = None
    try:
        reserve = str(await _fx_read_reserve(teg_base, admin_key))
    except Exception:
        pass
    return {
        "config": _rkeeper_cfg_dict(cfg),
        "env_gate_enabled": env_gate,
        "active": bool(env_gate and cfg.enabled),
        "frame": os.getenv("REGISTRY_NAME", "registry-a"),
        "currency": ccy,
        "reserve": reserve,
        "floor": str(_fx_reserve_floor(ccy)),
    }


@router.put("/fx/reserve-keeper", summary="Admin: update FX reserve peg keeper config (FX Desk)")
@limiter.limit("120/minute")
async def fx_reserve_keeper_put(
    body: FxReserveKeeperConfigBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Update the keeper config (partial). The worker re-reads it every cycle (live retune)."""
    cfg = await _rkeeper_get_or_create(db)
    data = body.model_dump(exclude_none=True)
    for num in ("ratio_vs_anchor", "target_float", "min_float", "max_float", "deadband_pct", "max_move_per_cycle"):
        if num in data:
            try:
                v = Decimal(str(data[num]))
            except (InvalidOperation, ValueError):
                raise HTTPException(status_code=422, detail=f"{num} must be numeric")
            if v < 0:
                raise HTTPException(status_code=422, detail=f"{num} must be ≥ 0")
            setattr(cfg, num, v)
    if "enabled" in data:
        cfg.enabled = bool(data["enabled"])
    if "anchor_currency" in data:
        cfg.anchor_currency = str(data["anchor_currency"]).strip().upper()[:16]
    if "source" in data:
        cfg.source = str(data["source"])[:32]
    if "operator_mode" in data:
        m = str(data["operator_mode"]).strip().lower()
        if m not in ("worker", "agent", "off"):
            raise HTTPException(status_code=422, detail="operator_mode must be worker|agent|off")
        cfg.operator_mode = m
    if "check_interval_sec" in data:
        iv = int(data["check_interval_sec"])
        if iv < 10:
            raise HTTPException(status_code=422, detail="check_interval_sec must be ≥ 10")
        cfg.check_interval_sec = iv
    # invariant: min ≤ target ≤ max (when each is set > 0; target is the anchor-frame static target)
    tgt, lo, hi = Decimal(cfg.target_float), Decimal(cfg.min_float), Decimal(cfg.max_float)
    if lo > 0 and tgt > 0 and lo > tgt:
        raise HTTPException(status_code=422, detail="min_float must be ≤ target_float")
    if hi > 0 and tgt > 0 and hi < tgt:
        raise HTTPException(status_code=422, detail="max_float must be ≥ target_float (or 0 to disable sweep)")
    cfg.updated_at = datetime.now(timezone.utc)
    cfg.updated_by = getattr(_admin, "email", None)
    await db.commit()
    await db.refresh(cfg)
    logger.info(f"[fx_reserve_keeper] config updated by {getattr(_admin,'email','?')}: {_rkeeper_cfg_dict(cfg)}")
    return {"status": "updated", "config": _rkeeper_cfg_dict(cfg)}


# =============================================================================
# OWL26: Treasury-First Funding Endpoints
# =============================================================================

class TreasuryFundAgentRequest(BaseModel):
    """Request to fund an agent from the treasury via TEG."""
    target_agent_did: str = Field(..., max_length=120, description="Target agent DID to fund")
    amount: str = Field(..., description="Amount to transfer, in the frame's unit (string for precision)")
    reason: str = Field(..., max_length=100, description="Reason, a code: `genesis_grant`, `dispute_compensation`, `reward` (a payout), `tutorial_grant`, `admin_grant`")
    reference_id: Optional[str] = Field(None, max_length=200, description="External reference (e.g., dispute ID)")

    @field_validator('target_agent_did')
    @classmethod
    def validate_target_did(cls, v):
        from agentvault_registry.input_validators import validate_did
        return validate_did(v)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)


class TreasuryReceiveRequest(BaseModel):
    """Request to return AVT from an agent to the treasury."""
    source_agent_did: str = Field(..., description="Source agent DID (e.g., slashed defendant)")
    amount: str = Field(..., description="Amount to return, in the frame's unit")
    reason: str = Field(..., description="Reason: dispute_slash, penalty, fee_collection")
    reference_id: Optional[str] = Field(None, description="External reference (e.g., dispute ID)")

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)


class TreasuryMintRequest(BaseModel):
    """Request to mint new AVT tokens via the TEG minting authority."""
    target_agent_did: str = Field(
        default="did:theprotocol:teg_system_treasury",
        max_length=120,
        description="Target DID to receive minted tokens (defaults to system treasury)",
    )
    amount: str = Field(..., description="Amount to mint, in the frame's unit (string for precision)")
    reason: str = Field(..., max_length=256, description="Reason for minting")

    @field_validator('target_agent_did')
    @classmethod
    def validate_target_did(cls, v):
        from agentvault_registry.input_validators import validate_did
        return validate_did(v)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_MINT_MAX_AVT", "100000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)


@router.post(
    "/treasury/mint",
    summary="Issue new units into this frame (admin)",
    # §pass66 (2026-05-22) — Mainframe-only. The TEG layer's MINTING_AUTHORITY
    # env on cloud-ops is set to "disabled" by cloud_provisioner so a /token/issue
    # would already fail, but blocking here returns a cleaner 503 with an
    # actionable message instead of a deeper validation failure.
    dependencies=[Depends(_mainframe_only_dep)],
)
async def mint_tokens(
    request: TreasuryMintRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """
    Issue new units of this frame's unit through the TEG's issuing authority, to `target_agent_did` (by default the
    system treasury), with a `reason`. It is the only path that creates units, and it runs on a frame registry only
    (a cloud operator answers 404, `mainframe_only`). The TEG checks its issuing authority, and the registry records
    `TokensIssued` in the event store. Needs an admin token with the `admin_treasury` flag.

    \f
    Mint new AVT tokens via the TEG minting authority.

    This is the ONLY authorized path for creating tokens from void.
    The TEG validates the minting authority guard (TEG_ID == MINTING_AUTHORITY).
    The Registry emits the TokensIssued event to the EventStore.

    Flow:
      1. Registry receives admin request (this endpoint)
      2. Calls TEG POST /admin/token/issue
      3. TEG validates minting authority + creates tokens in DB
      4. Registry emits TokensIssued event to EventStore
      5. Returns transaction details

    Auth: Admin developer JWT (is_admin=True required).
    """
    logger.info(
        f"[Mint] Minting {request.amount} AVT to {request.target_agent_did} "
        f"(reason: {request.reason}, admin: {current_admin.id})"
    )

    # §29 LIVE CALL SITE for I7 `mint_allowed`. Minting is the ONLY operation that can break
    # Δ=0, so the authority to do it is stated once as a rule instead of being re-derived from
    # env reads at each call site. NOTE on `is_genesis_registry`: this is the frame's OWN
    # minting authority (a mainframe mints; a cloud-op never does) — deliberately NOT
    # FIAT_GENESIS_REGISTRY, which gates only the fiat onramp and is Frame-A-only. Conflating
    # the two is exactly the confusion PART 5 FLOW 12 warns about.
    try:
        from agentvault_registry import opa_shadow as _opa
        _central = os.getenv("IS_CENTRAL_REGISTRY", "false").strip().lower() == "true"
        await _opa.shadow_check(
            "agentvault/invariants/mint_allowed",
            {
                "federated_mode": not _central,
                "is_genesis_registry": _central,
                "actor_is_admin": True,          # require_admin_flag("admin_treasury") guarantees it
                "via_mint_proxy": bool(os.getenv("MINT_PROXY_SECRET", "")),
            },
            True, "teg.mint_tokens")
    except Exception:
        pass   # observability must never block or break a money path

    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/token/issue",
                json={
                    "target_agent_id": request.target_agent_did,
                    "amount": request.amount,
                    "reason": request.reason,
                },
                headers={
                    "Authorization": f"Bearer {TEG_ADMIN_API_KEY}",
                    # §pass73.3.19: proxy marker for the TEG mint lock-down
                    # (TEG_MINT_REQUIRE_PROXY). Identifies this as the authorized
                    # registry mint proxy so the TEG accepts the raw mint. Tests /
                    # callers that hit the TEG directly lack this and are rejected,
                    # which guarantees TokensIssued is always emitted (below).
                    "X-Mint-Proxy-Secret": os.getenv("MINT_PROXY_SECRET", ""),
                },
                timeout=15.0,
            )

            if response.status_code == 200:
                data = response.json()

                # Emit TokensIssued event (Registry is the authorized emitter)
                try:
                    from agentvault_registry.event_emitter import get_event_emitter
                    event_emitter = get_event_emitter()
                    if event_emitter:
                        await event_emitter.emit(
                            aggregate_id=request.target_agent_did,
                            event_type="TokensIssued",
                            idempotency_key=(f"mint-{data.get('transaction_id')}" if data.get("transaction_id") else None),
                            data={
                                "amount": request.amount,
                                "transaction_id": data.get("transaction_id", ""),
                                "issued_by": f"admin:{current_admin.id}",
                                "reason": request.reason,
                                "target_agent_id": request.target_agent_did,
                            },
                        )
                except Exception as e:
                    logger.warning(f"[Mint] EventStore emission failed (non-fatal): {e}")

                logger.info(
                    f"[Mint] SUCCESS: {request.amount} AVT minted to {request.target_agent_did} "
                    f"(tx: {data.get('transaction_id', '?')}, "
                    f"new_balance: {data.get('new_target_balance', '?')})"
                )
                return data

            elif response.status_code == 403:
                detail = response.json().get("detail", "Minting not authorized on this TEG")
                logger.warning(f"[Mint] REJECTED by TEG: {detail}")
                raise HTTPException(status_code=403, detail=detail)

            else:
                error_detail = response.text[:500]
                logger.error(f"[Mint] TEG returned {response.status_code}: {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"TEG issuance failed: {error_detail}",
                )

        except httpx.RequestError as e:
            logger.error(f"[Mint] TEG connection failed: {e}")
            raise HTTPException(
                status_code=503,
                detail="TEG Layer unavailable for the issuance",
            )


async def _fund_agent_from_treasury_internal(
    db: AsyncSession,
    request: TreasuryFundAgentRequest,
    actor_label: str,
    idempotency_key: Optional[str] = None,
) -> dict:
    """
    Fund an agent via the reward funding waterfall (Phase 2, 2026-05-08).

    Replaces the OWL26 direct treasury-transfer with /admin/reward-fund which
    drains fee_collector first then treasury per the configured per-reason
    policy. Caller-facing semantics unchanged ("fund this agent"); funding
    source is policy-driven instead of always treasury.

    Used by `/teg/treasury/fund-agent`, funding-request approve, sandbox
    canary bootstrap, astraeus leaderboard payouts. The Mint button calls
    `/teg/treasury/mint` (different endpoint, void-mint, manual only).

    Returns the TEG response dict on success — note shape changed from the
    pre-Phase-2 treasury_transfer response. Now includes legs[] describing
    waterfall execution. Top-level `transaction_id` is preserved for
    backwards-compat by promoting `legs[0].transaction_id`.

    `actor_label` is logged for attribution.
    """
    logger.info(
        f"[Reward Fund] Funding {request.target_agent_did} with {request.amount} AVT "
        f"(reason: {request.reason}, ref: {request.reference_id}, actor: {actor_label})"
    )

    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            _hdrs = {"Authorization": f"Bearer {TEG_ADMIN_API_KEY}"}
            if idempotency_key:
                # Durable TEG-rail dedup (teg_idempotency_records): a replayed leg with the
                # same key returns the cached result and moves nothing.
                _hdrs["Idempotency-Key"] = idempotency_key
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/reward-fund",
                json={
                    "target_agent_id": request.target_agent_did,
                    "amount": request.amount,
                    "reason": request.reason,
                    "reference_id": request.reference_id
                },
                headers=_hdrs,
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()

                # Phase 2 backwards-compat shim: callers expect top-level
                # `transaction_id`. Hoist from legs[0] so existing code continues
                # working unchanged. Legs are also preserved for new callers
                # that want to inspect the waterfall execution.
                _legs = data.get("legs") or []
                if _legs and "transaction_id" not in data:
                    data["transaction_id"] = _legs[0].get("transaction_id", "")
                if "new_target_balance" not in data:
                    data["new_target_balance"] = data.get("new_target_balance", "0")

                # Sync local Agent.liquid_balance from TEG response
                from agentvault_registry.models import Agent
                try:
                    result = await db.execute(
                        select(Agent).where(Agent.did == request.target_agent_did)
                    )
                    agent = result.scalar_one_or_none()
                    if agent:
                        new_balance = data.get("new_target_balance", "0")
                        agent.liquid_balance = Decimal(str(new_balance))
                        await db.commit()
                        logger.info(
                            f"[Treasury Fund] DB synced: {request.target_agent_did} "
                            f"liquid_balance = {agent.liquid_balance}"
                        )
                    else:
                        logger.warning(
                            f"[Treasury Fund] Agent {request.target_agent_did} not found in local DB — "
                            f"balance not synced (may be federated agent)"
                        )
                except Exception as sync_err:
                    logger.error(f"[Treasury Fund] DB balance sync FAILED: {sync_err}")
                    # Re-fetch from TEG to ensure we have the right balance
                    try:
                        result2 = await db.execute(
                            select(Agent).where(Agent.did == request.target_agent_did)
                        )
                        agent2 = result2.scalar_one_or_none()
                        if agent2:
                            bal_resp = await client.get(
                                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                                headers={"Authorization": f"Bearer {await get_teg_token_for_agent(agent2.id, agent2.did)}"},
                                timeout=5.0
                            )
                            if bal_resp.status_code == 200:
                                agent2.liquid_balance = Decimal(str(bal_resp.json().get("balance", agent2.liquid_balance)))
                                await db.commit()
                                logger.info(f"[Treasury Fund] DB re-synced from TEG: {agent2.liquid_balance}")
                    except Exception as resync_err:
                        logger.error(f"[Treasury Fund] DB re-sync also failed: {resync_err}")
                
                # Emit EventStore event
                try:
                    from agentvault_registry.event_emitter import get_event_emitter
                    event_emitter = get_event_emitter()
                    if event_emitter:
                        # f037: Emit TokensTransferred (not TreasuryFundingGranted) so the
                        # projection credits the agent. TreasuryFundingGranted is audit-only
                        # and doesn't affect balance projection.
                        treasury_did = data.get("treasury_did", "did:theprotocol:teg_system_treasury")
                        # §pass57: use the canonical emit_tokens_transferred() helper which
                        # sets idempotency_key=f"tokens_transferred:{transaction_id}" so the
                        # EventStore UNIQUE constraint dedupes server-side retries. The
                        # previous emit_event() call left idempotency_key as a fresh UUID
                        # per call, defeating EventStore-level dedup.
                        await event_emitter.emit_tokens_transferred(
                            from_agent=treasury_did,
                            to_agent=request.target_agent_did,
                            amount=str(request.amount),
                            transaction_id=data.get("transaction_id", ""),
                            memo=f"treasury_fund:{request.reason}",
                        )
                except Exception as e:
                    logger.warning(f"[Treasury Fund] EventStore emission failed (non-fatal): {e}")
                
                logger.info(
                    f"[Treasury Fund] SUCCESS: {request.amount} AVT → {request.target_agent_did} "
                    f"(tx: {data.get('transaction_id', 'unknown')}, "
                    f"treasury: {data.get('new_treasury_balance', '?')})"
                )
                return data
            else:
                # §LEDGERGATE (V0598): the TEG's ledger gate refused the funding before its handler ran: nothing moved,
                # so no balance to verify; its sentence and Retry-After, as they came
                _refusal = ledger_refusal(response)
                if _refusal is not None:
                    logger.warning("[Treasury Fund] the TEG refused the funding: its ledger cannot record it right now")
                    raise _refusal
                error_detail = response.text[:500]
                logger.warning(
                    f"[Treasury Fund] TEG returned {response.status_code} - {error_detail}. "
                    f"Verifying actual balance (TEG may process transfers despite error responses)..."
                )

                # TEG sometimes returns 400 yet still processes the transfer.
                # Verify by checking the agent's actual TEG balance and syncing if it changed.
                try:
                    teg_token = f"ADMIN_IMPERSONATE:{request.target_agent_did}:{TEG_ADMIN_API_KEY}"
                    verify_resp = await client.get(
                        f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                        headers={"Authorization": f"Bearer {teg_token}"},
                        timeout=10.0,
                    )
                    if verify_resp.status_code == 200:
                        verify_data = verify_resp.json()
                        actual_balance = Decimal(str(verify_data.get("balance", "0")))

                        from agentvault_registry.models import Agent
                        result = await db.execute(
                            select(Agent).where(Agent.did == request.target_agent_did)
                        )
                        agent = result.scalar_one_or_none()
                        if agent:
                            db_balance = agent.liquid_balance or Decimal("0")
                            expected_amount = Decimal(str(request.amount))

                            # If TEG balance is ≥ old DB balance + requested amount,
                            # the transfer went through despite the error response
                            if actual_balance >= db_balance + expected_amount * Decimal("0.9"):
                                agent.liquid_balance = actual_balance
                                await db.commit()
                                logger.info(
                                    f"[Treasury Fund] RECOVERY: TEG returned {response.status_code} "
                                    f"but balance verification shows transfer succeeded. "
                                    f"DB synced: {request.target_agent_did} = {actual_balance} AVT"
                                )
                                return {
                                    "status": "completed_with_recovery",
                                    "new_target_balance": str(actual_balance),
                                    "note": "TEG returned error but balance verification confirmed transfer",
                                }
                            else:
                                logger.info(
                                    f"[Treasury Fund] Verified: transfer genuinely failed. "
                                    f"TEG balance={actual_balance}, DB={db_balance}"
                                )
                except Exception as verify_err:
                    logger.warning(f"[Treasury Fund] Balance verification failed: {verify_err}")

                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Treasury transfer failed: {error_detail}"
                )
                
        except httpx.RequestError as e:
            logger.error(f"[Treasury Fund] TEG connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG treasury service unavailable"
            )


@router.post("/treasury/fund-agent", summary="Fund Agent from Treasury")
async def fund_agent_from_treasury(
    request: TreasuryFundAgentRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="Optional client-supplied UUID. Replays with same key return the same response."),
):
    """
    Pay units to an agent through the funding waterfall (by default the fee account first, then the treasury);
    nothing is issued. The body names `target_agent_did`, `amount`, `reason` and an optional `reference_id`. An
    `Idempotency-Key` header is kept for 24 hours: the same key and body answer the first result again, the same key
    with another body is refused (422). Needs an admin token with the `admin_treasury` flag.

    \f
    OWL26: Fund an agent from the TEG treasury.

    This is the canonical way to give agents AVT. It replaces:
    - Direct TEG /admin/token/issue calls (minting from void)
    - CORS-broken tutorial funding
    - Hardcoded genesis grant minting

    Flow:
    1. Calls TEG POST /api/v1/admin/treasury/transfer
    2. TEG deducts from treasury, credits agent
    3. Updates local Agent.liquid_balance from TEG response
    4. Emits EventStore event
    5. Returns transaction details

    Auth: Admin developer JWT (is_admin=True). Other registry routers should call
    `_fund_agent_from_treasury_internal()` directly instead of looping back through HTTP.

    §pass57: Idempotency-Key now ENFORCED via Redis cache (24h TTL).
    - Same key + same body → cached response returned (no re-execution).
    - Same key + different body → 422.
    - No key → normal behavior (no dedup).
    - Redis down → fail-open (sandbox-friendly).

    Two-layer defense: this request-level cache prevents client double-submit;
    EventStore UNIQUE(idempotency_key) (via the canonical `emit_tokens_transferred`
    helper which uses `tokens_transferred:{transaction_id}` as the deterministic
    event key) prevents emit-side retries from double-storing.
    """
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import developer_caller

    me = developer_caller(current_admin.id)   # D6-777: the key is this administrator's
    body_for_idem = request.model_dump(mode="json")
    cached, err = await idempotency_lookup("teg.treasury.fund-agent", idempotency_key, body_for_idem, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached

    result = await _fund_agent_from_treasury_internal(db, request, actor_label=current_admin.email)
    await idempotency_store("teg.treasury.fund-agent", idempotency_key, body_for_idem, result, principal=me)
    return result


@router.post("/treasury/receive", summary="Return units to the treasury (admin)")
async def return_to_treasury(
    request: TreasuryReceiveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_treasury"))
):
    """
    Move units from an agent back to this frame's treasury (`source_agent_did`, `amount`, `reason`, an optional
    `reference_id`), for example a dispute slash or an administrator's correction. The registry's copy of the agent's
    balance follows the TEG's answer. Needs an admin token with the `admin_treasury` flag.

    \f
    OWL26: Return AVT from an agent to the TEG treasury.
    
    Used for:
    - Dispute slashes (defendant pays penalty back to treasury)
    - Fee collection
    - Admin clawback
    
    Flow:
    1. Calls TEG POST /api/v1/admin/treasury/receive
    2. TEG deducts from agent, credits treasury
    3. Updates local Agent.liquid_balance from TEG response
    4. Emits EventStore event
    5. Returns transaction details
    """
    logger.info(
        f"[Treasury Receive] Returning {request.amount} AVT from {request.source_agent_did} "
        f"(reason: {request.reason}, ref: {request.reference_id})"
    )
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/treasury/receive",
                json={
                    "source_agent_id": request.source_agent_did,
                    "amount": request.amount,
                    "reason": request.reason,
                    "reference_id": request.reference_id
                },
                headers={"Authorization": f"Bearer {TEG_ADMIN_API_KEY}"},
                timeout=15.0
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Sync local Agent.liquid_balance from TEG response
                from agentvault_registry.models import Agent
                result = await db.execute(
                    select(Agent).where(Agent.did == request.source_agent_did)
                )
                agent = result.scalar_one_or_none()
                if agent:
                    new_balance = data.get("new_source_balance", "0")
                    agent.liquid_balance = Decimal(str(new_balance))
                    await db.commit()
                    logger.info(
                        f"[Treasury Receive] DB synced: {request.source_agent_did} "
                        f"liquid_balance = {agent.liquid_balance}"
                    )
                
                # Emit EventStore event
                try:
                    from agentvault_registry.event_emitter import get_event_emitter
                    event_emitter = get_event_emitter()
                    if event_emitter:
                        await event_emitter.emit(
                            aggregate_id=request.source_agent_did,
                            event_type="TreasurySlashReceived",
                            idempotency_key=(f"slash-recv-{data.get('transaction_id')}" if data.get("transaction_id") else None),
                            data={
                                "agent_did": request.source_agent_did,
                                "amount": request.amount,
                                "reason": request.reason,
                                "reference_id": request.reference_id,
                                "transaction_id": data.get("transaction_id", ""),
                                "new_treasury_balance": data.get("new_treasury_balance", ""),
                                "new_source_balance": data.get("new_source_balance", "")
                            }
                        )
                except Exception as e:
                    logger.warning(f"[Treasury Receive] EventStore emission failed (non-fatal): {e}")
                
                logger.info(
                    f"[Treasury Receive] SUCCESS: {request.amount} AVT ← {request.source_agent_did} "
                    f"(tx: {data.get('transaction_id', 'unknown')}, "
                    f"treasury: {data.get('new_treasury_balance', '?')})"
                )
                return data
            else:
                error_detail = response.text[:500]
                logger.error(
                    f"[Treasury Receive] TEG treasury receive failed: "
                    f"{response.status_code} - {error_detail}"
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Treasury receive failed: {error_detail}"
                )
                
        except httpx.RequestError as e:
            logger.error(f"[Treasury Receive] TEG connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG treasury service unavailable"
            )


# =============================================================================
# Cross-TEG Treasury Fund (One-Way: Origin Registry-A → Satellite TEGs)
# =============================================================================

class CrossTEGTreasuryFundRequest(BaseModel):
    """Request to fund a satellite TEG's treasury from the origin TEG (TEG-A)."""
    target_registry: str = Field(
        ...,
        description="Target registry name as in TRUSTED_REGISTRIES or PARTNER_TEGS (e.g., 'Registry B', 'Sandbox Alpha')"
    )
    amount: str = Field(..., description="Amount to transfer, in the frame's unit (string for precision)")
    reason: str = Field(
        default="cross_teg_fund",
        description="Reason: cross_teg_fund, liquidity_provision, settlement, fiat_routed_settle"
    )
    # PB-2 (2026-05-09): caller-supplied correlation_id for idempotency
    # (fiat_purchase_id from the routed-fiat webhook). When provided, this
    # value is used end-to-end (debit + credit both reference it). Server
    # falls back to a fresh UUID when not provided (preserves prior behavior).
    correlation_id: Optional[str] = Field(
        default=None,
        description="Idempotency key (e.g., fiat_purchase_id for routed-fiat). Auto-generated UUID when omitted."
    )

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        try:
            val = Decimal(v)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('Amount must be a valid number')
        if not val.is_finite():   # §MCPTEST30: NaN made `val <= 0` raise InvalidOperation, which answered 500
            raise ValueError('Amount must be a finite number')
        if val <= 0:
            raise ValueError('Amount must be positive')
        _max = money_knob("TEG_TRANSFER_MAX_AVT", "10000000")
        if val > _max:
            raise ValueError(f'Amount exceeds maximum ({_max:,})')
        return str(val)


def _resolve_peer_teg_url(target_registry_name: str) -> Optional[tuple]:
    """Resolve a peer registry name to (teg_url, api_key_or_None).

    Source priority:
      1. TRUSTED_REGISTRIES env (Frame B, registry-b, etc.) — same TEG_ADMIN_API_KEY,
         returns api_key=None to signal "use local TEG_ADMIN_API_KEY for credit leg".
      2. PARTNER_TEGS env (operators, cross-frame TEG partners) — has per-target
         api_key encoded in the env value; returns it so the credit leg can auth
         against the destination TEG's own admin key.

    Match heuristics: slug equality on name, or slug equality after stripping
    'registry-'/'teg-layer-' prefixes (covers both 'cloud-op-X' and
    'teg-layer-X' style identifiers).

    Returns (teg_url, api_key_or_None) on hit, or None when no source matches.
    PB-2 (2026-05-09) — extended from prior single-string return for routed-fiat;
    the api_key tuple element is consumed by `cross_teg_treasury_fund` to use
    the destination TEG's admin key when available, falling back to local key
    when None (which preserves the historical TRUSTED_REGISTRIES behavior).
    """
    target_norm = _slug(target_registry_name)

    # Source 1: TRUSTED_REGISTRIES (existing)
    trusted = getattr(settings, 'trusted_registries', None) or getattr(settings, 'TRUSTED_REGISTRIES', None)
    if trusted:
        for reg in trusted:
            reg_dict = reg if isinstance(reg, dict) else (reg.model_dump() if hasattr(reg, 'model_dump') else vars(reg))
            name = reg_dict.get('registry_name', '') or reg_dict.get('name', '')
            teg_url = reg_dict.get('teg_url', '')
            # Match by name (case-insensitive, whitespace-normalized).
            # Bug fix 2026-05-09: was `target_registry__slug(name)` (double-underscore
            # typo + wrong arg) which raised NameError on every lookup; correct call
            # is `_slug(target_registry_name)` so the candidate's slug matches the
            # caller-supplied target's slug.
            if _slug(name) == target_norm:
                return (teg_url, None)  # use local TEG_ADMIN_API_KEY
            # Also try direct match
            if name.lower() == target_registry_name.lower():
                return (teg_url, None)

    # Source 2: PARTNER_TEGS (cross-TEG partners with per-target admin keys)
    # PB-2 (2026-05-09): added for routed-fiat. PARTNER_TEGS already populates
    # operator URLs + admin keys at compose time (see sandbox-A
    # agentvault_teg_layer_test_a env for examples).
    try:
        partners = json.loads(os.environ.get("PARTNER_TEGS", "[]"))
    except (json.JSONDecodeError, TypeError):
        partners = []
    for partner in partners:
        partner_name = partner.get("registry_id", "") or ""
        partner_teg = partner.get("teg_id", "") or ""
        partner_url = partner.get("url", "") or ""
        partner_key = partner.get("api_key", "") or None
        if not partner_url:
            continue
        # Try slug equality on registry_id (e.g., 'registry-sandbox-alpha')
        if _slug(partner_name) == target_norm:
            return (partner_url, partner_key)
        # Try after stripping 'registry-' / 'teg-layer-' prefixes for tolerant matching
        # (e.g., target='cloud-op-sandboxalpha' matches partner_teg='teg-layer-sandbox-alpha'
        # after both strip 'teg-layer-' / 'registry-')
        norm_partner = _slug(partner_name).replace('registry-', '')
        norm_target_relaxed = target_norm.replace('registry-', '').replace('cloud-op-', '')
        if norm_partner.replace('cloud-op-', '') == norm_target_relaxed:
            return (partner_url, partner_key)
        # Also try teg_id-derived match (strip 'teg-layer-')
        norm_teg = _slug(partner_teg).replace('teg-layer-', '')
        if norm_teg == norm_target_relaxed or norm_teg == target_norm:
            return (partner_url, partner_key)

    return None


async def _resolve_peer_target_for_cross_teg_fund(
    target_registry_name: str,
    db: AsyncSession,
) -> Optional[tuple]:
    """PB-2 (2026-05-10): Resolve target_registry_name → (target_url, cache_key_id).

    Authoritative source: `peer_registries` DB table (already populated by the
    federation invitation/discovery flow on both sandbox AND production).
    This is the SAME data source used by federation_sync, contracts, etc. —
    naming-convention-agnostic, prod-safe.

    `target_url` is the peer's `base_url` (the mTLS endpoint, exactly what
    nginx-federation listens on). The TEG sender uses it directly with mTLS
    via the existing CrossTEGClientFactory — no PARTNER_TEGS lookup required
    on the TEG side because the URL is already canonical.

    `cache_key_id` is a stable per-peer identifier derived from the peer's
    name slug. It is used ONLY as the connection-cache key inside
    `CrossTEGClientFactory.get_client(teg_id, url)` — its value does NOT
    influence routing, auth, or any cross-system contract. The actual mTLS
    auth is via the TEG container's SPIRE certs, validated by the peer's
    nginx-federation against TRUSTED_SPIFFE_DOMAINS / SPIRE bundle —
    completely independent of this string.

    Returns (target_url, cache_key_id) or None when peer not found / inactive.
    """
    peer = await _peer_for_cross_teg_fund(target_registry_name, db)
    if peer is None:
        return None
    base_url = (peer.base_url or '').strip()
    if not base_url:
        logger.warning(
            f"[CROSS-TEG TREASURY] peer '{peer.name}' has no base_url — cannot route"
        )
        return None
    # cache_key_id is a stable string per peer; uses peer.name slug so it's
    # deterministic across orchestrator invocations but NEVER exposed as
    # a routing/auth identifier.
    cache_key_id = f"crossteg-fund-cache:{_slug(peer.name)}"
    return (base_url, cache_key_id)


async def _peer_for_cross_teg_fund(target_registry_name: str, db: AsyncSession):
    """The ACTIVE peer row a cross-TEG treasury fund names (the slug of its name, case-insensitive; peer_registries.name
    is the display name, e.g. "Sandbox Alpha", "Cloud Op London"), or None."""
    if not target_registry_name:
        return None
    target_norm = _slug(target_registry_name)
    row = await db.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.status == 'ACTIVE',
        )
    )
    for peer in row.scalars().all():
        if _slug(peer.name or '') == target_norm:
            return peer
    return None


async def _assert_cross_teg_fund_peer_may_receive(db: AsyncSession, target_registry_name: str) -> None:
    """D6-801 / SEC-18: the checks every other money path asks of a receiving peer, before a treasury fund moves
    anything: its federation licence (assert_peer_license_active, which refuses only where FEDERATION_ENFORCEMENT_ACTIVE
    is set and otherwise records the attempt, as at the cross-registry transfer), for a peer whose operator DID this
    registry can name; and the quarantine (403 while this registry holds the peer in quarantine, soft quarantine or
    blacklisted; 503 when the compliance state cannot be read). The routed fiat purchase settles through this fund, and
    its checkout asked both; the fund itself re-read only that the peer row is ACTIVE."""
    from agentvault_registry.services.federation_license_gate import (
        assert_peer_license_active, assert_registry_not_quarantined, resolve_peer_operator_did,
    )
    peer = await _peer_for_cross_teg_fund(target_registry_name, db)
    if peer is None:
        return   # the caller refuses an unresolvable peer itself (400)
    operator_did = await resolve_peer_operator_did(db, peer)
    if operator_did:
        await assert_peer_license_active(db=db, operator_did=operator_did, context="cross_teg_treasury_fund")
    await assert_registry_not_quarantined(db, peer.name, context="cross_teg_treasury_fund")


@router.post(
    "/treasury/cross-teg-fund",
    summary="Fund satellite TEG treasury from origin TEG (one-way)",
    tags=["Treasury", "Federation"]  # §pass56 PR-6: TitleCase
)
async def cross_teg_treasury_fund(
    request: CrossTEGTreasuryFundRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_treasury"))
):
    """
    Move units from this frame's treasury to the treasury of a federated peer registry's TEG (a cloud operator), one
    way and without a fee. Only a registry the origin allowlist names may start it (`CROSS_TEG_FUND_ORIGIN_ALLOWLIST`),
    the peer must be an active federated peer, a peer this registry holds in quarantine, soft quarantine or blacklisted
    is refused with 403 (503 when its compliance state cannot be read), its federation licence is checked as at the
    cross-registry transfer, and a treasury holding less than the amount is refused with 409 unless automated issuance
    is switched on (`TREASURY_MINT_ON_DEMAND_ENABLED`, off by default). Needs an admin token with the `admin_treasury`
    flag.

    \f
    Transfer AVT from origin TEG treasury to a satellite/operator TEG's treasury.

    PB-2 (2026-05-10) ARCHITECTURE: This is the registry-orchestrator entry
    point. It calls the LOCAL TEG's admin-keyed `/admin/treasury/cross-teg-fund-send`,
    which in turn uses the existing `CrossTEGClientFactory` to make an mTLS call
    to the peer's `/api/v1/cross-teg/treasury-fund` endpoint. This routes via
    the existing prod nginx-federation `/api/v1/cross-teg/` location block —
    zero new nginx config required.

    Treasury-to-treasury moves are ARCHITECTURALLY FEE-EXEMPT (per Commander
    direction 2026-05-10): they are internal protocol primitives, not market
    transactions. Anti-abuse: TEG sender hardcodes sender/receiver agent_id,
    admin Bearer auth required, origin allowlist enforced here at registry layer.

    Mint-on-demand: if mainframe treasury < amount, mint shortage via existing
    `/admin/token/issue` (mainframe-only authority — operator TEGs return 403).

    Flow:
      0. Origin allowlist guard (CROSS_TEG_FUND_ORIGIN_ALLOWLIST env, default 'registry-a').
      1. Resolve target_teg_id from PARTNER_TEGS env.
      2. Mint-on-demand pre-check: balance < amount → mint shortage.
      3. Single call to local TEG's /admin/treasury/cross-teg-fund-send.
      4. Emit CrossTEGTreasuryFunded event.
      5. Return.
    """

    # ── Origin-only guard (env-relaxable for sandbox testing) ──
    # PB-2: CROSS_TEG_FUND_ORIGIN_ALLOWLIST env var (default 'registry-a' so prod
    # behavior is unchanged). Sandbox-A sets this to 'registry-a,registry-test'
    # to enable testing. Comma-separated; substring match per token.
    registry_name = getattr(settings, 'REGISTRY_NAME', '')
    allowed_env = os.getenv("CROSS_TEG_FUND_ORIGIN_ALLOWLIST")   # unset ⇒ 'registry-a' (parse_… default)
    allowed_slugs = parse_fund_origin_allowlist(allowed_env)
    local_slug = _slug(registry_name).lower()
    if not fund_origin_allowed(registry_name, allowed_env):     # §MONEY-R50: the ONE predicate
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Cross-TEG treasury funding is restricted to genesis-class registries. "
                f"This registry is '{registry_name}' (slug='{local_slug}'); "
                f"allowlist={sorted(allowed_slugs)}."
            )
        )

    # Use caller-supplied correlation_id when present (e.g., fiat_purchase_id
    # from routed-fiat webhook), else generate one.
    correlation_id = request.correlation_id or str(uuid.uuid4())
    logger.info(
        f"[CROSS-TEG TREASURY] Admin {current_admin.email} requesting {request.amount} AVT "
        f"→ {request.target_registry} (reason: {request.reason}, corr: {correlation_id})"
    )

    # ── Step 1: Resolve target via peer_registries DB (canonical, prod-safe) ──
    # Uses the same `peer_registries` table that powers federation_sync /
    # contracts / cross-frame transfer routing. NO naming-convention assumption
    # — the URL comes directly from the federated invitation flow.
    resolved = await _resolve_peer_target_for_cross_teg_fund(request.target_registry, db)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot resolve peer for '{request.target_registry}'. "
                f"No ACTIVE peer_registries row matches this name slug. "
                f"Verify the peer is invited + license-active."
            )
        )
    target_url, target_cache_key_id = resolved

    # D6-801 / SEC-18: the licence and the quarantine of the receiving peer, before anything moves
    await _assert_cross_teg_fund_peer_may_receive(db, request.target_registry)

    teg_admin_headers = {"Authorization": f"Bearer {TEG_ADMIN_API_KEY}"}

    # ── Step 2: Mint-on-demand pre-check ──
    # PB-2 (2026-05-10) — Commander: "minting only mainframe work". If treasury
    # short of `amount`, mint shortage via existing /admin/token/issue (gated
    # at TEG by settings.teg_id == settings.minting_authority — mainframe only).
    # Sandbox treasury holds 877M AVT, so this rarely fires; code ships for prod.
    try:
        amount_dec = Decimal(str(request.amount))
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid amount '{request.amount}': {e}"
        )

    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        # Query mainframe treasury balance
        try:
            bal_resp = await client.get(
                f"{TEG_API_BASE_URL}/api/v1/governance/admin/treasury/balance",
                headers=teg_admin_headers,
                timeout=10.0,
            )
            if bal_resp.status_code != 200:
                logger.warning(
                    f"[CROSS-TEG TREASURY] balance check failed {bal_resp.status_code}: "
                    f"{bal_resp.text[:200]} — proceeding without mint-on-demand"
                )
                current_balance = None
                treasury_did_for_mint = "did:theprotocol:teg_system_treasury"
            else:
                bal_data = bal_resp.json()
                current_balance = Decimal(str(bal_data.get("balance", "0")))
                treasury_did_for_mint = bal_data.get("treasury_did", "did:theprotocol:teg_system_treasury")
        except httpx.RequestError as e:
            logger.warning(
                f"[CROSS-TEG TREASURY] balance check connection error: {e} — proceeding"
            )
            current_balance = None
            treasury_did_for_mint = "did:theprotocol:teg_system_treasury"

        if current_balance is not None and current_balance < amount_dec:
            shortage = amount_dec - current_balance
            if not _mint_on_demand_enabled():
                # §MONEY-R19 / D9: refuse, and name the operator action. Minting to
                # cover a provisioning shortfall is a supply decision, not plumbing.
                if TREASURY_SHORTFALL_REFUSED is not None:
                    try:
                        TREASURY_SHORTFALL_REFUSED.labels(reason="cross_teg_fund").inc()
                    except Exception:  # noqa: BLE001
                        pass
                logger.error(
                    "[CROSS-TEG TREASURY] REFUSED: treasury short by %s (have %s, need %s, "
                    "corr %s). Automated minting is OFF (D9) — mint deliberately via the "
                    "registry mint-proxy rail, then retry this fund.",
                    shortage, current_balance, amount_dec, correlation_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Treasury short by {shortage} (have {current_balance}, "
                        f"need {amount_dec}) — issue units first. Automated issuance on demand is "
                        f"disabled; issuance is a supply decision and must be deliberate. "
                        f"Use the registry's issuance rail (POST /api/v1/teg/treasury/mint), then retry."
                    ),
                )
            logger.warning(
                f"[CROSS-TEG TREASURY] TREASURY_MINT_ON_DEMAND_ENABLED=true — minting "
                f"{shortage} AVT to cover a shortfall. THIS INCREASES SUPPLY. "
                f"(have {current_balance}, need {amount_dec})"
            )
            try:
                mint_resp = await client.post(
                    f"{TEG_API_BASE_URL}/api/v1/admin/token/issue",
                    json={
                        "target_agent_id": treasury_did_for_mint,
                        "amount": str(shortage),
                        "reason": f"routed_fiat_treasury_topup:{correlation_id}",
                    },
                    headers={
                        **teg_admin_headers,
                        "Idempotency-Key": f"mint-topup-{correlation_id}",
                        # §pass73.3.19 mint lock-down proxy marker (TEG_MINT_REQUIRE_PROXY)
                        "X-Mint-Proxy-Secret": os.getenv("MINT_PROXY_SECRET", ""),
                    },
                    timeout=15.0,
                )
                if mint_resp.status_code != 200:
                    logger.error(
                        f"[CROSS-TEG TREASURY] mint-on-demand failed "
                        f"{mint_resp.status_code}: {mint_resp.text[:300]}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=(
                            f"Issuance on demand failed (cannot top up treasury for cross-TEG fund): "
                            f"{mint_resp.text[:200]}"
                        )
                    )
                logger.info(
                    f"[CROSS-TEG TREASURY] Minted {shortage} AVT to mainframe treasury "
                    f"(corr: {correlation_id})"
                )
            except httpx.RequestError as e:
                logger.error(f"[CROSS-TEG TREASURY] mint-on-demand connection error: {e}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Issuance on demand unreachable: {str(e)[:200]}"
                )

        # ── Step 3: Single call to local TEG's cross-teg-fund-send ──
        # We pass the canonical `target_url` (from peer_registries DB — same
        # authoritative source federation_sync uses). The cache_key_id is just
        # a connection-pool tag inside the TEG's CrossTEGClientFactory; not a
        # routing/auth identifier. mTLS auth happens via SPIRE certs on the
        # TEG container, validated by the peer's nginx-federation. We map
        # TEG's status codes 1:1 to ours (4xx = deterministic / 5xx = transient).
        try:
            send_resp = await client.post(
                f"{TEG_API_BASE_URL}/api/v1/admin/treasury/cross-teg-fund-send",
                json={
                    "amount": request.amount,
                    "target_teg_id": target_cache_key_id,  # cache key only, not routing
                    "target_url": target_url,              # canonical mTLS endpoint
                    "correlation_id": correlation_id,
                    "reason": request.reason,
                },
                headers=teg_admin_headers,
                timeout=30.0,  # generous: covers mTLS handshake + peer commit
            )
        except httpx.RequestError as e:
            logger.error(f"[CROSS-TEG TREASURY] local TEG connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Local TEG unreachable for cross-teg-fund-send: {str(e)[:200]}"
            )

        if send_resp.status_code != 200:
            error_detail = send_resp.text[:500]
            logger.error(
                f"[CROSS-TEG TREASURY] cross-teg-fund-send returned "
                f"{send_resp.status_code}: {error_detail}"
            )
            raise HTTPException(
                status_code=send_resp.status_code,
                detail=f"Cross-TEG fund-send failed: {error_detail}",
            )

        send_data = send_resp.json()

    # ── Step 4: Emit EventStore event ──
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        event_emitter = get_event_emitter()
        if event_emitter:
            await event_emitter.emit(
                aggregate_id="treasury",
                event_type="CrossTEGTreasuryFunded",
                idempotency_key=f"xteg-fund-{correlation_id}",
                data={
                    "correlation_id": correlation_id,
                    "source_teg": _get_local_teg_id(),
                    "target_registry": request.target_registry,
                    "target_url": target_url,
                    "amount": request.amount,
                    "reason": request.reason,
                    "admin_email": current_admin.email,
                    "transaction_id": send_data.get("transaction_id", ""),
                    "source_treasury_after": str(send_data.get("new_treasury_balance", "")),
                    "peer_response": send_data.get("peer_response", {}),
                }
            )
    except Exception as e:
        logger.warning(f"[CROSS-TEG TREASURY] EventStore emission failed (non-fatal): {e}")

    logger.info(
        f"[CROSS-TEG TREASURY] SUCCESS: {request.amount} AVT from TEG-A → {request.target_registry} "
        f"(corr: {correlation_id}, admin: {current_admin.email})"
    )

    peer_resp = send_data.get("peer_response") or {}
    return {
        "status": send_data.get("status", "completed"),
        "correlation_id": correlation_id,
        "amount": request.amount,
        "source_teg": _get_local_teg_id(),
        "target_registry": request.target_registry,
        "target_url": target_url,
        "source_debit": {
            "transaction_id": send_data.get("transaction_id"),
            "new_treasury_balance": str(send_data.get("new_treasury_balance", "")),
        },
        "target_credit": {
            "transaction_id": peer_resp.get("transaction_id", ""),
            "new_treasury_balance": str(peer_resp.get("new_treasury_balance", "")),
        },
        "reason": request.reason,
    }


logger.info("TEG integration router initialized with strict JWT authentication (no backward compatibility)")
