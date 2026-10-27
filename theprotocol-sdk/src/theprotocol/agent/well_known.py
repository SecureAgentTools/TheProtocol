"""A2A v1.0 §4.1.2 — Agent Card discovery via /.well-known/agent-card.json.

`serve_well_known_card(app, card_or_fetch_url, ...)` mounts the canonical
discovery routes on a FastAPI app. Two modes:

  1. STATIC — caller passes an `AgentCard` instance; helper serializes it.
  2. FEDERATED — caller passes a `fetch_url` (typically the registry's
     `/api/v1/agents/{did}/card-export`); helper fetches at startup, caches
     in memory, refreshes every `refresh_seconds` seconds.

Routes mounted:
  GET  /.well-known/agent-card.json     (primary, A2A v1.0 §4.1.2)
  GET  /.well-known/agent.json          (legacy alias for older clients)
  OPTIONS /.well-known/agent-card.json  (CORS preflight)
  OPTIONS /.well-known/agent.json

Response headers:
  Content-Type: application/json
  Cache-Control: public, max-age=300, stale-while-revalidate=600
  ETag: "<sha256-hex-truncated>"
  Access-Control-Allow-Origin: *

Registry-canonical fields (federation_metadata, flare, last_pulled_*) are
stripped before serving — agents own their identity, registries own enrichment.

In STATIC mode, `sign_with` signs the served card: it carries a `signatures`
entry (a detached JWS, EdDSA) that `theprotocol.auth.verify_agent_card` checks
against the agent's public key. FEDERATED mode serves the fetched card as is.
"""
# NB: do NOT add `from __future__ import annotations` here — FastAPI introspects
# the route handlers' annotations at registration time, and with stringified
# annotations the `Response` forward ref leaks into pydantic schema generation
# and crashes startup. Annotations must resolve to real types at module load.

import asyncio
import contextlib
import hashlib
import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Union

logger = logging.getLogger(__name__)


# Fields the agent never publishes — these are registry-owned enrichment.
# Per Option C plan §3.1 (ownership split): agent serves identity/transport/auth;
# registry stamps federation_metadata + flare on top during pull-sync.
_REGISTRY_OWNED_FIELDS = frozenset({
    "federation_metadata",
    "flare",
    "last_pulled_at",
    "last_pulled_etag",
})

_CACHE_CONTROL_VALUE = "public, max-age=300, stale-while-revalidate=600"
_DEFAULT_REFRESH_SEC = 3600
_FETCH_TIMEOUT_SEC = 10.0


def _strip_registry_owned(card_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Remove registry-owned fields from a card dict (returns new dict)."""
    return {k: v for k, v in card_dict.items() if k not in _REGISTRY_OWNED_FIELDS}


def _serialize_card(card: Any) -> Dict[str, Any]:
    """Coerce an AgentCard / dict input into a stripped dict.

    Accepts:
      - pydantic AgentCard instance (uses .model_dump(by_alias=True, exclude_none=True))
      - plain dict (used as-is, then stripped)
    """
    if hasattr(card, "model_dump"):
        data = card.model_dump(by_alias=True, exclude_none=True, mode="json")
    elif isinstance(card, dict):
        data = dict(card)
    else:
        raise TypeError(
            f"serve_well_known_card: expected AgentCard or dict, got {type(card).__name__}"
        )
    return _strip_registry_owned(data)


def _compute_etag(body_bytes: bytes) -> str:
    """ETag is the sha256 hex prefix (16 chars) of the serialized body."""
    digest = hashlib.sha256(body_bytes).hexdigest()
    return f'"{digest[:16]}"'


def _serialize_for_wire(card_dict: Dict[str, Any]) -> bytes:
    """Sorted-keys JSON serialization (Phase 9 JWS needs byte-stable input)."""
    return json.dumps(card_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")


class _CardCache:
    """Holds the latest card payload + its ETag.

    Federated mode populates this from the registry; static mode populates it
    once at mount time and never refreshes.
    """

    def __init__(self) -> None:
        self.body: Optional[bytes] = None
        self.etag: Optional[str] = None
        self.last_fetch_ok: bool = False
        self.last_error: Optional[str] = None
        self._lock = asyncio.Lock()

    def set_payload(self, card_dict: Dict[str, Any]) -> None:
        body = _serialize_for_wire(card_dict)
        self.body = body
        self.etag = _compute_etag(body)
        self.last_fetch_ok = True
        self.last_error = None


def _build_handlers(
    cache: _CardCache,
) -> Dict[str, Callable[..., Awaitable[Any]]]:
    """Return the FastAPI route handler callables, bound to the cache.

    Returning a dict keeps the helper testable without importing fastapi
    until call-time.
    """
    from fastapi import Header
    from fastapi.responses import JSONResponse, Response

    _CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "If-None-Match, Accept",
        "Access-Control-Max-Age": "86400",
    }

    async def get_card(
        if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    ) -> Response:
        if cache.body is None:
            # Federated startup-fetch failed; signal "not yet ready" per §3.4
            # (the spec-compliant alternative to 404 is 503 + Retry-After).
            return JSONResponse(
                status_code=503,
                content={
                    "error": "agent card temporarily unavailable",
                    "reason": cache.last_error or "card not yet loaded",
                },
                headers={**_CORS_HEADERS, "Retry-After": "30"},
            )

        # 304 short-circuit
        if if_none_match and cache.etag and if_none_match == cache.etag:
            return Response(
                status_code=304,
                headers={
                    **_CORS_HEADERS,
                    "ETag": cache.etag,
                    "Cache-Control": _CACHE_CONTROL_VALUE,
                },
            )

        return Response(
            status_code=200,
            content=cache.body,
            media_type="application/json",
            headers={
                **_CORS_HEADERS,
                "ETag": cache.etag or "",
                "Cache-Control": _CACHE_CONTROL_VALUE,
            },
        )

    async def options_card() -> Response:
        return Response(status_code=200, headers=_CORS_HEADERS)

    return {"GET": get_card, "OPTIONS": options_card}


async def _fetch_card_from_url(
    fetch_url: str,
    fetch_headers: Optional[Mapping[str, str]],
    cache: _CardCache,
) -> None:
    """Federated mode: pull the card from the registry's card-export endpoint."""
    try:
        import httpx
    except ImportError as exc:
        cache.last_error = f"httpx not installed: {exc}"
        logger.error("serve_well_known_card federated mode requires httpx: %s", exc)
        return

    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SEC, verify=True) as client:
            resp = await client.get(fetch_url, headers=dict(fetch_headers or {}))
        if resp.status_code != 200:
            cache.last_error = f"upstream {resp.status_code}"
            logger.warning(
                "serve_well_known_card: federated fetch %s returned %s",
                fetch_url, resp.status_code,
            )
            return
        upstream = resp.json()
        if not isinstance(upstream, dict):
            cache.last_error = "upstream returned non-object body"
            return
        stripped = _strip_registry_owned(upstream)
        cache.set_payload(stripped)
        logger.info(
            "serve_well_known_card: federated fetch succeeded — etag=%s len=%d",
            cache.etag, len(cache.body or b""),
        )
    except Exception as exc:
        cache.last_error = f"fetch failed: {exc.__class__.__name__}: {exc}"
        logger.warning("serve_well_known_card: federated fetch error: %s", exc)


def _start_refresh_loop(
    fetch_url: str,
    fetch_headers: Optional[Mapping[str, str]],
    cache: _CardCache,
    refresh_seconds: int,
) -> Callable[[], Awaitable[None]]:
    """Build a startup hook that fetches once + spawns a refresh task."""

    async def startup() -> None:
        await _fetch_card_from_url(fetch_url, fetch_headers, cache)

        async def loop() -> None:
            while True:
                await asyncio.sleep(refresh_seconds)
                await _fetch_card_from_url(fetch_url, fetch_headers, cache)

        asyncio.create_task(loop())

    return startup


def _register_startup(app: Any, hook: Callable[[], Awaitable[None]]) -> None:
    """Register an async startup hook across FastAPI/Starlette generations.

    FastAPI < 0.139 exposes the classic ``add_event_handler`` API. FastAPI
    0.139+ (Starlette 1.x) removed it in favor of lifespan contexts, but the
    router still carries an ``on_startup`` list consumed by its default
    lifespan. Try each in order; the final fallback wraps the router's
    lifespan context so the hook runs before serving, preserving any
    user-supplied lifespan.
    """
    if hasattr(app, "add_event_handler"):
        app.add_event_handler("startup", hook)
        return

    router = getattr(app, "router", None)
    on_startup = getattr(router, "on_startup", None)
    if on_startup is not None:
        on_startup.append(hook)
        return

    if router is not None and hasattr(router, "lifespan_context"):
        existing = router.lifespan_context

        @contextlib.asynccontextmanager
        async def _wrapped(app_: Any):
            await hook()
            async with existing(app_) as state:
                yield state

        router.lifespan_context = _wrapped
        return

    raise RuntimeError(
        "serve_well_known_card: could not register a startup hook on this app "
        "(no add_event_handler / router.on_startup / router.lifespan_context)."
    )


def serve_well_known_card(
    app: Any,
    card: Any = None,
    *,
    fetch_url: Optional[str] = None,
    fetch_headers: Optional[Mapping[str, str]] = None,
    refresh_seconds: int = _DEFAULT_REFRESH_SEC,
    sign_with: Optional[Dict[str, str]] = None,
    primary_path: str = "/.well-known/agent-card.json",
    legacy_path: str = "/.well-known/agent.json",
) -> None:
    """Mount A2A v1.0 §4.1.2 discovery routes on a FastAPI app.

    Args:
        app: a FastAPI application instance.
        card: an `AgentCard` instance or plain dict (STATIC mode). Mutually
            exclusive with `fetch_url`.
        fetch_url: a URL that returns the agent's card JSON. (FEDERATED mode.)
            Typically `https://api.theprotocol.cloud/api/v1/agents/{did}/card-export`.
            Mutually exclusive with `card`.
        fetch_headers: optional headers to include on each federated fetch
            (e.g., `{"Authorization": "Bearer ..."}`).
        refresh_seconds: how often to re-fetch in federated mode. Default 3600.
        sign_with: STATIC mode only: `{"private_pem": "<Ed25519 private key,
            PEM>", "kid": "did:...#1"}` signs the served card. A key that cannot
            be used is logged as a warning and the card is served unsigned.
            FEDERATED mode ignores it.
        primary_path: route path for the canonical well-known. Default per spec.
        legacy_path: backward-compat alias path. Default `/.well-known/agent.json`.

    Behavior:
        - STATIC: the card is serialized once at mount time, stored in memory,
          served unchanged for the life of the process. To change the card,
          restart the agent (consistent with §4.1.2 cache semantics).
        - FEDERATED: an asyncio startup hook fetches the card, then a refresh
          task re-fetches every `refresh_seconds`. If fetch fails, the route
          returns 503 + `Retry-After: 30`.
        - Both modes strip `federation_metadata` and `flare` (registry-owned)
          before serving.
        - ETag is the truncated sha256 of the wire body. Clients can `If-None-Match`
          for 304.
        - Sets `Cache-Control: public, max-age=300, stale-while-revalidate=600`
          so CDNs can cache.
        - CORS `Access-Control-Allow-Origin: *` (the well-known is public
          discovery data, no security risk).
        - STATIC with `sign_with`: the stripped card is signed with
          `theprotocol.auth.sign_agent_card` (RFC 7515 detached JWS, EdDSA),
          the served payload carries the `signatures[]` array, and the ETag is
          computed on the signed body. `verify_agent_card(card, public_jwk)`
          checks it.
    """
    if (card is None) == (fetch_url is None):
        raise ValueError(
            "serve_well_known_card: pass exactly one of `card=` (static) or "
            "`fetch_url=` (federated)."
        )

    cache = _CardCache()

    if card is not None:
        # STATIC mode — serialize once.
        card_dict = _serialize_card(card)
        if sign_with is not None:
            try:
                from ..auth.jws_card import sign_agent_card
                card_dict = sign_agent_card(
                    card_dict,
                    private_pem=sign_with["private_pem"],
                    kid=sign_with["kid"],
                )
                logger.info(
                    "serve_well_known_card: signed card with kid=%s",
                    sign_with["kid"],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "serve_well_known_card: sign_with failed (%s) — serving unsigned",
                    e,
                )
        cache.set_payload(card_dict)
    else:
        # FEDERATED mode — register startup hook for initial fetch + refresh loop.
        startup = _start_refresh_loop(fetch_url, fetch_headers, cache, refresh_seconds)
        _register_startup(app, startup)

    handlers = _build_handlers(cache)
    app.add_api_route(primary_path, handlers["GET"], methods=["GET"])
    app.add_api_route(primary_path, handlers["OPTIONS"], methods=["OPTIONS"])
    app.add_api_route(legacy_path, handlers["GET"], methods=["GET"])
    app.add_api_route(legacy_path, handlers["OPTIONS"], methods=["OPTIONS"])

    logger.info(
        "serve_well_known_card: mounted %s + %s (mode=%s)",
        primary_path, legacy_path, "static" if card is not None else "federated",
    )


__all__ = ["serve_well_known_card"]
