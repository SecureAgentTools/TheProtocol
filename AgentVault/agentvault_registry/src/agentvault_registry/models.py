import uuid
from datetime import timezone
import datetime
# --- MODIFIED: Added Optional and Decimal ---
from typing import List, Dict, Any, Optional
from decimal import Decimal

from .core.network_profile import money_knob as _np_money_knob  # §MONEY-M2
# --- END MODIFIED ---

import sqlalchemy as sa
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Index,
    # --- MODIFIED: Added unique=True for email token ---
    UUID as SQLUUID, func, UniqueConstraint,
    # --- END MODIFIED ---
    # --- ADDED: Numeric for staking amounts ---
    Numeric,
    # --- END ADDED ---
    # --- ADDED: BigInteger for metrics counts ---
    BigInteger,
    # --- END ADDED ---
    # --- ADDED: SmallInteger for IRONKEY L3/L4 depth fields ---
    SmallInteger,
    # --- END ADDED ---
    # --- ADDED: Float for metrics ---
    Float,
    # --- END ADDED ---
    # --- ADDED: LargeBinary for registry-card asset bytes (mig 0141) ---
    LargeBinary
    # --- END ADDED ---
)
# --- MODIFIED: Import mapped_column and relationship directly if not already ---
# --- MODIFIED: Added DateTime ---
from sqlalchemy.orm import relationship, backref, Mapped, mapped_column, selectinload # Added selectinload, DateTime, backref
# --- END MODIFIED ---


# Import the Base class from database setup
from .database import Base
# Add Text import for longer fields
from sqlalchemy import Text, text
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY  # IRONKEY spend-policy scopes

# --- Developer Model ---
class Developer(Base):
    """SQLAlchemy model for agent developers."""
    __tablename__ = "developers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    # --- ADDED: New fields for email/password auth ---
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    verification_token_expires: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hashed_recovery_key: Mapped[Optional[str]] = mapped_column(String, nullable=True) # Hash of one representative key
    # --- ToS consent record (0120): server-stamped proof of Terms acceptance at registration ---
    tos_accepted_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    tos_accepted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- f037: Email-based password reset tokens ---
    password_reset_token: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    password_reset_token_expires: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- END f037 ---
    # --- END ADDED ---
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True) # Ensure index=True
    # --- ADDED: Admin flag for permission management ---
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    # --- END ADDED ---

    # --- DevCard consent (§V0064 Passport, migration 0090) ---
    # True = this developer REFUSES owner-identity disclosure to foreign venues;
    # build_signed_devcard 403s → their agents cannot Passport-trade. Default
    # False = consent flows from the agent-initiated participation itself (D24).
    dev_card_passport_opt_out: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    
    # --- ADDED: 2FA/TOTP Support Fields ---
    totp_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment='Encrypted TOTP secret for 2FA (Fernet token when TWO_FACTOR_ENCRYPTION_KEY is set; mig 0110 widened 64→255)')
    two_fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False, index=True, comment='Whether 2FA is enabled')
    backup_codes: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True, comment='Encrypted backup recovery codes')  # R57: jsonb (mig 0174)
    two_fa_verified_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment='When 2FA was last verified during setup')
    two_fa_recovery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False, comment='Number of failed 2FA recovery attempts')
    two_fa_last_failure: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment='Last failed 2FA attempt for rate limiting')
    trusted_devices: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True, comment='List of trusted device fingerprints')  # R57: jsonb (mig 0174)
    # --- END 2FA/TOTP Support ---
    # --- AUTH LIFECYCLE (AL-1, mig 0125, 2026-07-24) ---
    # Monotonic revocation counter stamped into every access token as `tv`. Bump
    # to invalidate ALL of this developer's live tokens at once (logout /
    # password change / admin force-logout). Tokens minted before 0125 carry no
    # `tv` and are grandfathered until they expire.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False, comment='Access-token revocation counter (bump = log out everywhere)')
    # PUSH LOGIN (mig 0135): approve sign-in from the enrolled phone with a fingerprint instead
    # of typing a code. Opt-in; default off so no existing account changes behaviour.
    push_login_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    # --- END AUTH LIFECYCLE ---
    # --- AGENTWORLD: Geolocation fields (f033) ---
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # --- END AGENTWORLD ---
    # --- PROFILE FIELDS (f035) ---
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    github_url: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    twitter_handle: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notification_prefs: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    last_login_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # §OURSTATE-3 (mig 0157): the opt-in public handle. NULL = unclaimed and
    # unreachable by name, which is the private default. Uniqueness is a
    # functional index on lower(handle) — "@ruFFa" and "@ruffa" are one name.
    handle: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    handle_claimed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile_visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default='public', server_default='public'
    )
    # --- END PROFILE FIELDS (f035) ---
    # --- OPERATOR BOOTSTRAP (f044) ---
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.text("false"), nullable=False)
    # --- END OPERATOR BOOTSTRAP ---
    # --- FEDERATION SHADOW (§pass66.9) ---
    # TRUE when this row is a placeholder created by federation_sync to
    # satisfy `agent_cards.developer_id NOT NULL` FK for a federated agent
    # card whose remote developer_id is unknown locally. Never a real user.
    # Used by `list_developers` to filter shadows out of human-facing UIs
    # by default. Migration 0081 backfills WHERE hashed_password matched
    # the canonical literal.
    is_federation_shadow: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.text("false"), nullable=False)
    # --- END FEDERATION SHADOW ---
    # --- OPERATOR ONBOARDING (f046, renamed f049) ---
    is_federation_operator: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.text("false"), nullable=False)
    federation_operator_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # pending/approved/suspended/revoked
    # --- END OPERATOR ONBOARDING ---
    # --- ADMIN FLAG SPLIT (Fix 1, 2026-04-20) — granular platform-admin roles ---
    admin_treasury: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false"), nullable=False
    )
    admin_support: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false"), nullable=False
    )
    admin_enforcement: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false"), nullable=False
    )
    admin_federation: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false"), nullable=False
    )
    admin_platform: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false"), nullable=False
    )
    # --- END ADMIN FLAG SPLIT ---
    # §FRAMELIC (mig 0176) — the SERVICE-ACCOUNT flag. Every agent card this developer
    # mints starts `unlisted=true`, so a system identity (svc-sim, svc-canary,
    # svc-provisioning, svc-market, the FX router) is out of discovery by construction
    # rather than by somebody remembering at each mint. Owner and admin can still flip
    # any individual card. This is a DISCOVERY property, never access control — a direct
    # DID lookup still resolves, exactly as §DISCREFINE designed `unlisted`.
    agents_unlisted_by_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false"), nullable=False
    )
    # --- ADMIN LIFECYCLE MANAGEMENT (M1, 2026-04-20) ---
    is_suspended: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false"), nullable=False, index=True
    )
    suspended_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    suspended_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- END ADMIN LIFECYCLE MANAGEMENT ---
    # --- USER-INITIATED ACCOUNT DELETION (W2, 2026-05-09 — Migration 0037) ---
    # GDPR Art. 17 right-of-erasure flow. State machine:
    #   active (NULL) → pending_deletion → anonymized
    # 14-day cooling-off in pending_deletion; user can cancel + revert.
    # Anonymize wipes PII in-place but keeps the row + FK integrity for
    # § 147 AO 10-year financial-record retention. See Privacy Policy § 4.5.
    deletion_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    deletion_requested_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    anonymized_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # --- END USER-INITIATED ACCOUNT DELETION ---
    # --- FLARE — PB-1 backer cosmetic (2026-05-09) ---
    # Profile flare: auto-applied on first fiat purchase, upgrades on higher-tier
    # purchases (Founder > Architect > Sentinel). Permanent — cannot be moved.
    flare_tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    flare_granted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    flare_source_purchase_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("fiat_purchases.id", ondelete="SET NULL"), nullable=True
    )
    # --- END FLARE ---

    # --- FLARE UNIQUENESS + CUSTOMIZATION (PB-1 hardening, 2026-05-09) ---
    # flare_id is the canonical identifier — generated on first grant,
    # preserved across tier upgrades. Non-transferable between developers
    # by design (no admin endpoint moves it). The customization fields below
    # are buyer-editable via PATCH /fiat/flare/customize.
    flare_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    flare_display_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    flare_tagline: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    flare_logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    flare_link_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    flare_cause: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    flare_accent_color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # --- END FLARE UNIQUENESS ---

    # --- FLARE SLOT SELECTION (multi-slot display, 2026-05-11) ---
    # Two independent display slots. `flare_tier` stays as the rolled-up
    # "highest tier earned" (rank-based). Selection columns drive what's
    # displayed in each slot — backers can wear a lower-rank corner if they
    # prefer. Default-populated by migration 0041 + auto-set on grant.
    selected_corner_flare: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    selected_encirclement_flare: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    # --- END FLARE SLOT SELECTION ---

    # --- FLARE ENCIRCLEMENT VARIANT (Shadow Chancellor aesthetic, 2026-05-12) ---
    # Picks the visual flavor of the encirclement (independent of TIER, which
    # stays palette-locked). Valid values: 'sauron' (default — black + red eye-slit),
    # 'goth' (original purple gooey halo), 'obsidian' (black mirror with iridescent
    # sheen), 'void' (event-horizon distortion rings). NULL = render default.
    # Tier governs rank; variant governs aesthetic — the two axes are orthogonal.
    flare_encirclement_variant: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # --- END FLARE ENCIRCLEMENT VARIANT ---

    # --- FLARE ENCIRCLEMENT OVERLAY (broken-machine family, §28, 2026-05-13) ---
    # Independent axis: an "overlay" sits ON TOP of the base encirclement
    # variant. Values: 'glitch' / 'cascade' / 'panic-a' / 'panic-b' / 'panic-c'
    # (the tournament round; collapses to 'panic' after winner selection).
    # NULL = no overlay. Orthogonal to flare_encirclement_variant. Migration
    # 0054 promotes existing glitch/cascade/panic variants to overlays and
    # resets their variant to 'sauron' (the default base).
    flare_encirclement_overlay: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # --- END FLARE ENCIRCLEMENT OVERLAY ---

    # --- FLARE CORNER VARIANT (admin-only alternative corner icons, 2026-05-13 §20) ---
    # Admins (is_admin OR any admin_* sub-flag) can override their corner badge
    # icon with a custom inline-SVG design (rocket / crown / vault / gavel /
    # atom / network). NULL = render default tier icon. The variant doesn't
    # change the corner TIER (still operator/commander/founder/etc.); it just
    # swaps the glyph rendered inside the badge. Migration 0045.
    flare_corner_variant: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # --- END FLARE CORNER VARIANT ---

    # --- FLARE CELEBRATION SEEN (one-shot upgrade modal ack, 2026-05-12 §15) ---
    # NULL + flare_tier='shadow_chancellor' → frontend shows the celebration
    # modal once (pick your encirclement variant). Set after the user
    # acknowledges. Migration 0043 backfills existing shadow_chancellor devs to
    # NOW() so they aren't retroactively prompted.
    flare_celebration_seen_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # --- END FLARE CELEBRATION SEEN ---

    # --- PROVISIONING ELIGIBILITY (flare-gated cloud-op self-service, 2026-05-11) ---
    # Backers earn 1 month of cloud-op self-provisioning eligibility per €25
    # backed. Stacking math at credit time: max(unlocked_until, NOW) + months×30d.
    # NULL/past = ineligible; future = eligible. provisioning_months_total is the
    # cumulative lifetime credit (never decremented) used for the "you've extended
    # N months total" stat in the Eligibility tab.
    provisioning_unlocked_until: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    provisioning_months_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    # --- END PROVISIONING ELIGIBILITY ---

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationship to AgentCard (one-to-many)
    agent_cards: Mapped[List["AgentCard"]] = relationship(
        "AgentCard", back_populates="developer", cascade="all, delete-orphan"
    )
    # --- ADDED: Relationship to DeveloperApiKey ---
    api_keys: Mapped[List["DeveloperApiKey"]] = relationship(
        "DeveloperApiKey", back_populates="developer", cascade="all, delete-orphan"
    )
    # --- END ADDED ---
    
    # --- ADDED: Organizations & Teams Relationships ---
    owned_organizations: Mapped[List["Organization"]] = relationship(
        "Organization", foreign_keys="Organization.owner_id", back_populates="owner"
    )
    organization_memberships: Mapped[List["OrganizationMember"]] = relationship(
        "OrganizationMember", foreign_keys="OrganizationMember.developer_id", back_populates="developer"
    )
    team_memberships: Mapped[List["TeamMember"]] = relationship(
        "TeamMember", foreign_keys="TeamMember.developer_id", back_populates="developer"
    )
    # --- END Organizations & Teams Relationships ---

    def __repr__(self):
        # --- MODIFIED: Add email and is_verified to repr ---
        return f"<Developer(id={self.id}, name='{self.name}', email='{self.email}', verified={self.is_verified})>"
        # --- END MODIFIED ---

# --- ADDED: Agent Model for OAuth Client Credentials ---
class Agent(Base):
    """SQLAlchemy model for registered agents."""
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    did: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_client_secret: Mapped[str] = mapped_column(String, nullable=False)
    creator_developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False
    )
    public_key_jwk: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String, default="active", nullable=False
    )  # active, suspended, revoked
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reputation_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)  # D4: default changed 100→0 (f029)
    liquid_balance = mapped_column(Numeric(precision=30, scale=6), default=0, nullable=False, index=True)
    staked_balance = mapped_column(Numeric(precision=30, scale=6), default=0, nullable=False, index=True)
    auto_compound_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)  # P8.24: Required by staking_rewards auto-compound endpoint

    # --- SPRINT 8 §7.1: Staking rewards tracking (f017_staking_auto_distribution) ---
    # These columns exist in the DB since f017 but were missing from the ORM model.
    last_reward_distribution: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment='Last time this agent received staking rewards'
    )
    total_rewards_earned: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(36, 18), server_default='0', nullable=True,
        comment='Cumulative staking rewards earned'
    )
    staking_tier: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment='Current staking tier (bronze/silver/gold/platinum/dynamic)'
    )
    # --- END SPRINT 8 §7.1 ---

    # --- SPRINT 1 §4.1: Enforcement fields (f029_enforcement_foundation) ---
    offense_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enforcement_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rewards_paused_until: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enforcement_status: Mapped[str] = mapped_column(
        String(20), default='active', nullable=False
    )  # 'active' | 'suspended' | 'revoked'  (≠ status which is registry status)
    last_offense_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reputation_bond_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0, nullable=False)
    reputation_bond_status: Mapped[str] = mapped_column(
        String(20), default='none', nullable=False
    )  # 'none' | 'locked' | 'matured' | 'forfeited'
    # --- END SPRINT 1 §4.1 ---
    # --- AGENTWORLD: Geolocation fields (f033) ---
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # --- END AGENTWORLD ---

    # --- Organization linking (f040) ---
    organization_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("organizations.id"), nullable=True
    )
    team_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("teams.id"), nullable=True
    )
    # --- END Organization linking ---

    # --- IRONHAND: Agent mTLS identity (f052) ---
    spiffe_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mtls_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa.false()
    )
    mtls_enrolled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # D6-802 (mig 0192): when an administrator revoked the agent's mTLS identity. While set, the agent's own
    # enable-mtls refuses and a coordinated reinstate restores nothing; an administrator's enrolment clears it.
    mtls_revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # --- END IRONHAND ---

    # --- CANARY system marker (Phase 1, 2026-05-04) ---
    is_canary: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa.false()
    )
    # --- END CANARY ---

    # --- FLARE — PB-1 backer cosmetic (2026-05-09) ---
    # Agent flare: starts on the agent that received the AVT from the fiat
    # purchase (anonymous flow → wallet agent; logged-in flow → selected agent).
    # Movable: dev can re-assign to any agent they own via POST /fiat/flare/move/.
    # Higher tier wins on multi-purchase (replaces existing if rank is higher).
    flare_tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    flare_granted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    flare_source_purchase_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("fiat_purchases.id", ondelete="SET NULL"), nullable=True
    )
    # Per-agent encirclement variant (2026-05-12 §15). Mirrors the Developer
    # column added in 0042 — lets agents wearing shadow_chancellor render
    # different aesthetics per agent. Migration 0043 backfills agents with
    # flare_tier='shadow_chancellor' to default 'sauron'.
    flare_encirclement_variant: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # Per-agent overlay (§28, 2026-05-13). Mirrors Developer.flare_encirclement_overlay.
    # NULL = inherit from the bearer-developer's overlay or no overlay.
    flare_encirclement_overlay: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # §23 (2026-05-14) — Dual-slot bearer flags (migration 0046).
    # Previously `flare_tier` alone tracked single-bearer status. That model
    # silently dropped a dev's corner-slot when moving the flare to an agent
    # (the renderer fell back to a canonical-default corner instead of the
    # dev's actual selected_corner_flare). Now: two independent boolean flags
    # — corner-slot bearer + encirclement-slot bearer — each constrained to
    # at most one agent per developer (enforced in the equip endpoint, not
    # via a partial UNIQUE since agents.flare_tier can outlive a dev change).
    # Backfill in migration 0046 sets BOTH = TRUE for any agent with
    # flare_tier IS NOT NULL, preserving legacy single-bearer semantics.
    bears_corner_flare: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa.false()
    )
    bears_encirclement_flare: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa.false()
    )
    # Per-agent admin corner badge variant — mirrors Developer.flare_corner_variant
    # from §20. Admin-only mutation via PATCH /fiat/flare/agent/{did}/corner-variant.
    # NULL = use dev's selected variant (or default tier icon).
    flare_corner_variant: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # --- END FLARE ---

    # §pass15 (2026-05-15) — Tier C-1: last_health column.
    # Stores the most recent agent_health_checker probe result
    # ('healthy' / 'unhealthy' / 'unreachable') so the next cycle can
    # detect actual transitions. Previously the checker compared the probe
    # against `status`, which conflated health with governance state and
    # produced 100% false-positive change rate. See migration 0055.
    last_health: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # §COCKPITA R2 (mig 0168) — WHEN that verdict was earned.
    # ⚠ A COLUMN AND A SCHEMA FIELD ARE NOT ENOUGH: the migration created it and
    # `AgentRead` declared it, but until the ORM MODEL knew about it every
    # `agent.last_health_at` raised AttributeError and turned the agent-list endpoint
    # into a 500. Three places, and the first two look like the whole job.
    last_health_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship to Developer
    creator_developer: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[creator_developer_id], backref="created_agents"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_agents_did", "did"),
        Index("ix_agents_client_id", "client_id"),
        Index("ix_agents_status", "status"),
        Index("ix_agents_creator_developer_id", "creator_developer_id"),
        Index("ix_agents_enforcement_status", "enforcement_status"),
        Index("ix_agents_enforcement_level", "enforcement_level"),
    )
    
    def __repr__(self):
        return f"<Agent(id={self.id}, did='{self.did}', client_id='{self.client_id}', status='{self.status}')>"
# --- END ADDED ---


# --- AgentCard Model ---
class AgentCard(Base):
    """SQLAlchemy model for storing Agent Card metadata."""
    __tablename__ = "agent_cards"

    # Using UUID for the primary key
    id: Mapped[uuid.UUID] = mapped_column(
        SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Foreign key to the developer who owns this card
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False, index=True
    )
    # --- OWL22 OPTION B: Agent↔Card linkage via agent_did ---
    agent_did: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True,
        doc="DID of the agent this card belongs to. Set during onboarding. Nullable for legacy cards."
    )
    # --- END OWL22 ---
    
    # Store the full Agent Card JSON data
    # JSONB is generally preferred in PostgreSQL for performance if available
    # SQLAlchemy's JSON type maps appropriately based on dialect
    card_data: Mapped[Dict[str, Any]] = mapped_column(PG_JSONB, nullable=False)  # R57: jsonb everywhere since mig 0174 (was json on four create_all operators)

    # Extracted fields for easier querying and indexing
    # Ensure these fields are populated correctly in CRUD operations
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True) # Allow nullable description
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # §DISCREFINE (mig 0153): owner-set. Hidden from discovery/search/facets; admins still
    # see it, marked. NOT access control — a direct DID lookup still resolves, because a
    # counterparty handed the DID must still be able to read the card to speak A2A to it.
    # §LISTPROP (2026-09-09): the CARD's content is still never exported to peers, but the
    # FACT is — an unlisted native card leaves as a tombstone (DID + one extension) so a peer
    # holding a stale mirror can hide it. On a MIRROR row this column is written by exactly
    # one thing, that tombstone; see services/listing_propagation.py.
    unlisted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # --- Option C Phase 3 (2026-05-17) — pull-sync watermark ---
    # agent_card_pullsync worker writes these on each fetch from the agent's
    # /.well-known/agent-card.json. Nullable for legacy cards never pulled.
    last_pulled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="Last time the pull-sync worker successfully fetched this agent's well-known card."
    )
    last_pulled_etag: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        doc="ETag from the agent's last 200/304 response — used for If-None-Match short-circuit."
    )
    # §FEDSYNCTRUTH (2026-09-03, mig 0169) — the pull CURSOR. `last_pulled_at` moves only on a
    # 200/304, so a card that always fails (dead host, internal host) never moved and the same
    # stalest 100 were handed to every cycle; nothing behind them was ever asked. Every ATTEMPT
    # stamps these three; consecutive failures back off exponentially (capped at a week).
    last_pull_attempt_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="Last time the pull-sync worker TRIED this card (any outcome) — the candidate cursor."
    )
    last_pull_status: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
        doc="Outcome of the last attempt: 200 | 304 | 4xx | 5xx | timeout | error | skipped."
    )
    pull_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0,
        doc="Consecutive failed attempts — drives the retry backoff; reset to 0 on 200/304."
    )

    # Relationship back to Developer (many-to-one)
    developer: Mapped["Developer"] = relationship("Developer", back_populates="agent_cards")

    # Explicit indexes (optional if index=True used on columns, but good for clarity)
    # Note: Indexes on `name` and `description` might benefit from specific types
    # like `text_pattern_ops` in PostgreSQL for LIKE queries, configured via postgresql_using='gin' or similar.
    # A GIN index on `card_data` could be useful for deep JSON searches later.
    __table_args__ = (
        Index("ix_agent_cards_name", "name"),
        Index("ix_agent_cards_description", "description"), # Indexing description
        Index("ix_agent_cards_is_active", "is_active"),
        Index("ix_agent_cards_last_pulled_at", "last_pulled_at"),
        Index("ix_agent_cards_last_pull_attempt_at", "last_pull_attempt_at"),  # §FEDSYNCTRUTH mig 0169
        # §FEDSYNC-V2 (2026-08-05) — every federation export filters and sorts on
        # updated_at (id tiebreak); without this index each peer pull was a
        # full-table seq scan + sort (measured 9,142 buffers/68ms warm, 30s cold
        # during the load-722 incident; 2 buffers/0.09ms with the index).
        # Built online fleet-wide 2026-08-05; migration 0144 covers new nodes.
        Index("ix_agent_cards_updated_at_id", "updated_at", "id"),
        # Example GIN index for PostgreSQL (requires specific dialect setup):
        # Index('ix_agent_cards_card_data_gin', card_data, postgresql_using='gin'),
    )

    def __repr__(self):
        return f"<AgentCard(id={self.id}, name='{self.name}', developer_id={self.developer_id})>"


# --- Option C Phase 9.a (2026-05-17) — JWS signing key history ---
class AgentSigningKey(Base):
    """Per-agent EdDSA signing-key rotation history.

    `agents.public_key_jwk` always mirrors the current (un-expired) key, but
    verifiers also accept older keys during the grace window (default 7 days).
    Rotation increments `rotation_seq`; old row is marked expired-at-grace via
    the admin endpoint.
    """
    __tablename__ = "agent_signing_keys"

    agent_did: Mapped[str] = mapped_column(String(255), primary_key=True)
    rotation_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_jwk: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="EdDSA")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="NULL = current; set to NOW() + grace days when rotation happens."
    )

    __table_args__ = (
        Index("ix_agent_signing_keys_did", "agent_did"),
        Index(
            "ix_agent_signing_keys_expires", "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentSigningKey(did={self.agent_did}, seq={self.rotation_seq}, expires={self.expires_at})>"


# --- Registry Card v0.3 (Migration 0079_rc_v03, 2026-05-21) ---
class RegistryCard(Base):
    """Singleton: the local registry's own published v0.3 registry card.

    Operator-editable subset (description, tags, operator persona, visual,
    commitments, links) is stored in card_json. The card builder overlays
    LOCKED fields (identity, capabilities, federation, policy, economic,
    stats, lifecycle) at serve time from live system state.

    Exactly one row (id=1) — CHECK constraint enforces singleton.
    """
    __tablename__ = "registry_card"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1,
        doc="Always 1 — singleton enforced via CHECK (id = 1) at DB level."
    )
    card_json: Mapped[Dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False,
        doc="Operator-editable subset of the v0.3 card. Builder overlays LOCKED fields at serve time."
    )
    card_etag: Mapped[str] = mapped_column(
        String(80), nullable=False,
        doc="SHA-256 prefix of the canonical card JSON. Drives If-None-Match conditional GETs."
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True,
        doc="Developer who last wrote this card via PUT /api/v1/admin/registry-card."
    )

    def __repr__(self) -> str:
        return f"<RegistryCard(etag={self.card_etag[:12]}..., updated_at={self.updated_at})>"


class RegistryCardAsset(Base):
    """Durable BYTES for the registry card's icon / operator avatar (mig 0141).

    The upload route writes the image to STATIC_DIR/registry-cards/<slug>/ for cheap
    static serving — but STATIC_DIR is the BUILT FRONTEND directory, so those bytes
    are destroyed by every container recreate and every image rebuild while
    card_json.visual.icon_url keeps pointing at them. The operator's logo vanished
    with no error anywhere. This table is the source of truth; the file on disk is a
    cache, rehydrated from here at startup.

    Not columns on RegistryCard: that row's card_json is canonicalised, hashed into
    card_etag and SIGNED on every serve, so image bytes do not belong in it.
    """
    __tablename__ = "registry_card_assets"

    kind: Mapped[str] = mapped_column(
        String(16), primary_key=True,
        doc="'icon' or 'avatar' — one row per kind, mirroring the singleton card."
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    ext: Mapped[str] = mapped_column(String(8), nullable=False, doc="'png' or 'jpg'.")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<RegistryCardAsset(kind={self.kind}, {self.size_bytes}B, {self.sha256[:12]}...)>"


class RegistrySigningKey(Base):
    """Per-registry EdDSA signing-key rotation history (mirror of AgentSigningKey).

    Used to sign the canonical fields of the registry card per spec §2
    (signature.signed_canonical list). Verifiers fetch the public JWK from
    /.well-known/registry-jwks.json and verify the detached JWS in
    card.signature.value.

    Auto-minted on first card serve (registry_card_keystore.get_or_mint).
    Rotation increments rotation_seq; old row marked expires_at = NOW() + 7 days.
    """
    __tablename__ = "registry_signing_keys"

    registry_spiffe_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    rotation_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_jwk: Mapped[Dict[str, Any]] = mapped_column(PG_JSONB, nullable=False)
    private_pem_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False,
        doc="AES-GCM-encrypted PEM blob. Key derived from REGISTRY_SIGNING_KEY_PASSPHRASE env."
    )
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="EdDSA")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="NULL = current; set to NOW() + 7 days at rotation."
    )

    __table_args__ = (
        Index("ix_registry_signing_keys_spiffe", "registry_spiffe_id"),
        Index(
            "ix_registry_signing_keys_expires", "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (f"<RegistrySigningKey(spiffe={self.registry_spiffe_id}, "
                f"seq={self.rotation_seq}, expires={self.expires_at})>")
# --- END Registry Card v0.3 ---


# --- ADDED: DeveloperApiKey Model ---
class DeveloperApiKey(Base):
    """SQLAlchemy model for storing developer-specific programmatic API keys."""
    __tablename__ = "developer_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    developer_id: Mapped[int] = mapped_column(Integer, ForeignKey("developers.id"), nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False, index=True) # e.g., "avreg_"
    hashed_key: Mapped[str] = mapped_column(String, nullable=False, unique=True) # bcrypt hash (legacy verify path)
    # Deterministic SHA-256 of the full key for O(1) indexed lookup (added 2026-05-31).
    # Nullable so pre-existing rows backfill lazily; UNIQUE (Postgres allows many NULLs).
    key_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True) # User-provided description
    # --- AUTH LIFECYCLE (AL-4, mig 0125, 2026-07-24) ---
    # scopes: JSONB list. Existing keys grandfather to ['*'] (full developer
    # authority — MCP bridge keys keep working). New keys may be minted narrower;
    # enforcement is opt-in per route (require_api_key_scope).
    scopes: Mapped[List[str]] = mapped_column(JSON, nullable=False, server_default='["*"]', default=lambda: ["*"])
    # expires_at: optional forced-rotation expiry. NULL = never (all existing keys).
    # New keys default to API_KEY_DEFAULT_TTL_DAYS at mint (0 = non-expiring).
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # --- END AUTH LIFECYCLE ---

    developer: Mapped["Developer"] = relationship("Developer", back_populates="api_keys")

    def __repr__(self):
        return f"<DeveloperApiKey(id={self.id}, developer_id={self.developer_id}, prefix='{self.key_prefix}', active={self.is_active})>"
# --- END ADDED ---

# --- ADDED: PeerRegistry Model for Federated Registry ---
class PeerRegistry(Base):
    """SQLAlchemy model for registered peer AgentVault Registry instances."""
    __tablename__ = "peer_registries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    base_url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    admin_contact_email: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, default="PENDING_APPROVAL", nullable=False
    )  # PENDING_APPROVAL, ACTIVE, INACTIVE, REJECTED
    hashed_shared_secret: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # For future inter-registry auth
    public_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # For future inter-registry auth
    federation_access_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Dedicated field for federation auth token
    discovery_auth_info: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # JSONB for auth configuration
    interaction_auth_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # JSONB for interaction auth
    registered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    last_synced_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Health check fields
    health_check_failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_health_check_attempt_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # RCA 2026-07-10 (federation-peer ratchet, mig 0122): WHY a row went INACTIVE.
    # NULL = legacy/unknown → the revival prober may auto-revive on a verified probe.
    # Reasons in the admin guard set (admin/owner/revoked/debris…) are never auto-revived.
    deactivated_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # OWL25 Phase 3: Auto-slash threshold configuration
    # If enabled, incoming slash requests from this peer up to max_avt are auto-approved.
    # Amounts exceeding the threshold require manual admin approval.
    auto_slash_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False,
        comment='Enable auto-slash for incoming requests from this peer'
    )
    auto_slash_max_avt: Mapped[Decimal] = mapped_column(
        Numeric(30, 6), default=0, server_default='0', nullable=False,
        comment='Max AVT amount auto-slashable without admin approval (0=disabled)'
    )

    # --- SPRINT 8 §5.1: Bayesian cross-registry trust columns (f030) ---
    total_interactions: Mapped[int] = mapped_column(
        Integer, default=0, server_default='0', nullable=False,
        comment='Cumulative count of cross-registry interactions with this peer'
    )
    disputes_lost_with: Mapped[int] = mapped_column(
        Integer, default=0, server_default='0', nullable=False,
        comment='Count of disputes lost where this peer was claimant'
    )
    bayesian_discount: Mapped[float] = mapped_column(
        Float, default=1.0, server_default='1.0', nullable=False,
        comment='Trust multiplier applied to cross-registry scores (1.0=full, 0.0=zero)'
    )
    last_interaction_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment='Timestamp of most recent cross-registry interaction'
    )
    inactivity_leak_start: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment='Timestamp from which inactivity discount starts accumulating'
    )
    # --- END SPRINT 8 ---

    # --- 2026-04-21 (0016_peer_topology_fields): federation hierarchy ---
    peer_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default='direct_peer', index=True,
        comment='Federation tier: frame | direct_peer | discovered | cloud_operator'
    )
    operator_did: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment='DID of the federation license attached to this peer (nullable for legacy/discovered rows)'
    )
    parent_registry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("peer_registries.id", ondelete="SET NULL"), nullable=True,
        comment='For BFS-discovered peers, the direct peer that led here (null for directly-added rows)'
    )
    hop_distance: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment='BFS hop depth: 1 = directly configured, 2+ = discovered via crawl'
    )
    trust_domain: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment='SPIFFE trust domain for frame peers (e.g. frame-b.theprotocol.cloud); null for non-frames'
    )
    discovered_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment='When BFS first discovered this row (null for directly-added)'
    )
    # --- END 0016 ---

    # --- 2026-04-21 (0017_peer_topology_last_seen): chain-reachability signal ---
    last_seen_in_topology_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment=('Last BFS cycle that observed this peer in fresh topology output. '
                 'Drift rule 3 suppresses when fresh — chain-reachable peers are '
                 'federated, not partial-teardowns.')
    )
    # --- END 0017 ---

    # --- 2026-04-21 (0018_frame_invitations): SPIRE bundle endpoint for frames ---
    spiffe_bundle_endpoint_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment=('SPIRE bundle endpoint URL for peer_type=frame rows. Used by '
                 'FrameTrustManager to re-fetch the peer\'s trust bundle. '
                 'Standard SPIFFE path: https://<trust-domain>:8443/.well-known/spiffe/bundle')
    )
    # --- END 0018 ---

    # --- Reachability (0128_peer_reachability, 2026-07-24) ---
    # `last_synced_at` alone could not tell "healthy" from "never answered once" — the
    # frame-c gap hid for seven weeks behind ACTIVE + failures=0. These record what the
    # federation fan-out already computes, so reachability is reportable and alertable.
    last_sync_attempt_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="When we last TRIED. NULL + last_synced_at NULL = never even attempted."
    )
    last_sync_error: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        doc="Why the last attempt failed, verbatim enough to diagnose "
            "(e.g. 'HTTP 401 untrusted trust domain', 'SSL hostname mismatch')."
    )
    consecutive_sync_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0,
        doc="Reset to 0 on success. Distinct from health_check_failure_count, which "
            "tracks the health prober, not the federation corridor."
    )

    # --- S3 (0127_peer_spiffe_bind, 2026-07-24): the SVID this peer presents ---
    spiffe_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True,
        comment=('The exact SPIFFE ID this peer authenticates with, e.g. '
                 'spiffe://<trust-domain>/operator/<slug>/registry. Lets '
                 'require_peer_registry_identity bind an incoming SVID to an ACTIVE '
                 'peer row instead of only shape-checking it. NULL = not yet stamped '
                 '(legacy rows); enforcement is gated on FEDERATION_REQUIRE_PEER_SPIFFE_BIND.')
    )
    # --- END S3 ---

    # --- §FEDLICENCE (0182_fed_licence_certs, 2026-09-28): the verdict THIS registry reached about the peer's network
    # licence, recomputed every federation-sync cycle from the peer's signed card and the issuer's signed list.
    # genesis · licensed · unlicensed · expired · revoked · suspended · unverified · invalid; NULL = never evaluated.
    licence_state: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    licence_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    licence_checked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    licence_reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    # --- END §FEDLICENCE ---

    # Relationships
    owner_developer: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[owner_developer_id], backref="owned_peer_registries"
    )
    approved_by_developer: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[approved_by_developer_id], backref="approved_peer_registries"
    )

    # PB-2 routed-fiat: per-operator HMAC secret for mainframe → operator
    # routed-settle callbacks. NULL ⇒ derive from FEDERATION_INTERNAL_SECRET
    # (sandbox shortcut). Production: admin issues a per-operator secret at
    # peer-activation time; rotatable. (Migration 0038, 2026-05-09.)
    callback_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # --- Registry Card v0.3 (Migration 0079_rc_v03, 2026-05-21) ---
    # Cached copy of the peer's /.well-known/registry-card.json body, fetched by
    # federation_sync._sync_registry_card on its 5-min cycle. ETag drives
    # If-None-Match round-trips so most cycles return 304 with no payload.
    # card_signature_verified records the result of the 3-way SPIFFE check
    # (card.identity.spiffe_id == mTLS-presented SVID == sovereign-variant catalog SVID).
    cached_registry_card: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        PG_JSONB, nullable=True,
        comment="Cached v0.3 registry card body from this peer. Populated by federation_sync."
    )
    card_last_pulled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Wall-clock when federation_sync last successfully fetched (200 or 304) this peer's card."
    )
    card_etag: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True,
        comment="Peer's ETag from last fetch. Sent as If-None-Match next cycle."
    )
    card_signature_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False,
        comment="True if last fetched card's JWS signature verified against peer's JWKS AND 3-way SPIFFE match passed."
    )
    card_signature_kid: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="kid (key-id) of the signing key that verified the last fetched card."
    )
    # --- END Registry Card v0.3 ---

    # Indexes
    __table_args__ = (
        Index("ix_peer_registries_name", "name"),
        Index("ix_peer_registries_status", "status"),
        Index("ix_peer_registries_base_url", "base_url"),
        Index("ix_peer_registries_owner_developer_id", "owner_developer_id"),
    )

    def __repr__(self):
        return f"<PeerRegistry(id={self.id}, name='{self.name}', status='{self.status}', owner_id={self.owner_developer_id})>"
# --- END ADDED ---

# --- ADDED: BootstrapToken Model for Agent Onboarding ---
class BootstrapToken(Base):
    """
    SQLAlchemy model for single-use bootstrap tokens used in agent onboarding.
    
    Bootstrap tokens are temporary, single-use tokens that allow a new agent
    to register itself in the system. They provide a secure link between the
    creator (developer) who authorized the agent's creation and the agent itself.
    
    Attributes:
        id: Primary key identifier
        token_value: Legacy column; since D6-283 a marker derived from the hash ("sha256:<hash>"), never the token
        creator_developer_id: ID of the developer who created the token
        agent_type_hint: Optional hint about the type of agent being created
        requested_by: Optional identifier for the requester (e.g., 'cli-user-xyz')
        created_at: Timestamp when the token was created
        expires_at: Timestamp when the token expires
        used_at: Timestamp when the token was used (None if unused)
        used_by_agent_did: DID of the agent that used the token (None if unused)
    """
    __tablename__ = "bootstrap_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    token_value: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # P23-001: SHA-256 hash. Populated for new tokens issued 2026-04-30+.
    # D6-283: validation looks up by this hash only; the plaintext is no longer stored (crud/bootstrap_token.py).
    # SEC-05: migration 0193 gave every row written before D6-283 its marker (and its hash where it had none).
    token_value_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    creator_developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False
    )
    agent_type_hint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requested_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    used_by_agent_did: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # --- ADDED: is_used boolean field for compatibility ---
    is_used: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    # --- END ADDED ---
    
    # Relationship to Developer
    creator_developer: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[creator_developer_id], backref="bootstrap_tokens"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_bootstrap_tokens_token_value", "token_value"),
        Index("ix_bootstrap_tokens_expires_at", "expires_at"),
        Index("ix_bootstrap_tokens_creator_developer_id", "creator_developer_id"),
    )
    
    def __repr__(self):
        return f"<BootstrapToken(id={self.id}, creator_id={self.creator_developer_id}, expires_at={self.expires_at}, used={self.used_at is not None})>"
# --- END ADDED ---

# --- ADDED: Dispute and Evidence Models for DDR System ---
class Dispute(Base):
    """
    SQLAlchemy model for disputes between agents in the Decentralized Dispute Resolution system.
    
    Disputes represent claims between two agents (complainant and defendant) that require
    resolution through the decentralized justice system.
    
    Attributes:
        id: Primary key identifier
        status: Current status of the dispute (OPEN, VOTING, CLOSED)
        ruling: Final ruling of the dispute (IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT, DISMISSED, null if not resolved)
        complainant_did: DID of the agent filing the complaint
        defendant_did: DID of the agent being accused
        created_at: Timestamp when the dispute was created
        updated_at: Timestamp when the dispute was last updated
        evidence: Relationship to Evidence model (one-to-many)
    """
    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    status: Mapped[str] = mapped_column(
        String, default="OPEN", nullable=False
    )  # OPEN, VOTING, CLOSED
    ruling: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )  # IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT, DISMISSED
    complainant_did: Mapped[str] = mapped_column(String, nullable=False)
    defendant_did: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Relationship to Evidence (one-to-many)
    evidence: Mapped[List["Evidence"]] = relationship(
        "Evidence", back_populates="dispute", cascade="all, delete-orphan"
    )

    # ── Phase 3 trust-chain — referenced ZKP attestations ──────────────
    # JSON array of attestation UUID strings cited by the defendant as
    # exculpatory evidence. Slash weight is reduced based on this set.
    referenced_attestations: Mapped[Optional[List[str]]] = mapped_column(
        JSON, nullable=True
    )

    # ── X1 (2026-05-06) — soft int reference to refactoring_upgrade_contracts.id ──
    # Populated when a dispute is filed via /api/v1/contracts/{id}/malpractice.
    # Allows Disputes.vue to render a "View source contract →" link.
    # No FK constraint: matches the cross-registry-friendly convention used by
    # cross_registry_settlements.dispute_id (dispute may live on a remote registry).
    contract_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    # CONTRACT SPINE (mig 0129): spine contract id (ctr_…) this dispute is about;
    # rulings on such disputes settle the ESCROW, never wallet compensation.
    contract_ref: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Indexes
    __table_args__ = (
        Index("ix_disputes_status", "status"),
        Index("ix_disputes_complainant_did", "complainant_did"),
        Index("ix_disputes_defendant_did", "defendant_did"),
        Index("ix_disputes_created_at", "created_at"),
    )

    def __repr__(self):
        return f"<Dispute(id={self.id}, status='{self.status}', complainant='{self.complainant_did}', defendant='{self.defendant_did}')>"


class Evidence(Base):
    """
    SQLAlchemy model for evidence submitted in disputes.
    
    Evidence represents proof or documentation submitted by agents to support
    their claims in a dispute.
    
    Attributes:
        id: Primary key identifier
        dispute_id: Foreign key to the associated dispute
        submitter_did: DID of the agent submitting the evidence
        evidence_data: JSON data containing the evidence details
        created_at: Timestamp when the evidence was submitted
    """
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    dispute_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("disputes.id"), nullable=False
    )
    submitter_did: Mapped[str] = mapped_column(String, nullable=False)
    evidence_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Relationship back to Dispute (many-to-one)
    dispute: Mapped["Dispute"] = relationship("Dispute", back_populates="evidence")
    
    # Indexes
    __table_args__ = (
        Index("ix_evidence_dispute_id", "dispute_id"),
        Index("ix_evidence_submitter_did", "submitter_did"),
        Index("ix_evidence_created_at", "created_at"),
    )
    
    def __repr__(self):
        return f"<Evidence(id={self.id}, dispute_id={self.dispute_id}, submitter='{self.submitter_did}')>"
# --- END ADDED ---

# --- ADDED: AuditorFlagLog Model for Algorithmic Auditor System ---
class AuditorFlagLog(Base):
    """
    SQLAlchemy model for algorithmic auditor flags on suspicious agent behavior.
    
    The AuditorFlagLog stores findings from the automated auditor system that monitors
    for suspicious economic behavior, market manipulation, and other violations.
    
    Attributes:
        id: Primary key identifier
        flagged_agent_did: DID of the agent that has been flagged
        flag_type: Type of violation detected (e.g., PriceCollusion, MarketManipulation)
        severity: Severity level of the flag (LOW, MEDIUM, HIGH)
        details: JSON data containing evidence and detailed information about the flag
        created_at: Timestamp when the flag was created
    """
    __tablename__ = "auditor_flag_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    flagged_agent_did: Mapped[str] = mapped_column(String, nullable=False)
    flag_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(
        String, nullable=False
    )  # LOW, MEDIUM, HIGH
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_auditor_flag_logs_flagged_agent_did", "flagged_agent_did"),
        Index("ix_auditor_flag_logs_flag_type", "flag_type"),
        Index("ix_auditor_flag_logs_severity", "severity"),
        Index("ix_auditor_flag_logs_created_at", "created_at"),
    )
    
    def __repr__(self):
        return f"<AuditorFlagLog(id={self.id}, agent='{self.flagged_agent_did}', type='{self.flag_type}', severity='{self.severity}')>"
# --- END ADDED ---

# --- ADDED: Governance Models for Agent Senate ---
class GovernanceProposal(Base):
    """
    SQLAlchemy model for governance proposals in the Agent Senate system.
    
    Proposals represent motions that agents can vote on to collectively decide
    the future direction of the ecosystem. Voting power is determined by an
    agent's staked balance.
    
    Attributes:
        id: Primary key identifier
        proposer_did: DID of the agent who created the proposal
        title: Short title describing the proposal
        description: Detailed description of what the proposal seeks to achieve
        status: Current status (VOTING, PASSED, FAILED)
        created_at: Timestamp when the proposal was created
        end_timestamp: Timestamp when voting ends
        votes: Relationship to Vote model (one-to-many)
    """
    __tablename__ = "governance_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    proposer_did: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, default="VOTING", nullable=False
    )  # VOTING, PASSED, FAILED
    # P3/D2: veToken governance extensions
    proposal_type: Mapped[str] = mapped_column(
        String(20), default="standard", nullable=False
    )  # standard, policy_change
    policy_diff: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )  # JSON diff for policy_change proposals
    quorum_percent: Mapped[Optional[float]] = mapped_column(
        sa.Float(), nullable=True
    )  # Required quorum (e.g. 10.0 = 10% of total veToken power)
    pass_percent: Mapped[Optional[float]] = mapped_column(
        sa.Float(), nullable=True
    )  # Required pass threshold (e.g. 50.0 = simple majority, 66.0 = supermajority)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    end_timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # §MEMBERSHIP D2 (mig 0184): "<host trust domain>/<federation proposal id>" on a `federation_ballot` proposal, whose
    # members' result becomes this registry's one ballot in that federation proposal; NULL on every other proposal
    federation_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # §MEMBERSHIP (mig 0185): the numbers a real tally decided on, kept with the proposal. tally_weight_mode is the unit of
    # the two numbers ('lock' = veToken power, 'member' = members' points); all five NULL until a real tally
    tally_weight_mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tally_network_power: Mapped[Optional[float]] = mapped_column(sa.Float(), nullable=True)
    tally_quorum_required: Mapped[Optional[float]] = mapped_column(sa.Float(), nullable=True)
    tally_quorum_met: Mapped[Optional[bool]] = mapped_column(sa.Boolean(), nullable=True)
    tallied_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationship to Vote (one-to-many)
    votes: Mapped[List["Vote"]] = relationship(
        "Vote", back_populates="proposal", cascade="all, delete-orphan"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_governance_proposals_proposer_did", "proposer_did"),
        Index("ix_governance_proposals_status", "status"),
        Index("ix_governance_proposals_end_timestamp", "end_timestamp"),
        Index("ix_governance_proposals_created_at", "created_at"),
        Index("ix_governance_proposals_proposal_type", "proposal_type"),
        # §MEMBERSHIP D2 (mig 0184): one members' vote per federation proposal it decides
        Index("uq_governance_proposals_federation_ref", "federation_ref", unique=True,
              postgresql_where=sa.text("federation_ref IS NOT NULL")),
    )
    
    def __repr__(self):
        return f"<GovernanceProposal(id={self.id}, title='{self.title}', type='{self.proposal_type}', status='{self.status}', proposer='{self.proposer_did}')>"


class Vote(Base):
    """
    SQLAlchemy model for votes cast on governance proposals.
    
    Each vote captures not just the voter's choice but also their voting power
    at the time of the vote, which is determined by their staked balance.
    
    Attributes:
        id: Primary key identifier
        proposal_id: Foreign key to the associated proposal
        voter_did: DID of the agent casting the vote
        vote: Boolean indicating vote direction (True=FOR, False=AGAINST)
        voting_power: The agent's staked balance at the time of voting
        created_at: Timestamp when the vote was cast
    """
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("governance_proposals.id"), nullable=False
    )
    voter_did: Mapped[str] = mapped_column(String, nullable=False)
    vote: Mapped[bool] = mapped_column(Boolean, nullable=False)  # True=FOR, False=AGAINST
    voting_power: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False, default=0)  # Snapshot of veToken power
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # P3/D2: Vote reason
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Relationship back to GovernanceProposal (many-to-one)
    proposal: Mapped["GovernanceProposal"] = relationship("GovernanceProposal", back_populates="votes")
    
    # Indexes and constraints
    __table_args__ = (
        UniqueConstraint("proposal_id", "voter_did", name="uix_votes_proposal_voter"),  # One vote per agent per proposal
        Index("ix_votes_proposal_id", "proposal_id"),
        Index("ix_votes_voter_did", "voter_did"),
        Index("ix_votes_created_at", "created_at"),
    )
    
    def __repr__(self):
        vote_str = "FOR" if self.vote else "AGAINST"
        return f"<Vote(id={self.id}, proposal_id={self.proposal_id}, voter='{self.voter_did}', vote={vote_str}, power={self.voting_power})>"
# --- END ADDED ---

# --- ADDED: RefactoringUpgradeContract Model for Agent Workshop ---
class RefactoringUpgradeContract(Base):
    """
    SQLAlchemy model for Refactoring & Upgrade Contracts in the Agent Workshop system.
    
    The RUC represents a formal agreement between a Client Agent who needs work done
    and an Upgrader Agent who will perform the work. This contract governs the entire
    lifecycle of an agent-to-agent upgrade service.
    
    Attributes:
        id: Primary key identifier
        client_agent_did: DID of the agent requesting the work
        upgrader_agent_did: DID of the agent performing the work
        status: Current status of the contract (PROPOSED, ACCEPTED, IN_PROGRESS, etc.)
        scope_description: Text description of the work to be done
        source_code_repo_url: Git repository URL of the Client Agent's code
        source_code_branch: Specific branch the Upgrader Agent must work on
        acceptance_criteria: JSON field defining conditions for success
        payment_amount: Agreed-upon payment for successful completion
        access_credentials_id: Reference to temporary, revocable access token
        created_at: Timestamp when the contract was created
        updated_at: Timestamp when the contract was last updated
        accepted_at: Timestamp when the Upgrader Agent accepted the contract
        completed_at: Timestamp when the work was completed
        pr_url: URL of the pull request containing the completed work
    """
    __tablename__ = "refactoring_upgrade_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    client_agent_did: Mapped[str] = mapped_column(String, nullable=False, index=True)
    upgrader_agent_did: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String, default="PROPOSED", nullable=False, index=True
    )  # PROPOSED, ACCEPTED, IN_PROGRESS, PENDING_MERGE, COMPLETED, FAILED, DISPUTED
    scope_description: Mapped[str] = mapped_column(String, nullable=False)
    source_code_repo_url: Mapped[str] = mapped_column(String, nullable=False)
    source_code_branch: Mapped[str] = mapped_column(String, nullable=False)
    acceptance_criteria: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    access_credentials_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # f045: Link A2A payment settlement to contract for dispute evidence chain
    payment_transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    accepted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Indexes
    __table_args__ = (
        Index("ix_ruc_client_agent_did", "client_agent_did"),
        Index("ix_ruc_upgrader_agent_did", "upgrader_agent_did"),
        Index("ix_ruc_status", "status"),
        Index("ix_ruc_created_at", "created_at"),
    )
    
    def __repr__(self):
        return f"<RefactoringUpgradeContract(id={self.id}, client='{self.client_agent_did}', upgrader='{self.upgrader_agent_did}', status='{self.status}')>"
# --- END ADDED ---

# --- ADDED: SystemEvent Model for Activity Feed ---
class SystemEvent(Base):
    """
    SQLAlchemy model for system-wide events displayed in the activity feed.
    
    SystemEvents track important activities across the entire AgentVault ecosystem,
    providing transparency and real-time updates to all participants.
    
    Attributes:
        id: Primary key identifier
        event_type: Type of event (e.g., AGENT_ONBOARDED, FEDERATION_REQUEST, REWARD_CYCLE)
        title: Short, human-readable title for the event
        description: Detailed description of what happened
        metadata: JSON field for additional event-specific data
        created_at: Timestamp when the event occurred
    """
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    event_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_system_events_event_type", "event_type"),
        Index("ix_system_events_created_at", "created_at"),
    )
    
    def __repr__(self):
        return f"<SystemEvent(id={self.id}, type='{self.event_type}', title='{self.title}', created_at={self.created_at})>"
# --- END ADDED ---

# --- ADDED: AgentLog Model for Agent Activity Logs ---
class AgentLog(Base):
    """
    SQLAlchemy model for agent activity logs.
    
    Stores logs generated by agents during their operations, providing
    transparency and debugging capabilities for developers.
    
    Attributes:
        id: Primary key identifier
        agent_did: DID of the agent that generated the log
        timestamp: When the log was created
        level: Log level (DEBUG, INFO, WARN, ERROR)
        message: The log message
        metadata: Additional structured data (JSON)
        source: Source component/module that generated the log
    """
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    agent_did: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    level: Mapped[str] = mapped_column(
        String, nullable=False,
        # Ensure valid log levels
        # Note: Add check constraint in migration
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    log_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    # Indexes for efficient querying
    __table_args__ = (
        Index("ix_agent_logs_agent_did", "agent_did"),
        Index("ix_agent_logs_timestamp", "timestamp"),
        Index("ix_agent_logs_level", "level"),
        Index("ix_agent_logs_agent_did_timestamp", "agent_did", "timestamp"),
    )
    
    def __repr__(self):
        return f"<AgentLog(id={self.id}, agent='{self.agent_did}', level='{self.level}', timestamp={self.timestamp})>"
# --- END ADDED ---

# --- ADDED: Staking Enhancement Models ---
class IdempotencyKey(Base):
    """
    SQLAlchemy model for idempotency keys to prevent duplicate operations.
    
    Idempotency keys ensure that if the same operation is requested multiple times
    (e.g., due to network issues), it will only be executed once.
    
    Attributes:
        key: The unique idempotency key provided by the client
        agent_id: ID of the agent that made the request
        response_data: The response that was returned for this operation
        created_at: When this key was first used
    """
    __tablename__ = "idempotency_keys"
    
    key: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    response_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    
    def __repr__(self):
        return f"<IdempotencyKey(key='{self.key}', agent_id='{self.agent_id}', created_at={self.created_at})>"


class Stake(Base):
    """
    SQLAlchemy model for individual staking positions.
    
    Each stake represents a specific amount of tokens locked by an agent
    for a certain period to earn rewards and voting power.
    
    Attributes:
        id: Unique identifier for the stake
        agent_id: Foreign key to the agent who owns this stake
        agent_did: DID of the agent (denormalized for performance)
        amount: Amount of tokens staked
        staked_at: When the stake was created
        unstaked_at: When the stake was unstaked (null if still active)
        is_active: Whether this stake is currently active
        teg_stake_id: Reference to the stake in the TEG layer
        lock_period_days: How long the tokens are locked
        apy_rate: The APY rate at the time of staking
    """
    __tablename__ = "stakes"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    agent_did: Mapped[str] = mapped_column(String, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=6), nullable=False)
    staked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    unstaked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    teg_stake_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    lock_period_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    apy_rate: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=2), default=Decimal("12.5"), nullable=False
    )
    # P3/D2: veToken governance fields
    lock_expiry_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ve_power_snapshot: Mapped[float] = mapped_column(
        sa.Float(), default=0.0, nullable=False
    )
    
    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", backref="stakes")
    transactions: Mapped[List["StakeTransaction"]] = relationship(
        "StakeTransaction", back_populates="stake"
    )
    rewards: Mapped[List["StakingReward"]] = relationship(
        "StakingReward", back_populates="stake", cascade="all, delete-orphan"
    )
    
    # Composite index for efficient queries
    __table_args__ = (
        Index("ix_stakes_active_by_agent", "agent_id", "is_active"),
    )
    
    def __repr__(self):
        return f"<Stake(id='{self.id}', agent_did='{self.agent_did}', amount={self.amount}, active={self.is_active})>"


class StakeTransaction(Base):
    """
    Enhanced SQLAlchemy model for stake-related transactions.
    
    Records all staking operations including stake, unstake, and reward claims
    with full traceability to the TEG layer.
    
    Attributes:
        id: Unique transaction identifier (UUID as string)
        agent_id: Foreign key to the agent
        stake_id: Reference to the associated stake (if applicable)
        transaction_type: Type of transaction (stake, unstake, claim_reward)
        amount: Amount involved in the transaction
        timestamp: When the transaction occurred
        teg_transaction_id: Reference to the TEG layer transaction
        status: Transaction status (completed, pending, failed)
        metadata: Additional transaction details
    """
    __tablename__ = "stake_transactions"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    stake_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("stakes.id"), nullable=True, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=6), nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    teg_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, default="completed", nullable=False, index=True
    )
    transaction_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, name="metadata")
    
    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", backref="stake_transactions")
    stake: Mapped[Optional["Stake"]] = relationship("Stake", back_populates="transactions")
    
    def __repr__(self):
        return f"<StakeTransaction(id='{self.id}', type='{self.transaction_type}', amount={self.amount}, status='{self.status}')>"


class StakingReward(Base):
    """
    SQLAlchemy model for tracking staking rewards.
    
    Records rewards earned by staking positions and tracks whether
    they have been claimed or not.
    
    Attributes:
        id: Primary key
        agent_id: Foreign key to the agent earning the reward
        stake_id: Foreign key to the stake that earned this reward
        amount: Amount of reward earned
        earned_at: When the reward was calculated
        claimed_at: When the reward was claimed (null if unclaimed)
        is_claimed: Whether the reward has been claimed
        claim_transaction_id: Reference to the claim transaction
    """
    __tablename__ = "staking_rewards"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    stake_id: Mapped[str] = mapped_column(
        String, ForeignKey("stakes.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=6), nullable=False)
    earned_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    claimed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_claimed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    claim_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", backref="staking_rewards")
    stake: Mapped["Stake"] = relationship("Stake", back_populates="rewards")
    
    def __repr__(self):
        return f"<StakingReward(id={self.id}, agent_id={self.agent_id}, amount={self.amount}, claimed={self.is_claimed})>"


class StakingApyTier(Base):
    """
    SQLAlchemy model for APY tier configuration.
    
    Defines the different APY rates available based on lock periods
    and minimum staking amounts.
    
    Attributes:
        id: Primary key
        lock_period_days: How long tokens must be locked
        apy_rate: Annual percentage yield for this tier
        min_amount: Minimum stake amount for this tier
        is_active: Whether this tier is currently available
        created_at: When this tier was created
    """
    __tablename__ = "staking_apy_tiers"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lock_period_days: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    apy_rate: Mapped[Decimal] = mapped_column(Numeric(precision=5, scale=2), nullable=False)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=6), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    def __repr__(self):
        return f"<StakingApyTier(id={self.id}, days={self.lock_period_days}, apy={self.apy_rate}%, min={self.min_amount})>"
# --- END ADDED ---


# --- AGENT METRICS MODELS ---
class AgentMetrics(Base):
    """
    SQLAlchemy model for aggregated agent performance metrics.
    
    Tracks cumulative statistics for each agent including request counts,
    response times, and success rates. Updated in real-time as agents
    process requests.
    
    Attributes:
        id: Primary key
        agent_id: Foreign key to the agent
        agent_did: DID of the agent (denormalized for performance)
        total_requests: Total number of API requests made
        successful_requests: Count of requests with 2xx status codes
        failed_requests: Count of requests with 4xx/5xx status codes
        total_response_time_ms: Sum of all response times for averaging
        last_request_at: Timestamp of the most recent request
        last_updated: When these metrics were last updated
        created_at: When metrics tracking began for this agent
    """
    __tablename__ = "agent_metrics"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, unique=True, index=True
    )
    agent_did: Mapped[str] = mapped_column(String, nullable=False, index=True)
    total_requests: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    successful_requests: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    failed_requests: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_response_time_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_request_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Relationship
    agent: Mapped["Agent"] = relationship("Agent", backref="metrics")
    
    def __repr__(self):
        return f"<AgentMetrics(agent_did='{self.agent_did}', requests={self.total_requests}, success_rate={self.success_rate}%)>"
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total_requests == 0:
            return 0.0
        return round((self.successful_requests / self.total_requests) * 100, 2)
    
    @property
    def avg_response_time(self) -> int:
        """Calculate average response time in milliseconds."""
        if self.successful_requests == 0:
            return 0
        return int(self.total_response_time_ms / self.successful_requests)


class AgentRequest(Base):
    """
    SQLAlchemy model for individual agent request logs.
    
    Records detailed information about each API request made by agents,
    used for calculating metrics and debugging performance issues.
    
    Attributes:
        id: Primary key
        agent_id: Foreign key to the agent
        agent_did: DID of the agent (denormalized)
        endpoint: The API endpoint that was called
        method: HTTP method (GET, POST, etc.)
        status_code: HTTP response status code
        response_time_ms: How long the request took in milliseconds
        error_message: Error details if the request failed
        request_metadata: Additional request details (headers, params, etc.)
        created_at: When this request was made (UTC timezone)
    """
    __tablename__ = "agent_requests"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    agent_did: Mapped[str] = mapped_column(String, nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String, nullable=False, index=True)
    method: Mapped[str] = mapped_column(String, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    
    # Relationship
    agent: Mapped["Agent"] = relationship("Agent", backref="requests")
    
    # Composite indexes for efficient queries
    __table_args__ = (
        Index("ix_agent_requests_agent_time", "agent_id", "created_at"),
        Index("ix_agent_requests_status_time", "status_code", "created_at"),
    )
    
    def __repr__(self):
        return f"<AgentRequest(agent_did='{self.agent_did}', {self.method} {self.endpoint}, status={self.status_code}, {self.response_time_ms}ms)>"


class AgentDailyStats(Base):
    """
    SQLAlchemy model for pre-aggregated daily agent statistics.
    
    Stores daily summaries to enable efficient historical queries
    without scanning millions of individual request records.
    
    Attributes:
        id: Primary key
        agent_id: Foreign key to the agent
        date: The date these stats are for
        requests_count: Total requests on this date
        success_count: Successful requests on this date
        error_count: Failed requests on this date
        avg_response_time_ms: Average response time for the day
        unique_endpoints: Number of distinct endpoints called
        created_at: When this record was created
    """
    __tablename__ = "agent_daily_stats"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    date: Mapped[datetime.date] = mapped_column(sa.Date(), nullable=False, index=True)
    requests_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_response_time_ms: Mapped[float] = mapped_column(sa.Float(), default=0, nullable=False)
    unique_endpoints: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Relationship
    agent: Mapped["Agent"] = relationship("Agent", backref="daily_stats")
    
    # Unique constraint to prevent duplicate entries
    __table_args__ = (
        sa.UniqueConstraint('agent_id', 'date', name='uq_agent_daily_stats_agent_date'),
        Index("ix_agent_daily_stats_agent_date", "agent_id", "date"),
    )
    
    def __repr__(self):
        return f"<AgentDailyStats(agent_id={self.agent_id}, date={self.date}, requests={self.requests_count})>"
# --- END AGENT METRICS MODELS ---

# --- OAUTH FEDERATION MODELS ---
class OAuthTokenExchange(Base):
    """
    SQLAlchemy model for tracking OAuth token exchanges between registries.
    
    Records all token exchanges for cross-registry authentication, providing
    an audit trail and enabling token revocation if needed.
    
    Attributes:
        id: Primary key (UUID)
        source_token_jti: JTI (JWT ID) of the incoming token
        issued_token_jti: JTI of the newly issued exchange token
        source_registry: URL of the registry that issued the source token
        agent_did: DID of the agent the tokens are for
        scope: OAuth scope granted in the exchange token
        expires_at: When the exchange token expires
        used_at: When the token was first used (for single-use enforcement)
        created_at: When the exchange occurred
    """
    __tablename__ = "oauth_token_exchanges"
    
    id: Mapped[uuid.UUID] = mapped_column(
        SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_token_jti: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    issued_token_jti: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    source_registry: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # RA3 (migration 0126): the row is the authority for single-use + revocation.
    # Introspection answers from these columns, not from the token alone.
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    constraints: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)

    # Indexes for efficient queries
    __table_args__ = (
        Index("ix_oauth_exchanges_agent_registry", "agent_did", "source_registry"),
        Index("ix_oauth_exchanges_expires", "expires_at"),
    )
    
    def __repr__(self):
        return f"<OAuthTokenExchange(id={self.id}, agent='{self.agent_did}', source='{self.source_registry}', expires={self.expires_at})>"


class RegistryTrustConfig(Base):
    """
    SQLAlchemy model for storing trusted registry configurations.
    
    Defines the trust relationships between registries for OAuth federation,
    including allowed operations and authentication credentials.
    
    Attributes:
        id: Primary key (UUID)
        registry_name: Human-friendly name of the trusted registry
        registry_url: Base URL of the trusted registry
        public_key: Public key for verifying tokens from this registry
        client_id: OAuth client ID for this registry relationship
        encrypted_client_secret: Encrypted OAuth client secret
        allowed_operations: Array of allowed operation types
        is_active: Whether this trust relationship is active
        created_at: When the trust was established
        updated_at: When the configuration was last modified
        created_by_developer_id: Admin who created this trust relationship
    """
    __tablename__ = "registry_trust_config"
    
    id: Mapped[uuid.UUID] = mapped_column(
        SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    registry_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    registry_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    public_key: Mapped[str] = mapped_column(
        Text, nullable=False,
        doc="The peer's JWKS URI (holds a URL, not key material — the admin CRUD has "
            "always stored public_key_url here; RA1 verification fetches it)."
    )
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    encrypted_client_secret: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="AES-GCM blob (registry_card_keystore helpers). Never stored plaintext."
    )
    # RA1/RA3 (migration 0126)
    issuer: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        doc="Exact `iss` this peer's tokens must carry. Falls back to registry_url."
    )
    max_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=6), nullable=True,
        doc="Per-peer ceiling minted into the exchanged token's constraints."
    )
    allowed_operations: Mapped[List[str]] = mapped_column(
        JSON, nullable=False, default=list
    )  # e.g., ["token_exchange", "introspection"]
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by_developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    
    # Relationships
    created_by: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[created_by_developer_id]
    )
    
    def __repr__(self):
        return f"<RegistryTrustConfig(id={self.id}, name='{self.registry_name}', url='{self.registry_url}', active={self.is_active})>"
# --- END OAUTH FEDERATION MODELS ---

# --- WEBHOOK MODELS ---
class DeveloperWebhook(Base):
    """
    SQLAlchemy model for developer webhook configurations.
    
    Webhooks allow developers to receive real-time notifications when
    specific events occur in the AgentVault system.
    
    Attributes:
        id: Primary key (UUID as string)
        developer_id: Foreign key to the developer who owns this webhook
        url: The endpoint URL to send webhook payloads to
        events: JSON array of event types to subscribe to
        secret: Secret key for webhook payload verification (HMAC-SHA256)
        is_active: Whether this webhook is currently active
        created_at: When the webhook was created
        updated_at: When the webhook was last modified
        last_triggered_at: When the webhook was last successfully triggered
        failure_count: Consecutive failure count (for disabling after threshold)
    """
    __tablename__ = "developer_webhooks"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    events: Mapped[List[str]] = mapped_column(PG_JSONB, nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_triggered_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Relationships
    developer: Mapped["Developer"] = relationship(
        "Developer", backref="webhooks"
    )
    deliveries: Mapped[List["WebhookDelivery"]] = relationship(
        "WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_developer_webhooks_developer_id", "developer_id"),
        Index("ix_developer_webhooks_is_active", "is_active"),
        Index("ix_developer_webhooks_developer_active", "developer_id", "is_active"),
    )
    
    def __repr__(self):
        return f"<DeveloperWebhook(id={self.id}, url='{self.url}', events={len(self.events)}, active={self.is_active})>"


class WebhookDelivery(Base):
    """
    SQLAlchemy model for tracking webhook delivery attempts.
    
    Records all webhook delivery attempts, including successful deliveries,
    failures, and retries. Used for debugging, monitoring, and retry logic.
    
    Attributes:
        id: Primary key (UUID as string)
        webhook_id: Foreign key to the webhook configuration
        event_type: The type of event that triggered this delivery
        payload: The JSON payload that was/will be sent
        response_status: HTTP status code from the webhook endpoint
        response_body: Response body from the webhook endpoint (truncated)
        delivered_at: When the delivery was attempted
        retry_count: Number of retry attempts
        next_retry_at: When to retry next (for failed deliveries)
        error_message: Error details if delivery failed
    """
    __tablename__ = "webhook_deliveries"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    webhook_id: Mapped[str] = mapped_column(
        String, ForeignKey("developer_webhooks.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    webhook: Mapped["DeveloperWebhook"] = relationship(
        "DeveloperWebhook", back_populates="deliveries"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_webhook_deliveries_webhook_id", "webhook_id"),
        Index("ix_webhook_deliveries_event_type", "event_type"),
        Index("ix_webhook_deliveries_delivered_at", "delivered_at"),
        Index("ix_webhook_deliveries_next_retry", "next_retry_at"),
        Index("ix_webhook_deliveries_webhook_event", "webhook_id", "event_type"),
    )
    
    def __repr__(self):
        status_str = f"status={self.response_status}" if self.response_status else "pending"
        return f"<WebhookDelivery(id={self.id}, event='{self.event_type}', {status_str}, retries={self.retry_count})>"
# --- END WEBHOOK MODELS ---

# --- ORGANIZATIONS & TEAMS MODELS ---
class Organization(Base):
    """
    Organization model for multi-tenant support.
    
    An organization represents a company, team, or group that can have
    multiple developers and agents under it.
    
    Attributes:
        id: Primary key (UUID as string)
        name: Organization name
        slug: URL-friendly unique identifier
        owner_id: Foreign key to the developer who owns the organization
        description: Optional organization description
        website: Optional organization website
        logo_url: Optional logo URL
        created_at: When the organization was created
        updated_at: When the organization was last updated
        is_active: Whether the organization is active
        settings: JSON field for organization-specific settings
        limits: JSON field for plan limits (agents, members, etc.)
        treasury_agent_did: the org's OWN keyless money account (Track C / §ORGTREASURY).
            Nullable: an org has one only once it opts in. Do NOT read this column
            directly — ask `services.org_treasury.resolve_org_treasury_did()`, which is
            the ONE answer to "where does this org's money live" and falls back to the
            org's first AGORA listing treasury for orgs that predate this column.
    """
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Track C — the org-level treasury Agent DID (keyless: its client_secret is generated,
    # hashed and discarded at creation, so no JWT can ever be minted for it). Unique so two
    # orgs can never share a purse. Money moves ONLY through the escrow mover in
    # services/org_treasury.py; the DID is never wired through an agent-JWT rail.
    treasury_agent_did: Mapped[Optional[str]] = mapped_column(String(120), unique=True, nullable=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    limits: Mapped[Optional[Dict[str, int]]] = mapped_column(
        JSON, nullable=True, default=lambda: {
            "max_agents": 100,
            "max_members": 50,
            "max_teams": 10
        }
    )
    # E1a — the single pending ownership-transfer offer (mig 0149). Ownership moves via a
    # two-party handshake, never a role edit; expiry is checked at read time (self-retiring,
    # no sweeper). History lives in the EventStore org aggregate, not here.
    pending_owner_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    pending_owner_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    owner: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[owner_id], back_populates="owned_organizations"
    )
    teams: Mapped[List["Team"]] = relationship(
        "Team", back_populates="organization", cascade="all, delete-orphan"
    )
    members: Mapped[List["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization", cascade="all, delete-orphan"
    )
    invitations: Mapped[List["OrganizationInvitation"]] = relationship(
        "OrganizationInvitation", back_populates="organization", cascade="all, delete-orphan"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_organizations_owner_id", "owner_id"),
        Index("ix_organizations_slug", "slug"),
        Index("ix_organizations_is_active", "is_active"),
    )
    
    def __repr__(self):
        return f"<Organization(id={self.id}, name='{self.name}', slug='{self.slug}')>"


class Team(Base):
    """
    Team model for organizing members within an organization.
    
    Teams allow organizations to group members and assign permissions
    at a team level.
    
    Attributes:
        id: Primary key (UUID as string)
        organization_id: Foreign key to the organization
        name: Team name
        description: Optional team description
        created_at: When the team was created
        updated_at: When the team was last updated
        is_active: Whether the team is active
        permissions: JSON field for team-specific permissions
    """
    __tablename__ = "teams"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    permissions: Mapped[Optional[List[str]]] = mapped_column(
        JSON, nullable=True, default=lambda: ["read_agents", "create_agents"]
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="teams"
    )
    members: Mapped[List["TeamMember"]] = relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_teams_organization_id", "organization_id"),
        Index("ix_teams_is_active", "is_active"),
        UniqueConstraint("organization_id", "name", name="uq_teams_org_name"),
    )
    
    def __repr__(self):
        return f"<Team(id={self.id}, name='{self.name}', org_id={self.organization_id})>"


class OrganizationMember(Base):
    """
    Organization membership model.
    
    Tracks which developers belong to which organizations and their roles.
    
    Attributes:
        id: Primary key (UUID as string)
        organization_id: Foreign key to the organization
        developer_id: Foreign key to the developer
        role: Member role (owner, admin, member, guest)
        joined_at: When the member joined
        invited_by: Who invited this member
        is_active: Whether the membership is active
    """
    __tablename__ = "organization_members"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True
    )
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="member"
    )  # owner, admin, member, guest
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    invited_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # V0650 (l) (mig 0198): a named approver may decide the approval requests agents post in the org's room, beside
    # the owner. It is a column of the membership row, so the authority ends when the membership does.
    can_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="members"
    )
    developer: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[developer_id], back_populates="organization_memberships"
    )
    inviter: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[invited_by]
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_organization_members_org_id", "organization_id"),
        Index("ix_organization_members_dev_id", "developer_id"),
        Index("ix_organization_members_role", "role"),
        UniqueConstraint("organization_id", "developer_id", name="uq_org_members"),
    )
    
    def __repr__(self):
        return f"<OrganizationMember(org_id={self.organization_id}, dev_id={self.developer_id}, role='{self.role}')>"


class TeamMember(Base):
    """
    Team membership model.
    
    Tracks which developers belong to which teams within an organization.
    
    Attributes:
        id: Primary key (UUID as string)
        team_id: Foreign key to the team
        developer_id: Foreign key to the developer
        role: Member role within the team (lead, member)
        joined_at: When the member joined the team
        is_active: Whether the membership is active
    """
    __tablename__ = "team_members"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.id"), nullable=False
    )
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="member"
    )  # lead, member
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Relationships
    team: Mapped["Team"] = relationship(
        "Team", back_populates="members"
    )
    developer: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[developer_id], back_populates="team_memberships"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_team_members_team_id", "team_id"),
        Index("ix_team_members_dev_id", "developer_id"),
        UniqueConstraint("team_id", "developer_id", name="uq_team_members"),
    )
    
    def __repr__(self):
        return f"<TeamMember(team_id={self.team_id}, dev_id={self.developer_id}, role='{self.role}')>"


class OrganizationInvitation(Base):
    """
    Organization invitation model.
    
    Tracks pending invitations to join organizations.
    
    Attributes:
        id: Primary key (UUID as string)
        organization_id: Foreign key to the organization
        email: Email address of the invitee
        role: Proposed role for the invitee
        token: Unique invitation token
        invited_by: Who sent the invitation
        created_at: When the invitation was created
        expires_at: When the invitation expires
        accepted_at: When the invitation was accepted (if applicable)
        status: Invitation status (pending, accepted, expired, cancelled)
    """
    __tablename__ = "organization_invitations"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    invited_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending, accepted, expired, cancelled
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="invitations"
    )
    inviter: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[invited_by]
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_org_invitations_org_id", "organization_id"),
        Index("ix_org_invitations_email", "email"),
        Index("ix_org_invitations_token", "token"),
        Index("ix_org_invitations_status", "status"),
    )
    
    def __repr__(self):
        return f"<OrganizationInvitation(id={self.id}, email='{self.email}', status='{self.status}')>"
# --- END ORGANIZATIONS & TEAMS MODELS ---


# --- AGENT EXPORT/IMPORT MODELS ---
class AgentCapability(Base):
    """
    Agent capabilities for export/import.
    
    Stores information about what an agent can do, including:
        - Name and description of the capability
        - Category for organization
        - Version information
        - Parameters and configuration
    """
    __tablename__ = "agent_capabilities"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('agent_did', 'name', name='uq_agent_capabilities_agent_did_name'),
    )
    
    def __repr__(self):
        return f"<AgentCapability(id={self.id}, name='{self.name}', agent_did='{self.agent_did}')>"


class AgentRoleGrant(Base):
    """IRONKEY (f-agent-rbac) — a role or bare-permission grant held by an agent.

    The agent-side analog of the developer `admin_*` flags. `grant_type='role'`
    values map through the code-side ROLE_PERMISSIONS catalog to permission sets;
    `grant_type='permission'` carries a single `domain.verb`. Resolution filters
    `expires_at IS NULL OR expires_at > now()` (time-based grants self-retire; no
    sweeper). Migration `0107_agent_ironkey`. Enforcement is gated by
    AGENT_RBAC_MODE (off|shadow|enforce) — rows are inert until it flips.
    """
    __tablename__ = "agent_role_grants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), nullable=False, index=True
    )
    grant_type: Mapped[str] = mapped_column(String, nullable=False, default="role")
    value: Mapped[str] = mapped_column(String, nullable=False)
    granted_by_dev_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    granted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("agent_did", "grant_type", "value", name="uq_agent_role_grant"),
    )

    def __repr__(self):
        return f"<AgentRoleGrant(agent_did='{self.agent_did}', {self.grant_type}='{self.value}')>"


class AgentSpendPolicy(Base):
    """IRONKEY (f-agent-rbac) — per-agent money caveats (L2).

    Two axes checked pre-escrow: (a) `max_per_tx` = exposure admission on a single
    action's face amount; (b) `max_per_day` = rolling-24h NET SETTLED outflow
    (maintained via Redis reserved/settled counters, NOT stored here). Outflow
    EXCLUDES staking (self-lock), fees, and refunded escrow. Amounts denominated in
    the agent's HOME currency (the debit side). NULL cap = uncapped. Migration
    `0107_agent_ironkey`. Δ-irrelevant (deny-only, never moves money).
    """
    __tablename__ = "agent_spend_policies"

    agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), primary_key=True
    )
    max_per_tx: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    max_per_day: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    allowed_currencies: Mapped[Optional[list]] = mapped_column(PG_ARRAY(String), nullable=True)
    counterparty_mode: Mapped[str] = mapped_column(String, nullable=False, default="any")
    counterparty_allow: Mapped[Optional[list]] = mapped_column(PG_ARRAY(String), nullable=True)
    require_approval_above: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    updated_by_dev_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<AgentSpendPolicy(agent_did='{self.agent_did}', per_tx={self.max_per_tx}, per_day={self.max_per_day})>"



class AgentStatusLine(Base):
    """V0650 (a) (mig 0199): an agent's one-line status, set by the agent and expiring on its own. A line past
    `expires_at` reads as no line at all. One row per agent; it goes with the agent. The attribute is `status_text`, not
    `text`: this module imports sqlalchemy's `text`, and a class attribute of that name would shadow it here."""
    __tablename__ = "agent_status_lines"

    agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), primary_key=True
    )
    status_text: Mapped[str] = mapped_column(String(140), nullable=False)
    set_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class AgentDelegationGrant(Base):
    """IRONKEY L3-D2 — a principal delegates a permission subset TO an agent (on-behalf-of).

    Consulted by ``resolve_delegated_permissions`` ONLY when the presented agent token
    carries a matching ``act.sub`` claim (authority is never inherited silently). ``org:``
    principals additionally require the delegate agent to be linked to that org.
    ``may_redelegate`` (the DeepMind meta-permission) governs whether the delegate may in
    turn issue capability tokens carrying these permissions. Migration `0108`. Inert until
    ``AGENT_DELEGATION_MODE`` flips. Δ-irrelevant (deny/extend authorization only).
    """
    __tablename__ = "agent_delegation_grants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    principal_type: Mapped[str] = mapped_column(String, nullable=False)   # dev|org|agent|service
    principal_ref: Mapped[str] = mapped_column(String, nullable=False, index=True)
    delegate_agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), nullable=False, index=True
    )
    permissions: Mapped[list] = mapped_column(PG_ARRAY(String), nullable=False, default=list)
    may_redelegate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_depth: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    granted_by_dev_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("principal_type", "principal_ref", "delegate_agent_did",
                         name="uq_agent_delegation"),
    )

    def __repr__(self):
        return f"<AgentDelegationGrant({self.principal_type}:{self.principal_ref} -> {self.delegate_agent_did})>"


class AgentCapabilityToken(Base):
    """IRONKEY L4 — an attenuable ``att_`` capability token (agent→sub-agent chain).

    The generalization of the ``apt_`` payment token from one payment to standing attenuated
    authority. ``parent_token_id`` is the self-referential chain; ``caveats`` (JSONB) carries
    permissions + numeric/scope bounds (Biscuit-Datalog-expressible); a child must be ≤ its
    parent on every axis (enforced at issuance). Presented on a gated endpoint it can only
    INTERSECT (reduce) the holder's authority. ``revoke_subtree`` cascades in one UPDATE.
    Migration `0109`. Δ-irrelevant (authorizes; never moves money — budget is bookkeeping).
    """
    __tablename__ = "agent_capability_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String, nullable=False)
    issuer_agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), nullable=False, index=True
    )
    holder_agent_did: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    parent_token_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("agent_capability_tokens.id", ondelete="CASCADE"), nullable=True
    )
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    caveats: Mapped[dict] = mapped_column(PG_JSONB, nullable=False, default=dict)
    budget_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    budget_spent: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="issued", index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    def __repr__(self):
        return f"<AgentCapabilityToken(id={self.id}, issuer='{self.issuer_agent_did}', depth={self.depth}, status='{self.status}')>"


class AgentEndpoint(Base):
    """
    Agent API endpoints for export/import.
    
    Stores API endpoint definitions including:
        - Path and HTTP method
        - Description and documentation
        - Parameters and response schema
        - Rate limiting configuration
    """
    __tablename__ = "agent_endpoints"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # GET, POST, etc.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    response_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    rate_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('agent_did', 'path', 'method', name='uq_agent_endpoints_agent_did_path_method'),
    )
    
    def __repr__(self):
        return f"<AgentEndpoint(id={self.id}, path='{self.path}', method='{self.method}')>"


class AgentVersion(Base):
    """
    Agent version history for export/import.
    
    Tracks different versions of an agent including:
        - Version number and changelog
        - Configuration at that version
        - Publication status and timestamp
    """
    __tablename__ = "agent_versions"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    changelog: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    configuration: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    published_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('agent_did', 'version', name='uq_agent_versions_agent_did_version'),
    )
    
    def __repr__(self):
        return f"<AgentVersion(id={self.id}, version='{self.version}', agent_did='{self.agent_did}')>"


# NOTE: AgentMetric removed - using existing AgentMetrics model instead
# The AgentMetrics model already exists earlier in the file with the same table name


class AgentTag(Base):
    """
    Agent tags for categorization.
    
    Simple tagging system for agents to support:
        - Search and discovery
        - Categorization
        - Export/import metadata
    """
    __tablename__ = "agent_tags"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_did: Mapped[str] = mapped_column(
        String, ForeignKey("agents.did", ondelete="CASCADE"), nullable=False, index=True
    )
    tag: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('agent_did', 'tag', name='uq_agent_tags_agent_did_tag'),
    )
    
    def __repr__(self):
        return f"<AgentTag(id={self.id}, tag='{self.tag}', agent_did='{self.agent_did}')>"
# --- END AGENT EXPORT/IMPORT MODELS ---


# --- EIGENTRUST++ PHASE 2 MODELS ---

class EvalSuite(Base):
    """Agent Evals (f-evals) — a named battery of tasks run against target agents.

    Additive, deny-nothing feature gated by EVALS_ENABLED. Scoring folds into the
    existing EigenTrust reputation via a local_trust edge (no new ranking system);
    optional pay-per-task rides the reward waterfall (Δ=0 preserved).
    """
    __tablename__ = "eval_suites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    task_type: Mapped[str] = mapped_column(String(24), nullable=False, default="http_probe")  # http_probe | a2a_message
    config: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    interval_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # NULL = manual only
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    pay_per_task: Mapped[float] = mapped_column(Numeric(38, 18), default=0, server_default="0", nullable=False)
    emit_reputation_signal: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    target_dids: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)  # list; NULL/[] = all active agents
    next_run_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class EvalTask(Base):
    """One scored step within a suite."""
    __tablename__ = "eval_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suite_id: Mapped[int] = mapped_column(Integer, ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    input: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    scorer: Mapped[str] = mapped_column(String(24), nullable=False, default="status_ok")  # exact|contains|regex|status_ok|latency_under_ms|code_patch
    expected: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0", nullable=False)
    # GÖDEL FORGE (mig 0124): holdout = hidden test — `expected` never shown to the target
    # agent (anti eval-hacking). grader_config = per-task grader params (code_patch repo/test cmd).
    holdout: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    grader_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)


class EvalResult(Base):
    """Outcome of one task against one agent in one run."""
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    suite_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_excerpt: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_eval_results_agent_suite_time", "agent_did", "suite_id", "created_at"),
    )


class LocalTrustScore(Base):
    """
    Bilateral trust values between agent pairs.
    Updated on every transfer, dispute resolution, and ZKP attestation.
    Self-loop rows (from_did == to_did) represent ZKP attestation self-signals.
    """
    __tablename__ = "local_trust_scores"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    from_did: Mapped[str] = mapped_column(String, nullable=False)
    to_did: Mapped[str] = mapped_column(String, nullable=False)
    satisfactory: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unsatisfactory: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    local_trust: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    normalized: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # mig 0171: NUMERIC(36,18), not BigInteger. With int(float(amount)) at the call
    # site AND an integer column, 57% of real transfers stored as 0 and 19 of 29
    # active senders scored zero volume in EigenTrust's Step-8 weighting.
    tx_volume: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=0, nullable=False)
    last_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("from_did", "to_did", name="uix_lt_pair"),
        Index("ix_lt_from", "from_did"),
        Index("ix_lt_to", "to_did"),
        Index("ix_lt_updated", "last_updated"),
    )

    def __repr__(self):
        return f"<LocalTrustScore(from={self.from_did[:16]}, to={self.to_did[:16]}, trust={self.local_trust:.2f})>"


class GlobalTrustVector(Base):
    """
    Computed EigenTrust++ global trust value per agent.
    One row per agent, upserted each epoch.
    Agent.reputation_score = int(global_trust × 1000), range 0-1000.
    """
    __tablename__ = "global_trust_vectors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_did: Mapped[str] = mapped_column(String, nullable=False)
    global_trust: Mapped[float] = mapped_column(Float, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    computation_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_did", name="uix_gtv_agent"),
        Index("ix_gtv_epoch", "epoch"),
    )

    def __repr__(self):
        return f"<GlobalTrustVector(did={self.agent_did[:16]}, trust={self.global_trust:.4f}, epoch={self.epoch})>"

# --- END EIGENTRUST++ PHASE 2 MODELS ---


# --- STAKING AUTO-DISTRIBUTION MODELS ---
class StakingDistribution(Base):
    """
    Tracks daily reward distribution runs.
    
    Records each distribution event including:
        - Total amount distributed
        - Number of stakers rewarded
        - Status and error tracking
        - Metadata for analysis
    """
    __tablename__ = "staking_distributions"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    distribution_date: Mapped[datetime.date] = mapped_column(
        sa.Date, nullable=False, unique=True, index=True
    )
    distribution_type: Mapped[str] = mapped_column(
        String(50), nullable=False  # 'daily', 'manual', 'emergency'
    )
    total_distributed: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), nullable=False, default=Decimal('0')
    )
    total_stakers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='pending', index=True  # pending, running, completed, failed
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    initiated_by: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True  # 'system' or developer email
    )
    distribution_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    def __repr__(self):
        return f"<StakingDistribution(id={self.id}, date={self.distribution_date}, status='{self.status}')>"


class StakingRewardRecord(Base):
    """
    Individual reward records for each staker.
    
    Tracks each reward distribution to an agent including:
        - Amount calculated based on APY
        - Distribution status
        - TEG transaction reference
    """
    __tablename__ = "staking_reward_records"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    distribution_id: Mapped[str] = mapped_column(
        String, ForeignKey("staking_distributions.id"), nullable=False, index=True
    )
    agent_did: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.did"), nullable=False, index=True
    )
    staked_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    apy_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # APY percentage
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    days_staked: Mapped[int] = mapped_column(Integer, nullable=False)
    tier_name: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True  # bronze, silver, gold, platinum
    )
    distributed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    teg_transaction_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True  # TEG layer transaction ID
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='pending', index=True  # pending, distributed, failed
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    def __repr__(self):
        return f"<StakingRewardRecord(id={self.id}, agent_did='{self.agent_did}', amount={self.reward_amount})>"


class StakingApyConfig(Base):
    """
    APY tier configuration for staking rewards.
    
    Defines the APY rates for different staking tiers:
        - Bronze: 100-999 tokens @ 5% APY
        - Silver: 1,000-9,999 tokens @ 8% APY + lock bonus
        - Gold: 10,000-99,999 tokens @ 12% APY + lock bonus
        - Platinum: 100,000+ tokens @ 15% APY + lock bonus
    """
    __tablename__ = "staking_apy_config"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tier_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    min_stake: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    max_stake: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    base_apy: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # Base APY rate
    lock_period_days: Mapped[int] = mapped_column(Integer, default=0)
    lock_bonus_apy: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal('0')  # Additional APY for lock period
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    effective_from: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_until: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    def __repr__(self):
        return f"<StakingApyConfig(id={self.id}, tier='{self.tier_name}', apy={self.base_apy}%)>"
# --- END STAKING AUTO-DISTRIBUTION MODELS ---


# --- SF-3: WRAPPED TOKEN BRIDGE MODEL ---
class BridgeTransaction(Base):
    """Tracks cross-frame AVT transfers using escrow + mint model.

    State machine: INITIATED → LOCKED → MINTED → COMPLETED | FAILED | EXPIRED

    Source frame: locks AVT (locked_balance), creates outbound record.
    Target frame: mints wrapped-AVT (wrapped_balance), creates inbound record.
    Redemption: burn wrapped → unlock original.
    """
    __tablename__ = "bridge_transactions"

    id = Column(String, primary_key=True)
    source_frame_id = Column(String, nullable=False)
    target_frame_id = Column(String, nullable=False)
    source_agent_did = Column(String, nullable=False)
    target_agent_did = Column(String, nullable=False)
    amount = Column(Numeric(precision=30, scale=6), nullable=False)
    status = Column(String(50), nullable=False, default="INITIATED")
    direction = Column(String(20), nullable=False, default="outbound")  # "outbound" or "inbound"

    # Transaction references (TEG transaction IDs)
    lock_tx_id = Column(String, nullable=True)
    mint_tx_id = Column(String, nullable=True)
    unlock_tx_id = Column(String, nullable=True)
    burn_tx_id = Column(String, nullable=True)

    # Idempotency
    idempotency_key = Column(String, nullable=True, unique=True)

    # Timeout
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(String(1000), nullable=True)


# --- OWL25: CROSS-REGISTRY SETTLEMENT MODEL ---
class CrossRegistrySettlement(Base):
    """
    Tracks cross-registry dispute compensation settlements.
    
    When a dispute involves agents from different registries, compensation
    requires two sovereign operations:
    1. SLASH: Defendant's home registry deducts AVT (DisputeSlash event)
    2. MINT: Complainant's home registry mints AVT (DisputeCompensationMinted event)
    
    The EventStore public ledger connects them via dispute_id and event references.
    
    Status flow: PENDING_SLASH → SLASHED → SETTLED | FAILED | EXPIRED
    """
    __tablename__ = "cross_registry_settlements"
    
    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # OWL25: No ForeignKey — dispute may exist on a REMOTE registry, not locally
    dispute_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    
    # Registry URLs
    origin_registry_url: Mapped[str] = mapped_column(String(500), nullable=False)
    defendant_registry_url: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Agent DIDs
    complainant_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    defendant_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Amounts
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)  # AVT requested
    slashed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 6), nullable=True, default=0)  # Actual slashed
    minted_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 6), nullable=True, default=0)  # Actual minted
    
    # Status: PENDING_SLASH, SLASHED, SETTLED, FAILED, EXPIRED
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PENDING_SLASH", index=True
    )
    ruling: Mapped[str] = mapped_column(String(100), nullable=False)
    # S2 (2026-05-06): evidence_hash dropped — was vestigial, never read anywhere.
    # Migration 0030_disputes_chain_polish removes the column.

    # EventStore event references (linking the audit trail)
    request_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    slash_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mint_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # TEG transaction IDs
    slash_tx_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mint_tx_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Callback URL for the origin registry to receive slash confirmation
    callback_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    requested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    slashed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # TITANIUM VAULT D3: Saga state tracking for cross-registry settlement rollback
    # S1 (2026-05-06): server_default flipped LEGACY → INITIATED via migration
    # 0030_disputes_chain_polish so new rows pick up the saga state machine's
    # actual start state. (Legacy rows pre-saga keep their stored 'LEGACY' value.)
    saga_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="INITIATED", server_default="INITIATED", index=True
    )
    saga_timeout_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    saga_last_step_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    saga_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default='0'
    )
    
    # OWL25: No relationship — dispute_id references a remote registry's dispute, not a local FK
    # dispute: Mapped["Dispute"] = relationship("Dispute", backref="settlements")  # REMOVED: no FK
    
    def __repr__(self):
        return (
            f"<CrossRegistrySettlement(id={self.id}, dispute={self.dispute_id}, "
            f"status={self.status}, amount={self.requested_amount})>"
        )
# --- END OWL25: CROSS-REGISTRY SETTLEMENT MODEL ---


# ==========================================================================
# SPRINT 1 (f029_enforcement_foundation) — Economic Engine §4.2-§4.5
# ==========================================================================


class RegistryEnforcementPolicy(Base):
    """
    Active enforcement policy configuration for this registry instance.

    Exactly ONE row has is_active=True at any time (enforced by partial unique
    index uix_policy_active). All other rows are historical versions retained
    for audit purposes.

    policy_json structure:
      dispute_escalation.levels.{1-4}.slash_percent
      dispute_escalation.offense_window_days
      staking_rewards.reputation_floor_for_rewards
      staking_rewards.min_eigentrust_for_rewards
      transaction_fees.base_rate_percent / max_rate_percent / velocity_scaling_factor
      reputation_bond.amount_avt / min_transactions / min_age_days / min_eigentrust
      governance.policy_change_requires_proposal / quorum / pass / min_stake
      correlation_penalty.same_registry_multiplier / window_hours
    """
    __tablename__ = "registry_enforcement_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    modified_by: Mapped[str] = mapped_column(String(200), default='system', nullable=False)
    modified_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False
    )
    previous_version: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey('registry_enforcement_policies.id', ondelete='SET NULL'),
        nullable=True
    )

    def __repr__(self):
        return (
            f"<RegistryEnforcementPolicy(id={self.id}, version={self.version}, "
            f"active={self.is_active}, by='{self.modified_by}')>"
        )


class EnforcementAction(Base):
    """
    Immutable audit record for every enforcement operation performed against an agent.

    Status flow:
      pending_approval  →  executed  (admin approves + engine runs)
                        →  rejected  (admin rejects with reason)
                        →  failed    (execution attempted but engine error)

    action_type values: slash_liquid, slash_stake, pause_rewards,
                        resume_rewards, suspend, reinstate, warn

    trigger values: dispute_ruling, reputation_threshold, admin_manual,
                    collusion_detection, governance_policy

    IMPORTANT: EnforcementAction.status ('pending_approval' etc.) is distinct
    from Agent.status ('active'/'suspended'/'revoked') and
    Agent.enforcement_status ('active'/'suspended'/'revoked').
    """
    __tablename__ = "enforcement_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_did: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_reference: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default='pending_approval', nullable=False
    )  # pending_approval | executed | rejected | failed
    escalation_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correlation_multi: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index('ix_enforcement_agent', 'agent_did'),
        Index('ix_enforcement_status', 'status'),
        Index('ix_enforcement_created', 'created_at'),
    )

    def __repr__(self):
        return (
            f"<EnforcementAction(id={self.id[:8]}, agent={self.agent_did[:16]}, "
            f"type='{self.action_type}', status='{self.status}')>"
        )


class ReputationBond(Base):
    """
    The reputation bond: money the TEG treasury holds in escrow for an agent that
    provides services (§REPBOND, 2026-09-05; the amount is a profile knob).

    One row per agent (enforced by UNIQUE constraint on agent_did).

    Status values:
      locked     — bond is held, agent is earning maturity
      matured    — all maturity conditions met, agent may reclaim
      forfeited  — bond slashed as part of enforcement action

    Maturity conditions (the frame's declared policy, §BONDFILL-3):
      - transactions >= enforcement.bond_maturity_min_transactions   (local_trust_scores)
      - age_days     >= enforcement.bond_maturity_min_age_days       (NOW() - locked_at)
      - trust: rated by >= enforcement.bond_maturity_min_rated_peers independent counterparties
               AND at/above enforcement.bond_maturity_min_trust_percentile of the frame's ranked
               agents — the percentile WAIVED (and said so) while too few agents are ranked for a
               percentile to mean anything. The old absolute `min_eigentrust` is RETIRED: it was a
               fixed threshold on a NORMALISED vector, unreachable by construction.

    At maturity a declared share (`bond_maturity_releases_percent`, at most 80) may be unlocked
    while the rest stays bonded; `release()` returns the remainder and is the EXIT.
    """
    __tablename__ = "reputation_bonds"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_did: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # §REPBOND (mig 0173): the amount is MONEY the treasury holds in escrow, so it is
    # NUMERIC like every other amount column; the profile derives it from the grant.
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=50, nullable=False)
    locked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default='locked', nullable=False
    )  # locked | matured | released | forfeited | voided
    matured_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    forfeited_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    forfeit_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # §REPBOND — who funded the escrow, how, and the ledger transactions it rode on.
    funder_did: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    funded_by: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # self | wallet | treasury
    escrow_ref: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    teg_transaction_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    release_ref: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    release_teg_transaction_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    released_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    forfeit_ref: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    # §BONDFILL-3 (mig 0177) — maturity UNLOCKS a declared share instead of ending the business.
    # `amount` keeps meaning what is HELD, so the slash waterfall and the six gates need no change;
    # the original is amount + partial_released_amount, derived rather than stored twice.
    partial_released_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    partial_released_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    partial_release_ref: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    partial_release_teg_transaction_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index('ix_bond_agent', 'agent_did'),
        Index('ix_bond_status', 'status'),
    )

    def __repr__(self):
        return (
            f"<ReputationBond(agent={self.agent_did[:16]}, amount={self.amount}, "
            f"status='{self.status}')>"
        )


class TransactionFeeRecord(Base):
    """
    Per-transfer fee audit record.

    Created by TransactionFeeService.apply_fee() (Sprint 3) before each
    agent-to-agent AVT transfer via /teg/transfer or /teg/cross-registry-transfer.

    Treasury-fund-agent calls and staking reward distributions are EXEMPT.

    fee_rate_percent: 1.5% (base) to 7.5% (high velocity), set by policy.
    destination: always 'treasury_recycle' until alternative sinks are defined.
    """
    __tablename__ = "transaction_fee_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_did: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=6), nullable=False)
    fee_rate_percent: Mapped[float] = mapped_column(Float, nullable=False)
    destination: Mapped[str] = mapped_column(
        String(30), default='treasury_recycle', nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Sprint 3 addendum (f030): extended audit columns
    transfer_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=30, scale=6), nullable=True,
        comment='Original transfer amount the fee was calculated against'
    )
    velocity_index: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment='Velocity index used for dynamic rate calculation (0.0–1.0)'
    )

    __table_args__ = (
        Index('ix_fee_agent', 'agent_did'),
        Index('ix_fee_created', 'created_at'),
        Index('ix_fee_transaction', 'transaction_id'),
    )

    def __repr__(self):
        return (
            f"<TransactionFeeRecord(tx={self.transaction_id[:12]}, "
            f"agent={self.agent_did[:16]}, amount={self.amount}, "
            f"rate={self.fee_rate_percent}%)>"
        )


# --- END SPRINT 1 (f029_enforcement_foundation) ---


# --- SPRINT 9: VelocityMetrics (f031_velocity_metrics) ---

class VelocityMetrics(Base):
    """
    Hourly transfer velocity snapshot per agent.

    Populated by background_tasks/velocity_snapshot.py (hourly).
    Consumed by TransactionFeeService._get_velocity_index() for dynamic fee scaling.

    One row per (agent_did, window_start) — UNIQUE constraint enforced.

    velocity_index: 0.0–1.0 normalised against the registry-wide maximum for
    that same window.  An agent at max throughput gets 1.0; an idle agent gets 0.0.
    """
    __tablename__ = 'velocity_metrics'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_did: Mapped[str] = mapped_column(
        String, nullable=False,
        comment='Agent DID this metric row belongs to'
    )
    window_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment='Start of the 1-hour window (truncated to the hour)'
    )
    tx_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment='Number of transfers initiated in this window'
    )
    tx_volume: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), default=0, nullable=False,
        comment='Total volume transferred in this window. NUMERIC(36,18) to match '
                'agent_spend_policies.max_per_day (mig 0170) — as a BigInteger it '
                'ROUNDED sub-unit volume away (0.1 -> 0) and half-up (0.6 -> 1), so '
                'the IRONKEY rolling-24h cap could not see fractional spend'
    )
    velocity_index: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False,
        comment='Normalized 0.0–1.0 index relative to registry-wide max'
    )
    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        comment='Timestamp when this row was computed'
    )

    __table_args__ = (
        Index('ix_velocity_agent', 'agent_did'),
        Index('ix_velocity_window', 'window_start'),
        sa.UniqueConstraint('agent_did', 'window_start', name='ix_velocity_agent_window'),
    )

    def __repr__(self):
        return (
            f"<VelocityMetrics(agent={self.agent_did[:16]}, "
            f"window={self.window_start}, idx={self.velocity_index:.3f})>"
        )


# --- END SPRINT 9 ---


# SPRINT 8 §7.1: ORM classes for staking_distributions, staking_reward_records,
# staking_apy_config are defined above in '--- STAKING AUTO-DISTRIBUTION MODELS ---'.
# Agent columns (last_reward_distribution, total_rewards_earned, staking_tier)
# are defined in the Agent class above.
# Duplicate classes that were erroneously added here have been removed.


# ---------------------------------------------------------------------------
# BETA INVITE CODES
# ---------------------------------------------------------------------------

class InviteCode(Base):
    """
    Single-use invite codes for beta access control.
    Commander generates codes via admin endpoint.
    Each code becomes a shareable URL: /ui#/register?invite=<code>
    """
    __tablename__ = "invite_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, nullable=False, index=True)

    created_by = Column(Integer, ForeignKey("developers.id"), nullable=False)
    used_by = Column(Integer, ForeignKey("developers.id"), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    max_uses = Column(Integer, default=1, nullable=False)
    use_count = Column(Integer, default=0, nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    note = Column(String(255), nullable=True)  # e.g. "Wave 1 — Twitter"

    # §OPGUIDE-3 (mig 0142): redeeming this code creates a FULL ADMIN instead of an
    # ordinary developer. Exists so a registry handed to an outside party can get its
    # first administrator without us creating the account and mailing a password:
    # they register themselves, choose their own password and accept the terms, and
    # the account is an admin from the moment it exists.
    # Default False — an existing code, or one generated without asking for this,
    # keeps its old meaning exactly.
    grants_admin = Column(Boolean, default=False, server_default=sa.false(), nullable=False)

    # §INVRBAC (mig 0143): WHICH admin capability the code confers, as a list of the
    # granular flag names (`admin_treasury`, `admin_support`, `admin_enforcement`,
    # `admin_federation`, `admin_platform`).
    #
    # This exists because `grants_admin` alone was all-or-nothing and reached for the
    # legacy `is_admin` super-flag, which is a blanket bypass inside every gate. All
    # 351 admin route gates read a GRANULAR flag; `is_admin` only ever short-circuits
    # them. So an invitation never needs to grant it, and after this migration it does
    # not: redemption sets exactly the flags named here and leaves `is_admin` False.
    #
    # NULL on a row minted before this column existed. Such a row resolves to all five
    # granular flags — the same effective authority its holder was promised, minus the
    # bypass. Resolution lives in ONE place: crud.invite_codes.resolve_admin_flags().
    admin_flags = Column(PG_JSONB, nullable=True)

    # Relationships
    creator = relationship("Developer", foreign_keys=[created_by], backref="created_invite_codes")
    used_by_dev = relationship("Developer", foreign_keys=[used_by])

    def __repr__(self):
        status = "used" if self.used_at else "active"
        return f"<InviteCode(code={self.code[:16]}..., status={status})>"

    @property
    def is_valid(self) -> bool:
        """Check if code can still be used."""
        if self.use_count >= self.max_uses:
            return False
        if self.expires_at and datetime.datetime.now(datetime.timezone.utc) > self.expires_at:
            return False
        return True

    @property
    def status(self) -> str:
        if self.use_count >= self.max_uses:
            return "used"
        if self.expires_at and datetime.datetime.now(datetime.timezone.utc) > self.expires_at:
            return "expired"
        return "active"


# ---------------------------------------------------------------------------
# ADMIN NOTIFICATION BROADCAST CHANNEL (f034)
# ---------------------------------------------------------------------------

class AdminBroadcast(Base):
    """
    A message composed by an admin and broadcast to all developers.

    Delivery channels (per broadcast):
      1. WebSocket — pushed to all connected developers immediately
      2. DB persistence — fetched on login by offline developers
      3. Email — optional, controlled by send_email flag

    broadcast_type values: info | warning | maintenance | critical
    is_active=False means the broadcast has been retracted/expired.
    """
    __tablename__ = 'admin_broadcasts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    broadcast_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default='info')
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('developers.id'), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.true())
    send_email: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    email_sent_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ws_recipients: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')

    # §bc2 T2.1 — schema extensions (migration 0070_bc2_schema_ext)
    cta_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cta_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    requires_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    scheduled_for: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source_frame: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    target_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True
    )
    # Migration 0179: a notice for ONE developer. No foreign key on purpose (see the migration): NULL means
    # everyone, so a SET NULL on delete would publish a private notice to the whole registry.
    target_developer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    creator: Mapped['Developer'] = relationship('Developer', foreign_keys=[created_by])
    reads: Mapped[List['DeveloperNotificationRead']] = relationship(
        'DeveloperNotificationRead', back_populates='broadcast', cascade='all, delete-orphan'
    )

    __table_args__ = (
        Index('ix_broadcasts_active_created', 'is_active', 'created_at'),
    )

    def __repr__(self):
        return f"<AdminBroadcast(id={self.id}, type='{self.broadcast_type}', active={self.is_active})>"


# ---------------------------------------------------------------------------
# §bc2 T2.5 — broadcast_email_failed
# ---------------------------------------------------------------------------

class AdminBroadcastTemplate(Base):
    """§bc3 T3.6 — saved compose template owned by an admin.

    UNIQUE on (created_by, label) so an admin can't have two templates
    named the same. Cascade delete with the admin.
    """
    __tablename__ = 'admin_broadcast_templates'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey('developers.id', ondelete='CASCADE'), nullable=False
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    title_template: Mapped[str] = mapped_column(String(200), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    broadcast_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default='info')
    send_email: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    requires_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    cta_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cta_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<AdminBroadcastTemplate(id={self.id}, label='{self.label}')>"


class BroadcastEmailFailed(Base):
    """
    Per-batch email-delivery failure capture for AdminBroadcast.

    When `_send_broadcast_email` raises mid-batch, the broadcast_email_retry_worker
    picks it up with exponential backoff (60s → 5min → 30min → 2h → 12h) and
    re-attempts. After 5 failures `dead_letter_at` is set and the row is
    surfaced via `/admin/broadcast-email-retry/status` for operator review.

    See migration 0071_bc2_email_failed.
    """
    __tablename__ = 'broadcast_email_failed'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    broadcast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('admin_broadcasts.id', ondelete='CASCADE'), nullable=False
    )
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    developer_ids_json: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    error_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    next_retry_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_retry_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_letter_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return (
            f"<BroadcastEmailFailed(id={self.id}, broadcast_id={self.broadcast_id}, "
            f"batch={self.batch_index}, retries={self.retry_count})>"
        )


class DeveloperNotificationRead(Base):
    """
    Records which developer has dismissed / read which broadcast.
    Presence of a row means the developer has acknowledged that broadcast.
    """
    __tablename__ = 'developer_notification_reads'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broadcast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('admin_broadcasts.id', ondelete='CASCADE'), nullable=False
    )
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('developers.id', ondelete='CASCADE'), nullable=False
    )
    read_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    broadcast: Mapped['AdminBroadcast'] = relationship('AdminBroadcast', back_populates='reads')
    developer: Mapped['Developer'] = relationship('Developer')

    __table_args__ = (
        UniqueConstraint('broadcast_id', 'developer_id', name='uix_notif_read_pair'),
        Index('ix_notif_read_dev', 'developer_id', 'broadcast_id'),
    )

    def __repr__(self):
        return f"<DeveloperNotificationRead(broadcast={self.broadcast_id}, dev={self.developer_id})>"

# ---------------------------------------------------------------------------
# END f034
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# f036_federation_compliance — Federation Policy Compliance Models
# ---------------------------------------------------------------------------

class FederatedRegistryCompliance(Base):
    """
    Stores the policy snapshot and compliance state for each federated peer.
    One-to-one with PeerRegistry.

    Created on admission; updated by compliance_poller and FederationComplianceMonitor.
    """
    __tablename__ = 'federated_registry_compliance'

    id: Mapped[uuid.UUID] = mapped_column(
        SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    peer_registry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('peer_registries.id', ondelete='CASCADE'),
        nullable=False, unique=True, index=True
    )
    # Policy snapshot stored at admission
    policy_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    policy_hash: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment='SHA-256 of canonical sorted policy JSON at time of admission'
    )
    policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Federation status state machine
    federation_status: Mapped[str] = mapped_column(
        String(20), default='pending', nullable=False,
        comment='pending | federated | quarantined | soft_quarantined | blacklisted'
    )
    compliance_score: Mapped[float] = mapped_column(
        Float, default=100.0, nullable=False,
        comment='0-100 score, degrades on drift events'
    )
    drift_events_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default='0', nullable=False
    )

    # Quarantine state
    quarantine_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quarantine_since: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quarantine_grace_expires: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment='Grace period end; if policy not corrected by this time, quarantine is hard'
    )
    quarantine_events: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default='[]',
        comment='List of past quarantine incident summaries'
    )

    # Blacklist state
    blacklist_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blacklisted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    blacklisted_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Polling metadata
    last_poll_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_hash_mismatch_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_poll_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default='0', nullable=False,
        comment='Consecutive unreachable polls; quarantine triggers at 3'
    )

    # Admission metadata
    admitted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    admitted_by: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        comment='Email of admin who completed the admission'
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationship
    peer_registry: Mapped['PeerRegistry'] = relationship(
        'PeerRegistry', backref=backref('compliance_record', uselist=False, passive_deletes=True)
    )

    __table_args__ = (
        Index('ix_frc_status', 'federation_status'),
        Index('ix_frc_peer', 'peer_registry_id'),
    )

    def in_grace_period(self) -> bool:
        """True if quarantine grace period has not yet expired."""
        if self.quarantine_grace_expires is None:
            return False
        import datetime as dt
        return dt.datetime.now(dt.timezone.utc) < self.quarantine_grace_expires

    def grace_expired(self) -> bool:
        """True if grace period was set and has now elapsed."""
        if self.quarantine_grace_expires is None:
            return False
        import datetime as dt
        return dt.datetime.now(dt.timezone.utc) >= self.quarantine_grace_expires

    def __repr__(self):
        return (
            f"<FederatedRegistryCompliance("
            f"peer={self.peer_registry_id}, "
            f"status='{self.federation_status}', "
            f"score={self.compliance_score})>"
        )


class RegistryOperatingState(Base):
    """
    Singleton operational state table (one row per registry instance).

    Tracks transient runtime counters that should NOT live in the versioned
    RegistryEnforcementPolicy (which is audited and immutable-per-version).

    Accessed/updated by:
      - background_tasks/staking_distributor.py  (treasury zero-day counter)
      - routers/registry_health.py               (economic health fields)
      - services/federation_compliance_monitor.py (treasury quarantine trigger)

    Singleton pattern: always the same UUID (REGISTRY_STATE_SINGLETON_ID).
    """
    __tablename__ = 'registry_operating_state'

    # Fixed UUID — always the same row
    id: Mapped[uuid.UUID] = mapped_column(
        SQLUUID(as_uuid=True), primary_key=True,
        default=lambda: uuid.UUID('00000000-0000-0000-0000-000000000001')
    )

    # Treasury bankruptcy tracking. §FEELOCK (2026-09-11): `treasury_zero_days` is RE-DERIVED from
    # the distribution ledger on every evaluation (federation_compliance_monitor.unfunded_streak):
    # consecutive days on which stakers were owed and the reward waterfall was exhausted, never a
    # count of zero-total runs. The two flags are recorded and read by nothing: nothing enforces
    # them. (The `comment=` strings are DB metadata from migration f036 and are left as written.)
    treasury_zero_days: Mapped[int] = mapped_column(
        Integer, default=0, server_default='0', nullable=False,
        comment='Consecutive days with zero treasury balance / zero distribution'
    )
    treasury_max_fee_locked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False,
        comment='True when treasury bankruptcy max fee lock is active'
    )
    treasury_quarantine_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False,
        comment='True when treasury bankruptcy auto-quarantine has fired'
    )
    last_treasury_check_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # CONSUL — Compliance poller enforcement mode (0007 migration)
    # Values: 'off' | 'dry_run' | 'enforcing'
    #   off        — poller skips all cycles
    #   dry_run    — poller detects drift + emits ComplianceDryRunDrift events,
    #                never calls trigger_quarantine
    #   enforcing  — live quarantine (also still requires FEDERATION_ENFORCEMENT_ACTIVE=true
    #                env var — two independent kill switches)
    compliance_enforcement_mode: Mapped[str] = mapped_column(
        String(20), default='off', server_default='off', nullable=False,
        comment="CONSUL enforcement mode: off | dry_run | enforcing"
    )
    compliance_mode_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Timestamp of last compliance_enforcement_mode change"
    )
    compliance_mode_updated_by: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Admin email that last changed compliance_enforcement_mode"
    )

    # General operational metadata
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self):
        return (
            f"<RegistryOperatingState("
            f"zero_days={self.treasury_zero_days}, "
            f"max_fee_locked={self.treasury_max_fee_locked}, "
            f"enforcement_mode={self.compliance_enforcement_mode})>"
        )


# Convenience constant for singleton row access
REGISTRY_STATE_SINGLETON_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')

# ---------------------------------------------------------------------------
# END f036
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# f037 — Event Emission Policy (Supply Invariant Fix)
# ---------------------------------------------------------------------------

class EventEmissionPolicy(Base):
    """
    Per-event-type emission policy. Controls which layer (TEG/Registry)
    is authorized to emit each event type to the EventStore.

    This prevents double-emission (the root cause of supply invariant drift)
    by giving each event type a single authoritative emitter.

    Checked by event_emitter.py before every emission.
    Managed via admin API: GET/PUT /admin/event-emission-policies
    """
    __tablename__ = 'event_emission_policies'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
        comment='Event type name (e.g., TokensTransferred, TokensStaked)'
    )
    emit_from_teg: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False,
        comment='Whether TEG layer is authorized to emit this event'
    )
    emit_from_registry: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sa.true(), nullable=False,
        comment='Whether Registry layer is authorized to emit this event'
    )
    skip_in_projection: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False,
        comment='If true, EventStore projection ignores this event in balance calculation'
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment='Human-readable description of this policy'
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        src = []
        if self.emit_from_teg: src.append('teg')
        if self.emit_from_registry: src.append('registry')
        return f"<EventEmissionPolicy({self.event_type}, source={'+'.join(src) or 'none'}, skip_proj={self.skip_in_projection})>"

# ---------------------------------------------------------------------------
# END f037
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# f038 — Developer Achievement System
# ---------------------------------------------------------------------------

class AchievementReward(Base):
    """
    Configurable payout amounts per achievement type.
    Admin-editable — change payouts for beta vs release without code changes.
    """
    __tablename__ = 'achievement_rewards'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    achievement_type: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
        comment='Achievement type key (e.g., tutorial_agent_lifecycle)'
    )
    achievement_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment='Display name (e.g., First Contact)'
    )
    payout_avt: Mapped[float] = mapped_column(
        Float, default=0, nullable=False,
        comment='AVT payout amount (0 = no payout, configurable for beta vs release)'
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sa.true(), nullable=False,
        comment='Whether this achievement can be earned and paid out'
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class DeveloperAchievement(Base):
    """
    Earned achievements per developer. UNIQUE(developer_id, achievement_type)
    ensures no duplicate payouts — ever.
    """
    __tablename__ = 'developer_achievements'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('developers.id', ondelete='CASCADE'), nullable=False
    )
    achievement_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment='Achievement type key — matches achievement_rewards.achievement_type'
    )
    achievement_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment='Display name at time of award'
    )
    awarded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payout_avt: Mapped[float] = mapped_column(
        Float, default=0, nullable=False,
        comment='Actual AVT paid (0 if no payout or payout disabled)'
    )
    payout_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment='TEG transaction ID for the payout (null if no payout)'
    )
    payout_status: Mapped[str] = mapped_column(
        String(20), default='pending', server_default='pending', nullable=False,
        comment='pending = not yet paid, paid = AVT transferred, no_agent = user had no agent'
    )
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        PG_JSONB, nullable=True,  # R57: jsonb (mig 0174)
        comment='Extra data: completion time, steps, track info'
    )

    __table_args__ = (
        UniqueConstraint('developer_id', 'achievement_type', name='uq_dev_achievement_type'),
        Index('ix_dev_achievements_dev_id', 'developer_id'),
    )

    def __repr__(self):
        return f"<DeveloperAchievement({self.developer_id}, {self.achievement_type}, {self.payout_avt} AVT)>"

# ---------------------------------------------------------------------------
# END f038
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# f041: AVT Funding Requests
# ---------------------------------------------------------------------------
import enum

class FundingRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FUNDED = "funded"


class FundingRequest(Base):
    """Developer/agent funding requests — admin-approved AVT distribution."""
    __tablename__ = "funding_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    requester_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=6), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=FundingRequestStatus.PENDING.value, nullable=False, index=True
    )

    # Admin review
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=30, scale=6), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Funding execution
    funded_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    funding_transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<FundingRequest(id={self.id}, did='{self.requester_did}', amount={self.requested_amount}, status='{self.status}')>"

# ---------------------------------------------------------------------------
# END f041
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# f042_support_tickets — Support Ticket System
# ---------------------------------------------------------------------------

class SupportTicket(Base):
    """
    A support ticket created by a developer.
    Tickets contain a thread of messages between the developer and admin staff.
    """
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default='general'
    )  # bug, question, feature, account, general
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default='open', index=True
    )  # open, in_progress, resolved, closed
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default='normal'
    )  # low, normal, high, urgent
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[List["SupportMessage"]] = relationship(
        "SupportMessage", back_populates="ticket",
        order_by="SupportMessage.created_at", cascade="all, delete-orphan"
    )
    developer: Mapped["Developer"] = relationship("Developer", foreign_keys=[developer_id])

    def __repr__(self):
        return f"<SupportTicket(id={self.id}, subject='{self.subject}', status='{self.status}')>"


class SupportMessage(Base):
    """
    A single message within a support ticket thread.
    sender_type is 'user' (developer) or 'admin'.
    """
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" or "admin"
    sender_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["SupportTicket"] = relationship("SupportTicket", back_populates="messages")

    def __repr__(self):
        return f"<SupportMessage(id={self.id}, ticket={self.ticket_id}, sender='{self.sender_type}')>"

# ---------------------------------------------------------------------------
# END f042
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# f043_federation_licenses — Federation License Key System
# ---------------------------------------------------------------------------

class FederationLicense(Base):
    """
    Federation license key for controlling which operators can federate
    with the network. Each operator must present a valid, active license
    to participate in cross-registry federation.

    License keys follow the format: tp_fed_<64 hex chars> (71 chars total).
    Only the SHA-256 hash of the key is stored; the plain key is shown once
    at generation time and cannot be recovered.

    Managed via admin API: /admin/federation/licenses/*
    Verified via the verify_federation_license FastAPI dependency.
    """
    __tablename__ = "federation_licenses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    operator_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment='Human-readable name of the federation operator'
    )
    operator_did: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True,
        comment='DID of the federation operator (unique per license)'
    )
    license_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment='SHA-256 hex digest of the license key (never store plain key)'
    )
    license_key_prefix: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment='First 12 chars of the key for display/identification'
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
        comment='License status: active, suspended, revoked'
    )
    issued_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment='Reason for revocation (set by admin)'
    )
    # Option D-light Phase D1 (2026-04-21) — suspension audit trail.
    # When status flips to "suspended" via cascade from suspend_operator, these
    # columns capture the timestamp, actor, and reason.
    suspended_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suspended_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True,
        comment='Admin developer who suspended the license'
    )
    suspended_reason: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment='Reason for suspension (set by admin)'
    )
    max_agents: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False,
        comment='Maximum number of agents this operator can register'
    )
    max_events_per_minute: Mapped[int] = mapped_column(
        Integer, default=1000, nullable=False,
        comment='Rate limit: max events per minute for this operator'
    )
    federation_tier: Mapped[str] = mapped_column(
        String(50), default="standard", nullable=False,
        comment='Federation tier: standard, enterprise'
    )
    last_seen_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment='Last time this license was presented for verification'
    )
    event_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment='Total number of events processed under this license'
    )
    min_image_version: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment='Minimum container image version required for this operator'
    )
    # §FRAMELIC (mig 0176) — WHO this licence is for. 'operator' is every pre-0176 row.
    # A frame licence and an operator licence share this table on purpose: one lifecycle,
    # one audit trail, one revoke path. The discriminator is what lets verification refuse
    # a frame key presented by an operator, and the reverse.
    licensee_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="operator", server_default="operator",
        comment="Licensee class: 'operator' (a cloud operator) or 'frame' (a sovereign frame)"
    )

    __table_args__ = (
        Index("ix_federation_licenses_status", "status"),
        Index("ix_federation_licenses_licensee_type", "licensee_type"),
        Index("ix_federation_licenses_operator_did", "operator_did"),
        Index("ix_federation_licenses_license_key_hash", "license_key_hash"),
    )

    def __repr__(self):
        return (
            f"<FederationLicense(id='{self.id}', operator='{self.operator_name}', "
            f"did='{self.operator_did}', status='{self.status}')>"
        )

# ---------------------------------------------------------------------------
# END f043
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BL-1 (2026-05-11) — Federation license self-serve rotation idempotency
# Backs POST /api/v1/federation/license/rotate-self.
# ---------------------------------------------------------------------------

class FederationLicenseRotation(Base):
    """Idempotency-key state for self-serve license rotation.

    Three-phase commit (Operator_CLI_Strategy.md §7.2.1):
      pending   — Phase 1: new license row pre-allocated; old still active
      committed — Phase 2: old license revoked; new license active
      returned  — Phase 3: plain key returned to caller (once)
      expired   — past expires_at; GC sweep marks as expired

    A retry with the same idempotency_key sees the row, resumes the appropriate
    phase, and returns the same plain key (per §6.2 — strictly once per key).
    """
    __tablename__ = "federation_license_rotations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
        comment='X-Idempotency-Key header value supplied by the caller'
    )
    caller_license_id: Mapped[str] = mapped_column(
        String(36), nullable=False,
        comment='ID of the license whose holder requested the rotation'
    )
    prev_license_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="",
        comment='SHA-256 of the pre-rotation key — used for replay-auth so the OLD key still proves identity within the 24h idempotency window'
    )
    new_license_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True,
        comment='ID of the newly-issued license (in update-in-place: same as caller_license_id)'
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment='Rotation state: pending, committed, returned, expired'
    )
    reason: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment='Operator-supplied reason: leak_suspected, scheduled_rotation, post_incident'
    )
    new_license_key: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True,
        comment='Plain key cached for once-only retry of Phase 3. Cleared at returned-state.'
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    committed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    returned_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment='Idempotency-key TTL — 24h from creation'
    )

    __table_args__ = (
        Index("ix_fed_lic_rotations_caller", "caller_license_id"),
        Index("ix_fed_lic_rotations_expires", "expires_at"),
    )

    def __repr__(self):
        return (
            f"<FederationLicenseRotation(id='{self.id}', key='{self.idempotency_key[:8]}...', "
            f"status='{self.status}')>"
        )


# ---------------------------------------------------------------------------
# f045_a2a_payment — A2A Payment Authorization Tokens
# ---------------------------------------------------------------------------

import enum as _enum


class A2APaymentStatus(str, _enum.Enum):
    AUTHORIZED = "authorized"
    CONSUMED = "consumed"
    SETTLING = "settling"       # TEG transfer in-flight (async fire-and-forget)
    SETTLED = "settled"
    EXPIRED = "expired"
    FAILED = "failed"
    RELEASED = "released"


class A2APaymentAuthorization(Base):
    """
    A2A Payment Authorization — registry-issued tokens that prove
    a caller has reserved funds before calling an agent's A2A endpoint.

    Flow: authorize → consumed (agent verified) → settled (TEG transfer done)
    """
    __tablename__ = "a2a_payment_authorizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    caller_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=6), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=A2APaymentStatus.AUTHORIZED.value, nullable=False, index=True
    )

    # Optional contract binding
    contract_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # CONTRACT SPINE (mig 0129): spine contract id (ctr_…); legacy int stays for RUC history
    contract_ref: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Task and settlement tracking
    task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    settlement_tx_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)

    # Timestamps
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self):
        return (
            f"<A2APaymentAuthorization(id='{self.id}', caller='{self.caller_did}', "
            f"target='{self.target_agent_did}', amount={self.amount}, status='{self.status}')>"
        )

# ---------------------------------------------------------------------------
# END f045
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# f046_operator_applications — Operator Onboarding Phase 1
# ---------------------------------------------------------------------------

class OperatorApplication(Base):
    """
    Tracks operator registry license applications through the review workflow.
    Applications are submitted publicly (no auth required) and reviewed by admins.

    Status flow: pending -> approved / rejected, and later approved -> suspended -> approved, or -> revoked.
    ⚠ THERE IS NO "activated" STATUS AND THERE NEVER HAS BEEN. Activation stamps `activated_at` and leaves the
    status at "approved"; an earlier version of this line said otherwise and a guard was written against it that
    could never pass (2026-09-16, §OPDIST). An activated, live application is `status == "approved"` AND
    `activated_at is not None` — read both, and read them from here rather than from a sentence.
    On activation, the linked Developer gets is_federation_operator=True, federation_operator_status='approved'.
    """
    __tablename__ = "operator_applications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    organization: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deployment: Mapped[str] = mapped_column(String(50), nullable=False, default="undecided")
    experience: Mapped[str] = mapped_column(String(50), nullable=False, default="beginner")
    use_case: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # §FESUITE V0595 (mig 0186): the configuration the applicant chose (services/env_catalog.py keys, operator scope;
    # the route refuses the frame's); the provisioner writes it into the operator's env after the inherited posture
    env_choices: Mapped[dict] = mapped_column(
        PG_JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # --- f047: Bundle provisioning fields ---
    bundle_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    bundle_generated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bundle_download_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    bundle_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    docker_registry_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    spire_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # --- END f047 ---

    # --- f048: Revocation fields ---
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revoked_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    # --- END f048 ---

    # --- f049: Activation code fields ---
    activation_code_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    activation_code_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    # --- END f049 ---

    # --- f050: Docker pull token fields ---
    docker_pull_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    docker_pull_token_prefix: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    docker_pull_token_issued_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    docker_pull_allowed_repos: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # --- END f050 ---

    # --- f051: Cloud hosting fields ---
    cloud_hosted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )
    cloud_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cloud_port_base: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cloud_provisioned_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cloud_torn_down_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cloud_stack_dir: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # --- END f051 ---

    # Relationships
    developer: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[developer_id], backref="operator_applications"
    )
    reviewer: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[reviewed_by]
    )
    revoker: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[revoked_by]
    )
    activated_developer: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[activated_developer_id]
    )

    def __repr__(self):
        return (
            f"<OperatorApplication(id='{self.id}', name='{self.name}', "
            f"email='{self.email}', status='{self.status}')>"
        )

# ---------------------------------------------------------------------------
# END f046
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# f058_frame_invitations — Sovereign Frame Federation Handshake (WS3, 2026-04-21)
# ---------------------------------------------------------------------------

class FrameInvitation(Base):
    """
    Tracks sovereign-frame federation invitations through the bilateral
    handshake workflow.

    A remote frame POSTs an invitation to this frame (initiator_* fields are
    the remote's details + a nonce it generated). Admin reviews; on approve,
    this frame imports the remote's SPIRE bundle, inserts a peer_registries
    row, and POSTs the remote's /finalize endpoint with our bundle + the echoed
    nonce. Remote completes the handshake on their side. Status becomes
    'approved' on admin action, then 'completed' when the bilateral callback
    lands.

    Status flow:
      pending → approved → (finalize-callback from remote confirms) → approved + completed_at
      pending → rejected
      (post-completion) → revoked  (admin tears down federation)

    Note: 'approved' + completed_at IS NULL means admin approved on our side
    but the bilateral /finalize POST to the remote hasn't succeeded yet.
    Retryable via finalize-retry admin endpoint.
    """
    __tablename__ = "frame_invitations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # --- Initiator (remote frame) details ---
    initiator_trust_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    initiator_bundle_endpoint_url: Mapped[str] = mapped_column(String(500), nullable=False)
    initiator_federation_endpoint_url: Mapped[str] = mapped_column(String(500), nullable=False)
    initiator_event_store_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    initiator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    initiator_contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    initiator_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    initiator_nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    initiator_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    # --- Review ---
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending | approved | rejected | completed | revoked
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # --- Completion ---
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    peer_registry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("peer_registries.id", ondelete="SET NULL"), nullable=True
    )
    spire_bundle_imported_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # --- Revocation ---
    revoked_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # --- §FEDLICENCE (0182): the network licence certificate (compact JWS) and its chain the initiator presented ---
    initiator_licence_certificate: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    initiator_licence_chain: Mapped[Optional[List[str]]] = mapped_column(PG_JSONB, nullable=True)
    initiator_licence_key: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    # --- Timestamps ---
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # --- Relationships ---
    reviewer: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[reviewed_by]
    )
    revoker: Mapped[Optional["Developer"]] = relationship(
        "Developer", foreign_keys=[revoked_by]
    )
    peer_registry: Mapped[Optional["PeerRegistry"]] = relationship(
        "PeerRegistry", foreign_keys=[peer_registry_id]
    )

    def __repr__(self):
        return (
            f"<FrameInvitation(id='{self.id}', trust_domain='{self.initiator_trust_domain}', "
            f"status='{self.status}')>"
        )

# ---------------------------------------------------------------------------
# END f058
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ZKP ATTESTATION MATURATION (2026-04-28, sandbox A)
# ---------------------------------------------------------------------------
class Attestation(Base):
    """ZKP attestation row.

    Phase 1 columns only (persistence + indexed query). Lifecycle (Phase 2),
    bundle cache (Phase 4), and dispute back-references (Phase 3) are
    additive in their respective migrations.
    """
    __tablename__ = "attestations"

    id: Mapped[uuid.UUID] = mapped_column(
        SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    circuit_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    circuit_version: Mapped[str] = mapped_column(String(64), nullable=False)
    public_inputs: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    proof_b64: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_parameters_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(timezone.utc),
        index=True,
    )
    verified_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SQLUUID(as_uuid=True), nullable=True
    )

    # ── Phase 2 — Lifecycle (expiry + revocation) ─────────────────────────
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    expired_emitted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Phase 4 — Signed bundle cache ─────────────────────────────────────
    bundle_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signature_pubkey_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    __table_args__ = (
        Index("ix_attestations_agent_submitted", "agent_did", "submitted_at"),
        Index("ix_attestations_circuit_submitted", "circuit_id", "submitted_at"),
        Index("ix_attestations_verified_submitted", "verified", "submitted_at"),
    )

    def __repr__(self):  # pragma: no cover
        return (
            f"<Attestation(id={self.id}, agent_did='{self.agent_did}', "
            f"circuit='{self.circuit_id}', verified={self.verified})>"
        )
# ---------------------------------------------------------------------------
# END ZKP ATTESTATION MATURATION (Phase 1)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ZKP ATTESTATION MATURATION — Phase 5: periodic-attestation schedule
# ---------------------------------------------------------------------------
class AttestationSchedule(Base):
    """Per-(agent, circuit) cadence entry for periodic ZKP attestation.

    Agents that publish recurring claims declare a row here so the registry
    can fan out reminders when an attestation is overdue. Submit-side
    coupling refreshes `last_attestation_at` and advances `next_due_at`
    on every successful attestation matching (agent_did, circuit_id).
    """
    __tablename__ = "attestation_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    circuit_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    last_attestation_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_due_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_reminder_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "agent_did", "circuit_id",
            name="uq_attestation_schedules_agent_circuit",
        ),
    )

    def __repr__(self):  # pragma: no cover
        return (
            f"<AttestationSchedule(id={self.id}, agent_did='{self.agent_did}', "
            f"circuit='{self.circuit_id}', interval_hours={self.interval_hours}, "
            f"enabled={self.enabled})>"
        )
# ---------------------------------------------------------------------------
# END ZKP ATTESTATION MATURATION (Phase 5)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ASYNC CROSS-FRAME TRANSFER (TEG_CROSS_FRAME_BACKEND=async, 2026-05-03)
# ---------------------------------------------------------------------------
# Sender-side `cross_frame_transfers`: one row per outbound async cross-frame
# transfer. Status flow: locked → settled (happy) | refunded (saga timeout).
# Receiver-side `cross_frame_transfers_inbound`: one row per inbound credit.
# Status flow: credited → reversed (only if a Refunded event arrives).
#
# Both sides idempotent at the DB layer: PK on transfer_id absorbs replay.
# Coordination is pure event-driven via SF-4 cross-frame ES replication +
# foreign_events Pub/Sub bridge — never HTTP between frames.
# ---------------------------------------------------------------------------
class CrossFrameTransfer(Base):
    """Sender-side row for an async cross-frame transfer."""
    __tablename__ = "cross_frame_transfers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sender_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    receiver_did: Mapped[str] = mapped_column(String(255), nullable=False)
    target_frame: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="locked", server_default="locked"
    )  # locked | settled | refunded
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    timeout_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    settled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refunded_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )

    __table_args__ = (
        Index("ix_cross_frame_transfers_status_timeout", "status", "timeout_at"),
    )


# --- CANARY system tables (Phase 2, 2026-05-04) — registry-a only ---

class CanaryAgent(Base):
    """A pre-funded system agent that fires continuous synthetic-transaction monitoring transfers."""
    __tablename__ = "canary_agents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_did: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret: Mapped[str] = mapped_column(Text, nullable=False)
    registry_id: Mapped[str] = mapped_column(String(64), nullable=False)
    registry_url: Mapped[str] = mapped_column(String(255), nullable=False)
    frame: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    # §MONEY-M2 (R13): a canary is pre-funded with REAL money, and 100,000 is
    # the whole of a small network's supply. The column default is now a knob
    # the network profile owns; the callable keeps it read-at-insert rather than
    # frozen at import, so a profile change needs no migration.
    prefund_amount: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), nullable=False,
        default=lambda: _np_money_knob("CANARY_PREFUND_AMOUNT", "100000"),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CanaryPath(Base):
    """One sender→receiver path in the canary test matrix."""
    __tablename__ = "canary_paths"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    path_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    sender_agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("canary_agents.id"), nullable=False
    )
    receiver_agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("canary_agents.id"), nullable=False
    )
    backend: Mapped[str] = mapped_column(String(16), nullable=False)  # async|2pc|intra
    amount: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), nullable=False, default=Decimal("1.0")
    )
    interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    slo_http_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    slo_settled_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    slo_p95_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    reverse_pair_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("canary_paths.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # §pass30 — which transport the runner should use for this path:
    # 'bearer' (default), 'federation_mtls' (legacy §15 registry-SVID), 'ironhand_mtls' (per-agent SVID via workload container)
    transport: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bearer", server_default="bearer"
    )


class CanaryTestResult(Base):
    """Append-only history of every canary transfer fired."""
    __tablename__ = "canary_test_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    test_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("canary_paths.id"), nullable=False
    )
    fired_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    backend: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_did: Mapped[str] = mapped_column(String(255), nullable=False)
    receiver_did: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    transfer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    http_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    phase_latencies: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="fired", server_default="fired"
    )  # fired|passed|failed
    failure_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # §pass30 — which transport the runner actually used for this fire
    # (closes pre-existing gap: runner set result["transport"] but never persisted)
    transport: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


# --- END CANARY ---


class CrossFrameTransferInbound(Base):
    """Receiver-side row for an async cross-frame transfer inbound credit."""
    __tablename__ = "cross_frame_transfers_inbound"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sender_did: Mapped[str] = mapped_column(String(255), nullable=False)
    receiver_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_frame: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="credited", server_default="credited"
    )  # credited | reversed
    credited_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reversed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )


# ---------------------------------------------------------------------------
# PB-1 — Fiat → AVT on-ramp (Stripe Checkout, EUR-denominated)
# Mainframe-only by construction. Federated registries cannot mint AVT,
# so they cannot run Stripe→AVT pipes. See routers/fiat_onramp.py for the
# IS_CENTRAL_REGISTRY guard.
# ---------------------------------------------------------------------------

class FiatPurchaseStatus(str, _enum.Enum):
    PENDING = "pending"        # Checkout Session created, awaiting payment
    PROCESSING = "processing"  # PB-2 routed: webhook fired, cross-TEG fund in flight
    COMPLETED = "completed"    # Stripe webhook confirmed; AVT credited
    FAILED = "failed"          # Stripe payment failed or AVT credit failed
    REFUNDED = "refunded"      # Stripe charge.refunded webhook fired


class FiatPurchase(Base):
    """
    Audit row for one fiat → AVT purchase via Stripe Checkout.

    Two flows share this table:
      • Logged-in: developer_id + agent_did set at checkout-session creation.
      • Anonymous: only customer_email set; webhook resolves/creates Developer
        + Agent and back-fills developer_id + agent_did on completion.

    Idempotency: stripe_event_id (UNIQUE) prevents double-credit on webhook
    retry. stripe_session_id (UNIQUE) prevents duplicate Checkout creation.
    """
    __tablename__ = "fiat_purchases"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    stripe_session_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    # Set by webhook on first checkout.session.completed; UNIQUE prevents replay.
    stripe_event_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )

    # Anonymous flow uses customer_email; logged-in flow back-fills both.
    developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True, index=True
    )
    agent_did: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    customer_email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )

    amount_eur: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), nullable=False
    )
    amount_avt: Mapped[Decimal] = mapped_column(
        Numeric(precision=30, scale=6), nullable=False
    )
    avt_per_eur_rate: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), nullable=False
    )
    tier_label: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), default=FiatPurchaseStatus.PENDING.value,
        nullable=False, index=True
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    avt_transfer_tx_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # §LEDGERGATE (V0599, migration 0189): a direct-flow purchase whose credit did not land is OWED (status
    # processing, failure_reason "credit_owed: <why>"), retried by background_tasks/fiat_credit_retry with the
    # purchase's own Idempotency-Key until it lands or its budget runs out (then failed, reward_fund_failed: a human's).
    credit_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default='0', nullable=False
    )
    credit_next_attempt_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Anonymous-flow scaffolding: webhook may have created a fresh Developer +
    # Agent. Track that for the magic-link login email + admin reconciliation.
    anonymous_flow: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False
    )

    # Buyer-supplied names for the auto-created Developer + Agent (PB-1, 2026-05-09).
    # Optional — null when buyer skipped, or for logged-in flow where names already exist.
    # Webhook handler prefers these over auto-generated slugs.
    requested_developer_name: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    requested_agent_name: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    # Fiat T&C consent (W1, 2026-05-09 — Migration 0036).
    # Captures the buyer's explicit acceptance of the Terms (incl. § 13 Fiat
    # Purchases / 14-day withdrawal-right carve-out per §312g + §356(5) BGB)
    # at the moment of checkout. Both columns are nullable for backward
    # compatibility — pre-W1 rows simply have NULL values.
    tos_accepted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tos_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # PB-2 routed-fiat columns (Migration 0038, 2026-05-09).
    # `routed` discriminates the flow: false = direct mainframe (PB-1), true =
    # routed-via-operator (PB-2). The mainframe-side row has the target_*
    # columns; the operator-side row has mainframe_fiat_purchase_id linking
    # back. See INVESTIGATION_2026-05-09_ROUTED_FIAT_PURCHASE_FROM_OPERATORS.md.
    routed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False, index=True
    )
    target_operator_did: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    target_operator_registry_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cross_teg_correlation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    operator_callback_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    operator_callback_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default='0', nullable=False
    )
    operator_callback_last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    operator_callback_last_attempted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Operator-side only: links to the mainframe FiatPurchase id (UNIQUE).
    mainframe_fiat_purchase_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )

    # Founders Wall personalization (Migration 0039, 2026-05-10).
    # Optional opt-in fields the buyer can set during checkout to enrich their
    # public Founders Wall chip. All defaults preserve current anonymized
    # behavior: a row with display_name=NULL and display_country=NULL renders
    # as a tier-flare-only chip (today's behavior). Server sanitizes
    # display_name (URL strip + char allowlist + length cap). display_country
    # is a 2-letter ISO 3166-1 alpha-2 code, prefilled browser-side from the
    # user's locale and confirmed before submit (no server-side IP→country).
    display_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    display_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    show_on_wall: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sa.true(), nullable=False, index=True
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refunded_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # PB-3 (BL-2) Webhook Fiat Layer columns (Migration 0050, 2026-05-12).
    # `payment_provider` discriminates between PSPs ('stripe' default; 'mollie' from W3+).
    # `provider_*_id` columns are the canonical PSP identifiers post-PB-3; the legacy
    # `stripe_*_id` columns above are kept for the 30-day expand-contract transition
    # per strategy §A.7, then dropped via Migration 0053. Composite UNIQUE indexes on
    # (payment_provider, provider_event_id) + (payment_provider, provider_session_id).
    # `disputed_at` + `dispute_reason` track chargebacks (no auto-clawback per Commander
    # doctrine; surfaced to admin UI for manual review). See Webhook_Fiat_Layer_Strategy.md.
    payment_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="stripe", server_default="stripe", index=True
    )
    provider_session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    disputed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispute_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self):
        return (
            f"<FiatPurchase(id='{self.id}', provider='{self.payment_provider}', "
            f"session='{self.provider_session_id or self.stripe_session_id}', "
            f"eur={self.amount_eur}, avt={self.amount_avt}, status='{self.status}')>"
        )


# ---------------------------------------------------------------------------
# PB-1 — Configurable fiat tier pricing (DB-backed, versioned)
#
# Singleton-with-history pattern: at any time exactly ONE row has
# is_active=True and represents the live pricing. Every PUT inserts a NEW
# row + archives the prior active row (atomic swap in a transaction).
#
# Config JSON shape:
#   {
#     "tiers": [
#       { "floor_eur": "1.00",   "avt_per_eur": "2000", "tier_label": "tier_1_base",    "bonus_label": "" },
#       { "floor_eur": "20.00",  "avt_per_eur": "2500", "tier_label": "tier_2_value",   "bonus_label": "+25%" },
#       { "floor_eur": "100.00", "avt_per_eur": "3000", "tier_label": "tier_3_premium", "bonus_label": "+50%" }
#     ],
#     "min_eur": "1.00",
#     "max_eur": "500.00",
#     "currency": "EUR"
#   }
#
# Rates are economically critical — never edit tier rows in-place. Every
# change is auditable via version history + created_by_developer_id +
# `note` field. Admin endpoint requires `admin_treasury` flag.
# ---------------------------------------------------------------------------

class FiatPricingConfig(Base):
    """Versioned fiat→AVT pricing config. One active row at a time."""
    __tablename__ = "fiat_pricing_config"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false(), index=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by_developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id"), nullable=True
    )
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self):
        return (
            f"<FiatPricingConfig(v{self.version}, active={self.is_active}, "
            f"created={self.created_at})>"
        )


# --- Registry Self (§pass34 — canonical federation identity) ---
class RegistrySelf(Base):
    """Singleton row holding THIS registry's canonical federation identity.

    Replaces the prior pattern of reading `developer.display_name` of the
    first admin (a personal handle field that drifted when admins edited
    their profile). One row per registry, ever; `id=1` enforced via DB-side
    check constraint.

    Set by the alembic migration on first deploy. For cloud-ops, also written
    by cloud_provisioner at activation time. For mainframes, seeded from
    REGISTRY_FEDERATION_NAME env. Future: trust_domain, public_url, etc. live
    here too.

    Renames must NOT be casual: the federation_name is stamped into every
    native agent_card's `card_data.federation_metadata.origin_registry_name`.
    Changing it requires re-stamping those cards and notifying peers, so the
    admin rename endpoint (when shipped) will cascade.
    """
    __tablename__ = "registry_self"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=sa.text("1"))
    federation_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        sa.CheckConstraint("id = 1", name="registry_self_singleton_chk"),
    )

    def __repr__(self):
        return f"<RegistrySelf(federation_name={self.federation_name!r})>"


class AgentFlag(Base):
    """§pass49 B1 — persistent flag state for agents.

    Raised by reactors (JWS-verify-failed throttle, persistent-drift) when
    thresholds are crossed. Cleared by an admin via the acknowledge endpoint.
    UI surfaces unacknowledged flags as pills on AdminAgents + AgentCICD.
    """
    __tablename__ = "agent_flags"

    # The column is UUID (mig 0068 creates it in raw SQL). Mapped as String(36) it bound every comparison as VARCHAR,
    # Postgres has no uuid = varchar, and acknowledging a flag answered 500 for every id (§MCPSWEEP 2026-09-27).
    id: Mapped[str] = mapped_column(SQLUUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    flag_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raised_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raised_by_event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    acknowledged_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by_dev_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True
    )
    ack_notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    def __repr__(self):
        return f"<AgentFlag(did={self.agent_did}, type={self.flag_type}, acked={self.acknowledged_at is not None})>"


class FxRouterKeeperConfig(Base):
    """Single-row (id='singleton') config for the FX-router liquidity keeper (migration 0085).

    The op→op FX route's `@fx_router` is an FX-settlement suspense account funded from the
    `@fx_reserve` pool. This row drives the leader-elected `fx_router_keeper` worker on each
    reserve frame (registry-a / frame-c). Default OFF / opt-in — the master env gate
    `FX_ROUTER_KEEPER_ENABLED` must ALSO be true. FX Desk-editable via /api/v1/teg/fx/router-keeper.
    """
    __tablename__ = "fx_router_keeper_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="singleton")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_float: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)
    min_float: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)
    max_float: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)  # 0 = no sweep ceiling
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="treasury")       # treasury (default; operational capital) | fx_reserve (advanced — raids the AMM pool, moves the rate)
    check_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_move_per_cycle: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)  # 0 = uncapped
    dead_letter_refund_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dead_letter_max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self):
        return f"<FxRouterKeeperConfig(enabled={self.enabled}, target={self.target_float}, min={self.min_float})>"


class FxReserveKeeperConfig(Base):
    """Single-row (id='singleton') config for the FX-RESERVE peg keeper (migration 0092, 2026-06-17).

    Holds the cross-frame FX peg by keeping THIS frame's `@fx_reserve` (the AMM pool whose 3
    balances DEFINE the rate) within a [min, target, max] band. RATIO-PEG: tracking frames derive
    `target = anchor_reserve * ratio_vs_anchor` each cycle (the anchor floats freely); the anchor
    frame uses `target_float` directly. MOVE-ONLY (treasury <-> reserve, Δ-neutral) — NEVER
    auto-mints; minting stays manual/op-gated (Commander decision). Default OFF / opt-in: env
    `FX_RESERVE_KEEPER_ENABLED` must ALSO be true. FX-Desk editable via /api/v1/teg/fx/reserve-keeper.
    Driven by the leader-elected `fx_reserve_keeper` worker on each reserve frame (A/B/C).
    `operator_mode` lets a future AI agent drive it (v2) over the same guarded primitives.
    """
    __tablename__ = "fx_reserve_keeper_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="singleton")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anchor_currency: Mapped[str] = mapped_column(String(16), nullable=False, default="AVT")
    ratio_vs_anchor: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=1)   # this_ccy : anchor (1 = parity); ignored on anchor frame
    target_float: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)       # anchor frame: absolute target; tracking frame: fallback if anchor read fails
    min_float: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)          # low watermark / hard floor (>= FX_RESERVE_FLOOR_<ccy>)
    max_float: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)          # high watermark / hard ceiling (0 = no sweep)
    deadband_pct: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.05"))  # anti-churn hysteresis (fraction)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="treasury")             # v1: treasury only (move-only)
    max_move_per_cycle: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)  # 0 = uncapped
    check_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    operator_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="worker")         # worker | agent | off (agent = v2)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self):
        return f"<FxReserveKeeperConfig(enabled={self.enabled}, anchor={self.anchor_currency}, target={self.target_float})>"


class GatewayFloatKeeperConfig(Base):
    """Single-row (id='singleton') config for the AGORA gateway-float keeper (migration 0096, 2026-06-19).

    Keeps THIS frame's passport gateway (`did:theprotocol:agora-gateway-<ccy>`) SOLVENT so refund/
    dividend repatriations never strand. The gateway is a shared cross-frame FLOAT (passport deposits
    in; order-funding + repats out of the SAME balance) that bleeds the FX spread and can be over-drawn
    by order-funding spending money owed to pending repats — with nothing to refill it. This keeper holds
    `gateway_liquid >= outstanding_repat_obligations + buffer`, MOVE-ONLY treasury→gateway via the
    reward-funding waterfall (fee_collector→treasury, Δ-neutral; NEVER auto-mints — a dry shortfall
    raises an alert, manual mint stays the Commander's lever). TOP-UP ONLY (a float, not a rate-defining
    reserve — no upper sweep band). Default OFF / opt-in: env `GATEWAY_KEEPER_ENABLED` must ALSO be true.
    Leader-elected `gateway_float_keeper` worker on each venue frame. Pairs with the sweeper reservation
    (env `EXCHANGE_PASSPORT_RESERVE_REPAT`) so the two make the gateway solvent by construction.
    """
    __tablename__ = "gateway_float_keeper_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="singleton")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    buffer: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)               # working cushion above outstanding obligations
    deadband_pct: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.05"))  # anti-churn hysteresis (fraction)
    max_move_per_cycle: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0)   # 0 = uncapped
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="treasury")               # v1: reward-funding waterfall (fee_collector→treasury)
    check_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    operator_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="worker")          # worker | off
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self):
        return f"<GatewayFloatKeeperConfig(enabled={self.enabled}, buffer={self.buffer})>"


class FxRouteDeadLetter(Base):
    """Durable record of funds parked at `@fx_router` by a failed-compensation op→op FX route
    (migration 0085). The `fx_router_keeper` worker refunds the ORIGINAL SENDER, retry-until-settled,
    so failed senders are made whole automatically (the true 'auto-refunding'). One row per route_id.
    """
    __tablename__ = "fx_route_dead_letters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    route_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    origin_did: Mapped[str] = mapped_column(String(120), nullable=False)
    origin_teg_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    origin_registry_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="AVT")
    parked_at_did: Mapped[str] = mapped_column(String(120), nullable=False)
    # pre_conversion | post_conversion | post_conversion_remote | egress_unknown | swap_unknown (the last two HELD,
    # §REPATLANE-2: a paying leg whose outcome is not known; nothing refunds them on its own)
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="pre_conversion")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")          # pending | sweeping | refunded | swept | delivered | failed
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution_tx: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # §FXSELFHEAL (mig 0145): receiver captured AT PARKING TIME (kills the ES-join fragility);
    # claim-before-sweep CAS fields — the ONLY double-pay guard on a rail with no idempotency.
    receiver_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    claimed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class FxRouteDelivery(Base):
    """§FXSELFHEAL (mig 0145) — the DESTINATION frame's durable record that an FX route was
    delivered FROM here. The already-delivered guard needs a LOCAL answer: delivery truth
    otherwise lives only in a TEG memo the registry cannot query, and the 2026-08-10 audit
    found two routes whose egress COMPLETED 4-6 s AFTER the origin wrote its dead-letter row
    (an age gate cannot catch that class; a delivery ledger can). route_id is the PK, so the
    same route can never be recorded — or re-swept — twice."""
    __tablename__ = "fx_route_deliveries"

    route_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    receiver_did: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # egress | egress-local | recovery
    tx_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    delivered_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<FxRouteDeadLetter(route={self.route_id}, {self.amount} {self.currency}, status={self.status})>"


class CanaryRemotePath(Base):
    """§V0045 Canary Cockpit — MASTER-side schedule row for a canary path that EXECUTES
    on a peer registry (its home). registry-a (CANARY_RUNNER_MODE=master) schedules these
    and dispatches fires over the federation mTLS channel; the home registry fires its
    own local canary_paths row (agents/creds/SVIDs never leave home). Master owns the
    SCHEDULING fields here; the home keeps the EXECUTION config in its canary_paths —
    no dual-owned fields, no drift."""
    __tablename__ = "canary_remote_paths"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    home_registry: Mapped[str] = mapped_column(String(128), nullable=False)
    remote_path_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    path_label: Mapped[str] = mapped_column(String(128), nullable=False)
    interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint("home_registry", "remote_path_id", name="uq_canary_remote_paths_home_path"),
    )

    def __repr__(self):
        return f"<CanaryRemotePath({self.home_registry}#{self.remote_path_id} {self.path_label} active={self.is_active})>"


class CanaryDispatch(Base):
    """§V0045 Canary Cockpit — master-side audit ledger: one row per dispatched remote
    fire. test_id is the END-TO-END idempotency key (the home's canary_test_results
    pre-INSERT replays on it). outcome: sent | acked | replayed | rejected | dispatch_failed."""
    __tablename__ = "canary_dispatches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    test_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    home_registry: Mapped[str] = mapped_column(String(128), nullable=False)
    remote_path_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    path_label: Mapped[str] = mapped_column(String(128), nullable=False)
    dispatched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="sent")
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_canary_dispatches_home_time", "home_registry", "dispatched_at"),
    )

    def __repr__(self):
        return f"<CanaryDispatch({self.test_id} → {self.home_registry} {self.outcome})>"


# ═════════════════════════════════════════════════════════════════════════
# AGORA — organization stock exchange (migration 0088_agora_core, 2026-06-12)
#
# Shares are a registry-local asset ledger; they never touch the TEG. Every
# AVT/BVT leg flows through the TEG escrow mover (/admin/exchange/move with
# teg:system:exchange_escrow on one side) → plain transfers → transit-neutral
# → supply Δ=0 by construction. Participant columns are PLAIN DID STRINGS by
# doctrine (foreign agents must stay representable — no FK to agents).
# ═════════════════════════════════════════════════════════════════════════


class FederatedStockCard(Base):
    """Cached AGORA Stock Card pulled from a federated peer (consume side of
    Federated Stock Cards, 2026-06-17). One row per source registry (by SPIFFE).
    `listings_json` = the peer's catalog-only listing list (NO live prices).

    Written ONLY by federation_sync._sync_stock_card when STOCK_CARD_SYNC_ENABLED
    AND the stock card's EdDSA signature verifies against the peer's JWKS AND
    hash(catalog)==signed digest (fail-closed). Read-only metadata — Δ-irrelevant
    (trading still settles via passport + escrow + signed DevCard)."""
    __tablename__ = "federated_stock_cards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_spiffe_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    source_registry_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    listings_json: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    digest: Mapped[str] = mapped_column(String(80), nullable=False)
    # §2026-06-25 Federated Market Card: ADVISORY coarse price/sparkline block
    # {SYMBOL: {last, change_24h_pct, spark[≤24], as_of}} carried alongside the catalog.
    # NOT part of the signed catalog digest (cosmetic — a forged sparkline can't move
    # money). `market_epoch` = the coarse floor(now/EPOCH) advertised on the peer's
    # stock_card link; the consumer re-fetches when it advances (the catalog digest is
    # trade-invariant, so it alone never would). Both nullable → pre-feature rows fine.
    market_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    market_epoch: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # §2026-06-18 fan-out carry: True = this catalog was learned TRANSITIVELY via the
    # registry-card fan-out (a parent frame relayed a peer's cached catalog), verified
    # against the digest signed into that peer's relayed registry card. False = locally
    # direct-consumed (full JWS verify). Direct rows are AUTHORITATIVE and are never
    # clobbered by a carried (possibly staler) copy — the multi-source-clobber guard.
    via_fanout: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false(), default=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<FederatedStockCard({self.source_registry_name} {self.currency} n={len(self.listings_json or [])} via_fanout={self.via_fanout})>"


class ExchangeListing(Base):
    """One listed organization: ticker, share count, IPO terms, fees, status.
    treasury_agent_did = the org's real treasury Agent (un-loginable; receives
    IPO proceeds + the org fee split, pays dividends)."""
    __tablename__ = "exchange_listings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(255), sa.ForeignKey("organizations.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    treasury_agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="AVT")
    ipo_price: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    ipo_float: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ipo_sold: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    fee_org_split_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=6667)
    # §2026-06-22 P2.2 maker-taker pricing (migration 0102). maker_rebate_bps>0 carves a
    # rebate OUT of the protocol fee slice for the resting (maker) order at settlement —
    # NEVER added on top, so escrow still nets to notional (Δ=0). 0 = off (fleet-safe
    # default = exact current behaviour). The whole leg is also flag-gated
    # (EXCHANGE_MAKER_REBATE_ENABLED) in the service. rebate_requires_registration=true
    # ⇒ only a granted+active ExchangeMarketMaker for this listing earns the rebate.
    maker_rebate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rebate_requires_registration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.true())
    tick: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0.01"))
    band_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ipo")  # ipo|trading|halted|delisted
    created_by_dev: Mapped[int] = mapped_column(Integer, nullable=False)
    listing_fee_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    listing_fee_parked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # §#84 circuit-breaker (volatility auto-halt). cb_pct=0 ⇒ breaker OFF for this listing
    # (default = today's behaviour). When a fill moves `last` > cb_pct/1e4 from a rolling
    # reference within the window (env EXCHANGE_CB_WINDOW_SEC) the listing auto-halts until
    # cb_halted_until (now + EXCHANGE_CB_COOLDOWN_SEC); place_order lazy-resumes once it passes.
    # Δ-irrelevant (status/state only, no money/share mutation). Migration 0104.
    cb_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cb_ref_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    cb_ref_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cb_halted_until: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ExchangeListing(${self.symbol} {self.status} shares={self.total_shares})>"


class OrgSharePosition(Base):
    """The share ledger: integral share holdings per DID per listing.
    locked_qty backs open SELL orders (I-X2). avg_cost is a UX convenience
    (P&L display), not load-bearing for conservation."""
    __tablename__ = "org_share_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), nullable=False)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    qty: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    locked_qty: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("listing_id", "agent_did", name="uq_org_share_positions_listing_agent"),
    )

    def __repr__(self):
        return f"<OrgSharePosition({self.agent_did[:24]}… {self.qty}/{self.locked_qty} of {self.listing_id[:8]})>"


class ExchangeOrder(Base):
    """CLOB order. Lifecycle: funding → open → partial → filled
    (or cancelled/expired/rejected). BUY orders escrow money BEFORE entering
    the book (status=funding until the deposit leg settles); SELL orders lock
    shares ledger-side in the same transaction that inserts them."""
    __tablename__ = "exchange_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), nullable=False)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # buy|sell
    order_type: Mapped[str] = mapped_column(String(6), nullable=False)  # limit|market
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)  # NULL for market
    qty: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining: Mapped[int] = mapped_column(BigInteger, nullable=False)
    escrow_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    escrow_refunded: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    matched_notional: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="funding")
    client_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # §2026-06-22 P5.1 (migration 0103): advanced order types. Both opt-in per order;
    # defaults reproduce today's behavior exactly (no feature flag). Δ-NEUTRAL — they
    # only change whether/how much of an order rests or whether it is accepted, never a
    # new money flow. tif='ioc' ⇒ unfilled remainder cancels post-match (refunded by the
    # refund_terminal_buys worker, same as a market remainder); 'fok' ⇒ rejected pre-escrow
    # unless fully fillable; post_only ⇒ rejected pre-escrow if the limit would cross
    # (forces pure maker, pairs with the P2.2 rebate). DEFERRED: stop/stop-limit, iceberg.
    tif: Mapped[str] = mapped_column(String(4), nullable=False, default="gtc", server_default="gtc")  # gtc|ioc|fok
    post_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.text("false"))
    # §#86 P5.1 (migration 0105): stop/stop-limit triggers + iceberg display. Additive, opt-in
    # per order; NULL ⇒ today's behavior exactly (no flag), Δ-NEUTRAL. stop_price set ⇒ the order
    # rests 'armed' (escrowed up front like a normal order, but NOT matched) until `last` crosses
    # stop_price → trigger_armed_stops (settlement worker) activates it (status→open + _match) as a
    # market (price NULL) or limit (price set = stop-limit) order. display_qty = iceberg visible
    # slice (book-depth display only).
    stop_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    display_qty: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ttl_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_exchange_orders_book", "listing_id", "side", "status", "price", "created_at"),
        Index("ix_exchange_orders_agent", "agent_did", "status"),
    )

    def __repr__(self):
        return f"<ExchangeOrder({self.side} {self.remaining}/{self.qty} @ {self.price} {self.status})>"


class ExchangeTrade(Base):
    """Immutable tape row. seq (BIGSERIAL) is the venue's total order of events —
    candles, snapshots and dividend snapshots all key on it. Money settles
    asynchronously: settle_status drives the settlement worker; escrow holds the
    notional until then (I-X3)."""
    __tablename__ = "exchange_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    seq: Mapped[int] = mapped_column(BigInteger, sa.Identity(), nullable=False, unique=True)
    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), nullable=False)
    buy_order_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_orders.id"), nullable=False)
    sell_order_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_orders.id"), nullable=False)
    buyer_did: Mapped[str] = mapped_column(String(120), nullable=False)
    seller_did: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    qty: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notional: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    fee_total: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    fee_org: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    fee_proto: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    # §2026-06-22 P2.2 (migration 0102): the maker rebate is carved OUT of fee_proto at
    # match (fee_proto = fee_total − fee_org − fee_maker_rebate, clamped ≥0) → the four
    # settlement legs pay+fee_proto+fee_org+fee_maker_rebate still sum to notional (Δ=0).
    # maker_did = the resting order's agent_did (∈ {buyer_did, seller_did}); settlement
    # pays it the rebate (or parks on the gateway if foreign). Both default to the no-op
    # value so pre-0102 rows / flag-off trades behave exactly as today.
    fee_maker_rebate: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"), server_default="0")
    maker_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    settle_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_settlement")
    settle_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settle_tx_refs: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    settled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_exchange_trades_listing_seq", "listing_id", "seq"),
    )

    def __repr__(self):
        return f"<ExchangeTrade(#{self.seq} {self.qty}@{self.price} {self.settle_status})>"


class ExchangeDividend(Base):
    """Declared dividend: per_share × holdings at snapshot_seq. Funded as ONE
    pot leg (treasury → escrow), then paid as per-holder legs from escrow —
    every leg exref-idempotent."""
    __tablename__ = "exchange_dividends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    per_share: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    snapshot_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    pot_funded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="declared")  # declared|paying|paid|failed
    declared_by_dev: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("listing_id", "epoch", name="uq_exchange_dividends_listing_epoch"),
    )


class ExchangeDividendLeg(Base):
    """One holder's payout within a dividend (escrow → holder)."""
    __tablename__ = "exchange_dividend_legs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dividend_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_dividends.id"), nullable=False)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    qty_at_snapshot: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")  # pending|paid|failed
    paid_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("dividend_id", "agent_did", name="uq_exchange_dividend_legs"),
    )


class ExchangeIpoPurchase(Base):
    """Fixed-price primary sale: funding (deposit leg) → allocated (shares
    granted from float) → settled (proceeds leg to org treasury) | refunded."""
    __tablename__ = "exchange_ipo_purchases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), nullable=False)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    qty: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="funding")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ExchangeParticipant(Base):
    """D25 compliance registry — 'no anonymous ghosts': every trading DID has a
    row carrying its owner-developer identity. Local agents auto-verify from the
    local developer record (verification_source='local'); foreign agents verify
    via a home-registry-signed DevCard (§9 Passport; payload+sig cached in kyc)."""
    __tablename__ = "exchange_participants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    home_registry: Mapped[str] = mapped_column(String(128), nullable=False, default="local")
    trust_domain: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    owner_dev_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    owner_dev_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    owner_dev_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verification_source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")  # local|dev_card
    # §2026-06-22 P2.2 (migration 0102): set true when this DID holds a designated
    # market-maker seat on at least one listing (see ExchangeMarketMaker). Surface/UX
    # flag — rebate eligibility is keyed per-listing on ExchangeMarketMaker, not here.
    market_maker: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    compliance_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")  # verified|pending|blocked
    kyc: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    verified_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ExchangeParticipant({self.agent_did[:24]}… {self.compliance_status} via {self.verification_source})>"


class ExchangeGatewayCredit(Base):
    """Passport repatriation sub-ledger (§V0064 P2, migration 0091): money that
    landed on the venue GATEWAY for a FOREIGN DID (dividend / refund), drained
    home by settlement batch I via /teg/send. ref = writer idempotency key."""
    __tablename__ = "exchange_gateway_credits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    did: Mapped[str] = mapped_column(String(120), nullable=False)
    home_registry: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="BVT")
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    ref: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rearm_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # autonomous-recon re-arm generations (0097); abandoned at GATEWAY_RECON_MAX_REARM
    tx_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ExchangeFlag(Base):
    """Venue-level kill switches (key='global_halt' seeded by migration 0088)."""
    __tablename__ = "exchange_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # §2026-06-18 widened 255→Text: demand_director JSON (all network tickers) overflowed varchar(255)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TreasuryMMConfig(Base):
    """§P2.1 Per-listing treasury market-maker config (migration 0098). The leader-
    elected treasury_market_maker worker reads enabled rows each cycle and quotes a
    two-sided treasury bid/ask (buyback + treasury-sell) within the band, inventory-
    floored. Δ-safe (rides place_order). Default OFF; set via the MM config endpoint."""
    __tablename__ = "treasury_mm_config"

    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    spread_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=200)      # ±2% quotes
    quote_qty: Mapped[int] = mapped_column(BigInteger, nullable=False, default=100)
    reserve_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # never sell treasury below
    cash_floor: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))  # never bid below
    ref_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="last")    # last|fair
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ExchangeMarketMaker(Base):
    """§P2.2 Designated external market-maker seat (migration 0102). Unlike TreasuryMMConfig
    (the org quoting its OWN book), this grants an INDEPENDENT third-party agent the right to
    be compensated (the maker rebate) for committing two-sided liquidity. Keyed per
    (listing, agent_did) — multiple external MMs can register on one listing. When the
    listing's rebate_requires_registration is true (default), ONLY an 'active' row here
    earns ExchangeListing.maker_rebate_bps. obligation params (min_uptime_pct / max_spread_bps)
    are a surveillance/SLA surface (P4.1 monitor flags breaches; no auto-enforcement v1)."""
    __tablename__ = "exchange_market_makers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), nullable=False)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|suspended|revoked
    min_uptime_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_spread_bps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    granted_by_dev: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("listing_id", "agent_did", name="uq_exchange_market_makers_listing_agent"),
        Index("ix_exchange_market_makers_listing", "listing_id", "status"),
    )

    def __repr__(self):
        return f"<ExchangeMarketMaker({self.agent_did[:24]}… {self.status} on {self.listing_id[:8]})>"


class ExchangeProposal(Base):
    """§P3.1 Share-weighted shareholder proposal on a listing (migration 0099). Voting
    power = shares held at proposal creation, frozen per-holder in ExchangeProposalHolder
    (treasury excluded, like dividends). Parallel to registry governance (which is
    veToken-weighted) — this is the exchange-domain equity vote. Δ-irrelevant (no money)."""
    __tablename__ = "exchange_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_listings.id"), nullable=False)
    proposer_did: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="voting")  # voting|passed|failed|applied
    # §2026-06-22 P1.4 governance-gated corporate actions. type="advisory" (default, no on-chain
    # effect) | "dilution" (on pass → org-admin executes a share mint → status="applied").
    # action_params carries the action, e.g. {"new_shares": N, "destination": "treasury"}.
    # Δ-irrelevant (shares are the registry ledger, NOT TEG money).
    proposal_type: Mapped[str] = mapped_column(String(16), nullable=False, default="advisory")
    action_params: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    quorum_pct: Mapped[float] = mapped_column(Float, nullable=False, default=20.0)
    pass_pct: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    snapshot_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    enfranchised_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # Σ eligible weight (excl treasury)
    end_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExchangeProposalHolder(Base):
    """§P3.1 Frozen voting snapshot — one row per eligible holder at proposal creation
    (weight = qty_at_snapshot). Mirrors ExchangeDividendLeg's freeze pattern; there is no
    holdings-by-seq replay, so eligibility/weight must be materialized at creation."""
    __tablename__ = "exchange_proposal_holders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_proposals.id"), nullable=False)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[int] = mapped_column(BigInteger, nullable=False)  # shares held at snapshot
    __table_args__ = (sa.UniqueConstraint("proposal_id", "agent_did", name="uq_eph_proposal_agent"),)


class DevicePushRegistration(Base):
    """POCKET FRAME (f-mobile, 2026-07-07): a developer's registered push device.
    rail='ntfy' → target is a topic on the self-hosted ntfy server (live);
    rail='fcm'/'apns' → target is a platform token (adapters stubbed until creds).
    Δ-irrelevant — read-side notification plumbing only. Migration 0112."""
    __tablename__ = "device_push_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="android")
    rail: Mapped[str] = mapped_column(String(16), nullable=False, default="ntfy")
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.true())
    prefs: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    # COCKPIT CARD (mig 0132): phone enclave signing key enrolled on the existing device row.
    # The fingerprint must not merely tap approve — it must UNLOCK A KEY that signs (P-256,
    # Secure Enclave/StrongBox, biometric-gated). key_revoked_at set → key dead, TOTP fallback.
    pubkey_jwk: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    key_alg: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)          # ES256
    attestation: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)       # platform key attestation blob
    key_enrolled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    key_revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # WEB PUSH (mig 0133): rail='webpush' → target is the browser-issued endpoint URL and these
    # are the RFC 8291 subscription keys. The Protocol PWA notifies you itself, no second app.
    p256dh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # WEBAUTHN (mig 0134): the confirmation signer. Unlike a WebCrypto key, the OS will not
    # produce an assertion without user verification, and says so in the signed flags.
    webauthn_credential_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    webauthn_public_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # COSE, b64url
    webauthn_sign_count: Mapped[Optional[int]] = mapped_column(sa.BigInteger, nullable=True)
    webauthn_enrolled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (sa.UniqueConstraint("developer_id", "rail", "target", name="uq_device_push_dev_rail_target"),)


class PhonePoolInstance(Base):
    """PHONE FABRIC (2026-07-07): a leasable phone instance. backend='mock' = synthetic
    (infinite); 'redroid' = a real Android-in-Docker container (data plane, Commander-gated).
    Δ-irrelevant. Migration 0113."""
    __tablename__ = "phone_pool_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")
    handle: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    leased_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (sa.UniqueConstraint("backend", "handle", name="uq_phone_pool_backend_handle"),)


class PhoneSession(Base):
    """PHONE FABRIC: one agent phone session, bound to the L4 capability token that authorized
    it. Metering rides the token's budget (agent_capability_tokens.budget_spent) — the
    budget_spent here is an audit MIRROR, not a money row. Δ-irrelevant. Migration 0113."""
    __tablename__ = "phone_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # pfs_<hex>
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    capability_token_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")
    instance_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    allowed_apps: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    max_actions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actions_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_screenshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    budget_currency: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    budget_spent: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False, default=0)
    current_app: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    current_screen: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class PhoneSessionAction(Base):
    """PHONE FABRIC: append-only per-action audit for a session (every tap/type/observe).
    Δ-irrelevant. Migration 0113."""
    __tablename__ = "phone_session_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(40), ForeignKey("phone_sessions.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    cost: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GuildWorkOrder(Base):
    """THE GUILD (2026-07-07): a posted task in the agent labor market. Money is NEVER stored here —
    the bounty is escrowed on the TEG (`@guild_escrow` mover, `escrow_ref` tag) via /teg/transfer, so
    every leg is a zero-sum transfer and Δ is untouched. This is the order book. Migration 0114."""
    __tablename__ = "guild_work_orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # gwo_<hex>
    poster_did: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    spec: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bounty: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    required_skills: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    min_reputation: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    deadline: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    awarded_bid_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    worker_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    # V0650 (f) (mig 0200): the agent the poster meant the task for. A flag, never a gate: anyone may bid, and a bid
    # from another agent is marked not_intended_worker (derived at read time; nothing is stored on the bid).
    intended_worker_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    escrow_ref: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    deliverable: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    dispute_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # FIRMS (mig 0115): payee ≠ submitter when a firm wins — payout goes to the org's AGORA
    # treasury_agent_did. NULL payee_did ⇒ pay worker_did (individual).
    payee_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    payee_org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # STAKED WORK (mig 0116): optional collateral the poster requires bidders to lock.
    stake_required: Mapped[Optional[float]] = mapped_column(Numeric(30, 10), nullable=True)
    # CROSS-REGISTRY (mig 0117): the awarded worker's home peer registry. NULL ⇒ local worker.
    worker_home_registry: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    fee_charged: Mapped[Optional[float]] = mapped_column(Numeric(30, 10), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    awarded_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class GuildBid(Base):
    """THE GUILD: a bid on an open work order. Δ-irrelevant. Migration 0114."""
    __tablename__ = "guild_bids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(40), ForeignKey("guild_work_orders.id", ondelete="CASCADE"), nullable=False)
    bidder_did: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False)
    eta_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pitch: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reputation: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    # FIRMS (mig 0115): a bid placed on behalf of an org (member agent bids for its firm). NULL ⇒ individual.
    on_behalf_of_org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # STAKED WORK (mig 0116): collateral the bidder locked for this bid (escrowed to treasury). status ∈ held|released|slashed.
    stake_amount: Mapped[Optional[float]] = mapped_column(Numeric(30, 10), nullable=True)
    stake_escrow_ref: Mapped[Optional[str]] = mapped_column(String(90), nullable=True)
    stake_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # CROSS-REGISTRY (mig 0117): the bidder's home peer registry when bid via federation. NULL ⇒ local.
    home_registry_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (sa.UniqueConstraint("order_id", "bidder_did", name="uq_guild_bid_once"),)


class GuildOrderEvent(Base):
    """THE GUILD: append-only lifecycle audit for a work order. Δ-irrelevant. Migration 0114."""
    __tablename__ = "guild_order_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(40), ForeignKey("guild_work_orders.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExchangeProposalVote(Base):
    """§P3.1 One vote per shareholder per proposal (weight copied from the frozen snapshot,
    NOT current holdings — buying shares mid-vote can't increase power)."""
    __tablename__ = "exchange_proposal_votes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(36), sa.ForeignKey("exchange_proposals.id"), nullable=False)
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    vote: Mapped[bool] = mapped_column(Boolean, nullable=False)  # True = for
    weight: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # §2026-06-22 cross-frame voting: the voter's home-frame SPIFFE/peer id when the vote was
    # relayed in from a peer registry (NULL = local same-registry voter). Mirrors
    # FederationVote.voter_registry_id. Δ-irrelevant (governance moves no money).
    voter_registry_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (sa.UniqueConstraint("proposal_id", "agent_did", name="uq_epv_proposal_agent"),)


class Contract(Base):
    """THE CONTRACT SPINE (2026-07-25): a typed, escrowed-at-agreed, milestoned agreement — the
    settlement object every origination surface mints into (direct / discovery / guild / template).
    Money NEVER lives here — escrowed on the TEG treasury via the shared rail
    (`services/escrow.py`, `ctrref:{id}:{leg}`), so every leg is zero-sum and Δ is untouched.
    `total_amount == 0` = agreement-only (MOU/NDA/framework form): full lifecycle, no escrow legs.
    Migration 0129. Lifecycle: draft→offered→agreed→in_progress→completed | disputed | cancelled | expired."""
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # ctr_<hex> (ctr_l… = migrated RUC)
    legacy_ruc_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True)
    contract_type: Mapped[str] = mapped_column(String(32), nullable=False, default="work_order")
    origin_surface: Mapped[str] = mapped_column(String(24), nullable=False, default="direct")
    origin_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)   # D6-815 (0195): a DID, as wide as client_did
    client_did: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    provider_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    payee_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    payee_org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    terms: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False)
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)   # snapshot (I-C5)
    fee_charged: Mapped[Optional[float]] = mapped_column(Numeric(30, 10), nullable=True)
    escrow_ref: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    template_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    template_royalty_bps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    template_price_paid: Mapped[Optional[float]] = mapped_column(Numeric(30, 10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    deadline: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dispute_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    counterparty_home_registry: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    agreed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ContractMilestone(Base):
    """Staged release: Σ milestone.amount == contract.total_amount (I-C6, enforced in code).
    0-amount milestone = sign-off gate (no legs). Migration 0129."""
    __tablename__ = "contract_milestones"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # ctm_<hex>
    contract_id: Mapped[str] = mapped_column(String(40), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    terms: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    deliverable: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    due_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (sa.UniqueConstraint("contract_id", "seq", name="uq_contract_milestone_seq"),)


class ContractEvent(Base):
    """Append-only lifecycle audit for a contract (guild_order_events twin). Δ-irrelevant. Mig 0129."""
    __tablename__ = "contract_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(String(40), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ContractTemplate(Base):
    """P4: a frozen, versioned agreement that MINTS contracts. Free | purchase | royalty pricing.
    `usage_count` increments at AGREED (real agreements, not clicks). Migration 0131."""
    __tablename__ = "contract_templates"

    id: Mapped[str] = mapped_column(String(44), primary_key=True)  # ctpl_<hex>
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    owner_agent_did: Mapped[str] = mapped_column(String(120), nullable=False)
    source_org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    maintained_by_org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    contract_type: Mapped[str] = mapped_column(String(32), nullable=False, default="work_order")
    visibility: Mapped[str] = mapped_column(String(12), nullable=False, default="private")
    pricing_model: Mapped[str] = mapped_column(String(12), nullable=False, default="free")
    price: Mapped[Optional[float]] = mapped_column(Numeric(30, 10), nullable=True)
    price_currency: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    royalty_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    forked_from_template_id: Mapped[Optional[str]] = mapped_column(String(44), nullable=True)
    current_version_id: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (sa.UniqueConstraint("owner_agent_did", "slug", name="uq_ctpl_owner_slug"),)


class ContractTemplateVersion(Base):
    """Immutable once `published_at` is set (I-C7). `terms_schema` (JSON Schema) makes it a FORM —
    the institutional capability. `content_hash` = sha256 over canonical (terms, terms_schema,
    milestones) — the ERP interchange integrity check. Migration 0131."""
    __tablename__ = "contract_template_versions"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # ctpv_<hex>
    template_id: Mapped[str] = mapped_column(String(44), ForeignKey("contract_templates.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title_tpl: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    terms: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    terms_schema: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    milestones: Mapped[Optional[list]] = mapped_column(PG_JSONB, nullable=True)
    suggested_amount: Mapped[Optional[float]] = mapped_column(Numeric(30, 10), nullable=True)
    suggested_currency: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    suggested_deadline_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    changelog: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (sa.UniqueConstraint("template_id", "version", name="uq_ctpv_template_version"),)


class ContractTemplatePurchase(Base):
    """Purchase receipt (queryable twin of the exactly-once TEG rail key ctpl:{tpl}:{buyer}).
    One purchase per buyer per template; re-instantiate after purchase = free. Migration 0131."""
    __tablename__ = "contract_template_purchases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(44), ForeignKey("contract_templates.id", ondelete="CASCADE"), nullable=False)
    buyer_did: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (sa.UniqueConstraint("template_id", "buyer_did", name="uq_ctpl_purchase_once"),)


class LiabilityMandate(Base):
    """COCKPIT CARD (L1, 2026-07-25): a liable hybrid identity — ONE human developer bound to
    ONE agent for a declared scope. The human carries the liability; authority is re-derived
    every request as agent_own ∪ (delegated(dev) ∩ dev_authority_now ∩ scope) ∩ caveats ∩ limits
    (issuer-current clamp, same shape as IRONKEY L4 resolve_capability). Deny-only, Δ-irrelevant.
    Migration 0132."""
    __tablename__ = "liability_mandates"

    id: Mapped[str] = mapped_column(String(44), primary_key=True)                     # lm_<hex>
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(8), nullable=False, default="T1")
    scope: Mapped[list] = mapped_column(PG_JSONB, nullable=False)
    limits: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="signed")  # signed|revoked|expired
    presence_method: Mapped[str] = mapped_column(String(16), nullable=False)           # totp|enclave
    authority_snapshot: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    registry_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    issued_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class LiabilityEvidence(Base):
    """COCKPIT CARD evidence chain: per-mandate append-only hash chain
    (chain_hash = sha256(prev_hash || digest), UNIQUE(mandate_id, seq)). Every issue / challenge /
    consume / deny / revoke appends; recompute mismatch = tamper. authority_snapshot captures the
    flags/roles live AT THAT EVENT — the intersection is auditable after the fact. Migration 0132."""
    __tablename__ = "liability_evidence"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    mandate_id: Mapped[str] = mapped_column(
        String(44), ForeignKey("liability_mandates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    authority_snapshot: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    presence: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (sa.UniqueConstraint("mandate_id", "seq", name="uq_liab_evidence_seq"),)


class LiabilityChallenge(Base):
    """COCKPIT CARD presence challenge (banking-app confirm): server renders canonical action
    facts, human approves by signing challenge_hash with the phone's biometric-gated enclave key
    (ES256 vs device_push_registrations.pubkey_jwk) or TOTP fallback. Single-use, 120s TTL,
    expiry is a denial; the achieved method is recorded, never silently downgraded. Migration 0132."""
    __tablename__ = "liability_challenges"

    id: Mapped[str] = mapped_column(String(44), primary_key=True)                     # lch_<hex>
    # §DISCREFINE (mig 0154): NULL for a step-up confirm with no mandate behind it
    # (agent credential reset). Mandate challenges are unchanged.
    mandate_id: Mapped[Optional[str]] = mapped_column(
        String(44), ForeignKey("liability_mandates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    action_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    facts: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    # §SHOWN (mig 0166) — SERVER time at which a surface acknowledged PRESENTING this
    # challenge. The delivery truth: the WS cue and the push are both best-effort, and
    # a send is not an arrival (R6). ARRIVE latency is measured to this, never to the
    # moment we tried to tell someone.
    delivery_acked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    nonce: Mapped[str] = mapped_column(String(32), nullable=False)
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending|approved|denied|expired|consumed
    method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    device_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentSpendApproval(Base):
    """B3 (RBAC plan) — one parked spend awaiting the owning human's step-up decision.

    Created by the spend gate when an amount crosses the agent's ``require_approval_above``
    threshold (previously a dead-end deny). Lifecycle: pending → approved|denied|expired,
    and approved → consumed by exactly ONE matching retry (atomic single-statement consume).
    Expiry is lazy — every reader filters on ``expires_at`` — so no sweeper is needed
    (same shape as B2's time-boxed roles). Rows are written through an ISOLATED session so
    the 403 the request still returns cannot roll them away. Migration 0147."""
    __tablename__ = "agent_spend_approvals"

    id: Mapped[str] = mapped_column(String(44), primary_key=True)                      # spa_<hex>
    agent_did: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 18), nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    counterparty_did: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending|approved|denied|expired|consumed
    reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_developer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    consumed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RegulatoryAuthorization(Base):
    """REGAUTH (SPEC 2026-08-15) — one attested regulatory approval on file.

    The operator's jurisdiction profile can declare that a lifecycle act (AGORA
    listing approval, IPO opening, the fiat lane) requires state approval; the gate
    then parks that act until a row here covers it. The row is an ATTESTATION with
    the operator's liability behind it (reference id public on the signed card),
    never a verified state document. subject_ref NULL = registry-wide scope.
    Liveness is re-derived at use: status='active' AND valid_from <= now < valid_until
    (NULL valid_until = open-ended). Revocation is status-only; renewals are new
    rows. Migration 0150."""
    __tablename__ = "regulatory_authorizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    authority: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(120), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False)
    valid_from: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_hash: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    evidence_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contract_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active", server_default="active")
    recorded_by_dev_id: Mapped[int] = mapped_column(Integer, ForeignKey("developers.id"), nullable=False)
    presence_method: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class FlareShopPurchase(Base):
    """§FLARESHOP (2026-08-16) — one cosmetic-flare purchase paid in the FRAME's
    own currency (AVT / JDAY / BVT), not euros.

    Why a second purchase table instead of reusing FiatPurchase: FiatPurchase is
    the euro ledger — its amount_eur feeds the cumulative Shadow Chancellor
    evaluation, the Founders Wall counts and the Stripe reconciliation surfaces.
    A local-currency purchase must be invisible to all three, so it gets its own
    row and never touches that lane.

    Lifecycle is pending -> completed|failed, written in that order: the row is
    created BEFORE the money moves so a crash between the debit and the grant is
    re-drivable from the row plus the durable Idempotency-Key
    (`flareshop-{id}`), which the TEG claims inside the money transaction. A
    purchase is therefore never recorded as paid when it was not, and a replay
    of the same row moves nothing.

    Δ-irrelevant by construction: the money leg is an in-circulation transfer
    (buyer agent -> system treasury) on the existing fee-free admin rail; the
    grant itself only writes cosmetic columns. Migration 0151."""
    __tablename__ = "flare_shop_purchases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    developer_id: Mapped[int] = mapped_column(Integer, ForeignKey("developers.id"), nullable=False, index=True)
    buyer_agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # The agent that WEARS the flare. Defaults to the buyer, may be any agent
    # the same developer owns (the flare is movable afterwards anyway).
    target_agent_did: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    teg_tx_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending", server_default="pending")
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DeveloperPref(Base):
    """§POCKETBRIDGE3 (mig 0152) — per-developer key/value prefs, JSONB.

    One row per (developer, key). Keys are ALLOWLISTED at the router
    (pocket.watchlist / pocket.price_alerts / pocket.assistant) with a size
    cap — this is a small synced-preferences rail, not a general store. The
    price-alert watcher scans `key = 'pocket.price_alerts'` across developers
    each cycle, hence the key index. Δ-irrelevant: nothing here is money."""
    __tablename__ = "developer_prefs"

    developer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# §OURSTATE-1 (mig 0155_chat_core, 2026-08-24) — the conversation primitive.
#
# Law 1 of the program: chat has NO money code. None of these tables carries a
# money column; every economic act in a thread is a typed CARD (jsonb envelope,
# closed vocabulary validated in services/chat_service.py) that doors into an
# EXISTING rail and carries ledger refs the CLIENT re-verifies. Δ-irrelevant.
#
# Ordering: per-conversation total order via Conversation.last_seq, assigned by
# an atomic UPDATE .. RETURNING (single writer per thread by construction).
# Unread is ALWAYS computed (last_seq - last_read_seq), never a counter column.
# ---------------------------------------------------------------------------

class Conversation(Base):
    """One thread. `dm_pair_key` is the one-thread-per-pair dedup (canonical
    unordered principal pair, kind-prefixed); NULL for non-pair kinds.
    `service_inflight_at` = the one-service-call-in-flight flag (a timestamp so
    a crashed worker's stale flag ages out). host_registry/remote_ref are
    OURSTATE-3 federation placeholders, unused in CORE."""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    created_by_ptype: Mapped[str] = mapped_column(String(12), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_message_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_preview: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    dm_pair_key: Mapped[Optional[str]] = mapped_column(String(600), nullable=True, unique=True)
    service_inflight_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    host_registry: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # §OURSTATE-2 (mig 0156) — rooms: 'open' | 'announce' (announce = only org
    # owner/admin post), the /topic line, and the un-burnable Room Genesis
    # ({stated, updated_by, updated_at, history[]} — edits keep history).
    mode: Mapped[str] = mapped_column(String(12), nullable=False, default="open", server_default="open")
    topic: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    genesis: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)

    # §OURSTATE-6 — the disappearing timer (mig 0163). NULL means keep, which
    # is the pre-existing behaviour, so an untouched thread is unchanged.
    # ⚠ The migration alone was not enough: the setter wrote through raw SQL and
    # answered 200 while every thread READ 500'd on `conv.retention_hours` —
    # a write that succeeds beside a read that crashes looks like a working
    # feature until someone opens the thread. Column and model land together.
    retention_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retention_set_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    retention_set_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    # §OURSTATE-7 D (mig 0164) — the support ticket this thread MIRRORS. Set
    # only on kind='support'. The ticket stays the authority: chat displays it,
    # the support rail decides it.
    support_ticket_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConversationParticipant(Base):
    """A typed principal (developer | agent) in a thread. `state` is the
    Requests-folder machine (active|pending|left); `hidden_before_seq` is what
    Burn-for-me writes; `last_read_seq` is monotonic and NEVER shown to the
    counterparty (law 6: no read receipts)."""
    __tablename__ = "conversation_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    ptype: Mapped[str] = mapped_column(String(12), nullable=False)
    developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="CASCADE"), nullable=True)
    agent_did: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # §OURSTATE-3b: a REMOTE principal — `handle@https://their.registry`. An
    # address this registry does not own and must not pretend to; deliberately
    # not a foreign key, because only their home registry can vouch for them.
    remote_key: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(12), nullable=False, default="member", server_default="member")
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="active", server_default="active")
    last_read_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    hidden_before_seq: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    # §OURSTATE-2 (mig 0156) — the room-scoped /mute flag. Room state ONLY:
    # org membership truth stays in organization_members.
    can_post: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.true())
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("conversation_id", "ptype", "developer_id", "agent_did",
                         name="uq_conv_part_principal"),
    )


class ChatMessage(Base):
    """One message. UNIQUE(conversation_id, seq) is the order;
    UNIQUE(conversation, sender, client_ref) is what makes the offline queue
    and every retry idempotent — a resend can never double-post."""
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_ptype: Mapped[str] = mapped_column(String(12), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    card: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    reply_to: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    client_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    # §OURSTATE-3b mirror columns. On a mirrored message the HOST's seq is the
    # truth and the local seq is only this database's ordering; the unique
    # (conversation, remote_seq) index is the idempotent receive.
    remote_seq: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    origin_registry: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # V0650 (h) (mig 0201): the principals the body @mentions, [{key, ptype, developer_id, agent_did, token}], resolved
    # at insert against the thread's participants (services/chat_mentions.py); NULL when it names nobody.
    mentions: Mapped[Optional[list]] = mapped_column(PG_JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    edited_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_chat_msg_conv_seq"),
        UniqueConstraint("conversation_id", "sender_ptype", "sender_id", "client_ref",
                         name="uq_chat_msg_client_ref"),
        Index("ix_chat_msg_mentioned", "conversation_id", "seq", postgresql_where=sa.text("mentions IS NOT NULL")),
    )


class ChatFederationOutbox(Base):
    """§OURSTATE-3b (mig 0158) — the HOST's delivery queue for a federated
    thread. One row per (conversation, seq, peer): the unique constraint is the
    no-double-delivery guarantee on this side, and the receiver's unique
    (conversation, remote_seq) is the other half — at-least-once on the wire,
    exactly-once in the log. Δ-irrelevant."""
    __tablename__ = "chat_federation_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    peer_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", "peer_base_url", name="uq_chat_fed_outbox_target"),
        Index("ix_chat_fed_outbox_due", "delivered_at", "next_attempt_at"),
    )


class ChatApproval(Base):
    """V0650 (l) (mig 0198): one approval request an agent posted in its organization's room, and its decision.

    The record, not the chat log, is the authority: a room's disappearing timer deletes messages, and the decision
    with its proof (who, when, how, the registry's signed statement) must outlive the cards that show it. `status` is
    pending|approved|denied|expired; a pending row past `expires_at` reads as expired everywhere and can never be
    approved. Who may decide is re-derived on every decision (the org owner or an active member with can_approve);
    agents never decide. Nothing here moves money."""
    __tablename__ = "chat_approvals"

    id: Mapped[str] = mapped_column(String(44), primary_key=True)                     # apr_<hex>
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requester_agent_did: Mapped[str] = mapped_column(String(255), nullable=False)
    client_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    request_message_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unlocks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    artifact_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    artifact_label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    production_impact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    facts: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    facts_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True)
    decided_by_role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    decision_via: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)
    presence_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    presence_challenge_id: Mapped[Optional[str]] = mapped_column(String(44), nullable=True)
    decision_statement: Mapped[Optional[dict]] = mapped_column(PG_JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("requester_agent_did", "client_ref", name="uq_chat_approval_client_ref"),
    )


class ChatBlock(Base):
    """User-level block (the census found NO block primitive existed anywhere).
    Enforced at conversation-create AND message-send, both directions, silently
    — the blocked party never learns."""
    __tablename__ = "chat_blocks"

    blocker_ptype: Mapped[str] = mapped_column(String(12), primary_key=True)
    blocker_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    blocked_ptype: Mapped[str] = mapped_column(String(12), primary_key=True)
    blocked_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# §CHATDESK C4 (mig 0165) — SUPPORT REVIEW WITH CONSENT.
# One row = the desk may READ one conversation, for one ticket, while the
# ticket lives. Revoke-never-delete (audit survives); the read side ALSO
# validates the ticket status live, so a missed revocation cannot keep a
# closed ticket readable — fail closed, both halves.
# ---------------------------------------------------------------------------
class SupportReviewGrant(Base):
    __tablename__ = "support_review_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    granted_by_dev: Mapped[int] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, server_default="read")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


# =============================================================================
# === §FRAMEFORM — public "I want a frame" intake (mig 0172) ==================
# =============================================================================

class FrameRequest(Base):
    """One submission of the public frame-request form.

    Mirrors the questions the `frame_request_intake` email asks, so a person can
    answer either way and the admin reads one shape. The scalar columns are the
    ones the admin list filters on and the ones that feed `FrameProvisionRequest`
    directly; `answers` holds the feature switches and the optional registry-card
    prefill, because that questionnaire changes and a migration per new question
    is how an intake form rots. See the migration docstring for the full why.

    Status flow: pending -> reviewed -> provisioned, or -> rejected.
    Nothing here provisions anything by itself; a human still decides.
    """
    __tablename__ = "frame_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True)

    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    organization: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # The seven from the intake block. All nullable on purpose: a half-filled
    # form from a stranger should land and be answerable, not 422 into the void.
    frame_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    trust_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ticker: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    currency_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    federation_choice: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)

    use_case: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # {"features": {...only the overrides...}, "card": {...}, "treasury": {...}}
    answers: Mapped[dict] = mapped_column(
        PG_JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    source_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provisioned_frame: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # §HELLOFRAME (mig 0180): the frame kit's download window for an approved self-hosted request (routers/frame_kit.py).
    kit_approved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    kit_download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    kit_last_download_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False)


class EsEmitOutbox(Base):
    """§SOVKIT K1 / V0372 (2026-09-14): the registry's durable ledger-emit outbox (migration 0178).

    A row is the event as the emitter would have POSTed it, written when the store could not be reached after the
    three fast attempts (connection errors, timeouts, 429, 5xx; never a 4xx). `background_tasks/es_emit_outbox_drainer`
    re-emits due rows under leadership, closes them with `delivered_at`, and parks one past its attempt budget with
    `dead_at` (logged with type, aggregate and key; never deleted). `idempotency_key` is unique: the store dedups on it.
    """
    __tablename__ = "es_emit_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(512), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Agent")
    payload: Mapped[dict] = mapped_column(PG_JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    delivered_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class GenesisGrantOwed(Base):
    """§LEDGERGATE (V0598, 2026-10-11): a first agent's genesis grant the TEG could not pay (migration 0188).

    Written by onboarding's `mint_genesis_grant` when the funding call fails (the ledger gate's refusal, or any TEG
    failure): the grant is owed, not lost. `background_tasks/genesis_grant_retry` pays due rows under leadership with the
    creation's own idempotency key (`genesis-{agent_did}`), closes a row with `granted_at`, and parks one past its attempt
    budget with `dead_at` (kept and logged; never deleted). One row per agent at most (the DID is the key).
    """
    __tablename__ = "genesis_grants_owed"

    agent_did: Mapped[str] = mapped_column(String(255), primary_key=True)
    developer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=38, scale=18), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    granted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    funding_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dead_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ForfeitureOwed(Base):
    """§LEDGERGATE (V0599, 2026-10-11): an account deletion's forfeiture that moved no money (migration 0190).

    Written by routers/account_deletion.anonymize_developer IN THE ANONYMIZATION'S OWN TRANSACTION when an agent's
    drain to the treasury fails (the ledger gate's refusal, a TEG error, the transport): the row exists if and only if
    the anonymization committed. `background_tasks/forfeiture_retry` drains due rows under leadership with the deletion's
    own key (`acctdel-forfeit-{deletion_id}-{agent_did}`, the row's id), closes a row with `done_at`, and parks one with
    `dead_at` when the TEG refuses it for good (a 4xx that is not the gate's: the balance is no longer there to take) or
    past its attempt budget: kept and logged, never deleted. Before it, nothing retried such a forfeiture and the balance
    stayed on the revoked agent for good (§MONEY-R39).
    """
    __tablename__ = "forfeitures_owed"

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False)
    developer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deletion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=38, scale=18), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    done_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyKept(Base):
    """§REPATLANE-8 (V0610, 2026-10-13): the durable copy of an Idempotency-Key's record (migration 0191).

    services/idempotency/cache.py keeps every answer a money endpoint may have paid under its key (V0606), in Redis,
    which evicts (allkeys-lru): a kept answer lost inside its 24 h window ran the payment again. services/idempotency/
    durable.py writes the same record here beside Redis: `state` 'claimed' while the request runs (`owner` is its claim's
    token), then 'answer' (a kept 2xx, `payload` the response) or 'error' (a kept error, `payload` its status, detail and
    Retry-After); the row is deleted when the key is given back. Read only when Redis has no record of the key. Rows past
    `expires_at` are dead; background_tasks/idempotency_kept_sweeper deletes them.
    """
    __tablename__ = "idempotency_kept"

    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    idem_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    owner: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class XRegRevokeOwed(Base):
    """D6-272 (2026-10-17): a cross-registry delegation revoke not yet delivered to the delegate's registry (migration
    0194_delivery_xreg_revoke).

    Written by DELETE /api/v1/agents/delegate-cross-registry/{credential_id} IN THE TRANSACTION OF THE ISSUER-SIDE RECORD
    (the `ironkey.xreg_delegation_revoke` audit row) when the route's own send did not land. That record stays the source
    of truth: the delegate's registry asks this one at use (services/xreg_issuer_authority) and is told the delegation is
    revoked whether or not this delivery landed. background_tasks/xreg_revoke_retry sends due rows again under
    leadership (services/xreg_revoke_delivery), closes a delivered one with `done_at`, and parks one with `dead_at` past
    its attempt budget, when the delegate's registry refuses the request for good, or once the delegation has expired
    (nothing is left to revoke there): kept, never deleted. One row per credential.
    """
    __tablename__ = "xreg_revokes_owed"

    credential_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    issuer_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    delegate_registry: Mapped[str] = mapped_column(Text, nullable=False)
    credential_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    done_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── §LEGALKIT (2026-09-20): one record per accepted legal document ─────────────────────────────
class LegalAcceptance(Base):
    """Terms § 10.3: "the version you accepted is recorded in your account". Written by every rail that
    asks for an acceptance (registration, the login re-consent, checkout, an operator application, a
    frame request, an MCP tool acting for a developer). `version` is always the version the SERVER served
    at that moment, never the client's word; the `developers.tos_accepted_*` columns remain the fast path
    and are written together with this row. Migration 0181."""
    __tablename__ = "legal_acceptances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    developer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    document: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    via: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    accepted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# §FEDLICENCE (0182_fed_licence_certs, 2026-09-28): network and operator licences as issuer-signed certificates.
# sessionlogs2026/DESIGN_2026-09-28_FEDERATION_LICENCE.md. The genesis signs frame licences, every frame signs its own
# operators' licences, and a hash shown on a card is checked against the issuer's signature, never taken on trust.
# ---------------------------------------------------------------------------

class FederationLicenceKey(Base):
    """This registry's licence-signing key (Ed25519). The private half is encrypted at rest with the registry-card
    keystore's scheme (REGISTRY_SIGNING_KEY_PASSPHRASE). One active row (retired_at NULL)."""
    __tablename__ = "federation_licence_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    public_jwk: Mapped[Dict[str, Any]] = mapped_column(PG_JSONB, nullable=False)
    private_pem_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retired_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class FederationLicenceCert(Base):
    """A licence certificate this registry issued (role `issued`), holds as its own network licence (`held`; an
    operator holds its parent frame's), holds as its operator licence (`held_operator`), or trusts as the network's
    genesis (`root`). One row per (hash, role): a genesis holds its own certificate in all three roles."""
    __tablename__ = "federation_licence_certs"
    __table_args__ = (UniqueConstraint("hash", "role", name="uq_federation_licence_certs_hash_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    lid: Mapped[str] = mapped_column(String(36), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    sub_trust_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    sub_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sub_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    iss_trust_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    network: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(40), nullable=False)
    issued_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active", default="active")
    state_reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    jws: Mapped[str] = mapped_column(Text, nullable=False)
    chain: Mapped[List[str]] = mapped_column(PG_JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    checked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("developers.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ═══ §MEMBERSHIP phase B (2026-10-02): the commons (mig 0183_commons_seasons) ═══════════════════════════════════════
# A registry's fee income funds a commons its members steer; it pays only for work (services/commons.py). These four
# mirror the migration column for column so a test database built by create_all is the database the code meets.

class CommonsSeason(Base):
    __tablename__ = "commons_seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    opens_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ends_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    fee_share_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=0, server_default="0")
    fee_collector_balance_at_open: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    seed: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=0, server_default="0")
    budget: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    recipient_cap_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    min_voters: Mapped[int] = mapped_column(Integer, nullable=False)
    rules: Mapped[Dict[str, Any]] = mapped_column(PG_JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    tally: Mapped[Optional[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cancelled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)

    __table_args__ = (
        sa.Index("uq_commons_one_live_season", sa.text("(true)"), unique=True,
                 postgresql_where=sa.text("status IN ('open', 'closed')")),
    )


class CommonsSubmission(Base):
    __tablename__ = "commons_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("commons_seasons.id"), nullable=False)
    submitter_did: Mapped[str] = mapped_column(String(255), nullable=False)
    developer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    evidence: Mapped[List[Dict[str, Any]]] = mapped_column(PG_JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="submitted", server_default="submitted")
    struck_reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    struck_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        sa.Index("ix_commons_submissions_season", "season_id", "status"),
        sa.Index("ix_commons_submissions_dev", "season_id", "developer_id"),
    )


class CommonsBallot(Base):
    __tablename__ = "commons_ballots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("commons_seasons.id"), nullable=False)
    voter_developer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    voter_did: Mapped[str] = mapped_column(String(255), nullable=False)
    allocations: Mapped[Dict[str, Any]] = mapped_column(PG_JSONB, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    presence_challenge_id: Mapped[Optional[str]] = mapped_column(String(44), nullable=True)
    cast_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("season_id", "voter_developer_id", name="uq_commons_ballot_member"),)


class CommonsAward(Base):
    __tablename__ = "commons_awards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("commons_seasons.id"), nullable=False)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("commons_submissions.id"), nullable=False)
    recipient_did: Mapped[str] = mapped_column(String(255), nullable=False)
    developer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    median_points: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    voters: Mapped[int] = mapped_column(Integer, nullable=False)
    share: Mapped[Decimal] = mapped_column(Numeric(20, 18), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    teg_transaction_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    funded_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    shortfall: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    attempted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    written_off_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    written_off_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    written_off_reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)

    __table_args__ = (
        UniqueConstraint("season_id", "submission_id", name="uq_commons_award_submission"),
        sa.Index("ix_commons_awards_recipient", "season_id", "recipient_did"),
    )
