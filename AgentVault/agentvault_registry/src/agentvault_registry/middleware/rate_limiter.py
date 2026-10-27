"""Rate limiting for the AgentVault Registry.

§RATEFIX (2026-08-27) rebuilt this module. What was here before had three
defects that had to be fixed in this order, because fixing the last one first
produces a limiter that stops honest callers and not attackers:

1. THE KEY WAS FORGEABLE. Every limit keyed on ``slowapi.util.get_remote_address``,
   which returns ``request.client.host`` — the value uvicorn's ProxyHeaders
   middleware rewrote from the FIRST element of ``X-Forwarded-For`` under
   ``forwarded_allow_ips="*"``. nginx APPENDS to that header, so the first
   element is whatever the caller sent. Measured: a request carrying
   ``X-Forwarded-For: 203.0.113.77`` was logged by the registry as coming from
   203.0.113.77. Fixed by ``core/client_ip.effective_client_ip`` (last element)
   and, better, by keying on the VERIFIED principal whenever there is one.

2. THE STORAGE WAS PER-WORKER. All 65 ``@limiter.limit(...)`` decorations were
   declared on router-local ``Limiter(key_func=get_remote_address)`` instances
   built with no ``storage_uri`` — i.e. in-memory, one counter set per worker
   process. registry-a runs 38 workers, so a written ``10/minute`` behaved like
   up to 380/minute, unevenly. Fixed by ``shared_limiter``: ONE instance, Redis
   backed, imported by every router, and the same object the SlowAPI middleware
   enforces. slowapi's decorator checks inline against ``self._route_limits``
   (the middleware pass runs with ``in_middleware=True``, which skips route
   limits entirely), so the routers must share the instance or their limits are
   both unshared and invisible.

3. THE SWITCH. ``SANDBOX_BYPASS_RATE_LIMIT=true`` monkey-patched
   ``slowapi.Limiter.limit`` into a no-op AT IMPORT TIME, so every per-route
   limit in the codebase was inert on all 16 core registries. The patch is gone.
   The env var survives with its honest meaning — ``limiter.enabled = False``,
   one flag on one object — because the sandbox tier's API tester sweeps a
   thousand endpoints in seconds and genuinely must not be limited.

ORDERING NOTE (load-bearing, unchanged from the old module): ``main.py`` imports
this module before any router, so ``shared_limiter`` exists by the time router
modules run their decorations. Do not move that import.

INTERNAL LANE: on-box and container-to-container traffic is exempt via
``_request_filters`` reading a ContextVar that ``rate_limit_lane_middleware``
sets per request. slowapi calls request filters with NO arguments, so the
ContextVar is how a filter learns anything about the request — the same pattern
``security.py`` uses for presented API-key scopes. The predicate itself lives in
``core/client_ip.is_internal_request`` and is conjunctive (no proxy headers AND
private peer) precisely so that an external caller reaching a published
container port cannot claim it.
"""

import contextvars
import logging
import os
from typing import Callable

import jwt
from fastapi import Request
from slowapi import Limiter
from starlette.responses import Response as _StarletteResponse

from agentvault_registry.config import settings
from agentvault_registry.core.client_ip import effective_client_ip, is_internal_request

logger = logging.getLogger(__name__)

class TolerantLimiter(Limiter):
    """slowapi's per-route decorator ends with

        self._inject_headers(kwargs.get("response"), request.state.view_rate_limit)

    for any endpoint that does not return a ``Response`` — and ``kwargs["response"]``
    is None unless the endpoint declares ``response: Response``. ``_inject_headers``
    then RAISES "parameter `response` must be an instance of
    starlette.responses.Response". Our decorated endpoints return dicts and pydantic
    models, so with headers enabled this is a 500 on EVERY decorated route the moment
    limits are live — measured 2026-08-27 in an isolated repro before this shipped
    (``scratchpad/slowapi_exempt_probe.py``: ``[500, 500, 500, 429, 429, 429]`` where
    the first three were requests INSIDE the limit).

    Nobody hit it because the monkey-patch meant no route limit had ever run in
    production. Skip injection when there is nothing to inject into; the middleware
    pass still injects the headers, because there the response really is a Response.
    """

    def _inject_headers(self, response, current_limit):
        if not isinstance(response, _StarletteResponse):
            return response
        return super()._inject_headers(response, current_limit)


# ── Process-wide bypass (sandbox tier only) ────────────────────────────────
# Honest implementation: one attribute on one object. NOT a monkey-patch of the
# slowapi class, which used to make the bypass invisible to every reader of a
# router file.
SANDBOX_BYPASS_RATE_LIMIT = os.getenv("SANDBOX_BYPASS_RATE_LIMIT", "").lower() in (
    "true", "1", "yes",
)

# ── Per-request lane, for the argument-less request filters ────────────────
_IS_INTERNAL: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "rate_limit_is_internal", default=False
)

# §DOCSFIX D6-315 (2026-10-16): the RATE_LIMITS role dict is gone with its four settings. slowapi applies limits per
# ROUTE, not per role; nothing consulted it, and an operator who set a role limit changed nothing.

ADMIN_API_KEY = getattr(settings, "TEG_ADMIN_API_KEY", "")


def get_user_role_from_request(request: Request) -> str:
    """Best-effort role for LOGGING and metrics.

    ⚠ This decodes the JWT WITHOUT verifying its signature, so a caller can
    claim any role it likes. That is acceptable for a log label and unacceptable
    for an authorization or rate-limit decision — which is why the key function
    below keys on the principal the auth dependencies VERIFIED, never on this.
    """
    try:
        api_key = request.headers.get("X-Api-Key", "")
        if api_key:
            if api_key == ADMIN_API_KEY or api_key in settings.rate_limit_bypass_keys:
                return "admin"
            return "developer"

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return "public"
        payload = jwt.decode(auth_header.split(" ")[1], options={"verify_signature": False})
        if payload.get("is_admin", False):
            return "admin"
        if payload.get("type") == "agent" or "agent_did" in payload:
            return "agent"
        if "sub" in payload:
            return "developer"
        return "public"
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not extract role from token: {e}")
        return "public"


def principal_rate_key(request: Request) -> str:
    """Bucket by WHO is calling, falling back to WHERE from.

    ``request.state.rl_principal`` is set by the token verifiers in
    ``security.py`` once a signature has actually been checked, so an agent gets
    its own bucket on every authenticated route. This is what stops one abusive
    agent from spending a shared allowance, and stops a hundred honest users
    behind one NAT from sharing one.

    The middleware pass runs before dependencies resolve, so the coarse default
    limit still keys on the address — but on the FORGE-PROOF one.
    """
    principal = getattr(request.state, "rl_principal", None)
    if principal:
        return principal
    key = settings.rate_limit_bypass_keys
    api_key = request.headers.get("X-Api-Key", "")
    if api_key and (api_key == ADMIN_API_KEY or api_key in key):
        return f"bypass:{api_key[:8]}"
    return f"ip:{effective_client_ip(request) or 'unknown'}"


def create_rate_limit_key_func() -> Callable:
    """The key function, finally wired (it never was: ``create_enhanced_limiter``
    used to build the limiter with ``key_func=get_remote_address`` and ignore
    this entirely)."""
    return principal_rate_key


def _internal_lane_filter() -> bool:
    """slowapi request filter. Called with NO arguments — hence the ContextVar."""
    return _IS_INTERNAL.get(False)


def _build_limiter() -> Limiter:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        logger.info(
            "Rate limiter using Redis storage: %s",
            redis_url.split("@")[-1] if "@" in redis_url else redis_url,
        )
    else:
        logger.warning(
            "Rate limiter has NO REDIS_URL — falling back to per-worker in-memory "
            "counters. Limits will be looser than written by roughly the worker count."
        )

    limiter = TolerantLimiter(
        key_func=principal_rate_key,
        default_limits=[settings.RATE_LIMIT_DEFAULT],
        storage_uri=redis_url,
        strategy="fixed-window",
        headers_enabled=True,
    )
    limiter._request_filters.append(_internal_lane_filter)

    if SANDBOX_BYPASS_RATE_LIMIT:
        limiter.enabled = False
        logger.warning(
            "[RateLimiter] SANDBOX_BYPASS_RATE_LIMIT=true — rate limiting is "
            "DISABLED for this process (sandbox/API-tester posture)."
        )
    return limiter


# THE limiter. Imported by every router; assigned to app.state.limiter in main.py.
shared_limiter: Limiter = _build_limiter()


def create_enhanced_limiter() -> Limiter:
    """Back-compat entry point for main.py. Returns the SHARED instance — it must
    not build a second one, or the middleware would enforce a different object
    than the routers decorated."""
    return shared_limiter


async def rate_limit_lane_middleware(request: Request, call_next):
    """Classify the request's lane before SlowAPIMiddleware runs.

    Added AFTER SlowAPIMiddleware in main.py, which makes it OUTER (Starlette
    runs the last-added middleware first) and therefore earlier.
    """
    # Both SlowAPIMiddleware and the per-route decorator read
    # request.state.view_rate_limit UNCONDITIONALLY, and Starlette's State
    # raises AttributeError on a miss — so an exempt request (nothing
    # counted, nothing set) would 500. Seed it.
    request.state.view_rate_limit = None
    token = _IS_INTERNAL.set(is_internal_request(request))
    try:
        return await call_next(request)
    finally:
        _IS_INTERNAL.reset(token)


def exempt_from_rate_limit(func):
    """Decorator to exempt specific endpoints from rate limiting."""
    func._rate_limit_exempt = True
    return func


async def admin_api_key_middleware(request: Request, call_next):
    """Flag the admin API key on the request for downstream consumers."""
    if request.headers.get("X-Api-Key", "") == ADMIN_API_KEY and ADMIN_API_KEY:
        request.state.is_admin = True
    return await call_next(request)
