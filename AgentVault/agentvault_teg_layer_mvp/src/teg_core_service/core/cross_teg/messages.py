"""
Cross-TEG Transfer Message Definitions.

Implements the message formats for AVTP cross-TEG communication.
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, validator
from decimal import Decimal


class TransferStatus(str, Enum):
    """Status of a cross-TEG transfer."""
    PENDING = "pending"
    LOCKED = "locked"
    TRANSFERRED = "transferred"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"


class CrossTEGTransferRequest(BaseModel):
    """Request to initiate a cross-TEG transfer."""
    
    # Transfer identification
    transfer_id: str = Field(..., description="Unique transfer ID (UUID)")
    correlation_id: str = Field(..., description="Correlation ID for distributed tracing")
    
    # Source information
    source_teg_id: str = Field(..., description="Source TEG identifier")
    source_registry_id: str = Field(..., description="Source registry identifier")
    source_agent_id: str = Field(..., description="Source agent DID")
    
    # Target information
    target_teg_id: str = Field(..., description="Target TEG identifier")
    target_registry_id: str = Field(..., description="Target registry identifier")
    target_teg_url: Optional[str] = Field(None, description="Target TEG mTLS URL (from registry BFS discovery)")
    target_agent_id: str = Field(..., description="Target agent DID")
    
    # Transfer details
    amount: Decimal = Field(..., gt=0, description="Transfer amount")
    currency: str = Field(default="TEG", description="Currency code")
    
    # Authentication
    authorization_token: str = Field(..., description="Cross-registry OAuth token")
    
    # Metadata
    memo: Optional[str] = Field(None, max_length=500, description="Transfer memo")
    initiated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Transfer expiration time")
    
    # Security
    idempotency_key: str = Field(..., description="Idempotency key for retry safety")
    signature: Optional[str] = Field(None, description="Digital signature of the request")
    
    @validator('expires_at')
    def validate_expiration(cls, v, values):
        """Ensure expiration is in the future and within limits."""
        initiated = values.get('initiated_at', datetime.now(timezone.utc))
        if v <= initiated:
            raise ValueError("Transfer expiration must be in the future")
        
        max_duration = 300  # 5 minutes max
        if (v - initiated).total_seconds() > max_duration:
            raise ValueError(f"Transfer expiration cannot exceed {max_duration} seconds")
        
        return v
    
    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }


class CrossTEGTransferResponse(BaseModel):
    """Response to a cross-TEG transfer request."""
    
    transfer_id: str
    correlation_id: str
    status: TransferStatus
    
    # Processing details
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processing_teg_id: str
    
    # Result information
    success: bool
    message: Optional[str] = None
    error_code: Optional[str] = None
    
    # Transaction details (when successful)
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None
    
    # Fee details (cross-registry fee collected on target TEG)
    fee_amount: Optional[Decimal] = None
    credited_amount: Optional[Decimal] = None

    # For failed transfers
    refund_transaction_hash: Optional[str] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TransferLockRequest(BaseModel):
    """Request to lock funds for a cross-TEG transfer."""
    
    transfer_id: str
    agent_id: str
    amount: Decimal
    expires_at: datetime
    
    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }


class TransferLockResponse(BaseModel):
    """Response to a fund lock request."""
    
    transfer_id: str
    locked: bool
    lock_transaction_hash: Optional[str] = None
    error: Optional[str] = None


class TransferAcceptRequest(BaseModel):
    """Request to accept an incoming cross-TEG transfer."""
    
    transfer_id: str
    correlation_id: str
    source_teg_id: str
    amount: Decimal
    recipient_agent_id: str
    authorization_token: str
    
    class Config:
        json_encoders = {
            Decimal: str
        }


class TransferAcceptResponse(BaseModel):
    """Response to accepting a cross-TEG transfer."""

    transfer_id: str
    accepted: bool
    transaction_hash: Optional[str] = None
    error: Optional[str] = None
    fee_amount: Optional[Decimal] = None
    credited_amount: Optional[Decimal] = None


class CompensationRequest(BaseModel):
    """Request to compensate (rollback) a failed transfer."""
    
    transfer_id: str
    correlation_id: str
    reason: str
    original_amount: Decimal
    agent_id: str
    
    class Config:
        json_encoders = {
            Decimal: str
        }


class CompensationResponse(BaseModel):
    """Response to a compensation request."""
    
    transfer_id: str
    compensated: bool
    refund_transaction_hash: Optional[str] = None
    error: Optional[str] = None


class HeartbeatMessage(BaseModel):
    """Heartbeat message for cross-TEG connection health."""
    
    teg_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "healthy"
    connected_tegs: list[str] = Field(default_factory=list)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TransferStatusQuery(BaseModel):
    """Query for transfer status across TEGs."""
    
    transfer_id: str
    querying_teg_id: str
    include_details: bool = False


class TransferStatusUpdate(BaseModel):
    """Update message for transfer status changes."""
    
    transfer_id: str
    correlation_id: str
    old_status: TransferStatus
    new_status: TransferStatus
    updated_by_teg: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Optional[Dict[str, Any]] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
