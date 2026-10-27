"""Pydantic schemas for API request/response models"""
from decimal import Decimal
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TokenBalanceResponse(BaseModel):
    """Response model for balance inquiry"""
    agent_id: str = Field(..., description="Agent identifier")
    balance: Decimal = Field(..., description="Current token balance")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }
        from_attributes = True


class FeeConfigResponse(BaseModel):
    """Response model for fee configuration"""
    fee_active: bool = Field(..., description="Whether fees are active")
    fee_percentage: float = Field(..., description="Fee percentage")
    min_fee_amount: Decimal = Field(..., description="Minimum fee amount")
    max_fee_amount: Decimal = Field(..., description="Maximum fee amount")
    fee_recipient: str = Field(..., description="Address where fees are collected")
    transfer_fee_amount: Optional[Decimal] = Field(None, description="Current transfer fee amount")
    fee_collection_address: Optional[str] = Field(None, description="Address where fees are collected")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class TokenTransferRequest(BaseModel):
    """Request model for token transfer"""
    receiver_agent_id: str = Field(..., description="Recipient agent ID")
    amount: Decimal = Field(..., gt=0, description="Amount to transfer")
    message: Optional[str] = Field(None, max_length=256, description="Optional message to attach to transfer")
    fee_amount: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Pre-calculated fee amount from the registry fee service. "
                    "If provided, TEG uses this value instead of reading system_config. "
                    "TEG deducts fee from sender and credits the configured fee_collection_address."
    )

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        # Limit decimal places to prevent precision issues
        if v.as_tuple().exponent < -18:
            raise ValueError("Amount has too many decimal places (max 18)")
        return v

    @field_validator('fee_amount')
    def validate_fee_amount(cls, v):
        if v is not None:
            if v < 0:
                raise ValueError("fee_amount cannot be negative")
            if v.as_tuple().exponent < -18:
                raise ValueError("fee_amount has too many decimal places (max 18)")
        return v

    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class TokenTransferResponse(BaseModel):
    """Response model for token transfer"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: str = Field(..., description="Transaction status")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    receiver_agent_id: str = Field(..., description="Recipient agent ID")
    amount: Decimal = Field(..., description="Amount transferred")
    fee_amount: Decimal = Field(default=Decimal("0"), description="Transaction fee")
    new_sender_balance: Decimal = Field(..., description="Sender's balance after transfer")
    timestamp: datetime = Field(..., description="Transaction timestamp")
    attached_message: Optional[str] = Field(None, description="Message attached to the transfer")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class TokenSystemTransferRequest(BaseModel):
    """Request model for agent-to-system token transfer"""
    system_account_type: str = Field(..., description="System account type (e.g., 'treasury')")
    amount: Decimal = Field(..., gt=0, description="Amount to transfer to system")
    purpose: Optional[str] = Field(None, description="Purpose of system transfer (e.g., 'fee_payment')")
    
    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        # Limit decimal places to prevent precision issues
        if v.as_tuple().exponent < -18:
            raise ValueError("Amount has too many decimal places (max 18)")
        return v
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class TokenSystemTransferResponse(BaseModel):
    """Response model for agent-to-system token transfer"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: str = Field(..., description="Transaction status")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    system_receiver_id: str = Field(..., description="System treasury DID")
    system_account_type: str = Field(..., description="System account type")
    amount: Decimal = Field(..., description="Amount transferred")
    purpose: str = Field(..., description="Purpose of the transfer")
    new_sender_balance: Decimal = Field(..., description="Sender's balance after transfer")
    timestamp: datetime = Field(..., description="Transaction timestamp")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class AdminTokenIssuanceRequest(BaseModel):
    """Request model for admin token issuance"""
    target_agent_id: str = Field(..., description="Target agent ID")
    amount: Decimal = Field(..., gt=0, description="Amount to issue")
    reason: Optional[str] = Field(None, description="Reason for issuance")
    
    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v.as_tuple().exponent < -18:
            raise ValueError("Amount has too many decimal places (max 18)")
        return v
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class AdminTokenIssuanceResponse(BaseModel):
    """Response model for admin token issuance"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    status: str = Field(..., description="Transaction status")
    target_agent_id: str = Field(..., description="Target agent ID")
    amount: Decimal = Field(..., description="Amount issued")
    new_target_balance: Decimal = Field(..., description="Target's balance after issuance")
    timestamp: datetime = Field(..., description="Transaction timestamp")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class TransactionInfo(BaseModel):
    """Transaction information model"""
    transaction_id: str
    sender_agent_id: Optional[str]
    receiver_agent_id: str
    amount: Decimal
    fee_amount: Decimal
    status: str
    transaction_type: str
    timestamp: datetime
    error_message: Optional[str] = None
    attached_message: Optional[str] = None
    reputation_signal_applied: Optional[bool] = False
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class TransactionHistoryResponse(BaseModel):
    """Response model for transaction history"""
    transactions: List[TransactionInfo]
    total: int = Field(..., description="Total number of transactions")
    limit: int = Field(..., description="Number of transactions returned")
    offset: int = Field(..., description="Offset for pagination")


class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Application-specific error code")


# Attestation Schemas
class ZKPAttestationDetail(BaseModel):
    """ZKP-specific attestation details"""
    circuit_id: str = Field(..., description="Circuit identifier (e.g., fairMarkupPolicy/v1.0.0)")
    public_inputs: dict = Field(..., description="Public inputs for the ZKP circuit")
    proof_value: str = Field(..., description="ZKP proof value")


class AttestationSubmissionRequest(BaseModel):
    """Request model for attestation submission"""
    agent_did: str = Field(..., description="Agent DID submitting the attestation")
    attestation_type: str = Field(..., description="Type of attestation")
    attestation_hash: str = Field(..., description="Hash of the attestation content")
    storage_pointer: str = Field(..., description="Storage location (e.g., IPFS CID)")
    submitted_at: Optional[datetime] = Field(None, description="Submission timestamp")
    zkp_payload: Optional[ZKPAttestationDetail] = Field(None, description="ZKP attestation details")


class AttestationSubmissionResponse(BaseModel):
    """Response model for attestation submission"""
    submission_id: str = Field(..., description="Unique submission identifier")
    agent_did: str = Field(..., description="Agent DID")
    attestation_type: str = Field(..., description="Type of attestation")
    status: str = Field(..., description="Submission status")
    policy_id: Optional[str] = Field(None, description="Associated policy ID")
    policy_name: Optional[str] = Field(None, description="Associated policy name")


class AttestationInfo(BaseModel):
    """Information about an attestation submission"""
    submission_id: str = Field(..., description="Unique submission identifier")
    agent_did: str = Field(..., description="Agent DID")
    attestation_type: str = Field(..., description="Type of attestation")
    attestation_hash: str = Field(..., description="Hash of the attestation content")
    storage_pointer: str = Field(..., description="Storage location (e.g., IPFS CID)")
    submitted_at: datetime = Field(..., description="Submission timestamp")
    status: str = Field(..., description="Submission status (logged, zkp_verified_true, zkp_verified_false)")
    reward_issued_tx_id: Optional[str] = Field(None, description="Transaction ID for reward payment")
    circuit_id: Optional[str] = Field(None, description="ZKP circuit identifier")
    zkp_public_inputs_json: Optional[str] = Field(None, description="ZKP public inputs as JSON string")
    zkp_proof_value: Optional[str] = Field(None, description="ZKP proof value")
    policy_id: Optional[str] = Field(None, description="Associated policy ID")
    policy_name: Optional[str] = Field(None, description="Associated policy name")
    reward_amount: Optional[str] = Field(None, description="Reward amount from policy")


# Policy Schemas
class PolicyCreateRequest(BaseModel):
    """Request model for creating a policy"""
    policy_code: str = Field(..., description="Unique policy code")
    policy_name: str = Field(..., description="Policy name")
    policy_type: str = Field(..., description="Policy type (e.g., attestation)")
    description: Optional[str] = Field(None, description="Policy description")
    parameters: Optional[dict] = Field(default_factory=dict, description="Policy parameters")
    circuit_identifier: Optional[str] = Field(None, description="Circuit identifier for ZKP policies")
    is_active: bool = Field(True, description="Whether the policy is active")
    enforcement_level: Optional[str] = Field(None, description="Enforcement level (e.g., mandatory, optional)")
    reward_amount: Optional[Decimal] = Field(None, description="Reward amount for compliance")
    policy_version: Optional[str] = Field("1.0.0", description="Policy version")
    rules_document_url: Optional[str] = Field(None, description="URL to detailed rules document")


class PolicyUpdateRequest(BaseModel):
    """Request model for updating a policy"""
    policy_name: Optional[str] = Field(None, description="Policy name")
    description: Optional[str] = Field(None, description="Policy description")
    parameters: Optional[dict] = Field(None, description="Policy parameters")
    rules_document_url: Optional[str] = Field(None, description="URL to detailed rules document")
    is_active: Optional[bool] = Field(None, description="Whether the policy is active")
    enforcement_level: Optional[str] = Field(None, description="Enforcement level")
    reward_amount: Optional[Decimal] = Field(None, description="Reward amount for compliance")


class PolicyResponse(BaseModel):
    """Response model for policy information"""
    policy_id: str = Field(..., description="Policy ID")
    policy_code: str = Field(..., description="Policy code")
    policy_name: str = Field(..., description="Policy name")
    policy_type: str = Field(..., description="Policy type")
    policy_version: str = Field(..., description="Policy version")
    description: Optional[str] = Field(None, description="Policy description")
    parameters: Optional[dict] = Field(None, description="Policy parameters")
    circuit_identifier: Optional[str] = Field(None, description="Circuit identifier")
    rules_document_url: Optional[str] = Field(None, description="URL to rules document")
    is_active: bool = Field(..., description="Whether the policy is active")
    enforcement_level: Optional[str] = Field(None, description="Enforcement level")
    reward_amount: Optional[Decimal] = Field(None, description="Reward amount")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class PolicyListResponse(BaseModel):
    """Response model for policy listing"""
    policies: List[PolicyResponse]
    total: int = Field(..., description="Total number of policies")


# Dispute Schemas
class DisputeLogRequest(BaseModel):
    """Request model for dispute logging"""
    claimant_agent_did: str = Field(..., description="Claimant agent DID")
    defendant_agent_did: str = Field(..., description="Defendant agent DID")
    avtp_transaction_id: Optional[str] = Field(None, description="Related AVTP transaction ID")
    reason_code: str = Field(..., description="Dispute reason code")
    brief_description: str = Field(..., description="Brief description of the dispute")
    evidence_pointer: Optional[str] = Field(None, description="Evidence location (e.g., IPFS CID)")
    # Enhanced fields
    dispute_reason_category: Optional[str] = Field(None, description="Category: UnfairFee, FailedService, ReputationAbuse, Other")
    related_transaction_id: Optional[str] = Field(None, description="Related TEG transaction ID")
    evidence_description_or_url: Optional[str] = Field(None, description="Evidence description or URL")


class DisputeLogResponse(BaseModel):
    """Response model for dispute logging"""
    dispute_log_id: str = Field(..., description="Unique dispute log identifier")
    status: str = Field(..., description="Dispute status")


class DisputeQueryResponse(BaseModel):
    """Response model for dispute query"""
    dispute_log_id: str = Field(..., description="Unique dispute log identifier")
    claimant_agent_did: str = Field(..., description="Claimant agent DID")
    defendant_agent_did: str = Field(..., description="Defendant agent DID")
    reason_code: str = Field(..., description="Dispute reason code")
    brief_description: str = Field(..., description="Brief description of the dispute")
    avtp_transaction_id: Optional[str] = Field(None, description="Related AVTP transaction ID")
    evidence_pointer: Optional[str] = Field(None, description="Evidence location")
    status: str = Field(..., description="Dispute status")
    resolution_notes: Optional[str] = Field(None, description="Resolution notes")
    # Enhanced fields
    dispute_reason_category: Optional[str] = Field(None, description="Dispute category")
    related_transaction_id: Optional[str] = Field(None, description="Related TEG transaction ID")
    evidence_description_or_url: Optional[str] = Field(None, description="Evidence description or URL")
    admin_reviewer_id: Optional[str] = Field(None, description="Admin who reviewed the dispute")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    class Config:
        from_attributes = True


class DisputeStatusUpdateRequest(BaseModel):
    """Request model for dispute status update"""
    new_status: str = Field(..., description="New dispute status")
    resolution_notes: Optional[str] = Field(None, description="Resolution notes")
    admin_reviewer_id: Optional[str] = Field(None, description="Admin reviewer ID")


class DisputeStatusUpdateResponse(BaseModel):
    """Response model for dispute status update"""
    dispute_log_id: str = Field(..., description="Unique dispute log identifier")
    old_status: str = Field(..., description="Previous status")
    new_status: str = Field(..., description="New status")
    resolution_notes: Optional[str] = Field(None, description="Resolution notes")
    updated_at: datetime = Field(..., description="Update timestamp")


class SystemMetricsResponse(BaseModel):
    """Response model for system metrics"""
    total_agents_with_balance: int = Field(..., description="Total number of agents with TEG balances")
    total_transactions: int = Field(..., description="Total number of TEG transactions processed")
    total_tokens_in_circulation: Decimal = Field(..., description="Total TEG tokens in circulation")
    total_fees_collected: Decimal = Field(..., description="Total fees collected by the system")
    system_fee_amount: Decimal = Field(..., description="Current system fee amount")
    fee_collection_address: str = Field(..., description="Current fee collection address")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


# Reputation Schemas
class AgentReputationResponse(BaseModel):
    """Response model for agent reputation"""
    agent_id: str = Field(..., description="Agent identifier")
    reputation_score: int = Field(..., description="Current reputation score")
    reputation_tier: str = Field(..., description="Reputation tier (BRONZE, SILVER, GOLD)")
    last_updated: Optional[datetime] = Field(None, description="Last update timestamp")
    attestation_factors: Optional[dict] = Field(None, description="Attestation-based reputation factors")


class ReputationSignalRequest(BaseModel):
    """Request model for applying reputation signal to a transaction"""
    signal_value: int = Field(..., description="Reputation signal value (+1 or -1)")
    
    @field_validator('signal_value')
    def validate_signal_value(cls, v):
        if v not in [-1, 1]:
            raise ValueError("Signal value must be +1 or -1")
        return v


class ReputationSignalResponse(BaseModel):
    """Response model for reputation signal"""
    transaction_id: str = Field(..., description="Transaction ID")
    sender_agent_id: str = Field(..., description="Sender agent ID")
    receiver_agent_id: str = Field(..., description="Receiver agent ID")
    signal_value: int = Field(..., description="Applied signal value")
    new_receiver_reputation: int = Field(..., description="Receiver's new reputation score")
    status: str = Field(..., description="Signal application status")


# Auditor Schemas
class AuditorFlagLogCreateSchema(BaseModel):
    """Schema for creating auditor flag log entries"""
    flagged_agent_did: str = Field(..., description="Agent DID being flagged")
    rule_violated_code: str = Field(..., description="Rule code violated")
    flag_reason: str = Field(..., description="Detailed reason for the flag")
    flag_type: str = Field(..., description="Flag type: HighVolumeVelocity, SuspiciousReputationActivity, AnomalousFeeCollection")
    severity: str = Field(..., description="Flag severity: LOW, MEDIUM, HIGH, CRITICAL")
    related_agent_id: Optional[str] = Field(None, description="Related agent DID")
    related_avtp_transaction_id: Optional[str] = Field(None, description="Related AVTP transaction")
    related_attestation_id: Optional[str] = Field(None, description="Related attestation")
    related_transaction_id: Optional[str] = Field(None, description="Related TEG transaction")
    details: Optional[str] = Field(None, description="Additional details (JSON or text)")
    status: str = Field(..., description="Flag status")
    flagged_by: str = Field(..., description="Who/what generated the flag")


class AuditorFlagCreateRequest(BaseModel):
    """Request model for creating an auditor flag"""
    flagged_agent_id: str = Field(..., description="Agent ID to flag")
    rule_code: str = Field(..., description="Rule code violated")
    severity: str = Field(..., description="Severity: low, medium, high")
    evidence: Optional[str] = Field(None, description="Evidence or details")


class AuditorFlagResponse(BaseModel):
    """Response model for auditor flag creation"""
    flag_id: str = Field(..., description="Created flag ID")
    status: str = Field(..., description="Creation status")
    severity: str = Field(..., description="Flag severity")


class AuditorFlagStatusUpdateRequest(BaseModel):
    """Request model for updating auditor flag status"""
    new_status: str = Field(..., description="New flag status: NEW, ACKNOWLEDGED, RESOLVED")
    resolution_notes: Optional[str] = Field(None, description="Resolution notes")


class AuditorFlagInfo(BaseModel):
    """Auditor flag information"""
    flag_id: str
    timestamp: datetime
    flagged_agent_did: str
    rule_violated_code: str
    flag_reason: str
    flag_type: Optional[str]
    severity: str
    related_agent_id: Optional[str]
    related_avtp_transaction_id: Optional[str]
    related_attestation_id: Optional[str]
    related_transaction_id: Optional[str]
    details: Optional[str]
    status: str
    flagged_by: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AuditorFlagsResponse(BaseModel):
    """Response model for auditor flags listing"""
    flags: List[AuditorFlagInfo]
    total: int = Field(..., description="Total number of flags")
    limit: int = Field(..., description="Number of flags returned")
    offset: int = Field(..., description="Offset for pagination")


# Auditor Admin Schemas
class AuditorFlagUpdateRequest(BaseModel):
    """Request model for updating auditor flag status"""
    new_status: str = Field(..., description="New flag status")
    admin_notes: Optional[str] = Field(None, description="Admin notes about the update")


class AuditorFlagUpdateResponse(BaseModel):
    """Response model for auditor flag update"""
    flag_id: str = Field(..., description="Flag ID")
    old_status: str = Field(..., description="Previous status")
    new_status: str = Field(..., description="New status")
    admin_notes: Optional[str] = Field(None, description="Admin notes")
    updated_at: datetime = Field(..., description="Update timestamp")


class AuditorFlagBulkUpdateRequest(BaseModel):
    """Request model for bulk flag updates"""
    flag_ids: List[str] = Field(..., description="List of flag IDs to update")
    new_status: str = Field(..., description="New status for all flags")
    admin_notes: Optional[str] = Field(None, description="Admin notes")


class AuditorFlagBulkUpdateResponse(BaseModel):
    """Response model for bulk flag updates"""
    total_updated: int = Field(..., description="Number of flags updated")
    status: str = Field(..., description="New status applied")
    admin_notes: Optional[str] = Field(None, description="Admin notes")


class AuditorFlagEscalateRequest(BaseModel):
    """Request model for escalating flag severity"""
    new_severity: str = Field(..., description="New severity level")
    escalation_reason: str = Field(..., description="Reason for escalation")


class AuditorFlagEscalateResponse(BaseModel):
    """Response model for flag escalation"""
    flag_id: str = Field(..., description="Flag ID")
    old_severity: str = Field(..., description="Previous severity")
    new_severity: str = Field(..., description="New severity")
    escalation_reason: str = Field(..., description="Escalation reason")
    updated_at: datetime = Field(..., description="Update timestamp")


class AgentSuspensionRequest(BaseModel):
    """Request model for agent suspension"""
    flag_id: Optional[str] = Field(None, description="Related flag ID")
    suspension_duration_hours: int = Field(..., description="Suspension duration in hours")
    suspension_reason: str = Field(..., description="Reason for suspension")


class AgentSuspensionResponse(BaseModel):
    """Response model for agent suspension"""
    agent_id: str = Field(..., description="Suspended agent ID")
    status: str = Field(..., description="Agent status")
    suspension_duration_hours: int = Field(..., description="Duration of suspension")
    suspension_reason: str = Field(..., description="Reason for suspension")
    suspended_until: datetime = Field(..., description="Suspension end time")


class AuditorRuleConfig(BaseModel):
    """Auditor rule configuration"""
    rule_code: str = Field(..., description="Rule code")
    description: str = Field(..., description="Rule description")
    enabled: bool = Field(..., description="Whether rule is enabled")
    thresholds: dict = Field(..., description="Rule thresholds")
    severity: str = Field(..., description="Default severity")


class AuditorRulesConfigResponse(BaseModel):
    """Response model for auditor rules configuration"""
    rules: List[AuditorRuleConfig] = Field(..., description="List of rule configurations")


class AuditorRuleUpdateRequest(BaseModel):
    """Request model for updating auditor rule configuration"""
    rule_code: str = Field(..., description="Rule code to update")
    thresholds: Optional[dict] = Field(None, description="New thresholds")
    enabled: Optional[bool] = Field(None, description="Enable/disable rule")
    disable_reason: Optional[str] = Field(None, description="Reason for disabling")


class AuditorMetricsResponse(BaseModel):
    """Response model for auditor performance metrics"""
    total_flags_created: int = Field(..., description="Total flags created")
    flags_by_severity: dict = Field(..., description="Flags breakdown by severity")
    flags_by_rule: dict = Field(..., description="Flags breakdown by rule")
    average_resolution_time_hours: float = Field(..., description="Average time to resolve flags")
    false_positive_rate: float = Field(..., description="False positive rate percentage")


# AVTP Schemas
class AVTPTransactionSummaryCreate(BaseModel):
    """Request model for AVTP transaction summary submission"""
    avtp_transaction_id: str = Field(..., description="Unique AVTP transaction identifier")
    timestamp: Optional[datetime] = Field(None, description="Transaction timestamp")
    agent_did: Optional[str] = Field(None, description="Agent DID (service provider) - defaults to responding_agent_did if not provided")
    initiating_agent_did: str = Field(..., description="DID of initiating agent")
    responding_agent_did: str = Field(..., description="DID of responding agent")
    service_identifier: Optional[str] = Field(None, description="Service identifier")
    price_avt: Optional[Decimal] = Field(None, description="Price in AVT")
    transaction_value: Optional[str] = Field(None, description="Transaction value as string")
    currency_type: Optional[str] = Field(None, description="Currency type (e.g., AVT, USD_SATS)")
    outcome_status: str = Field(..., description="Transaction outcome status")
    sla_identifier_referenced: Optional[str] = Field(None, description="SLA identifier")
    raw_log_pointer: Optional[str] = Field(None, description="Pointer to detailed log")
    
    @field_validator('outcome_status')
    def validate_outcome_status(cls, v):
        valid_statuses = ["SUCCESS", "FAILURE_PROVIDER", "FAILURE_CONSUMER", "FAILURE_PROTOCOL"]
        if v not in valid_statuses:
            raise ValueError(f"Invalid outcome_status. Must be one of: {', '.join(valid_statuses)}")
        return v
    
    @field_validator('initiating_agent_did', 'responding_agent_did', 'agent_did')
    def validate_agent_dids(cls, v, info):
        if v is None and info.field_name == 'agent_did':
            # agent_did is optional
            return v
        if not v:
            raise ValueError(f"{info.field_name} is required")
        # For MVP, accept simple agent IDs or DID format
        # Production would enforce stricter DID format
        return v.strip()


class AVTPTransactionSummaryResponse(BaseModel):
    """Response model for AVTP transaction summary submission"""
    log_id: str = Field(..., description="Unique log identifier")
    status: str = Field(..., description="Submission status")


# Treasury and Rewards Schemas
class TreasuryBalanceResponse(BaseModel):
    """Response model for treasury balance"""
    treasury_did: str = Field(..., description="Treasury DID")
    balance: Decimal = Field(..., description="Current treasury balance")
    last_updated: datetime = Field(..., description="Last update timestamp")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class RewardConfigResponse(BaseModel):
    """Response model for reward configuration"""
    attestation_submission_reward: Decimal = Field(..., description="Reward amount for attestation submission")
    associated_policy_id: Optional[str] = Field(None, description="Policy ID governing attestation rewards")
    proof_of_positive_balance_policy_id: Optional[str] = Field(None, description="Policy ID for proof of positive balance")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class RewardConfigUpdateRequest(BaseModel):
    """Request model for updating reward configuration"""
    attestation_submission_reward: Optional[Decimal] = Field(None, description="New reward amount")
    associated_policy_id: Optional[str] = Field(None, description="New policy ID for attestations")
    proof_of_positive_balance_policy_id: Optional[str] = Field(None, description="New policy ID for proof of positive balance")
    
    @field_validator('attestation_submission_reward')
    def validate_reward(cls, v):
        if v is not None and v < 0:
            raise ValueError("Reward amount must be non-negative")
        return v


# Agent Initialization Schemas
class AgentInitializationRequest(BaseModel):
    """Request model for TEG account initialization"""
    agent_id: str = Field(..., description="Agent DID to initialize (e.g., did:agentvault:email@example.com)")
    initial_balance: Optional[Decimal] = Field(Decimal("0"), description="Initial balance for the agent")
    initial_reputation_score: Optional[int] = Field(0, description="Initial reputation score")
    
    @field_validator('agent_id')
    def validate_agent_id(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("agent_id must be a non-empty string")
        return v
    
    @field_validator('initial_balance')
    def validate_balance(cls, v):
        if v is not None and v < 0:
            raise ValueError("Initial balance cannot be negative")
        return v
    
    @field_validator('initial_reputation_score')
    def validate_reputation(cls, v):
        if v is not None and v < 0:
            raise ValueError("Initial reputation score cannot be negative")
        return v
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class AgentInitializationResponse(BaseModel):
    """Response model for TEG account initialization"""
    agent_id: str = Field(..., description="Initialized agent DID")
    teg_account_status: str = Field(..., description="Status: 'created' or 'existing'")
    initial_balance: Decimal = Field(..., description="Agent's TEG balance")
    initial_reputation_score: int = Field(..., description="Agent's reputation score")
    initialized_at: datetime = Field(..., description="Account creation timestamp")
    message: str = Field(..., description="Status message")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


# Admin Dashboard Schemas
class AdminDashboardSummaryResponse(BaseModel):
    """Response model for admin dashboard summary statistics"""
    total_active_agents: int = Field(..., description="Count of agents with initialized TEG accounts")
    total_policies: dict = Field(..., description="Policy counts by status")
    open_disputes_count: int = Field(..., description="Number of unresolved disputes")
    new_auditor_flags_count: int = Field(..., description="New auditor flags in last 24h")
    total_rewards_distributed: Decimal = Field(..., description="Total rewards distributed in period")
    period: str = Field(..., description="Time period for statistics")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class AdminDashboardRecentActivityResponse(BaseModel):
    """Response model for admin dashboard recent activity"""
    recent_transactions: List[TransactionInfo] = Field(..., description="Recent transactions")
    recent_disputes: List[DisputeQueryResponse] = Field(..., description="Recent disputes")
    recent_auditor_flags: List[AuditorFlagInfo] = Field(..., description="Recent auditor flags")
    recent_attestations: List[AttestationSubmissionResponse] = Field(..., description="Recent attestations")
    cutoff_time: datetime = Field(..., description="Time cutoff for recent items")


# Onboarding Protocol Schemas
class BootstrapTokenRequest(BaseModel):
    """Request model for bootstrap token issuance"""
    agent_type_hint: Optional[str] = Field(
        None, 
        description="Hint for the type of agent being created (e.g., com.agentvault.research.v1)"
    )
    requested_by: Optional[str] = Field(
        None, 
        description="Identifier for the entity making the request (e.g., cli-user-rzj)"
    )


class BootstrapTokenResponse(BaseModel):
    """Response model for bootstrap token issuance"""
    bootstrap_token: str = Field(
        ..., 
        description="Single-use token for agent registration"
    )
    expires_in: int = Field(
        ..., 
        description="Token lifetime in seconds"
    )
    expires_at: datetime = Field(
        ..., 
        description="Absolute expiration timestamp"
    )


class JWKPublicKey(BaseModel):
    """JSON Web Key public key format"""
    kty: str = Field(..., description="Key type (e.g., OKP)")
    crv: str = Field(..., description="Curve name (e.g., Ed25519)")
    x: str = Field(..., description="X coordinate (base64url encoded)")


class AgentRegisterRequest(BaseModel):
    """Request model for agent registration"""
    agent_did_method: str = Field(
        ..., 
        description="Desired DID method (e.g., 'cos' for Concierge-OS native)"
    )
    public_key_jwk: Optional[JWKPublicKey] = Field(
        None, 
        description="Agent's public key in JSON Web Key format"
    )
    proof_of_work_solution: Optional[str] = Field(
        None, 
        description="Solution to PoW challenge for Sybil resistance"
    )


class AgentRegisterResponse(BaseModel):
    """Response model for agent registration"""
    agent_did: str = Field(
        ..., 
        description="Newly created permanent DID for the agent"
    )
    client_id: str = Field(
        ..., 
        description="OAuth client ID for API access"
    )
    client_secret: str = Field(
        ..., 
        description="OAuth client secret (shown only once)"
    )
    account_status: str = Field(
        ..., 
        description="Account status (e.g., 'active')"
    )
    initial_funding_status: str = Field(
        ..., 
        description="Status of initial token grant from faucet"
    )
    faucet_transaction_id: str = Field(
        ..., 
        description="Transaction ID for initial funding"
    )


# Staking and Delegation Schemas
class StakeCreateRequest(BaseModel):
    """Request model for staking AVT tokens"""
    amount: Decimal = Field(..., gt=0, description="Amount of AVT to stake")
    
    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Stake amount must be positive")
        if v.as_tuple().exponent < -18:
            raise ValueError("Amount has too many decimal places (max 18)")
        return v
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class StakeResponse(BaseModel):
    """Response model for stake information"""
    stake_id: str = Field(..., description="Unique stake identifier")
    agent_id: str = Field(..., description="Agent who owns the stake")
    amount: Decimal = Field(..., description="Staked amount")
    staked_at: datetime = Field(..., description="When the stake was created")
    unstaked_at: Optional[datetime] = Field(None, description="When the stake was unstaked")
    is_active: bool = Field(..., description="Whether the stake is currently active")
    last_reward_claim: Optional[datetime] = Field(None, description="Last reward claim timestamp")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class UnstakeRequest(BaseModel):
    """Request model for unstaking AVT tokens"""
    stake_id: str = Field(..., description="ID of the stake to unlock")


class UnstakeResponse(BaseModel):
    """Response model for unstake operation"""
    stake_id: str = Field(..., description="Unique stake identifier")
    amount_unstaked: Decimal = Field(..., description="Amount that was unstaked")
    total_returned: Decimal = Field(..., description="Total amount returned (stake + rewards)")
    unstaked_at: datetime = Field(..., description="When the unstake occurred")
    is_active: bool = Field(..., description="Stake active status (should be False)")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class MyStakesResponse(BaseModel):
    """Response model for agent's stakes"""
    agent_id: str = Field(..., description="Agent DID")
    total_staked: Decimal = Field(..., description="Total amount currently staked")
    stakes: List[StakeResponse] = Field(..., description="List of agent's stakes")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class DelegationCreateRequest(BaseModel):
    """Request model for creating a delegation"""
    stake_id: str = Field(..., description="ID of the stake to delegate")
    validator_agent_id: str = Field(..., description="Agent ID to delegate to")
    amount: Optional[Decimal] = Field(None, description="Amount to delegate (None = entire stake)")
    reward_share_percentage: Decimal = Field(
        default=Decimal("10.0"),
        ge=0,
        le=100,
        description="Percentage of rewards to share with validator (0-100)"
    )
    
    @field_validator('amount')
    def validate_amount(cls, v):
        if v is not None:
            if v <= 0:
                raise ValueError("Delegation amount must be positive")
            if v.as_tuple().exponent < -18:
                raise ValueError("Amount has too many decimal places (max 18)")
        return v
    
    @field_validator('reward_share_percentage')
    def validate_percentage(cls, v):
        if v < 0 or v > 100:
            raise ValueError("Reward share percentage must be between 0 and 100")
        return v
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class DelegationResponse(BaseModel):
    """Response model for delegation information"""
    delegation_id: str = Field(..., description="Unique delegation identifier")
    delegator_agent_id: str = Field(..., description="Agent who delegated")
    validator_agent_id: str = Field(..., description="Agent delegated to")
    stake_id: str = Field(..., description="Associated stake ID")
    delegated_amount: Decimal = Field(..., description="Amount delegated")
    delegation_start: datetime = Field(..., description="When delegation started")
    delegation_end: Optional[datetime] = Field(None, description="When delegation ended")
    is_active: bool = Field(..., description="Whether delegation is active")
    reward_share_percentage: Decimal = Field(..., description="Reward share percentage")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class StakingRewardCycleRequest(BaseModel):
    """Request model for triggering staking reward distribution"""
    reward_percentage: Decimal = Field(
        default=Decimal("5.0"),
        gt=0,
        le=100,
        description="Percentage of total stake to distribute as rewards (0-100)"
    )
    
    @field_validator('reward_percentage')
    def validate_percentage(cls, v):
        if v <= 0 or v > 100:
            raise ValueError("Reward percentage must be between 0 and 100")
        return v
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class StakingRewardCycleResponse(BaseModel):
    """Response model for staking reward distribution"""
    success: bool = Field(..., description="Whether the distribution succeeded")
    reward_percentage: Decimal = Field(..., description="Percentage distributed")
    stakers_rewarded: int = Field(..., description="Number of stakers who received rewards")
    total_distributed: Decimal = Field(..., description="Total amount distributed")
    timestamp: datetime = Field(..., description="When the distribution occurred")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class StakingSummaryResponse(BaseModel):
    """Response model for system-wide staking summary"""
    total_staked: Decimal = Field(..., description="Total AVT staked in the system")
    active_stakes_count: int = Field(..., description="Number of active stakes")
    unique_stakers: int = Field(..., description="Number of unique stakers")
    average_stake_size: Decimal = Field(..., description="Average stake size")
    recent_reward_distributions: List[dict] = Field(..., description="Recent reward distributions")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class AllStakesResponse(BaseModel):
    """Response model for listing all stakes (admin)"""
    total: int = Field(..., description="Total number of stakes")
    limit: int = Field(..., description="Results per page")
    offset: int = Field(..., description="Pagination offset")
    stakes: List[StakeResponse] = Field(..., description="List of stakes")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


# Admin Attestation Management Schemas
class PendingAttestationAgentInfo(BaseModel):
    """Agent information for pending attestation"""
    agent_did: str = Field(..., description="Agent DID")
    reputation_score: int = Field(..., description="Agent's current reputation score")
    token_balance: Decimal = Field(..., description="Agent's current token balance")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class PendingAttestationZKPDetails(BaseModel):
    """ZKP details for pending attestation"""
    circuit_id: Optional[str] = Field(None, description="ZKP circuit identifier")
    has_zkp: bool = Field(..., description="Whether attestation includes ZKP")
    zkp_verified: Optional[bool] = Field(None, description="ZKP verification result")


class PendingAttestationPolicyInfo(BaseModel):
    """Policy information for pending attestation"""
    policy_id: Optional[str] = Field(None, description="Associated policy ID")
    policy_name: Optional[str] = Field(None, description="Policy name")
    reward_amount: Optional[Decimal] = Field(None, description="Reward amount from policy")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class PendingAttestationInfo(BaseModel):
    """Detailed information about a pending attestation"""
    submission_id: str = Field(..., description="Unique submission identifier")
    agent_info: PendingAttestationAgentInfo = Field(..., description="Agent information")
    attestation_type: str = Field(..., description="Type of attestation")
    attestation_hash: str = Field(..., description="Hash of the attestation content")
    storage_pointer: str = Field(..., description="Storage location (e.g., IPFS CID)")
    submitted_at: datetime = Field(..., description="Submission timestamp")
    status: str = Field(..., description="Submission status")
    reward_issued: bool = Field(..., description="Whether reward has been issued")
    zkp_details: PendingAttestationZKPDetails = Field(..., description="ZKP details")
    policy_info: PendingAttestationPolicyInfo = Field(..., description="Policy information")


class PendingAttestationsResponse(BaseModel):
    """Response model for pending attestations listing"""
    total_count: int = Field(..., description="Total number of pending attestations")
    limit: int = Field(..., description="Number of results per page")
    offset: int = Field(..., description="Pagination offset")
    attestations: List[PendingAttestationInfo] = Field(..., description="List of pending attestations")


# Admin Attestation Verification
class AttestationVerificationRequest(BaseModel):
    """Request model for manual attestation verification"""
    status: str = Field(..., description="New status: zkp_verified_true, zkp_verified_false, basic_validated, rejected")


class AttestationVerificationResponse(BaseModel):
    """Response model for attestation verification"""
    submission_id: str = Field(..., description="Submission ID")
    old_status: str = Field(..., description="Previous status")
    new_status: str = Field(..., description="New status")
    reward_issued: bool = Field(..., description="Whether reward was issued")
    verified_by: str = Field(..., description="Who verified (admin)")
    verified_at: datetime = Field(..., description="Verification timestamp")


# Bulk Transfer Schemas (Phase 1 Scaling)
class BulkTransferItem(BaseModel):
    """A single transfer within a bulk transfer request."""
    sender_agent_id: str = Field(..., description="Sender agent DID")
    receiver_agent_id: str = Field(..., description="Receiver agent DID")
    amount: str = Field(..., description="Amount to transfer (as string for Decimal precision)")
    fee_amount: Optional[str] = Field("0", description="Pre-calculated fee amount")
    message: Optional[str] = Field(None, max_length=256, description="Optional message to attach")


class BulkTransferRequest(BaseModel):
    """Request model for bulk token transfers (server-to-server, admin-only)."""
    transfers: List[BulkTransferItem] = Field(..., description="List of transfers to process")


class BulkTransferResult(BaseModel):
    """Result of a single transfer within a bulk operation."""
    transaction_id: Optional[str] = Field(None, description="Transaction ID (None if failed)")
    status: str = Field(..., description="Transfer status: 'completed' or 'failed'")
    error: Optional[str] = Field(None, description="Error message if failed")
    sender_agent_id: str = Field(..., description="Sender agent DID")
    receiver_agent_id: str = Field(..., description="Receiver agent DID")
    amount: str = Field(..., description="Transfer amount")
    # 2026-05-01: enriched fields so registry's TEGBulkProxy can build a full
    # TEGTransferResponse without a follow-up /token/balance roundtrip.
    fee_amount: Optional[str] = Field(None, description="Fee charged (as string)")
    new_sender_balance: Optional[str] = Field(None, description="Sender balance after debit")
    timestamp: Optional[str] = Field(None, description="Commit timestamp (ISO 8601)")
    attached_message: Optional[str] = Field(None, description="Per-transfer message (echoed)")


class BulkTransferResponse(BaseModel):
    """Response model for bulk token transfers."""
    total: int = Field(..., description="Total number of transfers requested")
    succeeded: int = Field(..., description="Number of successful transfers")
    failed: int = Field(..., description="Number of failed transfers")
    results: List[BulkTransferResult] = Field(..., description="Per-transfer results")


# Test Faucet Schemas
class TestFaucetRequest(BaseModel):
    """Request model for test faucet funding"""
    agent_did: str = Field(..., description="Agent DID requesting test funds")
    
    @field_validator('agent_did')
    def validate_agent_did(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("agent_did must be a non-empty string")
        return v.strip()


class TestFaucetResponse(BaseModel):
    """Response model for test faucet funding"""
    transaction_id: str = Field(..., description="Transaction ID of the funding")
    agent_did: str = Field(..., description="Agent DID that received funds")
    amount: Decimal = Field(..., description="Amount of test tokens transferred")
    new_balance: Decimal = Field(..., description="Agent's new balance after funding")
    timestamp: datetime = Field(..., description="When the funding occurred")
    message: str = Field(..., description="Status message")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)
        }
