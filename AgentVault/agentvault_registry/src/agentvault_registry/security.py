import secrets
import hashlib
import hmac
import contextvars
import logging
import os
import uuid
# --- ADDED: Imports for JWT and datetime ---
from datetime import datetime, timedelta, timezone
# --- MODIFIED: Added Optional, Any, List ---
from typing import Optional, Any, List, Tuple
# --- END MODIFIED ---
import jwt  # PyJWT (§DEPS: python-jose is gone)
from jwt import PyJWTError as JWTError
# --- END ADDED ---
# §DEPS (2026-09-28): passlib is gone; bcrypt is called in one place, core/secret_hash.py, with passlib's rules.
from agentvault_registry.core.secret_hash import hash_secret, verify_secret
from typing import Optional # Added Optional

# --- FastAPI Imports ---
# --- MODIFIED: Added Header ---
from fastapi import Depends, HTTPException, status, Header, Security, Request
from sqlalchemy.exc import SQLAlchemyError
# --- END MODIFIED ---
# --- MODIFIED: Import OAuth2PasswordBearer ---
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
# --- END MODIFIED ---


# --- SQLAlchemy Imports ---
from sqlalchemy.ext.asyncio import AsyncSession
# --- ADDED: Import select and func for API key update ---
from sqlalchemy import select, update, func, and_, text
# --- END ADDED ---


# --- Local Imports ---
# Fix the imports to use absolute paths instead of relative
from agentvault_registry import models
from agentvault_registry.database import get_db
# --- MODIFIED: Import specific CRUD functions ---
from agentvault_registry.crud import developer as developer_crud # Use alias
from agentvault_registry.crud import agent as agent_crud # For agent authentication
# --- END MODIFIED ---
# --- ADDED: Import settings ---
from agentvault_registry.config import settings
# --- END ADDED ---


logger = logging.getLogger(__name__)

# IRONKEY (DEBUG-2026-07-18 finding#2) — per-request on-behalf-of principal, set by
# ``require_agent_permission`` and read by ``enforce_agent_spend`` so cross-registry
# delegation caveats (max_per_tx / allowed_currencies) can be enforced on the spend path
# WITHOUT threading act_principal through every money endpoint. Per-request: the gate runs
# in the same task/context as the handler that calls enforce_agent_spend, so the value
# propagates; default None = self-acting (no delegation caveat applies).
import contextvars as _contextvars
_ACT_PRINCIPAL: "_contextvars.ContextVar[Optional[str]]" = _contextvars.ContextVar(
    "ironkey_act_principal", default=None)

try:  # metrics are optional; their absence must never change a decision
    from prometheus_client import Counter as _AuthzCounter
    AUTHZ_READ_FAILED_TOTAL = _AuthzCounter(
        "agent_authz_read_failed_total",
        "IRONKEY policy reads that raised, by site and mode (under enforce each one refused its request)",
        ["site", "mode"],
    )
except Exception:  # pragma: no cover
    AUTHZ_READ_FAILED_TOTAL = None


def _authz_read_failed(site: str, mode: str, did: Any, exc: BaseException, what: str = "") -> None:
    """§SECFIX-1 (2026-09-25): an IRONKEY policy read raised. Under ``enforce`` the request is REFUSED with a 503 and
    nothing is done; in ``shadow`` it is logged and the request proceeds, because observing is what shadow is for (and
    shadow is the kill switch for enforce). These reads used to fail OPEN in every mode: a database error while
    resolving an agent's permissions, its spend policy, its org ceiling or a delegation's caveats authorized the
    request (the architecture audit of 2026-09-25). Counted in both modes."""
    logger.warning("[AGENT-RBAC] %s read failed mode=%s did=%s%s: %r", site, mode, did, f" {what}" if what else "", exc)
    if AUTHZ_READ_FAILED_TOTAL is not None:
        try:
            AUTHZ_READ_FAILED_TOTAL.labels(site=site, mode=mode).inc()
        except Exception:  # noqa: BLE001
            pass
    if mode == "enforce":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"authz_unavailable: the {site} check could not be completed, so nothing was done; retry shortly",
            headers={"Retry-After": "5"},
        )

# --- Password Hashing Context ---
class _SecretHashContext:
    """The `pwd_context.hash()` / `.verify()` that seeds, services and older operator recipes
    (`docker exec <registry> python -c "from agentvault_registry.security import pwd_context; ..."`) call.
    passlib's CryptContext stood here until §DEPS (2026-09-28); both methods are core/secret_hash.py now, whose
    hashes passlib verifies and which verifies every hash passlib made."""

    @staticmethod
    def hash(secret: str) -> str:
        return hash_secret(secret)

    @staticmethod
    def verify(secret: str, stored: str) -> bool:
        return verify_secret(secret, stored)


pwd_context = _SecretHashContext()

# --- JWT Configuration ---
SECRET_KEY = settings.API_KEY_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

# --- API Key Verification (for programmatic keys) ---
def verify_api_key(plain_api_key: str, hashed_api_key: str) -> bool:
    """Verifies a plain API key against its stored bcrypt hash (False on any refusal, never raises)."""
    return verify_secret(plain_api_key, hashed_api_key)

# --- API Key Hashing (for programmatic keys) ---
def hash_api_key(api_key: str) -> str:
    """Hashes an API key with bcrypt."""
    return hash_secret(api_key)

def api_key_lookup_hash(api_key: str) -> str:
    """Deterministic, indexable lookup hash for a programmatic API key.

    API keys are 256-bit random tokens (`secrets.token_urlsafe(32)`), so a fast
    SHA-256 is cryptographically sufficient to identify a key — unlike a password,
    a random token of this size cannot be brute-forced regardless of hash speed.
    Because it is deterministic (no per-row salt, unlike bcrypt) it can live in a
    UNIQUE index and be looked up in O(1), instead of scanning + bcrypt-verifying
    every active key. MUST be computed identically at create time and verify time.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

# --- Password Verification ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password (or agent client secret) against its stored bcrypt hash.

    False on any refusal and never raises: a mirrored developer's or a deleted account's marker is not a hash."""
    return verify_secret(plain_password, hashed_password)

# --- Password Hashing ---
def hash_password(password: str) -> str:
    """Hashes a password (or agent client secret) with bcrypt."""
    return hash_secret(password)

# --- Secure API Key Generation (for programmatic keys) ---
def generate_secure_api_key(length: int = 32) -> str:
    """Generates a cryptographically secure, URL-safe API key."""
    if length < 24:
        logger.warning(f"Requested API key length ({length}) is short; using minimum of 24 bytes.")
        length = 24
    random_part = secrets.token_urlsafe(length)
    api_key = f"avreg_{random_part}"
    logger.info(f"Generated new secure programmatic API key (prefix added).")
    return api_key

# --- Recovery Key Functions ---
def generate_recovery_keys(count: int = 3) -> List[str]:
    """Generates a list of secure, user-friendly recovery keys."""
    keys = []
    for _ in range(count):
        # Generate more entropy if needed
        key = f"avrec-{secrets.token_hex(4)}-{secrets.token_hex(4)}-{secrets.token_hex(4)}"
        keys.append(key)
    logger.info(f"Generated {count} recovery keys.")
    return keys

def hash_recovery_key(recovery_key: str) -> str:
    """Hashes a single recovery key with bcrypt."""
    if not isinstance(recovery_key, str):
         # Add explicit check here before encoding
         logger.error(f"hash_recovery_key received non-string input: type={type(recovery_key)}")
         raise TypeError("Recovery key must be a string")
    try:
        return hash_secret(recovery_key)
    except Exception as e:
        logger.exception(f"Error hashing recovery key with bcrypt: {e}")
        raise # Re-raise to indicate failure

# §FESUITE: registration hands a person three recovery keys, and only the first one's hash was ever stored ("one
# representative key"), so keys two and three could never recover the account and the first one, once used, left none.
# `developers.hashed_recovery_key` now holds one hash PER KEY, newline-separated (a hash never contains a newline; a
# legacy row with a single hash reads as one key). Each key works once: the one presented is burned when it verifies.
RECOVERY_HASH_SEP = "\n"


def hash_recovery_keys(recovery_keys: List[str]) -> str:
    """One stored value for all of a person's recovery keys: one hash per key."""
    return RECOVERY_HASH_SEP.join(hash_recovery_key(k) for k in recovery_keys)


def recovery_key_hashes(stored: Optional[str]) -> List[str]:
    """The individual hashes in a stored value (a legacy single hash is a list of one)."""
    return [h for h in (stored or "").split(RECOVERY_HASH_SEP) if h]


def match_recovery_key(plain_recovery_key: str, stored: Optional[str]) -> Optional[int]:
    """The index of the stored hash this key matches, or None."""
    if not isinstance(plain_recovery_key, str) or not plain_recovery_key:
        return None
    for i, h in enumerate(recovery_key_hashes(stored)):
        if verify_recovery_key(plain_recovery_key, h):
            return i
    return None


def burn_recovery_key(stored: Optional[str], index: int) -> Optional[str]:
    """The stored value without the key at `index` (None once no key is left)."""
    hashes = recovery_key_hashes(stored)
    if 0 <= index < len(hashes):
        del hashes[index]
    return RECOVERY_HASH_SEP.join(hashes) or None


def verify_recovery_key(plain_recovery_key: str, stored_hash: str) -> bool:
    """Verifies a plain recovery key against its stored bcrypt hash."""
    if not isinstance(plain_recovery_key, str) or not isinstance(stored_hash, str):
        logger.warning("Invalid types received for recovery key verification.")
        return False
    return verify_secret(plain_recovery_key, stored_hash)
# --- END MODIFIED ---

# --- ADDED: Function to generate verification token ---
def generate_verification_token(length: int = 32) -> str:
    """Generates a secure, URL-safe token for email verification."""
    return secrets.token_urlsafe(length)
# --- END ADDED ---

# --- JWT Creation ---
REFRESH_TOKEN_EXPIRE_DAYS = 7  # Refresh tokens last 7 days


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    token_version: Optional[int] = None,
) -> str:
    """Creates a JWT access token.

    AL-1 (2026-07-24): every token now carries a unique `jti` (harmless for all
    token types; a future per-token denylist keys off it). Developer access
    tokens additionally carry `tv` (the developer's current token_version) when
    the caller passes token_version=… — the developer verifier rejects a token
    whose `tv` is stale, giving us log-out-everywhere / password-change / admin
    force-logout revocation. Non-developer tokens (agent JWTs, registry↔registry
    JWTs) simply omit token_version and are unaffected.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "jti": str(uuid.uuid4())})
    if token_version is not None:
        to_encode["tv"] = int(token_version)
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(developer_id: int, token_version: Optional[int] = None) -> str:
    """Creates a long-lived JWT refresh token (7 days).

    AL-3 (2026-07-24): refresh tokens now also carry `tv` (token_version) + a
    `jti`. Without this a stolen 7-day refresh token SURVIVED a password change —
    the refresh endpoint checks `tv`, so password-change / logout / admin-suspend
    now kill refresh tokens too, not just access tokens.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": str(developer_id),
        "type": "refresh",
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    if token_version is not None:
        to_encode["tv"] = int(token_version)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def owner_session_token_minutes() -> int:
    """OWNER_SESSION_TOKEN_MINUTES (default 30, bounded 1..120): how long an owner session token lives. Read per mint, so
    a changed value needs no restart; an unreadable value falls back to 30."""
    try:
        return max(1, min(int(os.getenv("OWNER_SESSION_TOKEN_MINUTES", "30") or 30), 120))
    except ValueError:
        return 30


def create_owner_session_token(agent: Any, developer: Any) -> Tuple[str, int]:
    """§FEFRAME W3 (V0504): an agent token minted from the OWNER's signed-in session (no client secret). The claims
    /auth/agent/token issues (sub = the DID, type = agent, agent_id), so every agent-tier route admits it unchanged, plus
    `via: owner`, the owner's developer id and token_version, so `owner_token_refusal` ends it the moment that session's
    authority ends. Returns (token, lifetime in seconds)."""
    minutes = owner_session_token_minutes()
    token = create_access_token(
        data={"sub": agent.did, "type": "agent", "agent_id": str(agent.id), "via": "owner",
              "owner": str(developer.id), "owner_tv": int(getattr(developer, "token_version", 0) or 0)},
        expires_delta=timedelta(minutes=minutes),
    )
    return token, minutes * 60


async def owner_token_refusal(db: AsyncSession, claims: Any, agent: Any) -> Optional[str]:
    """§FEFRAME W3 (V0504): None when an agent token may act, else the reason an OWNER session token may not.

    An ordinary agent token (no `via`) passes untouched. An owner token lives only while the session that minted it
    could: the developer's token_version unchanged (a logout everywhere or a password change ends it), the account not
    suspended, deleted or anonymized, and the agent still that developer's (a transfer ends it). Every path that admits
    an agent JWT asks it through agent_token_refusal (D6-281): get_current_agent here and in routers/utils.py, the two
    read-actor resolvers and the MCP bridge. One indexed primary-key read, only for owner tokens."""
    if not isinstance(claims, dict) or claims.get("via") != "owner":
        return None
    try:
        owner_id = int(claims.get("owner"))
        owner_tv = int(claims.get("owner_tv"))
    except (TypeError, ValueError):
        return "the token's owner claims are malformed"
    if agent is None or getattr(agent, "creator_developer_id", None) != owner_id:
        return "the agent no longer belongs to the developer who minted this token"
    row = (await db.execute(
        select(models.Developer.token_version, models.Developer.is_suspended, models.Developer.deleted_at,
               models.Developer.deletion_status).where(models.Developer.id == owner_id)
    )).first()
    if row is None:
        return "the owner account no longer exists"
    tv, suspended, deleted_at, deletion_status = row
    if int(tv or 0) != owner_tv:
        return "the owner's session ended (a logout everywhere or a password change)"
    if suspended:
        return "the owner account is suspended"
    if deleted_at is not None or deletion_status == "anonymized":
        return "the owner account is deleted"
    return None


def owner_refusal_exception(reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Owner session token refused: {reason}",
        headers={"WWW-Authenticate": "Bearer"},
    )


def agent_credential_version(agent: Any) -> Optional[str]:
    """D6-281: a fingerprint of the agent's CURRENT credential, carried as `cv` in every token minted from it.

    Derived from the stored client-secret hash, which a credential reset (POST /onboard/agents/{did}/reset-credentials)
    and an admin rotation (POST /admin/agents/{did}/rotate-credentials) both replace: the developer token's `tv` pattern
    without a version column (no migration). Keyed with API_KEY_SECRET, so the claim tells a holder nothing about the
    stored hash. None for an agent with no stored secret."""
    stored = getattr(agent, "hashed_client_secret", None)
    if not stored:
        return None
    return hmac.new(SECRET_KEY.encode(), b"agent-credential\x00" + str(stored).encode(), hashlib.sha256).hexdigest()[:32]


def agent_token_claims(agent: Any, **extra: Any) -> dict:
    """The claims of an agent token minted from the agent's own credential (POST /auth/agent/token, and an act token
    minted for an authenticated agent): sub = the DID, type = agent, agent_id, and `cv` (agent_credential_version), which
    ends the token the moment the credential is reset or rotated (agent_token_refusal)."""
    claims = {"sub": agent.did, "type": "agent", "agent_id": str(agent.id)}
    cv = agent_credential_version(agent)
    if cv:
        claims["cv"] = cv
    claims.update(extra)
    return claims


async def agent_token_refusal(db: AsyncSession, claims: Any, agent: Any) -> Optional[str]:
    """None when an agent token may act, else why not. The ONE question every path that admits an agent JWT asks
    (get_current_agent here and in routers/utils.py, the two read-actor resolvers, the MCP bridge):

    - D6-281: a token minted from the agent's credential carries `cv`; once the credential is reset or rotated it no
      longer matches, and the token ends with the next request instead of living to its expiry. A token without `cv`
      is not asked: an owner session token (bound to its owner's session instead), a token the registry mints for its
      own internal call, and a token issued before this check existed (until it expires).
    - an owner session token whose session ended (owner_token_refusal)."""
    if isinstance(claims, dict) and claims.get("cv") is not None:
        current = agent_credential_version(agent) if agent is not None else None
        if current is None or not hmac.compare_digest(str(claims.get("cv")), current):
            return "the agent's credentials were reset after this token was issued; sign in with the new credentials"
    return await owner_token_refusal(db, claims, agent)


def agent_token_refusal_exception(claims: Any, reason: str) -> HTTPException:
    """The 401 for agent_token_refusal's answer, naming the kind of token it refused."""
    if isinstance(claims, dict) and claims.get("via") == "owner":
        return owner_refusal_exception(reason)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Agent token refused: {reason}",
        headers={"WWW-Authenticate": "Bearer"},
    )


def validate_refresh_token(token: str) -> Optional[int]:
    """Validate a refresh token and return the developer_id, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        sub = payload.get("sub")
        return int(sub) if sub else None
    except (JWTError, ValueError):
        return None


def access_token_subject(payload: Any) -> Optional[int]:
    """D6-731: the developer id a DEVELOPER ACCESS TOKEN names, or None when `payload` is not one.

    The one rule every developer-token verifier asks (verify_access_token_required, the optional verifier,
    get_current_developer_unified and the MCP auth bridge): an access token names an integer `sub` and carries neither a
    `type` (refresh tokens say "refresh", agent tokens "agent") nor a `purpose` (the password-set token, the 2FA login's
    partial token, the TEG exchange token). Every one of those is signed with the same key, so the signature alone does
    not say "access token": the 2FA login's partial token, handed out after the password and before the code, was read
    as a full session by every verifier that refused only purpose "password-set". Signature and expiry are the caller's
    decode; the token_version is `token_version_current`.
    """
    if not isinstance(payload, dict) or payload.get("type") is not None or payload.get("purpose") is not None:
        return None
    sub = payload.get("sub")
    if isinstance(sub, bool) or sub is None:
        return None
    try:
        return int(str(sub))
    except (TypeError, ValueError):
        return None


async def token_version_current(db: AsyncSession, developer_id: int, tv: Any) -> bool:
    """AL-1: a token carrying `tv` is valid only while it matches the developer's CURRENT token_version (logout, a
    password change or an admin force-logout bump it). A token without `tv` predates mig 0125 and is grandfathered until
    it expires. One indexed read, only when `tv` is present. A database error is raised (SQLAlchemyError): the caller
    answers 503, never "invalid token"."""
    if tv is None:
        return True
    try:
        want = int(tv)
    except (TypeError, ValueError):
        return False
    current = (await db.execute(
        select(models.Developer.token_version).where(models.Developer.id == developer_id)
    )).scalar_one_or_none()
    return current is not None and want == int(current)

# --- FastAPI Authentication Dependencies ---

# Define header scheme for programmatic API keys
api_key_header_scheme = APIKeyHeader(name="X-Api-Key", auto_error=False)

# Define OAuth2 scheme for JWT Bearer tokens (still needed for login endpoint response)
# Set auto_error=True for the required dependency
oauth2_scheme_required = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=True)
# Keep auto_error=False for potential use elsewhere if needed, but optional verify won't use it directly
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


# --- JWT Token Verification Dependencies ---
# ---------------------------------------------------------------------------
# API-KEY SCOPE (2026-08-27, §MCPSCOPE) — reported by an external researcher.
#
# THE PROBLEM, in the words of the comment that sat six lines below this one:
# the `avreg_` branch "returns the same int developer_id the JWT path produces,
# so downstream callers (get_current_developer, ADMIN FLAG CHECKS, etc.) are
# completely unaware which auth mode fired". So an API key was indistinguishable
# from a full password login across the whole surface — and the OAuth flow
# (mcp/oauth.py) hands one to any client that completes a consent, under a
# `scope` parameter that was echoed back and never enforced.
#
# `scopes` existed on the row since AL-4 but had exactly ONE live consumer
# (the key-minting gate in auth_secure.py) — a stored-but-ignored field
# everywhere else.
#
# THE FIX IS ONE PREDICATE ASKED AT ONE SEAM. We publish the scopes of the key
# that authenticated THIS request in a ContextVar (the pattern §EXTMTLS already
# uses for the MCP peer IP), and `require_admin_flag` — 367 call sites, 66 files,
# the whole admin surface — asks it.
#
# FAIL DIRECTION IS DELIBERATE AND IS THE RISKY HALF: unset means "not an API
# key" (a JWT, or an auth path that does not resolve keys), and that must stay
# UNRESTRICTED or every human admin login breaks. So a bug that fails to SET the
# var silently disables this control rather than locking anyone out. That is the
# right trade for availability, and it is why the battery asserts the var is
# actually set on a real request instead of only asserting the deny.
_PRESENTED_KEY_SCOPES: "contextvars.ContextVar[Optional[List[str]]]" = contextvars.ContextVar(
    "presented_api_key_scopes", default=None
)
# §POCKETPAIR (2026-10-15): the id of that key, beside its scopes. A phone paired by POCKET FRAME registers its push
# device with the key it was paired with; the device route records this id so that removing the phone revokes the key
# (and revoking the key disables the phone's push rows). None for a JWT, like the scopes.
_PRESENTED_KEY_ID: "contextvars.ContextVar[Optional[int]]" = contextvars.ContextVar(
    "presented_api_key_id", default=None
)


def _stash_rate_principal(request: "Request", principal: str) -> None:
    """§RATEFIX — publish the VERIFIED principal for the rate limiter's key
    function (``middleware/rate_limiter.principal_rate_key``).

    Set only after a signature has actually been checked, which is the whole
    point: the old limiter keyed on ``request.client.host``, a value the caller
    writes via ``X-Forwarded-For``, and the module's own role helper decodes the
    JWT with ``verify_signature: False``. Neither can carry a limit. Failing to
    stash is never fatal — the key function falls back to the forge-proof
    address, which is a correct if coarser bucket.
    """
    try:
        if request is not None:
            request.state.rl_principal = principal
    except Exception:  # noqa: BLE001 - never fail an authenticated request on bookkeeping
        pass


def presented_api_key_scopes() -> Optional[List[str]]:
    """Scopes of the API key that authenticated this request, or None for a JWT."""
    return _PRESENTED_KEY_SCOPES.get()


def presented_api_key_id() -> Optional[int]:
    """§POCKETPAIR: the id of the API key that authenticated this request, or None (a JWT, or an unresolved row)."""
    return _PRESENTED_KEY_ID.get()


async def presented_key_scopes(db: AsyncSession, plain_key: str) -> Tuple[List[str], Optional[int]]:
    """D6-715: the scopes and the id of the API key `plain_key`, failing CLOSED.

    The one lookup every scope gate reads (the published scopes below, the key-mint gate of /auth/api-keys, the MCP
    bridge's admin flag). A row with no scopes is a key minted before AL-4: full authority by design (['*']). A row that
    cannot be read (an unexpected error, or the key gone since it authenticated) carries NO scope ([]): neither admin nor
    mint. It used to read as ['*'], so a narrow key (a paired phone's, an MCP OAuth client's) whose lookup failed held
    full authority, admin included, for that request. A database error is raised (SQLAlchemyError) for the caller to
    answer 503: the scope could not be checked.
    """
    try:
        row = await developer_crud.get_api_key_row_by_plain_key(db=db, plain_key=plain_key)
    except SQLAlchemyError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[MCPSCOPE] scope lookup failed ({type(e).__name__}); the key carries no scope on this request")
        return [], None
    if row is None:
        logger.warning("[MCPSCOPE] the key's row could not be read; it carries no scope on this request")
        return [], None
    kid = getattr(row, "id", None)
    scopes = effective_key_scopes(list(getattr(row, "scopes", None) or ["*"]), getattr(row, "description", None))
    return scopes, (int(kid) if kid is not None else None)


async def _publish_presented_key(db: AsyncSession, plain_key: str, request: Optional[Request] = None) -> None:
    """§MCPSCOPE + §POCKETPAIR: publish the scopes and the id of the key that authenticated this request.

    One helper for every dependency that resolves an avreg_ key (verify_access_token_required and
    get_current_developer_unified), so no auth path leaves the scope unset (an unset scope reads as a JWT, which
    disables the admin and mint gates for that request). D6-715: fails CLOSED (presented_key_scopes): a row that cannot
    be read publishes no scope, and a database that cannot answer is 503. D6-514: and refuses (403) a key scoped to MCP
    on a route it may not reach directly (mcp_key_route_refusal; without the request, every route).
    """
    try:
        scopes, kid = await presented_key_scopes(db, plain_key)
    except SQLAlchemyError as e:
        raise _credential_store_unavailable(e) from e
    _PRESENTED_KEY_SCOPES.set(scopes)
    _PRESENTED_KEY_ID.set(kid)
    why = mcp_key_route_refusal(
        scopes, plain_key,
        getattr(request, "method", None),
        getattr(getattr(request, "url", None), "path", None),
        request.headers.get(MCP_RELAY_HEADER) if request is not None else None,
    )
    if why:
        logger.info(f"[MCPSCOPE] key {kid} refused on {getattr(request, 'method', '?')} "
                    f"{getattr(getattr(request, 'url', None), 'path', '?')}: scopes={scopes}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=why)


# D6-514: a key scoped to MCP (it holds 'mcp:tools' or 'mcp:admin', and not '*': an MCP OAuth client's, a paired
# phone's) is an MCP credential, not a general one. The MCP tools reach the REST API for it over loopback, presenting
# the key, and every such call carries this registry's relay proof for that key (mcp/auth_bridge.mcp_http_client), which
# only a holder of API_KEY_SECRET can make. It carried the account's whole developer authority on every non-admin route
# before; a key with no narrow scope keeps the reach it had.
#
# SEC-10 (2026-10-17): a paired phone's key holds a scope of its own. POCKET FRAME's "Pair this phone" mints
# ['mcp:tools', 'pocket:device']: 'pocket:device' names what the phone does with the REST API itself (it registers its
# push device), 'mcp:tools' the MCP tools its assistant drives. The direct allowance used to belong to 'mcp:tools', so
# any MCP credential (an MCP OAuth connector's key) could register a push device on the account directly and receive the
# account's notifications; 'mcp:tools' now reaches nothing directly, and 'pocket:device' alone is not an MCP credential
# (key_reaches_mcp). Presented to a REST route directly, a narrow key reaches only the routes its scopes name for direct
# use (KEY_DIRECT_ROUTES).
MCP_KEY_SCOPES = frozenset({"mcp:tools", "mcp:admin"})
PHONE_KEY_SCOPE = "pocket:device"
NARROW_KEY_SCOPES = MCP_KEY_SCOPES | {PHONE_KEY_SCOPE}
MCP_RELAY_HEADER = "X-MCP-Relay"
KEY_DIRECT_ROUTES = {PHONE_KEY_SCOPE: frozenset({("POST", "/api/v1/devices/register")})}
# A phone paired before SEC-10 holds ['mcp:tools'] alone, under the name the console gives every phone key; it keeps what
# it had (its push registration) until it is paired again or the key expires (a phone key lives 90 days). A key's name
# is fixed when it is minted, and an MCP credential cannot mint one, so no connector can take this name.
PAIRED_PHONE_KEY_NAME_PREFIX = "POCKET FRAME: "


def effective_key_scopes(scopes: List[str], name: Optional[str]) -> List[str]:
    """SEC-10: the scopes a key carries on a request: its own, and for a phone paired before SEC-10 (scopes exactly
    ['mcp:tools'], named by the console's pairing) also 'pocket:device', which it held as part of 'mcp:tools'."""
    if list(scopes) == ["mcp:tools"] and str(name or "").startswith(PAIRED_PHONE_KEY_NAME_PREFIX):
        return ["mcp:tools", PHONE_KEY_SCOPE]
    return list(scopes)


def key_reaches_mcp(scopes: List[str]) -> bool:
    """SEC-10: may a key with these scopes be used on the MCP endpoints? A key with '*', or with no narrow scope, as
    before; a narrow key only when it holds an MCP scope (a paired phone's 'pocket:device' alone is not an MCP
    credential). A key whose scopes could not be read ([]) is left to the gates that read them again, as before (no
    admin over MCP, and the REST API refuses it)."""
    if not scopes or "*" in scopes:
        return True
    held = NARROW_KEY_SCOPES.intersection(scopes)
    return not held or bool(held & MCP_KEY_SCOPES)


def mcp_relay_proof(token: str) -> str:
    """D6-514: this registry's proof that its own MCP server sent a request made with the API key `token`."""
    return hmac.new(SECRET_KEY.encode(), b"mcp-relay\x00" + str(token).encode(), hashlib.sha256).hexdigest()


def mcp_key_route_refusal(scopes: Optional[List[str]], token: str, method: Optional[str], path: Optional[str],
                          relay_proof: Optional[str]) -> Optional[str]:
    """D6-514 + SEC-10: why the presented API key may not reach this route, or None when it may.

    None for a JWT (no scopes) and for a key with '*'. A key whose scopes could not be read ([], D6-715) reaches nothing.
    A key holding a narrow scope (NARROW_KEY_SCOPES) reaches a route through MCP's relay (a valid relay proof) when it
    holds an MCP scope, or when one of its scopes names the route for direct use (KEY_DIRECT_ROUTES: 'pocket:device', a
    phone's push registration); a key with no narrow scope keeps its reach."""
    if scopes is None or "*" in scopes:
        return None
    if not scopes:
        return "This API key's scopes could not be read, so it cannot be used on this request; try again."
    held = NARROW_KEY_SCOPES.intersection(scopes)
    if not held:
        return None
    mcp = held & MCP_KEY_SCOPES
    if mcp and relay_proof and hmac.compare_digest(str(relay_proof), mcp_relay_proof(token)):
        return None
    route = ((method or "").upper(), (path or "").rstrip("/"))
    if any(route in KEY_DIRECT_ROUTES.get(s, ()) for s in held):
        return None
    phone = " and a paired phone's push registration" if PHONE_KEY_SCOPE in held else ""
    if mcp:
        return (f"This API key is scoped to MCP ({', '.join(sorted(held))}): it reaches this registry's REST API through "
                f"the MCP tools{phone} only. Call the MCP endpoint, or use a key with full authority ('*').")
    return (f"This API key is a paired phone's ({PHONE_KEY_SCOPE}): it reaches this registry's REST API only to register "
            "the phone's push device (POST /api/v1/devices/register). Use a key with full authority ('*') for anything "
            "else.")


def scopes_grant_admin(scopes: List[str]) -> bool:
    """A key's scopes reach an admin gate only with '*' (full authority, every key minted before AL-4) or 'mcp:admin'."""
    return "*" in scopes or "mcp:admin" in scopes


def key_may_mint(requested_scopes: Optional[List[str]] = None) -> bool:
    """§POCKETPAIR: may the credential on THIS request mint an API key with these scopes?

    A JWT (no presented key) may. A key with '*' may. Any other key may mint only when it holds 'keys:manage' AND the
    new key's scopes stay inside its own: no key, scoped or not, mints a key broader than itself. `requested_scopes`
    None or empty means '*' (what the mint rails store for an empty list).
    """
    sc = _PRESENTED_KEY_SCOPES.get()
    if sc is None or "*" in sc:
        return True
    if "keys:manage" not in sc:
        return False
    want = list(requested_scopes or ["*"])
    return all(s in sc for s in want)


def _admin_on_this_credential(developer: Any, held: bool) -> bool:
    """The half every inline admin check shares with require_admin_flag: authority the account `held`, carried by THIS
    request's credential (api_key_grants_admin), under REQUIRE_ADMIN_2FA (admin_second_factor_ok), and never while a
    password change is forced (the operator bootstrap gate, D6-821)."""
    return (held and not bool(getattr(developer, "must_change_password", False)) and api_key_grants_admin()
            and admin_second_factor_ok(developer))


def admin_credential(developer: Any) -> bool:
    """§POCKETPAIR: is this developer an admin ON THIS REQUEST'S CREDENTIAL?

    `developer.is_admin` alone answers for the account; a request made with a scoped API key (a paired phone's key, an
    MCP OAuth key) is an admin request only when that key also reaches admin (api_key_grants_admin). Every inline
    `is_admin` check that gates admin power asks this instead, the way require_admin_flag already does. D6-621: and only
    while the account meets REQUIRE_ADMIN_2FA (admin_second_factor_ok). D6-821: and not while the account must change
    its password, which require_admin_flag and get_current_admin_developer refused and this inline twin let through.
    """
    return _admin_on_this_credential(developer, bool(getattr(developer, "is_admin", False)))


ADMIN_FLAGS = ("admin_treasury", "admin_support", "admin_enforcement", "admin_federation", "admin_platform")


def admin_flag_credential(developer: Any, flag_name: Optional[str] = None) -> bool:
    """D6-821: the inline twin of require_admin_flag, for a check that cannot be a dependency (a read it widens, a
    socket's audience): legacy is_admin, or the admin flag `flag_name` on the account (any admin flag when None), on
    THIS request's credential, under the same three conditions as admin_credential. Several inline checks read the
    account's flags alone, so an admin's scoped key, an account without the second factor REQUIRE_ADMIN_2FA demands, or
    one that must change its password still widened what it read."""
    if flag_name is not None and flag_name not in ADMIN_FLAGS:
        raise ValueError(f"Unknown admin flag: {flag_name}. Valid: {sorted(ADMIN_FLAGS)}")
    flags = ADMIN_FLAGS if flag_name is None else (flag_name,)
    held = bool(getattr(developer, "is_admin", False)) or any(bool(getattr(developer, f, False)) for f in flags)
    return _admin_on_this_credential(developer, held)


ADMIN_2FA_REQUIRED = ("Admin authority requires two-factor authentication on this account. Set up 2FA in Settings, "
                      "Security, then retry.")


def admin_second_factor_ok(developer: Any) -> bool:
    """D6-621: may this developer exercise ADMIN authority under REQUIRE_ADMIN_2FA?

    With REQUIRE_ADMIN_2FA on, an account holding admin authority (is_admin or any admin_* flag) must have 2FA enabled.
    The password login enforced that, and nothing else did: an API key (an MCP OAuth key, a CLI or bridge key), a session
    that outlived a 2FA disable, or any other credential carried the account's admin authority without it. So the rule
    is asked where admin authority is used (require_admin_flag, get_current_admin_developer, admin_credential and the
    sites built on api_key_grants_admin, the MCP bridge's admin flag, the websocket's admin role), for every credential:
    a credential conveys admin authority only while its developer has 2FA enabled. Non-admin use is never affected.
    With the flag off (the default) this is always True.
    """
    if not getattr(settings, "REQUIRE_ADMIN_2FA", False):
        return True
    return bool(getattr(developer, "two_fa_enabled", False))


def api_key_grants_admin() -> bool:
    """May the credential on THIS request reach an admin gate?

    None  -> not an API key (JWT / unresolved path): unchanged, unrestricted.
    '*'   -> full developer authority: every key minted before this change, so
             this is byte-inert for the existing fleet.
    else  -> only an explicit mcp:admin scope opens admin ([] = scopes that could not be read: never).
    """
    sc = _PRESENTED_KEY_SCOPES.get()
    if sc is None:
        return True
    return scopes_grant_admin(sc)


def _credential_store_unavailable(e: Exception) -> HTTPException:
    """§FESUITE: the credential check could not reach the database. That is the registry's trouble, not the caller's
    credential: the 401 it used to be told the console the session was dead (and the console signs out on a 401, which
    revokes the account's tokens everywhere), so a busy database ("too many clients already", measured on sbx-alpha)
    signed people out. 503 with Retry-After says "try again"."""
    logger.error(f"Credential check could not reach the database: {e}")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="The registry cannot check credentials right now; try again shortly.",
        headers={"Retry-After": "5"},
    )


async def _developer_for_api_key(db: AsyncSession, plain_key: str):
    """developer_crud.get_developer_by_plain_api_key, with a database failure answered 503 instead of "no such key"."""
    try:
        return await developer_crud.get_developer_by_plain_api_key(db=db, plain_key=plain_key)
    except SQLAlchemyError as e:
        raise _credential_store_unavailable(e) from e


async def verify_access_token_required(
    request: Request,
    token: str = Depends(oauth2_scheme_required),
    db: AsyncSession = Depends(get_db),
) -> int:
    """
    FastAPI dependency to verify JWT token (required).
    Raises HTTPException on failure. Returns developer ID (int).
    Uses OAuth2PasswordBearer with auto_error=True.

    §pass66.7 (2026-05-23) — API-key-as-Bearer fallback. The MCP stdio bridge
    + tp-operator CLI + any programmatic developer client sends the developer
    API key (`avreg_...`) in the Authorization Bearer header. Prior to this
    fix only JWT decoding was attempted; API keys hit JWTError and 401'd. The
    `get_current_developer_unified` dependency was supposed to handle this
    but `/developers/me` (+ 43 other endpoints in routers/developers.py) use
    the plain `get_current_developer` → `verify_access_token_required` chain.
    Patching the bottleneck here unblocks every endpoint at once without
    touching the 44 caller sites.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # auto_error=True in oauth2_scheme_required handles the case where token is None

    # §pass66.7 — API key Bearer short-circuit. If the token starts with the
    # `avreg_` prefix, it's a programmatic developer key, not a JWT. Skip the
    # JWT decode attempt (would fail with "Not enough segments") and resolve
    # directly via the API-keys table. Returns the same `int` developer_id
    # the JWT path produces, so downstream callers (get_current_developer,
    # admin flag checks, etc.) are completely unaware which auth mode fired.
    if token.startswith("avreg_"):
        api_key_developer = await _developer_for_api_key(db, token)
        if api_key_developer is None:
            logger.warning("API key Bearer auth failed: no active key matches the provided hash")
            raise credentials_exception
        # §MCPSCOPE — publish THIS key's scopes for the admin gate (and, §POCKETPAIR, its id). Separate
        # O(1) indexed lookup (AL-4 added it for exactly this kind of
        # inspection) rather than widening get_developer_by_plain_api_key,
        # which also touches last_used_at and is called from four other sites.
        # D6-514: with the request, so a key scoped to MCP is held to the routes it may reach.
        await _publish_presented_key(db, token, request)
        logger.debug(
            f"API key Bearer auth succeeded for developer ID: {api_key_developer.id}"
        )
        _stash_rate_principal(request, f"d:{api_key_developer.id}")
        return api_key_developer.id

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # RA4 + D6-731: only a developer ACCESS token passes (an integer sub, no `type`, no `purpose`): never a refresh
        # token, a password-set token or the 2FA login's partial token (access_token_subject says why).
        developer_id = access_token_subject(payload)
        if developer_id is None:
            logger.warning(
                f"JWT verification failed: not a developer access token "
                f"(type={payload.get('type')!r}, purpose={payload.get('purpose')!r})."
            )
            raise credentials_exception

        # AL-1 (2026-07-24): token_version revocation; tokens minted before mig 0125 carry no `tv` and are grandfathered.
        if not await token_version_current(db, developer_id, payload.get("tv")):
            logger.info(
                f"JWT rejected: token_version mismatch for developer {developer_id} "
                f"(token tv={payload.get('tv')}) — token revoked."
            )
            raise credentials_exception

    except JWTError as e:
        # 2026-05-04 (B5): demote known structural-rejection patterns to DEBUG.
        # Bot probes hitting authenticated endpoints with garbage Authorization
        # headers fail at the JWT structure-parse stage (no segments, bad
        # padding, etc.) — these are internet noise, not security signals.
        # Real auth failures (expired tokens, wrong claims, signature mismatch)
        # surface with different error strings and stay at WARNING. This
        # eliminated ~17,000 log lines/h on registry-a (1,400 probes/h ×
        # ~12 lines per traceback + DB-rollback ERROR pair).
        err_msg = str(e)
        BOT_PROBE_PATTERNS = (
            "Not enough segments",       # garbage in Authorization header
            "Invalid header string",     # malformed JWT structure
            "Invalid crypto padding",    # truncated tokens
            "Error decoding signature",  # garbled tokens
        )
        if any(p in err_msg for p in BOT_PROBE_PATTERNS):
            logger.debug(f"JWT structural rejection (likely bot probe): {err_msg}")
        else:
            logger.warning(f"JWT verification failed: {err_msg}")
        raise credentials_exception from e
    except HTTPException:
        # §FESUITE: this block's own refusals (a revoked token_version, a refresh token, a bad `sub`) are not
        # "unexpected": the catch-all below logged each one as an ERROR with a traceback before re-raising it.
        raise
    except SQLAlchemyError as e:
        # the token_version read could not reach the database: 503, never 401 (see _credential_store_unavailable)
        raise _credential_store_unavailable(e) from e
    except Exception as e:
         logger.error(f"Unexpected error during JWT decode/validation: {e}", exc_info=True)
         raise credentials_exception from e

    logger.debug(f"Required JWT verified successfully for developer ID: {developer_id}")
    _stash_rate_principal(request, f"d:{developer_id}")
    return developer_id

# --- CORRECTED verify_access_token_optional ---
async def verify_access_token_optional(authorization: Optional[str] = Header(None)) -> Optional[int]:
    """
    FastAPI dependency to optionally verify JWT token from Authorization header.
    Returns developer ID (int) if valid, None otherwise (does not raise HTTPException).
    """
    claims = await verify_access_token_optional_claims(authorization)
    return claims[0] if claims else None


async def verify_access_token_optional_claims(
    authorization: Optional[str] = Header(None),
) -> Optional[Tuple[int, Optional[int]]]:
    """The optional verifier's decode, returning `(developer_id, tv)` or None. Never raises.

    §PROXYKEY 2026-09-11 — the optional path used to keep only the id and drop the `tv`
    (token_version) claim, so `get_current_developer_optional` could not tell a revoked token
    from a live one. It also accepted a REFRESH token, which the required path refuses (RA4):
    a 7-day refresh token was a 7-day identity on every optional route, and one of those routes
    is the admin gate of the api-tester router. Both now match the required verifier.
    """
    if authorization is None:
        logger.debug("Optional JWT verification: No Authorization header provided.")
        return None # No header, no user

    parts = authorization.split()
    # Check format: exactly two parts, first part is "Bearer" (case-insensitive)
    if len(parts) != 2 or parts[0].lower() != "bearer": # Check the FIRST part
        logger.debug(f"Optional JWT verification failed: Invalid Authorization header format. Header: {authorization[:20]}...")
        return None # Invalid scheme or format

    # --- FIX: Extract the token string (second part) ---
    token = parts[1]
    # --- END FIX ---
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # D6-731: the same claims rule as the required verifier (access_token_subject)
        developer_id = access_token_subject(payload)
        if developer_id is None:
            logger.debug("Optional JWT verification failed: not a developer access token.")
            return None
        try:
            _tv = payload.get("tv")
            logger.debug(f"Optional JWT verification succeeded for developer ID: {developer_id}")
            return developer_id, (int(_tv) if _tv is not None else None)
        except (TypeError, ValueError):
            logger.debug("Optional JWT verification failed: 'tv' claim is not an integer.")
            return None

    except JWTError as e: # Catches ExpiredSignatureError, InvalidTokenError etc.
        logger.debug(f"Optional JWT verification failed: {e}")
        return None # Invalid token
    except Exception as e:
         logger.error(f"Unexpected error during optional JWT decode/validation: {e}", exc_info=True)
         return None # Treat unexpected errors as invalid token
# --- END CORRECTED verify_access_token_optional ---

async def verify_temp_password_token(token: str = Depends(oauth2_scheme_required)) -> int: # Use required scheme here
    """
    FastAPI dependency specifically for verifying the temporary password set token.
    Checks for the 'password-set' purpose. Raises HTTPException on failure.
    """
    return (await verify_temp_password_claims(token))[0]


async def verify_temp_password_claims(token: str = Depends(oauth2_scheme_required)) -> Tuple[int, Optional[int]]:
    """(developer id, the token_version the token was issued at) of a password-set token: the purpose and the expiry are
    checked here, the version by the route that holds the developer row (a token whose version has moved since it was
    issued is spent: setting the password moves it, so the token sets a password once)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired password recovery token",
        headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
    )
    # auto_error=True handles missing token

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": True}) # Ensure expiry is checked
        developer_id_str: Optional[str] = payload.get("sub")
        purpose: Optional[str] = payload.get("purpose")

        if developer_id_str is None or purpose != "password-set":
            logger.warning(f"Temporary token verification failed: 'sub' missing or purpose is not 'password-set'. Purpose: {purpose}")
            raise credentials_exception
        try:
            developer_id = int(developer_id_str)
        except ValueError:
            logger.warning(f"Temporary token verification failed: 'sub' claim '{developer_id_str}' is not an integer.")
            raise credentials_exception

    except JWTError as e:
        logger.warning(f"Temporary token JWT verification failed: {e}")
        raise credentials_exception from e
    except HTTPException:
        # §MCPTEST30 (V0545): its own refusals (a token of another purpose) are logged above at WARNING; the
        # catch-all below logged each again as "Unexpected error" with a traceback
        raise
    except Exception as e:
         logger.error(f"Unexpected error during temporary token decode/validation: {e}", exc_info=True)
         raise credentials_exception from e

    logger.debug(f"Temporary password set token verified successfully for developer ID: {developer_id}")
    tv = payload.get("tv")
    try:
        return developer_id, (int(tv) if tv is not None else None)
    except (TypeError, ValueError):
        return developer_id, None


# --- Developer Fetching Dependencies ---
async def get_current_developer(
    db: AsyncSession = Depends(get_db),
    developer_id: int = Depends(verify_access_token_required) # Use REQUIRED verifier
) -> models.Developer:
    """
    FastAPI dependency to get the current developer based on a verified JWT token.
    Raises HTTPException(401) if the developer ID from the token doesn't exist in DB.
    """
    from agentvault_registry.opa_shadow import shadow_check

    # Use the STRICT lookup so a transient DB/session fault (pool exhaustion under
    # burst dashboard polling, poisoned session, idle-txn reap) does NOT get
    # swallowed to None and misreported as "developer not found" → spurious 401 →
    # forced FE logout (root cause of the frame-c 3-5min auto-logout, 2026-07-05).
    # A real infra fault → 503 (retryable; FE does not log out on 5xx).
    try:
        developer = await developer_crud.get_developer_by_id_strict(db=db, developer_id=developer_id)
    except Exception as e:
        logger.warning(f"[auth] transient DB error loading developer {developer_id}: {e}")
        try:
            await db.rollback()  # clear any poisoned session state for the next request
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication temporarily unavailable; please retry.",
            headers={"Retry-After": "1"},
        )

    is_deleted = developer is not None and getattr(developer, "deleted_at", None) is not None
    is_suspended = developer is not None and bool(getattr(developer, "is_suspended", False))
    # W2 (2026-05-09) — anonymized accounts must NOT be reachable via stale
    # JWTs that were issued before anonymization. The DB row stays for FK
    # integrity, but the user's ability to authenticate ends at anonymize-time.
    is_anonymized = (
        developer is not None
        and getattr(developer, "deletion_status", None) == "anonymized"
    )
    python_allow = (
        developer is not None
        and not is_deleted
        and not is_suspended
        and not is_anonymized
    )

    opa_input = {
        "developer_id": developer_id,
        "developer_exists": developer is not None,
        "is_deleted": is_deleted,
        "is_suspended": is_suspended,
    }
    effective_allow = await shadow_check(
        "agentvault/developer/allow", opa_input, python_allow, label="developer_jwt"
    )

    if developer is None:
        logger.warning(f"Authenticated developer ID {developer_id} not found in database.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with token not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # M1 2026-04-20: admin-suspend / admin-delete gate
    if is_deleted:
        logger.warning(f"Authenticated developer ID {developer_id} is deleted ({developer.deleted_at}).")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account deleted",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if is_suspended:
        logger.warning(f"Authenticated developer ID {developer_id} is suspended.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account suspended",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # W2 (2026-05-09) — block stale JWTs against anonymized accounts.
    if is_anonymized:
        logger.warning(
            f"Authenticated developer ID {developer_id} is anonymized "
            f"(anonymized_at={getattr(developer, 'anonymized_at', None)})."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account anonymized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not effective_allow:
        # Reached only when OPA enforce-mode denies a request Python would allow.
        logger.warning(
            f"Developer JWT denied by OPA enforce for developer ID {developer_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization denied by policy",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"Successfully identified current developer: ID={developer.id}, Name={developer.name}")
    return developer

# --- MODIFIED: get_current_developer_optional uses OPTIONAL JWT verification ---
async def get_current_developer_optional(
    db: AsyncSession = Depends(get_db),
    claims: Optional[Tuple[int, Optional[int]]] = Depends(verify_access_token_optional_claims),
) -> Optional[models.Developer]:
    """
    FastAPI dependency that attempts to get the current developer based on the
    Authorization: Bearer header, returning None if token missing/invalid or dev not found.

    §PROXYKEY 2026-09-11 — "optional" means a missing identity is allowed, never that a
    REVOKED one is. This returned the developer for a logged-out token (token_version
    moved on), a suspended account and a deleted one, all of which `get_current_developer`
    refuses; and the api-tester router hands this function's answer straight to its admin
    check. Each of those now reads as anonymous, exactly as the required path would refuse it.
    """
    if claims is None:
        logger.debug("Optional authentication: No valid developer ID from token.")
        return None
    developer_id, token_tv = claims

    try:
        # §MCPTEST30 (V0553): the developer's own row, never every card and key it owns (crud get_developer_by_id_strict)
        developer = await developer_crud.get_developer_by_id_lean(db=db, developer_id=developer_id)
        if developer is None:
            logger.debug(f"Optional authentication: Developer ID {developer_id} from token not found.")
            return None
        # The required path's three refusals, in the same terms (AL-1, M1, W2).
        if token_tv is not None and int(token_tv) != int(getattr(developer, "token_version", 0) or 0):
            logger.info(f"Optional authentication: revoked token for developer {developer_id} "
                        f"(token tv={token_tv}) read as anonymous.")
            return None
        if (getattr(developer, "deleted_at", None) is not None
                or bool(getattr(developer, "is_suspended", False))
                or getattr(developer, "deletion_status", None) == "anonymized"):
            logger.info(f"Optional authentication: developer {developer_id} is deleted/suspended; "
                        f"read as anonymous.")
            return None
        logger.debug(f"Optional authentication successful for developer ID: {developer.id}")
        return developer
    except Exception as e:
        logger.error(f"Unexpected error during optional developer lookup by ID {developer_id}: {e}", exc_info=True)
        return None
# --- END MODIFIED ---

# --- Dependency for programmatic API Key Auth ---
async def verify_programmatic_api_key(
    api_key: Optional[str] = Depends(api_key_header_scheme), # Use X-Api-Key header
    db: AsyncSession = Depends(get_db)
) -> models.Developer:
    """
    FastAPI dependency to get the current developer based on the X-Api-Key header,
    checking against the new DeveloperApiKey table. Raises HTTPException on failure.
    """
    if not api_key:
        logger.warning("Programmatic API Key auth failed: X-Api-Key header missing.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authenticated: X-Api-Key header missing or empty"
        )

    developer = await _developer_for_api_key(db, api_key)

    if developer is None:
        logger.warning(f"Programmatic API Key auth failed: Invalid or inactive API Key provided (Key starts with: {api_key[:10]}...).")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API Key"
        )

    logger.debug(f"Successfully authenticated developer ID via programmatic API key: {developer.id}")
    return developer

# --- Admin Developer Dependencies ---
async def get_current_admin_developer(
    current_developer: models.Developer = Depends(get_current_developer)
) -> models.Developer:
    """
    FastAPI dependency to verify that the current developer has admin privileges.

    This checks the is_admin field on the Developer model to determine admin status.
    Also blocks admin operations if must_change_password is set (operator bootstrap).

    Raises HTTPException(403) if the developer is not an admin or must change password.
    """
    # Check if current developer has admin privileges via is_admin field
    if not current_developer.is_admin:
        logger.warning(f"Admin access denied for developer: {current_developer.email} (ID: {current_developer.id})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    # Block admin operations until password is changed (operator bootstrap gate)
    if getattr(current_developer, 'must_change_password', False):
        logger.warning(f"Admin access blocked: developer {current_developer.id} must change password first")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required before admin operations. POST /api/v1/auth/change-password"
        )

    # D6-621: the scope of the presented key (as require_admin_flag) and REQUIRE_ADMIN_2FA, for every credential
    if not api_key_grants_admin():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This credential's scopes do not reach admin operations.")
    if not admin_second_factor_ok(current_developer):
        logger.warning(f"Admin access denied: developer {current_developer.id} has no 2FA (REQUIRE_ADMIN_2FA)")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_2FA_REQUIRED)

    logger.debug(f"Admin access granted to developer: {current_developer.email} (ID: {current_developer.id})")
    return current_developer


# --- Fix 1 (2026-04-20): granular admin flag dependency factory ---
#
# Five operational admin sub-roles live as boolean columns on `developers`:
#   admin_treasury / admin_support / admin_enforcement / admin_federation / admin_platform
#
# Routes that previously used Depends(get_current_admin_developer) can migrate
# to Depends(require_admin_flag("admin_support")) to narrow authority. Legacy
# is_admin continues to act as a super-flag: during migration, any developer
# with is_admin=True still passes every require_admin_flag check — this
# preserves backward compatibility while enabling sub-admin creation.
#
# The must_change_password operator-bootstrap gate is inherited automatically.
# REQUIRE_ADMIN_2FA applies uniformly once flipped: at the login AND here, for every credential (D6-621).
def require_admin_flag(flag_name: str):
    """
    FastAPI dependency factory that requires a specific granular admin flag.

    Usage in a router:
        @router.get("/admin/support/tickets")
        async def list_tickets(
            admin: models.Developer = Depends(security.require_admin_flag("admin_support"))
        ):
            ...

    Legacy is_admin=True passes every flag check (superadmin). During the
    incremental migration of admin routers, this ensures existing admins keep
    full access while new sub-admins get only the flags explicitly set.
    """
    valid_flags = {
        "admin_treasury",
        "admin_support",
        "admin_enforcement",
        "admin_federation",
        "admin_platform",
    }
    if flag_name not in valid_flags:
        raise ValueError(f"Unknown admin flag: {flag_name}. Valid: {sorted(valid_flags)}")

    async def _check(
        current_developer: models.Developer = Depends(get_current_developer)
    ) -> models.Developer:
        from agentvault_registry.opa_shadow import shadow_check

        must_change = bool(getattr(current_developer, "must_change_password", False))
        is_admin = bool(current_developer.is_admin)
        flag_held = bool(getattr(current_developer, flag_name, False))
        # §MCPSCOPE — an API key minted for MCP tool use is NOT a password login.
        # Checked BEFORE is_admin so that being an admin does not rescue a
        # narrow-scoped credential: the question is what the CREDENTIAL may do,
        # not who the human is.
        scope_ok = api_key_grants_admin()

        if not scope_ok:
            _sc = presented_api_key_scopes()
            logger.warning(
                f"[MCPSCOPE] admin flag '{flag_name}' DENIED for developer "
                f"{current_developer.id}: credential scopes={_sc} lack '*'/'mcp:admin'"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This credential is scoped for MCP tool use and cannot perform "
                    "admin operations. Scopes: " + ", ".join(_sc or []) + "."
                ) if _sc else (
                    # D6-715: the key's scopes could not be read on this request (presented_key_scopes fails closed)
                    "This API key's scopes could not be read, so it cannot perform admin operations; try again."
                ),
            )

        # D6-621: REQUIRE_ADMIN_2FA for every credential, not only the password login (an API key, an MCP OAuth key, a
        # session that outlived a 2FA disable all carried the account's admin authority without it). Asked only of a
        # developer who would otherwise hold the authority, before the OPA shadow (which mirrors the flag checks).
        if (is_admin or flag_held) and not must_change and not admin_second_factor_ok(current_developer):
            logger.warning(
                f"Admin flag '{flag_name}' denied for developer {current_developer.id}: "
                f"no 2FA on the account (REQUIRE_ADMIN_2FA)"
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_2FA_REQUIRED)

        if must_change:
            python_allow = False
            deny_reason = "must_change_password"
        elif is_admin or flag_held:
            python_allow = True
            deny_reason = None
        else:
            python_allow = False
            deny_reason = "missing_flag"

        opa_input = {
            "flag": flag_name,
            "developer_id": current_developer.id,
            "is_admin": is_admin,
            "must_change_password": must_change,
            "admin_flags": {f: bool(getattr(current_developer, f, False)) for f in valid_flags},
        }
        effective_allow = await shadow_check(
            "agentvault/admin/allow", opa_input, python_allow, label=flag_name
        )

        if effective_allow:
            return current_developer

        if deny_reason == "must_change_password":
            logger.warning(
                f"Admin access blocked: developer {current_developer.id} must change password first"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password change required before admin operations. POST /api/v1/auth/change-password",
            )
        if deny_reason == "missing_flag":
            logger.warning(
                f"Admin flag '{flag_name}' denied for developer: "
                f"{current_developer.email} (ID: {current_developer.id})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Admin flag required: {flag_name}",
            )
        # OPA-induced deny in enforce mode (Python allowed, OPA tightened).
        logger.warning(
            f"Admin flag '{flag_name}' denied by OPA enforce for developer: "
            f"{current_developer.email} (ID: {current_developer.id})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Admin flag required: {flag_name}",
        )

    return _check


def require_agent_permission(permission: str):
    """IRONKEY — the agent-side analog of ``require_admin_flag``.

    Authorizes AND RETURNS the ``Agent`` (a true drop-in for
    ``Depends(get_current_agent)`` — handlers keep consuming the same object). Swap
    only the ~33 MUTATING agent endpoints; GET/read endpoints stay on plain
    ``get_current_agent`` (an agent reading its own state is not worth a per-request
    policy call).

    Fleet-wide enforcement is the Python ``AGENT_RBAC_MODE`` switch (off|shadow|enforce)
    — NOT OPA (OPA is reg-a-only). ``off`` returns the agent unconditionally
    (byte-inert). ``shadow`` logs a would-deny but allows. ``enforce`` raises 403.
    Δ-safe: the check fires pre-escrow; a denial never touches the ledger.

        @router.post("/transfer")
        async def transfer(
            agent: models.Agent = Depends(security.require_agent_permission("teg.transfer"))
        ): ...
    """
    from agentvault_registry.agent_authz import ALL_PERMISSIONS
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Unknown agent permission: {permission}. Valid: {sorted(ALL_PERMISSIONS)}")

    async def _check(
        request: Request,
        current_agent: "models.Agent" = Security(get_current_agent),
        agent_info: dict = Depends(verify_agent_token),
        db: AsyncSession = Depends(get_db),
    ) -> "models.Agent":
        from agentvault_registry.agent_authz import (
            agent_rbac_mode, agent_delegation_mode, resolve_agent_permissions,
        )
        mode = agent_rbac_mode()
        if mode == "off":
            return current_agent

        agent_did = getattr(current_agent, "did", None)
        # L3 — on-behalf-of principal from the token's act claim (None = self-acting).
        act = agent_info.get("act") if isinstance(agent_info, dict) else None
        act_principal = act.get("sub") if isinstance(act, dict) else None
        # stash for enforce_agent_spend (xreg delegation caveat enforcement); set every
        # request so a prior request's value on this worker can never leak.
        _ACT_PRINCIPAL.set(act_principal)
        try:
            perms = await resolve_agent_permissions(db, agent_did, act_principal)
        except Exception as exc:  # a resolver error never 500s the request, and never authorizes it under enforce
            _authz_read_failed("permission", mode, agent_did, exc, f"perm={permission}")  # raises under enforce
            return current_agent  # shadow: observed and allowed

        # L4 — a presented capability token REPLACES the holder's own authority for this
        # request with the attenuated (caveat ∩ issuer-current) delegated set. The holder
        # is acting AS a delegate; a clamp of the issuer instantly empties `cap.permissions`.
        dmode = agent_delegation_mode()
        cap_token = request.headers.get("X-Capability-Token")
        cap = None
        if cap_token and cap_token.startswith("att_") and dmode != "off":
            try:
                from agentvault_registry.agent_delegation import resolve_capability
                cap, cap_reason = await resolve_capability(db, cap_token, agent_did)
            except Exception as exc:
                logger.warning(f"[IRONKEY-L4] capability resolve failed did={agent_did}: {exc!r}")
                cap, cap_reason = None, "resolver_error"
            if cap is None:
                logger.warning("[IRONKEY-L4] mode=%s did=%s perm=%s decision=CAP-DENY reason=%s",
                               dmode, agent_did, permission, cap_reason)
                if dmode == "enforce":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Capability token rejected: {cap_reason}",
                    )
            else:
                request.state.ironkey_capability = cap  # for budget debit / audit downstream
                if dmode == "enforce":
                    perms = set(cap["permissions"])  # attenuated authority replaces own

        allowed = permission in perms

        if not allowed:
            via = f" via_cap={cap['id']}" if cap else (f" act={act_principal}" if act_principal else "")
            logger.warning(
                "[AGENT-RBAC] mode=%s did=%s perm=%s decision=DENY held=%s%s",
                mode, agent_did, permission, sorted(perms), via,
            )
            if cap is not None and mode == "enforce":
                # a consumed capability asking for an action outside its caveats is a misuse
                # signal — feed the circuit breaker (best-effort; enforce-only inside).
                try:
                    from agentvault_registry.agent_delegation import note_capability_misuse
                    await note_capability_misuse(db, cap["id"], "permission_outside_caveats", actor_did=agent_did)
                except Exception:  # noqa: BLE001
                    pass
            # B1 — durable denial row for the owner's feed (best-effort, never raises,
            # shadow denials included — the would-deny is exactly what shadow is for).
            try:
                from agentvault_registry.services.admin_audit import log_ironkey_action
                await log_ironkey_action(
                    db, action="rbac_deny", actor_type="agent", actor_id=agent_did,
                    target_type="permission", target_id=permission,
                    outcome="deny", severity="warning",
                    details={"mode": mode, "act": act_principal,
                             "held": sorted(perms)[:40]},
                )
            except Exception:  # noqa: BLE001
                pass
            if mode == "enforce":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Agent lacks required permission: {permission}",
                )
        return current_agent

    return _check


async def enforce_agent_spend(
    db: "AsyncSession",
    agent_did: str,
    amount,
    *,
    currency: Optional[str] = None,
    counterparty_did: Optional[str] = None,
    same_registry: Optional[bool] = None,
    request: Optional[Request] = None,
) -> None:
    """IRONKEY L2 — call PRE-escrow in a money endpoint body to apply the spend policy.

    Respects ``AGENT_RBAC_MODE``: ``off`` → no-op; ``shadow`` → log a would-deny but
    proceed; ``enforce`` → raise 403 on violation. Δ-safe (fires before any mover/escrow;
    a denial has no ledger footprint). Both exposure axes are live: per-tx, and the
    rolling-24h daily cap via the velocity_snapshot materialization (which only covers
    completed hours — the current hour lags by up to ~1h, R-2 known limitation).
    """
    from agentvault_registry.agent_authz import agent_rbac_mode, check_spend_policy
    mode = agent_rbac_mode()
    if mode == "off":
        return
    try:
        allowed, reason = await check_spend_policy(
            db, agent_did, amount, currency=currency,
            counterparty_did=counterparty_did, same_registry=same_registry,
        )
    except Exception as exc:  # never 500 a money path over an authz read, and never pass one under enforce
        _authz_read_failed("spend policy", mode, agent_did, exc)  # raises under enforce
        return  # shadow: observed and allowed
    if not allowed:
        # ── B3 (RBAC plan): the approval threshold PARKS instead of dead-ending ──
        # Only the require_approval_above deny becomes a step-up: an APPROVED matching
        # ask is consumed atomically and the spend proceeds (still subject to the org
        # ceiling below); otherwise a pending ask is created/pushed and the deny reason
        # becomes actionable (`approval_pending:<id>`). Runs on an isolated session so
        # the 403 cannot roll the parked row away; any step-up failure degrades to the
        # original hard deny. Enforce-mode only — shadow keeps observing.
        if mode == "enforce" and str(reason or "").startswith("denied_above_approval_threshold"):
            try:
                from agentvault_registry.services.spend_approvals import step_up
                verdict = await step_up(
                    agent_did=agent_did, amount=amount, currency=currency,
                    counterparty_did=counterparty_did, policy_reason=str(reason),
                )
            except Exception:  # noqa: BLE001 — never 500 a money path over the queue
                verdict = None
            if verdict is not None and verdict.allowed:
                logger.info(
                    "[AGENT-RBAC] mode=%s did=%s decision=SPEND-APPROVED-STEPUP amount=%s %s",
                    mode, agent_did, amount, verdict.reason,
                )
                allowed = True
            elif verdict is not None:
                reason = verdict.reason
    if not allowed:
        logger.warning(
            "[AGENT-RBAC] mode=%s did=%s decision=SPEND-DENY amount=%s reason=%s",
            mode, agent_did, amount, reason,
        )
        try:  # B1 — durable denial row (best-effort)
            from agentvault_registry.services.admin_audit import log_ironkey_action
            await log_ironkey_action(
                db, action="spend_deny", actor_type="agent", actor_id=agent_did,
                target_type="spend", target_id=str(amount),
                outcome="deny", severity="warning",
                details={"mode": mode, "reason": str(reason), "currency": currency},
            )
        except Exception:  # noqa: BLE001
            pass
        if mode == "enforce":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Agent spend policy violation: {reason}",
            )

    # ── Track A5 (RBAC plan): ORG spend ceiling — tighten-only, frame-LOCAL ────────
    # An org caps every agent it OWNS (agents.organization_id — membership-based, so
    # an org agent cannot dodge the cap by self-acting) via settings.org_spend_ceiling_avt.
    # min(agent_cap, org_cap) arises naturally: the agent's own policy already denied
    # above; the org ceiling denies ADDITIONALLY here. One seam ⇒ all 10 spend sites.
    # Deny-only, pre-escrow → Δ-safe. A read error refuses under enforce with a 503 and is observed in shadow
    # (§SECFIX-1; it failed open before). get_org_settings rides its own SAVEPOINT.
    try:
        from agentvault_registry.services.org_policy import get_org_settings, org_spend_ceiling
        _org_ceiling = org_spend_ceiling(await get_org_settings(db, agent_did))
    except Exception as exc:  # noqa: BLE001
        _authz_read_failed("org ceiling", mode, agent_did, exc)  # raises under enforce
        _org_ceiling = None
    if _org_ceiling is not None:
        from decimal import Decimal as _OD, InvalidOperation as _OIE
        try:
            _over = _OD(str(amount)) > _OD(str(_org_ceiling))
        except (_OIE, TypeError, ValueError):
            _over = False
        if _over:
            logger.warning(
                "[AGENT-RBAC] mode=%s did=%s decision=ORG-CEILING-DENY amount=%s ceiling=%s",
                mode, agent_did, amount, _org_ceiling,
            )
            try:  # B1 — durable denial row (best-effort)
                from agentvault_registry.services.admin_audit import log_ironkey_action
                await log_ironkey_action(
                    db, action="org_ceiling_deny", actor_type="agent", actor_id=agent_did,
                    target_type="spend", target_id=str(amount),
                    outcome="deny", severity="warning",
                    details={"mode": mode, "ceiling": float(_org_ceiling)},
                )
            except Exception:  # noqa: BLE001
                pass
            if mode == "enforce":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Org spend ceiling exceeded: {amount} > {_org_ceiling}",
                )

    # ── IRONKEY xreg delegation caveat enforcement (DEBUG-2026-07-18 finding#2 FULL) ──
    # When this spend is performed on-behalf-of a cross-registry issuer (the presented token
    # carried act.sub=agent:<issuer> and a live delegation credential minted the grant), apply
    # the issuer-attached caveats (max_per_tx / allowed_currencies) recorded on the credential
    # but previously advisory-only. The att_ capability-token path already enforces caveats;
    # this closes the coarser xreg-grant path. Deny-only, pre-escrow → Δ-safe.
    act = _ACT_PRINCIPAL.get()
    if act and isinstance(act, str) and act.startswith("agent:"):
        try:
            row = (await db.execute(text(
                "SELECT id, caveats FROM agent_delegation_credentials "
                "WHERE issuer_did = :iss AND delegate_did = :del AND revoked_at IS NULL "
                "AND caveats IS NOT NULL AND caveats::text <> '{}' "
                "ORDER BY received_at DESC LIMIT 1"
            ), {"iss": act[len("agent:"):], "del": agent_did})).first()
            cav = row[1] if row and row[1] else None
            _xcred_id = row[0] if row else None
        except Exception as exc:  # never 500 a money path over a caveat lookup, and never pass one under enforce
            _authz_read_failed("delegation caveat", mode, agent_did, exc, f"act={act}")  # raises under enforce
            cav = None
        if isinstance(cav, dict) and cav:
            from decimal import Decimal as _D, InvalidOperation as _IE
            over_cap = False
            mpt = cav.get("max_per_tx")
            if mpt is not None:
                try:
                    over_cap = _D(str(amount)) > _D(str(mpt))
                except (_IE, ValueError, TypeError):
                    over_cap = True  # §SECFIX-1: an issuer's bound that cannot be read binds; it passed everything before
            # §auditfix (2026-07-19): durable audit row for an ENFORCED caveat deny only.
            # The writer commits the session — safe solely because the very next line
            # raises 403 (pre-escrow, request dies; nothing of the money path is pending).
            # Shadow mode deliberately gets NO row here: the request proceeds into real
            # escrow writes and a mid-flight commit on a money path is not worth a metric.
            async def _audit_caveat_deny(caveat: str, extra: dict) -> None:
                try:
                    from agentvault_registry.services.admin_audit import log_ironkey_action
                    await log_ironkey_action(
                        db, action="delegation_caveat_deny", actor_type="agent",
                        actor_id=agent_did, target_type="principal", target_id=act,
                        outcome="denied", severity="warning",
                        details={"caveat": caveat, "amount": str(amount), **extra},
                    )
                except Exception:  # noqa: BLE001 — the deny itself already stands
                    logger.debug("[IRONKEY-XREG] caveat-deny audit row skipped", exc_info=True)
            if over_cap:
                logger.warning("[IRONKEY-XREG] mode=%s did=%s SPEND-DENY caveat=max_per_tx amount=%s cap=%s act=%s",
                               mode, agent_did, amount, mpt, act)
                if mode == "enforce":
                    await _audit_caveat_deny("max_per_tx", {"max_per_tx": str(mpt)})
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Delegation caveat violation: amount {amount} exceeds max_per_tx {mpt}")
            allowed = cav.get("allowed_currencies")
            if isinstance(allowed, list) and allowed and currency and currency not in allowed:
                logger.warning("[IRONKEY-XREG] mode=%s did=%s SPEND-DENY caveat=currency cur=%s allowed=%s act=%s",
                               mode, agent_did, currency, allowed, act)
                if mode == "enforce":
                    await _audit_caveat_deny("allowed_currencies", {"currency": currency, "allowed": allowed})
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Delegation caveat violation: currency {currency} not in allowed {allowed}")
            # ── B4/B6 polish: the same richer axes on the CROSS-REGISTRY credential path —
            # geo is at its most meaningful here (the credential mirrors an issuer's caveats
            # to a foreign frame; geo_allow bounds WHERE that mirrored authority executes).
            _xgeo = cav.get("geo_allow")
            if isinstance(_xgeo, list) and _xgeo:
                from agentvault_registry.agent_authz import _geo_ok as _xg_ok, local_registry_name as _xg_name
                if not _xg_ok(_xgeo):
                    logger.warning("[IRONKEY-XREG] mode=%s did=%s SPEND-DENY caveat=geo_allow local=%s allowed=%s act=%s",
                                   mode, agent_did, _xg_name(), _xgeo, act)
                    if mode == "enforce":
                        await _audit_caveat_deny("geo_allow", {"registry": _xg_name(), "geo_allow": _xgeo})
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Delegation caveat violation: registry {_xg_name()} not in geo_allow {_xgeo}")
            _xrate = cav.get("rate_per_hour")
            if _xrate is not None and _xcred_id is not None:
                from agentvault_registry.agent_authz import spend_rate_exceeded as _xr_exceeded
                _xover = await _xr_exceeded(f"xcred:{_xcred_id}", int(_xrate))
                # issuer-set bound → fail CLOSED like the att_-token rate (None = unverifiable)
                if _xover is None or _xover:
                    _why = "rate window unavailable" if _xover is None else f"over {_xrate} attempts this hour"
                    logger.warning("[IRONKEY-XREG] mode=%s did=%s SPEND-DENY caveat=rate_per_hour %s act=%s",
                                   mode, agent_did, _why, act)
                    if mode == "enforce":
                        await _audit_caveat_deny("rate_per_hour", {"rate_per_hour": str(_xrate), "why": _why})
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Delegation caveat violation: rate_per_hour — {_why}")

    # ── IRONKEY L4 capability-token caveat enforcement on the money axis (S1, 2026-07-24) ──
    # require_agent_permission resolves a presented X-Capability-Token and stashes it on
    # request.state precisely "for budget debit downstream" — but until now NOTHING read it:
    # an att_ token's max_per_tx / currency / budget / max_uses caveats were inert on the
    # money rails (a budget_total=10 token could move unlimited AVT via /teg/transfer).
    # Deny-only, pre-escrow; the budget/uses debit is an atomic guarded UPDATE riding THIS
    # request's transaction (a failed money leg rolls it back with everything else). Δ-safe.
    # NOTE: the explicit /agents/capabilities/consume endpoint also debits — a client doing
    # both double-counts, which errs in the conservative (tighter-budget) direction.
    cap = getattr(getattr(request, "state", None), "ironkey_capability", None) if request is not None else None
    if isinstance(cap, dict) and cap.get("id") is not None:
        from agentvault_registry.agent_authz import agent_delegation_mode
        dmode = agent_delegation_mode()
        if dmode != "off":
            from decimal import Decimal as _D, InvalidOperation as _IE
            ccav = cap.get("caveats") or {}

            async def _cap_deny(caveat: str, reason_txt: str, extra: dict) -> None:
                logger.warning("[IRONKEY-L4] mode=%s did=%s SPEND-DENY cap=%s caveat=%s amount=%s %s",
                               dmode, agent_did, cap.get("id"), caveat, amount, reason_txt)
                if dmode == "enforce":
                    try:
                        from agentvault_registry.services.admin_audit import log_ironkey_action
                        await log_ironkey_action(
                            db, action="capability_caveat_deny", actor_type="agent",
                            actor_id=agent_did, target_type="capability_token",
                            target_id=str(cap.get("id")), outcome="denied", severity="warning",
                            details={"caveat": caveat, "amount": str(amount), **extra},
                        )
                    except Exception:  # noqa: BLE001 — the deny itself already stands
                        logger.debug("[IRONKEY-L4] caveat-deny audit row skipped", exc_info=True)
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                        detail=f"Capability caveat violation: {reason_txt}")

            mpt = ccav.get("max_per_tx")
            if mpt is not None:
                try:
                    _over = _D(str(amount)) > _D(str(mpt))
                except (_IE, ValueError, TypeError):
                    _over = True  # §SECFIX-1: an issuer's bound that cannot be read binds; it passed everything before
                if _over:
                    await _cap_deny("max_per_tx", f"amount {amount} exceeds max_per_tx {mpt}",
                                    {"max_per_tx": str(mpt)})
            # §TWOAGENT (2026-09-23): counterparty_allow — WHO this token may pay. /agents/spawn writes it onto the
            # birth token and attenuation checks it is a subset of the parent's, but no money rail read it: a hand
            # bound to one seller could pay anyone. Fail-CLOSED like the other issuer-set bounds, so a spend that
            # names no counterparty (a market order, a bridge, a system transfer) cannot use a counterparty-bound token.
            ccpa = ccav.get("counterparty_allow")
            if isinstance(ccpa, list) and ccpa:
                if not counterparty_did:
                    await _cap_deny("counterparty_allow",
                                    f"this capability may only pay {ccpa}, and this spend names no counterparty",
                                    {"counterparty_allow": ccpa})
                elif counterparty_did not in ccpa:
                    await _cap_deny("counterparty_allow",
                                    f"counterparty {counterparty_did} is not in counterparty_allow {ccpa}",
                                    {"counterparty": counterparty_did, "counterparty_allow": ccpa})
            tok_cur = cap.get("currency")
            if tok_cur and currency and currency != tok_cur:
                await _cap_deny("currency", f"currency {currency} is not the token's {tok_cur}",
                                {"token_currency": tok_cur, "currency": currency})
            acur = ccav.get("allowed_currencies")
            if isinstance(acur, list) and acur and currency and currency not in acur:
                await _cap_deny("allowed_currencies", f"currency {currency} not in allowed {acur}",
                                {"currency": currency, "allowed": acur})
            # ── B4 (RBAC plan): geo_allow — where this token may EXECUTE spends. Each
            # registry checks its own name, so an issuer bounds where delegated
            # authority is exercisable even as the token travels cross-frame.
            cgeo = ccav.get("geo_allow")
            if isinstance(cgeo, list) and cgeo:
                from agentvault_registry.agent_authz import _geo_ok, local_registry_name
                if not _geo_ok(cgeo):
                    await _cap_deny("geo_allow",
                                    f"registry {local_registry_name()} not in geo_allow {cgeo}",
                                    {"registry": local_registry_name(), "geo_allow": cgeo})
            # ── B4: rate_per_hour — issuer-set attempts/hour bound, live Redis window.
            # FAIL-CLOSED: an issuer's explicit bound must hold even through a Redis
            # outage (contrast: the policy-side rate in check_spend_policy fails open —
            # that one is the developer's own knob, availability-biased).
            crate = ccav.get("rate_per_hour")
            if crate is not None:
                from agentvault_registry.agent_authz import spend_rate_exceeded
                over = await spend_rate_exceeded(f"cap:{cap.get('id')}", int(crate))
                if over is None:
                    await _cap_deny("rate_unavailable",
                                    "rate_per_hour bound could not be verified (window store unavailable)",
                                    {"rate_per_hour": str(crate)})
                elif over:
                    await _cap_deny("rate_per_hour",
                                    f"over {crate} spend attempts in the current hour",
                                    {"rate_per_hour": str(crate)})
            if dmode == "enforce":
                # Atomic budget/uses admission+debit — rowcount 0 means a concurrent spend
                # raced this one past the cap, or the token just exhausted. Rides the
                # request txn: committed with the money leg, rolled back with a failure.
                try:
                    _amt = _D(str(amount))
                except (_IE, ValueError, TypeError):
                    _amt = None
                if _amt is None:  # §SECFIX-1: an unreadable amount used to debit 0 and pass
                    await _cap_deny("budget", "the spend amount could not be read against the capability budget",
                                    {"amount": str(amount)})
                # §DOCSFIX D6-154: both live statuses, as the resolver reads them. /agents/capabilities/consume sets a
                # token 'active', and matching only 'issued' refused such a token here as exhausted with its budget
                # intact; the budget, the uses, the revocation and 'exhausted' still bind it.
                debited = await db.execute(text(
                    "UPDATE agent_capability_tokens "
                    "SET budget_spent = budget_spent + :a, uses = uses + 1 "
                    "WHERE id = :i AND status IN ('issued', 'active') AND revoked_at IS NULL "
                    "AND (budget_total IS NULL OR budget_spent + :a <= budget_total) "
                    "AND (max_uses IS NULL OR uses < max_uses)"
                ), {"a": _amt, "i": cap["id"]})
                if getattr(debited, "rowcount", 0) == 0:
                    await _cap_deny("budget", "capability budget or uses exhausted",
                                    {"budget_remaining": str(cap.get("budget_remaining"))})


# --- ADDED: Agent Authentication Dependencies ---
async def verify_agent_token(
    request: Request,
    token: str = Depends(oauth2_scheme_required),
) -> dict:
    """
    FastAPI dependency to verify JWT token for agents.
    Returns the payload containing agent DID and ID.
    Raises HTTPException on failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate agent credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        agent_did: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")
        agent_id_str: Optional[str] = payload.get("agent_id")
        
        if agent_did is None or token_type != "agent" or agent_id_str is None:
            logger.warning("Agent JWT verification failed: missing or invalid claims")
            raise credentials_exception

        try:
            agent_id = int(agent_id_str)
            # L3 — carry the optional RFC 8693 `act` (on-behalf-of) claim through so the
            # authz resolver + audit can answer "on whose authority." Absent = self-acting.
            act = payload.get("act") if isinstance(payload.get("act"), dict) else None
            _stash_rate_principal(request, f"a:{agent_did}")
            # §FEFRAME W3: an owner session token's claims ride along for owner_token_refusal (None on any other token)
            # D6-281: and the credential version a token minted from the agent's credential carries (agent_token_refusal)
            return {"did": agent_did, "id": agent_id, "act": act, "via": payload.get("via"),
                    "owner": payload.get("owner"), "owner_tv": payload.get("owner_tv"), "cv": payload.get("cv")}
        except ValueError:
            logger.warning(f"Agent JWT verification failed: agent_id '{agent_id_str}' is not an integer")
            raise credentials_exception
            
    except JWTError as e:
        logger.warning(f"Agent JWT verification failed: {e}")
        raise credentials_exception from e
    except HTTPException:
        # §MCPTEST30 (V0545): the refusals raised ABOVE (a token without the agent claims, a non-integer agent id) are
        # already logged at WARNING; the catch-all below caught them too and logged every one as "Unexpected error"
        # with a traceback (15 in 30 minutes on sbx-alpha: a developer's token at an agent route is a normal 401)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during agent JWT verification: {e}", exc_info=True)
        raise credentials_exception from e


async def get_current_agent(
    db: AsyncSession = Depends(get_db),
    agent_info: dict = Depends(verify_agent_token)
) -> models.Agent:
    """
    FastAPI dependency to get the current agent based on a verified JWT token.
    Raises HTTPException(401) if the agent doesn't exist or is not active.
    """
    from agentvault_registry.opa_shadow import shadow_check

    agent_did = agent_info["did"]
    agent = await agent_crud.get_agent_by_did(db=db, did=agent_did)

    agent_status = getattr(agent, "status", None) if agent is not None else None
    is_blocked = agent_status in ("suspended", "revoked")
    python_allow = agent is not None and not is_blocked

    opa_input = {
        "agent_did": agent_did,
        "agent_exists": agent is not None,
        "status": agent_status,
    }
    effective_allow = await shadow_check(
        "agentvault/agent/allow", opa_input, python_allow, label="agent_jwt"
    )

    if agent is None:
        logger.warning(f"Authenticated agent DID {agent_did} not found in database")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent associated with token not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_blocked:
        logger.warning(f"Authenticated agent DID {agent_did} is blocked (status: {agent_status})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Agent account is {agent_status}"
        )

    if not effective_allow:
        # Reached only when OPA enforce-mode denies a request Python would allow.
        logger.warning(f"Agent JWT denied by OPA enforce for DID {agent_did}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent authorization denied by policy"
        )

    _owner_why = await agent_token_refusal(db, agent_info, agent)   # D6-281: the credential version, then the owner
    if _owner_why:
        logger.info(f"Agent token for {agent_did} refused: {_owner_why}")
        raise agent_token_refusal_exception(agent_info, _owner_why)

    # Update last active timestamp
    await agent_crud.update_agent_last_active(db, agent.id)

    logger.debug(f"Successfully identified current agent: DID={agent.did}, ID={agent.id}")
    return agent
# --- END ADDED ---

# --- ADDED: Unified Authentication Dependencies ---
async def get_current_actor_for_read(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme_required),
) -> dict:
    """
    Dual-auth dependency for read endpoints that should accept EITHER:
      - an agent JWT (caller is the agent — caller will enforce self-only on path DID)
      - a developer JWT (caller is the developer — full read across all agents)

    Returns a dict with shape:
      {"kind": "agent",     "agent_did": str, "agent": Agent}
      {"kind": "developer", "developer": Developer}

    Raises 401 if the token is missing, invalid, expired, or for a deleted/blocked principal.

    This is the X34 fix (2026-05-06): replaces strict `get_current_agent` on
    GET /contracts/{id}, GET /contracts/agent/{did}, GET /disputes/agent/{did}
    so the developer-managing-agents UI can browse without being forced to mint
    an agent JWT. Anonymous still 401 (D1 anti-IDOR posture preserved).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.warning(f"actor_for_read: token decode failed: {e}")
        raise credentials_exception from e

    token_type = payload.get("type")

    # Agent JWT path
    if token_type == "agent":
        agent_did = payload.get("sub")
        agent_id_str = payload.get("agent_id")
        if not agent_did or not agent_id_str:
            raise credentials_exception
        agent = await agent_crud.get_agent_by_did(db=db, did=agent_did)
        if agent is None:
            raise credentials_exception
        agent_status = getattr(agent, "status", None)
        if agent_status in ("suspended", "revoked"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Agent account is {agent_status}",
            )
        _owner_why = await agent_token_refusal(db, payload, agent)   # D6-281
        if _owner_why:
            raise agent_token_refusal_exception(payload, _owner_why)
        return {"kind": "agent", "agent_did": agent_did, "agent": agent}

    # Developer JWT path — the SAME refusals every other developer route applies, through the same two helpers
    # the optional twin below already uses. §TWOAGENT #18 (2026-09-23): this branch used to check only "the
    # developer exists", so a token revoked by logout / password change / admin force-logout (`tv` behind
    # `token_version`), a refresh token, a password-set token, and a deleted, suspended or anonymized developer
    # all kept READING and WRITING chat (measured on EU: after logout /developers/me 401, chat list 200, chat
    # create 201). A refusal reads exactly as the required path's 401.
    claims = await verify_access_token_optional_claims(f"Bearer {token}")
    developer = await get_current_developer_optional(db=db, claims=claims)
    if developer is None:
        raise credentials_exception
    if hasattr(developer, "is_active") and not developer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Developer account is inactive",
        )
    return {"kind": "developer", "developer": developer}


async def get_current_actor_for_read_or_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme_required),
) -> dict:
    """V0650 (m): get_current_actor_for_read, plus a developer API key (`avreg_`).

    The chat read routes decoded JWTs only, so a developer API key, which is what the MCP bridges, the CLI and the
    sessions' tools present, answered 401 there. A key now resolves exactly as on every other developer route
    (verify_access_token_required, then get_current_developer): the key acts as its developer, a revoked or expired key
    is refused 401, an MCP-scoped key is held to the routes it may reach and its scopes are published for the gates. A
    JWT, developer or agent, goes through get_current_actor_for_read unchanged. Read routes only: no write route takes
    this.
    """
    if token.startswith("avreg_"):
        developer_id = await verify_access_token_required(request=request, token=token, db=db)
        developer = await get_current_developer(db=db, developer_id=developer_id)
        if hasattr(developer, "is_active") and not developer.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account is inactive")
        return {"kind": "developer", "developer": developer}
    return await get_current_actor_for_read(db=db, token=token)


async def get_current_actor_for_read_optional(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> Optional[dict]:
    """§TRUSTCHAIN (2026-09-12) — the OPTIONAL twin of `get_current_actor_for_read`.

    Returns `{"kind": "agent", "agent_did", "agent"}` for a live agent JWT,
    `{"kind": "developer", "developer"}` for a live developer JWT, and None for no header, an
    invalid token, or a principal the required paths would refuse (a suspended or revoked agent;
    a developer whose token_version moved on, or who is deleted or suspended). Never raises.

    Why it exists: journal 45 says "what a member OR AN AGENT HOLDING A TOKEN may read is what
    this frame actually thinks" of the registry hosting a discovered agent, and the §DISCOTRUST
    routes resolved their viewer with `get_current_developer_optional`, whose `sub` must be an
    integer developer id — so an agent JWT, the very caller journal 45 is about, received no
    verdict (measured §BATCH0911, decided §TRUSTCHAIN). The developer half delegates to
    `get_current_developer_optional` so its three refusals stay in ONE place; the agent half
    applies the same two refusals `get_current_actor_for_read` applies.
    """
    if authorization is None:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.debug(f"actor_for_read_optional: token decode failed: {e}")
        return None
    except Exception as e:  # noqa: BLE001
        logger.error(f"actor_for_read_optional: unexpected decode error: {e}", exc_info=True)
        return None

    if payload.get("type") == "agent":
        agent_did = payload.get("sub")
        if not agent_did or not payload.get("agent_id"):
            return None
        try:
            agent = await agent_crud.get_agent_by_did(db=db, did=agent_did)
        except Exception as e:  # noqa: BLE001
            logger.error(f"actor_for_read_optional: agent lookup failed for {agent_did}: {e}", exc_info=True)
            return None
        if agent is None or getattr(agent, "status", None) in ("suspended", "revoked"):
            logger.info(f"actor_for_read_optional: agent {agent_did} missing or blocked; read as anonymous.")
            return None
        try:
            _owner_why = await agent_token_refusal(db, payload, agent)   # D6-281
        except Exception as e:  # noqa: BLE001 — never raises: an unreadable owner reads as anonymous, never as the agent
            logger.error(f"actor_for_read_optional: owner check failed for {agent_did}: {e}", exc_info=True)
            return None
        if _owner_why:
            logger.info(f"actor_for_read_optional: agent token for {agent_did} refused ({_owner_why}); read as anonymous.")
            return None
        return {"kind": "agent", "agent_did": agent_did, "agent": agent}

    claims = await verify_access_token_optional_claims(authorization)
    developer = await get_current_developer_optional(db=db, claims=claims)
    if developer is None:
        return None
    return {"kind": "developer", "developer": developer}


async def get_current_developer_unified(
    # §pass52 PR-2: declare security schemes in OpenAPI without changing
    # runtime behavior. `oauth2_scheme_optional` and `_api_key_header` use
    # auto_error=False so the function still tries the raw Header() paths
    # below — but FastAPI now emits `security: [{OAuth2PasswordBearer:[]}]`
    # in the spec for every endpoint that uses this dependency.
    _oauth2_token: Optional[str] = Security(oauth2_scheme_optional),
    authorization: Optional[str] = Header(None, description="JWT Bearer token or API key"),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key", description="API key header"),
    db: AsyncSession = Depends(get_db),
    request: Request = None,   # injected by FastAPI; a direct caller passes it (D6-514: the route a key may reach)
) -> models.Developer:
    """
    Unified authentication dependency that accepts either:
    1. JWT Bearer token in Authorization header
    2. API key in X-Api-Key header
    3. API key as Bearer token (for backward compatibility)

    Returns the authenticated developer or raises HTTPException.
    """
    # First, try X-Api-Key header if present
    if x_api_key:
        logger.debug(f"Attempting API key authentication via X-Api-Key header")
        developer = await _developer_for_api_key(db, x_api_key)
        if developer:
            await _publish_presented_key(db, x_api_key, request)   # §POCKETPAIR: this path published nothing before
            logger.debug(f"Successfully authenticated developer ID {developer.id} via X-Api-Key")
            return developer
        else:
            logger.warning(f"Invalid API key provided in X-Api-Key header")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key"
            )
    
    # Second, try Authorization header
    if authorization:
        parts = authorization.split()
        if len(parts) != 2:
            logger.warning(f"Invalid Authorization header format: {authorization[:20]}...")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format"
            )
        
        scheme, credential = parts[0].lower(), parts[1]
        
        if scheme == "bearer":
            # Check if it's a JWT token (has 3 segments)
            if credential.count('.') == 2:
                # Looks like a JWT, try to decode it
                logger.debug("Attempting JWT authentication")
                try:
                    payload = jwt.decode(credential, SECRET_KEY, algorithms=[ALGORITHM])
                except JWTError as e:
                    payload = None
                    logger.debug(f"JWT decode failed: {e}")
                    # Fall through to try as API key
                if payload is not None:
                    # D6-731: the required verifier's rules, not a weaker copy: a developer ACCESS token only (no refresh,
                    # password-set or 2FA partial token) whose token_version is current.
                    developer_id = access_token_subject(payload)
                    try:
                        _current = developer_id is not None and await token_version_current(
                            db, developer_id, payload.get("tv"))
                    except SQLAlchemyError as e:
                        raise _credential_store_unavailable(e) from e
                    if not _current:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid token"
                        )
                    # §MCPTEST30 (V0553): the developer's own row only (crud get_developer_by_id_strict)
                    developer = await developer_crud.get_developer_by_id_lean(db=db, developer_id=developer_id)

                    if not developer:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User not found"
                        )

                    logger.debug(f"Successfully authenticated developer ID {developer.id} via JWT")
                    return developer
            
            # Not a JWT or JWT decode failed, try as API key
            logger.debug("Attempting API key authentication via Bearer token")
            developer = await _developer_for_api_key(db, credential)
            if developer:
                await _publish_presented_key(db, credential, request)   # §POCKETPAIR: published nothing before
                logger.debug(f"Successfully authenticated developer ID {developer.id} via API key as Bearer")
                return developer
    
    # No valid authentication provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"}
    )
# --- END ADDED ---
