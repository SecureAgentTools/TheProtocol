"""
MCP OAuth 2.0 Authorization Server — Phase 3 Claude Custom Connector

Implements:
  - RFC 8414: OAuth 2.0 Authorization Server Metadata (/.well-known/oauth-authorization-server)
  - RFC 9728: Protected Resource Metadata (/.well-known/oauth-protected-resource)
  - RFC 7591: Dynamic Client Registration (POST /oauth/register)
  - OAuth 2.1 Authorization Code Flow with PKCE (S256)

Endpoints:
  GET  /.well-known/oauth-authorization-server   — Discovery metadata
  GET  /.well-known/oauth-protected-resource      — Resource metadata
  POST /oauth/register                            — Dynamic client registration
  GET  /oauth/authorize                           — Authorization page (login form)
  POST /oauth/authorize                           — Process login + issue code
  POST /oauth/token                               — Exchange code for access_token
"""
import hashlib
import base64
import json as _json
import os as _os
import secrets
import uuid
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MCP OAuth"])

# ---------------------------------------------------------------------------
# Redis-backed stores with in-memory fallback (multi-worker safe)
# ---------------------------------------------------------------------------

# In-memory fallback (used only when Redis is unavailable)
_mem_clients: Dict[str, Dict[str, Any]] = {}
_mem_codes: Dict[str, Dict[str, Any]] = {}
_mem_refresh: Dict[str, Dict[str, Any]] = {}

# TTLs
# §MCPSCOPE-2 — registration was unauthenticated AND unlimited (measured: 12 of 12
# accepted, none refused). Open DCR is deliberate (MCP clients rely on it), so the
# answer is a limit, not a lock.
#
# 🔴 IT IS NOT DONE WITH @limiter.limit, AND THAT IS THE POINT. I wrote it that way
# first, copying the house pattern, and the battery measured 14 of 14 still accepted.
# SlowAPIMiddleware enforces only what is registered on `app.state.limiter` (main.py's
# enhanced instance); a decorator bound to a router's OWN Limiter() registers into a
# registry nobody consults. That is true of all 67 such decorators in this tree —
# verified separately: /onboard/bootstrap/request-token is marked 20/minute and
# answered 25 of 25. Filed; not fixed here, because flipping 67 dormant limits live
# is its own change with its own blast radius.
#
# So this one is self-contained on the Redis this module already uses. Degrades OPEN
# if Redis is unavailable, matching the rest of the app: a nuisance guard must not
# become an outage.
_REGISTER_LIMIT_PER_HOUR = int(_os.getenv("OAUTH_REGISTER_LIMIT_PER_HOUR", "10"))

_CLIENT_TTL = 86400       # 24 hours
_CODE_TTL = 300           # 5 minutes
_REFRESH_TTL = 2592000    # 30 days
# D6-729: the access token this flow issues IS an API key, and it lives exactly as long as the token response says. The
# code exchange and every refresh set the key's expiry to now + _ACCESS_TOKEN_TTL; /oauth/revoke deactivates it.
_ACCESS_TOKEN_TTL = 86400   # 24 hours: the token response's expires_in
_KEY_NAME_PREFIX = "MCP OAuth ("   # the name of every key this flow mints: "MCP OAuth (<client name>)"


async def _redis():
    """Get Redis connection (None if unavailable)."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        return await get_redis()
    except Exception:
        return None


async def _register_rate_ok(request: Request) -> tuple:
    """(allowed, seen) for unauthenticated client registration, per client IP/hour.

    Uses the EXISTING `_effective_client_ip` rather than a fourth copy of the XFF
    idiom: nginx sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which APPENDS
    the real peer, so the LAST element is the only one a caller cannot forge.
    Reading the FIRST element (the usual idiom) would let anyone rotate a header
    and bypass this entirely.
    """
    r = await _redis()
    if r is None:
        return True, 0
    try:
        from agentvault_registry.routers.agent_mtls import _effective_client_ip
        ip = _effective_client_ip(request) or "unknown"
        key = f"oauth:reg:rate:{ip}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 3600)
        return (n <= _REGISTER_LIMIT_PER_HOUR), n
    except Exception as e:
        logger.warning(f"[MCP OAuth] registration rate check failed, allowing: {e}")
        return True, 0


async def _store_client(client_id: str, data: dict):
    r = await _redis()
    if r:
        await r.setex(f"oauth:client:{client_id}", _CLIENT_TTL, _json.dumps(data))
    else:
        _mem_clients[client_id] = data


async def _get_client(client_id: str) -> Optional[dict]:
    r = await _redis()
    if r:
        raw = await r.get(f"oauth:client:{client_id}")
        return _json.loads(raw) if raw else None
    return _mem_clients.get(client_id)


async def _store_code(code: str, data: dict):
    r = await _redis()
    if r:
        await r.setex(f"oauth:code:{code}", _CODE_TTL, _json.dumps(data))
    else:
        data["expires_at"] = time.time() + _CODE_TTL
        _mem_codes[code] = data


async def _pop_code(code: str) -> Optional[dict]:
    r = await _redis()
    if r:
        raw = await r.getdel(f"oauth:code:{code}")
        return _json.loads(raw) if raw else None
    return _mem_codes.pop(code, None)


async def _store_refresh(token: str, data: dict):
    r = await _redis()
    if r:
        await r.setex(f"oauth:refresh:{token}", _REFRESH_TTL, _json.dumps(data))
    else:
        _mem_refresh[token] = data


async def _get_refresh(token: str) -> Optional[dict]:
    r = await _redis()
    if r:
        raw = await r.get(f"oauth:refresh:{token}")
        return _json.loads(raw) if raw else None
    return _mem_refresh.get(token)


async def _delete_refresh(token: str) -> bool:
    """§pass68 — RFC 7009 revocation primitive. Delete a refresh token from Redis
    (or in-memory fallback). Returns True if the token existed and was deleted,
    False otherwise. Per RFC 7009 §2.2 the server should NOT reveal this to the
    caller — the revoke endpoint always returns 200.
    """
    r = await _redis()
    if r:
        deleted = await r.delete(f"oauth:refresh:{token}")
        return bool(deleted)
    return _mem_refresh.pop(token, None) is not None


async def _delete_refresh_by_api_key(api_key: str) -> int:
    """§pass68 — revoke ALL refresh tokens tied to a specific access_token
    (which in this implementation IS the developer's api_key — see token_exchange
    line 533). Returns count of deleted refresh tokens. Used when the revoke
    endpoint receives token_type_hint=access_token: we don't want to invalidate
    the underlying api_key (it's used elsewhere), but we DO want to revoke
    the OAuth grant — meaning future refresh attempts fail.
    """
    r = await _redis()
    if r:
        deleted = 0
        async for key in r.scan_iter(match="oauth:refresh:*", count=100):
            try:
                raw = await r.get(key)
                if not raw:
                    continue
                data = _json.loads(raw)
                if data.get("api_key") == api_key:
                    if await r.delete(key):
                        deleted += 1
            except Exception:
                continue
        return deleted
    # In-memory fallback
    keys_to_delete = [t for t, data in _mem_refresh.items() if data.get("api_key") == api_key]
    for t in keys_to_delete:
        _mem_refresh.pop(t, None)
    return len(keys_to_delete)


async def _renew_key(api_key: str) -> bool:
    """D6-729: set the OAuth access key's expiry to now + _ACCESS_TOKEN_TTL, the lifetime the token response states.

    False when the key is no longer active (revoked from the console, or by /oauth/revoke): the grant is over. A
    database error is raised for the caller to answer temporarily_unavailable."""
    from sqlalchemy import update
    from ..database import get_db_context
    from .. import models
    from ..security import api_key_lookup_hash
    async with get_db_context() as db:
        row = (await db.execute(
            update(models.DeveloperApiKey)
            .where(models.DeveloperApiKey.key_sha256 == api_key_lookup_hash(api_key),
                   models.DeveloperApiKey.is_active.is_(True))
            .values(expires_at=datetime.now(timezone.utc) + timedelta(seconds=_ACCESS_TOKEN_TTL))
            .returning(models.DeveloperApiKey.id)
        )).first()
        await db.commit()
    return row is not None


async def _revoke_key(api_key: str) -> int:
    """D6-729 (RFC 7009 2.1): revoking either token of a grant ends its access token, which is the API key this flow
    minted. Deactivates the key, only a key this flow minted (named "MCP OAuth (...)"), and disables the push devices it
    registered, as the console's revoke does. Returns 1 when a key was deactivated."""
    from sqlalchemy import update
    from ..database import get_db_context
    from .. import models
    from ..security import api_key_lookup_hash
    from ..services.device_key_link import disable_devices_for_key
    async with get_db_context() as db:
        row = (await db.execute(
            update(models.DeveloperApiKey)
            .where(models.DeveloperApiKey.key_sha256 == api_key_lookup_hash(api_key),
                   models.DeveloperApiKey.is_active.is_(True),
                   models.DeveloperApiKey.description.startswith(_KEY_NAME_PREFIX))   # the key's name
            .values(is_active=False)
            .returning(models.DeveloperApiKey.id, models.DeveloperApiKey.developer_id)
        )).first()
        if row is not None:
            await disable_devices_for_key(db, row[1], row[0])
        await db.commit()
    return 1 if row is not None else 0


def _get_issuer(request: Request) -> str:
    """Derive the issuer URL from the request."""
    # Use X-Forwarded headers if behind nginx, otherwise request.base_url
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    return f"{proto}://{host}"


# ---------------------------------------------------------------------------
# OAuth Metadata Discovery
# ---------------------------------------------------------------------------

@router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    """RFC 8414 — OAuth 2.0 Authorization Server Metadata."""
    issuer = _get_issuer(request)
    return JSONResponse(
        content={
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            # §pass68 — RFC 7009 token revocation endpoint
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "revocation_endpoint_auth_methods_supported": ["none"],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["mcp:tools", "mcp:admin"],
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "mcp-protocol-version",
        },
    )


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request):
    """RFC 9728 — Protected Resource Metadata."""
    issuer = _get_issuer(request)
    return JSONResponse(
        content={
            "resource": f"{issuer}/mcp",
            "authorization_servers": [issuer],
            "scopes_supported": ["mcp:tools", "mcp:admin"],
            "bearer_methods_supported": ["header"],
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "mcp-protocol-version",
        },
    )


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------

def _redirect_host(uri: str) -> str:
    """The host the authorization code will be delivered to, for the human.

    Shown because the destination used to live only in a hidden input: the victim
    saw an attacker-chosen client_name and nothing else. Deliberately the HOST and
    not the full URI - a long path is where a misleading string would hide.
    """
    try:
        p = urlparse(uri or "")
        return (p.hostname or uri or "unknown") + (f":{p.port}" if p.port else "")
    except Exception:
        return uri or "unknown"


def _key_scopes_for(oauth_scope: str) -> list:
    """§MCPSCOPE — the OAuth `scope` becomes what the KEY MAY DO, never '*'.

    Before 2026-08-27 this flow posted a BARE STRING body to /auth/api-keys,
    which takes the AL-4 defaults: scopes ['*'] (full developer authority) and a
    365-day TTL. So `scope=mcp:tools` minted a credential that could do anything
    the owner's password could, for a year, and a password change does not
    revoke an API key (measured in §CMDROTATE). The scope parameter was echoed
    back in the token response and enforced nowhere.
    """
    req = set((oauth_scope or "mcp:tools").split())
    if "mcp:admin" in req:
        return ["mcp:admin", "mcp:tools"]
    return ["mcp:tools"]


@router.post("/oauth/register")
async def register_client(request: Request):
    """Register a new OAuth client dynamically."""
    _allowed, _seen = await _register_rate_ok(request)
    if not _allowed:
        logger.warning(f"[MCP OAuth] registration rate limit hit ({_seen} this hour)")
        return JSONResponse(status_code=429, content={
            "error": "temporarily_unavailable",
            "error_description": f"Too many client registrations from this address (limit {_REGISTER_LIMIT_PER_HOUR}/hour).",
        }, headers={"Retry-After": "3600", "Access-Control-Allow-Origin": "*"})
    body = await request.json()

    redirect_uris = body.get("redirect_uris", [])
    if not redirect_uris:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": "redirect_uris required"})

    # Validate redirect URIs — must be localhost or HTTPS
    for uri in redirect_uris:
        parsed = urlparse(uri)
        if parsed.hostname not in ("localhost", "127.0.0.1") and parsed.scheme != "https":
            return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": f"Redirect URI must be localhost or HTTPS: {uri}"})

    client_id = str(uuid.uuid4())
    client_secret = secrets.token_hex(32)

    await _store_client(client_id, {
        "client_secret": client_secret,
        "redirect_uris": redirect_uris,
        "client_name": body.get("client_name", "MCP Client"),
        "grant_types": body.get("grant_types", ["authorization_code", "refresh_token"]),
        "response_types": body.get("response_types", ["code"]),
        "token_endpoint_auth_method": body.get("token_endpoint_auth_method", "client_secret_post"),
        "created_at": time.time(),
    })

    logger.info(f"[MCP OAuth] Registered client: {client_id} ({body.get('client_name', 'unnamed')})")

    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_id,
            "client_secret": client_secret,
            "client_id_issued_at": int(time.time()),
            "client_secret_expires_at": None,
            "redirect_uris": redirect_uris,
            "client_name": body.get("client_name", "MCP Client"),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "mcp-protocol-version",
        },
    )


# ---------------------------------------------------------------------------
# Authorization Endpoint
# ---------------------------------------------------------------------------

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TheProtocol — Authorize</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', -apple-system, sans-serif;
    background: #05050a;
    color: #e0e0e0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .card {
    background: rgba(10,14,20,0.95);
    border: 1px solid rgba(0,210,210,0.12);
    border-radius: 16px;
    padding: 2.5rem;
    width: 380px;
    box-shadow: 0 0 40px rgba(0,210,210,0.05);
  }
  .brand {
    text-align: center;
    margin-bottom: 2rem;
  }
  .brand-name {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.2em;
    color: rgba(0,210,210,0.8);
    font-family: 'Fira Code', monospace;
  }
  .brand-sub {
    font-size: 0.6rem;
    color: rgba(255,255,255,0.25);
    letter-spacing: 0.1em;
    margin-top: 0.3rem;
  }
  .client-name {
    text-align: center;
    font-size: 0.75rem;
    color: rgba(255,255,255,0.5);
    margin-bottom: 1.5rem;
    padding: 0.5rem;
    background: rgba(0,210,210,0.03);
    border-radius: 6px;
    border: 1px solid rgba(0,210,210,0.06);
  }
  label {
    display: block;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    color: rgba(255,255,255,0.35);
    margin-bottom: 0.4rem;
    text-transform: uppercase;
  }
  input[type="email"], input[type="password"] {
    width: 100%;
    padding: 0.7rem 0.9rem;
    background: rgba(0,210,210,0.03);
    border: 1px solid rgba(0,210,210,0.1);
    border-radius: 8px;
    color: #fff;
    font-size: 0.85rem;
    margin-bottom: 1rem;
    outline: none;
    transition: border-color 0.2s;
    font-family: 'Fira Code', monospace;
  }
  input:focus {
    border-color: rgba(0,210,210,0.4);
  }
  .btn {
    width: 100%;
    padding: 0.75rem;
    background: rgba(0,210,210,0.15);
    border: 1px solid rgba(0,210,210,0.3);
    border-radius: 8px;
    color: rgba(0,210,210,0.9);
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    cursor: pointer;
    transition: all 0.2s;
    text-transform: uppercase;
  }
  .btn:hover {
    background: rgba(0,210,210,0.25);
    border-color: rgba(0,210,210,0.5);
  }
  .error {
    background: rgba(240,70,70,0.1);
    border: 1px solid rgba(240,70,70,0.2);
    color: rgba(240,70,70,0.8);
    padding: 0.6rem;
    border-radius: 6px;
    font-size: 0.75rem;
    margin-bottom: 1rem;
    text-align: center;
  }
  .scope-info {
    text-align: center;
    font-size: 0.6rem;
    color: rgba(255,255,255,0.2);
    margin-top: 1rem;
  }
  /* §MCPSCOPE-2 — the destination was a hidden input, so the one fact that
     distinguishes a real connector from a rogue one was never on screen. */
  .dest {
    border: 1px solid rgba(240,180,70,0.35);
    background: rgba(240,180,70,0.06);
    border-radius: 8px;
    padding: 0.7rem 0.8rem;
    margin-bottom: 1.2rem;
    font-size: 0.72rem;
    line-height: 1.5;
    color: rgba(255,255,255,0.75);
  }
  .dest-label {
    display: block;
    font-size: 0.58rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(240,180,70,0.75);
    margin-bottom: 0.25rem;
  }
  .dest-host { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; color: #fff; }
  .dest-warn { display: block; margin-top: 0.4rem; color: rgba(255,255,255,0.45); }
</style>
</head>
<body>
<div class="card">
  <div class="brand">
    <div class="brand-name">// SOVEREIGN NODE</div>
    <div class="brand-sub">AUTHORIZE MCP CONNECTION</div>
  </div>
  <div class="client-name">{{CLIENT_NAME}} wants to connect</div>
  <div class="dest">
    <span class="dest-label">Your access will be sent to</span>
    <span class="dest-host">{{REDIRECT_HOST}}</span>
    <span class="dest-warn">If you do not recognise this destination, close this page. The name above is chosen by whoever built the client and is not verified by us.</span>
  </div>
  {{ERROR_HTML}}
  <form method="POST" action="/oauth/authorize">
    <input type="hidden" name="client_id" value="{{CLIENT_ID}}">
    <input type="hidden" name="redirect_uri" value="{{REDIRECT_URI}}">
    <input type="hidden" name="code_challenge" value="{{CODE_CHALLENGE}}">
    <input type="hidden" name="code_challenge_method" value="{{CODE_CHALLENGE_METHOD}}">
    <input type="hidden" name="state" value="{{STATE}}">
    <input type="hidden" name="scope" value="{{SCOPE}}">
    <label>Email</label>
    <input type="email" name="email" placeholder="your@email.com" required autofocus>
    <label>Password</label>
    <input type="password" name="password" placeholder="••••••••" required>
    <button type="submit" class="btn">Authorize</button>
  </form>
  <div class="scope-info">Grants access to TheProtocol MCP tools</div>
</div>
</body>
</html>"""


@router.get("/oauth/authorize")
async def authorize_get(
    request: Request,
    client_id: str = "",
    response_type: str = "code",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    redirect_uri: str = "",
    state: str = "",
    scope: str = "mcp:tools",
):
    """Show the login page for OAuth authorization."""
    # Validate client
    client = await _get_client(client_id)
    if not client:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": "Unknown client_id"})

    if response_type != "code":
        return JSONResponse(status_code=400, content={"error": "unsupported_response_type"})

    if not code_challenge:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": "code_challenge required (PKCE)"})

    # Validate redirect_uri
    if redirect_uri and redirect_uri not in client["redirect_uris"]:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": "redirect_uri not registered"})
    if not redirect_uri:
        redirect_uri = client["redirect_uris"][0]

    client_name = client.get("client_name", "MCP Client")

    html = LOGIN_HTML.replace("{{CLIENT_ID}}", client_id)
    html = html.replace("{{CLIENT_NAME}}", client_name)
    html = html.replace("{{REDIRECT_URI}}", redirect_uri)
    html = html.replace("{{REDIRECT_HOST}}", _redirect_host(redirect_uri))
    html = html.replace("{{CODE_CHALLENGE}}", code_challenge)
    html = html.replace("{{CODE_CHALLENGE_METHOD}}", code_challenge_method)
    html = html.replace("{{STATE}}", state)
    html = html.replace("{{SCOPE}}", scope)
    html = html.replace("{{ERROR_HTML}}", "")

    return HTMLResponse(content=html)


@router.post("/oauth/authorize")
async def authorize_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    state: str = Form(""),
    scope: str = Form("mcp:tools"),
):
    """Process login and issue authorization code."""
    # Validate client
    client = await _get_client(client_id)
    if not client:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": "Unknown client_id"})

    # Authenticate the developer via the registry's auth system
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            auth_resp = await http_client.post(
                "http://localhost:8000/api/v1/auth/login",
                data={"username": email, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if auth_resp.status_code != 200:
                # Login failed — show form again with error
                client_name = client.get("client_name", "MCP Client")
                html = LOGIN_HTML.replace("{{CLIENT_ID}}", client_id)
                html = html.replace("{{CLIENT_NAME}}", client_name)
                html = html.replace("{{REDIRECT_URI}}", redirect_uri)
                html = html.replace("{{REDIRECT_HOST}}", _redirect_host(redirect_uri))
                html = html.replace("{{CODE_CHALLENGE}}", code_challenge)
                html = html.replace("{{CODE_CHALLENGE_METHOD}}", code_challenge_method)
                html = html.replace("{{STATE}}", state)
                html = html.replace("{{SCOPE}}", scope)
                html = html.replace("{{ERROR_HTML}}", '<div class="error">Invalid email or password</div>')
                return HTMLResponse(content=html, status_code=200)

            auth_data = auth_resp.json()
            dev_token = auth_data["access_token"]
    except Exception as e:
        logger.error(f"[MCP OAuth] Auth error: {e}")
        return JSONResponse(status_code=500, content={"error": "server_error", "error_description": "Authentication service unavailable"})

    # Generate an API key for the developer (persistent token)
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            key_resp = await http_client.post(
                "http://localhost:8000/api/v1/auth/api-keys",
                json={
                    "key_name": f"{_KEY_NAME_PREFIX}{client.get('client_name', 'Claude')})",
                    "scopes": _key_scopes_for(scope),
                    # D6-729: a day, not the 365-day default, even when the code is never exchanged; the exchange then
                    # sets the exact expiry the token response states
                    "expires_in_days": 1,
                },
                headers={"Authorization": f"Bearer {dev_token}", "Content-Type": "application/json"},
            )
            if key_resp.status_code in (200, 201):
                key_data = key_resp.json()
                api_key = key_data.get("plain_api_key", "")
                logger.info(f"[MCP OAuth] Generated API key for {email}: {api_key[:15]}...")
            else:
                # §MCPSCOPE — FAIL CLOSED. The old fallback handed out `dev_token`,
                # a raw developer JWT with NO scope restriction at all, which
                # defeats the entire point of scoping this flow: the error path
                # was strictly more powerful than the success path. If we cannot
                # mint a correctly-scoped credential we issue nothing.
                logger.error(f"[MCP OAuth] API key creation FAILED ({key_resp.status_code}) for {email} — refusing to issue an unscoped credential")
                return JSONResponse(status_code=503, content={
                    "error": "temporarily_unavailable",
                    "error_description": "Could not issue a scoped credential. Nothing was granted; please retry.",
                })
    except Exception as e:
        logger.error(f"[MCP OAuth] API key creation EXCEPTION ({e}) for {email} — refusing to issue an unscoped credential")
        return JSONResponse(status_code=503, content={
            "error": "temporarily_unavailable",
            "error_description": "Could not issue a scoped credential. Nothing was granted; please retry.",
        })

    # Generate authorization code (stored in Redis with 5-min TTL)
    code = secrets.token_urlsafe(48)
    await _store_code(code, {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scope,
        "api_key": api_key,
        "dev_token": dev_token,
    })

    logger.info(f"[MCP OAuth] Authorization code issued for {email} → client {client_id}")

    # Redirect to client callback
    params = {"code": code}
    if state:
        params["state"] = state
    callback = f"{redirect_uri}?{urlencode(params)}"
    return RedirectResponse(url=callback, status_code=302, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Token Endpoint
# ---------------------------------------------------------------------------

@router.post("/oauth/token")
async def token_exchange(request: Request):
    """Exchange authorization code for access token, or refresh."""
    form = await request.form()
    grant_type = form.get("grant_type", "")

    if grant_type == "authorization_code":
        code = form.get("code", "")
        code_verifier = form.get("code_verifier", "")
        client_id = form.get("client_id", "")

        # Look up authorization code (atomic pop — prevents replay)
        auth_code = await _pop_code(code)
        if not auth_code:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "Invalid or expired authorization code"})

        if auth_code["client_id"] != client_id:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "client_id mismatch"})

        # §MCPSCOPE-2 (2026-08-27) — CLIENT AUTHENTICATION. Measured before this
        # change: a token exchange carrying a DELIBERATELY WRONG client_secret
        # returned HTTP 200, because the secret was generated, returned, stored and
        # then never read again. Client authentication did not exist.
        client = await _get_client(client_id)
        if not client:
            return JSONResponse(status_code=400, content={"error": "invalid_client", "error_description": "Unknown client_id"})
        if (client.get("token_endpoint_auth_method") or "client_secret_post") != "none":
            presented = form.get("client_secret", "") or ""
            expected_secret = client.get("client_secret", "") or ""
            if not presented or not expected_secret or not secrets.compare_digest(presented, expected_secret):
                logger.warning(f"[MCP OAuth] client_secret mismatch for client {client_id}")
                return JSONResponse(status_code=401, content={"error": "invalid_client", "error_description": "Client authentication failed"},
                                    headers={"WWW-Authenticate": "Basic"})

        # §MCPSCOPE-2 — PKCE IS MANDATORY, NOT OPTIONAL.
        # It used to be checked `if code_verifier:`, so omitting the verifier
        # skipped the check entirely (measured: no verifier -> HTTP 200). The
        # challenge is ALWAYS present because /oauth/authorize refuses without
        # one, so a missing verifier can only ever be a downgrade attempt.
        # Together with the missing client auth above, this meant an authorization
        # code was bearer authority: anyone who obtained one inside its 5-minute
        # window could exchange it, holding no secret and no verifier. Codes ride
        # in URLs, so they land in browser history, proxy logs and Referer headers.
        if not code_verifier:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "code_verifier required (PKCE)"})
        expected = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        if not secrets.compare_digest(expected, auth_code.get("code_challenge", "")):
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "Incorrect code_verifier"})

        # D6-729: the key expires when the response below says it does (and a key revoked since the sign-in is no grant)
        try:
            if not await _renew_key(auth_code["api_key"]):
                return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "The authorization was revoked"})
        except Exception as e:  # noqa: BLE001
            logger.error(f"[MCP OAuth] could not set the access token's expiry ({type(e).__name__}); nothing issued")
            return JSONResponse(status_code=503, content={"error": "temporarily_unavailable",
                                                          "error_description": "Could not issue the token; please retry."})

        # Generate refresh token (stored in Redis with 30-day TTL)
        refresh_token = secrets.token_urlsafe(48)
        await _store_refresh(refresh_token, {
            "client_id": client_id,
            "api_key": auth_code["api_key"],
            "scope": auth_code.get("scope", "mcp:tools"),
            "created_at": time.time(),
        })

        logger.info(f"[MCP OAuth] Token issued for client {client_id}")

        return JSONResponse(
            content={
                "access_token": auth_code["api_key"],
                "token_type": "Bearer",
                "expires_in": _ACCESS_TOKEN_TTL,
                "refresh_token": refresh_token,
                "scope": auth_code.get("scope", "mcp:tools"),
            },
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "mcp-protocol-version",
            },
        )

    elif grant_type == "refresh_token":
        refresh = form.get("refresh_token", "")
        token_data = await _get_refresh(refresh)
        if not token_data:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "Invalid refresh token"})

        # §MCPSCOPE-2 — the refresh grant needs client auth for the same reason the
        # code grant does; otherwise a leaked refresh token alone renews forever.
        _rc_id = form.get("client_id", "") or token_data.get("client_id", "")
        if _rc_id != token_data.get("client_id"):
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "client_id mismatch"})
        _rclient = await _get_client(_rc_id)
        if _rclient and (_rclient.get("token_endpoint_auth_method") or "client_secret_post") != "none":
            _rp = form.get("client_secret", "") or ""
            _re = _rclient.get("client_secret", "") or ""
            if not _rp or not _re or not secrets.compare_digest(_rp, _re):
                logger.warning(f"[MCP OAuth] refresh client_secret mismatch for client {_rc_id}")
                return JSONResponse(status_code=401, content={"error": "invalid_client", "error_description": "Client authentication failed"},
                                    headers={"WWW-Authenticate": "Basic"})

        # D6-729: a refresh renews the key for another _ACCESS_TOKEN_TTL; a key revoked meanwhile ends the grant
        try:
            if not await _renew_key(token_data["api_key"]):
                await _delete_refresh(refresh)
                return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "The authorization was revoked"})
        except Exception as e:  # noqa: BLE001
            logger.error(f"[MCP OAuth] could not renew the access token ({type(e).__name__})")
            return JSONResponse(status_code=503, content={"error": "temporarily_unavailable",
                                                          "error_description": "Could not renew the token; please retry."})

        logger.info(f"[MCP OAuth] Token refreshed for client {token_data['client_id']}")

        return JSONResponse(
            content={
                "access_token": token_data["api_key"],
                "token_type": "Bearer",
                "expires_in": _ACCESS_TOKEN_TTL,
                "refresh_token": refresh,
                "scope": token_data.get("scope", "mcp:tools"),
            },
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "mcp-protocol-version",
            },
        )

    return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})


# ---------------------------------------------------------------------------
# Token Revocation Endpoint (RFC 7009)
# ---------------------------------------------------------------------------

@router.post("/oauth/revoke")
async def token_revocation(request: Request):
    """RFC 7009 token revocation for the MCP OAuth connector. Send `token` (form-encoded) and, optionally,
    `token_type_hint` (`refresh_token` or `access_token`). The answer is 200 whether or not the token was valid.
    Revoking a refresh token deletes it; revoking an access token (here, the developer's API key) ends the OAuth grant:
    every refresh token issued for that key is deleted, and the API key itself stays valid. Each revocation is recorded
    in the security audit log.

    \f
    §pass68 (2026-05-23) — RFC 7009 OAuth 2.0 Token Revocation.

    Closes the false claim in Ch12 MCP docs that "OAuth tokens are revocable
    per-client". Now it's true.

    POST application/x-www-form-urlencoded
      token=<the token to revoke>
      token_type_hint=refresh_token | access_token   (optional)

    Per RFC 7009:
      - Server returns HTTP 200 regardless of whether the token was valid
        (don't reveal token validity to a probing caller).
      - Revoking a refresh_token: delete that refresh token, and (D6-729, RFC 7009 2.1) deactivate the access token of
        the same grant: the API key this flow minted for the connector.
      - Revoking an access_token (which in this implementation IS that api_key): deactivate it and delete every
        refresh token of the grant. The key used to stay valid for its whole 365 days after a "revocation".
      Only a key this flow minted ("MCP OAuth (...)") is ever deactivated here; any other token is a no-op.

    The revocation is observable in `security_audit_logs` as a
    `token_revocation` event (existing SecurityEventType).
    """
    form = await request.form()
    token = form.get("token", "").strip()
    hint = (form.get("token_type_hint", "") or "").strip().lower()

    if not token:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "token parameter required"},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    actor_ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    req_id = request.headers.get("x-request-id")

    revoked_count = 0
    revoke_type = "unknown"

    try:
        # Try refresh_token path first if hinted or no hint
        if hint in ("refresh_token", ""):
            _grant = await _get_refresh(token)
            if await _delete_refresh(token):
                revoked_count = 1
                revoke_type = "refresh_token"
                # D6-729: the grant's access token (its API key) ends with it
                if (_grant or {}).get("api_key"):
                    revoked_count += await _revoke_key(_grant["api_key"])

        # If no hint OR hinted access_token, try the access_token path
        if revoked_count == 0 and hint in ("access_token", ""):
            # access_token IS the api_key in this implementation: D6-729 deactivates it, and ends the grant's refreshes
            count = await _delete_refresh_by_api_key(token)
            count += await _revoke_key(token)
            if count > 0:
                revoked_count = count
                revoke_type = "access_token"

        # Audit log entry (best-effort)
        try:
            from ..database import get_db_context
            from ..security_oauth.audit_logger import (
                SecurityEventType,
                security_auditor,
            )
            async with get_db_context() as db:
                await security_auditor.log_event(
                    db=db,
                    event_type=SecurityEventType.TOKEN_REVOCATION,
                    action="revoke",
                    outcome="success" if revoked_count > 0 else "noop",
                    severity="info",
                    actor_type="oauth_client",
                    actor_id=None,
                    actor_ip=actor_ip,
                    target_type=revoke_type,
                    target_id=f"<{len(token)}-char-token>",
                    details={
                        "hint": hint or "none",
                        "revoked_count": revoked_count,
                        "revoke_type": revoke_type,
                    },
                    request_id=req_id,
                    user_agent=ua,
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("token_revocation audit log failed: %s", exc)

        logger.info(
            f"[MCP OAuth] /oauth/revoke processed (hint={hint or 'none'}, "
            f"revoked={revoked_count} of type={revoke_type})"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[MCP OAuth] /oauth/revoke unexpected error: {exc}")
        # Per RFC 7009 §2.2 — still return 200; don't leak server state

    # RFC 7009: always 200, empty body
    return JSONResponse(
        status_code=200,
        content={},
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "mcp-protocol-version, content-type, authorization",
        },
    )


# ---------------------------------------------------------------------------
# CORS preflight for OAuth endpoints
# ---------------------------------------------------------------------------

@router.options("/oauth/token")
@router.options("/oauth/register")
@router.options("/oauth/revoke")
@router.options("/.well-known/oauth-authorization-server")
@router.options("/.well-known/oauth-protected-resource")
async def oauth_cors_preflight():
    return JSONResponse(
        status_code=200,
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, mcp-protocol-version",
        },
    )
