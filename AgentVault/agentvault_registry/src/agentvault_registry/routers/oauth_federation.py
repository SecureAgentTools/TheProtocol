"""
OAuth Federation Router for Cross-Registry Authentication
Implements RFC 8693 Token Exchange, RFC 7662 Token Introspection, RFC 7009 Revocation.

§RA1/RA2/RA3 (2026-07-24) — this surface was previously reachable but not real:

* **RA1** the subject token (the entire claim of "which agent, on which registry")
  was decoded with ``verify_signature=False``, so any holder of the client
  credentials could assert any DID on any peer. Now verified against the peer's
  published JWKS (``services/oauth_peer_verify``), with ``iss``/``exp`` enforced
  and ``alg`` restricted — no unverified fall-through.
* **RA2** ``/oauth/.well-known/jwks.json`` minted a fresh random RSA keypair per
  request while tokens were signed HS256 with the registry master secret. Now a
  durable per-registry RS256 keypair (``services/oauth_keystore``) signs exchange
  tokens and the JWKS publishes its stable public half — which is exactly what
  the TEG's multi-issuer verifier has been trying to fetch.
* **RA3** ``single_use``/``max_amount`` were minted into the token and enforced by
  nobody, and there was no revocation. The ``oauth_token_exchanges`` row is now
  authoritative: introspection reports used/revoked/expired, ``consume=true``
  burns a single-use token atomically, and ``POST /oauth/revoke`` kills one.

Trust configuration is read from the ``registry_trust_config`` table first (admin
CRUD below, client secrets encrypted at rest) and falls back to the
``TRUSTED_REGISTRIES`` env for bootstrap. With neither, the whole issuing surface
is fenced closed (501) — see ``_require_oauth_federation_enabled``.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import jwt  # PyJWT
from fastapi import APIRouter, Body, Depends, Form, HTTPException, Security, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.config import settings
from agentvault_registry.database import get_db
from agentvault_registry.models import OAuthTokenExchange
from agentvault_registry.security import get_current_developer, admin_credential
from agentvault_registry.services import oauth_keystore
from agentvault_registry.services.oauth_peer_verify import (
    PeerTokenError,
    clear_cache as clear_peer_jwks_cache,
    verify_peer_token,
)
from agentvault_registry.services.registry_card_keystore import _decrypt_pem, _encrypt_pem

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/oauth",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "OAuth Federation"
)

_DID_PREFIXES = ("did:agentvault:", "did:theprotocol:", "did:cos:")
_DEFAULT_MAX_AMOUNT = Decimal("1000.0")

# --- Pydantic Models ---

class TokenExchangeRequest(BaseModel):
    """RFC 8693 Token Exchange Request"""
    grant_type: str = Field(default="urn:ietf:params:oauth:grant-type:token-exchange")
    subject_token: str = Field(..., description="The token being exchanged")
    subject_token_type: str = Field(
        default="urn:ietf:params:oauth:token-type:access_token",
        description="Type of the subject token"
    )
    requested_token_type: Optional[str] = Field(
        default="urn:ietf:params:oauth:token-type:access_token",
        description="Type of token requested"
    )
    audience: Optional[str] = Field(None, description="Target audience for the new token")
    scope: Optional[str] = Field(None, description="Requested scope for new token")
    actor_token: Optional[str] = Field(None, description="Token representing the acting party")
    actor_token_type: Optional[str] = Field(None, description="Type of the actor token")
    client_id: Optional[str] = Field(None, description="Client ID for registry authentication")
    client_secret: Optional[str] = Field(None, description="Client secret for registry authentication")

class TokenExchangeResponse(BaseModel):
    """RFC 8693 Token Exchange Response"""
    access_token: str
    issued_token_type: str = "urn:ietf:params:oauth:token-type:access_token"
    token_type: str = "Bearer"
    expires_in: int
    scope: Optional[str] = None
    refresh_token: Optional[str] = None

class TokenIntrospectionRequest(BaseModel):
    """RFC 7662 Token Introspection Request"""
    token: str = Field(..., description="The token to introspect")
    token_type_hint: Optional[str] = Field(None, description="Hint about token type")

class TokenIntrospectionResponse(BaseModel):
    """RFC 7662 Token Introspection Response.

    RFC 7662 §2.2 allows extra members; `constraints`/`used`/`revoked` are ours,
    so a consumer can see WHY a token is inactive and what limits it carries.
    """
    active: bool
    scope: Optional[str] = None
    client_id: Optional[str] = None
    username: Optional[str] = None
    token_type: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    nbf: Optional[int] = None
    sub: Optional[str] = None
    aud: Optional[str] = None
    iss: Optional[str] = None
    jti: Optional[str] = None
    constraints: Optional[Dict[str, Any]] = None
    used: Optional[bool] = None
    revoked: Optional[bool] = None
    inactive_reason: Optional[str] = None

class RegistryTrustConfig(BaseModel):
    """Configuration for a trusted registry peer (admin create body)."""
    registry_name: str
    registry_url: str
    teg_url: Optional[str] = None
    client_id: str
    allowed_operations: List[str]
    public_key_url: str = Field(..., description="The peer's JWKS URI — RA1 verification fetches it")
    client_secret: Optional[str] = Field(
        None,
        description="Shared client secret. Stored AES-GCM encrypted. Without one the "
                    "entry can never authenticate (by design).",
    )
    issuer: Optional[str] = Field(None, description="Exact `iss` the peer's tokens carry. Defaults to registry_url.")
    max_amount: Optional[Decimal] = Field(None, description="Per-peer ceiling minted into token constraints.")


@dataclass
class TrustEntry:
    """A resolved trust relationship, whatever its source."""
    registry_name: str
    registry_url: str
    issuer: str
    jwks_uri: str
    client_id: str
    client_secret: str
    allowed_operations: List[str]
    max_amount: Decimal
    source: str  # "db" | "env"


# --- Helper Functions ---

def _issuer() -> str:
    """This registry's OAuth issuer identity.

    Explicit OAUTH_ISSUER wins; otherwise derive from BASE_URL so every frame has
    a correct, distinct issuer without per-node config. (The old baked default
    made every frame claim `iss: http://registry-a:8000`, which no peer could
    match.)
    """
    configured = (getattr(settings, "OAUTH_ISSUER", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    return str(settings.BASE_URL).rstrip("/")


def _coerce_amount(raw: Any) -> Decimal:
    if raw is None or raw == "":
        return _DEFAULT_MAX_AMOUNT
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return _DEFAULT_MAX_AMOUNT


def _entry_from_env(cfg: Dict[str, Any]) -> Optional[TrustEntry]:
    client_id = (cfg.get("client_id") or "").strip()
    registry_url = (cfg.get("registry_url") or "").strip().rstrip("/")
    if not client_id or not registry_url:
        return None
    jwks_uri = (cfg.get("public_key_url") or cfg.get("jwks_uri") or "").strip()
    if not jwks_uri:
        jwks_uri = f"{registry_url}/api/v1/oauth/.well-known/jwks.json"
    return TrustEntry(
        registry_name=cfg.get("registry_name") or cfg.get("name") or registry_url,
        registry_url=registry_url,
        issuer=(cfg.get("issuer") or registry_url).rstrip("/"),
        jwks_uri=jwks_uri,
        client_id=client_id,
        client_secret=(cfg.get("client_secret") or "").strip(),
        allowed_operations=list(cfg.get("allowed_operations") or []),
        max_amount=_coerce_amount(cfg.get("max_amount")),
        source="env",
    )


async def load_trust_entries(db: AsyncSession) -> List[TrustEntry]:
    """Resolve every trust relationship: DB rows are authoritative, env is bootstrap."""
    entries: Dict[str, TrustEntry] = {}

    rows = (await db.execute(
        select(models.RegistryTrustConfig).where(models.RegistryTrustConfig.is_active.is_(True))
    )).scalars().all()
    for row in rows:
        if not row.client_id:
            continue
        secret = ""
        if row.encrypted_client_secret:
            try:
                secret = _decrypt_pem(row.encrypted_client_secret)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[OAuth] trust row %s has an undecryptable client secret: %s",
                    row.registry_name, exc,
                )
                continue
        registry_url = (row.registry_url or "").rstrip("/")
        entries[row.client_id] = TrustEntry(
            registry_name=row.registry_name,
            registry_url=registry_url,
            issuer=(row.issuer or registry_url).rstrip("/"),
            jwks_uri=row.public_key,
            client_id=row.client_id,
            client_secret=secret,
            allowed_operations=list(row.allowed_operations or []),
            max_amount=_coerce_amount(row.max_amount),
            source="db",
        )

    for cfg in (settings.trusted_registries or []):
        if not isinstance(cfg, dict):
            continue
        entry = _entry_from_env(cfg)
        if entry and entry.client_id not in entries:
            entries[entry.client_id] = entry

    return list(entries.values())


async def _require_oauth_federation_enabled(db: AsyncSession) -> List[TrustEntry]:
    """AL-5 fence, kept: with no trust relationship the issuing surface is 501.

    Fail CLOSED rather than answer with a half-configured federation. Returns the
    entries so callers do not load them twice.
    """
    entries = await load_trust_entries(db)
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Cross-registry OAuth federation is not enabled on this registry "
                "(no active trusted registries configured)."
            ),
        )
    return entries


def _authenticate_client(entries: List[TrustEntry], client_id: Optional[str], client_secret: Optional[str]) -> TrustEntry:
    """Constant-time client authentication.

    An entry with an empty stored secret authenticates NOBODY: the old code
    compared against `cfg.get('client_secret', '')`, so a trust row without a
    secret would accept an empty secret from anyone.
    """
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="client_id and client_secret are required",
        )
    for entry in entries:
        if entry.client_id != client_id:
            continue
        if not entry.client_secret:
            logger.error(
                "[OAuth] trust entry %s (%s) has no client secret — refusing to authenticate it",
                entry.registry_name, entry.source,
            )
            break
        if secrets.compare_digest(client_secret, entry.client_secret):
            return entry
        break
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid client credentials",
    )


async def _enforce_exchange_rate_limit(db: AsyncSession, entry: TrustEntry) -> None:
    """OAUTH_MAX_TOKEN_EXCHANGES_PER_HOUR — the setting existed but nothing read it."""
    limit = int(getattr(settings, "OAUTH_MAX_TOKEN_EXCHANGES_PER_HOUR", 0) or 0)
    if limit <= 0:
        return
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    used = (await db.execute(
        select(func.count(OAuthTokenExchange.id)).where(
            OAuthTokenExchange.client_id == entry.client_id,
            OAuthTokenExchange.created_at >= since,
        )
    )).scalar() or 0
    if used >= limit:
        logger.warning("[OAuth] exchange rate limit hit client_id=%s used=%s", entry.client_id, used)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Token exchange rate limit reached ({limit}/hour)",
        )


# --- Endpoints ---

@router.post(
    "/token/exchange",
    response_model=TokenExchangeResponse,
    summary="Exchange token from another registry",
    responses={
        200: {"description": "Token successfully exchanged"},
        401: {"description": "Invalid or expired token"},
        403: {"description": "Token exchange not allowed"},
        429: {"description": "Exchange rate limit reached"},
        501: {"description": "Federation not configured on this registry"},
    }
)
async def exchange_token(
    request: TokenExchangeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    RFC 8693 Token Exchange.

    Exchanges a **verified** token from a trusted peer registry for a
    limited-scope, single-use local token signed with this registry's federation
    key. Client credentials go in the JSON body (client_id + client_secret).
    """
    entries = await _require_oauth_federation_enabled(db)
    entry = _authenticate_client(entries, request.client_id, request.client_secret)

    if request.grant_type != "urn:ietf:params:oauth:grant-type:token-exchange":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported grant type")

    if "token_exchange" not in entry.allowed_operations:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token exchange is not an allowed operation for this registry",
        )

    await _enforce_exchange_rate_limit(db, entry)

    # RA1: the subject token is verified against the peer's JWKS. No fall-through.
    try:
        token_data = await verify_peer_token(
            request.subject_token,
            jwks_uri=entry.jwks_uri,
            expected_issuer=entry.issuer,
        )
    except PeerTokenError as exc:
        logger.warning("[OAuth] subject token rejected from %s: %s", entry.registry_name, exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid subject token: {exc}")

    agent_did = token_data.get("sub")
    if not agent_did or not any(agent_did.startswith(p) for p in _DID_PREFIXES):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent DID in token")

    requested_scope = request.scope or "teg:transfer:execute"
    if not any(op in requested_scope for op in entry.allowed_operations):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requested scope not allowed for this registry",
        )

    lifetime = int(getattr(settings, "OAUTH_TOKEN_EXCHANGE_LIFETIME", 300) or 300)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=lifetime)
    issuer = _issuer()
    audience = request.audience or getattr(settings, "OAUTH_DEFAULT_AUDIENCE", "") or settings.TEG_API_BASE_URL

    constraints = {
        "source_registry": entry.registry_url,
        "single_use": True,
        "max_amount": str(entry.max_amount),
        "valid_operations": ["transfer", "balance_inquiry"],
        "source_token_jti": str(token_data.get("jti") or ""),
    }

    # Mint the key first: it commits, and we do not want that commit landing in
    # the middle of the exchange row's transaction.
    key_row = await oauth_keystore.get_or_mint_key(db, issuer)

    jti = f"exchange_{secrets.token_urlsafe(16)}"
    exchange_row = OAuthTokenExchange(
        source_token_jti=str(token_data.get("jti") or "unknown"),
        issued_token_jti=jti,
        source_registry=entry.registry_url,
        agent_did=agent_did,
        scope=requested_scope,
        expires_at=expires_at,
        client_id=entry.client_id,
        constraints=constraints,
    )
    db.add(exchange_row)
    # RA3: the audit row is a precondition, not best-effort bookkeeping. If it
    # cannot be written the token is never minted — an unauditable token is
    # exactly the thing that cannot be revoked later.
    await db.flush()

    access_token = oauth_keystore.sign(
        {
            "iss": issuer,
            "sub": agent_did,
            "aud": audience,
            "exp": int(expires_at.timestamp()),
            "iat": int(now.timestamp()),
            "jti": jti,
            "scope": requested_scope,
            "grant_type": "token_exchange",
            "constraints": constraints,
        },
        key_row,
    )
    await db.commit()

    logger.info(
        "[OAuth] exchanged token agent=%s peer=%s scope=%s jti=%s kid=%s",
        agent_did, entry.registry_name, requested_scope, jti, (key_row.public_jwk or {}).get("kid"),
    )

    return TokenExchangeResponse(
        access_token=access_token,
        expires_in=lifetime,
        scope=requested_scope,
    )


@router.post(
    "/introspect",
    response_model=TokenIntrospectionResponse,
    summary="Introspect a token",
    responses={
        200: {"description": "Token introspection result"},
        401: {"description": "Invalid client credentials"},
        501: {"description": "Federation not configured on this registry"},
    }
)
async def introspect_token(
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(None),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    consume: bool = Form(False, description="Burn a single-use token (RA3). Plain introspection does not consume."),
    amount: Optional[str] = Form(None, description="Amount this call intends to move; checked against the token's max_amount."),
    db: AsyncSession = Depends(get_db)
):
    """
    RFC 7662 Token Introspection, answered from the exchange ledger.

    A token is inactive if its signature fails, or if the matching
    ``oauth_token_exchanges`` row says revoked / expired / already used. Pass
    ``consume=true`` to atomically burn a single-use token: that is the
    enforcement point for the ``single_use`` constraint.
    """
    entries = await _require_oauth_federation_enabled(db)
    _authenticate_client(entries, client_id, client_secret)

    issuer = _issuer()
    jwks = await oauth_keystore.public_jwks(db, issuer)
    try:
        payload = oauth_keystore.verify_self_signed(token, jwks, issuer=issuer)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[OAuth] introspection: signature/claims invalid: %s", exc)
        return TokenIntrospectionResponse(active=False, inactive_reason="invalid_signature_or_claims")

    jti = payload.get("jti")
    row = None
    if jti:
        row = (await db.execute(
            select(OAuthTokenExchange).where(OAuthTokenExchange.issued_token_jti == jti)
        )).scalar_one_or_none()

    if row is None:
        # Signature verified but we have no record: treat as inactive rather than
        # vouching for a token this registry cannot account for.
        return TokenIntrospectionResponse(active=False, jti=jti, inactive_reason="unknown_token")

    constraints = row.constraints or {}
    single_use = bool(constraints.get("single_use", True))
    now = datetime.now(timezone.utc)

    def _inactive(reason: str) -> TokenIntrospectionResponse:
        return TokenIntrospectionResponse(
            active=False,
            jti=jti,
            sub=row.agent_did,
            scope=row.scope,
            constraints=constraints,
            used=row.used_at is not None,
            revoked=row.revoked_at is not None,
            inactive_reason=reason,
        )

    if row.revoked_at is not None:
        return _inactive("revoked")
    expires_at = row.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at <= now:
        return _inactive("expired")
    if single_use and row.used_at is not None:
        return _inactive("already_used")

    if amount is not None and str(amount).strip() != "":
        try:
            requested = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            return _inactive("invalid_amount")
        ceiling = _coerce_amount(constraints.get("max_amount"))
        if requested > ceiling:
            logger.warning(
                "[OAuth] introspection denied: amount %s exceeds max_amount %s jti=%s",
                requested, ceiling, jti,
            )
            return _inactive("amount_exceeds_max")

    if consume:
        # Atomic burn: only the caller whose UPDATE matches used_at IS NULL wins.
        burned = (await db.execute(
            OAuthTokenExchange.__table__.update()
            .where(
                OAuthTokenExchange.id == row.id,
                OAuthTokenExchange.used_at.is_(None),
                OAuthTokenExchange.revoked_at.is_(None),
            )
            .values(used_at=now)
        )).rowcount
        await db.commit()
        if not burned:
            return _inactive("already_used")
        logger.info("[OAuth] single-use token consumed jti=%s agent=%s", jti, row.agent_did)

    return TokenIntrospectionResponse(
        active=True,
        scope=row.scope,
        client_id=row.client_id,
        token_type="Bearer",
        exp=payload.get("exp"),
        iat=payload.get("iat"),
        nbf=payload.get("nbf"),
        sub=row.agent_did,
        aud=payload.get("aud"),
        iss=payload.get("iss"),
        jti=jti,
        constraints=constraints,
        used=consume or row.used_at is not None,
        revoked=False,
    )


@router.post(
    "/revoke",
    summary="Revoke an exchanged token",
    responses={
        200: {"description": "Revocation processed (RFC 7009 always returns 200)"},
        401: {"description": "Invalid client credentials"},
        501: {"description": "Federation not configured on this registry"},
    }
)
async def revoke_token(
    token: Optional[str] = Form(None),
    jti: Optional[str] = Form(None),
    token_type_hint: Optional[str] = Form(None),
    reason: Optional[str] = Form(None),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """
    RFC 7009 revocation of an exchanged federation access token. Accepts the token itself or its `jti`. As RFC 7009
    section 2.2 requires, an unknown token still answers 200, so revocation cannot be used to learn whether a token
    exists.

    \f
    RFC 7009 revocation for exchanged tokens (RA3).

    Accepts the token itself or its `jti`. Per RFC 7009 §2.2 an unknown token is
    still a 200 — revocation must not become an oracle for token existence.
    """
    entries = await _require_oauth_federation_enabled(db)
    entry = _authenticate_client(entries, client_id, client_secret)

    target_jti = (jti or "").strip()
    if not target_jti and token:
        try:
            # Unverified read is safe here: we only use the jti to look up a row we
            # own, and revoking a garbage jti is a no-op.
            target_jti = str(jwt.decode(token, options={"verify_signature": False}).get("jti") or "")
        except Exception:  # noqa: BLE001
            target_jti = ""

    if not target_jti:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"revoked": False, "detail": "no token identifier"})

    row = (await db.execute(
        select(OAuthTokenExchange).where(OAuthTokenExchange.issued_token_jti == target_jti)
    )).scalar_one_or_none()

    if row is None:
        logger.info("[OAuth] revoke: unknown jti=%s from %s", target_jti, entry.registry_name)
        return JSONResponse(status_code=status.HTTP_200_OK, content={"revoked": False})

    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_reason = (reason or f"revoked by {entry.registry_name}")[:255]
        await db.commit()
        logger.info("[OAuth] revoked jti=%s agent=%s by=%s", target_jti, row.agent_did, entry.registry_name)

    return JSONResponse(status_code=status.HTTP_200_OK, content={"revoked": True})


@router.get(
    "/.well-known/jwks.json",
    summary="JSON Web Key Set",
    responses={200: {"description": "JWKS for token verification"}}
)
async def get_jwks(db: AsyncSession = Depends(get_db)):
    """
    This registry's federation JWKS: the public half of the RS256 key that signs exchanged access tokens, plus any
    rotated key still inside its grace window. Public by design; the TEG's multi-issuer verifier fetches it to
    validate those access tokens.

    \f
    This registry's federation JWKS — the stable public half of the RS256 key that
    signs exchange tokens, plus any rotated key still inside its grace window.

    Deliberately NOT fenced: public key material is meant to be fetchable, and the
    TEG's multi-issuer verifier fetches it to validate tokens. (It used to return
    a freshly generated random key on every call, which is why nothing could ever
    verify anything.)
    """
    return JSONResponse(content=await oauth_keystore.public_jwks(db, _issuer()))


@router.get(
    "/federation/status",
    summary="Federation Status",
    responses={200: {"description": "Current federation configuration and status"}}
)
async def get_federation_status(
    current_user = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """Current OAuth federation configuration, for debugging and monitoring."""
    entries = await load_trust_entries(db)
    issuer = _issuer()
    key_row = await oauth_keystore.get_or_mint_key(db, issuer)

    return JSONResponse(content={
        "oauth_enabled": bool(entries),
        "issuer": issuer,
        "token_exchange_enabled": bool(getattr(settings, "OAUTH_TOKEN_EXCHANGE_ENABLED", True)) and bool(entries),
        "signing": {
            "algorithm": oauth_keystore.ALGORITHM,
            "kid": (key_row.public_jwk or {}).get("kid"),
            "rotation_seq": key_row.rotation_seq,
        },
        "trusted_registries": [
            {
                "name": e.registry_name,
                "url": e.registry_url,
                "issuer": e.issuer,
                "jwks_uri": e.jwks_uri,
                "allowed_operations": e.allowed_operations,
                "max_amount": str(e.max_amount),
                "source": e.source,
                "has_client_secret": bool(e.client_secret),
            }
            for e in entries
        ],
        "supported_grant_types": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "introspection_endpoint": f"{issuer}{settings.API_V1_STR}/oauth/introspect",
        "revocation_endpoint": f"{issuer}{settings.API_V1_STR}/oauth/revoke",
        "jwks_endpoint": f"{issuer}{settings.API_V1_STR}/oauth/.well-known/jwks.json",
    })


# --- Registry Trust Management (Admin only) ---

@router.get(
    "/federation/trust",
    summary="List Trusted Registries",
    responses={
        200: {"description": "Trust relationships (secrets never returned)"},
        403: {"description": "Admin access required"},
    }
)
async def list_trusted_registries(
    current_user = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    List the trust relationships with peer registries (administrators only). Secrets are reported as a boolean only.

    \f
    List trust relationships. Admin only. Secrets are reported as a boolean only.

    (The contract suite has expected this route since §pass47; it never existed,
    so the listing was a 405. It does now.)
    """
    if not admin_credential(current_user):   # §POCKETPAIR: a scoped key is not admin
        raise HTTPException(status_code=403, detail="Admin access required")

    rows = (await db.execute(
        select(models.RegistryTrustConfig).order_by(models.RegistryTrustConfig.created_at.desc())
    )).scalars().all()

    return JSONResponse(content={
        "trusted_registries": [
            {
                "id": str(row.id),
                "registry_name": row.registry_name,
                "registry_url": row.registry_url,
                "issuer": row.issuer,
                "jwks_uri": row.public_key,
                "client_id": row.client_id,
                "has_client_secret": bool(row.encrypted_client_secret),
                "allowed_operations": list(row.allowed_operations or []),
                "max_amount": str(row.max_amount) if row.max_amount is not None else None,
                "is_active": bool(row.is_active),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "count": len(rows),
    })


@router.post(
    "/federation/trust",
    summary="Add Trusted Registry",
    responses={
        201: {"description": "Trust relationship created"},
        401: {"description": "Unauthorized"},
        409: {"description": "Registry already trusted"}
    }
)
async def add_trusted_registry(
    config: RegistryTrustConfig,
    current_user = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """Add a trusted registry for OAuth federation. Admin only.

    The client secret is encrypted at rest with the same AES-GCM helper the
    signing keystores use. An entry created without one is inert by design.
    """
    if not admin_credential(current_user):   # §POCKETPAIR: a scoped key is not admin
        raise HTTPException(status_code=403, detail="Admin access required")

    existing = await db.execute(
        select(models.RegistryTrustConfig).where(
            models.RegistryTrustConfig.registry_url == config.registry_url
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Registry {config.registry_url} already trusted")

    if not config.client_secret:
        logger.warning(
            "[OAuth] trust entry %s created without a client secret — it cannot authenticate",
            config.registry_name,
        )

    trust = models.RegistryTrustConfig(
        registry_name=config.registry_name,
        registry_url=config.registry_url,
        public_key=config.public_key_url,
        client_id=config.client_id,
        encrypted_client_secret=_encrypt_pem(config.client_secret) if config.client_secret else None,
        allowed_operations=config.allowed_operations,
        issuer=(config.issuer or config.registry_url).rstrip("/"),
        max_amount=config.max_amount,
        is_active=True,
        created_by_developer_id=current_user.id,
    )
    db.add(trust)
    await db.commit()
    clear_peer_jwks_cache()

    logger.info(f"Added trusted registry: {config.registry_name} at {config.registry_url}")

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "message": "Trust relationship created",
            "registry": config.registry_name,
            "registry_url": config.registry_url,
            "has_client_secret": bool(config.client_secret),
        }
    )

@router.delete(
    "/federation/trust/{registry_url:path}",
    summary="Remove Trusted Registry",
    responses={
        204: {"description": "Trust relationship removed"},
        401: {"description": "Unauthorized"},
        404: {"description": "Registry not found"}
    }
)
async def remove_trusted_registry(
    registry_url: str,
    current_user = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """Remove a trusted registry from OAuth federation. Admin only."""
    if not admin_credential(current_user):   # §POCKETPAIR: a scoped key is not admin
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(
        select(models.RegistryTrustConfig).where(models.RegistryTrustConfig.registry_url == registry_url)
    )
    trust = result.scalar_one_or_none()
    if not trust:
        raise HTTPException(status_code=404, detail=f"Registry {registry_url} not found in trust config")

    await db.delete(trust)
    await db.commit()
    clear_peer_jwks_cache()

    logger.info(f"Removed trusted registry: {registry_url}")

    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
