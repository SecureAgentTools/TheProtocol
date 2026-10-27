"""READONLY_MODE — global break-glass write freeze (§29, 2026-07-28).

WHY ONE SWITCH, IN MIDDLEWARE
"Stop all state change, now" is an operational lever the registry did not have. Threading a
freeze flag through every router would guarantee that the next router added forgets it — so the
check lives in ONE pure-ASGI middleware that every HTTP request passes through, and no money path
has to implement its own.

    READONLY_MODE=false   (DEFAULT — byte-inert, not a single behaviour change)
    READONLY_MODE=true    reads serve normally; writes are refused 503

FAIL CLOSED, DELIBERATELY
`/mcp*` is refused wholesale while frozen. Every MCP tool call is a POST to ONE path, so read and
write are indistinguishable at this layer; allowing them through would mean the freeze silently
leaks writes. **A guarantee that does not hold is worse than no guarantee** — reads stay available
over the HTTP API and the FE, so nothing observational is lost.

WHAT STAYS OPEN WHILE FROZEN (and why)
Login and token minting. They are POSTs, but an incident responder who cannot authenticate cannot
*look* at the system they just froze — a freeze that locks out its own operator is a foot-gun, not
a safety feature. These create a session, never economic state.

DISABLING REQUIRES A CONTAINER RECREATE (env-only, on purpose)
There is deliberately NO API to clear the flag: a switch that a compromised admin token can flip
back off is not a safety mechanism. The cost is ~30s to recreate; that is the right trade.

Δ-irrelevant: deny-only, and it refuses BEFORE any handler runs, so nothing is half-applied.
"""
from __future__ import annotations

import logging
import os

from starlette.types import ASGIApp, Receive, Scope, Send

from ..errors import create_error_response

logger = logging.getLogger(__name__)


def _flag() -> bool:
    return os.getenv("READONLY_MODE", "false").strip().lower() in ("1", "true", "yes")


_ENABLED = _flag()
_RETRY_AFTER = os.getenv("READONLY_RETRY_AFTER", "300")

# Safe by definition — never touched by the freeze.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Writes that remain permitted while frozen. Session establishment only: no economic state, and
# without them the operator cannot authenticate to observe the frozen system.
# §DOCSFIX D6-232 (2026-10-16): with the two second steps of a two-factor sign-in (the password step answers a partial
# token; the session comes from /2fa/validate or /2fa/recover), so an admin with 2FA can still sign in while frozen.
# The entry /api/v1/auth/token is gone: no route serves it.
_EXEMPT_WRITE_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/2fa/validate",
    "/api/v1/auth/2fa/recover",
    "/api/v1/auth/agent/token",
    "/api/v1/auth/refresh",
    "/health",
    "/metrics",
})

# Refused wholesale while frozen — read/write cannot be told apart here (see module docstring).
_FAIL_CLOSED_PREFIXES = ("/mcp",)

try:  # metrics are optional; their absence must never affect the gate
    from prometheus_client import Counter
    READONLY_REFUSED_TOTAL = Counter(
        "registry_readonly_refused_total",
        "Writes refused because READONLY_MODE is engaged",
        ["method", "reason"],
    )
except Exception:  # pragma: no cover
    READONLY_REFUSED_TOTAL = None


# ── background-worker freeze ────────────────────────────────────────────────────────────────
# The middleware only sees HTTP. ~43 workers + 39 reactors mutate state on their own timers and
# never pass through it, so a freeze that stopped only HTTP would be a HALF freeze — and a
# half-freeze you believe is total is exactly the kind of false guarantee this module exists to
# avoid. Every leader-elected task funnels through `leader.try_acquire_leadership`, so ONE gate
# there covers all of them: refuse leadership while frozen and the worker simply skips its cycle
# and retries later. No worker needs to be edited, and the next worker added is covered for free.
#
# DEFAULT IS FREEZE. A task is frozen unless it is explicitly known to be an observer — a new
# worker is assumed to mutate, because the failure mode of guessing wrong the other way is
# "the freeze silently let something through".
#
# The exemptions are OBSERVABILITY, and they are load-bearing: you engage a freeze BECAUSE
# something is wrong, which is precisely when you must not go blind. Each was checked for table
# writes before being listed (2026-07-28) — none writes. NOTE `compliance_poller` is deliberately
# NOT here despite sounding observational: it auto-quarantines registries, so it mutates.
_EXEMPT_TASKS_DEFAULT = frozenset({
    "supply_auditor",         # the Δ=0 watchdog — the last thing to blind during an incident
    "auditor_worker",         # independent observer
    "license_drift_monitor",  # observation only (FEDERATION_ENFORCEMENT_ACTIVE=false)
})

_LOG_THROTTLE_S = 300.0
_last_logged: dict = {}

try:
    from prometheus_client import Counter as _C
    READONLY_WORKER_SKIPPED_TOTAL = _C(
        "registry_readonly_worker_skipped_total",
        "Background-worker cycles skipped because READONLY_MODE is engaged",
        ["task"],
    )
except Exception:  # pragma: no cover
    READONLY_WORKER_SKIPPED_TOTAL = None


def _exempt_tasks() -> frozenset:
    """Code default ∪ READONLY_EXEMPT_TASKS (comma-separated), so an operator can widen the
    observability set during an incident without a rebuild. Widening only ever ADDS observers;
    it can never un-freeze a mutating task by accident, because the operator must name it."""
    extra = os.getenv("READONLY_EXEMPT_TASKS", "")
    return _EXEMPT_TASKS_DEFAULT | {t.strip() for t in extra.split(",") if t.strip()}


def task_frozen(task_name: str) -> bool:
    """True when READONLY_MODE is engaged and this task is not an exempt observer."""
    if not _ENABLED:
        return False
    if task_name in _exempt_tasks():
        return False
    if READONLY_WORKER_SKIPPED_TOTAL is not None:
        try:
            READONLY_WORKER_SKIPPED_TOTAL.labels(task_name).inc()
        except Exception:
            pass
    # Throttled: these poll on short intervals and would otherwise flood the log.
    import time as _t
    now = _t.monotonic()
    if now - _last_logged.get(task_name, -1e9) > _LOG_THROTTLE_S:
        _last_logged[task_name] = now
        logger.warning("[READONLY] worker '%s' frozen — leadership refused, cycle skipped",
                       task_name)
    return True


class ReadOnlyModeMiddleware:
    """Pure-ASGI (matches AdmissionControlMiddleware — BaseHTTPMiddleware is avoided here)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        if _ENABLED:
            # Loud on purpose: a frozen registry must never be a silent surprise to whoever
            # reads the logs next.
            logger.warning(
                "[READONLY] ENGAGED — all writes refused 503 except %s; %s refused wholesale. "
                "Clear it by setting READONLY_MODE=false and recreating the container.",
                sorted(_EXEMPT_WRITE_PATHS), list(_FAIL_CLOSED_PREFIXES),
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Fast path: the flag is read ONCE at import, so when disabled this is a single
        # boolean test per request and nothing else.
        if not _ENABLED or scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope.get("method", "GET")
        path = scope.get("path", "")

        if method in _SAFE_METHODS and not path.startswith(_FAIL_CLOSED_PREFIXES):
            return await self.app(scope, receive, send)
        if path in _EXEMPT_WRITE_PATHS:
            return await self.app(scope, receive, send)

        reason = "mcp_indistinguishable" if path.startswith(_FAIL_CLOSED_PREFIXES) else "write"

        # §29 LIVE CALL SITE for I4 `write_allowed`. Evaluated only while the freeze is engaged:
        # calling OPA on every request in normal operation would put its latency back on the
        # critical path, which is exactly what §V0119 removed. Observability, never the gate —
        # Python has already decided by this point.
        try:
            from agentvault_registry import opa_shadow as _opa
            await _opa.shadow_check(
                "agentvault/invariants/write_allowed",
                {"readonly_mode": True, "method": method},
                False, f"readonly.{reason}")
        except Exception:
            pass   # a freeze must never depend on the policy sidecar being up

        if READONLY_REFUSED_TOTAL is not None:
            try:
                READONLY_REFUSED_TOTAL.labels(method, reason).inc()
            except Exception:
                pass

        logger.warning("[READONLY] refused %s %s (reason=%s)", method, path, reason)
        resp = create_error_response(
            detail=("Registry is in READ-ONLY mode — state-changing requests are refused. "
                    "Reads are unaffected."),
            status_code=503,
            error_type="service_unavailable",
        )
        resp.headers["Retry-After"] = _RETRY_AFTER
        resp.headers["X-Readonly-Mode"] = "engaged"
        return await resp(scope, receive, send)
