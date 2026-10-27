"""
Docker Registry v2 Token Authentication Server (f050)

Implements the Docker Distribution token auth protocol for images.raphaeljeziorny.com.
Replaces htpasswd-based auth with DB-backed pull tokens and short-lived RS256 JWTs.

Endpoint:
    GET /api/v1/docker-registry/token?service=...&scope=repository:name:actions

Protocol flow:
    1. docker pull → Registry returns 401 with WWW-Authenticate: Bearer realm=<this endpoint>
    2. Docker client sends Basic auth (operator-name:dpt_token) to this endpoint
    3. This endpoint validates credentials against OperatorApplication.docker_pull_token_hash
    4. Returns signed RS256 JWT with scoped access claims (15 min expiry)
    5. Docker client retries pull with Bearer JWT — Registry verifies against mounted cert
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
import jwt  # PyJWT (§DEPS: python-jose is gone)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.config import settings
from agentvault_registry.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/docker-registry", tags=["Docker Registry Auth"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_ALLOWED_REPOS = ["registry", "teg-layer", "cert-writer", "event-store"]

# ---------------------------------------------------------------------------
# Signing key (loaded once at startup)
# ---------------------------------------------------------------------------

_signing_key_pem: Optional[bytes] = None
_signing_key_id: Optional[str] = None


def load_signing_key() -> None:
    """Load the RSA private key for JWT signing. Called once at app startup."""
    global _signing_key_pem, _signing_key_id

    key_path = getattr(settings, "DOCKER_TOKEN_SIGNING_KEY_PATH", "") or os.getenv(
        "DOCKER_TOKEN_SIGNING_KEY_PATH", ""
    )
    if not key_path:
        logger.warning("DOCKER_TOKEN_SIGNING_KEY_PATH not set — Docker token auth disabled")
        return

    path = Path(key_path)
    if not path.is_file():
        logger.warning(f"Docker token signing key not found at {path} — token auth disabled")
        return

    pem_bytes = path.read_bytes()
    private_key = serialization.load_pem_private_key(pem_bytes, password=None)
    _signing_key_pem = pem_bytes

    # Compute key ID matching Docker Registry's libtrust library.
    # libtrust uses SubjectPublicKeyInfo (SPKI) DER encoding of the public key,
    # SHA-256 hashes it, base32-encodes first 30 bytes, groups by 4 with colons.
    # Verified against Go libtrust v0.0.0-20160708172513 via direct execution.
    pub_der = private_key.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    digest = hashlib.sha256(pub_der).digest()
    b32 = base64.b32encode(digest[:30]).decode("ascii")
    _signing_key_id = ":".join(b32[i : i + 4] for i in range(0, 48, 4))

    logger.info(f"Docker token signing key loaded (kid={_signing_key_id})")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_basic_auth(authorization: Optional[str]) -> tuple[str, str]:
    """Parse Authorization: Basic <base64> header. Returns (username, password)."""
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Basic realm=\"TheProtocol Image Registry\""},
        )
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
        return username, password
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Basic auth credentials",
            headers={"WWW-Authenticate": "Basic realm=\"TheProtocol Image Registry\""},
        )


def _parse_scope(scope_str: Optional[str]) -> list[dict]:
    """
    Parse Docker scope string(s) into access array.
    Format: 'repository:<name>:<actions>' where actions are comma-separated.
    """
    if not scope_str:
        return []

    scopes = []
    for part in scope_str.split(" "):
        part = part.strip()
        if not part:
            continue
        segments = part.split(":")
        if len(segments) >= 3 and segments[0] == "repository":
            repo_name = segments[1]
            actions = segments[2].split(",")
            scopes.append({
                "type": "repository",
                "name": repo_name,
                "actions": [a.strip() for a in actions if a.strip()],
            })
    return scopes


def _authorize_access(
    requested: list[dict],
    allowed_repos: list[str],
    is_admin: bool,
) -> list[dict]:
    """Filter requested scopes to what the authenticated user is allowed."""
    if is_admin:
        # Admin: full push+pull on all repositories
        return requested if requested else []

    granted = []
    for scope in requested:
        if scope.get("type") != "repository":
            continue
        repo = scope.get("name", "")
        if repo not in allowed_repos:
            continue
        # Operators: pull only
        actions = [a for a in scope.get("actions", []) if a == "pull"]
        if actions:
            granted.append({"type": "repository", "name": repo, "actions": actions})
    return granted


def _anonymous_public_pull(requested: list[dict]) -> Optional[list[dict]]:
    """§RELEASECHANNEL: the pull scopes an ANONYMOUS client may hold, or None when it may hold none.

    None unless core.release_channel.public_pull_enabled() (the switch, default off). With the switch on, every
    requested scope must be a repository under the public namespace ("<ns>/<name>") asking for `pull` only; one scope
    outside that, or any push, and the answer is None (the caller then answers 401 exactly as before). An empty
    request (the client's /v2/ ping) yields an empty grant, which Distribution accepts for the ping and nothing else.
    """
    from agentvault_registry.core import release_channel as _rc
    if not _rc.public_pull_enabled():
        return None
    ns = _rc.public_namespace() + "/"
    granted: list[dict] = []
    for scope in requested:
        if scope.get("type") != "repository":
            return None
        name = scope.get("name") or ""
        actions = [a for a in scope.get("actions", []) if a]
        if not name.startswith(ns) or name.count("/") != 1 or not actions or any(a != "pull" for a in actions):
            return None
        granted.append({"type": "repository", "name": name, "actions": ["pull"]})
    return granted


def _build_token(access: list[dict], subject: str) -> str:
    """Build a Docker Registry v2 JWT signed with RS256."""
    if _signing_key_pem is None or _signing_key_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token signing key not configured",
        )

    now = int(time.time())
    expiry = getattr(settings, "DOCKER_TOKEN_EXPIRY_SECONDS", None) or int(
        os.getenv("DOCKER_TOKEN_EXPIRY_SECONDS", "900")
    )
    issuer = getattr(settings, "DOCKER_TOKEN_ISSUER", None) or os.getenv(
        "DOCKER_TOKEN_ISSUER", "theprotocol-registry-auth"
    )
    service = getattr(settings, "DOCKER_TOKEN_SERVICE", None) or os.getenv(
        "DOCKER_TOKEN_SERVICE", "images.raphaeljeziorny.com"
    )

    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": service,
        "exp": now + expiry,
        "nbf": now,
        "iat": now,
        "jti": str(uuid_mod.uuid4()),
        "access": access,
    }

    token = jwt.encode(
        payload,
        _signing_key_pem,
        algorithm="RS256",
        headers={"kid": _signing_key_id},
    )
    return token


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/token")
async def docker_registry_token(
    request: Request,
    service: str = Query(..., description="Docker registry service name"),
    scope: Optional[str] = Query(None, description="Requested scope (repository:name:actions)"),
    account: Optional[str] = Query(None, description="Account name hint from Docker client"),
    db: AsyncSession = Depends(get_db),
):
    """
    Docker Registry v2 Token endpoint.

    Called by Docker clients after receiving a 401 from the registry.
    Authenticates via Basic auth, returns a signed JWT granting scoped access.
    """
    # 1. Parse Basic auth. §RELEASECHANNEL: a request WITHOUT credentials may still get a pull token for the
    #    public namespace, and only while the switch is on; every other anonymous request is refused as before.
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        anonymous = _anonymous_public_pull(_parse_scope(scope))
        if anonymous is not None:
            _expiry = getattr(settings, "DOCKER_TOKEN_EXPIRY_SECONDS", None) or int(
                os.getenv("DOCKER_TOKEN_EXPIRY_SECONDS", "900")
            )
            logger.info("Docker token auth: anonymous public pull for %s from %s",
                        [a["name"] for a in anonymous] or "/v2/", request.client.host if request.client else "unknown")
            return {
                "token": _build_token(anonymous, "anonymous"),
                "expires_in": _expiry,
                "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            }
    username, password = _parse_basic_auth(auth_header)

    # 2. Authenticate
    is_admin = False
    allowed_repos = DEFAULT_ALLOWED_REPOS
    admin_username = os.getenv("DOCKER_ADMIN_USERNAME", "theprotocol-admin")

    if username == admin_username:
        # Admin authentication via env var hash
        admin_hash = getattr(settings, "DOCKER_ADMIN_PULL_TOKEN_HASH", "") or os.getenv(
            "DOCKER_ADMIN_PULL_TOKEN_HASH", ""
        )
        if not admin_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin token auth not configured",
            )
        presented_hash = hashlib.sha256(password.encode()).hexdigest()
        if not hmac.compare_digest(presented_hash, admin_hash.lower()):
            logger.warning(f"Docker token auth: invalid admin credentials from {request.client.host if request.client else 'unknown'}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        is_admin = True
        logger.info(f"Docker token auth: admin authenticated from {request.client.host if request.client else 'unknown'}")
    else:
        # Operator authentication via DB
        presented_hash = hashlib.sha256(password.encode()).hexdigest()
        result = await db.execute(
            select(models.OperatorApplication).where(
                models.OperatorApplication.docker_pull_token_hash == presented_hash,
                models.OperatorApplication.docker_registry_username == username,
            )
        )
        app_record = result.scalars().first()

        if app_record is None:
            logger.warning(
                f"Docker token auth: no matching operator for {username} "
                f"from {request.client.host if request.client else 'unknown'}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        # Check operator lifecycle status
        if app_record.status != "approved" or app_record.revoked_at is not None:
            logger.warning(
                f"Docker token auth: operator {username} denied "
                f"(status={app_record.status}, revoked={app_record.revoked_at is not None})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operator access revoked or suspended",
            )

        # Parse allowed repos (JSON array or default)
        if app_record.docker_pull_allowed_repos:
            try:
                allowed_repos = json.loads(app_record.docker_pull_allowed_repos)
            except (json.JSONDecodeError, TypeError):
                allowed_repos = DEFAULT_ALLOWED_REPOS

        logger.info(
            f"Docker token auth: operator {username} authenticated "
            f"from {request.client.host if request.client else 'unknown'}"
        )

    # 3. Parse requested scope
    requested_scopes = _parse_scope(scope)

    # 4. Authorize
    granted_access = _authorize_access(requested_scopes, allowed_repos, is_admin)

    # 5. Build and sign JWT
    token = _build_token(granted_access, username)

    expiry = getattr(settings, "DOCKER_TOKEN_EXPIRY_SECONDS", None) or int(
        os.getenv("DOCKER_TOKEN_EXPIRY_SECONDS", "900")
    )

    return {
        "token": token,
        "expires_in": expiry,
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
