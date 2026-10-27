"""TEG Layer integration endpoints for TheProtocol v1.0.0

This module provides proxy endpoints that allow the v1.0.0 UI to interact
with the TEG Layer MVP API. It handles authentication bridging between
v1.0.0 JWT tokens and TEG API calls using JWT-SVIDs.

REQ-INT-V1AUTH-001 Implementation:
- Acquires JWT-SVIDs for authenticated agents via SPIRE
- Forwards JWT-SVIDs to TEG API for end-user authentication
- Maintains mTLS connection for service-to-service trust
"""

import logging
import os
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field
import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from agentvault_registry import models, security
from agentvault_registry.config import settings
from agentvault_registry.core.jwt_svid_provider import acquire_agent_jwt_svid

# Import SPIRE mTLS client for secure communication
try:
    from agentvault_registry.core.spire_mtls_client import SPIREMTLSClient
    SPIRE_MTLS_AVAILABLE = True
except ImportError:
    SPIRE_MTLS_AVAILABLE = False
    logging.warning("SPIRE mTLS client not available - using standard HTTPS")

logger = logging.getLogger(__name__)

# TEG API configuration - using environment variables
TEG_API_BASE_URL = getattr(settings, 'TEG_API_BASE_URL', 'https://localhost:8001')  # Changed to HTTPS
TEG_API_V1_PREFIX = '/api/v1'

# JWT-SVID audience for TEG Core Service
TEG_CORE_AUDIENCE = "spiffe://agentvault.com/service/teg-core"

router = APIRouter(
    prefix="/teg",
    tags=["TEG Integration"],
    dependencies=[Depends(security.get_current_developer)]
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

class TEGReputationSignalRequest(BaseModel):
    """Request model for applying reputation signal"""
    signal_value: int = Field(..., description="Reputation signal value (+1 or -1)")

class TEGReputationSignalResponse(BaseModel):
    """Response model for reputation signal"""
    transaction_id: str
    sender_agent_id: str
    receiver_agent_id: str
    signal_value: int
    new_receiver_reputation: int
    status: str

class TEGAgentReputationResponse(BaseModel):
    """Response model for agent reputation"""
    agent_id: str
    reputation_score: int
    reputation_tier: str
    last_updated: Optional[str] = None


# --- Helper Functions ---
async def get_mtls_client():
    """Get an mTLS-enabled HTTP client if SPIRE is available"""
    if SPIRE_MTLS_AVAILABLE:
        try:
            client = SPIREMTLSClient()
            return await client.get_async_client()
        except Exception as e:
            logger.warning(f"Failed to create mTLS client: {e}, falling back to standard HTTPS")
    
    # Fallback to standard HTTPS client
    return httpx.AsyncClient(verify=False)  # In production, use proper CA verification


async def make_teg_request_with_jwt_svid(
    method: str,
    endpoint: str,
    current_developer: models.Developer,
    json_data: Optional[dict] = None,
    params: Optional[dict] = None
) -> httpx.Response:
    """
    Make a request to the TEG API with proper JWT-SVID authentication.
    
    This function:
    1. Acquires a JWT-SVID for the authenticated agent
    2. Establishes an mTLS connection to TEG API
    3. Includes the JWT-SVID in the Authorization header
    
    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint path
        current_developer: Authenticated v1.0.0 developer
        json_data: Optional JSON body
        params: Optional query parameters
    
    Returns:
        httpx.Response from the TEG API
    """
    # Acquire JWT-SVID for the authenticated agent
    try:
        jwt_svid = await acquire_agent_jwt_svid(
            agent_email=current_developer.email,
            audience=TEG_CORE_AUDIENCE
        )
        logger.info(f"Acquired JWT-SVID for agent: {current_developer.email}")
    except Exception as e:
        logger.error(f"Failed to acquire JWT-SVID: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to acquire authentication token for TEG service"
        )
    
    # Get mTLS client
    client = await get_mtls_client()
    
    try:
        # Make the request with JWT-SVID authentication
        url = f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}{endpoint}"
        
        response = await client.request(
            method=method,
            url=url,
            headers={
                "Authorization": f"Bearer {jwt_svid}",
                "X-Request-Source": "agentvault-registry-v1"
            },
            json=json_data,
            params=params,
            timeout=10.0
        )
        
        return response
        
    finally:
        await client.aclose()


# --- Updated Endpoints with JWT-SVID Authentication ---
@router.get("/balance", response_model=TEGBalanceResponse, summary="Get TEG Token Balance")
async def get_teg_balance(
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get the TEG token balance for the currently authenticated developer.
    
    This endpoint proxies the request to the TEG Layer API using:
    - mTLS for service-to-service authentication
    - JWT-SVID for end-user authentication
    """
    try:
        response = await make_teg_request_with_jwt_svid(
            method="GET",
            endpoint="/token/balance",
            current_developer=current_developer
        )
        
        if response.status_code == 200:
            data = response.json()
            return TEGBalanceResponse(
                agent_id=data.get("agent_id"),
                balance=str(data.get("balance", "0"))
            )
        elif response.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEG service authentication failed"
            )
        else:
            logger.error(f"TEG API balance request failed: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to fetch TEG balance at this time"
            )
            
    except httpx.RequestError as e:
        logger.error(f"TEG API connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG service unavailable"
        )


@router.post("/transfer", response_model=TEGTransferResponse, summary="Transfer TEG Tokens")
async def transfer_teg_tokens(
    request: TEGTransferRequest,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Transfer TEG tokens to another agent.
    
    This endpoint proxies the transfer request to the TEG Layer API,
    using JWT-SVIDs for authentication.
    """
    try:
        # Prepare TEG API request
        teg_request = {
            "receiver_agent_id": request.receiver_agent_id,
            "amount": request.amount
        }
        if request.message:
            teg_request["message"] = request.message
        
        response = await make_teg_request_with_jwt_svid(
            method="POST",
            endpoint="/token/transfer",
            current_developer=current_developer,
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
            # Parse error from TEG API
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
            
    except httpx.RequestError as e:
        logger.error(f"TEG API connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG service unavailable"
        )


@router.post("/system-transfer", response_model=TEGSystemTransferResponse, summary="Transfer TEG Tokens to System")
async def transfer_teg_to_system(
    request: TEGSystemTransferRequest,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Transfer TEG tokens to the system treasury.
    
    This endpoint proxies the system transfer request to the TEG Layer API
    using JWT-SVIDs for authentication.
    """
    try:
        # Prepare TEG API request
        teg_request = {
            "amount": request.amount,
            "purpose": request.purpose
        }
        
        response = await make_teg_request_with_jwt_svid(
            method="POST",
            endpoint="/token/system-transfer",
            current_developer=current_developer,
            json_data=teg_request
        )
        
        if response.status_code == 200:
            data = response.json()
            return TEGSystemTransferResponse(
                transaction_id=data["transaction_id"],
                status=data["status"],
                sender_agent_id=data["sender_agent_id"],
                system_receiver_id=data["system_receiver_id"],
                amount=str(data["amount"]),
                purpose=data["purpose"],
                new_sender_balance=str(data["new_sender_balance"]),
                timestamp=data["timestamp"]
            )
        elif response.status_code == 400:
            # Parse error from TEG API
            error_data = response.json()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_data.get("detail", "System transfer failed")
            )
        else:
            logger.error(f"TEG API system transfer request failed: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to process system transfer at this time"
            )
            
    except httpx.RequestError as e:
        logger.error(f"TEG API connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG service unavailable"
        )


@router.get("/history", response_model=TEGTransactionHistoryResponse, summary="Get Transaction History")
async def get_transaction_history(
    limit: int = 100,
    offset: int = 0,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get transaction history for the authenticated developer's agent.
    
    Returns paginated list of transactions where the agent was either
    sender or receiver, ordered by timestamp (newest first).
    """
    try:
        response = await make_teg_request_with_jwt_svid(
            method="GET",
            endpoint="/token/history",
            current_developer=current_developer,
            params={"limit": limit, "offset": offset}
        )
        
        if response.status_code == 200:
            data = response.json()
            # Convert transaction data
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
            
    except httpx.RequestError as e:
        logger.error(f"TEG API connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG service unavailable"
        )


@router.post("/transactions/{transaction_id}/reputation-signal", response_model=TEGReputationSignalResponse, summary="Apply Reputation Signal")
async def apply_reputation_signal(
    transaction_id: str,
    request: TEGReputationSignalRequest,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Apply a reputation signal to a completed transaction.
    
    Allows the sender of a successful A2A token transfer to signal
    about the receiver's performance. Each transaction can only
    receive one reputation signal.
    """
    try:
        teg_request = {
            "signal_value": request.signal_value
        }
        
        response = await make_teg_request_with_jwt_svid(
            method="POST",
            endpoint=f"/token/{transaction_id}/reputation-signal",
            current_developer=current_developer,
            json_data=teg_request
        )
        
        if response.status_code == 200:
            data = response.json()
            return TEGReputationSignalResponse(
                transaction_id=data["transaction_id"],
                sender_agent_id=data["sender_agent_id"],
                receiver_agent_id=data["receiver_agent_id"],
                signal_value=data["signal_value"],
                new_receiver_reputation=data["new_receiver_reputation"],
                status=data["status"]
            )
        elif response.status_code == 400:
            error_data = response.json()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_data.get("detail", "Failed to apply reputation signal")
            )
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        else:
            logger.error(f"TEG API reputation signal request failed: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to apply reputation signal at this time"
            )
            
    except httpx.RequestError as e:
        logger.error(f"TEG API connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG service unavailable"
        )


@router.get("/agents/{agent_id}/reputation", response_model=TEGAgentReputationResponse, summary="Get Agent Reputation")
async def get_agent_reputation(
    agent_id: str,
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get reputation score for a specific agent.
    
    Returns the current reputation score and tier for the specified agent.
    Note: Uses a system view token as agents can view other agents' reputation.
    """
    try:
        response = await make_teg_request_with_jwt_svid(
            method="GET",
            endpoint=f"/agents/{agent_id}/reputation",
            current_developer=current_developer
        )
        
        if response.status_code == 200:
            data = response.json()
            return TEGAgentReputationResponse(
                agent_id=data["agent_id"],
                reputation_score=data["reputation_score"],
                reputation_tier=data["reputation_tier"],
                last_updated=data.get("last_updated")
            )
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )
        else:
            logger.error(f"TEG API reputation request failed: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to fetch reputation at this time"
            )
            
    except httpx.RequestError as e:
        logger.error(f"TEG API connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG service unavailable"
        )


@router.get("/fee-config", response_model=TEGFeeConfigResponse, summary="Get Fee Configuration")
async def get_fee_configuration():
    """
    Get current fee configuration.
    
    Returns the current transfer fee amount and the address where fees are collected.
    This endpoint is public as agents need to know the fee before initiating transfers.
    
    Note: This endpoint doesn't require JWT-SVID as it's public information.
    """
    client = await get_mtls_client()
    
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
    finally:
        await client.aclose()


logger.info("TEG integration router initialized with JWT-SVID authentication support")
