from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from uuid import uuid4

class Event(BaseModel):
    """Base event model"""
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})
    
    id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    aggregate_id: str
    aggregate_type: str = "Agent"
    data: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    source_service: str
    # TITANIUM VAULT D1: Idempotency key for exactly-once delivery
    idempotency_key: Optional[str] = None
    # 2026-05-02 (Round 4): monotonic INSERT-time cursor for SF-4 replication.
    # Set by DB sequence; clients omit on submission.
    seq: Optional[int] = None

# Economic Events
class TokensIssuedEvent(Event):
    event_type: str = "TokensIssued"

class TokensTransferredEvent(Event):
    event_type: str = "TokensTransferred"

class TokensStakedEvent(Event):
    event_type: str = "TokensStaked"

class TokensUnstakedEvent(Event):
    event_type: str = "TokensUnstaked"

# Agent Events
class AgentCreatedEvent(Event):
    event_type: str = "AgentCreated"

class AgentUpdatedEvent(Event):
    event_type: str = "AgentUpdated"

# Attestation Events
class AttestationSubmittedEvent(Event):
    event_type: str = "AttestationSubmitted"

# Reputation Events
class ReputationChangedEvent(Event):
    event_type: str = "ReputationChanged"