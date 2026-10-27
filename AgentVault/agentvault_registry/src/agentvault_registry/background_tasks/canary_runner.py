"""Canary runner — fires periodic synthetic-transaction transfers across the canary path matrix.

Runs as a leader-elected periodic task. Each tick:
  1. Reads active rows from canary_paths (registry-a DB).
  2. For each path whose interval_sec has elapsed since last fire: fires a transfer.
  3. Writes a canary_test_results row (outcome='fired') + a Redis state hash
     (canary:<test_id>) for the validator reactor (Phase 4) to fill in.

Auth: each canary agent has its own client_id/client_secret in canary_agents.
Runner mints a fresh agent JWT via POST /api/v1/auth/agent/token on the
sender's home registry. JWTs are cached in-memory for 30 min.

Transfer endpoints:
  - backend='intra': POST {sender_registry_url}/api/v1/teg/transfer
  - backend='async'|'2pc': POST {sender_registry_url}/api/v1/teg/cross-registry-transfer?backend=...

Correlation ID: every fire passes `message="canary-<test_id>"` so downstream
events carry the prefix and the validator can filter by it.

Env config (see Phase 0 of canary system plan):
  CANARY_ENABLED=true|false                     # global kill switch (default true)
  CANARY_RUNNER_INTERVAL_SEC=5                  # cycle tick (how often to check next-due)
  CANARY_RUNNER_LEADER_KEY=canary_runner        # Redis leader-election key
  CANARY_RUNNER_HTTP_TIMEOUT_SEC=15

Phase 4 (reactor_canary_validator) and Phase 5 (canary_judge) consume the
state this runner produces. Without them the runner just records 'fired'
rows that never resolve — useful as a smoke test for the matrix itself.
"""
import asyncio
import datetime
import json
from pathlib import Path
import logging
import os
import ssl
import uuid
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update as sa_update

from .. import models
from ..database import get_db_context
from .leader import try_acquire_leadership, get_redis
from . import vitals as _vitals

logger = logging.getLogger(__name__)


CANARY_ENABLED = os.environ.get("CANARY_ENABLED", "true").lower() == "true"
# Per-registry runner gate. Default OFF — only registry-a (which hosts canary_paths)
# should start the runner. Operators + frame-b-registry stay no-op.
CANARY_RUNNER_ENABLED = os.environ.get("CANARY_RUNNER_ENABLED", "false").lower() == "true"

# §V0045 Canary Cockpit — scheduling-topology mode:
#   local    (default) — self-schedules its own canary_paths (standalone / third-party
#              operators / pre-cockpit behavior; fully autonomous).
#   master   — the cluster cockpit (registry-a): schedules its OWN local paths AND
#              dispatches remote fires (canary_remote_paths) to each path's HOME
#              registry over the federation mTLS channel (/api/v1/federation/canary-fire).
#   follower — fleet member under the cockpit: NEVER self-schedules; fires only on
#              master dispatch (its canary agents/creds/SVIDs stay home).
CANARY_RUNNER_MODE = os.environ.get("CANARY_RUNNER_MODE", "local").strip().lower()
# One flag on the master silences ALL scheduling (local fires + remote dispatches).
# Redis-only BY DESIGN: if Redis flushes, canaries RESUME (fail-open-to-monitoring).
CANARY_FLEET_PAUSED_KEY = "canary:fleet_paused"
CANARY_DISPATCH_TIMEOUT_SEC = float(os.environ.get("CANARY_DISPATCH_TIMEOUT_SEC", "30"))
CANARY_RUNNER_INTERVAL_SEC = int(os.environ.get("CANARY_RUNNER_INTERVAL_SEC", "5"))
CANARY_RUNNER_LEADER_KEY = os.environ.get("CANARY_RUNNER_LEADER_KEY", "canary_runner")
CANARY_RUNNER_HTTP_TIMEOUT_SEC = int(os.environ.get("CANARY_RUNNER_HTTP_TIMEOUT_SEC", "15"))

# Redis state TTL for in-flight test (validator + judge consume this)
CANARY_REDIS_STATE_TTL_SEC = int(os.environ.get("CANARY_REDIS_STATE_TTL_SEC", "300"))

# §pass21 (2026-05-16) — route canary transfers via mTLS-terminating nginx-federation
# sidecars so SPIRE SVIDs get exercised by synthetic traffic. Sandbox-only by default
# (CANARY_USE_MTLS=true on registry-test{,-b}); prod registries leave this false.
# Auth model is transport-only mTLS — the Bearer agent JWT path is unchanged. Falls
# back to bearer-token path on mTLS 5xx / connection error, counted into
# canary_mtls_fallback_total{path_id,reason}. 4xx is NOT retried (real validation error).
CANARY_USE_MTLS = os.environ.get("CANARY_USE_MTLS", "false").lower() == "true"

# Optional override of the default sandbox URL map (host_or_url → mTLS proxy URL).
# JSON-encoded dict. Empty/unset → hardcoded map below.
CANARY_MTLS_URL_MAP = os.environ.get("CANARY_MTLS_URL_MAP", "").strip()


# Canary sender.registry_url → mTLS-terminating nginx sidecar URL.
# Covers both sandbox tier (5 senders: 2 mainframes + 3 cloud-ops, trust domain
# sandbox-a.test) and prod tier (10 senders: 2 mainframes + 8 cloud-ops, split
# across trust domains agentvault.com + frame-b.theprotocol.cloud — SPIRE
# federation makes the handshake mutually trusted). Every entry's RHS hostname
# matches a SAN on the receiver nginx-federation SVID (verified §15 prod
# rollout — handshakes to all 10 prod targets returned 404 from nginx app
# logic, not TLS error, proving TLS terminated cleanly).
# An unmapped sender skips the mTLS attempt and uses bearer-token transparently.
_CANARY_MTLS_MAP_DEFAULT = "canary_mtls_map.mainnet-2026.json"
_CANARY_MTLS_MAP_FILE = os.environ.get("CANARY_MTLS_MAP_FILE", _CANARY_MTLS_MAP_DEFAULT).strip()
# §REDERIVE (2026-09-12) — AN EXPLICITLY NAMED MAP THAT IS NOT THERE IS A DIFFERENT FACT FROM THE
# DEFAULT ONE BEING ABSENT, AND THE TWO MUST NOT SHARE A LOG LINE. Measured on EU and ASIA while
# re-deriving the reprovisioning ledger: CANARY_MTLS_MAP_FILE names
# `canary_mtls_map.frame-local.json`, nothing in the standup writes it, and the path is BAKED into
# the image rather than mounted — so the frame ASKED for mTLS and every sender silently falls back
# to bearer. The old code called that a warning, in the same sentence it uses for "this node just
# doesn't ship the default map", which is the documented and harmless case. One sentence, two
# states, different fixes (§29e). Inert today only because the canaries are off.
_CANARY_MTLS_MAP_EXPLICIT = _CANARY_MTLS_MAP_FILE != _CANARY_MTLS_MAP_DEFAULT


def _load_canary_mtls_map() -> Dict[str, str]:
    """The dial-alias -> mTLS-URL map is DATA about one network, not code (§BATCH3 item 1):
    it lives in config/canary_mtls_map.mainnet-2026.json (shipped to /app/config), or in the
    file CANARY_MTLS_MAP_FILE names. No file => {} and a WARNING: every sender is then unmapped
    and the runner uses bearer transparently, which is the documented fallback, never a crash."""
    from ..core.network_profile import find_config_file
    try:
        path = Path(_CANARY_MTLS_MAP_FILE) if "/" in _CANARY_MTLS_MAP_FILE else find_config_file(_CANARY_MTLS_MAP_FILE)
        if not path or not path.is_file():
            if _CANARY_MTLS_MAP_EXPLICIT:
                logger.error(
                    f"[CanaryRunner] CANARY_MTLS_MAP_FILE names {_CANARY_MTLS_MAP_FILE} and no such file exists. "
                    "This node was deliberately configured to use an mTLS map, so every canary sender falling "
                    "back to bearer is a MISCONFIGURATION, not the documented default. Write the map at standup "
                    "(it is data about one network) or unset CANARY_MTLS_MAP_FILE to accept the bearer fallback.")
            else:
                logger.warning(f"[CanaryRunner] mTLS map file not found ({_CANARY_MTLS_MAP_FILE}); every sender unmapped -> bearer")
            return {}
        data = json.loads(path.read_text())
        loaded = {str(k): str(v) for k, v in data.items() if isinstance(k, str) and not k.startswith("_")}
        logger.info(f"[CanaryRunner] mTLS map: {len(loaded)} entries from {path}")
        return loaded
    except Exception as _e:  # noqa: BLE001
        logger.warning(f"[CanaryRunner] mTLS map load failed ({_CANARY_MTLS_MAP_FILE}): {_e}; every sender unmapped -> bearer")
        return {}


_CANARY_MTLS_MAP: Dict[str, str] = _load_canary_mtls_map()

try:
    if CANARY_MTLS_URL_MAP:
        _override = json.loads(CANARY_MTLS_URL_MAP)
        if isinstance(_override, dict):
            _CANARY_MTLS_MAP.update(_override)
except Exception as _e:  # noqa: BLE001
    logger.warning(f"[CanaryRunner] CANARY_MTLS_URL_MAP parse failed: {_e}")


# Prometheus counter for mTLS → bearer fallbacks. Optional dependency.
try:
    from prometheus_client import Counter as _PromCounter
    from prometheus_client import Histogram as _PromHistogram

    canary_mtls_fallback_total = _PromCounter(
        "canary_mtls_fallback_total",
        "Canary transfers that fell back from mTLS path to bearer-token path",
        ["path_id", "reason"],
    )
    canary_mtls_attempt_total = _PromCounter(
        "canary_mtls_attempt_total",
        "Canary transfers attempted over the mTLS path",
        ["path_id", "outcome"],
    )
    # §pass30 — Pattern A IRONHAND mTLS canary counters
    canary_ironhand_attempt_total = _PromCounter(
        "canary_ironhand_attempt_total",
        "IRONHAND canary fire attempts (per-agent SVID via Workload API)",
        ["path_id", "outcome"],
    )
    canary_ironhand_fail_total = _PromCounter(
        "canary_ironhand_fail_total",
        "IRONHAND canary fire failures by reason",
        ["path_id", "reason"],
    )
    canary_ironhand_revocation_propagation_seconds = _PromHistogram(
        "canary_ironhand_revocation_propagation_seconds",
        "Time from /admin/agents/{did}/revoke API call to /revoked-identities reflecting",
        buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
    )
except Exception:  # noqa: BLE001
    canary_mtls_fallback_total = None
    canary_mtls_attempt_total = None
    canary_ironhand_attempt_total = None
    canary_ironhand_fail_total = None
    canary_ironhand_revocation_propagation_seconds = None


def _mtls_url_for(registry_url: str, suffix: str) -> Optional[str]:
    """Return the mTLS-proxied URL for a canary sender, or None if no mapping exists.

    `suffix` is the path the canary wants to hit, e.g. `/api/v1/teg/transfer`
    or `/api/v1/teg/cross-registry-transfer?backend=2pc`. Keeps cloud-op
    sender URLs unmapped so they fall through to the bearer-token path.
    """
    base = _CANARY_MTLS_MAP.get(registry_url)
    if not base:
        return None
    return f"{base}{suffix}"

# In-memory JWT cache: agent_did → (jwt, expires_at)
_jwt_cache: Dict[str, Tuple[str, datetime.datetime]] = {}

# In-memory last-fire timestamp per path_id (rebuilt on leader-takeover from Redis)
_last_fire: Dict[int, datetime.datetime] = {}


async def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def _get_agent_jwt(canary: models.CanaryAgent) -> str:
    """Get a (cached) agent JWT minted from the sender's home registry."""
    cached = _jwt_cache.get(canary.agent_did)
    now = await _now_utc()
    if cached and cached[1] > now + datetime.timedelta(minutes=5):
        return cached[0]

    async with httpx.AsyncClient(timeout=CANARY_RUNNER_HTTP_TIMEOUT_SEC) as client:
        r = await client.post(
            f"{canary.registry_url}/api/v1/auth/agent/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=f"username={canary.client_id}&password={canary.client_secret}",
        )
    if r.status_code != 200:
        raise RuntimeError(
            f"agent token mint failed for {canary.agent_did} via {canary.registry_url}: "
            f"HTTP {r.status_code} body={r.text[:200]}"
        )
    data = r.json()
    jwt = data["access_token"]
    # Cache for 30 min (agent JWTs last longer; we re-mint defensively)
    _jwt_cache[canary.agent_did] = (jwt, now + datetime.timedelta(minutes=30))
    return jwt


async def _fire_transfer(
    path: models.CanaryPath,
    sender: models.CanaryAgent,
    receiver: models.CanaryAgent,
    test_id: Optional[str] = None,
) -> dict:
    """Fire one canary transfer. Returns a dict with timing + result fields.

    §V0045 Cockpit: `test_id` may be injected by the master's dispatch (it is the
    end-to-end idempotency key); locally-scheduled fires mint their own as before.
    """
    test_id = test_id or f"canary-{path.path_id}-{uuid.uuid4().hex[:10]}"
    correlation_id = test_id  # message=test_id (already prefixed with 'canary-')
    fired_at = await _now_utc()

    # 2026-05-19 state-hash race fix: pre-INSERT canary_test_results row BEFORE pre-HSET.
    # With the row pre-existing, the judge's UPDATE always finds it, so a PASSED verdict
    # isn't silently lost to a 0-row UPDATE when judge runs while runner is still in
    # flight. Companion: _record_fire is now a conditional UPDATE (not INSERT) and no
    # longer recreates canary:<test_id> hash (which was the BACKLOG_2026-05-17 race).
    try:
        async with get_db_context() as _pre_db:
            _pre_db.add(models.CanaryTestResult(
                test_id=test_id,
                path_id=path.id,
                fired_at=fired_at,
                backend=path.backend,
                sender_did=sender.agent_did,
                receiver_did=receiver.agent_did,
                amount=path.amount,
                outcome="fired",
            ))
            await _pre_db.commit()
    except Exception as e:
        logger.warning(f"[CanaryRunner] pre-fire DB insert failed for {test_id}: {e}")

    # 2026-05-04: Pre-create canary state hash + memo reverse-index BEFORE the HTTP call.
    # Closes the WS race where validator catches CrossFrameTransferInitiated on the
    # ES WS (often within ~50ms of emit) before _record_fire runs (~150ms after HTTP
    # response). Without this, validator would silently skip — `canary_xfer:<tid>`
    # didn't exist yet. Now validator can fall back to `memo` lookup, where memo == test_id.
    from .leader import get_redis as _get_redis
    pre_redis = await _get_redis()
    if pre_redis is not None:
        try:
            await pre_redis.hset(
                f"canary:{test_id}",
                mapping={
                    "test_id": test_id,
                    "path_id": str(path.id),
                    "path_human": path.path_id,
                    "backend": path.backend,
                    "sender_did": sender.agent_did,
                    "receiver_did": receiver.agent_did,
                    "amount": str(path.amount),
                    "fired_iso": fired_at.isoformat(),
                    "expected_intra_settled": "true" if path.backend == "intra" else "false",
                    "expected_cf_initiated": "false" if path.backend == "intra" else "true",
                    "expected_cf_settled_remote": "false" if path.backend == "intra" else "true",
                    "status": "firing",
                },
            )
            await pre_redis.expire(f"canary:{test_id}", CANARY_REDIS_STATE_TTL_SEC)
            # Pre-set correlation reverse-index so memo-based lookup works
            await pre_redis.set(
                f"canary_corr:{test_id}", test_id, ex=CANARY_REDIS_STATE_TTL_SEC
            )
        except Exception as e:
            logger.warning(f"[CanaryRunner] pre-fire Redis state failed for {test_id}: {e}")

    try:
        sender_jwt = await _get_agent_jwt(sender)
    except Exception as e:
        return {
            "test_id": test_id,
            "fired_at": fired_at,
            "http_status": None,
            "http_latency_ms": None,
            "transfer_id": None,
            "failure_type": "auth_failed",
            "failure_detail": {"error": str(e)[:300]},
        }

    if path.backend == "intra":
        suffix = "/api/v1/teg/transfer"
        body = {
            "receiver_agent_id": receiver.agent_did,
            "amount": str(path.amount),
            "message": correlation_id,
        }
    elif path.backend == "smartsend":
        # f060 (2026-06-12): unified smart-send canary — the registry derives the
        # route (local/2pc/async/fx) itself; response carries top-level transfer_id
        # + status like the rails, so parsing/judging below is unchanged. FX-class
        # smartsend paths keep notes startswith "fx" to ride the FX judge.
        suffix = "/api/v1/teg/send"
        body = {
            "receiver_did": receiver.agent_did,
            "amount": str(path.amount),
            "message": correlation_id,
        }
    else:
        suffix = f"/api/v1/teg/cross-registry-transfer?backend={path.backend}"
        body = {
            "receiver_did": receiver.agent_did,
            "amount": str(path.amount),
            "message": correlation_id,
        }
    bearer_url = f"{sender.registry_url}{suffix}"

    # §pass30 — Pattern A IRONHAND mTLS dispatch.
    # Delegates the fire to a per-agent workload container that owns its own
    # SPIRE SVID (Docker-label attestation). Runner XADDs a fire command to
    # a Redis Stream (durable, replayed on subscriber attach), awaits result
    # via SET key. FAIL LOUDLY per §pass25-b — no bearer fallback.
    #
    # §pass31 Phase 3 (2026-05-17) — replaced PUBLISH (fire-and-forget) with
    # XADD/XREADGROUP. Pubsub messages were lost during container startup
    # before subscriber attach (~30s window), causing `ironhand_no_response`
    # bursts on each container restart. Streams persist the message until
    # consumed + provide exactly-once semantics via consumer groups.
    transport = getattr(path, "transport", None) or "bearer"
    if transport == "ironhand_mtls":
        fire_stream = f"canary_ironhand_fire:{path.path_id}"
        result_key = f"canary_ironhand_result:{test_id}"
        # §pass31 Phase 4 — explicit endpoint + body in payload so the workload
        # can fire intra OR cross-frame uniformly. Backend chooses body shape:
        #   intra        → /api/v1/teg/transfer + receiver_agent_id
        #   smartsend    → /api/v1/teg/send + receiver_did (f060 — registry derives the route)
        #   async / 2pc  → /api/v1/teg/cross-registry-transfer?backend=X + receiver_did
        if path.backend == "intra":
            endpoint_path = "/api/v1/teg/transfer"
            fire_body: dict = {
                "receiver_agent_id": receiver.agent_did,
                "amount": str(path.amount),
                "message": correlation_id,
            }
        elif path.backend == "smartsend":
            endpoint_path = "/api/v1/teg/send"
            fire_body = {
                "receiver_did": receiver.agent_did,
                "amount": str(path.amount),
                "message": correlation_id,
            }
        else:
            endpoint_path = f"/api/v1/teg/cross-registry-transfer?backend={path.backend}"
            fire_body = {
                "receiver_did": receiver.agent_did,
                "amount": str(path.amount),
                "message": correlation_id,
            }
        payload = {
            "test_id": test_id,
            "endpoint": endpoint_path,
            "body": fire_body,
            # Legacy flat fields preserved for backward-compat with older
            # workload images that don't read endpoint/body.
            "receiver_did": receiver.agent_did,
            "amount": str(path.amount),
            "memo": correlation_id,
        }
        redis_cli = await _get_redis()
        if redis_cli is None:
            if canary_ironhand_fail_total is not None:
                canary_ironhand_fail_total.labels(
                    path_id=path.path_id, reason="ironhand_redis_unavailable"
                ).inc()
            return {
                "test_id": test_id,
                "fired_at": fired_at,
                "http_status": None,
                "http_latency_ms": None,
                "transfer_id": None,
                "transport": "ironhand_mtls",
                "failure_type": "ironhand_redis_unavailable",
                "failure_detail": {"reason": "runner-side Redis client is None"},
            }

        try:
            # Ensure the consumer group exists BEFORE the first XADD. Without this,
            # the consumer container's XGROUP CREATE with id="$" only picks up
            # messages added AFTER its group creation — pre-existing messages are
            # orphaned. By creating here first (idempotent BUSYGROUP), the group
            # exists from the moment of the very first XADD on this stream, and
            # ANY consumer attaching later will pick up every queued message.
            try:
                await redis_cli.xgroup_create(
                    name=fire_stream,
                    groupname="canary_runner_group",
                    id="$",
                    mkstream=True,
                )
            except Exception as ge:
                if "BUSYGROUP" not in str(ge):
                    logger.debug(f"[CanaryRunner] xgroup_create non-fatal: {ge}")
            # XADD with MAXLEN cap. approximate=True (~) trims efficiently.
            # data field is JSON-serialised payload.
            await redis_cli.xadd(
                fire_stream,
                {"data": json.dumps(payload)},
                maxlen=100,
                approximate=True,
            )
        except Exception as e:
            if canary_ironhand_fail_total is not None:
                canary_ironhand_fail_total.labels(
                    path_id=path.path_id, reason="ironhand_publish"
                ).inc()
            return {
                "test_id": test_id,
                "fired_at": fired_at,
                "http_status": None,
                "http_latency_ms": None,
                "transfer_id": None,
                "transport": "ironhand_mtls",
                "failure_type": "ironhand_publish",
                "failure_detail": {"reason": str(e)[:200]},
            }

        # Poll for result. 20s envelope = 15s exec budget + 5s slack.
        deadline = fired_at.timestamp() + 20
        result_raw = None
        while (await _now_utc()).timestamp() < deadline:
            try:
                result_raw = await redis_cli.get(result_key)
            except Exception:
                result_raw = None
            if result_raw:
                break
            await asyncio.sleep(0.5)

        if not result_raw:
            if canary_ironhand_fail_total is not None:
                canary_ironhand_fail_total.labels(
                    path_id=path.path_id, reason="ironhand_no_response"
                ).inc()
            return {
                "test_id": test_id,
                "fired_at": fired_at,
                "http_status": None,
                "http_latency_ms": None,
                "transfer_id": None,
                "transport": "ironhand_mtls",
                "failure_type": "ironhand_no_response",
                "failure_detail": {
                    "reason": "workload container did not publish result within 20s",
                    "fire_stream": fire_stream,
                },
            }

        try:
            await redis_cli.delete(result_key)
        except Exception:
            pass

        try:
            wc_result = json.loads(result_raw)
        except Exception as e:
            if canary_ironhand_fail_total is not None:
                canary_ironhand_fail_total.labels(
                    path_id=path.path_id, reason="ironhand_invalid_result"
                ).inc()
            return {
                "test_id": test_id,
                "fired_at": fired_at,
                "http_status": None,
                "http_latency_ms": None,
                "transfer_id": None,
                "transport": "ironhand_mtls",
                "failure_type": "ironhand_invalid_result",
                "failure_detail": {"reason": str(e)[:200]},
            }

        # Increment counters
        if canary_ironhand_attempt_total is not None:
            status = wc_result.get("http_status")
            outcome = "ok" if status and status < 400 else (
                f"http_{status}" if status else "fail"
            )
            canary_ironhand_attempt_total.labels(
                path_id=path.path_id, outcome=outcome
            ).inc()
        if wc_result.get("failure_type") and canary_ironhand_fail_total is not None:
            canary_ironhand_fail_total.labels(
                path_id=path.path_id,
                reason=wc_result["failure_type"],
            ).inc()

        return {
            "test_id": test_id,
            "fired_at": fired_at,
            "http_status": wc_result.get("http_status"),
            "http_latency_ms": wc_result.get("http_latency_ms"),
            "transfer_id": wc_result.get("transfer_id"),
            "response_body": wc_result.get("response_body"),
            "transport": "ironhand_mtls",
            "failure_type": wc_result.get("failure_type"),
            "failure_detail": wc_result.get("failure_detail"),
        }

    # §pass21 (2026-05-16) — optional mTLS-terminated path attempt before bearer.
    # SVID cert exercises SPIRE end-to-end every fire. Falls back on 5xx /
    # connection error; 4xx is a real validation error and must not be retried.
    mtls_attempted = False
    mtls_failure_reason: Optional[str] = None
    if CANARY_USE_MTLS:
        mtls_url = _mtls_url_for(sender.registry_url, suffix)
        if mtls_url:
            try:
                from ..identity.svid_client import svid_client

                cert_config = svid_client.get_client_cert_config(target_url=mtls_url)
                if cert_config is None:
                    mtls_failure_reason = "no_svid"
                else:
                    mtls_attempted = True
                    t_mtls_start = (await _now_utc()).timestamp()
                    async with httpx.AsyncClient(
                        timeout=CANARY_RUNNER_HTTP_TIMEOUT_SEC, **cert_config
                    ) as mclient:
                        mr = await mclient.post(
                            mtls_url,
                            headers={
                                "Authorization": f"Bearer {sender_jwt}",
                                "Content-Type": "application/json",
                            },
                            json=body,
                        )
                    if mr.status_code < 500:
                        # Success or deliberate 4xx — surface as the final result.
                        if canary_mtls_attempt_total is not None:
                            canary_mtls_attempt_total.labels(
                                path_id=str(path.id),
                                outcome="ok" if mr.status_code < 400 else f"http_{mr.status_code}",
                            ).inc()
                        t_mtls_end = (await _now_utc()).timestamp()
                        try:
                            data = mr.json()
                        except Exception:
                            data = {"raw": mr.text[:200]}
                        transfer_id = (
                            data.get("transaction_id")
                            or data.get("transfer_id")
                            or (data.get("data") or {}).get("transaction_id")
                        )
                        out = {
                            "test_id": test_id,
                            "fired_at": fired_at,
                            "http_status": mr.status_code,
                            "http_latency_ms": int((t_mtls_end - t_mtls_start) * 1000),
                            "transfer_id": transfer_id,
                            "response_body": data,
                            "transport": "mtls",
                        }
                        if mr.status_code >= 400:
                            out["failure_type"] = "http_error"
                            out["failure_detail"] = {"status": mr.status_code, "body": data}
                        return out
                    mtls_failure_reason = f"http_{mr.status_code}"
            except (httpx.ConnectError, httpx.ReadTimeout, ssl.SSLError) as exc:
                mtls_failure_reason = type(exc).__name__
            except Exception as exc:  # noqa: BLE001
                mtls_failure_reason = type(exc).__name__
                logger.warning(
                    f"[CanaryRunner] mTLS path crashed for {path.path_id} "
                    f"test_id={test_id}: {exc}"
                )

    if mtls_attempted and mtls_failure_reason:
        if canary_mtls_fallback_total is not None:
            canary_mtls_fallback_total.labels(
                path_id=str(path.id), reason=mtls_failure_reason
            ).inc()
        logger.warning(
            f"[CanaryRunner] mTLS fallback path={path.path_id} reason={mtls_failure_reason}"
        )

    t_start = fired_at.timestamp()
    try:
        async with httpx.AsyncClient(timeout=CANARY_RUNNER_HTTP_TIMEOUT_SEC) as client:
            r = await client.post(
                bearer_url,
                headers={
                    "Authorization": f"Bearer {sender_jwt}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        t_end = (await _now_utc()).timestamp()
        http_latency_ms = int((t_end - t_start) * 1000)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:200]}
        transfer_id = (
            data.get("transaction_id")
            or data.get("transfer_id")
            or (data.get("data") or {}).get("transaction_id")
        )
        out = {
            "test_id": test_id,
            "fired_at": fired_at,
            "http_status": r.status_code,
            "http_latency_ms": http_latency_ms,
            "transfer_id": transfer_id,
            "response_body": data,
            "transport": "mtls_fallback_bearer" if mtls_attempted else "bearer",
        }
        if r.status_code >= 400:
            out["failure_type"] = "http_error"
            out["failure_detail"] = {"status": r.status_code, "body": data}
        return out
    except httpx.TimeoutException:
        return {
            "test_id": test_id,
            "fired_at": fired_at,
            "http_status": None,
            "http_latency_ms": None,
            "transfer_id": None,
            "failure_type": "timeout",
            "failure_detail": {"timeout_sec": CANARY_RUNNER_HTTP_TIMEOUT_SEC},
        }
    except Exception as e:
        return {
            "test_id": test_id,
            "fired_at": fired_at,
            "http_status": None,
            "http_latency_ms": None,
            "transfer_id": None,
            "failure_type": "exception",
            "failure_detail": {"error": str(e)[:300]},
        }


async def _record_fire(
    db, path: models.CanaryPath, sender: models.CanaryAgent, receiver: models.CanaryAgent, result: dict
) -> None:
    """UPDATE pre-INSERTed canary_test_results row with HTTP results + write reverse-index.

    2026-05-19 race fix: the row was INSERTed at fire-time in `_fire_transfer` so the
    judge can always find it. We UPDATE here with HTTP results, conditional on
    `outcome='fired'` so we never overwrite a row the judge has already finalized.

    We deliberately do NOT recreate the `canary:<test_id>` hash here — that was the
    BACKLOG_2026-05-17 race source. The pre-HSET in `_fire_transfer` is the canonical
    state hash; we only write the `canary_xfer:<transfer_id>` reverse-index here, plus
    the Phase 7.6 intra self-stamp guarded by `EXISTS` so it never recreates a hash
    the judge has already swept.
    """
    test_id = result["test_id"]

    try:
        await db.execute(
            sa_update(models.CanaryTestResult)
            .where(models.CanaryTestResult.test_id == test_id)
            .where(models.CanaryTestResult.outcome == "fired")
            .values(
                transfer_id=result.get("transfer_id"),
                http_status=result.get("http_status"),
                http_latency_ms=result.get("http_latency_ms"),
                failure_type=result.get("failure_type"),
                failure_detail=result.get("failure_detail"),
                transport=result.get("transport"),
            )
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"[CanaryRunner] DB update failed for {test_id}: {e}")

    redis = await get_redis()
    if redis is None:
        return
    try:
        tid = result.get("transfer_id")
        if tid:
            await redis.set(f"canary_xfer:{tid}", test_id, ex=CANARY_REDIS_STATE_TTL_SEC)

        # Phase 7.6 (2026-05-04, preserved): intra self-stamp. /teg/transfer is
        # synchronous — registry returns 200 ONLY after TEG commits + emits
        # TokensTransferred. The HTTP 200 + tx_id IS the proof. Only stamp if
        # the hash still exists (judge hasn't already finalized + swept it).
        if path.backend == "intra" and result.get("http_status") == 200 and tid:
            key = f"canary:{test_id}"
            if await redis.exists(key):
                now_iso = (await _now_utc()).isoformat()
                await redis.hset(
                    key,
                    mapping={
                        "tokens_xfer_seen_iso": now_iso,
                        "fee_collected_seen_iso": now_iso,
                        "transfer_id": tid,
                        "http_status": str(result.get("http_status")),
                        "status": "fired",
                    },
                )

        # §FX (2026-06-03): cross-currency FX-swap canary self-stamp.
        # A currency-mismatched /teg/cross-registry-transfer auto-routes through the
        # reserve-mediated FX booth, which is SYNCHRONOUS + source-orchestrated — the
        # HTTP response (status=completed + credited_amount) IS the settlement proof,
        # exactly like intra /teg/transfer. The FxSwapSettled audit event is emitted to
        # the SENDER frame's ES ONLY (it is NOT in the ES cross_frame_replicator's
        # CROSS_FRAME_BROADCAST_TYPES allowlist), so it never reaches the centralized
        # hub (sandbox-A) — an async ES-event validator cannot see it, especially the
        # reverse (C→A) leg whose event lives only on Frame-C's ES. Self-stamping from
        # the synchronous response makes BOTH directions judgeable from the hub Redis
        # with zero cross-frame coordination dependency (the exact "settled not coming
        # back" gap). FX paths are tagged notes='fx...'. On a non-200 / non-completed
        # response (e.g. the booth refunds at the destination → HTTP 409) stamp a refund
        # signal so the judge fails promptly instead of waiting out the SLO window.
        if (path.notes or "").lower().startswith("fx"):
            key = f"canary:{test_id}"
            if await redis.exists(key):
                now_iso = (await _now_utc()).isoformat()
                body = result.get("response_body") if isinstance(result.get("response_body"), dict) else {}
                resp_status = str((body or {}).get("status", "")).lower()
                if result.get("http_status") == 200 and resp_status == "completed":
                    await redis.hset(
                        key,
                        mapping={
                            "fx_settled_seen_iso": now_iso,
                            "fx_credited_amount": str((body or {}).get("credited_amount", "")),
                            "fx_source_teg": str((body or {}).get("source_teg", "")),
                            "fx_dest_teg": str((body or {}).get("target_teg", "")),
                            "transfer_id": tid or "",
                            "http_status": str(result.get("http_status")),
                            "status": "fired",
                        },
                    )
                elif result.get("http_status") is not None:
                    # A DEFINITIVE HTTP response that wasn't a settled-200 — e.g. the
                    # booth refused at the destination (409: reserve floor / breaker /
                    # slippage cap), a 4xx validation error, or a 200 whose body status
                    # wasn't 'completed'. Deterministic failure → stamp so the judge
                    # fails it promptly + precisely as 'refunded'. A no-response failure
                    # (timeout / connection error → http_status is None) is left
                    # UNstamped so the judge's SLO-window 'timeout' verdict (infra, not
                    # economic) applies — keeping the two failure classes distinct.
                    await redis.hset(
                        key,
                        mapping={
                            "fx_refunded_seen_iso": now_iso,
                            "failure_signal": "refunded",
                            "http_status": str(result.get("http_status")),
                            "status": "fired",
                        },
                    )
    except Exception as e:
        logger.warning(f"[CanaryRunner] Redis state write failed for {test_id}: {e}")


async def _load_active_paths(db):
    """Fetch active canary_paths + their sender + receiver in one query each."""
    result = await db.execute(
        select(models.CanaryPath).where(models.CanaryPath.is_active == True)
    )
    paths = list(result.scalars().all())

    if not paths:
        return []

    # Fetch all referenced canary agents in one query
    agent_ids = set()
    for p in paths:
        agent_ids.add(p.sender_agent_id)
        agent_ids.add(p.receiver_agent_id)

    result = await db.execute(
        select(models.CanaryAgent).where(models.CanaryAgent.id.in_(agent_ids))
    )
    agents_by_id = {a.id: a for a in result.scalars().all()}

    enriched = []
    for p in paths:
        sender = agents_by_id.get(p.sender_agent_id)
        receiver = agents_by_id.get(p.receiver_agent_id)
        if sender is None or receiver is None or not sender.is_active or not receiver.is_active:
            continue
        enriched.append((p, sender, receiver))
    return enriched


async def execute_canary_fire(db, remote_path_id: int, test_id: str) -> dict:
    """§V0045 Cockpit EXECUTOR — fire OUR local path with OUR canary agent on master
    dispatch (called by /api/v1/federation/canary-fire; peer-mTLS-authenticated there).

    Idempotent on test_id: the canary_test_results pre-INSERT (unique test_id) is the
    replay guard — a duplicate dispatch acks {replayed:true} and does NOT re-fire.
    The local path must exist AND be is_active (local execution-enable is respected;
    the master only owns scheduling)."""
    from sqlalchemy import select as _select

    if not test_id or not str(test_id).startswith("canary-"):
        return {"ok": False, "error": "invalid test_id (must be canary-…)"}
    existing = (await db.execute(
        _select(models.CanaryTestResult.id).where(models.CanaryTestResult.test_id == test_id)
    )).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "replayed": True, "test_id": test_id}

    row = (await db.execute(
        _select(models.CanaryPath).where(models.CanaryPath.id == int(remote_path_id))
    )).scalar_one_or_none()
    if row is None:
        return {"ok": False, "error": f"no local canary path id={remote_path_id}", "test_id": test_id}
    if not row.is_active:
        return {"ok": False, "rejected": "path_inactive", "test_id": test_id}
    sender = (await db.execute(
        _select(models.CanaryAgent).where(models.CanaryAgent.id == row.sender_agent_id)
    )).scalar_one_or_none()
    receiver = (await db.execute(
        _select(models.CanaryAgent).where(models.CanaryAgent.id == row.receiver_agent_id)
    )).scalar_one_or_none()
    if sender is None or receiver is None or not sender.is_active or not receiver.is_active:
        return {"ok": False, "error": "sender/receiver canary agent missing or inactive", "test_id": test_id}

    # §2026-06-21 idle-in-txn fix: release the request connection before the network
    # fire; the result write below uses its own short session (get_db_context).
    await db.commit()
    result = await _fire_transfer(row, sender, receiver, test_id=test_id)
    async with get_db_context() as wdb:
        await _record_fire(wdb, row, sender, receiver, result)
    logger.info(
        f"[CanaryRunner] EXECUTED dispatch {row.path_id} test_id={test_id} "
        f"http={result.get('http_status')} failure={result.get('failure_type')}"
    )
    return {
        "ok": result.get("failure_type") is None,
        "test_id": test_id,
        "path_id": row.path_id,
        "http_status": result.get("http_status"),
        "failure_type": result.get("failure_type"),
        "transfer_id": result.get("transfer_id"),
    }


async def _load_active_remote_paths(db):
    """Master: fetch the cockpit's remote-path schedule rows."""
    res = await db.execute(
        select(models.CanaryRemotePath).where(models.CanaryRemotePath.is_active == True)
    )
    return list(res.scalars().all())


# §V0046 — share _last_fire across workers via a Redis hash. Leadership rotates
# between gunicorn workers; with per-worker memory each new leader started from an
# empty dict and re-fired everything due-now (~1.8× nominal cadence observed).
# Merge-on-cycle + persist-on-fire keeps cadence honest across rotations.
_LAST_FIRE_HASH = "canary:last_fire"


async def _merge_last_fire_from_redis() -> None:
    try:
        redis = await get_redis()
        if redis is None:
            return
        raw = await redis.hgetall(_LAST_FIRE_HASH)
        if not raw:
            return
        from datetime import datetime as _dt
        for k, v in raw.items():
            k = k.decode() if isinstance(k, (bytes, bytearray)) else str(k)
            v = v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
            try:
                ts = _dt.fromisoformat(v)
            except Exception:
                continue
            key = k if k.startswith("remote:") else (int(k) if k.isdigit() else k)
            cur = _last_fire.get(key)
            if cur is None or ts > cur:
                _last_fire[key] = ts
    except Exception:
        pass  # best-effort — falls back to per-worker memory


async def _persist_last_fire(key, when) -> None:
    try:
        redis = await get_redis()
        if redis is not None:
            await redis.hset(_LAST_FIRE_HASH, str(key), when.isoformat())
    except Exception:
        pass


async def _dispatch_remote(rp) -> None:
    """Master → home: dispatch one scheduled remote fire over the federation mTLS
    channel (the IRONHAND probe-remote pattern). Exactly-once discipline: the master
    mints test_id; retry ONLY on connect-class errors (the request provably never
    reached the home — same class split as the §V0042 P1 retry); a read-timeout is
    NOT retried (the fire may have landed; the home's idempotent executor + judge own
    the truth from there, and the dispatch row records the uncertainty)."""
    import httpx as _httpx
    import time as _time
    from ..routers.teg_integration import _to_internal_mtls_url
    from ..identity import svid_client
    from sqlalchemy import update as _update, func as _func

    test_id = f"canary-{rp.path_label}-{uuid.uuid4().hex[:10]}"
    t0 = _time.monotonic()
    # Durable audit row FIRST (outcome=sent) — the dispatch ledger is the cockpit's
    # conservation check (dispatched vs home-recorded).
    async with get_db_context() as db:
        db.add(models.CanaryDispatch(
            test_id=test_id, home_registry=rp.home_registry,
            remote_path_id=rp.remote_path_id, path_label=rp.path_label, outcome="sent",
        ))
        await db.commit()

    outcome, http_status, err = "dispatch_failed", None, None
    try:
        async with get_db_context() as db:
            peers = (await db.execute(
                select(models.PeerRegistry).where(
                    _func.lower(models.PeerRegistry.name) == rp.home_registry.lower()
                )
            )).scalars().all()
        peer = next((p for p in peers if (p.status or "").upper() == "ACTIVE"),
                    (peers[0] if peers else None))
        if peer is None or not peer.base_url:
            err = f"no reachable peer registry '{rp.home_registry}'"
        else:
            url = _to_internal_mtls_url(peer.base_url.rstrip("/")) + "/api/v1/federation/canary-fire"
            client_config: dict = {"timeout": CANARY_DISPATCH_TIMEOUT_SEC}
            if url.startswith("https://"):
                cc = svid_client.get_client_cert_config(target_url=url)
                if cc:
                    client_config.update(cc)
                else:
                    err = "no mTLS client cert available for dispatch"
            else:
                lic = os.getenv("FEDERATION_LICENSE_KEY", "")
                if lic:
                    client_config["headers"] = {"X-Federation-License": lic}
                else:
                    client_config["headers"] = {
                        "X-Federation-Secret": os.getenv("FEDERATION_INTERNAL_SECRET", ""),
                        "X-Federation-SPIFFE-ID": svid_client.get_spiffe_id() or "",
                    }
            if err is None:
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        async with _httpx.AsyncClient(**client_config) as c:
                            r = await c.post(url, json={
                                "remote_path_id": rp.remote_path_id, "test_id": test_id,
                            })
                        http_status = r.status_code
                        data = {}
                        try:
                            data = r.json()
                        except Exception:
                            pass
                        if r.status_code == 200 and data.get("ok"):
                            outcome = "replayed" if data.get("replayed") else "acked"
                        elif r.status_code == 200 and data.get("rejected"):
                            outcome, err = "rejected", str(data.get("rejected"))
                        else:
                            outcome = "dispatch_failed"
                            err = (str(data)[:300] if data else f"HTTP {r.status_code}")
                        break
                    except (_httpx.ConnectError, _httpx.ConnectTimeout) as e:
                        if attempt >= 2:
                            err = f"connect: {str(e)[:200]}"
                            break
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        err = str(e)[:200]
                        break
    except Exception as e:
        err = str(e)[:200]

    lat = int((_time.monotonic() - t0) * 1000)
    async with get_db_context() as db:
        await db.execute(
            _update(models.CanaryDispatch)
            .where(models.CanaryDispatch.test_id == test_id)
            .values(outcome=outcome, http_status=http_status, latency_ms=lat, error=err)
        )
        await db.commit()
    log = logger.info if outcome in ("acked", "replayed") else logger.warning
    log(f"[CanaryRunner] DISPATCH {rp.path_label}@{rp.home_registry} test_id={test_id} "
        f"outcome={outcome} http={http_status} lat={lat}ms{' err=' + err if err else ''}")


_EMPTY_CYCLES = 0


async def _run_cycle():
    """One runner cycle: fire any due paths."""
    if not CANARY_ENABLED:
        return
    # §V0045 Cockpit: followers never self-schedule — they fire only on master dispatch
    # (/api/v1/federation/canary-fire). Judge/validators/rebalancer are unaffected.
    if CANARY_RUNNER_MODE == "follower":
        return
    # §V0045 Cockpit: fleet pause — one flag silences ALL scheduling here (local fires
    # AND remote dispatches). On the master that silences the whole fleet.
    try:
        _r = await get_redis()
        if _r is not None and await _r.get(CANARY_FLEET_PAUSED_KEY):
            return
    except Exception:
        pass

    now = await _now_utc()
    # §V0046 — adopt the fleet-shared schedule state (survives leader rotation).
    await _merge_last_fire_from_redis()
    fired_count = 0
    error_count = 0

    async with get_db_context() as db:
        try:
            paths = await _load_active_paths(db)
        except Exception as e:
            logger.error(f"[CanaryRunner] load paths failed: {e}", exc_info=True)
            return

        # §2026-06-21 idle-in-txn fix: release the connection after the read; the
        # per-path fires (network) + result writes use their own short sessions, so the
        # outer session must not sit idle-in-transaction across the whole fire loop.
        await db.commit()
        # §BATCH10 finding 25: with zero paths the runner said nothing for forty minutes — idle-by-design and dead read the same.
        # One line per cycle when there is nothing to fire (throttled to every 10th cycle), the count when there is.
        global _EMPTY_CYCLES
        if not paths:
            _EMPTY_CYCLES += 1
            if _EMPTY_CYCLES == 1 or _EMPTY_CYCLES % 10 == 0:
                logger.info(f"[CanaryRunner] cycle: 0 active canary paths on this node (idle by design or unseeded; cycle #{_EMPTY_CYCLES})")
            try:
                from . import vitals as _vitals
                await _vitals.stamp_turn("canary_runner")
            except Exception:  # noqa: BLE001
                pass
        else:
            _EMPTY_CYCLES = 0
        for (path, sender, receiver) in paths:
            last = _last_fire.get(path.id)
            if last is not None:
                elapsed = (now - last).total_seconds()
                if elapsed < path.interval_sec:
                    continue
            try:
                result = await _fire_transfer(path, sender, receiver)
                _last_fire[path.id] = now
                await _persist_last_fire(path.id, now)
                # Use a fresh per-fire DB session for the result write
                async with get_db_context() as wdb:
                    await _record_fire(wdb, path, sender, receiver, result)
                fired_count += 1
                if result.get("failure_type"):
                    logger.warning(
                        f"[CanaryRunner] FIRED {path.path_id} test_id={result['test_id']} "
                        f"FAILED ({result['failure_type']}): "
                        f"http={result.get('http_status')} lat={result.get('http_latency_ms')}ms"
                    )
                else:
                    logger.info(
                        f"[CanaryRunner] FIRED {path.path_id} test_id={result['test_id']} "
                        f"http={result.get('http_status')} lat={result.get('http_latency_ms')}ms "
                        f"tx={result.get('transfer_id') or '?'}"
                    )
            except Exception as e:
                error_count += 1
                logger.error(
                    f"[CanaryRunner] fire path {path.path_id} ({path.id}) crashed: {e}",
                    exc_info=True,
                )

    # §V0045 Cockpit (master only): dispatch due REMOTE paths to their home registries.
    if CANARY_RUNNER_MODE == "master":
        try:
            async with get_db_context() as rdb:
                rpaths = await _load_active_remote_paths(rdb)
            for rp in rpaths:
                # §V0046 — per-dispatch pause re-check: a fleet-pause set MID-cycle stops
                # the dispatch tail immediately (the tail is ≤25 × ~1s otherwise).
                try:
                    _rr = await get_redis()
                    if _rr is not None and await _rr.get(CANARY_FLEET_PAUSED_KEY):
                        logger.info("[CanaryRunner] fleet pause set mid-cycle — dispatch tail stopped")
                        break
                except Exception:
                    pass
                rkey = f"remote:{rp.id}"
                rlast = _last_fire.get(rkey)
                if rlast is not None and (now - rlast).total_seconds() < (rp.interval_sec or 60):
                    continue
                _last_fire[rkey] = now
                await _persist_last_fire(rkey, now)
                try:
                    await _dispatch_remote(rp)
                    fired_count += 1
                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"[CanaryRunner] dispatch {rp.path_label}@{rp.home_registry} crashed: {e}",
                        exc_info=True,
                    )
        except Exception as e:
            error_count += 1
            logger.error(f"[CanaryRunner] remote dispatch pass failed: {e}", exc_info=True)

    if fired_count or error_count:
        logger.info(
            f"[CanaryRunner] cycle done: fired={fired_count} errors={error_count}"
        )


async def _force_fire_subscriber() -> None:
    """§pass21 (2026-05-16) — Redis pub/sub listener for canary_runner_force_fire.

    `POST /admin/canary/fire` publishes a path_id to the `canary_runner_force_fire`
    channel; this listener pops the path from `_last_fire` so the next runner
    cycle (within CANARY_RUNNER_INTERVAL_SEC) fires that path regardless of its
    interval_sec. Replaces the previous workaround of restarting the registry
    to clear the in-memory dict. Best-effort: reconnects on Redis hiccup.
    """
    from agentvault_registry.services.pubsub_backoff import jittered
    while True:
        try:
            redis = await get_redis()
            if redis is None:
                await asyncio.sleep(jittered(8.0))
                continue
            pubsub = redis.pubsub()
            await pubsub.subscribe("canary_runner_force_fire")
            logger.info(
                "[CanaryRunner] force-fire subscriber attached to canary_runner_force_fire"
            )
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                raw = message.get("data")
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="ignore")
                try:
                    path_id = int(raw)
                except (TypeError, ValueError):
                    continue
                _last_fire.pop(path_id, None)
                try:  # §V0046 — clear the fleet-shared copy too
                    if redis is not None:
                        await redis.hdel(_LAST_FIRE_HASH, str(path_id))
                except Exception:
                    pass
                logger.info(
                    f"[CanaryRunner] force-fire received path_id={path_id} "
                    "(cleared from _last_fire; next cycle will fire it)"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Flat 10s meant every worker on every registry came back on the same tick.
            wait = jittered(15.0)
            logger.warning(
                f"[CanaryRunner] force-fire subscriber error, reconnecting in {wait:.2f}s: {exc}"
            )
            await asyncio.sleep(wait)


class CanaryRunner:
    """Leader-elected canary firing background task."""

    def __init__(self) -> None:
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.subscriber_task: Optional[asyncio.Task] = None

    async def _run_loop(self) -> None:
        logger.info(
            f"[CanaryRunner] starting (interval={CANARY_RUNNER_INTERVAL_SEC}s, "
            f"enabled={CANARY_ENABLED}, mtls={CANARY_USE_MTLS})"
        )
        await _vitals.register(CANARY_RUNNER_LEADER_KEY, module=__name__,
                               pattern="hand-rolled",
                               interval_sec=CANARY_RUNNER_INTERVAL_SEC, enabled=CANARY_ENABLED)
        while self.running:
            try:
                if not CANARY_ENABLED:
                    await asyncio.sleep(CANARY_RUNNER_INTERVAL_SEC)
                    continue
                if not await try_acquire_leadership(CANARY_RUNNER_LEADER_KEY):
                    await asyncio.sleep(CANARY_RUNNER_INTERVAL_SEC)
                    continue
                # No error-handling change here: _run_cycle's only top-level try is a
                # best-effort read of the fleet-pause flag (failing open is intended),
                # and everything after it already escapes to this loop.
                async with _vitals.cycle("canary_runner"):
                    await _run_cycle()
            except Exception as e:
                logger.error(
                    f"[CanaryRunner] unexpected error in cycle: {e}", exc_info=True
                )
            await asyncio.sleep(CANARY_RUNNER_INTERVAL_SEC)

    async def start(self) -> None:
        if self.running:
            logger.warning("[CanaryRunner] already running")
            return
        if not CANARY_RUNNER_ENABLED:
            logger.info(
                "[CanaryRunner] disabled (CANARY_RUNNER_ENABLED!=true); skipping start"
            )
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        self.subscriber_task = asyncio.create_task(_force_fire_subscriber())
        logger.info("[CanaryRunner] background runner started")

    async def stop(self) -> None:
        self.running = False
        for t in (self.task, self.subscriber_task):
            if t is None:
                continue
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        self.task = None
        self.subscriber_task = None
        logger.info("[CanaryRunner] background runner stopped")


_runner: Optional[CanaryRunner] = None


async def start_canary_runner() -> None:
    global _runner
    if _runner is None:
        _runner = CanaryRunner()
    await _runner.start()


async def stop_canary_runner() -> None:
    global _runner
    if _runner is not None:
        await _runner.stop()
