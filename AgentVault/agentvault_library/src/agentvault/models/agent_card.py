"""
Pydantic models representing the structure of an A2A Agent Card.

Aligned with A2A Protocol v0.3.0 (stable) / Draft v1.0.
OWL22 A2A Alignment Audit — 2026-02-23.
"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator, AnyUrl, ConfigDict


# Note: Using standard Python types and Pydantic types.
# Field aliases can be used if the JSON field names differ from Pythonic names.

class AgentProvider(BaseModel):
    """Information about the provider or developer of the agent."""
    name: str = Field(..., description="Name of the agent provider or developer.")
    url: Optional[HttpUrl] = Field(None, description="Homepage URL of the provider.")
    support_contact: Optional[str] = Field(None, description="Contact information for support (e.g., email or URL).")
    # Add other relevant provider fields as needed (e.g., legal info URL)

class AgentSkill(BaseModel):
    """Describes a specific skill or capability of the agent."""
    id: str = Field(..., description="Unique identifier for the skill within the agent's context.")
    name: str = Field(..., description="Human-readable name of the skill.")
    description: str = Field(..., description="Detailed description of what the skill does.")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema describing the expected input format for this skill (if applicable).")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema describing the output format produced by this skill (if applicable).")
    # §CALLFORMAT 2026-08-27 — THE CONVENTION FOR "how do I phrase this call?".
    # `examples` is the A2A-standard field for exactly that, and it was being
    # SILENTLY DROPPED on write: a card could declare examples, the PUT returned
    # 200, and they were gone. So no agent could tell a caller how to talk to it,
    # and /call had nothing to suggest but a guess.
    #
    # A schema is where a convention becomes real: adding it here means every
    # FUTURE agent gets this by publishing a conformant card, with no registry
    # change and nothing to remember.
    examples: Optional[List[str]] = Field(None, description="Example inputs a caller can send to this skill, in the caller's own words (A2A `examples`). Each one SHOULD actually work.")
    tags: Optional[List[str]] = Field(None, description="Short tags categorising the skill (A2A `tags`).")

class AgentAuthentication(BaseModel):
    """Describes an authentication scheme supported by the agent's A2A endpoint."""
    # --- Q-C W6 (2026-05-12): added 'mtls'/'mutualTLS' for IRONHAND ───────────
    scheme: Literal['apiKey', 'bearer', 'oauth2', 'mtls', 'mutualTLS', 'none'] = Field(..., description="The type of authentication scheme required ('apiKey', 'oauth2' Client Credentials, 'bearer', 'mtls'/'mutualTLS', or 'none').")
    description: Optional[str] = Field(None, description="Human-readable description of how to obtain and use credentials for this scheme.")
    token_url: Optional[HttpUrl] = Field(None, alias="tokenUrl", description="URL of the OAuth 2.0 token endpoint (required for 'oauth2' scheme).")
    scopes: Optional[List[str]] = Field(None, description="List of OAuth 2.0 scope identifiers required by the agent (for 'oauth2' scheme).")
    # --- END MODIFIED ---
    service_identifier: Optional[str] = Field(None, description="Optional identifier used by the client's KeyManager to retrieve the correct local key (e.g., 'openai', 'agent-specific-id'). If omitted, might default to agent's humanReadableId or require explicit client configuration.")

    @model_validator(mode='after')
    def check_oauth2_fields(self) -> 'AgentAuthentication':
        """Ensure tokenUrl is provided if scheme is oauth2."""
        if self.scheme == 'oauth2' and self.token_url is None:
             raise ValueError("'tokenUrl' is required when scheme is 'oauth2'")
        return self


class TeeDetails(BaseModel):
    """Details about the Trusted Execution Environment (TEE) an agent utilizes."""
    type: str = Field(..., description="Identifier for the type of TEE technology used (e.g., 'Intel SGX', 'AMD SEV', 'AWS Nitro Enclaves').")
    attestation_endpoint: Optional[HttpUrl] = Field(None, alias="attestationEndpoint", description="URL where clients can obtain or verify attestation documents for the TEE instance.")
    public_key: Optional[str] = Field(None, alias="publicKey", description="Public key associated with the TEE instance, potentially used for secure communication or verifying attestations (format depends on TEE type).")
    description: Optional[str] = Field(None, description="Human-readable description of the TEE setup or guarantees.")


def _check_endpoint_scheme(v: Any, what: str) -> Any:
    """ONE rule for BOTH legal places a card declares its endpoint (the v0.3 `url` and the v1.0
    `supportedInterfaces[].url`): https, or http to localhost itself, or plain http on a sandbox registry.

    §SSRFGUARD (2026-09-16): a hostname check, not a text prefix. `http://localhost.attacker.example` is a public host
    and used to inherit localhost's exemption (reported 2026-09-12).
    §TWOAGENT #12 (2026-09-23): the rule guarded `url` only, so an A2A v1.0 card declared an http endpoint on any host
    through `supportedInterfaces[]` while the same URL in `url` was refused. And the refusal now says where http is
    accepted, instead of leaving the sandbox exemption to be discovered.
    """
    if v is None:
        return v
    url_str = str(v)
    from urllib.parse import urlparse as _urlparse
    try:
        _host = (_urlparse(url_str).hostname or '').lower()
    except Exception:
        _host = ''
    if url_str.startswith('https://') or (
        url_str.startswith('http://') and _host in ('localhost', '127.0.0.1', '::1')
    ):
        return v
    import os as _os
    _sandbox = (
        (_os.getenv('SANDBOX_MODE') or '').lower() in ('1', 'true', 'yes')
        or (_os.getenv('CC_TARGET_ENVIRONMENT') or '').lower() == 'sandbox'
    )
    if _sandbox and url_str.startswith('http://'):
        return v
    raise ValueError(f'{what} must use HTTPS unless it is localhost (a registry accepts plain http:// '
                     f'only in sandbox mode)')


class SupportedInterface(BaseModel):
    """A2A v1.0 §4.4.4 — a transport binding the agent exposes.

    Q-C W6 (2026-05-12).
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    url: AnyUrl = Field(..., description="Endpoint URL for this interface.")
    protocol_binding: str = Field("JSONRPC", alias="protocolBinding", description="Transport binding (JSONRPC, gRPC, REST, etc.).")
    protocol_version: str = Field("1.0", alias="protocolVersion", description="A2A protocol version for this interface.")

    @field_validator('url')
    @classmethod
    def check_interface_url_scheme(cls, v: AnyUrl) -> AnyUrl:
        return _check_endpoint_scheme(v, 'Interface URL')


class AgentExtension(BaseModel):
    """A2A v1.0 §4.4.4 — declares a supported/required extension on AgentCard.

    Q-C W6 (2026-05-12).
    """
    model_config = ConfigDict(extra="allow")
    uri: str = Field(..., description="Canonical extension URI (e.g. https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed).")
    description: Optional[str] = None
    required: bool = False
    params: Optional[Dict[str, Any]] = None


class AgentCapabilities(BaseModel):
    """Defines the overall capabilities and supported protocols."""
    # Q-C W6 (2026-05-12): extra="allow" for forward compat with v1.1+ fields.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # --- P0-2 FIX (OWL22): Added 'streaming' — REQUIRED by A2A v0.3.0 spec ---
    streaming: bool = Field(..., description="Indicates if the agent supports Server-Sent Events (SSE) via the message/stream JSON-RPC method. REQUIRED by A2A v0.3.0.")
    # --- END P0-2 FIX ---

    @model_validator(mode='before')
    @classmethod
    def backcompat_streaming_default(cls, data: Any) -> Any:
        """Backward compat: default streaming=False for legacy cards missing the field."""
        if isinstance(data, dict) and 'streaming' not in data:
            data['streaming'] = False
        return data
    a2a_version: Optional[str] = Field(None, alias="a2aVersion", description="Legacy: Version of the A2A protocol supported. Redundant with root protocolVersion in v1.0, kept for backward compat.")
    mcp_version: Optional[str] = Field(None, alias="mcpVersion", description="Version of the Model Context Protocol supported (if any).")
    supported_message_parts: Optional[List[str]] = Field(None, alias="supportedMessageParts", description="List of message part types supported (e.g., 'text', 'file', 'data'). If omitted, client may assume basic types.")
    tee_details: Optional[TeeDetails] = Field(None, alias="teeDetails", description="Details about the Trusted Execution Environment the agent runs in, if applicable.")
    supports_push_notifications: Optional[bool] = Field(None, alias="supportsPushNotifications", description="Indicates if the agent supports sending push notifications to a webhook specified by the client during task initiation.")
    state_transition_history: Optional[bool] = Field(None, alias="stateTransitionHistory", description="Indicates if the agent retains and exposes historic state transition logs for auditing.")

    # --- Q-C W6 (2026-05-12): A2A v1.0 §4.4 native field names ───────────
    push_notifications: Optional[bool] = Field(None, alias="pushNotifications", description="A2A v1.0 §4.4 — push notification support (renamed from supportsPushNotifications).")
    extended_agent_card: Optional[bool] = Field(None, alias="extendedAgentCard", description="A2A v1.0 §4.4 — agent supports an extended (authenticated) variant of its card.")


class AgentCard(BaseModel):
    """
    Represents the A2A Agent Card, providing metadata about a remote agent.
    Aligned with A2A v0.3.0 + A2A v1.0 (dual-shape per Q-C W6 / Commander Q5).

    During the 6-month Q-C transition, cards may carry BOTH v0.3 fields
    (``url`` / ``preferredTransport`` / ``authSchemes``) and v1.0 fields
    (``supportedInterfaces`` / ``securitySchemes`` / ``security`` /
    ``extensions``). The backend canonicalizer
    (``agentvault_registry.services.a2a_v1.compat.canonicalize_card_data``)
    fills in derived v1.0 fields on every write.

    ``extra="allow"`` lets unknown fields pass through (forward-compat to
    v1.1+ extensions + federation peer metadata).
    """
    # Q-C W6 (2026-05-12): extra="allow" so v1.0 fields + federation
    # metadata survive Pydantic round-trip.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # --- P0-1 FIX (OWL22): Renamed schemaVersion → protocolVersion per A2A v0.3.0 spec ---
    protocol_version: str = Field(..., alias="protocolVersion", description="The A2A protocol version supported by the agent (e.g., '0.3.0', '1.0'). Replaces legacy 'schemaVersion'.")
    # --- END P0-1 FIX ---

    @model_validator(mode='before')
    @classmethod
    def backcompat_schema_version(cls, data: Any) -> Any:
        """Backward compat: accept legacy 'schemaVersion' and map to 'protocolVersion'."""
        if isinstance(data, dict):
            if 'schemaVersion' in data and 'protocolVersion' not in data:
                data['protocolVersion'] = data.pop('schemaVersion')
        return data
    human_readable_id: str = Field(..., alias="humanReadableId", description="A user-friendly, unique identifier for the agent (e.g., 'my-org/weather-reporter'). Often used for discovery and key management.")
    agent_version: str = Field(..., alias="agentVersion", description="Version string of the agent software itself.")
    name: str = Field(..., description="Human-readable display name of the agent.")
    description: str = Field(..., description="Detailed description of the agent's purpose and functionality.")

    # --- v0.3 transport fields (now optional; v1.0 supportedInterfaces may take their place) ---
    url: Optional[AnyUrl] = Field(None, description="v0.3 primary A2A endpoint URL. Optional under v1.0 (use supportedInterfaces[]). Kept for 6-mo dual-shape transition.")
    preferred_transport: Optional[str] = Field(None, alias="preferredTransport", description="v0.3 transport hint (e.g. JSONRPC). Optional under v1.0 (carried in supportedInterfaces[].protocolBinding).")

    provider: AgentProvider = Field(..., description="Information about the agent's provider.")
    capabilities: AgentCapabilities = Field(..., description="Defines the agent's protocol capabilities.")

    # --- v0.3 authSchemes (now optional; v1.0 securitySchemes + security may take its place) ---
    auth_schemes: Optional[List[AgentAuthentication]] = Field(None, alias="authSchemes", description="v0.3 authentication schemes. Optional under v1.0 (use securitySchemes + security). Kept for 6-mo transition.")

    # --- Q-C W6 (2026-05-12): A2A v1.0 §4.4 + §4.5 native fields ───────────
    supported_interfaces: Optional[List[SupportedInterface]] = Field(None, alias="supportedInterfaces", description="A2A v1.0 §4.4.4 — transport bindings declared by the agent.")
    security_schemes: Optional[Dict[str, Any]] = Field(None, alias="securitySchemes", description="A2A v1.0 §4.5 — named security scheme map (APIKey/HTTPAuth/OAuth2/OpenIdConnect/MutualTLS).")
    security: Optional[List[Dict[str, List[str]]]] = Field(None, description="A2A v1.0 §4.5 — list of {scheme_name: scopes[]} requirement maps.")
    extensions: Optional[List[AgentExtension]] = Field(None, description="A2A v1.0 §4.4.4 — agent-declared extensions.")

    skills: Optional[List[AgentSkill]] = Field(None, description="Optional list detailing specific skills the agent possesses.")
    tags: Optional[List[str]] = Field(None, description="Keywords or tags for categorization and discovery.")
    privacy_policy_url: Optional[HttpUrl] = Field(None, alias="privacyPolicyUrl", description="URL to the agent's privacy policy.")
    terms_of_service_url: Optional[HttpUrl] = Field(None, alias="termsOfServiceUrl", description="URL to the agent's terms of service.")
    icon_url: Optional[HttpUrl] = Field(None, alias="iconUrl", description="URL to an icon representing the agent.")
    last_updated: Optional[str] = Field(None, alias="lastUpdated", description="Timestamp (ISO 8601 format recommended) indicating when the card was last updated.") # Consider using datetime

    # Example validator: Ensure URL is HTTPS if not localhost.
    # §pass47 B8/B2 — in sandbox mode (CC_TARGET_ENVIRONMENT=sandbox or
    # SANDBOX_MODE=true) we accept plain http:// so bootstrap E2E tests can
    # register throwaway HTTP-only agents on the docker network without
    # standing up a TLS proxy. Production behavior unchanged.
    @field_validator('url')
    @classmethod
    def check_url_scheme(cls, v: Optional[AnyUrl]) -> Optional[AnyUrl]:
        return _check_endpoint_scheme(v, 'Agent URL')

    # --- Q-C W6 (2026-05-12): dual-shape sanity ──────────────────────────
    @model_validator(mode='after')
    def at_least_one_endpoint_or_interface(self) -> 'AgentCard':
        """A card must declare AT LEAST one endpoint — v0.3 ``url`` OR v1.0
        ``supportedInterfaces[]`` non-empty. Both is fine (dual-shape)."""
        if not self.url and not self.supported_interfaces:
            raise ValueError("Agent card must declare at least one endpoint via `url` (v0.3) or `supportedInterfaces[]` (v1.0).")
        return self

    @model_validator(mode='after')
    def at_least_one_auth_surface(self) -> 'AgentCard':
        """A card must declare AT LEAST one auth surface — v0.3 ``authSchemes``
        OR v1.0 ``securitySchemes`` + ``security`` (which MAY be empty maps
        when no auth is required)."""
        v03_present = bool(self.auth_schemes)
        v1_present = self.security_schemes is not None and self.security is not None
        if not v03_present and not v1_present:
            raise ValueError("Agent card must declare auth via `authSchemes` (v0.3) or `securitySchemes`+`security` (v1.0).")
        return self

#
