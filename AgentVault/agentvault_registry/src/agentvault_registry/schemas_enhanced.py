# Enhanced Schemas for Operation Beta Forge
# Add these to your schemas.py file or create schemas_enhanced.py

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from datetime import datetime

# --- Enhanced Staking Schemas ---

class StakeRequest(BaseModel):
    """Enhanced schema for requesting to stake tokens."""
    amount: Decimal = Field(..., gt=0, description="Amount of tokens to stake. Must be positive.")
    lock_period: int = Field(0, ge=0, le=365, description="Lock period in days (0 = flexible)")
    
    class Config:
        json_encoders = {
            Decimal: str
        }


class UnstakeRequest(BaseModel):
    """A request to release locked units."""
    amount: Decimal = Field(..., gt=0, description="Amount of units to release. Must be positive.")
    position_id: Optional[str] = Field(
        None,
        description=(
            "Release from this lock only (§FESUITE). Without it the amount comes from the unlocked positions, "
            "oldest first; with it a locked position is refused with its unlock date and no other position is touched."
        ),
    )
    
    class Config:
        json_encoders = {
            Decimal: str
        }


class StakeTransactionRead(BaseModel):
    """A lock or release transaction."""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    stake_id: Optional[str] = Field(None, description="Associated lock ID (for a release)")
    agent_did: str = Field(..., description="DID of the agent")
    amount: str = Field(..., description="Amount locked or released, as a string")
    transaction_type: str = Field(..., description="Type: 'stake' (a lock) or 'unstake' (a release)")
    timestamp: str = Field(..., description="ISO format timestamp")
    status: str = Field(..., description="Transaction status")
    new_staked_balance: str = Field(..., description="New locked balance after the transaction")
    new_liquid_balance: str = Field(..., description="New liquid balance after transaction")
    teg_transaction_id: Optional[str] = Field(None, description="TEG Layer transaction reference")
    
    class Config:
        from_attributes = True


class StakeBalanceResponse(BaseModel):
    """Enhanced schema for comprehensive balance information."""
    agent_did: str = Field(..., description="DID of the agent")
    liquid_balance: Decimal = Field(..., description="Available tokens in TEG Layer")
    staked_balance: Decimal = Field(..., description="Locked tokens")
    total_balance: Decimal = Field(..., description="Sum of liquid and locked")
    pending_rewards: Optional[Decimal] = Field(None, description="Unclaimed payouts on locked units")
    voting_power: Optional[Decimal] = Field(None, description="Current governance voting weight")
    active_stakes_count: Optional[int] = Field(None, description="Number of active locks")
    last_updated: datetime = Field(..., description="Timestamp of this data")
    warning: Optional[str] = Field(None, description="Any warnings about data staleness")
    
    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }


class StakeDetail(BaseModel):
    """One lock's details."""
    stake_id: str = Field(..., description="Unique lock identifier")
    amount: str = Field(..., description="Amount locked")
    staked_at: str = Field(..., description="ISO format timestamp when locked")
    days_staked: int = Field(..., description="Number of days since the lock began")
    can_unstake: bool = Field(..., description="Whether cooldown period has passed")
    cooldown_ends_at: Optional[str] = Field(None, description="When the lock can be released")


class StakingStatusResponse(BaseModel):
    """The detailed lock status."""
    system_status: Dict[str, Any] = Field(..., description="System-wide status and parameters")
    agent_status: Dict[str, Any] = Field(..., description="Agent-specific status")
    recent_activity: Dict[str, List[Dict[str, Any]]] = Field(..., description="Recent transactions")
    active_stakes_detail: List[StakeDetail] = Field(..., description="Details of the active locks")
    
    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }


# --- Governance Schemas (Strike Package 2) ---

class ProposalCreate(BaseModel):
    """Schema for creating a governance proposal."""
    title: str = Field(..., min_length=5, max_length=200, description="Proposal title")
    description: str = Field(..., min_length=20, max_length=5000, description="Detailed description")
    proposal_type: str = Field(..., max_length=50, description="Type: parameter_change, feature_request, etc")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Type-specific parameters")
    voting_period_days: int = Field(default=7, ge=1, le=30, description="Days for voting")

    @field_validator("title", "description")
    @classmethod
    def sanitize_text_fields(cls, v):
        from agentvault_registry.input_validators import validate_safe_text
        return validate_safe_text(v, "proposal field")


class ProposalRead(BaseModel):
    """Schema for reading governance proposal."""
    id: str = Field(..., description="Unique proposal identifier")
    proposer_id: str = Field(..., description="DID of proposer")
    title: str = Field(..., description="Proposal title")
    description: str = Field(..., description="Detailed description")
    proposal_type: str = Field(..., description="Type of proposal")
    status: str = Field(..., description="Status: active, passed, rejected")
    created_at: datetime = Field(..., description="Creation timestamp")
    voting_ends_at: datetime = Field(..., description="Voting deadline")
    votes_for: int = Field(..., description="Total voting power in favor")
    votes_against: int = Field(..., description="Total voting power against")
    participation_rate: Decimal = Field(..., description="Percentage of total stake voting")
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Decimal: str
        }


class VoteRequest(BaseModel):
    """Schema for casting a vote."""
    vote: bool = Field(..., description="True for YES, False for NO")
    reason: Optional[str] = Field(None, max_length=500, description="Optional voting rationale")


class VoteConfirmation(BaseModel):
    """Schema for vote confirmation."""
    proposal_id: str = Field(..., description="Proposal voted on")
    voter_did: str = Field(..., description="Voter's DID")
    vote: str = Field(..., description="YES or NO")
    voting_power: str = Field(..., description="Voting power used")
    timestamp: datetime = Field(..., description="When vote was cast")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ProposalTallyResponse(BaseModel):
    """Schema for proposal tally results."""
    proposal_id: str = Field(..., description="Proposal identifier")
    final_status: str = Field(..., description="Final status: passed or rejected")
    votes_for: str = Field(..., description="Total voting power in favor")
    votes_against: str = Field(..., description="Total voting power against")
    total_votes: str = Field(..., description="Total voting power used")
    participation_rate: str = Field(..., description="Percentage of total stake that voted")
    executed: bool = Field(..., description="Whether proposal changes were executed")
    execution_details: Optional[Dict[str, Any]] = Field(None, description="Details of execution")


# --- Dispute Schemas (Strike Package 3) ---

class DisputeCreate(BaseModel):
    """Schema for filing a dispute."""
    defendant_agent_id: str = Field(..., max_length=120, description="DID of accused agent")
    avtp_transaction_id: Optional[str] = Field(None, max_length=200, description="Related AVTP transaction")
    reason_code: str = Field(..., max_length=50, description="Standardized reason code")
    brief_description: str = Field(..., max_length=1000, description="Brief description")
    evidence_pointer: Optional[str] = Field(None, max_length=500, description="IPFS hash of evidence")

    @field_validator("defendant_agent_id")
    @classmethod
    def validate_did(cls, v):
        from agentvault_registry.input_validators import validate_did
        return validate_did(v)

    @field_validator("brief_description", "reason_code")
    @classmethod
    def sanitize_text_fields(cls, v):
        from agentvault_registry.input_validators import validate_safe_text
        return validate_safe_text(v, "dispute field")


class DisputeRead(BaseModel):
    """Schema for reading dispute details."""
    id: str = Field(..., description="Unique dispute identifier")
    claimant_id: str = Field(..., description="DID of claimant")
    defendant_id: str = Field(..., description="DID of defendant")
    status: str = Field(..., description="Status: open, resolved, dismissed")
    reason_code: str = Field(..., description="Reason code")
    brief_description: str = Field(..., description="Description")
    created_at: datetime = Field(..., description="When filed")
    resolution: Optional[Dict[str, Any]] = Field(None, description="Resolution details")
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class EvidenceSubmit(BaseModel):
    """Schema for submitting evidence."""
    evidence_type: str = Field(..., max_length=50, description="Type: document, log, screenshot, etc")
    content_hash: str = Field(..., max_length=200, description="IPFS hash of evidence")
    description: str = Field(..., max_length=500, description="Evidence description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v):
        from agentvault_registry.input_validators import validate_safe_text
        return validate_safe_text(v, "evidence description")


class ReputationSignalRequest(BaseModel):
    """Schema for reputation signal on transaction."""
    signal_value: int = Field(..., ge=-1, le=1, description="+1 or -1 signal")
    reason: Optional[str] = Field(None, max_length=200, description="Optional reason")


# --- System Intelligence Schemas (Strike Package 4) ---

class ActivityFeedEvent(BaseModel):
    """Schema for activity feed events."""
    event_id: str = Field(..., description="Unique event identifier")
    event_type: str = Field(..., description="Type of event")
    timestamp: datetime = Field(..., description="When event occurred")
    actor_did: Optional[str] = Field(None, description="Agent that triggered event")
    title: str = Field(..., description="Human-readable title")
    description: str = Field(..., description="Event details")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ActivityFeedResponse(BaseModel):
    """Schema for activity feed response."""
    events: List[ActivityFeedEvent] = Field(..., description="List of events")
    total_count: int = Field(..., description="Total events available")
    has_more: bool = Field(..., description="Whether more events exist")
    next_cursor: Optional[str] = Field(None, description="Cursor for pagination")


class TEGSummaryEnhanced(BaseModel):
    """Enhanced TEG summary with real data."""
    developer_id: int = Field(..., description="Developer ID")
    total_agents: int = Field(..., description="Number of agents")
    active_agents: int = Field(..., description="Active agents")
    total_liquid_balance: str = Field(..., description="Total liquid balance, in the frame's unit")
    total_staked_balance: str = Field(..., description="Total staked balance, in the frame's unit")
    total_balance: str = Field(..., description="Total balance, in the frame's unit")
    average_reputation: Decimal = Field(..., description="Average agent reputation")
    pending_rewards: str = Field(..., description="Unclaimed rewards")
    total_voting_power: str = Field(..., description="Combined voting power")
    recent_activity: List[Dict[str, Any]] = Field(..., description="Recent transactions")
    performance_metrics: Dict[str, Any] = Field(..., description="Performance data")
    
    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }
