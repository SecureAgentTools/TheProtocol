import uuid
import datetime
# --- MODIFIED: Added EmailStr, SecretStr, Literal, model_validator, Union ---
from typing import List, Optional, Dict, Any, Literal, Union, Annotated
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, EmailStr, SecretStr, model_validator, field_validator, BeforeValidator

# Coerce Decimal/float/int to str for exact JSON serialization (no IEEE 754 rounding)
DecimalStr = Annotated[str, BeforeValidator(lambda v: str(v) if v is not None else "0")]
# --- END MODIFIED ---

# Import local models for type checking
# from . import models # No longer needed here

# --- Developer Schemas (Define before AgentCardRead) ---

# --- ADDED: DeveloperCreate Schema ---
class DeveloperCreate(BaseModel):
    """Schema for creating a new developer."""
    name: str = Field(..., min_length=3, max_length=100, description="Unique name for the developer.")
    email: EmailStr = Field(..., description="Developer's email address.")
    password: SecretStr = Field(..., min_length=12, description="Developer's chosen password.")
    invite_code: Optional[str] = Field(None, max_length=30, description="Beta invite code (required when BETA_INVITE_REQUIRED=true)")
    age_confirmed: bool = Field(False, description="§LEGALKIT: the person confirmed being 18 or older (Privacy § 12); recorded as document age18.")
    tos_accepted: bool = Field(False, description="The user accepted the Terms of Service + Privacy Policy. Required when TOS_CONSENT_REQUIRED; the server stamps the authoritative version.")

    @model_validator(mode="after")
    def validate_inputs(self):
        from agentvault_registry.input_validators import validate_password_strength, validate_safe_text
        validate_password_strength(self.password.get_secret_value())
        self.name = validate_safe_text(self.name, "name")
        return self
# --- END ADDED ---


# ---------------------------------------------------------------------------
# BETA INVITE CODE SCHEMAS
# ---------------------------------------------------------------------------

class InviteCodeGenerateRequest(BaseModel):
    """Request to generate a batch of invite codes."""
    count: int = Field(1, ge=1, le=500, description="Number of codes to generate")
    expires_days: Optional[int] = Field(None, ge=1, le=365, description="Expiry in days from now (None = never expires)")
    note: Optional[str] = Field(None, max_length=255, description="Label for this batch e.g. 'Wave 1 - Twitter'")
    max_uses: int = Field(1, ge=1, le=10, description="Max times each code can be used (default 1 = single-use)")
    grants_admin: bool = Field(
        False,
        description=(
            "Redeeming this code grants admin capability instead of creating an ordinary "
            "developer. Use to hand a registry an administrator without creating the account "
            "yourself: the recipient registers, picks their own password and accepts the "
            "terms. Combine with max_uses=1. Say WHICH capability with admin_flags."
        ),
    )
    admin_flags: Optional[List[str]] = Field(
        None,
        description=(
            "Which granular admin flags redeeming this code grants: any of "
            "admin_platform, admin_federation, admin_treasury, admin_enforcement, "
            "admin_support. Only meaningful with grants_admin=true; omitted means all "
            "five, which is what grants_admin meant before this field existed. The legacy "
            "is_admin super-flag is never granted by an invitation: every admin gate reads "
            "a granular flag, and is_admin only bypasses them. You cannot grant a flag you "
            "do not hold yourself."
        ),
    )

    @field_validator("admin_flags")
    @classmethod
    def _known_flags_only(cls, v):
        if v is None:
            return v
        from agentvault_registry.crud.invite_codes import ADMIN_FLAGS
        unknown = [f for f in v if f not in ADMIN_FLAGS]
        if unknown:
            raise ValueError(
                f"Unknown admin flag(s): {unknown}. Valid: {list(ADMIN_FLAGS)}"
            )
        return v


class InviteCodeResponse(BaseModel):
    """A single invite code with its shareable URL."""
    code: str
    invite_url: str
    expires_at: Optional[datetime.datetime]
    note: Optional[str]
    status: str  # active / used / expired
    use_count: int
    max_uses: int
    grants_admin: bool = False
    admin_flags: List[str] = Field(
        default_factory=list,
        description=(
            "The granular admin flags redeeming this code grants, resolved: empty for an "
            "ordinary invitation, and all five for an admin-granting code minted before "
            "flags could be chosen."
        ),
    )
    created_at: datetime.datetime
    # §OPGUIDE-6 — audit fields for the Settings › Invitations panel. All optional
    # with None defaults so every existing caller (MCP, SDK, scripts) is unaffected.
    used_at: Optional[datetime.datetime] = None
    created_by_email: Optional[str] = Field(
        None, description="Email of the admin who minted this code (None if that account was removed)."
    )
    used_by_email: Optional[str] = Field(
        None, description="Email of the developer who redeemed it (None while unused)."
    )

    model_config = ConfigDict(from_attributes=True)


class InviteCodeBatchResponse(BaseModel):
    """Response for batch code generation."""
    codes: List[InviteCodeResponse]
    count: int


class InviteCodeValidationResponse(BaseModel):
    """Result of validating an invite code."""
    valid: bool
    reason: Optional[str] = None  # "expired", "used", "not_found"


class DeveloperRead(BaseModel):
    """Schema for reading developer information (full profile — f035)."""
    id: int
    name: str
    email: EmailStr = Field(..., description="Developer's email address.")
    created_at: datetime.datetime
    is_verified: bool = Field(..., description="Indicates if the developer is verified.")
    is_admin: bool = Field(..., description="Indicates if the developer has admin privileges (super-flag).")
    # Granular admin sub-flags (RBAC audit fix, 2026-05-08).
    # Without these in the response, the frontend's `usePermissions().can()`
    # always returns false for sub-flag-only admins — the sub-flag system was
    # documented but non-functional on the UI surface. Backend endpoint gates
    # (`require_admin_flag()`) read straight from the model and were always
    # correct; this exposure makes the sidebar + route-guard layers honor the
    # same semantics.
    admin_treasury:    bool = Field(default=False, description="admin_treasury sub-flag — treasury / mint / fee_collector / funding_request gates.")
    admin_support:     bool = Field(default=False, description="admin_support sub-flag — support tickets gates.")
    admin_enforcement: bool = Field(default=False, description="admin_enforcement sub-flag — settlements / suspensions / disputes gates.")
    admin_federation:  bool = Field(default=False, description="admin_federation sub-flag — peer ops / drift / frame management gates.")
    admin_platform:    bool = Field(default=False, description="admin_platform sub-flag — platform infra / agents / webhooks / event store gates.")
    # 2FA
    two_fa_enabled: Optional[bool] = Field(None)
    # Geolocation (f033)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_label: Optional[str] = None
    # Extended profile (f035)
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    website_url: Optional[str] = None
    github_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    company: Optional[str] = None
    timezone: Optional[str] = None
    notification_prefs: Optional[Dict[str, Any]] = None
    last_login_at: Optional[datetime.datetime] = None
    profile_visibility: Optional[str] = Field(default='public')
    # Operator onboarding (f046, renamed f049)
    is_federation_operator: Optional[bool] = None
    federation_operator_status: Optional[str] = None
    # PB-1 backer cosmetic flare (2026-05-09). Sentinel/Architect/Founder.
    # Profile flare is permanent — auto-applied on first fiat purchase,
    # upgrades on higher-tier subsequent purchases.
    flare_tier: Optional[str] = Field(default=None, description="'sentinel' | 'architect' | 'founder' | 'shadow_chancellor' | 'operator' | 'commander'")
    flare_granted_at: Optional[datetime.datetime] = None
    # PB-1 hardening (2026-05-09): unique flare identifier + buyer customization.
    flare_id: Optional[str] = None
    flare_display_name: Optional[str] = None
    flare_tagline: Optional[str] = None
    flare_logo_url: Optional[str] = None
    flare_link_url: Optional[str] = None
    flare_cause: Optional[str] = None
    flare_accent_color: Optional[str] = None
    # 2026-05-11 §12: dual-slot flare display selection. Independent of
    # flare_tier (rolled-up "highest earned"). selected_corner_flare drives
    # the corner badge slot (next to user name), selected_encirclement_flare
    # drives the avatar-circle wrap. Frontend reads these to compose the
    # header avatar + Founders Wall row + agent cards.
    selected_corner_flare: Optional[str] = Field(
        default=None,
        description="User's chosen corner badge: sentinel|architect|founder|operator|commander",
    )
    selected_encirclement_flare: Optional[str] = Field(
        default=None,
        description="User's chosen avatar encirclement: shadow_chancellor (only encirclement-class tier)",
    )
    # 2026-05-12 §14: aesthetic variant for the encirclement (independent of
    # tier). Valid values: 'sauron' | 'goth' | 'obsidian' | 'void'. NULL = the
    # default (currently 'sauron'). Frontend FlareEncirclement renders the
    # matching CSS variant. Tier is rank; variant is flavor.
    flare_encirclement_variant: Optional[str] = Field(
        default=None,
        description="Encirclement aesthetic: sauron|goth|obsidian|void (NULL → default 'sauron')",
    )
    # §28 (2026-05-13) — Broken-machine OVERLAY (independent axis).
    flare_encirclement_overlay: Optional[str] = Field(
        default=None,
        description="Encirclement overlay: glitch|cascade|panic-a|panic-b|panic-c (NULL = none)",
    )
    # 2026-05-13 §20: admin-only corner badge variant. NULL = render the
    # default tier icon; non-null = swap to an inline-SVG design (rocket /
    # crown / vault / gavel / atom / network). Only admins can SET non-null
    # via PATCH /fiat/flare/selection (backend enforces).
    flare_corner_variant: Optional[str] = Field(
        default=None,
        description="Admin-only corner badge variant: rocket|crown|vault|gavel|atom|network (NULL → default tier icon)",
    )
    # 2026-05-12 §15: celebration ack — when NULL on a shadow_chancellor dev,
    # the FE shows the upgrade modal once. Surfaced via DeveloperRead so the
    # frontend can pre-emptively check (the /flare/status endpoint also
    # exposes a derived `should_celebrate` for the canonical check).
    flare_celebration_seen_at: Optional[datetime.datetime] = None
    # W2 — User-initiated deletion / GDPR Art. 17 erasure (2026-05-09).
    # Settings → Danger Zone reads these to render active vs. pending-deletion
    # state. Anonymized accounts cannot log in (password is wiped at the
    # anonymize step), so the frontend only ever sees NULL or 'pending_deletion'.
    deletion_status: Optional[str] = Field(
        default=None,
        description="None ≡ active. 'pending_deletion' during 14-day cooling-off. 'anonymized' is terminal.",
    )
    deletion_requested_at: Optional[datetime.datetime] = None
    anonymized_at: Optional[datetime.datetime] = None

    # §EXCISION-10 — the FE hydrates the session from /developers/me, so the
    # forced-password-change gate must be readable HERE, not only in the login
    # response: otherwise a page refresh loses it and the user lands in an admin
    # UI where every call 403s with no explanation.
    must_change_password: bool = False

    # §LEGALKIT (Terms § 10.2): read by the console after login; the handler fills the two computed ones.
    tos_accepted_version: Optional[str] = None
    tos_current_version: Optional[str] = None
    tos_reconsent_required: bool = False
    reconsent_documents: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class DeveloperProfileUpdate(BaseModel):
    """Schema for updating developer profile fields (PUT /developers/me)."""
    display_name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None)
    avatar_url: Optional[str] = Field(None, max_length=500)
    website_url: Optional[str] = Field(None, max_length=500)
    github_url: Optional[str] = Field(None, max_length=200)
    twitter_handle: Optional[str] = Field(None, max_length=100)

    # §FESUITE 135: the profile's website and GitHub page are links others press; only http(s) is stored
    @field_validator("website_url", "github_url")
    @classmethod
    def _web_addresses(cls, v, info):
        from agentvault_registry.core.web_address import web_address_or_empty
        return web_address_or_empty(v, info.field_name)
    company: Optional[str] = Field(None, max_length=255)
    timezone: Optional[str] = Field(None, max_length=100)
    notification_prefs: Optional[Dict[str, Any]] = Field(None)
    profile_visibility: Optional[str] = Field(
        None,
        pattern=r'^(public|private|team)$',
        description='public | private | team'
    )


class DeveloperProfile(BaseModel):
    """Schema for developer profile information."""
    id: int
    name: str
    email: EmailStr
    organization: Optional[str] = None
    role: str
    is_verified: bool
    # --- ADDED: is_admin field for Embassy access control ---
    is_admin: bool
    # --- END ADDED ---
    created_at: datetime.datetime
    # §LEGALKIT (Terms § 10.2): the console asks for renewed acceptance when the served version moved on.
    tos_accepted_version: Optional[str] = None
    tos_current_version: Optional[str] = None
    tos_reconsent_required: bool = False
    reconsent_documents: list[str] = []

    model_config = ConfigDict(from_attributes=True)

# --- ADDED: Auth Related Schemas ---
class Token(BaseModel):
    """Schema for access token response."""
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: Optional[int] = Field(None, description="Token expiration time in seconds.")
    refresh_token: Optional[str] = Field(None, description="Refresh token for obtaining new access tokens.")

class OwnerSessionToken(BaseModel):
    """§FEFRAME W3 (V0504): a short agent token minted from the owner's signed-in session (no client secret)."""
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds (OWNER_SESSION_TOKEN_MINUTES).")
    agent_did: str
    via: Literal["owner"] = "owner"
    registry_url: Optional[str] = Field(None, description="The registry that minted it, the only one that admits it.")

class RegistrationResponse(BaseModel):
    """Schema for the response after successful registration."""
    message: str
    recovery_keys: List[str] = Field(..., description="Generated recovery keys. Store these securely!")

class PasswordResetRequest(BaseModel):
    """Schema for requesting a password reset email."""
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    """Schema for confirming password reset using a token."""
    token: str = Field(..., max_length=500, description="The password reset token received via email.")
    new_password: SecretStr = Field(..., min_length=12, description="The new password for the account.")

    @model_validator(mode="after")
    def validate_password(self):
        from agentvault_registry.input_validators import validate_password_strength
        validate_password_strength(self.new_password.get_secret_value())
        return self

class PasswordResetRecover(BaseModel):
    """Schema for initiating password reset using a recovery key."""
    email: EmailStr = Field(..., description="The email address associated with the account.")
    recovery_key: str = Field(..., description="One of the recovery keys provided during registration.")

class PasswordSetNew(BaseModel):
    """Schema for setting a new password after recovery key validation."""
    new_password: SecretStr = Field(..., min_length=12, description="The new password for the account.")

    @model_validator(mode="after")
    def validate_password(self):
        from agentvault_registry.input_validators import validate_password_strength
        validate_password_strength(self.new_password.get_secret_value())
        return self
# --- END ADDED ---

# --- ADDED: API Key Schemas ---
class ApiKeyCreateRequest(BaseModel):
    """Object form of the API-key mint body (AL-4).

    The endpoint also still accepts a BARE JSON STRING (the pre-AL-4 contract:
    just the key name). Both the FE Settings view and the MCP `createApiKey` tool
    send that bare string, so accepting only the object form 422s every existing
    caller — hence the union at the endpoint.
    """
    key_name: str = Field(..., description="Name/description for the API key.")
    scopes: Optional[List[str]] = Field(None, description="Optional scope list; omit for full authority ['*'].")
    expires_in_days: Optional[int] = Field(None, description="Optional per-key TTL in days; 0 = non-expiring. Omit for the server default.")


class ApiKeyRead(BaseModel):
    """Schema for reading details about a developer's API key (excluding the key itself)."""
    id: int # Added ID for potential future management needs
    key_prefix: str = Field(..., description="The non-secret prefix of the API key (e.g., 'avreg_').")
    description: Optional[str] = Field(None, description="User-provided description for the key.")
    is_active: bool = Field(..., description="Whether the API key is currently active.")
    created_at: datetime.datetime = Field(..., description="Timestamp when the key was created.")
    last_used_at: Optional[datetime.datetime] = Field(None, description="Timestamp when the key was last used (if tracked).")
    # AL-4 (2026-07-24)
    scopes: Optional[List[str]] = Field(default=None, description="Authorized scopes; ['*'] = full developer authority.")
    expires_at: Optional[datetime.datetime] = Field(None, description="Forced-rotation expiry; null = non-expiring.")

    model_config = ConfigDict(from_attributes=True)

class NewApiKeyResponse(BaseModel):
    """Schema for the response when a new API key is generated."""
    plain_api_key: str = Field(..., description="The full, plain-text API key. Store this securely, it will not be shown again.")
    api_key_info: ApiKeyRead = Field(..., description="Metadata about the newly created key.")
# --- END ADDED ---


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
    # --- MODIFIED: Reverted to developer_id and added developer_is_verified ---
    developer_id: int = Field(..., description="ID of the developer who owns this card.")
    developer_is_verified: bool = Field(..., description="Indicates if the developer owning this card is verified.")
    # --- END MODIFIED ---
    # --- OWL22 OPTION B: Expose agent_did so frontend can preserve DID across saves ---
    agent_did: Optional[str] = Field(None, description="DID of the agent this card belongs to.")
    # --- END OWL22 ---
    card_data: Dict[str, Any] = Field(..., description="The full Agent Card JSON object.")
    # §DISCREFINE (mig 0153) — owner-set listing visibility, so the owner's page can
    # hydrate its toggle from the server instead of guessing. Public readers see the
    # value too; it is not a secret that an agent chose not to be listed, and any
    # reader holding the card already reached it by DID.
    unlisted: bool = Field(False, description="Hidden from discovery, search and facets, here and on every peer; still federated (peers hold an unlisted mirror), so the agent resolves by DID everywhere (§DARKSYNC).")
    # §CARDLINK (2026-09-08) — the registry's own last word on whether this card's PUBLISHED
    # ADDRESS answers, so no surface hands a reader an endpoint it knows is not there.
    # THREE states and the third is the point: null means never probed HERE — every federated
    # mirror legitimately is — and must not read as "dead" (§RAT: never-observed and failing
    # must not look the same). ⚠ This is NOT `is_live`, which is last_active_at within 24h.
    endpoint_health: Optional[str] = Field(
        None, description="healthy | unhealthy | unreachable, or null when never probed here.")
    endpoint_checked_at: Optional[datetime.datetime] = Field(
        None, description="When this registry last dialled the published address; null if never.")
    created_at: datetime.datetime = Field(..., description="Timestamp when the card was created.")
    updated_at: datetime.datetime = Field(..., description="Timestamp when the card was last updated.")
    # --- REMOVED: developer: DeveloperRead field ---
    # developer: DeveloperRead = Field(..., description="Details of the developer owning this card.")
    # --- END REMOVED ---

    # Enable ORM mode (now from_attributes=True)
    model_config = ConfigDict(from_attributes=True)


class AgentCardSummary(BaseModel):
    """Schema for representing a summarized Agent Card in list responses."""
    id: uuid.UUID = Field(..., description="Unique identifier for the Agent Card record.")
    name: str = Field(..., description="Human-readable display name of the agent.")
    description: Optional[str] = Field(None, description="Detailed description of the agent's purpose.")
    is_active: bool = Field(..., description="Whether the agent card is active and discoverable.")
    origin_registry_name: Optional[str] = Field(None, description="Name of the registry where this agent is hosted (for federated results).")
    # §DIRFEED (2026-09-06) — the two fields an external INDEX needs from the list to decide what to fetch.
    # Without them a directory pays one DETAIL read per card per cycle just to learn the DID and the epoch
    # (measured on the EU/ASIA trial: 105 detail reads a minute for 0 changes). Both are additive and
    # populate from the ORM row (from_attributes); a card with no linked agent answers agent_did null.
    agent_did: Optional[str] = Field(None, description="DID of the agent this card belongs to (OWL22 linkage); null when the card is not linked.")
    updated_at: Optional[datetime.datetime] = Field(None, description="When this card row last changed — the cursor an index compares against (see updated_since on the list).")
    # §TRUSTCHAIN (2026-09-12, journal 45): THIS frame's own verdict on the registry HOSTING this card,
    # attached only for an identified caller (developer or agent token) and only for a card whose
    # origin is a peer of this frame — a frame holds no opinion of itself. Null is "not told", never
    # "trusted". The block is peer_trust_policy.trust_block, the same one /federation/registries serves.
    registry_trust: Optional[Dict[str, Any]] = Field(None, description="This frame's peer-trust verdict on the registry hosting this card (identified callers only; null = not told).")

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
    # §DIRFEED (2026-09-06) — FastAPI IGNORES an unknown query parameter silently, so a client cannot learn by
    # trying whether a server understood its cursor. This block echoes what the server actually applied: absent
    # (null) means the caller asked for no server-side index filter, a key present means that filter ran.
    applied_filters: Optional[Dict[str, Any]] = Field(None, description="The index filters this response actually applied (updated_since / natives_only). Null when none were requested.")


# --- Developer Schemas (Moved earlier) ---
# class DeveloperRead defined above

# --- REMOVED: Old DeveloperCreateResponse ---
# class DeveloperCreateResponse(DeveloperRead):
#     """Schema for response after creating a developer, including the plain API key."""
#     api_key: str = Field(..., description="The generated plain-text API key. Store this securely!")
# --- END REMOVED ---

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
    validated_card_data: Optional[Dict[str, Any]] = Field(None, description="The validated and potentially normalized card data if is_valid is True (optional).")

# --- ADDED: Agent Builder Config Schema ---
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

    # Simple Wrapper Specific Fields (Optional based on agent_builder_type)
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

    # ADK Agent Specific Fields (Optional based on agent_builder_type)
    adk_model_name: Optional[str] = Field(
        None,
        description="Required if agent_builder_type is 'adk_agent'. Model name for ADK LlmAgent (e.g., gemini-1.5-flash-latest)."
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
        description="Authentication required for the generated agent's *own* A2A endpoint."
    )
    wrapper_service_id: Optional[str] = Field(
        None,
        description="Required if wrapper_auth_type is 'apiKey'. Service ID for the generated agent's API key."
    )

    # --- Validation Logic ---
    @model_validator(mode='after')
    def check_conditional_fields(self) -> 'AgentBuildConfig':
        # Simple Wrapper Checks
        if self.agent_builder_type == "simple_wrapper":
            if not self.wrapper_llm_backend_type:
                raise ValueError("'wrapper_llm_backend_type' is required when agent_builder_type is 'simple_wrapper'")
            if not self.wrapper_model_name:
                raise ValueError("'wrapper_model_name' is required when agent_builder_type is 'simple_wrapper'")
        # ADK Agent Checks
        elif self.agent_builder_type == "adk_agent":
            if not self.adk_model_name:
                raise ValueError("'adk_model_name' is required when agent_builder_type is 'adk_agent'")
            if not self.adk_instruction:
                raise ValueError("'adk_instruction' is required when agent_builder_type is 'adk_agent'")

        # Wrapper Auth Check
        if self.wrapper_auth_type == "apiKey" and not self.wrapper_service_id:
            raise ValueError("'wrapper_service_id' is required when wrapper_auth_type is 'apiKey'")

        return self
# --- END ADDED ---

# --- ADDED: Peer Registry Schemas for Federated Registry ---
class RegistryAuthInfoBase(BaseModel):
    """Base schema for registry authentication information."""
    type: Literal["api_key", "oauth2"] = Field(..., description="Type of authentication required.")
    description: Optional[str] = Field(None, description="Human-readable description of the auth method.")
    instructions_url: Optional[str] = Field(None, description="URL to documentation for this auth method.")

class RegistryAuthInfoApiKey(RegistryAuthInfoBase):
    """Schema for API key authentication information."""
    type: Literal["api_key"] = "api_key"
    api_key_header_name: str = Field(..., description="Name of the header to send the API key in.")

class RegistryAuthInfoOAuth2(RegistryAuthInfoBase):
    """Schema for OAuth2 authentication information."""
    type: Literal["oauth2"] = "oauth2"
    token_url: str = Field(..., description="URL to obtain OAuth2 tokens.")
    required_scopes: List[str] = Field(default_factory=list, description="List of required OAuth2 scopes.")

# Union type with discriminator for proper serialization
RegistryAuthInfo = Union[RegistryAuthInfoApiKey, RegistryAuthInfoOAuth2]

class PeerRegistryCreate(BaseModel):
    """Schema for creating a new peer registry registration request."""
    name: str = Field(..., min_length=3, max_length=100, description="Unique name for the peer registry.")
    description: Optional[str] = Field(None, max_length=500, description="Description of the peer registry.")
    base_url: str = Field(..., pattern=r"^https?://", description="HTTP(S) base URL of the peer registry.")
    admin_contact_email: EmailStr = Field(..., description="Contact email for the registry administrator.")
    discovery_auth_info: RegistryAuthInfo = Field(..., description="Authentication info for discovery endpoints.")

class PeerRegistryPublicRead(BaseModel):
    """A peer registry as the PUBLIC routes show it (GET /federation/peers/ and /federation/peers/{peer_id}): every field
    of PeerRegistryRead but the administrator's contact e-mail, which only the registry's admins (the admin federation
    routes) and the developer who registered the peer (its own registrations) read. §SECBATCH wave 3 (2026-10-16): the
    public routes answered it for every active peer."""
    id: int
    owner_developer_id: int
    name: str
    description: Optional[str]
    base_url: str
    status: Literal["PENDING_APPROVAL", "ACTIVE", "INACTIVE", "REJECTED"]
    discovery_auth_info: Dict[str, Any]  # Using Dict for read since it's stored as JSON
    interaction_auth_info: Optional[Dict[str, Any]] = None
    registered_at: datetime.datetime
    approved_at: Optional[datetime.datetime] = None
    approved_by_developer_id: Optional[int] = None
    last_synced_at: Optional[datetime.datetime] = None
    peer_type: Optional[str] = None
    hop_distance: Optional[int] = None
    parent_registry_id: Optional[int] = None
    trust_domain: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PeerRegistryRead(PeerRegistryPublicRead):
    """Schema for reading peer registry information (the admin and owner routes): the public fields and the contact."""
    # pass73.3.19 (2026-05-28): was EmailStr — a READ model strictly re-validating
    # stored data 500'd the whole endpoint when a peer carried a non-RFC address
    # (e.g. 'admin@local'). Read models must faithfully represent stored rows, not
    # re-validate them; the create/update path keeps EmailStr. Caught by
    # MCP-tester getMyFederationRegistrations → federation_peers.py:190.
    # See [[feedback_emailstr_rejects_rfc6761_tlds]].
    admin_contact_email: str

class PeerRegistryAdminUpdateStatus(BaseModel):
    """Schema for admin status updates to peer registries."""
    status: Literal["ACTIVE", "INACTIVE", "REJECTED"] = Field(
        ..., description="New status for the peer registry."
    )

class PeerRegistryUpdate(BaseModel):
    """Schema for updating peer registry details by the owner."""
    description: Optional[str] = Field(None, max_length=500, description="Description of the peer registry.")
    admin_contact_email: Optional[EmailStr] = Field(None, description="Contact email for the registry administrator.")
    discovery_auth_info: Optional[RegistryAuthInfo] = Field(None, description="Authentication info for discovery endpoints.")

class PeerRegistryListResponse(BaseModel):
    """Schema for the response when listing peer registries."""
    items: List[PeerRegistryRead] = Field(..., description="List of peer registries for the current page.")
    pagination: PaginationInfo = Field(..., description="Pagination details.")

class PeerRegistryPublicListResponse(BaseModel):
    """The public list of peer registries (GET /federation/peers/): PeerRegistryPublicRead items, no contact e-mail."""
    items: List[PeerRegistryPublicRead] = Field(..., description="List of peer registries for the current page.")
    pagination: PaginationInfo = Field(..., description="Pagination details.")
# --- END ADDED ---

# --- ADDED: Agent Schemas ---
class AgentRead(BaseModel):
    """Schema for reading agent information."""
    id: int
    did: str = Field(..., description="Agent's Decentralized Identifier")
    client_id: str = Field(..., description="OAuth client ID")
    status: str = Field(..., description="Account status (active, suspended, revoked)")
    creator_developer_id: int = Field(..., description="ID of the developer who created this agent")
    created_at: datetime.datetime
    last_active_at: Optional[datetime.datetime] = None
    # §COCKPITA R2 (§RUNTIME) — RUNTIME is a THIRD fact, and it is not `status`.
    # `status` is the ENFORCEMENT state (active|suspended|revoked), which an owner cannot
    # set; a deployment row says whether this registry's CI/CD ever shipped the agent;
    # neither answers "is it up right now". These two do, from opposite directions:
    #   last_health / last_health_at  — WE called IT (agent_health_checker, pull)
    #   last_active_at                — IT called US with its own JWT (push)
    # ⚠ `last_health_at` is exposed BESIDE the verdict on purpose. A verdict with no age
    # is indistinguishable from a fossil, and on registry-a six of eleven running agents
    # were reading stale words because the checker could not see their card shape at all.
    last_health: Optional[str] = Field(None, description="healthy | unhealthy | unreachable — last PROBE result, never an enforcement state")
    last_health_at: Optional[datetime.datetime] = Field(None, description="When that probe ran. Null = never probed; an old value is not a current claim.")
    reputation_score: int = Field(..., description="Agent's current reputation score")
    liquid_balance: DecimalStr = Field(..., description="Agent's liquid (not locked) balance in the frame's units")
    staked_balance: DecimalStr = Field(..., description="Agent's locked balance in the frame's units")
    # --- ADDED: Fields for agent display ---
    name: Optional[str] = Field(None, description="Agent's display name from agent card")
    description: Optional[str] = Field(None, description="Agent's description from agent card")
    card_data: Optional[Dict[str, Any]] = Field(None, description="Full agent card data if available")
    # --- END ADDED ---
    # PB-1 backer flare cosmetic (2026-05-09) — public.
    flare_tier: Optional[str] = Field(default=None, description="'sentinel' | 'architect' | 'founder'")
    flare_granted_at: Optional[datetime.datetime] = None
    # Hardening: customization is sourced from the owning developer's flare row
    # (display_name, tagline, etc.). Caller can render the full bespoke badge
    # without an extra round-trip.
    flare_id: Optional[str] = None
    flare_display_name: Optional[str] = None
    flare_tagline: Optional[str] = None
    flare_logo_url: Optional[str] = None
    flare_link_url: Optional[str] = None
    flare_cause: Optional[str] = None
    flare_accent_color: Optional[str] = None
    # 2026-05-13 §15+§19+§20: per-agent encirclement variant. Migration 0043
    # adds the column on agents; PATCH /fiat/flare/agent/{did}/variant writes
    # it. Without exposing it here, /developers/me/agents returns the agent
    # rows WITHOUT the variant — frontend reloads then see the stored value
    # as undefined, falling back to default 'sauron'. THIS was the bug
    # Commander hit on prod: variants persisted in DB but vanished on reload.
    flare_encirclement_variant: Optional[str] = Field(
        default=None,
        description="Per-agent encirclement variant (PB-1 §15) — sauron|goth|obsidian|void|aurora|phoenix|crystal|blackhole|halloween|inferno|glacier|matrix|galaxy|ink|circuit|yule|sakura|solstice|harvest",
    )
    # §28 (2026-05-13) — Per-agent broken-machine overlay (independent axis).
    flare_encirclement_overlay: Optional[str] = Field(
        default=None,
        description="Per-agent overlay (§28) — glitch|cascade|panic-a|panic-b|panic-c|null",
    )
    # §23 (2026-05-14) — Dual-slot bearer flags. When the dev equips a slot
    # on this agent via POST /flare/equip/{slot}/{did}, the corresponding
    # flag flips TRUE. The list endpoint (developers.py:list_developer_agents)
    # attaches the OWNING developer's selected_*_flare to each agent row
    # when bears_*_flare is TRUE — so UserAvatar.vue's typeof-aware fallback
    # resolves the corner+encirclement on each agent independently.
    bears_corner_flare: bool = Field(default=False, description="True if this agent bears the dev's corner flare slot.")
    bears_encirclement_flare: bool = Field(default=False, description="True if this agent bears the dev's encirclement flare slot.")
    flare_corner_variant: Optional[str] = Field(
        default=None,
        description="Per-agent admin corner-badge variant (admin-only). rocket|crown|vault|gavel|atom|network. NULL = use dev's selected variant or default tier icon.",
    )
    # Slot-derived fields populated by list_developer_agents (NOT DB columns):
    # the OWNING dev's slot selections, attached when this agent bears that
    # slot. Lets UserAvatar.vue render BOTH slots independently with no extra
    # request. NULL when this agent does not bear the slot (or dev has no
    # selection in that slot).
    selected_corner_flare: Optional[str] = Field(
        default=None,
        description="Dev's selected_corner_flare, attached when bears_corner_flare=True.",
    )
    selected_encirclement_flare: Optional[str] = Field(
        default=None,
        description="Dev's selected_encirclement_flare, attached when bears_encirclement_flare=True.",
    )
    # §MARKSURFACES (2026-09-10) — the LEDGER-EARNED mark, beside the PURCHASED flare.
    # These are two different visual classes and must never be confused: everything above
    # is bought, this is struck from the registry's own guild ledger and recomputed on
    # read (`services/track_record.compact_track_record`). NULL/absent = no verified work,
    # which is most agents and renders as no mark at all.
    # ⚠ This dict is assembled KEY BY KEY in `list_developer_agents` before
    # `AgentRead(**agent_dict)`, so adding the field here alone leaves it None forever
    # (§EXCISION-10). The writer is in developers.py and the FE reads it in UserAvatar.
    track_record: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Registry-attested verified-work summary (jobs/stars/on-time/disputes). Absent = no verified work.",
    )

    model_config = ConfigDict(from_attributes=True)
# --- END ADDED ---

# --- ADDED: Staking Schemas for Economic Engine ---
class StakeRequest(BaseModel):
    """Schema for requesting to stake tokens."""
    amount: str = Field(..., description="Amount to stake, in the frame's unit (numeric string, e.g. '100' or '50.5').")

class UnstakeRequest(BaseModel):
    """Schema for requesting to unstake tokens."""
    amount: str = Field(..., description="Amount to unstake, in the frame's unit (numeric string).")

class StakeTransactionCreate(BaseModel):
    """Schema for creating a stake transaction (internal use)."""
    agent_did: str = Field(..., description="DID of the agent performing the transaction.")
    transaction_type: Literal["STAKE", "UNSTAKE"] = Field(..., description="Type of transaction.")
    amount: str = Field(..., description="Amount, in the frame's unit (numeric string).")

class StakeTransactionRead(BaseModel):
    """Schema for reading stake transaction information."""
    id: int
    agent_did: str
    transaction_type: Literal["STAKE", "UNSTAKE"]
    amount: DecimalStr
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class StakeBalanceResponse(BaseModel):
    """Schema for returning stake balance information."""
    agent_did: str = Field(..., description="DID of the agent.")
    liquid_balance: DecimalStr = Field(..., description="Current liquid (unstaked) balance.")
    staked_balance: DecimalStr = Field(..., description="Current staked balance.")
    total_balance: DecimalStr = Field(..., description="Total balance (liquid + staked).")
# --- END ADDED ---

# --- ADDED: System Event Schemas for Activity Feed ---
class SystemEventRead(BaseModel):
    """Schema for reading system event information."""
    id: int
    event_type: str = Field(..., description="Type of event (e.g., AGENT_ONBOARDED, FEDERATION_REQUEST)")
    title: str = Field(..., description="Short, human-readable title for the event")
    description: str = Field(..., description="Detailed description of what happened")
    event_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional event-specific data")
    created_at: datetime.datetime
    
    model_config = ConfigDict(from_attributes=True)

class SystemEventListResponse(BaseModel):
    """Schema for the response when listing system events."""
    items: List[SystemEventRead] = Field(..., description="List of system events")
    total: int = Field(..., description="Total number of events (for pagination)")
# --- END ADDED ---

# --- ADDED: TEG Summary Schema for Mission Control ---
class TEGSummaryResponse(BaseModel):
    """Schema for developer's aggregate TEG (Token Economic Graph) summary."""
    total_liquid_balance: DecimalStr = Field(..., description="Total liquid tokens across all developer's agents")
    total_staked_balance: DecimalStr = Field(..., description="Total locked units across all of the developer's agents")
    total_balance: DecimalStr = Field(..., description="Total units (liquid + locked) across all agents")
    aggregate_reputation_score: DecimalStr = Field(..., description="Average reputation score across all developer's agents")
    agent_count: int = Field(..., description="Total number of agents owned by the developer")
    active_agent_count: int = Field(..., description="Number of active agents owned by the developer")
    # §ORGPOCKET O4 (2026-08-28) — THE SUM DECLARES ITS OWN UNIT.
    # These totals are a plain addition over one registry's `agents` table, so
    # they are single-currency by construction today. The field exists so that
    # stays TRUE BY CONSTRUCTION rather than by accident: anything that later
    # widens this aggregate across frames has to answer "which currency did I
    # just add up", and the caller labels from this field instead of from the
    # viewer's own frame. §FOREIGNACT's rule, one level up — a label attached to
    # a number must come from the same place the number does.
    currency: Optional[str] = Field(None, description="Settlement currency these totals are denominated in")
# --- END ADDED ---

# --- ADDED: Agent Log Schemas ---
class AgentLogBase(BaseModel):
    """Base schema for agent logs"""
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = Field(
        ..., description="Log level"
    )
    message: str = Field(..., description="Log message")
    source: Optional[str] = Field(None, description="Source component/module")
    log_metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional structured data"
    )

class AgentLogCreate(AgentLogBase):
    """Schema for creating a new log entry"""
    timestamp: Optional[datetime.datetime] = Field(
        None, description="Log timestamp (defaults to current time)"
    )

class AgentLogRead(AgentLogBase):
    """Schema for reading log entries"""
    id: int
    agent_did: str
    timestamp: datetime.datetime
    
    model_config = ConfigDict(from_attributes=True)

class AgentLogFilter(BaseModel):
    """Schema for filtering log queries"""
    level: Optional[Literal["DEBUG", "INFO", "WARN", "ERROR"]] = None
    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
# --- END ADDED ---


# --- ADDED: Template Download Config Schema (Agent-Own MCP Server — OWL-22) ---
class TemplateDownloadConfig(BaseModel):
    """Schema for generating a downloadable agent bundle with embedded MCP server."""
    template_id: Literal[
        "sovereign-marketplace",
        "trading-sentinel",
        "data-oracle",
        "senate-delegate"
    ] = Field(..., description="Template type to generate")
    agent_name: str = Field(..., min_length=3, max_length=100, description="Display name for the agent")
    human_readable_id: str = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        min_length=3,
        max_length=50,
        description="Unique slug for the agent (lowercase, hyphens only)"
    )
    agent_did: str = Field(
        ...,
        pattern=r"^did:(theprotocol|cos):(?:[a-z0-9][a-z0-9.-]{0,61}[a-z0-9]:)?[a-z0-9_][a-z0-9_\-]{2,80}$",  # §DIDWIDEN: <issuer>:<uuid4> is a valid third shape
        description="The agent's DID (obtained from /onboard/create_agent)"
    )
    client_id: str = Field(
        ...,
        pattern=r"^agent-[0-9a-f]+$",
        description="The agent's OAuth client_id"
    )
    # NOTE: client_secret is NOT included — user fills .env.secret after extraction
    registry_url: str = Field(
        default="http://localhost:8000",
        description="URL of the TheProtocol Registry"
    )
    teg_url: str = Field(
        default="http://localhost:8100",
        description="URL of the TEG Layer"
    )
    mcp_port: int = Field(default=3100, ge=1024, le=65535, description="Port for the agent's MCP server")
    agent_api_port: int = Field(default=8020, ge=1024, le=65535, description="Port for the agent's FastAPI service")
    agent_metrics_port: int = Field(default=9020, ge=1024, le=65535, description="Port for the agent's Prometheus metrics")
    include_circuits: bool = Field(default=True, description="Bundle ZKP circuits in the download")
# --- END ADDED ---


# ---------------------------------------------------------------------------
# Operator Application Schemas (f046)
# ---------------------------------------------------------------------------

class OperatorApplicationCreate(BaseModel):
    """Schema for submitting an operator registry license application."""
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., max_length=200)
    organization: str = Field(default="", max_length=255)
    deployment: str = Field(default="undecided", max_length=50)
    experience: str = Field(default="beginner", max_length=50)
    use_case: str = Field(default="", max_length=2000)
    # §LEGALKIT: Operator Terms § 1.2 says acceptance happens at application; it is now asked and recorded.
    accept_operator_terms: bool = Field(default=False, description="The applicant accepted the Federation Operator Terms (required).")
    # §FESUITE V0595: the configuration the applicant chooses (GET /public/env-catalog keys, operator scope only; the
    # route refuses a frame-scope key with the reason); absent or empty = everything inherited from the frame
    env_choices: Dict[str, str] = Field(default_factory=dict, description="Catalog key -> option (GET /api/v1/public/env-catalog).")


class OperatorApplicationRead(BaseModel):
    """Schema for reading an operator application."""
    id: str
    developer_id: Optional[int] = None
    name: str
    email: str
    organization: Optional[str] = None
    deployment: str
    experience: str
    use_case: Optional[str] = None
    status: str
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime.datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime.datetime
    # §FESUITE V0595 (mig 0186): what the applicant chose; {} = everything inherited from the frame
    env_choices: Dict[str, str] = Field(default_factory=dict)
    # --- f047: Bundle provisioning fields ---
    bundle_path: Optional[str] = None
    bundle_generated_at: Optional[datetime.datetime] = None
    bundle_download_count: int = 0
    bundle_expires_at: Optional[datetime.datetime] = None
    docker_registry_username: Optional[str] = None
    spire_fingerprint: Optional[str] = None
    # --- END f047 ---
    # --- f048: Revocation fields ---
    revoked_at: Optional[datetime.datetime] = None
    revoked_reason: Optional[str] = None
    revoked_by: Optional[int] = None
    # --- END f048 ---
    # --- f049: Activation fields ---
    activation_code_expires_at: Optional[datetime.datetime] = None
    activated_at: Optional[datetime.datetime] = None
    activated_developer_id: Optional[int] = None
    # --- END f049 ---
    # --- f050: Docker pull token fields ---
    docker_pull_token_prefix: Optional[str] = None
    docker_pull_token_issued_at: Optional[datetime.datetime] = None
    # --- END f050 ---
    # --- f051: Cloud hosting fields ---
    cloud_hosted: bool = False
    cloud_url: Optional[str] = None
    cloud_port_base: Optional[int] = None
    cloud_provisioned_at: Optional[datetime.datetime] = None
    cloud_torn_down_at: Optional[datetime.datetime] = None
    cloud_stack_dir: Optional[str] = None
    # --- END f051 ---

    model_config = ConfigDict(from_attributes=True)


class CloudProvisionRequest(BaseModel):
    """Request body for provisioning a cloud-hosted operator."""
    pass  # operator identified by application_id in URL


class CloudTeardownRequest(BaseModel):
    """Request body for tearing down a cloud-hosted operator."""
    reason: str = Field(default="Teardown requested", max_length=1000)
    # §2026-06-14 — purge=true = LEAVE-NO-TRACES (drain genesis back to mainframe,
    # revoke SPIRE, DELETE peer/app/ES rows on ALL 3 frames, delete stack dir).
    # Default false = SAFE decommission (deactivate peer, archive dir) for audit.
    purge: bool = Field(default=False, description="Leave-no-traces purge (test ops); default archives + deactivates")


class CloudRenameRequest(BaseModel):
    """Request body for an operator IDENTITY re-slug (rename Lane B).

    §2026-06-14 — this changes the load-bearing SLUG (= the op's SPIFFE ID),
    a fleet-wide cascade. NOT the common case: a human-facing name change is the
    zero-downtime DISPLAY rename (Lane A, POST /operator-portal/self-rename).

    Safety: the mutating phases stay gated OFF behind env OPERATOR_RENAME_ALLOW_MUTATING
    until the qatest16 dry-run+rollback is proven. `dry_run=true` (default) runs only
    quiesce+snapshot+plan-gate and STOPS before any mutation. For a real (non-dry-run)
    run, `confirm` MUST equal the operator's current slug (typed-confirm guard).
    """
    new_slug: str = Field(..., min_length=3, max_length=40,
                          description="New operator slug [a-z0-9-]; becomes the new SPIFFE identity")
    dry_run: bool = Field(default=True,
                          description="Default true: quiesce+snapshot+plan only, no mutation. false = execute cascade")
    confirm: Optional[str] = Field(default=None,
                                   description="For a real run, must equal the current slug (typed-confirm)")


class OperatorApplicationReview(BaseModel):
    """Schema for admin review of an operator application (approve/reject)."""
    notes: str = Field(default="", max_length=1000)


class OperatorActivateRequest(BaseModel):
    """Schema for activating an approved operator application with an activation code."""
    activation_code: str = Field(..., min_length=10, max_length=100)

# --- END f046 ---


# --- f048: Operator Revocation / Status schemas ---

class OperatorStatusResponse(BaseModel):
    """Schema for the operator self-status check."""
    is_federation_operator: bool
    federation_operator_status: Optional[str] = None
    application: Optional[OperatorApplicationRead] = None

    model_config = ConfigDict(from_attributes=True)


class OperatorRevocationRequest(BaseModel):
    """Schema for requesting operator revocation (admin or self-request)."""
    reason: str = Field(..., min_length=1, max_length=1000)

# --- END f048 ---


# =============================================================================
# === §FRAMEFORM — public frame-request intake (mig 0172) =====================
# =============================================================================

class FrameRequestAdminRead(BaseModel):
    """Full row for the admin review list."""
    id: str
    status: str
    contact_name: str
    contact_email: str
    organization: Optional[str] = None
    frame_name: Optional[str] = None
    display_name: Optional[str] = None
    hostname: Optional[str] = None
    trust_domain: Optional[str] = None
    ticker: Optional[str] = None
    currency_name: Optional[str] = None
    federation_choice: Optional[str] = None
    use_case: Optional[str] = None
    notes: Optional[str] = None
    answers: Dict[str, Any] = Field(default_factory=dict)
    # §FESUITE V0595: the env lines the chosen features mean (services/env_catalog.py), for the reviewer; a feature the
    # catalog does not know (a row older than it) is left out here and stays in answers as it was sent
    env_preview: List[str] = Field(default_factory=list)
    source_ip: Optional[str] = None
    developer_id: Optional[int] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime.datetime] = None
    review_notes: Optional[str] = None
    provisioned_frame: Optional[str] = None
    # §HELLOFRAME (mig 0180): the frame kit's download window, for an approved self-hosted request
    kit_approved_at: Optional[datetime.datetime] = None
    kit_download_count: Optional[int] = 0   # None on a row built in memory; the column's server default is 0
    kit_last_download_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _preview_env(self):
        feats = (self.answers or {}).get("features") or {}
        if feats and not self.env_preview:
            from agentvault_registry.services.env_catalog import env_lines, validate_choices
            clean, _errors = validate_choices(feats, "frame")
            self.env_preview = [f"{name}={value}" for name, value in env_lines(clean)]
        return self


class FrameRequestUpdate(BaseModel):
    """Admin review action. Status + notes only; nothing here provisions. `approved` is for a self-hosted request and
    opens its frame kit download window (routers/frame_kit.py); approving again opens a new window."""
    model_config = ConfigDict(extra="forbid")

    status: Optional[Literal["pending", "reviewed", "approved", "provisioned", "rejected"]] = None
    review_notes: Optional[str] = Field(None, max_length=2000)
    provisioned_frame: Optional[str] = Field(None, max_length=64)

# --- END §FRAMEFORM ---


# ===========================================================================
# Admin Management Plane (M1, 2026-04-20) — /api/v1/admin/developers/*
# ===========================================================================

class DeveloperAdminRead(BaseModel):
    """List-row shape for the admin developers view.

    email is a plain str ON PURPOSE: this is a READ model for the admin
    surface, and the database can hold addresses EmailStr rejects (measured
    2026-08-23: a provisioning-seeded 'admin@localhost' row 500'd the ENTIRE
    /admin/developers list — one malformed row must never blind the admin to
    all the others). Write-side validation keeps EmailStr."""
    id: int
    name: str
    email: str
    is_verified: bool
    is_admin: bool
    two_fa_enabled: bool
    is_suspended: bool
    is_federation_operator: bool
    federation_operator_status: Optional[str] = None
    must_change_password: bool = False
    agent_count: int = 0
    last_login_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    deleted_at: Optional[datetime.datetime] = None
    suspended_at: Optional[datetime.datetime] = None
    suspended_reason: Optional[str] = None
    # Fix 1 (2026-04-20): granular admin flags
    admin_treasury: bool = False
    admin_support: bool = False
    admin_enforcement: bool = False
    admin_federation: bool = False
    admin_platform: bool = False
    # §FRAMELIC — service account: every agent this developer mints starts unlisted.
    agents_unlisted_by_default: bool = False

    model_config = ConfigDict(from_attributes=True)


class DeveloperAdminFlagsUpdate(BaseModel):
    """Body for PUT /admin/developers/{id}/admin-flags (Fix 1, 2026-04-20)."""
    admin_treasury: Optional[bool] = None
    admin_support: Optional[bool] = None
    admin_enforcement: Optional[bool] = None
    admin_federation: Optional[bool] = None
    admin_platform: Optional[bool] = None
    # §FRAMELIC (2026-09-07) — not an admin flag: the SERVICE-ACCOUNT marker. It rides here
    # because this is the one rail that already sets per-developer posture, with the audit
    # event and the self-lockout guard the change deserves.
    agents_unlisted_by_default: Optional[bool] = None


class DeveloperAdminApiKeySummary(BaseModel):
    """API key listing inside developer detail."""
    id: int
    key_prefix: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime.datetime
    last_used_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DeveloperAdminAgentSummary(BaseModel):
    """Agent listing inside developer detail (minimal — full via /admin/agents)."""
    did: str
    name: Optional[str] = None
    status: str
    enforcement_status: Optional[str] = None
    created_at: datetime.datetime
    last_active_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DeveloperAdminOrgMembership(BaseModel):
    """Organization membership inside developer detail."""
    organization_id: str
    organization_name: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class DeveloperAdminDetailRead(DeveloperAdminRead):
    """Full developer detail for admin drawer view."""
    # Profile
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    website_url: Optional[str] = None
    github_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    company: Optional[str] = None
    timezone: Optional[str] = None
    profile_visibility: Optional[str] = None
    # Geolocation
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_label: Optional[str] = None
    # §pass66.11 — flare tier (for admin Grant Flare Tier display)
    flare_tier: Optional[str] = None
    # Relations
    agents: List[DeveloperAdminAgentSummary] = Field(default_factory=list)
    api_keys: List[DeveloperAdminApiKeySummary] = Field(default_factory=list)
    organizations: List[DeveloperAdminOrgMembership] = Field(default_factory=list)
    # Operator app linking
    operator_application_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DeveloperAdminListResponse(BaseModel):
    """Paginated list response for admin developers endpoint."""
    developers: List[DeveloperAdminRead]
    total: int
    limit: int
    offset: int


class DeveloperSuspendRequest(BaseModel):
    """Body for POST /admin/developers/{id}/suspend."""
    reason: str = Field(..., min_length=10, max_length=500)


class DeveloperActionReasonRequest(BaseModel):
    """Generic body for admin actions that require a reason."""
    reason: str = Field(..., min_length=1, max_length=500)


class DeveloperDeleteRequest(BaseModel):
    """Body for DELETE /admin/developers/{id} — requires typed email confirm.

    confirm_email is a plain str ON PURPOSE: it must EQUAL the stored value,
    and the stored value can be an address EmailStr rejects — with EmailStr
    here, the one malformed row (measured: 'admin@localhost', 2026-08-23) was
    exactly the row the delete rail could never confirm. Equality against the
    target is the whole validation.
    """
    reason: str = Field(..., min_length=20, max_length=500)
    confirm_email: str = Field(..., min_length=3, max_length=320, description="Must match the target developer's email exactly.")


class GiftProvisioningRequest(BaseModel):
    """§pass66.9 — Body for POST /admin/developers/{id}/gift-provisioning."""
    months: int = Field(..., ge=1, le=120, description="Months to add to provisioning unlock window")
    reason: str = Field(..., min_length=10, max_length=500, description="Audit reason (visible in admin action log)")


# Simple status-response shape for action endpoints
class DeveloperAdminActionResponse(BaseModel):
    """Response after admin action on a developer."""
    developer_id: int
    action: str
    status: str
    message: Optional[str] = None


# --- Agent admin (M2, 2026-04-20) --------------------------------------------

class AgentAdminRead(BaseModel):
    """List-row shape for the admin agents view."""
    did: str
    name: Optional[str] = None
    client_id: str
    status: str
    enforcement_status: str
    enforcement_level: int = 0
    offense_count: int = 0
    creator_developer_id: int
    creator_developer_email: Optional[str] = None
    creator_developer_deleted: bool = False
    organization_id: Optional[str] = None
    team_id: Optional[str] = None
    reputation_score: int = 0
    liquid_balance: float = 0.0
    staked_balance: float = 0.0
    staking_tier: Optional[str] = None
    auto_compound_enabled: bool = False
    mtls_enabled: bool = False
    spiffe_id: Optional[str] = None
    created_at: datetime.datetime
    last_active_at: Optional[datetime.datetime] = None
    # §pass37 (2026-05-18) — Option C signal cell fields for the compound
    # "Signals" column on /admin/agents. Cheap LEFT JOINs (no extra round-trip).
    last_pulled_at: Optional[datetime.datetime] = None
    last_pulled_etag: Optional[str] = None
    current_signing_kid: Optional[str] = Field(
        None,
        description="`<did>#<max_rotation_seq>` if any signing key row exists, else null.",
    )
    drift_count_24h: int = Field(
        0,
        description="Count of AgentCardPulled events for this DID in the last 24 hours.",
    )

    model_config = ConfigDict(from_attributes=True)


class AgentAdminListResponse(BaseModel):
    """Paginated list response for admin agents endpoint."""
    agents: List[AgentAdminRead]
    total: int
    limit: int
    offset: int


class AgentAdminStakePosition(BaseModel):
    """A lock inside the agent detail."""
    id: str
    amount: float
    staked_at: datetime.datetime
    unstaked_at: Optional[datetime.datetime] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class AgentSigningKeyRead(BaseModel):
    """One row of agent_signing_keys for the admin drawer."""
    rotation_seq: int
    kid: str = Field(..., description="`<did>#<rotation_seq>`")
    algorithm: str = "EdDSA"
    public_jwk: Optional[Dict[str, Any]] = None
    created_at: datetime.datetime
    expires_at: Optional[datetime.datetime] = None
    is_current: bool = Field(..., description="True when expires_at IS NULL.")

    model_config = ConfigDict(from_attributes=True)


class AgentLastDriftEvent(BaseModel):
    """Most-recent AgentCardPulled event for an agent (drawer Card Sync tab)."""
    timestamp: Optional[datetime.datetime] = None
    drifted_fields: List[str] = Field(default_factory=list)
    new_etag: Optional[str] = None


class AgentAdminDetailRead(AgentAdminRead):
    """Full agent detail for admin drawer view."""
    public_key_jwk: Optional[Dict[str, Any]] = None
    reputation_bond_amount: float = 0.0
    reputation_bond_status: str = "none"
    rewards_paused_until: Optional[datetime.datetime] = None
    total_rewards_earned: Optional[float] = None
    last_reward_distribution: Optional[datetime.datetime] = None
    last_offense_at: Optional[datetime.datetime] = None
    mtls_enrolled_at: Optional[datetime.datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_label: Optional[str] = None
    stakes: List[AgentAdminStakePosition] = Field(default_factory=list)
    open_disputes_as_complainant: int = 0
    open_disputes_as_defendant: int = 0
    # §pass34 (2026-05-17) — full agent_cards.card_data + metadata for admin
    # transparency. Lets the AdminAgents drawer render the entire card_data
    # JSON (federation metadata, supported interfaces, security schemes, etc.)
    # without an extra round-trip. Null when no card row exists.
    card_data: Optional[Dict[str, Any]] = None
    card_id: Optional[str] = None
    card_created_at: Optional[datetime.datetime] = None
    card_updated_at: Optional[datetime.datetime] = None
    card_is_active: Optional[bool] = None
    # §pass37 (2026-05-18) — Option C: signing-key history + most-recent drift
    # event surfaced inline so the Card Sync + Signing Keys tabs render with
    # zero extra round-trips.
    signing_keys: List[AgentSigningKeyRead] = Field(default_factory=list)
    last_drift_event: Optional[AgentLastDriftEvent] = None

    model_config = ConfigDict(from_attributes=True)


class AgentBulkRefreshCardsRequest(BaseModel):
    """Body for POST /admin/agents/bulk/refresh-cards (§pass37)."""
    agent_dids: List[str] = Field(..., min_length=1, max_length=50)
    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional context for the audit trail.",
    )


class AgentBulkRefreshCardResult(BaseModel):
    agent_did: str
    status: str = Field(..., description="ok | skipped | timeout | error | not_found | 4xx | 5xx")
    http: Optional[int] = None
    url: Optional[str] = None
    drifted_fields: List[str] = Field(default_factory=list)
    listed_columns: List[str] = Field(
        default_factory=list,
        description="the row's listed columns (name, description) this pull carried from the card",
    )
    reason: Optional[str] = None


class AgentBulkRefreshCardsResponse(BaseModel):
    requested: int
    succeeded: int
    failed: int
    skipped: int
    results: List[AgentBulkRefreshCardResult] = Field(default_factory=list)


class AgentOwnershipTransferRequest(BaseModel):
    """Body for POST /admin/agents/{did}/transfer-ownership."""
    new_creator_developer_id: int = Field(..., ge=1)
    reason: str = Field(..., min_length=10, max_length=500)


class AgentRotateCredentialsResponse(BaseModel):
    """Response after rotating agent credentials — plain secret shown ONCE."""
    did: str
    client_id: str
    new_client_secret: str = Field(..., description="Plain secret — shown once, store securely.")
    rotated_at: datetime.datetime
    # §FEFRAME W1: the credential's home (core/public_url.credential_home_url)
    registry_url: Optional[str] = Field(None, description="The registry where these credentials are used")


class AgentHardDeleteRequest(BaseModel):
    """Body for DELETE /admin/agents/{did} — requires typed DID confirm."""
    reason: str = Field(..., min_length=20, max_length=500)
    confirm_did: str = Field(..., description="Must match the target agent DID exactly.")


class AgentBulkSuspendRequest(BaseModel):
    """Body for POST /admin/agents/bulk/suspend."""
    agent_dids: List[str] = Field(..., min_length=1, max_length=50)
    reason: str = Field(..., min_length=10, max_length=500)
    # Phase 6 escape hatch: registry-only suspend, leave mTLS + TEG active.
    soft_suspend: bool = Field(default=False, description="If true, skip mTLS revoke + TEG suspend")


class AgentBulkReinstateRequest(BaseModel):
    """Body for POST /admin/agents/bulk/reinstate (Phase 6 coordinated reinstate)."""
    agent_dids: List[str] = Field(..., min_length=1, max_length=50)
    reason: Optional[str] = Field(default="", max_length=500)
    soft_reinstate: bool = Field(default=False, description="If true, skip mTLS re-enroll + TEG reinstate")


class AgentAdminActionResponse(BaseModel):
    """Response after admin action on an agent."""
    did: str
    action: str
    status: str
    message: Optional[str] = None


class AgentBulkActionResult(BaseModel):
    """Per-agent result inside a bulk operation response."""
    did: str
    status: str  # "succeeded" | "skipped" | "failed"
    reason: Optional[str] = None


class AgentBulkSuspendResponse(BaseModel):
    """Aggregate response for bulk suspend."""
    requested: int
    succeeded: int
    skipped: int
    failed: int
    results: List[AgentBulkActionResult]

# === END Admin Management Plane ===


# ---------------------------------------------------------------------------
# Frame Invitation Schemas (f058 — WS3 sovereign frame federation)
# ---------------------------------------------------------------------------

# SPIFFE URI trust-domain regex: letters/digits/hyphens/dots, no scheme prefix.
# (The SPIFFE spec allows "spiffe://<trust_domain>/..." but the trust_domain
# alone is what we store and pass to spire-server CLI.)
_SPIFFE_TRUST_DOMAIN_RE = r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$"
_HTTPS_URL_RE = r"^https://[a-zA-Z0-9][a-zA-Z0-9.\-]*(:\d+)?(/[^\s]*)?$"
_HEX_NONCE_RE = r"^[a-fA-F0-9]{16,64}$"


class FrameInvitationCreate(BaseModel):
    """Public POST body for a remote frame initiating a federation invitation.

    The remote generates `initiator_nonce` locally (16-64 hex chars) and stores
    it with its own record of the outbound invitation. When we (the receiver)
    approve and POST back to the remote's /finalize endpoint, we include this
    nonce as proof of authenticity. The remote rejects the callback if the
    nonce doesn't match.
    """
    trust_domain: str = Field(..., min_length=3, max_length=255, pattern=_SPIFFE_TRUST_DOMAIN_RE)
    bundle_endpoint_url: str = Field(..., min_length=8, max_length=500, pattern=_HTTPS_URL_RE)
    federation_endpoint_url: str = Field(..., min_length=8, max_length=500, pattern=_HTTPS_URL_RE)
    event_store_url: Optional[str] = Field(
        default=None, max_length=500, pattern=_HTTPS_URL_RE,
        description=("Optional: the initiator's EventStore base URL (e.g. https://events-c.example:8200). "
                     "Required for SF-4 cross-frame event replication to auto-wire on approve; "
                     "if omitted, admin can resync later via /admin/federation/frames/{id}/resync-eventstore."),
    )
    name: str = Field(..., min_length=1, max_length=255)
    contact_email: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    initiator_nonce: str = Field(..., min_length=16, max_length=64, pattern=_HEX_NONCE_RE)


class FrameInvitationOutboundCreate(BaseModel):
    """§HELLOFRAME (2026-09-18): the INITIATOR side of the invitation rail, admin-only on the frame that wants to join.

    The frame's own facts (trust domain, bundle endpoint, federation lane, ledger URL, name) come from its environment;
    the caller names only the peer and how to reach the frame's operator. `spire_bundle_imported` says the host CLI has
    already put the target's bundle into this frame's SPIRE (`frame federate` does that before it calls here), so the
    finalize callback can complete on a registry that holds no docker socket.
    """
    target_registry_url: str = Field(..., min_length=8, max_length=500, pattern=_HTTPS_URL_RE,
                                     description="The peer frame's public registry URL (its console origin).")
    contact_email: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    spire_bundle_imported: bool = Field(
        default=False,
        description="True when the target's SPIRE bundle is already in this frame's SPIRE (the host CLI imported it).",
    )


class FrameInvitationOutboundRead(BaseModel):
    id: str
    status: str
    target_registry_url: str
    initiator_trust_domain: str
    spire_bundle_imported: bool
    created_at: datetime.datetime


class FrameInvitationPublicRead(BaseModel):
    """Minimal response returned by the public create endpoint."""
    id: str
    status: str
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class FrameInvitationAdminRead(BaseModel):
    """Full invitation record for admin review + audit."""
    id: str
    initiator_trust_domain: str
    initiator_bundle_endpoint_url: str
    initiator_federation_endpoint_url: str
    initiator_event_store_url: Optional[str] = None
    initiator_name: str
    initiator_contact_email: str
    initiator_description: Optional[str] = None
    initiator_ip: Optional[str] = None
    status: str
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime.datetime] = None
    review_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    completed_at: Optional[datetime.datetime] = None
    peer_registry_id: Optional[int] = None
    spire_bundle_imported_at: Optional[datetime.datetime] = None
    revoked_by: Optional[int] = None
    revoked_at: Optional[datetime.datetime] = None
    revoked_reason: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class FrameInvitationApprove(BaseModel):
    """Admin approve body — optional free-text notes."""
    notes: str = Field(default="", max_length=2000)


class FrameInvitationReject(BaseModel):
    """Admin reject body — reason is required."""
    reason: str = Field(..., min_length=1, max_length=2000)


class FrameInvitationFinalize(BaseModel):
    """Bilateral callback body — the approving frame POSTs this to the
    initiator's /frame-invitations/{id}/finalize endpoint after importing the
    initiator's bundle on its own side.

    `nonce_echo` must match the `initiator_nonce` the initiator stored for
    this invitation. Single-use: once accepted, the callback cannot be replayed.
    """
    approver_trust_domain: str = Field(..., min_length=3, max_length=255, pattern=_SPIFFE_TRUST_DOMAIN_RE)
    approver_bundle_endpoint_url: str = Field(..., min_length=8, max_length=500, pattern=_HTTPS_URL_RE)
    approver_name: str = Field(..., min_length=1, max_length=255)
    approver_bundle_pem: str = Field(..., min_length=16, max_length=100_000)
    nonce_echo: str = Field(..., min_length=16, max_length=64, pattern=_HEX_NONCE_RE)
    # §FRAMELIC (2026-09-07) — the approver issues the joining frame its federation licence as
    # PART of the handshake and hands the plain key back here, once. Optional so an older
    # approver (no licence rail) still finalizes: a frame with no key simply holds none, which
    # is exactly the pre-0176 state.
    # §HELLOFRAME (2026-09-18): the approver's mTLS federation lane, so the initiator's peer row dials the lane
    # (card pulls, fan-out) and not the SPIRE bundle endpoint it used to store there. Optional: an older approver
    # sends none and the row keeps the old derivation.
    approver_federation_endpoint_url: Optional[str] = Field(
        default=None, max_length=500, pattern=_HTTPS_URL_RE,
    )
    federation_license_key: Optional[str] = Field(
        None, min_length=16, max_length=128,
        description="Frame federation licence key issued by the approver — shown ONCE",
    )


class FrameFederationRevoke(BaseModel):
    """Admin revoke body — reason is required."""
    reason: str = Field(..., min_length=1, max_length=2000)

# === END Frame Invitation Schemas ===


# =============================================================================
# === Registry Card v0.3 Schemas (Migration 0079_rc_v03, 2026-05-21) =========
# Spec: sessionlogs2026/SPEC_2026-05-21_REGISTRY_CARD_v0.3.md
# Plan: sessionlogs2026/PLAN_2026-05-21_REGISTRY_CARD_v0.3_IMPLEMENTATION.md
# =============================================================================

# Regex for hex color codes (3 or 6 hex digits, # required).
_HEX_COLOR_RE = r"^#[0-9a-fA-F]{6}$"
# Regex for SPIFFE IDs: spiffe://<trust-domain>/registry/<name>.
_REG_SPIFFE_RE = r"^spiffe://[a-z0-9._-]{3,255}/registry/[A-Za-z0-9._-]{1,255}$"
# Registry tier enum.
_RegistryTier = Literal[
    "sovereign-mainframe",  # Frame-A, Frame-B
    "regional-mainframe",   # Future regional frames
    "cloud-operator",       # op-tokyo / op-paris / etc.
    "sandbox",              # test environments
    "standalone",           # air-gapped
]
_RegistryStatus = Literal["active", "quarantined", "revoked", "suspended"]
_RegistryTheme = Literal["neural", "sovereign", "custom"]
_RegistryFeeRecipient = Literal["receiver_registry", "sender_registry", "split"]
_RegistryFeeDestination = Literal["treasury_recycle", "operator_keep", "burn"]
_SignatureAlg = Literal["ed25519", "EdDSA"]


class RegistryCardIdentity(BaseModel):
    """LOCKED — derived from env / SPIRE; operator cannot edit."""
    spiffe_id: str = Field(..., pattern=_REG_SPIFFE_RE, max_length=512)
    registry_name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=128)
    trust_domain: str = Field(..., min_length=3, max_length=255)
    public_url: str = Field(..., pattern=r"^https?://", max_length=500)
    federation_base_url: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    founded_at: datetime.datetime
    tier: _RegistryTier
    # §pass66 (2026-05-22) — Path 3 / Bug A. Deploy tag this registry is running.
    # DERIVED at serve time from IMAGE_TAG env > OPERATOR_DEFAULT_IMAGE_VERSION
    # > BUNDLED_IMAGE_TAG constant. NOT signed (outside the 13 canonical paths
    # in registry_card_signer.SIGNED_CANONICAL_PATHS); peer claims here are
    # advisory — compliance gates use the operator's actual runtime env.
    # Empty string == legacy peer not yet on pass66+.
    software_version: Optional[str] = Field(
        None, max_length=128,
        description="Deploy tag of running source (e.g. 'pass66-…-2026-05-22'). "
                    "DERIVED, not signed. Informational — federation peers + ops "
                    "dashboards consume; not authoritative for compliance.",
    )


class RegistryCardSupportContact(BaseModel):
    # §FEDLICENCE improvement 16 (2026-09-28): the admin PUT (RegistryCardOperatorPut) forbids extras at the top
    # level only; a misspelled key one level down was dropped silently and the PUT answered 200.
    model_config = ConfigDict(extra="forbid")
    email: Optional[EmailStr] = None
    matrix: Optional[str] = Field(None, max_length=255)
    signal: Optional[str] = Field(None, max_length=64)


class RegistryCardOperator(BaseModel):
    """Operator persona — mostly EDITABLE. v0.4: developer_id is dropped from the
    served card (internal id) and contact_email is opt-in. Both are Optional here
    so the editor can echo the operator block back on PUT without re-supplying them."""
    # §FEDLICENCE improvement 16 (2026-09-28): the admin PUT (RegistryCardOperatorPut) forbids extras at the top
    # level only; a misspelled key one level down was dropped silently and the PUT answered 200.
    model_config = ConfigDict(extra="forbid")
    developer_id: Optional[int] = Field(None, ge=1)
    display_name: Optional[str] = Field(None, min_length=1, max_length=128)
    bio: Optional[str] = Field(None, max_length=2000)
    contact_email: Optional[EmailStr] = None
    company: Optional[str] = Field(None, max_length=256)
    url: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    github_url: Optional[str] = Field(None, pattern=r"^https://github\.com/", max_length=500)
    twitter_handle: Optional[str] = Field(None, pattern=r"^@?[A-Za-z0-9_]{1,15}$")
    timezone: Optional[str] = Field(None, max_length=64)
    location_label: Optional[str] = Field(None, max_length=128)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0,
        description="Operator-set geo latitude — AUTHORITATIVE for the AgentWorld globe "
                    "(v0.4, 2026-06-14). Set on the card (editor / PUT); supersedes the "
                    "legacy dev-location fallback in build_registry_card.")
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0,
        description="Operator-set geo longitude — AUTHORITATIVE for the AgentWorld globe (v0.4, 2026-06-14).")
    operator_since: Optional[datetime.datetime] = None
    operator_avatar_url: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    successor_contact: Optional[str] = Field(None, max_length=500,
        description="Bus-factor-1 mitigation; free-text contact for handover scenarios.")
    support_contact: Optional[RegistryCardSupportContact] = None


class RegistryCardVisual(BaseModel):
    """Visual identity — editable within guardrails, sovereign frames are PINNED.

    Encirclement + corner + overlay variants mirror the §pass37-43 agent flare
    system (FlareEncirclement.vue). They are PURELY COSMETIC — no SPIFFE lock
    (only `sovereign_variant` is SPIFFE-locked). Receivers render via the
    same FlareEncirclement component used for agent hover tooltips.
    """
    # §FEDLICENCE improvement 16 (2026-09-28): the admin PUT (RegistryCardOperatorPut) forbids extras at the top
    # level only; a misspelled key one level down was dropped silently and the PUT answered 200.
    model_config = ConfigDict(extra="forbid")
    icon_url: Optional[str] = Field(None, pattern=r"^https?://|^/static/", max_length=500)
    icon_etag: Optional[str] = Field(None, max_length=80)
    icon_size_bytes: Optional[int] = Field(None, ge=0, le=512_000)  # 500 KB cap
    orb_color: str = Field("#00d2d2", pattern=_HEX_COLOR_RE)
    orb_glow_color: str = Field("#00ffff", pattern=_HEX_COLOR_RE)
    orb_pulse_speed_hz: float = Field(1.4, ge=0.5, le=3.0)
    orb_size_px: int = Field(16, ge=10, le=24)
    halo_enabled: bool = True
    halo_thickness: float = Field(1.4, ge=0.5, le=2.5)
    theme: _RegistryTheme = "neural"
    sovereign_variant: Optional[str] = Field(None, max_length=64,
        description="SPIFFE-LOCKED — must match SOVEREIGN_REGISTRY_VARIANTS catalog.")
    flare_corner_variant: Optional[str] = Field(None, max_length=64,
        description="Corner badge variant (cosmetic, free-choose). Mirrors agent flare_corner_variant.")
    flare_encirclement_variant: Optional[str] = Field(None, max_length=64,
        description="Encirclement ring variant from the 19-slot catalog (sauron / aurora / matrix / glitch / etc.).")
    flare_encirclement_overlay: Optional[str] = Field(None, max_length=64,
        description="Broken-machine overlay on top of encirclement (glitch / cascade / panic / etc., 13 variants). Requires flare_encirclement_variant to be set.")
    schema_compat: str = Field("v0.3", pattern=r"^v\d+\.\d+$")


class RegistryCardCapabilities(BaseModel):
    """DERIVED — env-var snapshot. Operator cannot lie about supported features."""
    fiat_genesis_registry: bool = False
    fiat_onramp_enabled: bool = False
    fiat_providers: List[Literal["stripe", "mollie"]] = Field(default_factory=list)
    is_central_registry: bool = False
    federation_enforcement_active: bool = False
    federation_enabled: bool = True
    kafka_enabled: bool = False
    event_store_enabled: bool = True
    astraeus_enabled: bool = False
    opa_enabled: bool = False
    auto_tally_enabled: bool = True
    canary_enabled: bool = False
    revocation_drill_enabled: bool = False
    oauth_token_exchange_enabled: bool = False
    routed_fiat_proxy_enabled: bool = False
    saga_adaptive_conc_enabled: bool = False
    federation_card_gc_enabled: bool = False
    zkp_phases_enabled: List[int] = Field(default_factory=list)
    a2a_versions_supported: List[str] = Field(default_factory=lambda: ["1.0"])
    registry_card_versions_served: List[str] = Field(default_factory=lambda: ["0.5"])
    # "sovereign" = central mainframe minting its own frame currency (A/B/C).
    # "genesis_only" kept for backward-compat with cards cached by peers on older
    # images (the validator also parses INCOMING peer cards).
    minting_capability: Literal["sovereign", "genesis_only", "disabled", "limited"] = "disabled"
    bridge_capability: Literal["none", "frame_to_frame", "multi_frame"] = "none"
    supports_payment_protocol: List[str] = Field(default_factory=lambda: ["a2a-payment-v1"])
    supports_event_types: int = Field(0, ge=0)


class RegistryCardIntraFee(BaseModel):
    base_rate_percent: float = Field(0.5, ge=0.0, le=100.0)
    max_rate_percent: float = Field(5.0, ge=0.0, le=100.0)
    velocity_scaling_factor: float = Field(1.0, ge=0.0)
    destination: _RegistryFeeDestination = "treasury_recycle"
    customizable: bool = False
    locked_by_network: bool = True


class RegistryCardCrossFee(BaseModel):
    base_rate_percent: float = Field(0.5, ge=0.0, le=100.0)
    fee_recipient: _RegistryFeeRecipient = "receiver_registry"
    customizable: bool = False
    locked_by_network: bool = True
    future_customization_in_bounded_params: Optional[List[float]] = None


class RegistryCardHostingFee(BaseModel):
    enabled: bool = False
    rate_percent_of_agent_service_fee: float = Field(0.0, ge=0.0, le=100.0)
    min_avt: DecimalStr = "0"
    applies_to_agent_dids: Optional[List[str]] = None
    description: Optional[str] = Field(None, max_length=500)


class RegistryCardEconomicDisclosure(BaseModel):
    spec_version: str = Field("v0.3", pattern=r"^v\d+\.\d+$")
    fee_floor_avt: DecimalStr = "0"   # the fee service applies no floor (transaction_fee_service.FEE_FLOOR_AVT)
    rounding: Literal["ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_DOWN"] = "ROUND_HALF_EVEN"
    fees_emit_event_types: List[str] = Field(
        default_factory=lambda: ["TransactionFeeCollected", "CrossRegistryTransferCompleted"]
    )


class RegistryCardFees(BaseModel):
    intra_registry: RegistryCardIntraFee = Field(default_factory=RegistryCardIntraFee)
    cross_registry: RegistryCardCrossFee = Field(default_factory=RegistryCardCrossFee)
    hosting: RegistryCardHostingFee = Field(default_factory=RegistryCardHostingFee)
    fee_collector_address: str = Field(..., max_length=255,
        description="LIVE-derived from SystemConfigCRUD.get_fee_collection_address(); not hardcoded.")
    fee_waterfall_policy: str = Field("fee_collector → treasury", max_length=200)   # the TEG waterfall's two sources
    settlement_currency: str = "AVT"  # Cross-Frame FX: frame-scoped (AVT/BVT/…), was Literal["AVT"]
    fee_audit_endpoint: str = Field("/api/v1/admin/teg/fees/audit", max_length=500)
    economic_disclosure: RegistryCardEconomicDisclosure = Field(default_factory=RegistryCardEconomicDisclosure)


class RegistryCardFederation(BaseModel):
    """LOCKED — derived from RegistryEnforcementPolicy + env."""
    protocol_version: str = "1.0"
    supported_auth_methods: List[str] = Field(default_factory=lambda: ["mtls", "jwt_svid", "federation_license"])
    trust_domains_accepted: List[str] = Field(default_factory=list)
    spire_bundle_endpoint: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    policy_hash: Optional[str] = Field(None, max_length=80,
        description="sha256:... over canonical JSON of LOCKED_PARAMS (matches registry_health.py:540 algorithm).")
    policy_version: int = Field(1, ge=1)
    policy_updated_at: Optional[datetime.datetime] = None
    is_genesis_registry: bool = False
    is_fiat_genesis: bool = False
    is_sovereign_frame: bool = False
    uptime_started_at: Optional[datetime.datetime] = None
    active_peer_count: int = Field(0, ge=0)
    trusted_peer_spiffe_ids: List[str] = Field(default_factory=list)
    license_id: Optional[str] = Field(None, max_length=128)
    license_status: Optional[str] = Field(None, max_length=32)
    license_key_prefix: Optional[str] = Field(None, max_length=32)


class RegistryCardPolicy(BaseModel):
    """LOCKED — derived from RegistryEnforcementPolicy."""
    locked_params_hash: Optional[str] = Field(None, max_length=80)
    bounded_params: Dict[str, Any] = Field(default_factory=dict,
        description="Canonical 8 fields per spec §0 row 4 — 3 fee + 1 APY + 2 enforcement + 2 governance.")
    policy_version: int = Field(1, ge=1)
    policy_modified_at: Optional[datetime.datetime] = None
    drift_status: Literal["compliant", "drift_detected", "quarantined", "unknown"] = "compliant"
    consul_compliance_state: Literal["active", "stale", "quarantined", "unknown"] = "active"
    policy_change_history_url: Optional[str] = Field(None, max_length=500)


class RegistryCardEconomic(BaseModel):
    """LOCKED — derived from EventStore /projections/supply-audit + RegistryOperatingState."""
    tokens_issued: DecimalStr = "0"
    total_circulating: DecimalStr = "0"
    tokens_destroyed: DecimalStr = "0"
    tokens_fees_collected: DecimalStr = "0"
    supply_invariant_delta: DecimalStr = "0.0"
    supply_invariant_status: Literal["OK", "BREACH", "UNKNOWN"] = "UNKNOWN"
    supply_last_audited_at: Optional[datetime.datetime] = None
    auditor_consecutive_ok_cycles: int = Field(0, ge=0)
    last_breach_at: Optional[datetime.datetime] = None
    treasury_zero_days: int = Field(0, ge=0)
    treasury_quarantine_triggered: bool = False
    external_auditor_endpoint: Optional[str] = Field("https://auditor.theprotocol.cloud",
        pattern=r"^https?://", max_length=500)


class RegistryCardSovereignAgent(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    did: Optional[str] = Field(None, max_length=255)
    subdomain: Optional[str] = Field(None, max_length=255)
    sovereign_variant: Optional[str] = Field(None, max_length=64)


class RegistryCardStats(BaseModel):
    """DERIVED at serve time."""
    agent_count: int = Field(0, ge=0)
    native_agent_count: int = Field(0, ge=0)
    federated_agent_count: int = Field(0, ge=0)
    sovereign_agent_count: int = Field(0, ge=0)
    service_agent_count: int = Field(0, ge=0)
    developer_count: int = Field(0, ge=0)
    active_peers: int = Field(0, ge=0)
    active_disputes: int = Field(0, ge=0)
    active_proposals: int = Field(0, ge=0)
    uptime_pct_30d: float = Field(0.0, ge=0.0, le=100.0)
    canary_pass_rate_24h: float = Field(0.0, ge=0.0, le=100.0)
    computed_at: Optional[datetime.datetime] = None


class RegistryCardEndpoints(BaseModel):
    """Endpoint catalog — operator may add optional URLs only."""
    openapi_spec: str = "/api/v1/openapi.json"
    agent_discovery: str = "/api/v1/agent-cards/"
    agent_card_well_known: Optional[str] = None   # §EXTREACH: no registry serves one; older cards still carry the path
    topology: str = "/api/v1/public/topology"
    network_stats: str = "/api/v1/federation/network-stats"
    federation_info: str = "/api/v1/federation/info"
    policy_compliance: str = "/api/v1/federation/policy-compliance"
    health_check: str = "/api/v1/federation/health-check"
    registry_card: str = "/.well-known/registry-card.json"
    registry_jwks: str = "/.well-known/registry-jwks.json"
    spire_bundle: Optional[str] = None            # §EXTREACH: the configured public bundle endpoint, or none
    fee_config: str = "/api/v1/teg/fees/config"
    external_auditor: Optional[str] = "https://auditor.theprotocol.cloud"
    public_status_page: Optional[str] = None


class RegistryCardLinks(BaseModel):
    """EDITABLE — free-form HTTPS URLs (all optional)."""
    # §FEDLICENCE improvement 16 (2026-09-28): the admin PUT (RegistryCardOperatorPut) forbids extras at the top
    # level only; a misspelled key one level down was dropped silently and the PUT answered 200.
    model_config = ConfigDict(extra="forbid")
    whitepaper: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    docs: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    github_source: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    status_page: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    blog: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    rss: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    terms_of_service: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    privacy_policy: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    code_of_conduct: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    support_url: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    discord: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    matrix: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    incident_log: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)


class RegistryCardCommitments(BaseModel):
    """EDITABLE — operator-declared SLAs / legal commitments."""
    # §FEDLICENCE improvement 16 (2026-09-28): the admin PUT (RegistryCardOperatorPut) forbids extras at the top
    # level only; a misspelled key one level down was dropped silently and the PUT answered 200.
    model_config = ConfigDict(extra="forbid")
    data_residency: Optional[str] = Field(None, max_length=32)
    gdpr_compliant: bool = False
    incident_disclosure_sla_hours: int = Field(72, ge=1, le=720)
    uptime_sla_pct: float = Field(99.0, ge=0.0, le=100.0)
    support_response_hours: int = Field(72, ge=1, le=720)
    deprecation_notice_days: int = Field(30, ge=0, le=365)
    open_source_license: Optional[str] = Field(None, max_length=64)
    breach_disclosure_policy: Optional[str] = Field(None, max_length=500)
    key_rotation_max_days: int = Field(90, ge=1, le=365)
    card_refresh_max_minutes: int = Field(5, ge=1, le=60)
    legally_binding_disclaimer: Optional[str] = Field(None, max_length=1000)


class RegistryCardLifecycle(BaseModel):
    """LOCKED — derived timestamps + status."""
    status: _RegistryStatus = "active"
    quarantine_reason: Optional[str] = Field(None, max_length=500)
    card_updated_at: datetime.datetime
    card_updated_by: Optional[int] = None
    card_etag: str = Field(..., max_length=80)
    served_at: datetime.datetime
    next_card_refresh: Optional[datetime.datetime] = None
    last_card_fetch_count_24h: int = Field(0, ge=0)


class RegistryCardSignature(BaseModel):
    """Signature over the 13 canonical fields (spec §2 signature.signed_canonical)."""
    alg: _SignatureAlg = "ed25519"
    kid: str = Field(..., max_length=255)
    jwks_url: str = Field("/.well-known/registry-jwks.json", max_length=500)
    signed_canonical: List[str] = Field(default_factory=list,
        description="Field paths that participated in the signature; receiver verifies same paths.")
    value: str = Field(..., min_length=1, max_length=2000)


class RegistryCardV03(BaseModel):
    """Full v0.3 Registry Card payload — what /.well-known/registry-card.json returns.

    Field-tier breakdown (spec §3):
      - LOCKED (derived): identity, capabilities, federation, policy, economic,
        sovereign_agents, stats, lifecycle, signature
      - EDITABLE (operator, bounded): description, tags, operator, visual,
        commitments, links
    """
    model_config = ConfigDict(
        json_schema_extra={"$schema": "https://docs.theprotocol.cloud/schemas/registry-card-v0.3.json"},
        extra="forbid",
    )

    registry_card_version: Literal["0.3"] = "0.3"

    identity: RegistryCardIdentity
    operator: RegistryCardOperator
    description: str = Field(..., min_length=0, max_length=2000)
    tags: List[str] = Field(default_factory=list, max_length=20)

    visual: RegistryCardVisual
    capabilities: RegistryCardCapabilities
    fees: RegistryCardFees
    federation: RegistryCardFederation
    policy: RegistryCardPolicy
    economic: RegistryCardEconomic
    sovereign_agents: List[RegistryCardSovereignAgent] = Field(default_factory=list)
    stats: RegistryCardStats
    endpoints: RegistryCardEndpoints
    links: RegistryCardLinks
    commitments: RegistryCardCommitments
    lifecycle: RegistryCardLifecycle
    signature: Optional[RegistryCardSignature] = None


# -------- Operator-editable PUT body (subset of full card) -----------------

class RegistryCardOperatorPut(BaseModel):
    """Subset of RegistryCardV03 that the operator may PUT via /api/v1/admin/registry-card.

    All other fields are LOCKED/DERIVED at serve time — see spec §3 field-tier
    table. Builder ignores any LOCKED field even if present in the PUT body
    (defense in depth — the OpenAPI schema also rejects via extra='forbid').
    """
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, min_length=0, max_length=2000)
    # §DOCSFIX CB-424: at most 20 tags of at most 48 characters each, the card schema's own limits; the item length
    # was not checked, so a longer tag was stored and the card that carried it failed its schema
    tags: Optional[List[Annotated[str, Field(max_length=48)]]] = Field(None, max_length=20)
    operator: Optional[RegistryCardOperator] = None
    visual: Optional[RegistryCardVisual] = None
    links: Optional[RegistryCardLinks] = None
    commitments: Optional[RegistryCardCommitments] = None


# -------- ETag-only event payload for RegistryCardUpdated (spec §0 row 3) --

class RegistryCardUpdatedEvent(BaseModel):
    """Payload emitted to EventStore on every successful card PUT.

    ETag-only (Commander decision 2026-05-21) — receivers fetch full card via
    /.well-known/registry-card.json on demand to keep EventStore lean.
    """
    spiffe_id: str = Field(..., pattern=_REG_SPIFFE_RE)
    card_etag: str = Field(..., max_length=80)
    updated_at: datetime.datetime
    updated_by: Optional[int] = None


# =============================================================================
# === END Registry Card v0.3 Schemas ==========================================
# =============================================================================


# =============================================================================
# === POCKET FRAME — Device Push Registration (f-mobile, 2026-07-07) =========
# =============================================================================

class DevicePushRegisterIn(BaseModel):
    """Register (or refresh) a push device. rail='ntfy' targets are topic names;
    'fcm'/'apns' targets are platform tokens (adapters stubbed until creds exist)."""
    platform: str = Field(..., description="android | ios | web")
    rail: str = Field("ntfy", description="ntfy | fcm | apns")
    target: str = Field(..., max_length=255, description="ntfy topic or platform push token")
    label: Optional[str] = Field(None, max_length=120, description="Human label, e.g. 'Commander Pixel 9'")
    prefs: Optional[dict] = Field(None, description="Per-device notification prefs (reserved)")


# =============================================================================
# === PHONE FABRIC — capability-gated agent computer-use (2026-07-07) =========
# =============================================================================

class PhoneSessionStartIn(BaseModel):
    """Start a phone session. Authorized by an L4 capability token (X-Capability-Token
    header) carrying `phone.use` + phone caveats. Optional `launch` opens an app immediately."""
    launch: Optional[str] = Field(None, max_length=120, description="Package to launch on start (must be in caveat allowlist)")


class PhoneActIn(BaseModel):
    """One phone action. `type` ∈ tap|type|swipe|key|launch|back|home."""
    type: str = Field(..., description="tap | type | swipe | key | launch | back | home")
    target: Optional[str] = Field(None, max_length=240, description="UiNode id (mock) / resource-id or xpath (redroid)")
    text: Optional[str] = Field(None, max_length=2000, description="Text for a 'type' action")
