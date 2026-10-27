"""
MCP Auth Bridge — Maps MCP authorization_token values to TheProtocol sessions.

MCP clients pass an Authorization: Bearer <token> header when making requests.
This module validates the token and extracts the developer or agent identity,
returning a structured MCPAuthContext that tools use for access control.

Supported token formats (tried in order):
  1. Developer JWT (from POST /api/v1/auth/login)      → developer context
  2. Agent JWT (from POST /api/v1/auth/agent/token)    → agent context
  3. API Key (from /api/v1/auth/api-keys)              → developer context
  4. No token                                           → anonymous context (Tier 1 only)

Auth Tiers:
  - anonymous   → Tier 1 tools only (discovery, stats)
  - developer   → Tier 1 + Tier 3 tools
  - agent       → Tier 1 + Tier 2 tools
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

import httpx
import jwt  # PyJWT (§DEPS: python-jose is gone)
from jwt import PyJWTError as JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..crud import agent as agent_crud
from ..crud import developer as developer_crud

logger = logging.getLogger(__name__)

# ── §EXTMTLS (2026-08-09) — originating client address for MCP-driven calls ──
# MCP tools reach the registry over loopback (REGISTRY_SELF_URL), so a handler
# downstream cannot tell where the real caller is. The HTTP entry point records
# it here and tools that care forward it as X-Forwarded-For on their internal
# call. Contextvars are per-task, so concurrent MCP requests cannot bleed into
# each other. Default None means "unknown" — never a fabricated address.
import contextvars as _contextvars

_MCP_CLIENT_IP: "_contextvars.ContextVar[Optional[str]]" = _contextvars.ContextVar(
    "mcp_client_ip", default=None
)


def set_mcp_client_ip(ip: Optional[str]) -> None:
    _MCP_CLIENT_IP.set(ip or None)


def get_mcp_client_ip() -> Optional[str]:
    return _MCP_CLIENT_IP.get()


_MCP_CAP_TOKEN: "_contextvars.ContextVar[Optional[str]]" = _contextvars.ContextVar(
    "mcp_capability_token", default=None
)


def set_mcp_capability_token(tok: Optional[str]) -> None:
    """B6 (RBAC plan) — stash the caller's att_ capability token for this MCP request.

    Set at the transport (X-Capability-Token header on the rpc POST) and overridable
    per tools/call via a `capability_token` argument. Read back by
    :func:`mcp_forwarded_headers`, so every internal REST call a tool makes carries the
    token and the EXISTING L4 caveat seam (enforce_agent_spend) finally sees it —
    before this, a capability presented over MCP was silently dropped."""
    _MCP_CAP_TOKEN.set((tok or "").strip() or None)


def get_mcp_capability_token() -> Optional[str]:
    return _MCP_CAP_TOKEN.get()


def mcp_forwarded_headers() -> dict:
    """Headers every internal (tool → own REST API) call must forward:
    the real client IP (§EXTMTLS) and, when presented, the capability token (B6)."""
    h: dict = {}
    ip = get_mcp_client_ip()
    if ip:
        h["X-Forwarded-For"] = ip
    cap = get_mcp_capability_token()
    if cap:
        h["X-Capability-Token"] = cap
    return h


# ── D6-514 — the MCP relay proof on a tool's own REST calls ──
# A key scoped to MCP (an MCP OAuth client's 'mcp:tools', a paired phone's) reaches a REST route only when this
# registry's own MCP server relays the call (security.mcp_key_route_refusal). Every tool module builds its httpx client
# with mcp_http_client, whose request hook adds the relay proof for the API key a call carries, and only on a call to
# this registry itself; a JWT, or a call to any other host, gets nothing.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_this_registry(url: "httpx.URL") -> bool:
    host = (url.host or "").lower()
    if host in _LOOPBACK_HOSTS:
        return True
    own = urlsplit(getattr(settings, "REGISTRY_SELF_URL", None) or "http://localhost:8000")
    return (host == (own.hostname or "").lower()
            and (url.port or _DEFAULT_PORTS.get(url.scheme)) == (own.port or _DEFAULT_PORTS.get(own.scheme or "")))


async def _add_mcp_relay_proof(request: "httpx.Request") -> None:
    scheme, _, credential = (request.headers.get("authorization") or "").partition(" ")
    credential = credential.strip()
    if scheme.lower() != "bearer" or not credential.startswith("avreg_") or not _is_this_registry(request.url):
        return
    from agentvault_registry.security import MCP_RELAY_HEADER, mcp_relay_proof
    request.headers[MCP_RELAY_HEADER] = mcp_relay_proof(credential)


def mcp_http_client(**kwargs) -> "httpx.AsyncClient":
    """D6-514: the httpx.AsyncClient every MCP tool module uses (the same arguments), with the relay-proof hook."""
    hooks = dict(kwargs.pop("event_hooks", None) or {})
    hooks["request"] = [*hooks.get("request", []), _add_mcp_relay_proof]
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)


# JWT configuration — same as security.py
SECRET_KEY = settings.API_KEY_SECRET
ALGORITHM = "HS256"


@dataclass
class MCPAuthContext:
    """
    Represents the authenticated identity of an MCP client.

    Fields:
        auth_type       : "developer" | "agent" | "anonymous"
        developer_id    : Internal developer ID (int) for developer context
        agent_did       : Agent DID string for agent context
        agent_id        : Internal agent ID (int) for agent context
        is_admin        : True if developer has admin flag
        raw_token       : Original token string for pass-through to internal HTTP calls
    """
    auth_type: str = "anonymous"
    developer_id: Optional[int] = None
    agent_did: Optional[str] = None
    agent_id: Optional[int] = None
    is_admin: bool = False
    raw_token: Optional[str] = None

    @property
    def is_developer(self) -> bool:
        return self.auth_type == "developer"

    @property
    def is_agent(self) -> bool:
        return self.auth_type == "agent"

    @property
    def is_anonymous(self) -> bool:
        return self.auth_type == "anonymous"


class MCPAuthUnavailable(Exception):
    """§MCPTEST30 (V0529, 2026-10-01): the credential could not be CHECKED: the database did not answer. Not the caller's
    credential, so never "authentication required": the servers answer -32003 with HTTP 503 and Retry-After. Before this,
    a valid API key read as anonymous whenever its lookup failed (the bridge's catch-all), and a developer JWT's lookup
    error escaped as -32603 carrying the driver's words; agentvault2-21 measured the REST half on sbx-alpha (16:55Z, "too
    many clients already" turned a valid admin bearer into 401, and the console signed out)."""


class MCPAuthError(Exception):
    """Raised when token validation fails for a tier that requires auth."""
    pass


async def authenticate_mcp_token(
    token: Optional[str],
    db: AsyncSession
) -> MCPAuthContext:
    """The token's auth context; MCPAuthUnavailable when the database could not answer the check (§MCPTEST30 V0529)."""
    try:
        return await _authenticate_mcp_token(token, db)
    except SQLAlchemyError as e:
        logger.error(f"MCP auth: the credential store could not answer ({type(e).__name__})")
        raise MCPAuthUnavailable("The registry cannot check credentials right now; try again shortly.") from e


async def _authenticate_mcp_token(
    token: Optional[str],
    db: AsyncSession
) -> MCPAuthContext:
    """
    Validates an MCP authorization token and returns an auth context.

    Steps:
        1. If no token → return anonymous context
        2. Try decode as developer JWT (sub = int, no type = "agent")
        3. Try decode as agent JWT (type = "agent", sub = DID, agent_id present)
        4. Try lookup as programmatic API key via developer_crud
        5. If all fail → return anonymous (tools will enforce auth tier as needed)

    Args:
        token : Bearer token string (from Authorization header), or None
        db    : Async DB session

    Returns:
        MCPAuthContext instance
    """
    if not token:
        logger.debug("MCP auth: no token provided — anonymous context")
        return MCPAuthContext(auth_type="anonymous")

    # --- Attempt 1: Developer JWT ---
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # D6-731: the REST verifier's rules, asked through its own helpers (security.access_token_subject and
        # security.token_version_current), not a copy of them: a developer ACCESS token only (a refresh token, a
        # password-set token or the 2FA login's partial token is none), and a revoked token_version reads as anonymous.
        # A database error is raised here and answered as MCPAuthUnavailable by authenticate_mcp_token.
        from agentvault_registry.security import access_token_subject, token_version_current
        _dev_id = access_token_subject(payload)
        if _dev_id is not None and not await token_version_current(db, _dev_id, payload.get("tv")):
            logger.info(f"MCP auth: developer token for {_dev_id} carries a revoked token_version — rejecting")
            return MCPAuthContext(auth_type="anonymous")

        if _dev_id is not None:
            try:
                developer_id = _dev_id
                # Look up developer to confirm existence and get admin flag. §MCPTEST30 (V0553): its own row only (every
                # MCP call loaded each card and key the developer owns here, and again in the route), and the STRICT
                # lookup: a database error must reach authenticate_mcp_token as MCPAuthUnavailable (V0529's 503).
                # get_developer_by_id swallowed it to None, so the 503 its test asserted (by patching the lookup to
                # raise) never happened: the token read as a developer that does not exist.
                developer = await developer_crud.get_developer_by_id_strict(
                    db=db, developer_id=developer_id
                )
                if developer:
                    # P23-003: deny suspended / soft-deleted developers (parity with
                    # OPA agentvault_developer.rego + HTTP get_current_developer).
                    if getattr(developer, "is_suspended", False) or getattr(developer, "deleted_at", None) is not None:
                        logger.warning(f"MCP auth: developer {developer_id} suspended/deleted — rejecting")
                        return MCPAuthContext(auth_type="anonymous")
                    logger.debug(f"MCP auth: developer JWT valid, developer_id={developer_id}")
                    # D6-621: admin over MCP only while the account meets REQUIRE_ADMIN_2FA (as require_admin_flag asks)
                    from agentvault_registry.security import admin_second_factor_ok
                    return MCPAuthContext(
                        auth_type="developer",
                        developer_id=developer_id,
                        is_admin=bool(getattr(developer, "is_admin", False)) and admin_second_factor_ok(developer),
                        raw_token=token
                    )
                else:
                    logger.debug(f"MCP auth: developer JWT valid but developer {developer_id} not found in DB")
            except (ValueError, TypeError):
                pass  # sub is not an int — not a developer JWT
    except JWTError:
        pass  # Not a valid developer JWT, try next

    # --- Attempt 2: Agent JWT ---
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("type")
        agent_did = payload.get("sub")
        agent_id_raw = payload.get("agent_id")

        if token_type == "agent" and agent_did and agent_id_raw:
            try:
                agent_id = int(agent_id_raw)
                # P23-003: deny suspended / revoked agents (parity with OPA
                # agentvault_agent.rego). Lookup confirms current DB status —
                # JWT alone is not a sufficient liveness signal post-suspension.
                agent = await agent_crud.get_agent_by_did(db=db, did=agent_did)
                if agent is None:
                    logger.warning(f"MCP auth: agent JWT valid but agent {agent_did} not in DB — rejecting")
                    return MCPAuthContext(auth_type="anonymous")
                if getattr(agent, "status", "active") in ("suspended", "revoked"):
                    logger.warning(f"MCP auth: agent {agent_did} status={agent.status} — rejecting")
                    return MCPAuthContext(auth_type="anonymous")
                # §FEFRAME W3: an owner session token ends with the session that minted it; D6-281: a token minted
                # from the agent's credential ends when that credential is reset or rotated (agent_token_refusal)
                from agentvault_registry.security import agent_token_refusal
                _owner_why = await agent_token_refusal(db, payload, agent)
                if _owner_why:
                    logger.warning(f"MCP auth: agent token for {agent_did} refused ({_owner_why}) — rejecting")
                    return MCPAuthContext(auth_type="anonymous")
                logger.debug(f"MCP auth: agent JWT valid, agent_did={agent_did}")
                return MCPAuthContext(
                    auth_type="agent",
                    agent_did=agent_did,
                    agent_id=agent_id,
                    raw_token=token
                )
            except (ValueError, TypeError):
                pass
    except JWTError:
        pass  # Not a valid agent JWT

    # --- Attempt 3: Programmatic API Key ---
    try:
        developer = await developer_crud.get_developer_by_plain_api_key(
            db=db, plain_key=token
        )
        if developer:
            # P23-003: same gate as developer-JWT path.
            if getattr(developer, "is_suspended", False) or getattr(developer, "deleted_at", None) is not None:
                logger.warning(f"MCP auth: API key resolved to suspended/deleted developer {developer.id} — rejecting")
                return MCPAuthContext(auth_type="anonymous")
            # §MCPSCOPE (2026-08-27) — the REST surface enforces key scope at
            # require_admin_flag; MCP has its OWN admin gate (require_admin_auth
            # reads ctx.is_admin), so the same predicate has to be asked HERE
            # too or the tools_admin surface stays wide open to a scoped key.
            # Same class as §FANOUTFIX: one question, asked everywhere it matters.
            # D6-621: admin only while the account meets REQUIRE_ADMIN_2FA, whatever the credential
            # D6-715: the REST gates' own lookup (security.presented_key_scopes), failing CLOSED: a row it cannot
            # read is no scope, so no admin (this used to leave is_admin as it was); a database error is raised and
            # answered as MCPAuthUnavailable.
            from agentvault_registry.security import (
                admin_second_factor_ok, key_reaches_mcp, presented_key_scopes, scopes_grant_admin,
            )
            _sc, _ = await presented_key_scopes(db, token)
            # SEC-10: a narrow key that holds no MCP scope (a paired phone's 'pocket:device' alone) is not an MCP
            # credential: the MCP endpoints treat it as no credential at all
            if not key_reaches_mcp(_sc):
                logger.warning(f"[MCPSCOPE] the key of developer {developer.id} is not an MCP credential "
                               f"(scopes={_sc}): anonymous")
                return MCPAuthContext(auth_type="anonymous")
            _is_admin = bool(getattr(developer, "is_admin", False)) and admin_second_factor_ok(developer)
            if _is_admin and not scopes_grant_admin(_sc):
                logger.warning(
                    f"[MCPSCOPE] MCP admin withheld for developer {developer.id}: "
                    f"credential scopes={_sc}"
                )
                _is_admin = False
            logger.debug(f"MCP auth: API key valid, developer_id={developer.id}, is_admin={_is_admin}")
            return MCPAuthContext(
                auth_type="developer",
                developer_id=developer.id,
                is_admin=_is_admin,
                raw_token=token
            )
    except SQLAlchemyError:
        raise   # §MCPTEST30 V0529: a lookup the database could not answer is not "no such key" (authenticate_mcp_token)
    except Exception as e:
        logger.debug(f"MCP auth: API key lookup failed: {e}")

    # --- Fallback: Anonymous ---
    logger.debug("MCP auth: token provided but all validation attempts failed — anonymous context")
    return MCPAuthContext(auth_type="anonymous")


def require_developer_auth(ctx: MCPAuthContext) -> None:
    """
    Raises MCPAuthError if context is not developer-level.
    Call at the top of Tier 3 tool functions.
    """
    if not ctx.is_developer:
        raise MCPAuthError(
            "This tool requires developer authentication. "
            "Provide a developer JWT from POST /api/v1/auth/login "
            "as the Bearer token in the Authorization header."
        )


def require_agent_auth(ctx: MCPAuthContext) -> None:
    """
    Raises MCPAuthError if context is not agent-level.
    Call at the top of Tier 2 tool functions.
    """
    if not ctx.is_agent:
        raise MCPAuthError(
            "This tool requires agent authentication. "
            "Provide an agent JWT from POST /api/v1/auth/agent/token "
            "as the Bearer token in the Authorization header."
        )


def format_tool_exception(e: BaseException) -> str:
    """Render an exception for an MCP tool's ``{"error": ...}`` payload.

    §MCPTEST-MCP10 (2026-08-08). Every wrapper's ``except`` arm used to return
    ``{"error": str(e)}``. That is silently useless for the single most common
    failure an MCP client actually meets — a timeout — because **httpx's
    timeout and network exceptions carry an empty message**::

        str(httpx.ReadTimeout(''))    == ''
        str(httpx.ConnectTimeout('')) == ''
        str(httpx.PoolTimeout(''))    == ''
        str(httpx.ReadError(''))      == ''

    so the caller received ``{"error": ""}`` and the MCP dispatcher rendered
    the bare string ``"Error: "``. The tool had failed, the transport said 200,
    and the payload named neither the cause nor the tool. Measured on
    ``operatorPortalSelfLogs``: a 23 s read timeout surfaced as ``"Error: "``,
    indistinguishable from a wrapper argument-validation refusal.

    Always yields a non-empty string: the exception's own message when it has
    one, else its class name. The class name alone is enough to separate "the
    call timed out" from "the wrapper rejected your arguments", which is the
    distinction the empty string destroyed.
    """
    msg = safe_exception_text(e).strip()
    cls = type(e).__name__
    return f"{cls}: {msg}" if msg else cls


def safe_exception_text(e: BaseException) -> str:
    """str(e), unless it carries a database driver's own words (§MCPTEST30 V0529: V0525's errors.withheld_db_words, on the
    MCP envelope). A tool's own database call that fails, or an exception that reaches a server's last-resort handler,
    used to hand the caller the SQL statement, a parameter's value, a table name. The words are logged, never returned;
    a database that could not take the call says so ("busy; try again")."""
    text = str(e)
    from agentvault_registry.errors import _DB_ERROR_WORDS, db_capacity_error
    if isinstance(e, SQLAlchemyError) or _DB_ERROR_WORDS.search(text):
        logger.error(f"MCP: a database error withheld from the caller: {text[:500]}")
        return ("the registry's database is busy; try again shortly" if db_capacity_error(text)
                else "a database error occurred")
    return text
