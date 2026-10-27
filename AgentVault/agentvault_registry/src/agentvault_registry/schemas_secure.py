"""
Data schemas for AgentVault Registry API
Includes all request/response models with comprehensive validation
"""

import uuid
import datetime
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict, EmailStr, SecretStr, model_validator

# --- Developer Schemas ---

class DeveloperCreate(BaseModel):
    """Schema for creating a new developer."""
    name: str = Field(..., min_length=3, max_length=100, description="Unique name for the developer.")
    email: EmailStr = Field(..., description="Developer's email address.")
    password: SecretStr = Field(..., min_length=12, description="Developer's chosen password (min 12 chars).")

class DeveloperRead(BaseModel):
    """Schema for reading developer information."""
    id: int
    name: str
    email: EmailStr = Field(..., description="Developer's email address.")
    created_at: datetime.datetime
    is_verified: bool = Field(..., description="Indicates if the developer is verified.")

    model_config = ConfigDict(from_attributes=True)

# --- Auth Related Schemas ---

class Token(BaseModel):
    """Schema for access token response."""
    access_token: str
    token_type: Literal["bearer"] = "bearer"

class RegistrationResponse(BaseModel):
    """Schema for the response after successful registration."""
    message: str
    recovery_keys: List[str] = Field(..., description="Generated recovery keys. Store these securely!")

class PasswordResetRequest(BaseModel):
    """Schema for requesting a password reset email."""
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    """Schema for confirming password reset using a token."""
    token: str = Field(..., description="The password reset token received via email.")
    new_password: SecretStr = Field(..., min_length=12, description="The new password for the account.")

class PasswordResetRecover(BaseModel):
    """Schema for initiating password reset using a recovery key."""
    email: EmailStr = Field(..., description="The email address associated with the account.")
    recovery_key: str = Field(..., description="One of the recovery keys provided during registration.")

class PasswordSetNew(BaseModel):
    """Schema for setting a new password after recovery key validation."""
    new_password: SecretStr = Field(..., min_length=12, description="The new password for the account.")

# --- API Key Schemas (Updated) ---

class APIKeyInfo(BaseModel):
    """Schema for API key information (without the actual key)."""
    id: str = Field(..., description="Unique identifier for the API key.")
    key_name: str = Field(..., description="User-friendly name for the API key.")
    key_prefix: str = Field(..., description="Public prefix of the API key (e.g., 'av_xxx...').")
    created_at: datetime.datetime
    last_used_at: Optional[datetime.datetime] = None
    expires_at: Optional[datetime.datetime] = None
    is_active: bool = Field(default=True, description="Whether the key is active.")
    scopes: List[str] = Field(default_factory=list, description="Permission scopes for this key.")

    model_config = ConfigDict(from_attributes=True)

class APIKeyResponse(BaseModel):
    """Response when creating a new API key."""
    key_name: str
    api_key: str = Field(..., description="The complete API key. Store securely - cannot be retrieved again.")
    key_prefix: str = Field(..., description="Public prefix for identifying this key.")
    created_at: datetime.datetime
    expires_at: Optional[datetime.datetime] = None
    message: str = Field(default="Store this API key securely. It will not be shown again.")

class ApiKeyRead(BaseModel):
    """Legacy schema - use APIKeyInfo instead."""
    id: int
    key_prefix: str = Field(..., description="The non-secret prefix of the API key.")
    description: Optional[str] = Field(None, description="User-provided description for the key.")
    is_active: bool = Field(..., description="Whether the API key is currently active.")
    created_at: datetime.datetime = Field(..., description="Timestamp when the key was created.")
    last_used_at: Optional[datetime.datetime] = Field(None, description="Timestamp when the key was last used.")

    model_config = ConfigDict(from_attributes=True)

class NewApiKeyResponse(BaseModel):
    """Legacy schema - use APIKeyResponse instead."""
    plain_api_key: str = Field(..., description="The full API key.")
    api_key_info: ApiKeyRead = Field(..., description="Metadata about the newly created key.")

# --- Agent Card Schemas ---

class AgentCardBase(BaseModel):
    """Base schema for Agent Card containing common fields."""
    name: str = Field(..., description="Human-readable display name of the agent.")
    description: Optional[str] = Field(None, description="Detailed description of the agent's purpose and functionality.")
    is_active: bool = Field(True, description="Whether the agent card is active and discoverable.")

class AgentCardCreate(BaseModel):
    """Schema for creating a new Agent Card via the API."""
    card_data: Dict[str, Any] = Field(
        ...,
        description="The full Agent Card JSON object conforming to the A2A Agent Card schema."
    )

class AgentCardUpdate(BaseModel):
    """Schema for updating an existing Agent Card via the API."""
    card_data: Optional[Dict[str, Any]] = Field(
        None,
        description="The full Agent Card JSON object conforming to the A2A Agent Card schema."
    )
    is_active: Optional[bool] = Field(
        None,
        description="Set the active status of the agent card."
    )

class AgentCardRead(AgentCardBase):
    """Schema for representing a full Agent Card read from the database."""
    id: uuid.UUID = Field(..., description="Unique identifier for the Agent Card record.")
    developer_id: int = Field(..., description="ID of the developer who owns this card.")
    developer_is_verified: bool = Field(..., description="Indicates if the developer owning this card is verified.")
    card_data: Dict[str, Any] = Field(..., description="The full Agent Card JSON object.")
    created_at: datetime.datetime = Field(..., description="Timestamp when the card was created.")
    updated_at: datetime.datetime = Field(..., description="Timestamp when the card was last updated.")

    model_config = ConfigDict(from_attributes=True)

class AgentCardSummary(BaseModel):
    """Schema for representing a summarized Agent Card in list responses."""
    id: uuid.UUID = Field(..., description="Unique identifier for the Agent Card record.")
    name: str = Field(..., description="Human-readable display name of the agent.")
    description: Optional[str] = Field(None, description="Detailed description of the agent's purpose.")

    model_config = ConfigDict(from_attributes=True)

# --- Pagination Schemas ---

class PaginationInfo(BaseModel):
    """Schema for pagination details in list responses."""
    total_items: int = Field(..., description="Total number of items available.")
    limit: int = Field(..., description="Number of items requested per page.")
    offset: int = Field(..., description="Offset of the current page.")
    total_pages: int = Field(..., description="Total number of pages available.")
    current_page: int = Field(..., description="The current page number (1-based).")

# --- List Response Schemas ---

class AgentCardListResponse(BaseModel):
    """Schema for the response when listing Agent Cards."""
    items: List[AgentCardSummary] = Field(..., description="List of agent card summaries for the current page.")
    pagination: PaginationInfo = Field(..., description="Pagination details.")

# --- Validation Schemas ---

class AgentCardValidationRequest(BaseModel):
    """Schema for requesting validation of Agent Card data."""
    card_data: Dict[str, Any] = Field(
        ...,
        description="The Agent Card JSON object to validate."
    )

class AgentCardValidationResponse(BaseModel):
    """Schema for the response of an Agent Card validation request."""
    is_valid: bool = Field(..., description="Indicates whether the provided card data is valid according to the schema.")
    detail: Optional[str] = Field(None, description="Provides details about validation errors if is_valid is False.")
    validated_card_data: Optional[Dict[str, Any]] = Field(None, description="The validated and potentially normalized card data if is_valid is True.")

# --- Agent Builder Config Schema ---

class AgentBuildConfig(BaseModel):
    """Schema for receiving configuration for the Agent Builder UI."""
    agent_name: str = Field(..., min_length=3, max_length=100, description="Display name for the new agent.")
    agent_description: str = Field(..., max_length=500, description="Description for the new agent.")
    human_readable_id: Optional[str] = Field(
        None,
        pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*\/[a-z0-9]+(?:[-_][a-z0-9]+)*$",
        description="Optional unique ID (e.g., 'my-org/my-agent'). Auto-generated if omitted."
    )
    agent_builder_type: Literal["simple_wrapper", "adk_agent"] = Field(
        ...,
        description="Specifies which type of agent structure to generate."
    )

    # Simple Wrapper Specific Fields
    wrapper_llm_backend_type: Optional[Literal["openai_api", "anthropic_api", "local_openai_compatible"]] = Field(
        None,
        description="Required if agent_builder_type is 'simple_wrapper'. The backend LLM API type."
    )
    wrapper_model_name: Optional[str] = Field(
        None,
        description="Required if agent_builder_type is 'simple_wrapper'. Model name for the backend."
    )
    wrapper_system_prompt: Optional[str] = Field(
        None,
        description="Optional system prompt for the simple wrapper agent."
    )

    # ADK Agent Specific Fields
    adk_model_name: Optional[str] = Field(
        None,
        description="Required if agent_builder_type is 'adk_agent'. Model name for ADK LlmAgent."
    )
    adk_instruction: Optional[str] = Field(
        None,
        description="Required if agent_builder_type is 'adk_agent'. System prompt/instructions for the ADK LlmAgent."
    )
    adk_tools: Optional[List[Literal["get_current_time", "google_search"]]] = Field(
        None,
        description="Optional list of pre-defined tools for the ADK agent."
    )

    # Generated Agent's Own Authentication
    wrapper_auth_type: Literal["none", "apiKey"] = Field(
        default="none",
        description="Authentication required for the generated agent's A2A endpoint."
    )
    wrapper_service_id: Optional[str] = Field(
        None,
        description="Required if wrapper_auth_type is 'apiKey'. Service ID for the generated agent's API key."
    )

    @model_validator(mode='after')
    def check_conditional_fields(self) -> 'AgentBuildConfig':
        """Validate conditional field requirements based on agent type."""
        if self.agent_builder_type == "simple_wrapper":
            if not self.wrapper_llm_backend_type:
                raise ValueError("'wrapper_llm_backend_type' is required when agent_builder_type is 'simple_wrapper'")
            if not self.wrapper_model_name:
                raise ValueError("'wrapper_model_name' is required when agent_builder_type is 'simple_wrapper'")
        elif self.agent_builder_type == "adk_agent":
            if not self.adk_model_name:
                raise ValueError("'adk_model_name' is required when agent_builder_type is 'adk_agent'")
            if not self.adk_instruction:
                raise ValueError("'adk_instruction' is required when agent_builder_type is 'adk_agent'")

        if self.wrapper_auth_type == "apiKey" and not self.wrapper_service_id:
            raise ValueError("'wrapper_service_id' is required when wrapper_auth_type is 'apiKey'")

        return self

# --- Health Check Schemas ---

class HealthCheckResponse(BaseModel):
    """Response for health check endpoint."""
    status: Literal["healthy", "degraded", "unhealthy"]
    environment: str
    version: str
    checks: Dict[str, str] = Field(..., description="Status of individual components")
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
