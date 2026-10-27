"""Pydantic models for A2A Agent Cards — Q-C v1.0 native (BL-3, 2026-05-12).

Supports BOTH:
  - A2A v1.0 native fields (per spec §4.4 + §4.5):
        protocolVersion, supportedInterfaces[], securitySchemes{},
        security[], extensions[], capabilities.extendedAgentCard
  - A2A v0.3.0 fields (preserved for 6-month dual-shape transition per Q5):
        url, preferredTransport, authSchemes[], capabilities.a2aVersion

`model_config = ConfigDict(populate_by_name=True, extra="allow")` lets
federation peers include unknown fields (forward-compat to v1.1+ extensions)
without 422 rejection.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, HttpUrl, AnyUrl, ConfigDict, model_validator


# ─── Provider / Skill (unchanged from v0.3) ──────────────────────────────────


class AgentProvider(BaseModel):
    name: str
    url: Optional[HttpUrl] = None
    support_contact: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="allow")


# ─── v0.3 AuthScheme (kept for 6-mo transition) ──────────────────────────────


class AgentAuthentication(BaseModel):
    scheme: Literal['apiKey', 'bearer', 'oauth2', 'mtls', 'mutualTLS', 'none']
    description: Optional[str] = None
    token_url: Optional[HttpUrl] = Field(None, alias="tokenUrl")
    scopes: Optional[List[str]] = None
    service_identifier: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @model_validator(mode='after')
    def check_oauth2_fields(self) -> 'AgentAuthentication':
        if self.scheme == 'oauth2' and self.token_url is None:
            raise ValueError("'tokenUrl' is required when scheme is 'oauth2'")
        return self


# ─── A2A v1.0 §4.4.4 — SupportedInterface ────────────────────────────────────


class SupportedInterface(BaseModel):
    """A2A v1.0 §4.4.4 — a transport binding the agent exposes."""
    url: AnyUrl
    protocol_binding: str = Field("JSONRPC", alias="protocolBinding")
    protocol_version: str = Field("1.0", alias="protocolVersion")
    model_config = ConfigDict(populate_by_name=True, extra="allow")


# ─── A2A v1.0 §4.4.4 — AgentExtension ────────────────────────────────────────


class AgentExtension(BaseModel):
    """A2A v1.0 §4.4.4 — declares a supported/required extension on AgentCard."""
    uri: str
    description: Optional[str] = None
    required: bool = False
    params: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="allow")


# ─── TEE details + capabilities ──────────────────────────────────────────────


class TeeDetails(BaseModel):
    type: str
    attestation_endpoint: Optional[HttpUrl] = Field(None, alias="attestationEndpoint")
    public_key: Optional[str] = Field(None, alias="publicKey")
    description: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AgentCapabilities(BaseModel):
    """A2A v1.0 §4.4 capability declaration."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    streaming: bool = Field(..., description="SSE streaming support.")

    @model_validator(mode='before')
    @classmethod
    def backcompat_streaming_default(cls, data: Any) -> Any:
        if isinstance(data, dict) and 'streaming' not in data:
            data['streaming'] = False
        return data

    # v0.3 fields — kept for transition
    a2a_version: Optional[str] = Field(None, alias="a2aVersion")
    mcp_version: Optional[str] = Field(None, alias="mcpVersion")
    supported_message_parts: Optional[List[str]] = Field(None, alias="supportedMessageParts")
    tee_details: Optional[TeeDetails] = Field(None, alias="teeDetails")
    supports_push_notifications: Optional[bool] = Field(None, alias="supportsPushNotifications")
    state_transition_history: Optional[bool] = Field(None, alias="stateTransitionHistory")

    # A2A v1.0 §4.4 native fields
    push_notifications: Optional[bool] = Field(None, alias="pushNotifications")
    extended_agent_card: Optional[bool] = Field(None, alias="extendedAgentCard")


# ─── AgentCard — v1.0 native + v0.3 dual-shape ───────────────────────────────


class AgentCard(BaseModel):
    """A2A v1.0 AgentCard with v0.3 backwards-compat fields.

    During the 6-month Q-C transition (Commander Q5 signoff), both v1.0 fields
    (``supportedInterfaces`` / ``securitySchemes`` / ``security`` / ``extensions``)
    and v0.3 fields (``url`` / ``preferredTransport`` / ``authSchemes``) MAY
    coexist on a card. The backend canonicalizer
    (``agentvault_registry.services.a2a_v1.compat``) ensures both shapes are
    written on every create/update.

    ``extra="allow"`` preserves unknown fields (forward-compat to v1.1+
    extensions + federation peers that publish proprietary metadata).
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # ─── Core identity ───────────────────────────────────────────────────────
    protocol_version: str = Field(..., alias="protocolVersion")

    @model_validator(mode='before')
    @classmethod
    def backcompat_schema_version(cls, data: Any) -> Any:
        """Accept legacy ``schemaVersion`` as alias for ``protocolVersion``."""
        if isinstance(data, dict) and 'schemaVersion' in data and 'protocolVersion' not in data:
            data['protocolVersion'] = data.pop('schemaVersion')
        return data

    human_readable_id: str = Field(..., alias="humanReadableId")
    agent_version: str = Field(..., alias="agentVersion")
    name: str
    description: str

    # ─── v0.3 transport fields (preserved for 6-mo transition) ──────────────
    url: Optional[AnyUrl] = Field(None, description="v0.3 primary endpoint URL (alongside v1.0 supportedInterfaces).")
    preferred_transport: Optional[str] = Field(None, alias="preferredTransport")
    auth_schemes: Optional[List[AgentAuthentication]] = Field(None, alias="authSchemes", description="v0.3 auth schemes; v1.0 cards use securitySchemes + security instead.")

    # ─── A2A v1.0 §4.4 + §4.5 native fields ─────────────────────────────────
    supported_interfaces: Optional[List[SupportedInterface]] = Field(None, alias="supportedInterfaces", description="A2A v1.0 §4.4.4 — transport bindings declared by the agent.")
    security_schemes: Optional[Dict[str, Any]] = Field(None, alias="securitySchemes", description="A2A v1.0 §4.5 — named security scheme map (APIKey/HTTPAuth/OAuth2/OpenIdConnect/MutualTLS).")
    security: Optional[List[Dict[str, List[str]]]] = Field(None, description="A2A v1.0 §4.5 — list of {scheme_name: scopes[]} requirement maps.")
    extensions: Optional[List[AgentExtension]] = Field(None, description="A2A v1.0 §4.4.4 — agent-declared extensions.")

    # ─── Provider + capabilities (unchanged) ────────────────────────────────
    provider: AgentProvider
    capabilities: AgentCapabilities

    # ─── Optional metadata ──────────────────────────────────────────────────
    skills: Optional[List[AgentSkill]] = None
    tags: Optional[List[str]] = None
    privacy_policy_url: Optional[HttpUrl] = Field(None, alias="privacyPolicyUrl")
    terms_of_service_url: Optional[HttpUrl] = Field(None, alias="termsOfServiceUrl")
    icon_url: Optional[HttpUrl] = Field(None, alias="iconUrl")
    last_updated: Optional[str] = Field(None, alias="lastUpdated")

    # ─── Dual-shape sanity check ────────────────────────────────────────────
    @model_validator(mode='after')
    def at_least_one_endpoint_or_interface(self) -> 'AgentCard':
        """A card must declare AT LEAST one endpoint — either v0.3 ``url`` OR
        v1.0 ``supportedInterfaces[]`` non-empty. Both is fine (dual-shape)."""
        if not self.url and not self.supported_interfaces:
            raise ValueError("Agent card must declare at least one endpoint via `url` (v0.3) or `supportedInterfaces[]` (v1.0).")
        return self

    @model_validator(mode='after')
    def at_least_one_auth_surface(self) -> 'AgentCard':
        """A card must declare AT LEAST one auth surface — v0.3 ``authSchemes`` OR
        v1.0 ``securitySchemes`` + ``security`` (empty list = no auth required,
        which IS a valid auth surface declaration)."""
        v03_present = bool(self.auth_schemes)
        v1_present = self.security_schemes is not None and self.security is not None
        if not v03_present and not v1_present:
            raise ValueError("Agent card must declare auth via `authSchemes` (v0.3) or `securitySchemes`+`security` (v1.0).")
        return self
