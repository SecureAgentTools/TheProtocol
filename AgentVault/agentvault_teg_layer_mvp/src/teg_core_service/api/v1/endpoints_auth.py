"""Authentication endpoints for TEG Core Service

P0-002: Added registry_jwt signature validation.
When REGISTRY_JWT_SECRET is configured, the /auth/token endpoint will:
1. Decode and verify the registry_jwt signature
2. Check that the JWT is not expired
3. Verify the agent_id in the JWT matches the request agent_id
"""
import logging
from typing import Optional

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


def _validate_registry_jwt(registry_jwt: str, claimed_agent_id: str) -> Optional[str]:
    """Validate the registry JWT and extract the agent identity.
    
    P0-002: This function verifies the registry_jwt signature using the
    shared secret (REGISTRY_JWT_SECRET). If the secret is not configured,
    validation is skipped with a warning (MVP backward compatibility).
    
    Args:
        registry_jwt: The JWT string from the Registry
        claimed_agent_id: The agent_id claimed in the request body
        
    Returns:
        The validated agent_id from the JWT, or None if validation is skipped
        
    Raises:
        HTTPException 401: If JWT is invalid, expired, or agent_id mismatch
    """
    # Check if registry JWT validation is configured
    if settings.registry_jwt_secret is None:
        logger.warning(
            "⚠️ REGISTRY_JWT_SECRET not configured — skipping registry_jwt validation. "
            "This is acceptable for MVP but MUST be configured in production."
        )
        return None
    
    secret_key = settings.registry_jwt_secret.get_secret_value()
    
    try:
        # Decode and verify the JWT signature
        # The registry uses HS256 with API_KEY_SECRET
        payload = pyjwt.decode(
            registry_jwt,
            secret_key,
            algorithms=["HS256"],
            options={
                "verify_exp": True,
                "verify_iat": False,  # iat is not always present
                "require": ["exp"],
            }
        )
        
        # Verify this is a token exchange JWT (not a regular user session token)
        purpose = payload.get("purpose")
        if purpose and purpose != "teg_token_exchange":
            logger.warning(f"Registry JWT has unexpected purpose: {purpose}")
            raise HTTPException(
                status_code=401,
                detail="Registry JWT is not a token exchange token"
            )
        
        # Extract the agent identity from the JWT
        # The registry encodes: sub="registry", agent_id=<agent DID>
        jwt_agent_id = payload.get("agent_id") or payload.get("did")
        
        # Fall back to 'sub' only if it's not the generic "registry" value
        if not jwt_agent_id:
            sub = payload.get("sub")
            if sub and sub != "registry":
                jwt_agent_id = sub
        
        if not jwt_agent_id:
            logger.error("Registry JWT missing agent identity claim (agent_id/did/sub)")
            raise HTTPException(
                status_code=401,
                detail="Registry JWT missing agent identity claim"
            )
        
        # Verify the agent_id in the JWT matches the request
        if jwt_agent_id != claimed_agent_id:
            # Flexible matching: the registry may use DID format while request uses short ID
            # e.g., claimed="did:agentvault:agent:42" vs jwt="did:agentvault:agent:42"
            # or claimed="42" vs jwt_agent_id="did:agentvault:agent:42"
            if not (
                claimed_agent_id in str(jwt_agent_id) or 
                str(jwt_agent_id) in claimed_agent_id
            ):
                logger.error(
                    f"Agent ID mismatch: request claims '{claimed_agent_id}', "
                    f"JWT contains '{jwt_agent_id}'"
                )
                raise HTTPException(
                    status_code=401,
                    detail="Agent ID in request does not match registry JWT"
                )
        
        logger.info(f"Registry JWT validated successfully for agent: {jwt_agent_id}")
        return jwt_agent_id
        
    except pyjwt.ExpiredSignatureError:
        logger.warning(f"Registry JWT expired for claimed agent: {claimed_agent_id}")
        raise HTTPException(
            status_code=401,
            detail="Registry JWT has expired"
        )
    except pyjwt.InvalidSignatureError:
        logger.error(f"Registry JWT signature invalid for claimed agent: {claimed_agent_id}")
        raise HTTPException(
            status_code=401,
            detail="Registry JWT signature is invalid"
        )
    except pyjwt.InvalidTokenError as e:
        logger.error(f"Registry JWT validation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail=f"Registry JWT is invalid: {str(e)}"
        )


@router.post("/token", response_model=TokenResponse)
async def create_agent_token(
    request: TokenRequest,
    db: Session = Depends(get_db)
):
    """
    Create a TEG access token for an agent.
    
    This endpoint is called by the Registry to exchange its JWT
    for a TEG-specific access token.
    
    P0-002: When REGISTRY_JWT_SECRET is configured, the registry_jwt
    signature is validated before issuing a TEG token.
    """
    # P0-002: Validate the registry JWT if secret is configured
    _validate_registry_jwt(request.registry_jwt, request.agent_id)
    
    # Ensure agent exists in TEG database
    agent = AgentCRUD.get_or_create(db, request.agent_id)
    
    # Generate TEG access token
    access_token = jwt_service.create_access_token(agent_id=request.agent_id)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=jwt_service.access_token_expire_minutes * 60
    )
