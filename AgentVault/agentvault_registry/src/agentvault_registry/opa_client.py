"""
OPA (Open Policy Agent) HTTP client.

Sandbox-only shadow-mode integration shipped 2026-04-30. Master kill switch is
``OPA_ENABLED`` env (default false) — when off, ``query_opa`` short-circuits
before any network call so the registry has zero OPA overhead.

Production registries set OPA_ENABLED=false explicitly as defense in depth.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from agentvault_registry.es_ssl_helper import get_httpx_verify, spire_trust_loaded, svid_stamp

logger = logging.getLogger(__name__)

_DEFAULT_OPA_URL = "http://opa:8181"
_DEFAULT_TIMEOUT_SECONDS = 1.0

_client: Optional[httpx.AsyncClient] = None
_client_stamp: tuple = ()


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
        try:
            await stale.aclose()
        except Exception as exc:
            logger.debug(f"OPA client close after an SVID rotation (non-fatal): {exc}")
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
    try:
        client = await get_client()
        resp = await client.post(url, json={"input": input_data})
        latency_ms = (time.perf_counter() - started) * 1000.0
        if resp.status_code != 200:
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
    except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        logger.debug(
            f"OPA query failed: policy={policy_path} err={type(exc).__name__}:{exc} "
            f"latency_ms={latency_ms:.1f}"
        )
        return None
    except Exception as exc:
        # Last-resort guard. Shadow-mode must never bubble up.
        logger.debug(f"OPA query unexpected error (suppressed): {exc!r}")
        return None
