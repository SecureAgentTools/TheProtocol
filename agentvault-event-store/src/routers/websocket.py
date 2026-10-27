"""
WebSocket Router - Handles WebSocket connections and subscriptions

Phase 10 #5 (2026-04-27): added optional shared-secret authentication on the
handshake. When EVENTSTORE_WS_AUTH_REQUIRED=true, the connection MUST present
?token=<INTERNAL_API_KEY> on the URL.

Phase 12.1 (2026-04-28): the token can now alternatively be a JWT-SVID minted
by the reactor's local SPIRE workload. ES detects shape (3 dot-separated
base64 segments → JWT, otherwise opaque shared-secret) and validates against a
JWKS endpoint exposed by the registry. Backwards-compatible: shared-secret
path stays for clients that don't have SPIRE access yet.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from typing import Optional, Tuple
from datetime import datetime, timezone
from src.services.websocket_publisher import connection_manager
from src.client_tls import client_tls_kwargs
from src.personal_ids import withhold_personal_ids
import logging
import json
import os
import time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


def _ws_auth_required() -> bool:
    """Whether /ws/events handshake requires the shared-secret token.
    Defaults to OFF for backwards compatibility — flip to "true" in prod
    once all reactor clients are sending the token."""
    return os.getenv("EVENTSTORE_WS_AUTH_REQUIRED", "false").lower() == "true"


def _expected_token() -> str:
    """The shared secret expected on /ws/events handshake. Same key the
    events.py X-Internal-Key path uses for HTTP auth."""
    return os.getenv("INTERNAL_API_KEY", "")


# Phase 12.1: JWT-SVID validation cache. Stores the parsed JWKS keyed by URL
# with a 5-min TTL. PyJWKClient does its own caching but we re-wrap it here
# so cache TTL is observable and force-refresh on transient failure works.
_JWKS_CACHE: dict = {}
_JWKS_CACHE_TTL = 300  # seconds
# §SECBATCH wave 2: a token is now also read on a store that does not require one (it decides whether a connection gets
# events as stored), so anyone can present one. A fetch the token causes (a refresh for an unknown kid, a retry after a
# failed fetch) happens at most once per spacing per worker, and the algorithm is one a SPIRE JWT-SVID can carry, never
# whatever the token's own header names.
_JWKS_FETCH_SPACING = 30.0  # seconds
_JWKS_FETCH_STATE = {"forced": float("-inf"), "failed": float("-inf")}
_JWT_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"})


def _looks_like_jwt(token: str) -> bool:
    """Heuristic: standard JWS compact serialization is `header.payload.sig`
    with three base64url segments. Anything else is treated as opaque."""
    if not token:
        return False
    segments = token.split(".")
    if len(segments) != 3:
        return False
    # Each segment should be non-empty and contain only base64url chars
    import re
    pattern = re.compile(r"^[A-Za-z0-9_\-]+$")
    return all(pattern.match(s) for s in segments)


def _jwks_url() -> str:
    """JWKS URL for JWT-SVID validation. Default points at the local registry
    container (sandbox A). Override via EVENTSTORE_JWT_JWKS_URL."""
    return os.getenv(
        "EVENTSTORE_JWT_JWKS_URL",
        "http://registry-test:8000/api/v1/spire/jwks",
    )


def _jwt_audience() -> str:
    """Audience claim the reactor mints with. Defaults to a SPIFFE-ish ID for
    the EventStore service."""
    return os.getenv(
        "EVENTSTORE_JWT_AUDIENCE",
        "spiffe://sandbox-a.test/eventstore",
    )


def _validate_jwt(token: str) -> Tuple[bool, str]:
    """Validate a JWT-SVID against the configured JWKS. Returns (ok, info)."""
    try:
        import jwt as pyjwt
        import httpx
    except ImportError as e:
        return False, f"missing dep: {e}"

    url = _jwks_url()
    audience = _jwt_audience()

    cached = _JWKS_CACHE.get(url)
    now = time.monotonic()
    if not cached or now - cached["ts"] > _JWKS_CACHE_TTL:
        if now - _JWKS_FETCH_STATE["failed"] < _JWKS_FETCH_SPACING:
            return False, "jwks_unavailable: the last fetch failed moments ago"
        try:
            resp = httpx.get(url, timeout=5.0, **client_tls_kwargs(url))
            resp.raise_for_status()
            cached = {"jwks": resp.json(), "ts": now}
            _JWKS_CACHE[url] = cached
        except Exception as e:
            _JWKS_FETCH_STATE["failed"] = now
            logger.warning(f"[WS] JWKS fetch failed ({url}): {e}")
            return False, f"jwks_fetch_failed: {e}"

    try:
        unverified = pyjwt.get_unverified_header(token)
    except Exception as e:
        return False, f"unverified_header: {e}"

    kid = unverified.get("kid")
    alg = unverified.get("alg", "RS256")
    if alg not in _JWT_ALGORITHMS:
        return False, f"algorithm_not_allowed: {alg}"
    keys = cached["jwks"].get("keys", [])
    matched = next((k for k in keys if k.get("kid") == kid), None)
    if matched is None:
        # Force-refresh once on kid miss (handles SPIRE rotation faster than TTL), at most once per spacing
        if now - _JWKS_FETCH_STATE["forced"] < _JWKS_FETCH_SPACING:
            return False, f"unknown_kid: {kid}"
        _JWKS_FETCH_STATE["forced"] = now
        try:
            resp = httpx.get(url, timeout=5.0, **client_tls_kwargs(url))
            resp.raise_for_status()
            cached = {"jwks": resp.json(), "ts": now}
            _JWKS_CACHE[url] = cached
            keys = cached["jwks"].get("keys", [])
            matched = next((k for k in keys if k.get("kid") == kid), None)
        except Exception as e:
            return False, f"jwks_refresh_failed: {e}"
    if matched is None:
        return False, f"unknown_kid: {kid}"

    try:
        # PyJWT >= 2.4 exposes PyJWK for parsing a JWK dict directly.
        public_key = pyjwt.PyJWK(matched).key
        decoded = pyjwt.decode(
            token,
            public_key,
            algorithms=[alg],
            audience=audience,
            options={"verify_aud": True, "verify_exp": True},
        )
        spiffe_id = decoded.get("sub", "<no_sub>")
        return True, f"sub={spiffe_id}"
    except pyjwt.ExpiredSignatureError:
        return False, "expired"
    except pyjwt.InvalidAudienceError:
        return False, f"audience_mismatch: expected={audience}"
    except Exception as e:
        return False, f"verify_failed: {e}"


async def _token_is_valid(token: Optional[str]) -> bool:
    """§SECBATCH wave 2: on a store that does not require a token, a presented one still decides whether the connection
    gets events as stored (a valid one: this store's key, or a JWT-SVID it verifies) or with personal ids withheld (none,
    or an invalid one: the connection is public, as every console's is). Never refuses: refusing is
    EVENTSTORE_WS_AUTH_REQUIRED's job. The JWT check fetches the registry's JWKS synchronously, so it runs in a thread."""
    if not token:
        return False
    if _looks_like_jwt(token):
        import asyncio

        try:
            ok, _info = await asyncio.to_thread(_validate_jwt, token)
        except Exception:  # noqa: BLE001  an unverifiable token is no credential
            return False
        return bool(ok)
    from ..internal_key import internal_key_ok  # §KEYROT: current OR previous during a rotation window
    return internal_key_ok(token)


def backlog_message(evt, public: bool) -> dict:
    """One stored event as the backlog sends it; a public connection's copy withholds its personal ids."""
    message = {
        "type": "event",
        "event": {
            "id": str(evt.id),
            "event_type": evt.event_type,
            "aggregate_id": evt.aggregate_id,
            "aggregate_type": evt.aggregate_type,
            "data": evt.data,
            "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
            "version": evt.version,
            "source_service": evt.source_service,
        },
    }
    return withhold_personal_ids(message) if public else message


BACKLOG_SIZE = 15


def backlog_statement(channel: str):
    """The query for the recent events a new subscription is sent, or None when the channel gets no backlog.

    D6-752 (2026-10-16): the backlog follows the channel's key, as the live stream does. events:all gets the last
    events of any type, events:<type> the last of that type, agent:<did> the last of that agent's own events (the ones
    it is the aggregate of; idx_aggregate_timestamp serves the query). An agent:<did> channel used to be sent the last
    events of every agent, and so did any other name; a channel the store publishes no events on (balance:updates, an
    unknown name, a channel with an empty key) now gets none.
    """
    from ..models.db_models import EventModel
    from sqlalchemy import select

    q = select(EventModel).order_by(EventModel.timestamp.desc()).limit(BACKLOG_SIZE)
    if channel == "events:all":
        return q
    kind, _, key = (channel or "").partition(":")
    if not key:
        return None
    if kind == "events":
        return q.where(EventModel.event_type == key)
    if kind == "agent":
        return q.where(EventModel.aggregate_id == key)
    return None


@router.websocket("/events")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Shared-secret auth token (required when EVENTSTORE_WS_AUTH_REQUIRED=true)")
):
    """
    WebSocket endpoint for real-time event notifications.

    Auth (Phase 10 #5):
      - When EVENTSTORE_WS_AUTH_REQUIRED=true, the handshake requires
        `?token=<INTERNAL_API_KEY>` on the URL. Mismatch → 1008 Policy Violation.
      - When EVENTSTORE_WS_AUTH_REQUIRED is unset/false, all connections are
        accepted (backwards-compatible default).
      - §SECBATCH wave 2: a connection that presented no valid credential (this store's key, or a JWT-SVID the store
        verifies) is PUBLIC: every frame's console opens one through its public /ws/events lane. It is sent each event
        with its personal ids withheld (an account id built from an e-mail address becomes an opaque account:<hex>,
        an address is withheld; src/personal_ids.py), it may not subscribe to a channel named by such an id, and its
        stats name no such channel. A connection with a valid credential (the registry's reactors) gets the events as
        stored.

    Clients can subscribe to channels:
    - agent:{did} - Events for a specific agent
    - events:all - All events
    - events:{type} - Events of a specific type

    On each subscribe the channel's last 15 events are sent first (see backlog_statement: that type, that agent's
    own, or any type for events:all; balance:updates gets none).

    Message format for subscriptions:
    {
        "action": "subscribe",
        "channel": "agent:did:cos:123"
    }
    """
    if _ws_auth_required():
        if not token:
            logger.warning("[WS] Rejected — token missing (auth_required=true)")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Phase 12.1: detect token shape — JWT-SVID vs shared secret. Either
        # is acceptable. JWT carries identity + audience claim; shared secret
        # is the legacy stepping stone.
        if _looks_like_jwt(token):
            ok, info = _validate_jwt(token)
            if not ok:
                logger.warning(f"[WS] Rejected — JWT validation failed: {info}")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            logger.info(f"[WS] JWT-SVID accepted ({info})")
        else:
            expected = _expected_token()
            if not expected:
                logger.error(
                    "[WS] EVENTSTORE_WS_AUTH_REQUIRED=true but INTERNAL_API_KEY "
                    "is not set and token is not a JWT — rejecting"
                )
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
                return
            from ..internal_key import internal_key_ok  # §KEYROT: current OR previous during a rotation window
            if not internal_key_ok(token):
                logger.warning("[WS] Rejected — shared-secret mismatch")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        credentialed = True
    else:
        credentialed = await _token_is_valid(token)

    await connection_manager.connect(websocket, public=not credentialed)
    public = not credentialed

    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Event Store WebSocket",
            "available_channels": [
                "agent:{did} - Events for specific agent",
                "events:all - All events",
                "events:{type} - Events of specific type"
            ]
        })
        
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            action = data.get("action")
            channel = data.get("channel")
            
            if action == "subscribe" and channel:
                if not await connection_manager.subscribe(websocket, channel):
                    continue  # refused (a personal channel on a public connection): no subscription, no backlog
                logger.info(f"Client subscribed to {channel}")

                # Backlog replay: send the channel's last events from DB on subscribe
                # (backlog_statement decides which; a channel with none gets none).
                # Runs as a background task so the receive loop is NOT blocked
                # by the DB query (5-10s under sim load). Live events stream
                # immediately; client dedups by event id on merge.
                async def _replay_backlog(ws, q, public):
                    try:
                        from ..database.connection import AsyncSessionLocal

                        async with AsyncSessionLocal() as _db:
                            res = await _db.execute(q)
                            for evt in reversed(res.scalars().all()):
                                await ws.send_json(backlog_message(evt, public))
                    except Exception as e:
                        logger.warning(f"Backlog replay failed (non-fatal): {e}")

                backlog_q = backlog_statement(channel)
                if backlog_q is not None:
                    import asyncio as _asyncio
                    _asyncio.create_task(_replay_backlog(websocket, backlog_q, public))
                
            elif action == "unsubscribe" and channel:
                await connection_manager.unsubscribe(websocket, channel)
                logger.info(f"Client unsubscribed from {channel}")
                
            elif action == "ping":
                # Respond to ping
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
            elif action == "stats":
                # Send connection stats (a public connection's name no personal channel)
                stats = connection_manager.get_stats(public=public)
                await websocket.send_json({
                    "type": "stats",
                    "data": stats
                })
                
            else:
                # Unknown action
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown action: {action}"
                })
                
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        connection_manager.disconnect(websocket)


@router.get("/connections")
async def get_websocket_stats():
    """Get current WebSocket connection statistics (public: a channel named by a personal id is withheld)"""
    return connection_manager.get_stats(public=True)
