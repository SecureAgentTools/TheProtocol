"""TEG Layer integration endpoints with mTLS support

This enhanced version includes SPIFFE/SPIRE integration for mTLS client authentication
when connecting to the TEG Layer API. It maintains backward compatibility for non-mTLS
environments while providing secure service-to-service authentication when available.
"""

import logging
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field
import httpx
from ..es_ssl_helper import get_httpx_verify
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded
from fastapi import APIRouter, Depends, HTTPException, status

from agentvault_registry import models, security
from agentvault_registry.identifiers import developer_teg_did
from agentvault_registry.config import settings
from agentvault_registry.identity import svid_client

logger = logging.getLogger(__name__)

# TEG API configuration - using environment variables
TEG_API_BASE_URL = getattr(settings, 'TEG_API_BASE_URL', 'http://localhost:8001')
# Switch to HTTPS if mTLS is available
if svid_client.is_initialized() and TEG_API_BASE_URL.startswith('http://'):
    TEG_API_BASE_URL = TEG_API_BASE_URL.replace('http://', 'https://')
    logger.info(f"mTLS available, using HTTPS for TEG API: {TEG_API_BASE_URL}")

TEG_API_V1_PREFIX = '/api/v1'

# For MVP, we'll use a placeholder approach for TEG authentication
# Boss will implement proper auth bridge later
TEG_PLACEHOLDER_AUTH_TOKEN = getattr(settings, 'TEG_PLACEHOLDER_AUTH_TOKEN', '')

router = APIRouter(
    prefix="/teg",
    tags=["TEG Integration"],
    dependencies=[Depends(security.get_current_developer)]
)

# --- Request/Response Schemas ---
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


def get_httpx_client() -> httpx.AsyncClient:
    """Create HTTPX client with mTLS configuration if available"""
    client_config = {}
    
    # Check if mTLS is available
    cert_config = svid_client.get_client_cert_config()
    if cert_config:
        logger.info(f"Using mTLS client with SPIFFE ID: {svid_client.get_spiffe_id()}")
        client_config.update(cert_config)
    else:
        logger.debug("mTLS not available, using standard HTTP client")
    
    # Add timeout configuration
    client_config['timeout'] = 10.0

    # Internal mTLS via SPIRE bundle + SVID (T1.2 — Option C)
    client_config['verify'] = get_httpx_verify()

    return httpx.AsyncClient(**client_config)


# --- Endpoints ---
@router.get("/balance", response_model=TEGBalanceResponse, summary="Get TEG Token Balance")
async def get_teg_balance(
    current_developer: models.Developer = Depends(security.get_current_developer)
):
    """
    Get the TEG token balance for the currently authenticated developer.
    
    This endpoint proxies the request to the TEG Layer API, mapping
    the v1.0.0 developer identity to their TEG agent ID. Uses mTLS
    for authentication when available.
    """
    # For MVP, we use the developer's email as their agent ID
    # Boss will implement proper ID mapping in REQ-INT-V1AUTH-001
    agent_id = developer_teg_did(current_developer.email)
    
    async with get_httpx_client() as client:
        try:
            # Make request to TEG API with agent ID as token
            # When mTLS is enabled, the TEG API will authenticate us via our SVID
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/balance",
                headers={
                    "Authorization": f"Bearer {agent_id}"  # Pass agent ID for TEG to use
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return TEGBalanceResponse(
                    agent_id=data.get("agent_id", agent_id),
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
    handling authentication and ID mapping. Uses mTLS for secure
    service-to-service communication when available.
    """
    # Map developer to agent ID
    sender_agent_id = developer_teg_did(current_developer.email)
    
    async with get_httpx_client() as client:
        try:
            # Prepare TEG API request
            teg_request = {
                "receiver_agent_id": request.receiver_agent_id,
                "amount": request.amount
            }
            if request.message:
                teg_request["message"] = request.message
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transfer",
                json=teg_request,
                headers={
                    "Authorization": f"Bearer {sender_agent_id}"  # Pass agent ID for TEG to use
                }
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
    for paying system fees or other system-level transfers. Uses mTLS for
    secure communication when available.
    """
    # Map developer to agent ID
    sender_agent_id = developer_teg_did(current_developer.email)
    
    async with get_httpx_client() as client:
        try:
            # Prepare TEG API request
            teg_request = {
                "amount": request.amount,
                "purpose": request.purpose
            }
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/system-transfer",
                json=teg_request,
                headers={
                    "Authorization": f"Bearer {sender_agent_id}"  # Pass agent ID for TEG to use
                }
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
    sender or receiver, ordered by timestamp (newest first). Uses mTLS
    for secure API communication when available.
    """
    # Map developer to agent ID
    agent_id = developer_teg_did(current_developer.email)
    
    async with get_httpx_client() as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/history",
                params={"limit": limit, "offset": offset},
                headers={
                    "Authorization": f"Bearer {agent_id}"  # Pass agent ID for TEG to use
                }
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
    receive one reputation signal. Uses mTLS for secure communication.
    """
    # Map developer to agent ID
    agent_id = developer_teg_did(current_developer.email)
    
    async with get_httpx_client() as client:
        try:
            teg_request = {
                "signal_value": request.signal_value
            }
            
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/{seg(transaction_id)}/reputation-signal",
                json=teg_request,
                headers={
                    "Authorization": f"Bearer {agent_id}"  # Pass agent ID for TEG to use
                }
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
    Uses mTLS for secure API communication when available.
    """
    async with get_httpx_client() as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/agents/{seg(agent_id)}/reputation",
                headers={
                    "Authorization": f"Bearer agent_system"  # Use a system token for viewing other agents' reputation
                }
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
    Uses mTLS when available for enhanced security.
    """
    async with get_httpx_client() as client:
        try:
            response = await client.get(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/fee-config"
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

# Initialize SVID client on module load
logger.info("Initializing SVID client for TEG integration...")
if svid_client.initialize():
    logger.info(f"mTLS client initialized with SPIFFE ID: {svid_client.get_spiffe_id()}")
else:
    logger.info("mTLS client not available - will use standard HTTP")

logger.info("TEG integration router initialized")
