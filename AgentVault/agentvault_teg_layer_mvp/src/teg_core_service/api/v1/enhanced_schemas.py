"""
Enhanced Pydantic schemas with comprehensive validation for TEG API

Provides:
- Strict input validation
- Clear error messages
- Type safety
- Business rule enforcement
"""
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Literal, Dict, Any
from uuid import UUID
import re

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


# ===== Constants =====
MAX_DECIMAL_PLACES = 18
MAX_MESSAGE_LENGTH = 256
MIN_AGENT_ID_LENGTH = 7  # "agent_" + at least 1 char
MAX_AGENT_ID_LENGTH = 64
DID_PATTERN = re.compile(r"^did:[a-zA-Z0-9]+:[a-zA-Z0-9_\-:]+$")
AGENT_ID_PATTERN = re.compile(r"^agent_[a-zA-Z0-9_\-]+$")


# ===== Error Codes =====
class ErrorCode:
    """Standardized error codes for consistent error handling"""
    # Validation errors
    INVALID_AMOUNT = "INVALID_AMOUNT"
    INVALID_AGENT_ID = "INVALID_AGENT_ID"
    INVALID_DID = "INVALID_DID"
    INVALID_TRANSACTION_ID = "INVALID_TRANSACTION_ID"
    
    # Business logic errors
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    TRANSACTION_NOT_FOUND = "TRANSACTION_NOT_FOUND"
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    
    # System errors
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


# ===== Base Models =====
class StrictBaseModel(BaseModel):
    """Base model with strict validation"""
    model_config = ConfigDict(
        # Validate field defaults
        validate_default=True,
        # Validate on assignment
        validate_assignment=True,
        # Use enum values
        use_enum_values=True,
        # Forbid extra fields
        extra="forbid",
        # Custom JSON encoders
        json_encoders={
            Decimal: lambda v: str(v),
            datetime: lambda v: v.isoformat()
        }
    )


# ===== Validators =====
def validate_decimal_amount(v: Decimal) -> Decimal:
    """Validate decimal amount with precision checks"""
    if v <= 0:
        raise ValueError("Amount must be positive")
    
    # Check decimal places
    if v.as_tuple().exponent < -MAX_DECIMAL_PLACES:
        raise ValueError(f"Amount has too many decimal places (max {MAX_DECIMAL_PLACES})")
    
    # Check for NaN or Infinity
    if not v.is_finite():
        raise ValueError("Amount must be a finite number")
    
    return v


def validate_agent_id(v: str) -> str:
    """Validate agent ID format"""
    if not v:
        raise ValueError("Agent ID cannot be empty")
    
    if len(v) < MIN_AGENT_ID_LENGTH:
        raise ValueError(f"Agent ID too short (min {MIN_AGENT_ID_LENGTH} chars)")
    
    if len(v) > MAX_AGENT_ID_LENGTH:
        raise ValueError(f"Agent ID too long (max {MAX_AGENT_ID_LENGTH} chars)")
    
    if not AGENT_ID_PATTERN.match(v):
        raise ValueError("Invalid agent ID format. Must be 'agent_' followed by alphanumeric, underscore, or hyphen")
    
    return v


def validate_did(v: str) -> str:
    """Validate DID format"""
    if not v:
        raise ValueError("DID cannot be empty")
    
    if not DID_PATTERN.match(v):
        raise ValueError("Invalid DID format. Must be 'did:method:identifier'")
    
    return v


# ===== Token Models =====
class TokenBalanceResponse(StrictBaseModel):
    """Response model for balance inquiry"""
    agent_id: str = Field(..., description="Agent identifier")
    balance: Decimal = Field(..., description="Current token balance", ge=0)
    
    @field_validator('agent_id')
    def validate_agent_id_field(cls, v):
        return validate_agent_id(v)


class FeeConfigResponse(StrictBaseModel):
    """Response model for fee configuration"""
    transfer_fee_amount: Decimal = Field(..., description="Current transfer fee amount", ge=0)
    fee_collection_address: str = Field(..., description="Address where fees are collected")
    is_active: bool = Field(default=True, description="Whether fees are currently active")
    
    @field_validator('fee_collection_address')
    def validate_fee_address(cls, v):
        return validate_did(v)


class TokenTransferRequest(StrictBaseModel):
    """Request model for token transfer with enhanced validation"""
    receiver_agent_id: str = Field(
        ..., 
        description="Recipient agent ID",
        min_length=MIN_AGENT_ID_LENGTH,
        max_length=MAX_AGENT_ID_LENGTH
    )
    amount: Decimal = Field(
        ..., 
        description="Amount to transfer",
        gt=0,
        decimal_places=MAX_DECIMAL_PLACES
    )
    message: Optional[str] = Field(
        None, 
        description="Optional message to attach to transfer",
        max_length=MAX_MESSAGE_LENGTH
    )
    idempotency_key: Optional[str] = Field(
        None,
        description="Optional idempotency key to prevent duplicate transfers",
        min_length=16,
        max_length=64
    )
    
    @field_validator('receiver_agent_id')
    def validate_receiver(cls, v):
        return validate_agent_id(v)
    
    @field_validator('amount')
    def validate_amount_field(cls, v):
        return validate_decimal_amount(v)
    
    @field_validator('message')
    def sanitize_message(cls, v):
        if v:
            # Remove control characters
            v = ''.join(char for char in v if ord(char) >= 32 or char in '\n\r\t')
            # Trim whitespace
            v = v.strip()
        return v


class TokenTransferResponse(StrictBaseModel):
    """Response model for token transfer"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: Literal["success", "pending", "failed"] = Field(..., description="Transaction status")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    receiver_agent_id: str = Field(..., description="Recipient agent ID")
    amount: Decimal = Field(..., description="Amount transferred")
    fee_amount: Decimal = Field(default=Decimal("0"), description="Transaction fee", ge=0)
    total_deducted: Decimal = Field(..., description="Total amount deducted from sender")
    new_sender_balance: Decimal = Field(..., description="Sender's balance after transfer", ge=0)
    timestamp: datetime = Field(..., description="Transaction timestamp")
    attached_message: Optional[str] = Field(None, description="Message attached to the transfer")
    
    @model_validator(mode='after')
    def validate_totals(self):
        """Ensure total_deducted equals amount + fee_amount"""
        expected_total = self.amount + self.fee_amount
        if self.total_deducted != expected_total:
            self.total_deducted = expected_total
        return self


class TokenSystemTransferRequest(StrictBaseModel):
    """Request model for agent-to-system token transfer"""
    amount: Decimal = Field(
        ...,
        description="Amount to transfer to system",
        gt=0,
        decimal_places=MAX_DECIMAL_PLACES
    )
    purpose: Literal[
        "system_fee",
        "service_payment",
        "treasury_contribution",
        "penalty_payment",
        "other"
    ] = Field(..., description="Purpose of system transfer")
    purpose_details: Optional[str] = Field(
        None,
        description="Additional details about the purpose",
        max_length=256
    )
    
    @field_validator('amount')
    def validate_amount_field(cls, v):
        return validate_decimal_amount(v)


# ===== Admin Models =====
class AdminTokenIssuanceRequest(StrictBaseModel):
    """Request model for admin token issuance"""
    target_agent_id: str = Field(
        ...,
        description="Target agent ID",
        min_length=MIN_AGENT_ID_LENGTH,
        max_length=MAX_AGENT_ID_LENGTH
    )
    amount: Decimal = Field(
        ...,
        description="Amount to issue",
        gt=0,
        decimal_places=MAX_DECIMAL_PLACES
    )
    reason: str = Field(
        ...,
        description="Reason for issuance",
        min_length=10,
        max_length=256
    )
    
    @field_validator('target_agent_id')
    def validate_target(cls, v):
        return validate_agent_id(v)
    
    @field_validator('amount')
    def validate_amount_field(cls, v):
        return validate_decimal_amount(v)


class AdminFeeConfigUpdateRequest(StrictBaseModel):
    """Request model for updating fee configuration"""
    transfer_fee_amount: Decimal = Field(
        ...,
        description="New transfer fee amount",
        ge=0,
        decimal_places=MAX_DECIMAL_PLACES
    )
    fee_collection_address: Optional[str] = Field(
        None,
        description="New fee collection address (DID format)"
    )
    
    @field_validator('transfer_fee_amount')
    def validate_fee_amount(cls, v):
        if v < 0:
            raise ValueError("Fee amount cannot be negative")
        return validate_decimal_amount(v) if v > 0 else v
    
    @field_validator('fee_collection_address')
    def validate_fee_address(cls, v):
        if v:
            return validate_did(v)
        return v


# ===== Transaction Models =====
class TransactionInfo(StrictBaseModel):
    """Enhanced transaction information model"""
    transaction_id: str
    sender_agent_id: Optional[str]
    receiver_agent_id: str
    amount: Decimal
    fee_amount: Decimal
    status: Literal["success", "pending", "failed"]
    transaction_type: Literal[
        "transfer",
        "issuance",
        "reward",
        "fee",
        "system_transfer",
        "penalty"
    ]
    timestamp: datetime
    error_message: Optional[str] = None
    attached_message: Optional[str] = None
    reputation_signal: Optional[int] = Field(
        None,
        description="Reputation signal applied (-1, 0, or +1)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional transaction metadata"
    )
    
    model_config = ConfigDict(from_attributes=True)


class TransactionHistoryRequest(StrictBaseModel):
    """Request model for transaction history with filters"""
    limit: int = Field(
        default=50,
        description="Number of transactions to return",
        ge=1,
        le=1000
    )
    offset: int = Field(
        default=0,
        description="Offset for pagination",
        ge=0
    )
    transaction_type: Optional[str] = Field(
        None,
        description="Filter by transaction type"
    )
    status: Optional[str] = Field(
        None,
        description="Filter by status"
    )
    start_date: Optional[datetime] = Field(
        None,
        description="Filter transactions after this date"
    )
    end_date: Optional[datetime] = Field(
        None,
        description="Filter transactions before this date"
    )
    
    @model_validator(mode='after')
    def validate_date_range(self):
        """Ensure end_date is after start_date if both provided"""
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                raise ValueError("end_date must be after start_date")
        return self


# ===== Attestation Models =====
class ZKPAttestationDetail(StrictBaseModel):
    """ZKP-specific attestation details"""
    circuit_id: str = Field(
        ...,
        description="Circuit identifier (e.g., fairMarkupPolicy/v1.0.0)",
        pattern=r"^[a-zA-Z0-9_\-]+/v\d+\.\d+\.\d+$"
    )
    public_inputs: Dict[str, Any] = Field(
        ...,
        description="Public inputs for the ZKP circuit"
    )
    proof_value: str = Field(
        ...,
        description="ZKP proof value",
        min_length=64
    )


class AttestationSubmissionRequest(StrictBaseModel):
    """Request model for attestation submission"""
    agent_did: str = Field(..., description="Agent DID submitting the attestation")
    attestation_type: Literal[
        "compliance",
        "quality",
        "identity",
        "resource_usage",
        "zkp"
    ] = Field(..., description="Type of attestation")
    attestation_hash: str = Field(
        ...,
        description="Hash of the attestation content",
        pattern=r"^[a-fA-F0-9]{64}$"
    )
    storage_pointer: str = Field(
        ...,
        description="Storage location (e.g., IPFS CID)",
        min_length=10,
        max_length=256
    )
    zkp_payload: Optional[ZKPAttestationDetail] = Field(
        None,
        description="ZKP attestation details"
    )
    
    @field_validator('agent_did')
    def validate_agent_did(cls, v):
        return validate_did(v)
    
    @model_validator(mode='after')
    def validate_zkp_requirements(self):
        """Ensure zkp_payload is provided for zkp attestations"""
        if self.attestation_type == "zkp" and not self.zkp_payload:
            raise ValueError("zkp_payload is required for zkp attestation type")
        return self


# ===== Reputation Models =====
class AgentReputationResponse(StrictBaseModel):
    """Response model for agent reputation"""
    agent_id: str = Field(..., description="Agent identifier")
    reputation_score: int = Field(..., description="Current reputation score", ge=0)
    reputation_tier: Literal["BRONZE", "SILVER", "GOLD"] = Field(
        ...,
        description="Reputation tier"
    )
    last_updated: Optional[datetime] = Field(None, description="Last update timestamp")
    breakdown: Optional[Dict[str, float]] = Field(
        None,
        description="Score breakdown by component"
    )


class ReputationSignalRequest(StrictBaseModel):
    """Request model for applying reputation signal"""
    signal_value: Literal[-1, 1] = Field(
        ...,
        description="Reputation signal value"
    )
    reason: Optional[str] = Field(
        None,
        description="Reason for the signal",
        max_length=256
    )


# ===== Error Response =====
class ErrorResponse(StrictBaseModel):
    """Enhanced error response with structured details"""
    detail: str = Field(..., description="Human-readable error message")
    error_code: str = Field(..., description="Machine-readable error code")
    field_errors: Optional[Dict[str, List[str]]] = Field(
        None,
        description="Field-specific validation errors"
    )
    request_id: Optional[str] = Field(
        None,
        description="Request ID for tracking"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Error timestamp"
    )


# ===== System Metrics =====
class SystemMetricsResponse(StrictBaseModel):
    """Enhanced response model for system metrics"""
    # Basic metrics
    total_agents_with_balance: int = Field(..., description="Total number of agents with TEG balances", ge=0)
    total_transactions: int = Field(..., description="Total number of TEG transactions processed", ge=0)
    total_tokens_in_circulation: Decimal = Field(..., description="Total TEG tokens in circulation", ge=0)
    total_fees_collected: Decimal = Field(..., description="Total fees collected by the system", ge=0)
    
    # Fee configuration
    system_fee_amount: Decimal = Field(..., description="Current system fee amount", ge=0)
    fee_collection_address: str = Field(..., description="Current fee collection address")
    
    # Additional metrics
    total_attestations_submitted: int = Field(default=0, description="Total attestations submitted", ge=0)
    total_attestations_verified: int = Field(default=0, description="Total attestations verified", ge=0)
    total_rewards_paid: Decimal = Field(default=Decimal("0"), description="Total rewards paid out", ge=0)
    total_reputation_signals: int = Field(default=0, description="Total reputation signals applied", ge=0)
    
    # System health
    metrics_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="When metrics were calculated")
    calculation_time_ms: Optional[int] = Field(None, description="Time taken to calculate metrics", ge=0)
