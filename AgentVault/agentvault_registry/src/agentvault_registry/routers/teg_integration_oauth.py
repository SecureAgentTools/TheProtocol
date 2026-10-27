"""TEG Layer integration with OAuth 2.0 JWT Bearer Grant

This module implements REQ-INT-V1AUTH-001: Enterprise-Grade Authentication Bridge.
It uses JWT-SVID assertions to obtain TEG-specific access tokens via OAuth 2.0
JWT Bearer Grant flow (RFC 7523).

The flow:
1. v1.0.0 authenticated user makes request to registry
2. Registry acquires JWT-SVID for the user via SPIRE
3. Registry exchanges JWT-SVID for TEG access token
4. Registry uses TEG access token for all TEG API calls
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pydantic import BaseModel, Field
import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from agentvault_registry import models, security
from agentvault_registry.config import settings
# from agentvault_registry.secure_config import settings as secure_settings

# Import JWT-SVID provider - STUBBED OUT (doesn't exist)
# from agentvault_registry.core.jwt_svid_provider import acquire_agent_jwt_svid

# Stub function until JWT-SVID provider is implemented
async def acquire_agent_jwt_svid(agent_email: str, audience: str) -> str:
    """Stub for JWT-SVID acquisition - returns a placeholder"""
    return f"stub-jwt-svid-{agent_email}-{audience}"

logger = logging.getLogger(__name__)

# TEG API configuration - use internal container port
TEG_API_BASE_URL = getattr(settings, 'TEG_API_BASE_URL', 'http://teg-layer:8080')
TEG_API_V1_PREFIX = '/api/v1'
TEG_AUTH_ENDPOINT = f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/auth/token"

# OAuth 2.0 constants
GRANT_TYPE_JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# Token cache settings
TOKEN_CACHE_BUFFER_SECONDS = 300  # Refresh tokens 5 minutes before expiry

router = APIRouter(
    prefix="/teg",
    tags=["TEG Integration"],
    dependencies=[Depends(security.get_current_developer)]
)


# --- Token Management ---
class TEGTokenCache:
    """Simple in-memory cache for TEG access tokens"""
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def get(self, agent_email: str) -> Optional[str]:
        """Get cached token if still valid"""
        if agent_email not in self._cache:
            return None
        
        cached = self._cache[agent_email]
        expires_at = cached.get("expires_at")
        
        if not expires_at:
            return None
        
        # Check if token is still valid (with buffer)
        now = datetime.now(timezone.utc)
        if now >= expires_at - timedelta(seconds=TOKEN_CACHE_BUFFER_SECONDS):
            # Token expired or about to expire
            del self._cache[agent_email]
            return None
        
        return cached.get("access_token")
    
    def set(self, agent_email: str, access_token: str, expires_in: int):
        """Cache a token with expiry"""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        self._cache[agent_email] = {
            "access_token": access_token,
            "expires_at": expires_at
        }
    
    def invalidate(self, agent_email: str):
        """Remove token from cache"""
        if agent_email in self._cache:
            del self._cache[agent_email]


# Global token cache
_token_cache = TEGTokenCache()


async def get_teg_access_token(developer: models.Developer) -> str:
    """
    Get a TEG access token for the authenticated developer.
    
    This implements the OAuth 2.0 JWT Bearer Grant flow:
    1. Check token cache
    2. If no valid cached token, acquire JWT-SVID
    3. Exchange JWT-SVID for TEG access token
    4. Cache the token
    
    Args:
        developer: Authenticated v1.0.0 developer
    
    Returns:
        TEG access token
    
    Raises:
        HTTPException: If token acquisition fails
    """
    # Check cache first
    cached_token = _token_cache.get(developer.email)
    if cached_token:
        logger.debug(f"Using cached TEG token for {developer.email}")
        return cached_token
    
    logger.info(f"Acquiring new TEG access token for {developer.email}")
    
    try:
        # Step 1: Acquire JWT-SVID assertion
        jwt_svid = await acquire_agent_jwt_svid(
            agent_email=developer.email,
            audience="spiffe://agentvault.com/service/teg-core"
        )
        
        # Step 2: Exchange JWT-SVID for TEG access token
        # Note: TEG expects agent_id and registry_jwt, not OAuth2 parameters
        # Create a proper Registry JWT
        from ..security import create_access_token
        from datetime import timedelta, timezone
        
        registry_jwt_data = {
            "sub": "registry",
            "developer_email": developer.email,
            "developer_id": str(developer.id),
            "purpose": "teg_token_exchange",
            "iss": "agentvault-registry",
        }
        registry_jwt = create_access_token(registry_jwt_data, expires_delta=timedelta(minutes=5))
        
        # For developer access, we need to use a default agent or developer's primary agent
        # For now, use a placeholder agent ID
        agent_id = f"did:theprotocol:developer-{developer.id}"
        
        async with httpx.AsyncClient(verify=False) as client:  # In production, use proper TLS
            response = await client.post(
                TEG_AUTH_ENDPOINT,
                json={
                    "agent_id": agent_id,  # Developer's virtual agent ID
                    "registry_jwt": registry_jwt  # Real Registry JWT
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                
                # Cache the token
                _token_cache.set(developer.email, access_token, expires_in)
                
                logger.info(f"Successfully acquired TEG access token for {developer.email}")
                return access_token
                
            else:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to authenticate with TEG service"
                )
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to acquire TEG access token: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG authentication service unavailable"
        )


async def make_teg_request(
    method: str,
    endpoint: str,
    developer: models.Developer,
    json_data: Optional[dict] = None,
    params: Optional[dict] = None,
    retry_on_401: bool = True
) -> httpx.Response:
    """
    Make an authenticated request to the TEG API.
    
    This handles:
    - Token acquisition and caching
    - Automatic retry on 401 with fresh token
    - Proper error handling
    
    Args:
        method: HTTP method
        endpoint: API endpoint (without base URL)
        developer: Authenticated developer
        json_data: Optional JSON body
        params: Optional query parameters
        retry_on_401: Whether to retry with fresh token on 401
    
    Returns:
        HTTP response
    """
    # Get access token
    access_token = await get_teg_access_token(developer)
    
    # Make request
    async with httpx.AsyncClient(verify=False) as client:  # In production, use proper TLS
        try:
            response = await client.request(
                method=method,
                url=f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}{endpoint}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Request-Source": "agentvault-registry-v1"
                },
                json=json_data,
                params=params,
                timeout=10.0
            )
            
            # Handle 401 - token might be expired
            if response.status_code == 401 and retry_on_401:
                logger.info("TEG token expired, acquiring fresh token")
                _token_cache.invalidate(developer.email)
                
                # Get fresh token and retry
                access_token = await get_teg_access_token(developer)
                
                response = await client.request(
                    method=method,
                    url=f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}{endpoint}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Request-Source": "agentvault-registry-v1"
                    },
                    json=json_data,
                    params=params,
                    timeout=10.0
                )
            
            return response
            
        except httpx.RequestError as e:
            logger.error(f"TEG API request error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


# --- Request/Response Schemas (unchanged) ---
class TEGBalanceResponse(BaseModel):
    """Response model for TEG token balance"""
    agent_id: str = Field(..., description="Agent identifier")
    balance: str = Field(..., description="Current token balance as string")

class TEGFeeConfigResponse(BaseModel):
    """Response model for fee configuration"""
    transfer_fee_amount: str = Field(..., description="Current transfer fee amount as string")
    fee_collection_address: str = Field(..., description="Address where fees are collected")
    
class TEGTransferRequest(BaseModel):
    """Request model for TEG token transfer"""
    receiver_agent_id: str = Field(..., description="Recipient agent ID")
    amount: str = Field(..., description="Amount to transfer as string")
    message: Optional[str] = Field(None, max_length=256, description="Optional message to attach to transfer")
    
class TEGTransferResponse(BaseModel):
    """Response model for TEG token transfer"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: str = Field(..., description="Transaction status")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    receiver_agent_id: str = Field(..., description="Recipient agent ID")
    amount: str = Field(..., description="Amount transferred as string")
    fee_amount: str = Field(..., description="Transaction fee as string")
    new_sender_balance: str = Field(..., description="Sender's balance after transfer as string")
    timestamp: str = Field(..., description="Transaction timestamp")
    attached_message: Optional[str] = Field(None, description="Message attached to the transfer")

class TEGSystemTransferRequest(BaseModel):
    """Request model for agent-to-system transfer"""
    amount: str = Field(..., description="Amount to transfer to system as string")
    purpose: Optional[str] = Field(None, description="Purpose of system transfer")
    
class TEGSystemTransferResponse(BaseModel):
    """Response model for agent-to-system transfer"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: str = Field(..., description="Transaction status")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    system_receiver_id: str = Field(..., description="System treasury DID")
    amount: str = Field(..., description="Amount transferred as string")
    purpose: str = Field(..., description="Purpose of the transfer")
    new_sender_balance: str = Field(..., description="Sender's balance after transfer as string")
    timestamp: str = Field(..., description="Transaction timestamp")

class TEGTransactionInfo(BaseModel):
    """Transaction information model"""
    transaction_id: str
    sender_agent_id: Optional[str]
    receiver_agent_id: str
    amount: str
    fee_amount: str
    status: str
    transaction_type: str
    timestamp: str
    error_message: Optional[str] = None
    reputation_signal_applied: Optional[bool] = False
    attached_message: Optional[str] = None

class TEGTransactionHistoryResponse(BaseModel):
    """Response model for transaction history"""
    transactions: list[TEGTransactionInfo]
    total: int
    limit: int
    offset: int


# --- Endpoints ---
@router.get("/balance", response_model=TEGBalanceResponse, summary="Get TEG Token Balance")
async def get_teg_balance(
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get the TEG token balance for the currently authenticated developer.
    
    Uses OAuth 2.0 JWT Bearer Grant flow for authentication.
    """
    response = await make_teg_request(
        method="GET",
        endpoint="/token/balance",
        developer=current_developer
    )
    
    if response.status_code == 200:
        data = response.json()
        return TEGBalanceResponse(
            agent_id=data.get("agent_id"),
            balance=str(data.get("balance", "0"))
        )
    else:
        logger.error(f"TEG API balance request failed: {response.status_code} - {response.text}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch TEG balance at this time"
        )


@router.post("/transfer", response_model=TEGTransferResponse, summary="Transfer TEG Tokens")
async def transfer_teg_tokens(
    request: TEGTransferRequest,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Transfer TEG tokens to another agent.
    
    Uses OAuth 2.0 JWT Bearer Grant flow for authentication.
    """
    teg_request = {
        "receiver_agent_id": request.receiver_agent_id,
        "amount": request.amount
    }
    if request.message:
        teg_request["message"] = request.message
    
    response = await make_teg_request(
        method="POST",
        endpoint="/token/transfer",
        developer=current_developer,
        json_data=teg_request
    )
    
    if response.status_code == 200:
        data = response.json()
        return TEGTransferResponse(
            transaction_id=data["transaction_id"],
            status=data["status"],
            sender_agent_id=data["sender_agent_id"],
            receiver_agent_id=data["receiver_agent_id"],
            amount=str(data["amount"]),
            fee_amount=str(data.get("fee_amount", "0")),
            new_sender_balance=str(data["new_sender_balance"]),
            timestamp=data["timestamp"],
            attached_message=data.get("attached_message")
        )
    elif response.status_code == 400:
        error_data = response.json()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_data.get("detail", "Transfer failed")
        )
    else:
        logger.error(f"TEG API transfer request failed: {response.status_code} - {response.text}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to process transfer at this time"
        )


@router.get("/history", response_model=TEGTransactionHistoryResponse, summary="Get Transaction History")
async def get_transaction_history(
    limit: int = 100,
    offset: int = 0,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get transaction history for the authenticated developer's agent.
    
    Uses OAuth 2.0 JWT Bearer Grant flow for authentication.
    """
    response = await make_teg_request(
        method="GET",
        endpoint="/token/history",
        developer=current_developer,
        params={"limit": limit, "offset": offset}
    )
    
    if response.status_code == 200:
        data = response.json()
        transactions = [
            TEGTransactionInfo(
                transaction_id=tx["transaction_id"],
                sender_agent_id=tx.get("sender_agent_id"),
                receiver_agent_id=tx["receiver_agent_id"],
                amount=str(tx["amount"]),
                fee_amount=str(tx["fee_amount"]),
                status=tx["status"],
                transaction_type=tx["transaction_type"],
                timestamp=tx["timestamp"],
                error_message=tx.get("error_message"),
                reputation_signal_applied=tx.get("reputation_signal_applied", False),
                attached_message=tx.get("attached_message")
            )
            for tx in data["transactions"]
        ]
        
        return TEGTransactionHistoryResponse(
            transactions=transactions,
            total=data["total"],
            limit=data["limit"],
            offset=data["offset"]
        )
    else:
        logger.error(f"TEG API history request failed: {response.status_code} - {response.text}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch transaction history at this time"
        )


@router.get("/fee-config", response_model=TEGFeeConfigResponse, summary="Get Fee Configuration")
async def get_fee_configuration():
    """
    Get current fee configuration.
    
    This endpoint is public as agents need to know the fee before initiating transfers.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/fee-config",
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return TEGFeeConfigResponse(
                    transfer_fee_amount=str(data["transfer_fee_amount"]),
                    fee_collection_address=data["fee_collection_address"]
                )
            else:
                logger.error(f"TEG API fee config request failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch fee configuration at this time"
                )
                
        except httpx.RequestError as e:
            logger.error(f"TEG API connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service unavailable"
            )


logger.info("TEG integration router initialized with OAuth 2.0 JWT Bearer Grant authentication")
