"""
Admission-Control / Load-Shedding Middleware (pure-ASGI).

Bounds the number of concurrent *heavy* (mutating, cross-service) requests per
uvicorn worker and returns HTTP 503 + Retry-After IMMEDIATELY when a lane is
full — instead of letting unbounded work saturate the workers into a
crash-loop. (Incident 2026-06-09: registry-a hit 782% CPU / ``/health`` 000 /
``Child process died`` respawn-storm under the FX ``fx/route-hop`` flood; no
admission control existed, only per-IP rate limiting.) Liveness/read traffic is
never governed, so ``/health`` can never be starved.

Design + full rationale:
  sessionlogs2026/PLAN_2026-06-09_REGISTRY_ADMISSION_CONTROL_MIDDLEWARE.md (v2)

Key properties:
  * NON-BLOCKING — rejects with 503, never ``await``s a slot. Several heavy
    handlers HTTP-self-call their own registry (a2a_payment.py:221/232,
    contracts.py:516, fiat_onramp.py:2343) which would DEADLOCK a blocking
    semaphore; a nested over-cap call instead fails fast and the outer handler
    refunds (Delta-safe).
  * Per-worker counters (module-level => one set per uvicorn process) — zero
    added latency, lock-free (single-threaded asyncio loop, so the
    check-then-increment runs with no ``await`` in between => atomic).
  * Two lanes: ``internal`` (federation/mTLS peer hops + loopback self-calls)
    and ``client`` (external agent/dev traffic via nginx). Independent caps
    isolate the two distinct flood types so neither can saturate the worker.
  * Env-gated: REGISTRY_ADMISSION_ENABLED=false (default) => pure no-op.
"""
import logging
import os

from ..core.mtls_auth import forwarded_cert_vouched

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from ..errors import create_error_response

logger = logging.getLogger(__name__)

# --- Prometheus (best-effort; a metrics problem must never break shedding) ---
try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge

    ADMISSION_SHED_TOTAL = _Counter(
        "registry_admission_shed_total",
        "Heavy requests shed with HTTP 503 by admission control",
        labelnames=["lane", "registry"],
    )
    ADMISSION_INFLIGHT = _Gauge(
        "registry_admission_inflight",
        "In-flight heavy requests per lane (per-worker)",
        labelnames=["lane", "registry"],
        multiprocess_mode="livesum",  # sum live workers in multiprocess /metrics
    )
    _PROM = True
except Exception:  # pragma: no cover — metrics optional
    _PROM = False
    ADMISSION_SHED_TOTAL = None
    ADMISSION_INFLIGHT = None


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes", "on")


# Read once at import (per worker process). Changing these requires a recreate.
_ENABLED = _flag("REGISTRY_ADMISSION_ENABLED", "false")
_REGISTRY = os.getenv("REGISTRY_NAME", "registry")
_CLIENT_LIMIT = int(os.getenv("REGISTRY_ADMISSION_CLIENT_LIMIT", "40"))
_INTERNAL_LIMIT = int(os.getenv("REGISTRY_ADMISSION_INTERNAL_LIMIT", "40"))
_RETRY_AFTER = os.getenv("REGISTRY_ADMISSION_RETRY_AFTER", "2")

# Heavy (mutating, cross-service) path prefixes. Cheap GET reads under these are
# exempt automatically because only mutating methods are governed.
_HEAVY_PREFIXES = (
    "/api/v1/teg/",                 # transfer, cross-registry-transfer, fx/route-hop, treasury/*, ...
    "/api/v1/bridge/",
    "/api/v1/a2a-payment/",
    "/api/v1/staking/",
    "/api/v1/disputes",
    "/api/v1/federation/disputes/",
    "/api/v1/contracts/",
    "/api/v1/onboard/create_agent",
    "/api/v1/onboard/agents/",
)
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Cheap POSTs under a heavy prefix that must NOT be governed (local lookups).
_EXEMPT_EXACT = frozenset({"/api/v1/a2a-payment/verify"})

# Per-worker in-flight counters (module-level => one set per uvicorn process).
_inflight = {"client": 0, "internal": 0}


def _classify_lane(headers: Headers) -> str:
    """``internal`` = peer settlement hop (federation/mTLS) or loopback self-call;
    ``client`` = external agent/dev traffic that traversed nginx (X-Real-IP set).
    Capacity hint only — NOT an auth boundary (the endpoint's own auth is
    unchanged; nginx always sets X-Real-IP so external traffic cannot reach the
    internal lane by omitting it)."""
    if (
        "x-federation-secret" in headers
        or "x-federation-spiffe-id" in headers
        or forwarded_cert_vouched(headers)
    ):
        return "internal"
    if "x-real-ip" not in headers and "x-forwarded-for" not in headers:
        return "internal"  # direct loopback self-call (never went through nginx)
    return "client"


class AdmissionControlMiddleware:
    """Pure-ASGI admission control. Disconnect-safe and lower overhead than
    BaseHTTPMiddleware (which can leak the in-flight counter on cancellation)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        if _ENABLED:
            logger.info(
                "[ADMISSION] enabled: client_limit=%d internal_limit=%d retry_after=%s "
                "registry=%s prom=%s",
                _CLIENT_LIMIT, _INTERNAL_LIMIT, _RETRY_AFTER, _REGISTRY, _PROM,
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Fast path: disabled, non-HTTP, non-mutating, or not a heavy path.
        if scope["type"] != "http" or not _ENABLED:
            return await self.app(scope, receive, send)
        if scope["method"] not in _MUTATING_METHODS:
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path in _EXEMPT_EXACT or not path.startswith(_HEAVY_PREFIXES):
            return await self.app(scope, receive, send)

        lane = _classify_lane(Headers(scope=scope))
        limit = _INTERNAL_LIMIT if lane == "internal" else _CLIENT_LIMIT

        # NON-BLOCKING admission: reject fast (never await a slot => no deadlock
        # with the documented heavy self-calls).
        if _inflight[lane] >= limit:
            if _PROM:
                try:
                    ADMISSION_SHED_TOTAL.labels(lane, _REGISTRY).inc()
                except Exception:
                    pass
            resp = create_error_response(
                detail="Registry temporarily overloaded — please retry shortly.",
                status_code=503,
                error_type="service_unavailable",
            )
            resp.headers["Retry-After"] = _RETRY_AFTER
            resp.headers["X-Admission-Shed"] = lane
            return await resp(scope, receive, send)

        _inflight[lane] += 1
        if _PROM:
            try:
                ADMISSION_INFLIGHT.labels(lane, _REGISTRY).inc()
            except Exception:
                pass
        try:
            await self.app(scope, receive, send)
        finally:
            _inflight[lane] -= 1
            if _PROM:
                try:
                    ADMISSION_INFLIGHT.labels(lane, _REGISTRY).dec()
                except Exception:
                    pass
