"""Authentication endpoints for TEG Core Service

POST /auth/token exchanges the registry's JWT for a TEG access token. The registry_jwt is always verified:
1. its HS256 signature with the registry's key (REGISTRY_JWT_SECRET; refused with 503 when no key is set)
2. its expiry
3. its purpose, which must be teg_token_exchange
4. the agent it names, which must be exactly the request's agent_id
"""
import logging

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.jwt_auth import jwt_service
from ...core.secure_config import get_settings
from ...database.db_session import get_db
from ...database.crud import AgentCRUD

logger = logging.getLogger(__name__)

router = APIRouter()

settings = get_settings()


class TokenRequest(BaseModel):
    """Request model for token generation"""
    agent_id: str
    registry_jwt: str  # JWT from Registry for validation


class TokenResponse(BaseModel):
    """Response model for token generation"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes


def _validate_registry_jwt(registry_jwt: str, claimed_agent_id: str) -> str:
    """Verify the registry's exchange JWT and return the agent it names.

    The registry signs this JWT with its API_KEY_SECRET (HS256); the TEG holds the same value as
    REGISTRY_JWT_SECRET (also read under TEG_REGISTRY_JWT_SECRET and REGISTRY_SERVICE_TOKEN, the names the
    kit composes pass). Without that secret the TEG cannot tell the registry from any other caller, so the
    exchange is refused (503) instead of issuing a token unchecked: the check was skipped when the setting
    was absent, which left every frame and operator TEG issuing tokens for any agent to anyone who reached
    the route (CB-049, closed by configuration on 2026-10-16).

    Raises:
        HTTPException 503: no registry secret is configured on this TEG
        HTTPException 401: the JWT is invalid, expired, not an exchange JWT, or names another agent
    """
    secret = settings.registry_jwt_secret
    if secret is None or not secret.get_secret_value().strip():
        logger.error(
            "REGISTRY_JWT_SECRET is not configured: refusing the token exchange. Set it to the "
            "registry's API_KEY_SECRET."
        )
        raise HTTPException(
            status_code=503,
            detail="Token exchange is not configured on this TEG (REGISTRY_JWT_SECRET is not set)",
        )

    try:
        payload = pyjwt.decode(
            registry_jwt,
            secret.get_secret_value(),
            algorithms=["HS256"],
            options={"verify_exp": True, "verify_iat": False, "require": ["exp"]},
        )
    except pyjwt.ExpiredSignatureError:
        logger.warning(f"Registry JWT expired for claimed agent: {claimed_agent_id}")
        raise HTTPException(status_code=401, detail="Registry JWT has expired")
    except pyjwt.InvalidSignatureError:
        logger.error(f"Registry JWT signature invalid for claimed agent: {claimed_agent_id}")
        raise HTTPException(status_code=401, detail="Registry JWT signature is invalid")
    except pyjwt.InvalidTokenError as e:
        logger.error(f"Registry JWT validation failed: {e}")
        raise HTTPException(status_code=401, detail=f"Registry JWT is invalid: {str(e)}")

    # Only a JWT the registry minted for this exchange counts: a session or agent JWT signed with the
    # same key is not an exchange JWT, with or without a purpose claim.
    if payload.get("purpose") != "teg_token_exchange":
        logger.warning(f"Registry JWT has purpose {payload.get('purpose')!r}, not teg_token_exchange")
        raise HTTPException(status_code=401, detail="Registry JWT is not a token exchange token")

    # The registry names the agent in agent_id (did is an older alias); it must be exactly the agent the
    # request asks for. No substring or prefix matching: "did:x:1" must never stand for "did:x:12".
    jwt_agent_id = payload.get("agent_id") or payload.get("did")
    if not jwt_agent_id:
        logger.error("Registry JWT missing agent identity claim (agent_id/did)")
        raise HTTPException(status_code=401, detail="Registry JWT missing agent identity claim")
    if str(jwt_agent_id) != claimed_agent_id:
        logger.error(f"Agent ID mismatch: request claims '{claimed_agent_id}', JWT contains '{jwt_agent_id}'")
        raise HTTPException(status_code=401, detail="Agent ID in request does not match registry JWT")

    logger.info(f"Registry JWT validated successfully for agent: {jwt_agent_id}")
    return str(jwt_agent_id)


@router.post("/token", response_model=TokenResponse)
async def create_agent_token(
    request: TokenRequest,
    db: Session = Depends(get_db)
):
    """
    Create a TEG access token for an agent.
    
    This endpoint is called by the Registry to exchange its JWT
    for a TEG-specific access token.
    
    The registry_jwt is always verified first (signature, expiry, purpose, the
    exact agent); without a configured registry secret the exchange is refused.
    """
    agent_id = _validate_registry_jwt(request.registry_jwt, request.agent_id)

    # Ensure agent exists in TEG database
    AgentCRUD.get_or_create(db, agent_id)

    # Generate TEG access token
    access_token = jwt_service.create_access_token(agent_id=agent_id)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=jwt_service.access_token_expire_minutes * 60
    )
