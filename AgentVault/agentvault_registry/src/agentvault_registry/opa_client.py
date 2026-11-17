"""
OPA (Open Policy Agent) HTTP client.

Sandbox-only shadow-mode integration shipped 2026-04-30. Master kill switch is
``OPA_ENABLED`` env (default false) — when off, ``query_opa`` short-circuits
before any network call so the registry has zero OPA overhead.

Since V0665 (2026-11-16) the production frames and their operators run OPA in enforce (security.py keeps OPA's answer for its three
permission checks; an OPA that does not answer leaves the Python check alone deciding).
"""
from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import httpx

from agentvault_registry.es_ssl_helper import get_httpx_verify, spire_trust_loaded, svid_stamp

logger = logging.getLogger(__name__)

_DEFAULT_OPA_URL = "http://opa:8181"
_DEFAULT_TIMEOUT_SECONDS = 1.0

_client: Optional[httpx.AsyncClient] = None
_client_stamp: tuple = ()

# V0667 (gwo_25771cc56f472ec72ed05673; session-release room seq 5385): a client replaced after an SVID refresh is RETIRED, never closed
# under a request: it closes when its last request leaves. A request lasts at most the client's timeout, so the grace below (well above
# it) only closes a client something kept busy that long, and the error that causes is counted as client_rotated, apart from any other.
RETIRE_GRACE_SECONDS = 5.0
_inflight: Dict[int, int] = {}                                          # id(client) -> requests running on it
_retired: Dict[int, Tuple[httpx.AsyncClient, float]] = {}               # id(client) -> (client, when retired)
# clients the grace closed under requests: every request it cut off is counted client_rotated; the client object is held so its id is
# never reused while it is marked, and the mark is dropped a minute later (any request on it ended long before)
_closed_by_rotation: Dict[int, Tuple[httpx.AsyncClient, float]] = {}
_MARK_SECONDS = 60.0
_errors: Dict[str, int] = {}                                            # cause -> count, this process

try:
    from prometheus_client import Counter

    OPA_CLIENT_ERRORS_TOTAL = Counter("opa_client_errors_total", "OPA queries that got no answer, by cause "
                                      "(client_rotated: its client was closed by an SVID refresh while it ran)", labelnames=["cause"])
except Exception:  # pragma: no cover - prometheus_client is in requirements; a duplicate registration in a re-import is not fatal
    OPA_CLIENT_ERRORS_TOTAL = None


def errors_by_cause() -> Dict[str, int]:
    return dict(_errors)


def retired_count() -> int:
    return len(_retired)


def _count(cause: str) -> None:
    _errors[cause] = _errors.get(cause, 0) + 1
    if OPA_CLIENT_ERRORS_TOTAL is not None:
        try:
            OPA_CLIENT_ERRORS_TOTAL.labels(cause=cause).inc()
        except Exception:  # noqa: BLE001 - a metric never stops a query
            pass


async def _close(client: httpx.AsyncClient) -> None:
    try:
        await client.aclose()
    except Exception as exc:
        logger.debug(f"OPA client close after an SVID rotation (non-fatal): {exc}")


async def _retire(client: httpx.AsyncClient) -> None:
    """An idle client closes now; a busy one when its last request leaves (or past the grace)."""
    if _inflight.get(id(client), 0) > 0:
        _retired[id(client)] = (client, time.monotonic())
    else:
        await _close(client)


async def _sweep() -> None:
    now = time.monotonic()
    for key, (_c, at) in list(_closed_by_rotation.items()):
        if now - at >= _MARK_SECONDS:
            _closed_by_rotation.pop(key, None)
    for key, (client, since) in list(_retired.items()):
        if now - since >= RETIRE_GRACE_SECONDS:
            _retired.pop(key, None)
            _closed_by_rotation[key] = (client, now)
            logger.warning(f"OPA client retired by an SVID refresh still had {_inflight.get(key, 0)} request(s) after "
                           f"{RETIRE_GRACE_SECONDS}s: closed under them")
            await _close(client)


@contextlib.asynccontextmanager
async def _lease() -> AsyncIterator[httpx.AsyncClient]:
    """The client a request runs on, held for the request: a refresh retires it, and only the last request out closes it."""
    client = await get_client()
    key = id(client)
    _inflight[key] = _inflight.get(key, 0) + 1
    try:
        yield client
    finally:
        left = _inflight.get(key, 1) - 1
        if left > 0:
            _inflight[key] = left
        else:
            _inflight.pop(key, None)
            if key in _retired:
                _retired.pop(key, None)
                await _close(client)


def opa_enabled() -> bool:
    """Master kill switch — read every call so compose env-var flips take effect on restart."""
    return os.getenv("OPA_ENABLED", "false").lower() == "true"


def opa_url() -> str:
    return os.getenv("OPA_URL", _DEFAULT_OPA_URL).rstrip("/")


async def get_client() -> httpx.AsyncClient:
    """Lazy-init a long-lived httpx client. First singleton in the registry.

    §MTLSHOPS V0378: TLS by scheme through es_ssl_helper (a T2 frame's OPA serves TLS and requires the registry's
    SVID; an http OPA_URL ignores the context). The client binds its context at construction, so it is rebuilt when
    the SVID file changes, the rule of teg_integration._get_teg_client (§SVIDRACE V0639: keyed on the cert, the key and
    the bundle, and recorded only for a SPIRE context)."""
    global _client, _client_stamp
    stamp = svid_stamp()
    if stamp and stamp != _client_stamp and _client is not None:
        stale, _client = _client, None
        await _retire(stale)            # V0667: never closed under a request (see RETIRE_GRACE_SECONDS)
    await _sweep()
    if _client is None or _client.is_closed:
        verify = get_httpx_verify()
        _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS, verify=verify)
        _client_stamp = stamp if spire_trust_loaded(verify, stamp) else ()
    return _client


async def close_client() -> None:
    """Called from main.py shutdown. Idempotent."""
    global _client
    if _client is not None and not _client.is_closed:
        try:
            await _client.aclose()
        except Exception as exc:
            logger.debug(f"OPA client close error (non-fatal): {exc}")
    _client = None


async def query_opa(policy_path: str, input_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    POST input to OPA at /v1/data/{policy_path}, return the parsed body or None.

    ``policy_path`` is slash-delimited (e.g. ``agentvault/admin/allow``). OPA
    treats trailing path segments as the rule name. Returning the full body
    ``{"result": <bool|null|object>}`` lets callers extract whichever rule
    output they need; ``shadow_check`` reads ``body["result"]`` for boolean.

    Returns None when:
      - OPA_ENABLED=false (kill switch — no network call attempted)
      - HTTP / DNS / timeout error
      - Non-200 response
    Errors are logged at debug; this function never raises into a request handler.

    Latency from start of call to response (or short-circuit) is also surfaced
    for the caller via the optional ``_last_latency_ms`` attribute on the
    returned dict — keeps the public signature simple while letting metrics
    code observe timing without timing the call itself.
    """
    if not opa_enabled():
        return None

    url = f"{opa_url()}/v1/data/{policy_path.lstrip('/')}"
    started = time.perf_counter()
    leased: Optional[int] = None
    try:
        async with _lease() as client:
            leased = id(client)
            resp = await client.post(url, json={"input": input_data})
            latency_ms = (time.perf_counter() - started) * 1000.0
            if resp.status_code != 200:
                _count("status")
                logger.debug(
                    f"OPA query non-200: policy={policy_path} status={resp.status_code} "
                    f"latency_ms={latency_ms:.1f}"
                )
                return None
            body = resp.json()
        # Stash latency for caller (metrics code) without changing the contract.
        if isinstance(body, dict):
            body["_latency_ms"] = latency_ms
        return body
    except (httpx.HTTPError, httpx.TimeoutException, ValueError, RuntimeError) as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        if leased is not None and leased in _closed_by_rotation:
            _count("client_rotated")
            logger.warning(f"OPA query failed because an SVID refresh closed its client: policy={policy_path} "
                           f"latency_ms={latency_ms:.1f}")
            return None
        _count("timeout" if isinstance(exc, httpx.TimeoutException) else "transport" if isinstance(exc, httpx.HTTPError)
               else "body" if isinstance(exc, ValueError) else "other")
        logger.debug(
            f"OPA query failed: policy={policy_path} err={type(exc).__name__}:{exc} "
            f"latency_ms={latency_ms:.1f}"
        )
        return None
    except Exception as exc:
        # Last-resort guard. Shadow-mode must never bubble up.
        _count("other")
        logger.debug(f"OPA query unexpected error (suppressed): {exc!r}")
        return None
