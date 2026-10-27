"""Canary auto-rebalancer — keeps every canary agent's liquid balance above FLOOR.

§pass24 (2026-05-16) — closes the manual-rebalance gap documented in
`Canary_System.md` § Real money moves. Each canary fire transfers ~0.5–1 AVT
from sender to receiver, so sender balances drift down over weeks. Before this
worker existed, sender balances could cross below the 1.0 AVT minimum lock
threshold for cross-TEG async transfers and cause silent timeout failures
(observed 2026-05-16 03:00–11:00 UTC: paris drained, 257 async failures).

Runs as a leader-elected periodic task on registry-a (the runner host). Each
cycle:
  1. Loads active rows from `canary_agents`
  2. For each agent: queries its home-TEG liquid balance via the agent's own JWT
  3. If balance < FLOOR_AVT (default 5000): refunds the agent up to TOPUP_AVT
  4. Records last-refund timestamp per agent to enforce MIN_INTERVAL_SEC cooldown

Funding routing depends on the canary's home TEG:
  - registry-a (mainframe Frame A): `_fund_agent_from_treasury_internal()` direct call
  - frame-b mainframe: Commander login on Frame B, then `/teg/treasury/fund-agent`
  - cloud-op-op-X: op admin login (creds from CANARY_REBALANCER_OP_CREDS env JSON),
    then op's local `/teg/treasury/fund-agent`

Env config:
  CANARY_REBALANCER_ENABLED            default false. Opt-in per registry env.
  CANARY_REBALANCER_INTERVAL_SEC=300   cycle tick
  CANARY_REBALANCER_LEADER_KEY=canary_rebalancer
  CANARY_REBALANCER_FLOOR_AVT=5000     Commander-specified floor (do not change)
  CANARY_REBALANCER_TOPUP_AVT=1000000  refill target matches today's manual baseline
  CANARY_REBALANCER_MIN_INTERVAL_SEC=3600  per-agent cooldown (1 hour)
  CANARY_REBALANCER_OP_CREDS={}        JSON map for cloud-op admin creds; empty → mainframe-only

Idempotency: in-memory `_last_rebalance` dict + per-fund `reference_id` for TEG dedup.
"""
import asyncio
import datetime
import json
import logging
import os
import secrets
import time
import urllib.parse
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import httpx
from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select

from .. import models
from ..database import get_db_context
from ._worker_base import BackgroundWorker
from .leader import get_redis, try_acquire_leadership

logger = logging.getLogger(__name__)


def _canary_home_host() -> str:
    """The host the retired password leg would dial an operator's admin login on (§BATCH3 item 1).
    Was the box IP as a literal; now CANARY_HOME_HOST, unset by default: the leg is a NAMED
    fallback that V0221 left without credentials, and a fallback must not carry topology in code."""
    return os.getenv("CANARY_HOME_HOST", "").strip()


# §pass27 Phase 2 — Prometheus metrics (lazy, best-effort).
try:
    from prometheus_client import Counter as _RCounter, Gauge as _RGauge

    REBALANCE_CYCLE_TOTAL = _RCounter(
        "canary_rebalance_cycle_total",
        "Rebalancer cycles run (leader only)",
        labelnames=["registry_id"],
    )
    REBALANCE_FUNDED_TOTAL = _RCounter(
        "canary_rebalance_funded_total",
        "Canary agents successfully refunded",
        labelnames=["home_kind"],
    )
    REBALANCE_SKIPPED_COOLDOWN_TOTAL = _RCounter(
        "canary_rebalance_skipped_cooldown_total",
        "Agents skipped due to per-agent cooldown",
        labelnames=["home_kind"],
    )
    REBALANCE_ERRORS_TOTAL = _RCounter(
        "canary_rebalance_errors_total",
        "Funding errors by home_kind and reason",
        labelnames=["home_kind", "reason"],
    )
    REBALANCE_AVT_DISBURSED_TOTAL = _RCounter(
        "canary_rebalance_avt_disbursed_total",
        "Units successfully disbursed by the rebalancer (the frame's unit)",
        labelnames=["home_kind"],
    )
except Exception:  # pragma: no cover
    REBALANCE_CYCLE_TOTAL = None
    REBALANCE_FUNDED_TOTAL = None
    REBALANCE_SKIPPED_COOLDOWN_TOTAL = None
    REBALANCE_ERRORS_TOTAL = None
    REBALANCE_AVT_DISBURSED_TOTAL = None

CANARY_REBALANCER_ENABLED = os.environ.get("CANARY_REBALANCER_ENABLED", "false").lower() == "true"
# §CANARYBIND: master canary switch + the runtime fleet-pause key, both owned by
# canary_runner. Imported (not re-derived) so the three workers cannot drift apart.
CANARY_ENABLED = os.environ.get("CANARY_ENABLED", "true").lower() == "true"
from .canary_runner import CANARY_FLEET_PAUSED_KEY  # noqa: E402
CANARY_REBALANCER_INTERVAL_SEC = int(os.environ.get("CANARY_REBALANCER_INTERVAL_SEC", "300"))
CANARY_REBALANCER_LEADER_KEY = os.environ.get("CANARY_REBALANCER_LEADER_KEY", "canary_rebalancer")
# §CANARYONBOARD (2026-09-22): env first, then the NETWORK PROFILE, then the legacy default. These read os.environ only,
# so a low-supply frame (EU/ASIA: 1,000,001 in circulation each) got a 1,000,000 top-up, its whole supply.
from ..core import network_profile as _np  # noqa: E402
CANARY_REBALANCER_FLOOR_AVT = Decimal(_np.knob("CANARY_REBALANCER_FLOOR_AVT", "5000") or "5000")
CANARY_REBALANCER_TOPUP_AVT = Decimal(_np.knob("CANARY_REBALANCER_TOPUP_AVT", "1000000") or "1000000")
# §CANARYONBOARD (his words 2026-09-22: "since we dont mint so much on eu-asia frame we have to rebalance them properly"):
# the band's upper edge. A canary holding more than the ceiling returns everything beyond FLOOR + TOP-UP (the most a
# refill leaves it with) to this node's treasury through the escrow rail's fee-free agent -> treasury move (Δ-neutral:
# the treasury is inside total_circulating). Without it the rebalancer only ever PAID canaries, so whatever a canary
# received (a genesis grant, the far side of a lane whose return leg failed) sat there for good, which a frame with a
# small supply cannot afford. 0, the default, is no sweep: a node that does not set it behaves exactly as before.
CANARY_REBALANCER_CEILING_AVT = Decimal(_np.knob("CANARY_REBALANCER_CEILING_AVT", "0") or "0")
# §2026-06-09: Frame-C ME-ops mint BVT and run small reciprocal-FX canaries on modest
# treasuries (~165k BVT), so the AVT-scaled 1M topup would overdraw the op treasury and
# the fund leg would fail every cycle. Use a BVT-sized topup for frame-c canaries (keyed
# on canary.frame); AVT (Frame-A/B) ops are unchanged. See _topup_for().
CANARY_REBALANCER_TOPUP_BVT = Decimal(os.environ.get("CANARY_REBALANCER_TOPUP_BVT", "50000"))
CANARY_REBALANCER_MIN_INTERVAL_SEC = int(os.environ.get("CANARY_REBALANCER_MIN_INTERVAL_SEC", "3600"))
CANARY_REBALANCER_HTTP_TIMEOUT_SEC = int(os.environ.get("CANARY_REBALANCER_HTTP_TIMEOUT_SEC", "15"))
# §2026-05-29: emit CanaryRebalancerErrored(balance_query_failed) only after this many
# CONSECUTIVE failures, then at most once per interval — transient registry→TEG timeouts
# under load shouldn't flood the event/WS feed (the Prometheus metric still ticks every cycle).
CANARY_REBALANCER_ERR_EMIT_AFTER = int(os.environ.get("CANARY_REBALANCER_ERR_EMIT_AFTER", "3"))
CANARY_REBALANCER_ERR_EMIT_INTERVAL_SEC = int(os.environ.get("CANARY_REBALANCER_ERR_EMIT_INTERVAL_SEC", "3600"))

# ── §R5 (batch 2, 2026-09-05, his word "fed sync is mtls"): the mTLS canary-refill rail ─────────────
# The master no longer logs in to an operator with an ADMIN PASSWORD over its host port to refill
# that operator's canary senders. It asks the operator, over the federation mTLS channel (the only
# prefix the cross-registry gateway forwards, the canary-fire pattern), to refill ITS OWN senders
# from ITS OWN treasury: POST /api/v1/federation/canary-refill → refill_local_senders(). The
# password leg (CANARY_REBALANCER_OP_CREDS) survives only as the fallback for a home that answers
# 404 (an image older than this rail) and is retired from registry-a's env once every running
# operator carries it.
CANARY_REFILL_ENABLED = os.environ.get("CANARY_REFILL_ENABLED", "true").lower() == "true"
CANARY_REFILL_MAX_FUND = int(os.environ.get("CANARY_REFILL_MAX_FUND", "10"))
try:
    CANARY_REFILL_TOTAL = _RCounter(
        "canary_refill_total",
        "R5 canary-refill rail: role=home (this node refilled its own senders on a peer's request) | master (this node asked a home); outcome",
        ["role", "outcome"],
    )
except Exception:  # noqa: BLE001 — duplicate registration on reload
    CANARY_REFILL_TOTAL = None

try:
    CANARY_REBALANCER_OP_CREDS: Dict[str, Dict] = json.loads(
        os.environ.get("CANARY_REBALANCER_OP_CREDS", "") or "{}"
    )
except Exception as e:  # noqa: BLE001
    logger.warning(f"[CanaryRebalancer] CANARY_REBALANCER_OP_CREDS parse failed: {e}")
    CANARY_REBALANCER_OP_CREDS = {}

# Commander login for Frame B mainframe. Same creds as registry-a; verified
# earlier in the §canary-refuel session that commander@theprotocol.cloud has
# admin on both frames.
FRAME_B_ADMIN_URL = os.environ.get("FRAME_B_URL", "https://frame-b.theprotocol.cloud")
FRAME_B_ADMIN_EMAIL = os.environ.get("FRAME_B_ADMIN_EMAIL", "commander@theprotocol.cloud")
FRAME_B_ADMIN_PASSWORD = os.environ.get("FRAME_B_ADMIN_PASSWORD", "")

_last_rebalance: Dict[str, datetime.datetime] = {}
_admin_jwt_cache: Dict[str, Tuple[str, datetime.datetime]] = {}

# §pass27 Phase 2 — per-agent live state for the Tier-3 modal.
# Keyed by agent_did.
_last_balance: Dict[str, Tuple[Decimal, datetime.datetime]] = {}
_last_error: Dict[str, str] = {}
# §2026-05-29: throttle balance_query_failed event emission (see loop). Root cause is the
# canary cross-frame churn saturating the sandbox TEG's I/O concurrency (short ~1.5s balance
# transactions) → occasional registry→TEG timeouts — NOT an auth/proxy fault.
_consec_balance_failures: Dict[str, int] = {}
_last_balance_err_emit: Dict[str, datetime.datetime] = {}
# §2026-06-09: throttle the fund_failed / unknown-home event the same way (≤once/interval per
# agent) so a persistently-unfundable canary can't flood the ES (root cause of the 4.9k-event
# CanaryRebalancerErrored backlog: a Frame-C ME-op canary with no creds emitting every cycle).
_last_fund_err_emit: Dict[str, datetime.datetime] = {}

# Most recent cycle stats — populated by _rebalance_cycle, read by snapshot().
_LAST_CYCLE_STATS: Dict[str, Any] = {
    "checked": 0,
    "funded": 0,
    "skipped_cooldown": 0,
    "errors": 0,
    "avt_disbursed": "0",
    "swept": 0,
    "avt_swept": "0",
    "remote_homes": 0,
    "remote_checked": 0,
    "remote_funded": 0,
    "remote_errors": 0,
    "remote_skipped_cooldown": 0,
}


async def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _topup_for(canary: "models.CanaryAgent") -> Decimal:
    """Frame-aware refill target: Frame-C ME-op canaries hold BVT on modest op treasuries
    → use the BVT-sized topup; everything else (Frame-A/B, AVT) uses the AVT baseline."""
    return CANARY_REBALANCER_TOPUP_BVT if getattr(canary, "frame", "") == "frame-c" else CANARY_REBALANCER_TOPUP_AVT


def sweep_amount(canary: "models.CanaryAgent", balance: Decimal) -> Decimal:
    """What a canary returns to the treasury: everything beyond FLOOR + its top-up, once it holds MORE than the ceiling.
    Zero when the sweep is off, the balance is inside the band, or the band is malformed (a ceiling at or below
    floor + top-up would sweep a sender to where the next refill pays it again, a loop that moves money for nothing)."""
    ceiling = CANARY_REBALANCER_CEILING_AVT
    keep = CANARY_REBALANCER_FLOOR_AVT + _topup_for(canary)
    if ceiling <= 0 or ceiling <= keep or balance is None or balance <= ceiling:
        return Decimal(0)
    return balance - keep


def sweep_reference(agent_did: str, now: datetime.datetime) -> str:
    """One sweep per sender per UTC day: the TEG claims this key with the move, so a second cycle the same day (a
    restart, a rotated leader) replays the first sweep instead of making another, and a different amount under the same
    key is refused (409) rather than paid."""
    return f"canary-sweep:{agent_did.split(':')[-1]}:{now.strftime('%Y%m%d')}"


async def _sweep_to_treasury(canary: "models.CanaryAgent", amount: Decimal, ref: str) -> Dict[str, Any]:
    """Canary -> this node's treasury on the escrow rail (services/escrow.py::escrow_deposit: TEG admin/treasury/receive,
    fee-free, Idempotency-Key = ref). The ledger records it as the TEG's balance move (entry treasury_rcv_canary_sweep)."""
    from ..services.escrow import escrow_deposit
    return await escrow_deposit(canary.agent_did, amount, ref, reason="canary_sweep")


async def _sweep_one(canary: "models.CanaryAgent", balance: Decimal, amount: Decimal, now: datetime.datetime,
                     actor: str) -> bool:
    ref = sweep_reference(canary.agent_did, now)
    try:
        resp = await _sweep_to_treasury(canary, amount, ref)
    except Exception as e:  # noqa: BLE001 — one refused sweep must never abort the cycle
        _last_error[canary.agent_did] = "sweep_failed"
        logger.warning(f"[CanaryRebalancer] sweep {canary.agent_did} {amount} ({actor}) failed: {str(e)[:200]}")
        return False
    _last_rebalance[canary.agent_did] = now
    _last_error.pop(canary.agent_did, None)
    logger.info(f"[CanaryRebalancer] SWEPT {canary.agent_did} balance={balance} > ceiling={CANARY_REBALANCER_CEILING_AVT}: "
                f"returned {amount} to the treasury ref={ref} tx={(resp or {}).get('transaction_id')} ({actor})")
    return True


def _is_self_url(registry_url: str) -> bool:
    """§CANARYONBOARD (2026-09-22): a sender whose registry_url is THIS node (loopback, or REGISTRY_SELF_URL)."""
    from urllib.parse import urlparse
    try:
        host = (urlparse(registry_url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    self_url = (os.environ.get("REGISTRY_SELF_URL") or "").strip().rstrip("/")
    return bool(self_url) and (registry_url or "").rstrip("/").startswith(self_url)


def _home_kind(registry_url: str) -> str:
    """Return 'self' | 'mainframe-a' | 'frame-b' | 'op-<city>' | 'unknown' for a canary's registry_url.

    §CANARYONBOARD (2026-09-22): 'self' first. The kinds below name the legacy registries (registry-a, frame-b,
    frame-c, the OP_CREDS ports), so on any other network a master's OWN senders read 'unknown' and were skipped
    forever ("never refilled"); a sender that lives on this node is funded from this node's treasury, as registry-a's
    always were."""
    if _is_self_url(registry_url):
        return "self"
    if "registry-a" in registry_url:
        return "mainframe-a"
    if registry_url.endswith(":8100"):
        return "frame-b"
    # §pass78c — frame-c sovereign mainframe (BVT). Its mainframe canary's
    # registry_url is the internal http://frame-c-registry:8000 (public :8101).
    # Funded via the direct-internal path (the rebalancer runs ON frame-c-registry).
    if "frame-c-registry" in registry_url or registry_url.endswith(":8101"):
        return "frame-c"
    for op, cfg in CANARY_REBALANCER_OP_CREDS.items():
        if f":{cfg.get('port')}" in registry_url:
            return op
    return "unknown"


async def _get_admin_jwt(cache_key: str, login_url: str, email: str, password: str, verify_tls: bool = True) -> Optional[str]:
    """Get a (cached) admin dev JWT. 5-min TTL."""
    cached = _admin_jwt_cache.get(cache_key)
    now = await _now_utc()
    if cached and cached[1] > now + datetime.timedelta(minutes=1):
        return cached[0]
    # §2026-06-09: set `verify` ONCE. op admins present self-signed certs → verify_tls=False.
    # Previously `verify` was put in transport_args AND ALSO passed explicitly to AsyncClient →
    # "got multiple values for keyword argument 'verify'" TypeError that crashed every op-funding
    # cycle (latent until ME-op homes resolved — Frame-A ops rarely drain below floor).
    transport_args: Dict = {
        "timeout": CANARY_REBALANCER_HTTP_TIMEOUT_SEC,
        "verify": (get_httpx_verify() if verify_tls else False),
    }
    async with httpx.AsyncClient(**transport_args) as client:
        # §FEDSYNCTRUTH-2 (2026-09-03): the body is a FORM and MUST be URL-encoded — the old f-string
        # sent `+` as a space and `%`/`=`/`&` raw, so every operator whose admin password carried one
        # of them answered 401 forever (op-doha, op-newyork, op-riyadh, op-washington; measured).
        r = await client.post(
            login_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urllib.parse.urlencode({"username": email, "password": password}),
        )
    if r.status_code != 200:
        logger.warning(f"[CanaryRebalancer] admin login {cache_key} → HTTP {r.status_code}: {r.text[:160]}")
        return None
    try:
        token = r.json()["access_token"]
    except (KeyError, ValueError):
        logger.warning(f"[CanaryRebalancer] admin login {cache_key} bad body: {r.text[:160]}")
        return None
    _admin_jwt_cache[cache_key] = (token, now + datetime.timedelta(minutes=5))
    return token


async def _check_balance(canary: "models.CanaryAgent") -> Optional[Decimal]:
    """Query the canary's home-TEG liquid balance using its own agent JWT."""
    # Reuse the cache from canary_runner (it mints + caches agent JWTs)
    from .canary_runner import _get_agent_jwt
    try:
        jwt = await _get_agent_jwt(canary)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[CanaryRebalancer] mint agent JWT for {canary.agent_did} failed: {e}")
        return None
    try:
        async with httpx.AsyncClient(timeout=CANARY_REBALANCER_HTTP_TIMEOUT_SEC, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{canary.registry_url}/api/v1/teg/balance",
                headers={"Authorization": f"Bearer {jwt}"},
            )
        if r.status_code != 200:
            logger.warning(f"[CanaryRebalancer] balance check for {canary.agent_did} → HTTP {r.status_code}")
            return None
        data = r.json()
        # TEG balance endpoint shape: {"balance": "<decimal>", ...}
        bal = data.get("balance") or data.get("token_balance") or data.get("liquid_balance")
        if bal is None:
            logger.warning(f"[CanaryRebalancer] balance for {canary.agent_did} not in response: {str(data)[:200]}")
            return None
        bal_dec = Decimal(str(bal))
        _last_balance[canary.agent_did] = (bal_dec, datetime.datetime.now(datetime.timezone.utc))
        return bal_dec
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[CanaryRebalancer] balance fetch for {canary.agent_did} crashed: {e}")
        return None


async def _emit_audit_event(event_type: str, agent_did: str, data: Dict[str, Any],
                            idempotency_key: Optional[str] = None) -> None:
    """Best-effort audit emission for the rebalancer's two new event types (§BATCH8 item 8: keyed by the
    funding reference, so a retried cycle cannot record one refund twice)."""
    try:
        from ..event_emitter import get_event_emitter
        emitter = get_event_emitter()
        if emitter is None:
            return
        await emitter.emit(
            event_type=event_type,
            aggregate_id=agent_did,
            aggregate_type="CanaryAgent",
            data=data,
            idempotency_key=idempotency_key,
        )
    except Exception as e:  # noqa: BLE001
        # §BATCH9 / S4 pass 5: a swallowed audit emit was a DEBUG line — the funding moved and the ledger
        # never heard, with no counter. Attempt and success are separate clocks: WARN + count.
        logger.warning(f"[CanaryRebalancer] audit emit FAILED ({event_type}) for {agent_did}: {e}")
        try:
            if REBALANCE_ERRORS_TOTAL is not None:
                REBALANCE_ERRORS_TOTAL.labels(home_kind="audit", reason="emit_failed").inc()
        except Exception:  # noqa: BLE001
            pass


async def _refund_agent(canary: "models.CanaryAgent", home: str) -> bool:
    """Refund the canary up to TOPUP via the appropriate path. Returns True on success."""
    ts = int(time.time() * 1000)
    ref = f"canary-rebalance-{canary.agent_did}-{ts}-{secrets.token_hex(4)}"
    amount_str = str(_topup_for(canary))  # frame-aware (BVT for Frame-C ME-ops)

    if home in ("mainframe-a", "frame-c", "self"):   # §CANARYONBOARD: 'self' = this node's own treasury
        # Direct internal call — no HTTP loopback. frame-c is a sovereign
        # mainframe (BVT); its rebalancer runs ON frame-c-registry, so this funds
        # the local frame-c canary from frame-c's OWN treasury in its local
        # currency (BVT), exactly as mainframe-a does for Frame A. §pass78c.
        # (ME-op canaries are kept topped up by BALANCED reciprocal FX paths —
        # the op→<city> remote-admin path can't reach them: their admin password
        # is random/unstored. See session log §pass78c.)
        from ..routers.teg_integration import (
            _fund_agent_from_treasury_internal,
            TreasuryFundAgentRequest,
        )
        async with get_db_context() as db:
            try:
                request = TreasuryFundAgentRequest(
                    target_agent_did=canary.agent_did,
                    amount=amount_str,
                    reason="canary_rebalance",
                    reference_id=ref,
                )
                result = await _fund_agent_from_treasury_internal(db, request, actor_label="canary_rebalancer")
                new_bal = result.get("new_target_balance") or result.get("new_balance") or "?"
                logger.info(f"[CanaryRebalancer] FUNDED {canary.agent_did} ({home}) → {new_bal} (ref={ref})")
                return True
            except Exception as e:  # noqa: BLE001
                logger.error(f"[CanaryRebalancer] {home} fund {canary.agent_did} crashed: {e}", exc_info=True)
                return False

    if home == "frame-b":
        if not FRAME_B_ADMIN_PASSWORD:
            logger.warning(f"[CanaryRebalancer] FRAME_B_ADMIN_PASSWORD unset; skipping {canary.agent_did}")
            return False
        token = await _get_admin_jwt(
            cache_key="frame-b",
            login_url=f"{FRAME_B_ADMIN_URL}/api/v1/auth/login",
            email=FRAME_B_ADMIN_EMAIL,
            password=FRAME_B_ADMIN_PASSWORD,
            verify_tls=True,
        )
        if not token:
            return False
        async with httpx.AsyncClient(timeout=CANARY_REBALANCER_HTTP_TIMEOUT_SEC, verify=get_httpx_verify()) as client:
            r = await client.post(
                f"{FRAME_B_ADMIN_URL}/api/v1/teg/treasury/fund-agent",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"target_agent_did": canary.agent_did, "amount": amount_str, "reason": "canary_rebalance", "reference_id": ref},
            )
        if r.status_code == 200:
            logger.info(f"[CanaryRebalancer] FUNDED {canary.agent_did} (frame-b) → 200 (ref={ref})")
            return True
        logger.warning(f"[CanaryRebalancer] frame-b fund {canary.agent_did} HTTP {r.status_code}: {r.text[:200]}")
        return False

    if home.startswith("op-"):
        creds = CANARY_REBALANCER_OP_CREDS.get(home)
        if not creds:
            logger.warning(f"[CanaryRebalancer] no creds for {home}; skipping {canary.agent_did}")
            return False
        port = creds["port"]
        host = _canary_home_host()
        if not host:
            logger.warning(f"[CanaryRebalancer] CANARY_HOME_HOST unset; cannot dial {home}; skipping {canary.agent_did}")
            return False
        base = f"http://{host}:{port}"
        token = await _get_admin_jwt(
            cache_key=home,
            login_url=f"{base}/api/v1/auth/login",
            email=creds["email"],
            password=creds["password"],
            verify_tls=False,
        )
        if not token:
            return False
        async with httpx.AsyncClient(timeout=CANARY_REBALANCER_HTTP_TIMEOUT_SEC, verify=get_httpx_verify()) as client:
            r = await client.post(
                f"{base}/api/v1/teg/treasury/fund-agent",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"target_agent_did": canary.agent_did, "amount": amount_str, "reason": "canary_rebalance", "reference_id": ref},
            )
        if r.status_code == 200:
            logger.info(f"[CanaryRebalancer] FUNDED {canary.agent_did} ({home}) → 200 (ref={ref})")
            return True
        logger.warning(f"[CanaryRebalancer] {home} fund {canary.agent_did} HTTP {r.status_code}: {r.text[:200]}")
        return False

    logger.warning(f"[CanaryRebalancer] unknown home '{home}' for {canary.agent_did}; skipping")
    return False


# ── §FEDSYNCTRUTH-2 (2026-09-03): the SENDERS of remote-homed paths ────────────────────────────
# The master schedules paths that live on the ops / Frame-B (`canary_remote_paths`); their SENDERS
# live in the home node's own tables — invisible to the local roster above — and the ops run no
# rebalancer of their own. Measured 2026-09-03: op-washington's fx 2pc sender sat at 5.4 AVT (each
# fire needs 5.9) and failed 26 of 141 fires a day with 402 while washington's treasury held 9.3M.
# This leg asks each home node, with the admin login the master already holds, for its active
# senders, reads their mirrored balance, and refills under-floor ones from THAT node's treasury
# through the canonical fund-agent rail (FLOW 4, delta-neutral). Frame-C runs its own rebalancer
# and is skipped. Off switch: CANARY_REBALANCER_REMOTE_SENDERS=false.
_REMOTE_SENDERS_ENABLED = os.environ.get("CANARY_REBALANCER_REMOTE_SENDERS", "true").lower() == "true"


def _remote_client(**kw) -> httpx.AsyncClient:
    """One indirection so a test can hand the leg a MockTransport client."""
    return httpx.AsyncClient(**kw)


def _remote_home_creds(home_registry: str) -> Optional[Dict[str, Any]]:
    """Admin login for a remote path's home: an op → CANARY_REBALANCER_OP_CREDS (identity keys —
    a container label such as op-singapore is collapsed to its identity first), Frame-B → the
    Frame-B admin login, Frame-C → None (it refills its own senders), anything else → None."""
    hl = (home_registry or "").strip().lower()
    if not hl or hl in ("frame-c", "registry-frame-c", "registry-a", "frame-a", "mainframe-a"):
        return None
    if hl in ("frame-b", "registry-frame-b"):
        if not FRAME_B_ADMIN_PASSWORD:
            return None
        return {"home": "frame-b", "base": FRAME_B_ADMIN_URL.rstrip("/"), "email": FRAME_B_ADMIN_EMAIL,
                "password": FRAME_B_ADMIN_PASSWORD, "verify_tls": True}
    try:
        from ..core.operator_names import identity_slug
        key = identity_slug(hl)
    except Exception:  # noqa: BLE001
        key = hl
    creds = CANARY_REBALANCER_OP_CREDS.get(key) or CANARY_REBALANCER_OP_CREDS.get(hl)
    if not creds or not creds.get("port"):
        return None
    host = _canary_home_host()
    if not host:
        return None
    return {"home": key, "base": f"http://{host}:{creds['port']}", "email": creds.get("email", ""),
            "password": creds.get("password", ""), "verify_tls": False}


async def _load_remote_homes() -> list:
    """Distinct home registries of the ACTIVE master-scheduled remote paths."""
    async with get_db_context() as db:
        rows = (await db.execute(
            select(models.CanaryRemotePath.home_registry)
            .where(models.CanaryRemotePath.is_active == True)  # noqa: E712
            .distinct()
        )).scalars().all()
    return sorted({(h or "").strip() for h in rows if (h or "").strip()})


async def _load_local_senders() -> list:
    """This node's ACTIVE canary senders (the same query the local cycle runs)."""
    async with get_db_context() as db:
        sender_ids_subq = (
            select(models.CanaryPath.sender_agent_id)
            .where(models.CanaryPath.is_active == True)  # noqa: E712
            .distinct()
        )
        result = await db.execute(
            select(models.CanaryAgent).where(
                models.CanaryAgent.is_active == True,  # noqa: E712
                models.CanaryAgent.id.in_(sender_ids_subq),
            )
        )
        return list(result.scalars().all())


def refill_reference(agent_did: str, now: datetime.datetime) -> str:
    """The refill's audit reference — unique per ATTEMPT, never an idempotency key.

    V0221 shipped this as one-per-sender-per-HOUR and passed it as the treasury rail's
    idempotency_key, to dedup a master's retry. tests/test_treasury_fund_idempotency.py refused it
    (§BATCH3, 2026-09-05), and the refusal is right: a floor-keeper reacts to the balance it reads,
    so a retried ask re-reads the sender ABOVE the floor and funds nothing — the balance read is the
    dedup. A per-hour key did the opposite of what a keeper is for: a sender that burned its refill
    at 10:05 stayed under the floor until 11:00, i.e. the 402 class R5 exists to prevent."""
    return f"canary-refill-{agent_did}-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


async def _fleet_paused() -> bool:
    try:
        _r = await get_redis()
        return bool(_r is not None and await _r.get(CANARY_FLEET_PAUSED_KEY))
    except Exception:  # noqa: BLE001
        return False


async def _fund_local_from_treasury(canary: "models.CanaryAgent", amount: Decimal, ref: str, actor: str) -> Dict[str, Any]:
    """Fund one of THIS node's canaries from THIS node's treasury through the registry rail
    (TokensTransferred emitted, Δ-neutral) — the same call the local cycle makes for a mainframe."""
    from ..routers.teg_integration import _fund_agent_from_treasury_internal, TreasuryFundAgentRequest
    async with get_db_context() as db:
        req = TreasuryFundAgentRequest(
            target_agent_did=canary.agent_did, amount=str(amount), reason="canary_refill", reference_id=ref,
        )
        # a keeper stays UNKEYED (test_treasury_fund_idempotency): the balance read is the dedup
        return await _fund_agent_from_treasury_internal(db, req, actor_label=actor)


async def refill_local_senders(*, requested_by: str, dry_run: bool = False,
                               max_fund: Optional[int] = None) -> Dict[str, Any]:
    """§R5 HOME side. Refill this node's canary senders that sit below the floor, from this node's
    own treasury, on a peer's mTLS-authenticated request. Returns the report the master aggregates.
    Refuses nothing silently: disabled / paused / fleet-off all say so in the body."""
    now = await _now_utc()
    out: Dict[str, Any] = {"ok": True, "requested_by": requested_by, "dry_run": bool(dry_run),
                           "checked": 0, "funded": 0, "would_fund": 0, "swept": 0, "would_sweep": 0,
                           "skipped_cooldown": 0, "errors": 0, "senders": [], "at": now.isoformat()}
    if not CANARY_REFILL_ENABLED or not CANARY_ENABLED:
        out.update(ok=True, disabled=True); return out
    if await _fleet_paused():
        out.update(paused=True); return out
    cap = CANARY_REFILL_MAX_FUND if max_fund is None else max(0, min(int(max_fund), CANARY_REFILL_MAX_FUND))
    funded_now = 0
    for canary in await _load_local_senders():
        out["checked"] += 1
        row: Dict[str, Any] = {"did": canary.agent_did}
        last = _last_rebalance.get(canary.agent_did)
        if last is not None and (now - last).total_seconds() < CANARY_REBALANCER_MIN_INTERVAL_SEC:
            out["skipped_cooldown"] += 1; row["action"] = "cooldown"; out["senders"].append(row); continue
        balance = await _check_balance(canary)
        if balance is None:
            out["errors"] += 1; _last_error[canary.agent_did] = "balance_query_failed"
            row["action"] = "balance_query_failed"; out["senders"].append(row); continue
        row["balance"] = str(balance)
        if balance >= CANARY_REBALANCER_FLOOR_AVT:
            # §CANARYONBOARD: above the ceiling the excess goes back to this node's treasury (the master's cycle does
            # the same for its own canaries; this is the leg that reaches an operator's)
            excess = sweep_amount(canary, balance)
            if excess <= 0:
                row["action"] = "above_floor"
            elif dry_run:
                out["would_sweep"] += 1; row.update(action="would_sweep", amount=str(excess))
            elif await _sweep_one(canary, balance, excess, now, actor=f"canary_refill:{requested_by}"):
                out["swept"] += 1; row.update(action="swept", amount=str(excess), reference=sweep_reference(canary.agent_did, now))
            else:
                out["errors"] += 1; row.update(action="sweep_failed", amount=str(excess))
            out["senders"].append(row); continue
        amount = _topup_for(canary); ref = refill_reference(canary.agent_did, now)
        row.update(amount=str(amount), reference=ref)
        if dry_run:
            out["would_fund"] += 1; row["action"] = "would_fund"; out["senders"].append(row); continue
        if funded_now >= cap:
            row["action"] = "cap_reached"; out["senders"].append(row); continue
        try:
            resp = await _fund_local_from_treasury(canary, amount, ref, actor=f"canary_refill:{requested_by}")
            funded_now += 1; out["funded"] += 1; _last_rebalance[canary.agent_did] = now
            row.update(action="funded", tx=(resp or {}).get("transaction_id") or (resp or {}).get("teg_transaction_id"))
            if CANARY_REFILL_TOTAL is not None:
                try: CANARY_REFILL_TOTAL.labels(role="home", outcome="funded").inc()
                except Exception: pass
            logger.info(f"[CanaryRefill] FUNDED {canary.agent_did} {amount} ref={ref} for {requested_by}")
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1; _last_error[canary.agent_did] = "refill_failed"; row["action"] = f"error: {str(e)[:120]}"
            if CANARY_REFILL_TOTAL is not None:
                try: CANARY_REFILL_TOTAL.labels(role="home", outcome="error").inc()
                except Exception: pass
            logger.warning(f"[CanaryRefill] {canary.agent_did} fund failed: {str(e)[:200]}")
        out["senders"].append(row)
    return out


async def _refill_home_via_federation(home: str, *, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    """§R5 MASTER side. Ask a remote home to refill its own senders over the federation mTLS
    channel (the canary-fire transport). None = the rail is not there (404, no peer row, no client
    cert, transport error) — the caller may fall back to the password leg and MUST say so."""
    from sqlalchemy import func as _func
    from ..routers.teg_integration import _to_internal_mtls_url
    from ..identity import svid_client
    async with get_db_context() as db:
        peers = (await db.execute(
            select(models.PeerRegistry).where(_func.lower(models.PeerRegistry.name) == home.lower())
        )).scalars().all()
    peer = next((p for p in peers if (p.status or "").upper() == "ACTIVE"), None)
    if peer is None or not peer.base_url:
        logger.info(f"[CanaryRefill] no ACTIVE peer row for home '{home}'"); return None
    url = _to_internal_mtls_url(peer.base_url.rstrip("/")) + "/api/v1/federation/canary-refill"
    cfg: Dict[str, Any] = {"timeout": CANARY_REBALANCER_HTTP_TIMEOUT_SEC}
    if url.startswith("https://"):
        cc = svid_client.get_client_cert_config(target_url=url)
        if not cc:
            logger.info(f"[CanaryRefill] no mTLS client cert for {url}"); return None
        cfg.update(cc)
    else:
        lic = os.getenv("FEDERATION_LICENSE_KEY", "")
        if lic:
            cfg["headers"] = {"X-Federation-License": lic}
    try:
        async with _remote_client(**cfg) as c:
            r = await c.post(url, json={"dry_run": bool(dry_run), "max_fund": CANARY_REFILL_MAX_FUND})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[CanaryRefill] {home}: transport failed: {str(e)[:160]}"); return None
    if r.status_code == 404:
        logger.info(f"[CanaryRefill] {home} has no refill rail yet (pre-R5 image)"); return None
    if r.status_code != 200:
        logger.warning(f"[CanaryRefill] {home}: HTTP {r.status_code} {r.text[:160]}"); return None
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        logger.warning(f"[CanaryRefill] {home}: refused: {str(data)[:200]}"); return None
    if CANARY_REFILL_TOTAL is not None:
        try: CANARY_REFILL_TOTAL.labels(role="master", outcome="ok").inc()
        except Exception: pass
    return data


async def _rebalance_remote_senders(now: datetime.datetime) -> Dict[str, int]:
    out = {"remote_homes": 0, "remote_checked": 0, "remote_funded": 0, "remote_swept": 0, "remote_errors": 0,
           "remote_skipped_cooldown": 0}
    if not _REMOTE_SENDERS_ENABLED:
        return out
    for home in await _load_remote_homes():
        fed = await _refill_home_via_federation(home)
        if fed is not None:
            out["remote_homes"] += 1
            out["remote_checked"] += int(fed.get("checked") or 0)
            out["remote_funded"] += int(fed.get("funded") or 0)
            out["remote_swept"] += int(fed.get("swept") or 0)
            out["remote_errors"] += int(fed.get("errors") or 0)
            out["remote_skipped_cooldown"] += int(fed.get("skipped_cooldown") or 0)
            logger.info(f"[CanaryRebalancer] remote senders: {home} via federation "
                        f"checked={fed.get('checked')} funded={fed.get('funded')} swept={fed.get('swept')} errors={fed.get('errors')}"
                        f"{' PAUSED' if fed.get('paused') else ''}{' DISABLED' if fed.get('disabled') else ''}")
            continue
        creds = _remote_home_creds(home)
        if creds is None:
            continue
        logger.warning(f"[CanaryRebalancer] remote senders: {home} has no refill rail — using the PASSWORD leg "
                       f"(retire CANARY_REBALANCER_OP_CREDS once every home runs the R5 image)")
        if CANARY_REFILL_TOTAL is not None:
            try: CANARY_REFILL_TOTAL.labels(role="master", outcome="password_fallback").inc()
            except Exception: pass
        out["remote_homes"] += 1
        hk = creds["home"]
        token = await _get_admin_jwt(
            cache_key=f"remote:{hk}", login_url=f"{creds['base']}/api/v1/auth/login",
            email=creds["email"], password=creds["password"], verify_tls=creds["verify_tls"],
        )
        if not token:
            out["remote_errors"] += 1
            continue
        hdr = {"Authorization": f"Bearer {token}"}
        verify = get_httpx_verify() if creds["verify_tls"] else False
        try:
            async with _remote_client(timeout=CANARY_REBALANCER_HTTP_TIMEOUT_SEC, verify=verify) as c:
                r = await c.get(f"{creds['base']}/api/v1/admin/canary/status", headers=hdr)
            if r.status_code != 200:
                raise RuntimeError(f"canary status HTTP {r.status_code}")
            paths = (r.json() or {}).get("paths") or []
        except Exception as e:  # noqa: BLE001
            out["remote_errors"] += 1
            logger.warning(f"[CanaryRebalancer] remote senders: {hk} status failed: {str(e)[:160]}")
            continue
        senders: Dict[str, str] = {}
        for p in paths:
            if not isinstance(p, dict) or not p.get("is_active") or not p.get("sender_did"):
                continue
            fp = str(p.get("frame_pair") or "")
            senders.setdefault(str(p["sender_did"]), fp.split("->", 1)[0].strip().lower() if "->" in fp else "")
        for did, sender_frame in senders.items():
            out["remote_checked"] += 1
            last = _last_rebalance.get(did)
            if last is not None and (now - last).total_seconds() < CANARY_REBALANCER_MIN_INTERVAL_SEC:
                out["remote_skipped_cooldown"] += 1
                continue
            try:
                async with _remote_client(timeout=CANARY_REBALANCER_HTTP_TIMEOUT_SEC, verify=verify) as c:
                    d = await c.get(f"{creds['base']}/api/v1/admin/agents/{did}", headers=hdr)
                if d.status_code != 200:
                    raise RuntimeError(f"agent detail HTTP {d.status_code}")
                bal = Decimal(str((d.json() or {}).get("liquid_balance") or "0"))
            except Exception as e:  # noqa: BLE001
                out["remote_errors"] += 1
                _last_error[did] = "balance_query_failed"
                logger.warning(f"[CanaryRebalancer] remote sender {did} on {hk}: balance failed: {str(e)[:160]}")
                continue
            _last_balance[did] = (bal, now)
            if bal >= CANARY_REBALANCER_FLOOR_AVT:
                _last_error.pop(did, None)
                continue
            topup = CANARY_REBALANCER_TOPUP_BVT if sender_frame == "frame-c" else CANARY_REBALANCER_TOPUP_AVT
            ref = f"canary-rebalance-{did}-{int(time.time() * 1000)}-{secrets.token_hex(4)}"
            logger.info(f"[CanaryRebalancer] remote sender {did} on {hk} balance={bal} < floor={CANARY_REBALANCER_FLOOR_AVT}, funding {topup}")
            ok = False
            try:
                async with _remote_client(timeout=CANARY_REBALANCER_HTTP_TIMEOUT_SEC, verify=verify) as c:
                    f = await c.post(
                        f"{creds['base']}/api/v1/teg/treasury/fund-agent",
                        headers={**hdr, "Content-Type": "application/json"},
                        json={"target_agent_did": did, "amount": str(topup), "reason": "canary_rebalance", "reference_id": ref},
                    )
                ok = f.status_code == 200
                if not ok:
                    logger.warning(f"[CanaryRebalancer] remote sender {did} on {hk}: fund HTTP {f.status_code}: {f.text[:200]}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[CanaryRebalancer] remote sender {did} on {hk}: fund raised: {str(e)[:160]}")
            if ok:
                _last_rebalance[did] = now
                _last_error.pop(did, None)
                out["remote_funded"] += 1
                logger.info(f"[CanaryRebalancer] FUNDED remote sender {did} ({hk}) → 200 (ref={ref})")
                for metric, val in ((REBALANCE_FUNDED_TOTAL, 1), (REBALANCE_AVT_DISBURSED_TOTAL, float(topup))):
                    if metric is not None:
                        try:
                            metric.labels(home_kind=hk).inc(val)
                        except Exception:
                            pass
                await _emit_audit_event("CanaryRebalancerFunded", did, {
                    "agent_did": did, "home_kind": hk, "scope": "remote_sender", "registry_url": creds["base"],
                    "pre_balance": str(bal), "amount": str(topup), "floor": str(CANARY_REBALANCER_FLOOR_AVT),
                    "funded_at": now.isoformat(),
                }, idempotency_key=f"canary-fund-{ref}")
            else:
                out["remote_errors"] += 1
                _last_error[did] = "fund_failed"
                if REBALANCE_ERRORS_TOTAL is not None:
                    try:
                        REBALANCE_ERRORS_TOTAL.labels(home_kind=hk, reason="fund_failed").inc()
                    except Exception:
                        pass
    return out


async def _rebalance_cycle() -> None:
    """One rebalancer cycle."""
    if not CANARY_REBALANCER_ENABLED:
        return
    # §CANARYBIND 2026-08-08 (Commander): the rebalancer exists ONLY to top up
    # canary senders. If canaries are off it has nothing to serve, so it must
    # follow the canary state rather than needing a second switch somebody has
    # to remember. Two bindings, cheapest first:
    #
    #   1. STATIC — `CANARY_ENABLED=false` ⇒ never rebalance. Previously the
    #      rebalancer gated ONLY on its own flag, so turning canaries off left
    #      it cycling (measured on registry-a: `checked=16` per cycle with the
    #      fleet paused, and on frame-c `checked=5`).
    #   2. RUNTIME — the same `canary:fleet_paused` key the runner honours, so a
    #      single `POST /admin/canary/fleet/pause` quiets scheduler + judge +
    #      rebalancer within one tick, with NO container recreate. That is the
    #      lever that works when someone forgets.
    #
    # Checked per-cycle (not at startup) so pause/resume takes effect live.
    if not CANARY_ENABLED:
        return
    try:
        _r = await get_redis()
        if _r is not None and await _r.get(CANARY_FLEET_PAUSED_KEY):
            return
    except Exception:
        pass
    now = await _now_utc()
    checked = 0
    refunded = 0
    skipped_cooldown = 0
    errors = 0

    async with get_db_context() as db:
        try:
            # AAA+ 2026-05-17: Filter to canaries that are SENDERS in at least one
            # active path. Pure receivers (registered as canary_agents only so the
            # runner can resolve their DID) don't need rebalancing — they only
            # *receive* AVT from canary fires, never spend it. Including them here
            # caused 24 CanaryRebalancerErrored events/hour because receivers'
            # client_id/secret are placeholder/cross-registry and can never mint
            # a JWT on the local registry, so _check_balance always fails →
            # `reason=balance_query_failed, home_kind=unknown` spam.
            sender_ids_subq = (
                select(models.CanaryPath.sender_agent_id)
                .where(models.CanaryPath.is_active == True)
                .distinct()
            )
            result = await db.execute(
                select(models.CanaryAgent).where(
                    models.CanaryAgent.is_active == True,
                    models.CanaryAgent.id.in_(sender_ids_subq),
                )
            )
            canaries = list(result.scalars().all())
        except Exception as e:  # noqa: BLE001
            logger.error(f"[CanaryRebalancer] load canaries failed: {e}", exc_info=True)
            return

    avt_disbursed = Decimal(0)
    swept = 0
    avt_swept = Decimal(0)
    for canary in canaries:
        checked += 1
        home = _home_kind(canary.registry_url)
        last = _last_rebalance.get(canary.agent_did)
        if last is not None and (now - last).total_seconds() < CANARY_REBALANCER_MIN_INTERVAL_SEC:
            skipped_cooldown += 1
            if REBALANCE_SKIPPED_COOLDOWN_TOTAL is not None:
                try:
                    REBALANCE_SKIPPED_COOLDOWN_TOTAL.labels(home_kind=home).inc()
                except Exception:
                    pass
            continue

        balance = await _check_balance(canary)
        if balance is None:
            errors += 1
            _last_error[canary.agent_did] = "balance_query_failed"
            if REBALANCE_ERRORS_TOTAL is not None:
                try:
                    REBALANCE_ERRORS_TOTAL.labels(home_kind=home, reason="balance_query_failed").inc()
                except Exception:
                    pass
            # §2026-05-29: balance_query_failed is dominated by TRANSIENT registry→TEG
            # read/connect timeouts when the canary cross-frame churn saturates the sandbox
            # TEG's I/O concurrency — NOT an auth/proxy fault (secrets verified; idle the call
            # is 200 in <1s). Keep the Prometheus metric every cycle (above), but only emit the
            # durable CanaryRebalancerErrored EVENT after N CONSECUTIVE failures, then at most
            # once/interval per agent — a real outage still surfaces; transient blips no longer
            # flood the event/WS feed.
            _consec_balance_failures[canary.agent_did] = _consec_balance_failures.get(canary.agent_did, 0) + 1
            consec = _consec_balance_failures[canary.agent_did]
            last_emit = _last_balance_err_emit.get(canary.agent_did)
            if consec >= CANARY_REBALANCER_ERR_EMIT_AFTER and (
                last_emit is None
                or (now - last_emit).total_seconds() >= CANARY_REBALANCER_ERR_EMIT_INTERVAL_SEC
            ):
                _last_balance_err_emit[canary.agent_did] = now
                await _emit_audit_event(
                    "CanaryRebalancerErrored",
                    canary.agent_did,
                    {
                        "agent_did": canary.agent_did,
                        "home_kind": home,
                        "reason": "balance_query_failed",
                        "consecutive_failures": consec,
                        "registry_url": canary.registry_url,
                        "occurred_at": now.isoformat(),
                    },
                )
            continue
        # balance readable → clear any failure streak (covers healthy + below-floor paths)
        _consec_balance_failures.pop(canary.agent_did, None)
        _last_balance_err_emit.pop(canary.agent_did, None)
        if balance >= CANARY_REBALANCER_FLOOR_AVT:
            # Healthy — clear any stale error.
            _last_error.pop(canary.agent_did, None)
            _last_fund_err_emit.pop(canary.agent_did, None)
            # §CANARYONBOARD: above the ceiling, the excess goes back to THIS node's treasury (a canary homed here only)
            excess = sweep_amount(canary, balance)
            if excess > 0 and home == "self":
                if await _sweep_one(canary, balance, excess, now, actor="canary_rebalancer"):
                    swept += 1
                    avt_swept += excess
                else:
                    errors += 1
            continue

        # §2026-06-09: a below-floor sender whose registry_url maps to no known frame/op
        # (home=unknown) cannot be funded from here and is typically FX-reciprocity-funded
        # (e.g. an op not yet in CANARY_REBALANCER_OP_CREDS). Skip QUIETLY — no fund attempt,
        # only a throttled INFO (never the per-cycle CanaryRebalancerErrored spam).
        if home == "unknown":
            _last_error[canary.agent_did] = "unfundable_unknown_home"
            _le = _last_fund_err_emit.get(canary.agent_did)
            if _le is None or (now - _le).total_seconds() >= CANARY_REBALANCER_ERR_EMIT_INTERVAL_SEC:
                _last_fund_err_emit[canary.agent_did] = now
                logger.info(
                    f"[CanaryRebalancer] {canary.agent_did} below floor (balance={balance}) but "
                    f"home=unknown (url={canary.registry_url}); skipping — not in OP_CREDS / "
                    f"FX-reciprocity-funded"
                )
            continue

        _topup = _topup_for(canary)  # frame-aware (BVT for Frame-C ME-ops)
        logger.info(
            f"[CanaryRebalancer] {canary.agent_did} balance={balance} < floor={CANARY_REBALANCER_FLOOR_AVT}, "
            f"home={home}, funding {_topup}"
        )
        try:
            ok = await _refund_agent(canary, home)
        except Exception as _fe:  # noqa: BLE001 — one bad fund must never abort the whole cycle
            ok = False
            logger.warning(f"[CanaryRebalancer] refund {canary.agent_did} ({home}) raised: {_fe}")
        if ok:
            _last_rebalance[canary.agent_did] = now
            refunded += 1
            avt_disbursed += _topup
            _last_error.pop(canary.agent_did, None)
            _last_fund_err_emit.pop(canary.agent_did, None)
            if REBALANCE_FUNDED_TOTAL is not None:
                try:
                    REBALANCE_FUNDED_TOTAL.labels(home_kind=home).inc()
                except Exception:
                    pass
            if REBALANCE_AVT_DISBURSED_TOTAL is not None:
                try:
                    REBALANCE_AVT_DISBURSED_TOTAL.labels(home_kind=home).inc(float(_topup))
                except Exception:
                    pass
            await _emit_audit_event(
                "CanaryRebalancerFunded",
                canary.agent_did,
                {
                    "agent_did": canary.agent_did,
                    "home_kind": home,
                    "registry_url": canary.registry_url,
                    "pre_balance": str(balance),
                    "amount": str(_topup),
                    "floor": str(CANARY_REBALANCER_FLOOR_AVT),
                    "funded_at": now.isoformat(),
                },
                idempotency_key=f"canary-fund-{canary.agent_did}-{now.isoformat()}",
            )
        else:
            errors += 1
            _last_error[canary.agent_did] = "fund_failed"
            if REBALANCE_ERRORS_TOTAL is not None:
                try:
                    REBALANCE_ERRORS_TOTAL.labels(home_kind=home, reason="fund_failed").inc()
                except Exception:
                    pass
            # §2026-06-09: throttle the durable event (mirror balance_query_failed) so a
            # persistently-unfundable known-home canary can't flood the ES every cycle.
            _le = _last_fund_err_emit.get(canary.agent_did)
            if _le is None or (now - _le).total_seconds() >= CANARY_REBALANCER_ERR_EMIT_INTERVAL_SEC:
                _last_fund_err_emit[canary.agent_did] = now
                await _emit_audit_event(
                    "CanaryRebalancerErrored",
                    canary.agent_did,
                    {
                        "agent_did": canary.agent_did,
                        "home_kind": home,
                        "reason": "fund_failed",
                        "registry_url": canary.registry_url,
                        "pre_balance": str(balance),
                        "occurred_at": now.isoformat(),
                    },
                )

    # §FEDSYNCTRUTH-2 — the senders of remote-homed paths (never aborts the cycle).
    try:
        remote = await _rebalance_remote_senders(now)
    except Exception as _re:  # noqa: BLE001
        logger.warning(f"[CanaryRebalancer] remote-sender leg raised: {_re}")
        remote = {"remote_homes": 0, "remote_checked": 0, "remote_funded": 0, "remote_errors": 0,
                  "remote_skipped_cooldown": 0}
    _LAST_CYCLE_STATS.update(remote)

    if REBALANCE_CYCLE_TOTAL is not None:
        try:
            REBALANCE_CYCLE_TOTAL.labels(registry_id=os.getenv("REGISTRY_NAME", "registry-a")).inc()
        except Exception:
            pass

    _LAST_CYCLE_STATS["checked"] = checked
    _LAST_CYCLE_STATS["funded"] = refunded
    _LAST_CYCLE_STATS["skipped_cooldown"] = skipped_cooldown
    _LAST_CYCLE_STATS["errors"] = errors
    _LAST_CYCLE_STATS["avt_disbursed"] = str(avt_disbursed)
    _LAST_CYCLE_STATS["swept"] = swept
    _LAST_CYCLE_STATS["avt_swept"] = str(avt_swept)

    if checked or refunded or swept or errors or remote["remote_checked"] or remote["remote_errors"]:
        logger.info(
            f"[CanaryRebalancer] cycle: checked={checked} refunded={refunded} "
            f"skipped_cooldown={skipped_cooldown} errors={errors} avt={avt_disbursed} swept={swept} avt_swept={avt_swept} | remote senders: "
            f"homes={remote['remote_homes']} checked={remote['remote_checked']} funded={remote['remote_funded']} "
            f"swept={remote.get('remote_swept', 0)} errors={remote['remote_errors']} cooldown={remote['remote_skipped_cooldown']}"
        )


class CanaryRebalancer(BackgroundWorker):
    """Leader-elected canary rebalancer (§pass27 Phase 2: BackgroundWorker)."""

    worker_id = "canary_rebalancer"
    leader_key = CANARY_REBALANCER_LEADER_KEY
    interval_sec = CANARY_REBALANCER_INTERVAL_SEC
    cold_start_delay_sec = 10  # Let the runner+judge warm up first.

    def _should_run(self) -> bool:
        return CANARY_REBALANCER_ENABLED

    async def _cycle_once(self) -> None:
        await _rebalance_cycle()
        self._stats = dict(_LAST_CYCLE_STATS)


_rebalancer: Optional[CanaryRebalancer] = None


async def start_canary_rebalancer() -> None:
    global _rebalancer
    if _rebalancer is None:
        _rebalancer = CanaryRebalancer()
    await _rebalancer.start()


async def stop_canary_rebalancer() -> None:
    global _rebalancer
    if _rebalancer is not None:
        await _rebalancer.stop()


def get_canary_rebalancer() -> Optional[CanaryRebalancer]:
    """Accessor for admin endpoints (returns None pre-start)."""
    return _rebalancer


def get_live_agent_state() -> Dict[str, Dict[str, Any]]:
    """Per-agent live state for the admin/status endpoint.

    Returns a {did: {balance, balance_checked_at, last_funded_at,
    last_error, state}} map. State is derived:
      - 'errored'      → most-recent error is set
      - 'cooldown'     → last fund within MIN_INTERVAL_SEC
      - 'under_floor'  → balance known and < FLOOR
      - 'healthy'      → otherwise
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    out: Dict[str, Dict[str, Any]] = {}
    dids = (
        set(_last_balance.keys())
        | set(_last_rebalance.keys())
        | set(_last_error.keys())
    )
    for did in dids:
        bal_pair = _last_balance.get(did)
        balance = bal_pair[0] if bal_pair else None
        balance_checked_at = bal_pair[1] if bal_pair else None
        last_funded = _last_rebalance.get(did)
        err = _last_error.get(did)
        # Derive state.
        state = "healthy"
        if err:
            state = "errored"
        elif last_funded and (now - last_funded).total_seconds() < CANARY_REBALANCER_MIN_INTERVAL_SEC:
            state = "cooldown"
        elif balance is not None and balance < CANARY_REBALANCER_FLOOR_AVT:
            state = "under_floor"
        out[did] = {
            "balance": str(balance) if balance is not None else None,
            "balance_checked_iso": balance_checked_at.isoformat() if balance_checked_at else None,
            "last_funded_iso": last_funded.isoformat() if last_funded else None,
            "next_eligible_iso": (
                (last_funded + datetime.timedelta(seconds=CANARY_REBALANCER_MIN_INTERVAL_SEC)).isoformat()
                if last_funded else None
            ),
            "last_error": err,
            "state": state,
        }
    return out


def get_runtime_config() -> Dict[str, Any]:
    """Read-only config snapshot for the admin status endpoint."""
    return {
        "enabled": CANARY_REBALANCER_ENABLED,
        "interval_sec": CANARY_REBALANCER_INTERVAL_SEC,
        "floor_avt": str(CANARY_REBALANCER_FLOOR_AVT),
        "topup_avt": str(CANARY_REBALANCER_TOPUP_AVT),
        "ceiling_avt": str(CANARY_REBALANCER_CEILING_AVT),
        "min_interval_sec": CANARY_REBALANCER_MIN_INTERVAL_SEC,
        "op_creds_count": len(CANARY_REBALANCER_OP_CREDS),
    }
