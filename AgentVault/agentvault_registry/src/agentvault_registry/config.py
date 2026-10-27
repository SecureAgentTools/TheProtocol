import os
import sys # Import sys
# --- MODIFIED: Added List, Union, Optional, EmailStr ---
from typing import List, Union, Optional
from pydantic import AnyHttpUrl, EmailStr, field_validator # Added EmailStr
# --- END MODIFIED ---
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
from pathlib import Path # Import Path

# Determine the root directory of the registry component to find the .env file
# config.py is in src/agentvault_registry/
# We want the .env file in the parent directory (agentvault_registry/)
CONFIG_DIR = Path(__file__).resolve().parent
REGISTRY_ROOT_DIR = CONFIG_DIR.parent.parent # Go up two levels (src/ -> agentvault_registry/)
ENV_FILE_PATH = REGISTRY_ROOT_DIR / ".env"

# --- Add Logging to check if the .env file is found ---
logger_config = logging.getLogger(__name__ + ".config_loading") # Use a distinct logger name
logger_config.info(f"Attempting to load .env file from explicit path: {ENV_FILE_PATH}")
if ENV_FILE_PATH.is_file():
    logger_config.info(f".env file found at: {ENV_FILE_PATH}")
else:
    # §MONEY-R37 (2026-09-04): its ABSENCE is now the intended state. The image
    # used to bake agentvault_registry/.env into /app/.env, shipping live
    # rate-limit config to every party that runs this image; .dockerignore and a
    # `RUN rm -f` removed it. Settings come from the container environment.
    #
    # Kept as a message, demoted from WARNING: a warning that fires on the
    # CORRECT configuration, once per gunicorn worker (38 on registry-a), is how
    # people learn to ignore warnings.
    logger_config.info(
        f"no .env at {ENV_FILE_PATH} (expected since §MONEY-R37 — configuration "
        f"comes from the environment). CWD: {os.getcwd()}"
    )
# --- End Logging ---


class Settings(BaseSettings):
    """
    Application Settings loaded from environment variables and .env file.
    """
    
    def validate_production_config(self) -> None:
        """Validate configuration for production environment"""
        # Check if we're in production based on various indicators
        is_production = (
            "production" in os.environ.get("ENVIRONMENT", "").lower() or
            "prod" in self.DATABASE_URL.lower() or
            self.BASE_URL and "localhost" not in str(self.BASE_URL).lower()
        )
        
        if not is_production:
            return
        
        errors = []
        
        # Check for SQLite in production
        if "sqlite" in self.DATABASE_URL.lower():
            errors.append("SQLite database not allowed in production. Use PostgreSQL.")
        
        # Check for wildcard CORS in production
        if "*" in [str(origin) for origin in self.ALLOWED_ORIGINS]:
            errors.append("Wildcard CORS origins not allowed in production.")
        
        # Check for test/example values in secrets
        if any(test_word in self.API_KEY_SECRET.lower() for test_word in ["test", "example", "demo", "sample"]):
            errors.append("API_KEY_SECRET appears to contain a test value.")
        
        # Check if email is properly configured for production.
        # §FRAMEMAIL-4: "configured to send" now has TWO valid shapes. A node in
        # relay posture deliberately has no MAIL_* at all (PART 11b — it must not
        # hold a submission token), and sends by asking its parent. Without this
        # branch every relay node raises HERE, at import, and crash-loops — the
        # same trap as the §V0160 BASE_URL/ALLOWED_ORIGINS pairing.
        _has_smtp = all([self.MAIL_SERVER, self.MAIL_USERNAME, self.MAIL_FROM])
        _has_relay = all([self.MAIL_RELAY_PARENT_URL, self.MAIL_RELAY_LICENSE])
        if self.MAIL_DISABLED and (_has_smtp or _has_relay):
            errors.append(
                "MAIL_DISABLED=true contradicts a configured SMTP/relay: a frame declares ONE mail shape "
                "(SMTP, a parent relay, or none)."
            )
        elif not _has_smtp and not _has_relay and not self.MAIL_DISABLED:
            errors.append(
                "Email configuration incomplete for production: set either SMTP "
                "(MAIL_SERVER, MAIL_USERNAME, MAIL_FROM), a parent relay "
                "(MAIL_RELAY_PARENT_URL, MAIL_RELAY_LICENSE), or declare MAIL_DISABLED=true "
                "for a frame that sends no mail (verification off, invite-gated)."
            )
        
        # Check federation secret if central registry
        if self.IS_CENTRAL_REGISTRY and not self.FEDERATION_HEALTH_CHECK_SECRET:
            errors.append("FEDERATION_HEALTH_CHECK_SECRET required for central registry.")
        
        if errors:
            raise ValueError(f"Production configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
    # --- Core Settings ---
    # §pass53 PR-13: canonical brand. env override via .env still respected.
    PROJECT_NAME: str = "TheProtocol Registry"
    API_V1_STR: str = "/api/v1" # Base path for API endpoints
    BASE_URL: AnyHttpUrl = "http://localhost:8000" # Default for local dev, override in production .env
    PORT: int = 8000  # Default port, can be overridden via environment
    HOST: str = "0.0.0.0"  # Default host, can be overridden via environment


    # --- Database Settings ---
    DATABASE_URL: str

    # --- Security Settings ---
    API_KEY_SECRET: str # Used for JWT signing now
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 90 # Default JWT expiry — §pass73.3.5 bump 30→90 (commander-approved cluster-wide). Long-running orchestrators + test suites exceeded 30min; re-mint pressure was wasteful. Env-overridable per deployment.
    # AL-4 (mig 0125, 2026-07-24): forced-rotation TTL for NEW developer API keys,
    # in days. 0 = non-expiring (back-compat / disable). Existing keys + MCP bridge
    # keys are grandfathered non-expiring regardless (they predate this). The mint
    # response surfaces the computed expires_at so it's never a silent surprise.
    API_KEY_DEFAULT_TTL_DAYS: int = 365
    # --- MODIFIED: Added Verification Token Expiry ---
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24 # Default: 24 hours
    # --- END MODIFIED ---
    # --- ADDED: Bootstrap Token Settings ---
    BOOTSTRAP_TOKEN_LIFETIME: int = 300  # Default: 5 minutes (300 seconds)
    # --- END ADDED ---
    
    # --- f050: Docker Registry Token Auth ---
    DOCKER_TOKEN_SIGNING_KEY_PATH: str = ""  # Path to RSA private key PEM
    DOCKER_ADMIN_PULL_TOKEN_HASH: str = ""   # SHA-256 hex of admin's dpt_ pull token
    DOCKER_TOKEN_ISSUER: str = "theprotocol-registry-auth"
    # §EXCISION — was `images.raphaeljeziorny.com`: a personal domain baked as the
    # default for every deployment, and drifted from what production actually
    # serves. Nodes that need the legacy host set DOCKER_TOKEN_SERVICE explicitly.
    DOCKER_TOKEN_SERVICE: str = "images.theprotocol.cloud"
    DOCKER_TOKEN_EXPIRY_SECONDS: int = 900   # 15 minutes

    # --- Event Store Configuration ---
    EVENT_STORE_URL: str = "http://localhost:8200"  # Event Store service URL
    EVENT_STORE_API_KEY: str = ""  # Internal API key for Event Store
    
    # --- Rate Limiting Configuration ---
    # §DOCSFIX D6-315 (2026-10-16): the role limits RATE_LIMIT_ADMIN / _DEVELOPER / _AGENT / _PUBLIC are gone. They
    # fed a RATE_LIMITS dict nothing consulted (slowapi limits per ROUTE), so setting one changed nothing.
    # Coarse per-principal backstop applied to EVERY route by the middleware.
    # Deliberately generous: the real protection is the per-route limits, and a
    # tight global default would only catch legitimate fan-out (a dashboard page
    # load, a federation sweep) while an attacker rotates principals anyway.
    RATE_LIMIT_DEFAULT: str = "1200/minute"
    # Comma-separated API keys that, presented in X-Api-Key, count in a bucket of their own (bypass:<prefix>) instead
    # of their address's: the limit is the same, these keys only stop sharing their address's counter.
    RATE_LIMIT_BYPASS_KEYS: str = ""
    
    @property
    def rate_limit_bypass_keys(self) -> List[str]:
        """Parse comma-separated bypass keys."""
        if not self.RATE_LIMIT_BYPASS_KEYS:
            return []
        return [key.strip() for key in self.RATE_LIMIT_BYPASS_KEYS.split(",") if key.strip()]


    # --- CORS Settings ---
    ALLOWED_ORIGINS: List[Union[AnyHttpUrl, str]] = ["*"]

    # --- Logging Settings ---
    LOG_LEVEL: str = "INFO"
    
    # --- Federation Settings ---
    REGISTRY_NAME: str = "AgentVault Registry"  # Name of this registry instance
    # §pass34 (2026-05-17) — Canonical federation identity of THIS registry,
    # used to stamp `card_data.federation_metadata.origin_registry_name` on
    # native exports and as the `is_native_card` comparator. Seeded into the
    # `registry_self` singleton by migration 0061 on first boot. Decoupled
    # from `developer.display_name` (which is a personal user handle).
    #
    # Mainframes set this per-frame (Registry-A / Frame-B / Sandbox-A / …).
    # Cloud operator registries set it to their slug (op-tokyo / op-paris / …)
    # via the cloud_provisioner-written .env.operator entry.
    REGISTRY_FEDERATION_NAME: Optional[str] = None
    IS_CENTRAL_REGISTRY: bool = False  # Whether this instance is the central registry
    FEDERATION_ENFORCEMENT_ACTIVE: bool = False  # Phase 2+ gating flag for quarantine/lockdown enforcement
    HEALTH_CHECK_INTERVAL_SECONDS: int = 3600  # How often to check peer health (1 hour)
    HEALTH_CHECK_FAILURE_THRESHOLD: int = 3  # Failures before marking peer as inactive
    FEDERATION_HEALTH_CHECK_SECRET: Optional[str] = None  # Shared secret for health check auth

    # --- OWL25: Federation Base URL (container-to-container, e.g. http://registry-a:8000) ---
    # Used for inter-registry callbacks in sovereign settlement protocol.
    # Defaults to BASE_URL if not set, but MUST be a Docker-internal hostname in containerized setups.
    FEDERATION_BASE_URL: Optional[str] = None

    # --- OAuth Federation Settings ---
    # RA2 (2026-07-24): empty = derive from BASE_URL, so every frame gets its own
    # correct issuer. The old non-empty placeholder (plus a baked .env pinning
    # "http://registry-a:8000") made every frame claim the same wrong `iss`.
    OAUTH_ISSUER: str = ""  # This registry's issuer URL; blank = use BASE_URL
    OAUTH_JWKS_URI: str = "/oauth/.well-known/jwks.json"  # JWKS endpoint path
    OAUTH_TOKEN_EXCHANGE_ENABLED: bool = True  # Enable RFC 8693 token exchange
    # RA2: default `aud` for an exchanged token when the caller does not ask for one.
    # The consumer is the TEG multi-issuer verifier, whose allowed_audiences are
    # ["teg", "cross-registry"] — the old default (TEG_API_BASE_URL) could never
    # match, so even a correctly signed token would have failed audience validation.
    OAUTH_DEFAULT_AUDIENCE: str = "teg"
    OAUTH_TOKEN_EXCHANGE_LIFETIME: int = 300  # Exchange token lifetime in seconds (5 minutes)
    OAUTH_MAX_TOKEN_EXCHANGES_PER_HOUR: int = 100  # Rate limit for token exchanges
    
    # Trusted registries for OAuth federation (loaded from environment as JSON)
    TRUSTED_REGISTRIES: Optional[str] = None  # JSON string of trusted registry configs
    
    @property
    def trusted_registries(self) -> List[dict]:
        """Parse trusted registries from JSON string."""
        if not self.TRUSTED_REGISTRIES:
            return []
        try:
            import json
            return json.loads(self.TRUSTED_REGISTRIES)
        except Exception as e:
            logger.error(f"Failed to parse TRUSTED_REGISTRIES: {e}")
            return []

    # --- ADDED: Email Settings ---
    # Phase 5 reactor: SupplyInvariantBreach alerting recipients (comma-separated emails).
    # If empty, the reactor logs the breach but does not send email — webhook subscribers
    # registered for "supply.invariant_breach" still fire regardless.
    SUPPLY_ALERT_RECIPIENTS: Optional[str] = None  # e.g., "treasury@theprotocol.cloud,security@your.example"
    SUPPLY_ALERT_THROTTLE_SECONDS: int = 300  # min seconds between repeat alerts for sustained breach (default 5min)

    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: Optional[EmailStr] = None
    MAIL_PORT: int = 587
    MAIL_SERVER: Optional[str] = None
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    MAIL_FROM_NAME: Optional[str] = "TheProtocol"
    # §ONESHOT (2026-09-12) — a frame may DECLARE that it sends no mail at all. A mail-less sandbox
    # frame is a legitimate shape (verification off, invite-gated), but validate_production_config()
    # below required SMTP or a parent relay on any frame with a public BASE_URL, so such a frame could
    # not boot; the only way past it had been a plausible relay nobody ran (`MAIL_SERVER=mailpit`, a
    # host that does not resolve — §FRAMELIC row 173). This is the honest third shape: nothing is
    # dialed, and every send logs that it was not sent. It contradicts a configured SMTP/relay on purpose.
    MAIL_DISABLED: bool = False

    # Sovereign sender (security/critical mails: password reset, suspensions, breaches).
    # Falls back to MAIL_* if not set so dev environments without a separate Proton mailbox
    # still send (display name will read "TheProtocol Security" though).
    SECURITY_ALERTS_MAIL_USERNAME: Optional[str] = None
    SECURITY_ALERTS_MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM_NAME_SECURITY: str = "TheProtocol Security"
    # §2026-07-29 — additional selectable sender identities for Email Studio.
    # An identity is advertised ONLY when username AND password are both set:
    # a half-configured sender in the picker would render fine and bounce at
    # the relay, which is the dishonest-UI class the send dialog just removed.
    OPERATORS_MAIL_USERNAME: Optional[str] = None
    OPERATORS_MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM_NAME_OPERATORS: str = "TheProtocol Operators"
    FOUNDER_MAIL_USERNAME: Optional[str] = None
    FOUNDER_MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM_NAME_FOUNDER: str = "Raphael Jeziorny"
    # --- END ADDED ---

    @field_validator("MAIL_FROM", mode="before")
    @classmethod
    def _blank_mail_from_is_none(cls, v):
        """An empty MAIL_FROM means "no sender", not "invalid address".

        A relay-posture node blanks its MAIL_* to prove it holds no local sender.
        `Optional[EmailStr]` rejects "" with "value is not a valid email address",
        which raises during Settings construction — i.e. at import, in every gunicorn
        worker, so the container crash-loops with no obvious link to the env change.
        Measured on op-demo 2026-08-02: "Worker failed to boot", whole node down.
        Empty/whitespace now normalises to None, which is what it was trying to say.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # --- §FRAMEMAIL-4: parent mail relay (CHILD side) ---
    # A node whose admin credential is held outside this org must not carry an SMTP
    # token (PART 11b), but still has to send verification mail or every account it
    # creates is locked out. Such a node sets these two INSTEAD of MAIL_*: it asks
    # its parent to send, over the ordinary federation lane, from a closed template
    # allowlist. Both unset (the default) = no relay = byte-inert.
    MAIL_RELAY_PARENT_URL: Optional[str] = None
    MAIL_RELAY_LICENSE: Optional[str] = None

    # --- §FRAMEMAIL-4: parent mail relay (PARENT side) ---
    # Ships DARK: with MAIL_RELAY_ENABLED false the endpoint 503s for everyone.
    # MAIL_RELAY_CALLERS is a JSON object mapping an authenticated federation
    # identity (or its operator-DID tail) to {"base_url": ..., "label": ...}.
    # Holding a federation license is deliberately NOT sufficient to relay mail.
    MAIL_RELAY_ENABLED: bool = False
    MAIL_RELAY_CALLERS: Optional[str] = None
    MAIL_RELAY_MAX_PER_HOUR: int = 60
    MAIL_RELAY_MAX_RECIPIENTS_PER_DAY: int = 200
    
    # --- Admin 2FA Enforcement ---
    # When True: admin accounts without 2FA enabled are blocked at login.
    # Safe to leave False during beta; flip to True once all admins have 2FA set up.
    REQUIRE_ADMIN_2FA: bool = False

    # --- Beta Invite System ---
    BETA_INVITE_REQUIRED: bool = False  # Set to True on production to gate registration
    # BASE_URL is already defined above and used for invite URL generation
    # --- End Beta Invite System ---

    # --- Email Verification ---
    # When False: newly registered developers are treated as verified immediately.
    # Sandbox registries should set this to False so downloaded agents can self-register.
    REQUIRE_EMAIL_VERIFICATION: bool = True
    # --- End Email Verification ---

    # --- ToS consent (0120) ---
    # When True, registration is refused (422) unless the caller sends tos_accepted=true. The server
    # then stamps TOS_VERSION + a timestamp on the developer row — the audit trail the register form's
    # checkbox alone never produced. Env-gated so it can be enabled per-frame (frame-c canary first).
    TOS_CONSENT_REQUIRED: bool = False
    TOS_VERSION: str = "2.4"  # §LEGALKIT: the ONE Terms version; fiat_onramp reads it, the FE asks GET /api/v1/legal/config
    # --- End ToS consent ---

    # --- TEG Layer Integration Settings ---
    TEG_API_BASE_URL: str = "http://teg-layer:8080"  # TEG Layer URL for container-to-container communication
    TEG_ADMIN_API_KEY: str = "deprecated-shared-key-retired-mtls-phase4"  # §2026-06-17 Phase-4: shared secret RETIRED. This is a NON-SECRET marker (not a credential), not the real key. registry→TEG auth is mTLS-SVID; the TEG ignores this value at enforce. Kept non-empty so the ~55 call sites that build `Authorization: Bearer {key}` unconditionally still emit a VALID header (an empty key → "Bearer " → httpx "Illegal header value", which broke AGORA settlement). Real key removed from env + stripped from the image's /app/.env.
    TEG_PLACEHOLDER_AUTH_TOKEN: Optional[str] = ""  # MVP placeholder token
    
    # --- Treasury DID ---
    # Canonical treasury DID — must match TEG Layer's teg_system_treasury_did
    TEG_SYSTEM_TREASURY_DID: str = "did:theprotocol:teg_system_treasury"
    
    # --- Genesis Grant Settings ---
    # Amount of AVT minted to a developer's FIRST agent upon creation.
    # Subsequent agents for the same developer start at 0 — they must earn or be granted tokens.
    GENESIS_GRANT_AMOUNT: str = "1000.0"  # 1000 AVT for beta
    GENESIS_GRANT_ENABLED: bool = True  # Toggle for production

    # --- POCKET FRAME: device push notifications (f-mobile, 2026-07-07) ---
    # Default OFF fleet-wide; canary = frame-c compose env. ntfy rail is live;
    # FCM/APNs are stubs until platform credentials exist.
    PUSH_NOTIFY_ENABLED: bool = False
    PUSH_NTFY_URL: str = "http://ntfy"   # compose service name on the canary frame
    PUSH_NTFY_PUBLIC_URL: str = ""       # public ntfy base for the FE pairing QR (e.g. https://push.theprotocol.cloud); empty = not publicly exposed on this frame
    PUSH_FCM_ENABLED: bool = False
    PUSH_APNS_ENABLED: bool = False
    # §NOTIFV2 (2026-07-26): catalog-driven notification preferences.
    #   off    → legacy _device_wants verdicts, byte-identical to pre-v2 (new types stay dark)
    #   shadow → legacy decides; v2 resolver runs alongside; disagreements counted in
    #            notify_prefs_shadow_mismatch_total (canary posture)
    #   on     → v2 resolver decides (catalog defaults ∘ dev rows ∘ legacy enablers ∘
    #            device narrowing ∘ thresholds ∘ quiet hours ∘ coalescing)
    # registry-a has NO env_file — set this in the compose environment: block there.
    NOTIFY_V2_MODE: str = "off"
    # Per-decision history (mig 0138). Records delivered/failed/suppressed+reason so the
    # question "why did I not get that one" has an answer other than a Prometheus counter.
    # Only ever written on the v2 path: NOTIFY_V2_MODE=off must stay byte-inert.
    NOTIFICATION_LOG_ENABLED: bool = True
    NOTIFICATION_LOG_RETENTION_DAYS: int = 14

    # --- PHONE FABRIC: capability-gated agent computer-use (2026-07-07) ---
    # Default OFF fleet-wide; enforce = frame-c canary. Backend 'mock' (deterministic test
    # phone) until the redroid data plane is lit on dedicated hardware (Commander-gated).
    PHONE_FABRIC_ENABLED: bool = False
    PHONE_FABRIC_BACKEND: str = "mock"     # mock | redroid
    PHONE_USE_MODE: str = "off"            # off | shadow | enforce
    PHONE_MAX_CONCURRENT_SESSIONS: int = 8
    PHONE_SESSION_TTL_DEFAULT: int = 600   # seconds; capped by the token's own expiry

    # --- THE GUILD: agent work exchange (2026-07-07) ---
    # Open labor market. Default OFF fleet-wide; frame-c canary. Money rides the treasury-as-escrow
    # path (Δ=0, rule-13). Protocol fee taken on settle (retained in treasury).
    GUILD_ENABLED: bool = False
    GUILD_FEE_BPS: int = 250               # 2.5% protocol fee on settle (cap 20%)
    GUILD_ZK_CREDENTIAL_ENABLED: bool = False   # Ed25519-signed work credential (ZK circuit = handoff)
    GUILD_REAPER_INTERVAL_SECONDS: int = 60

    # --- THE CONTRACT SPINE (2026-07-25, SPEC_2026-07-25_CONTRACT_SPINE_V2) ---
    # Contracts = the durable escrowed-at-agreed milestoned agreement every surface mints into
    # (direct, discovery "Engage", THE GUILD, templates). Default OFF fleet-wide; frame-c canary.
    # Money rides the SHARED treasury-escrow rail (services/escrow.py, ctrref legs, Δ=0, rule-13).
    CONTRACTS_V2_ENABLED: bool = False
    CONTRACT_FEE_BPS: int = 0              # D5: bilateral ≠ marketplace — no fee on direct contracts
    CONTRACT_REAPER_INTERVAL_SECONDS: int = 60
    CONTRACT_STUCK_ESCROW_MINUTES: int = 30    # agreed w/ NULL escrow_ref (crash between claim+deposit)
    CONTRACT_STUCK_MONEY_MINUTES: int = 30     # releasing older than this → reaper re-drives legs
    CONTRACT_DEADLINE_GRACE_HOURS: int = 24    # past-deadline grace before auto-dispute
    GUILD_MINTS_CONTRACTS: bool = False    # P3a mirror mode: guild awards mint contract ledger rows
    CONTRACT_TEMPLATES_ENABLED: bool = False   # P4: template library (free | purchase | royalty)
    TEMPLATE_CONTRACT_FEE_BPS: int = 0     # D5: fee snapshot for template-originated contracts
    CONTRACT_ROYALTY_STACK_CAP_BPS: int = 750  # D2: combined template+forge carve ceiling

    # --- COCKPIT CARD: liable hybrid identity (2026-07-25, SPEC_2026-07-25_LIABLE_IDENTITY_COCKPIT_CARD) ---
    # A human developer underwrites ONE agent for a declared scope; authority re-derived every
    # request via the issuer-current clamp (never snapshotted into power). Deny-only, Δ-irrelevant.
    LIABILITY_MODE: str = "off"                    # off | shadow | enforce (per-registry ratchet, frame-c first)
    # JURISDICTION PROFILES: operator-declared per-deployment feature restriction (SPEC 2026-07-31).
    # off = byte-inert. shadow = evaluate + log + count, never block. enforce = 403 pre-escrow.
    # Profile JSON lives in exchange_flags key 'jurisdiction_profile' (null = unrestricted).
    JURISDICTION_MODE: str = "off"                 # off | shadow | enforce (frame-c testbed first)
    # CROSS-FRAME CONTRACTS: off = byte-inert (no mirror emitted, no replica stored, routes 404).
    # shadow = mirror + replicate + reconcile, but the peer surface is read-only advisory.
    # enforce = the relayed command rail is live. Deny-only and pre-escrow → Δ-irrelevant.
    CONTRACTS_XFRAME_MODE: str = "off"             # off | shadow | enforce
    LIABILITY_PRESENCE_MAX_AGE_MINUTES: int = 5    # freshness window for a presence proof at issue
    LIABILITY_CHALLENGE_TTL_SECONDS: int = 120     # banking-app confirm window; expiry is a DENIAL
    # §SUBAGENT-LIABILITY (2026-08-13, "hands, not persons"): graduated autonomy — a walletless
    # HAND may move value inside its leash autonomously, but a dispute-bearing / over-leash action
    # above this amount PAUSES for a live human presence proof (Cockpit fingerprint/TOTP) in enforce;
    # in shadow it only logs "would require presence". 0 = step-up disabled (default, byte-inert).
    LIABILITY_PRESENCE_THRESHOLD_AVT: float = 0.0
    LIABILITY_ISSUE_ORG_ADMIN_ONLY: bool = False   # decision #2: self-service default; registries may restrict

    # Where the INSTALLED Pocket PWA lives. Push deep links must point at the origin the app was
    # installed from, or Android opens a browser tab instead of the app (api.* and registry.* are
    # the same backend but different origins, and only one of them is installed). Defaults to
    # BASE_URL when unset, so single-origin deployments need no configuration.
    PUSH_APP_BASE_URL: str = ""


    # --- Pydantic Settings Configuration ---
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH if ENV_FILE_PATH.is_file() else None,
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore',
        validate_default=False,
    )

# Function to help detect testing environments
def is_testing() -> bool:
    """Check if we're running in a test environment"""
    return 'PYTEST_CURRENT_TEST' in os.environ

# Instantiate settings. This will load values upon import.
try:
    settings = Settings()
    logger_config.info("Settings loaded successfully.")
    
    # Validate production configuration
    try:
        settings.validate_production_config()
        logger_config.info("Production configuration validation passed.")
    except ValueError as e:
        logger_config.error(f"Production configuration validation failed: {e}")
        if not is_testing():
            raise
    
    try:
        loaded_env_files = settings.model_config.get('env_file')
        logger_config.info(f"Pydantic settings loaded env_file: {loaded_env_files}")
    except Exception:
        pass
    # --- MODIFIED: Check email settings ---
    if not settings.MAIL_SERVER or not settings.MAIL_USERNAME or not settings.MAIL_FROM:
        logger_config.warning("Email settings (MAIL_SERVER, MAIL_USERNAME, MAIL_FROM) are not fully configured. Email sending will likely fail.")
    # --- END MODIFIED ---


except Exception as e:
    logger_config.error(f"Failed to instantiate Settings: {e}", exc_info=True)
    if is_testing():
        logger_config.warning("Loading settings failed, falling back to test defaults.")
        settings = Settings(
            DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test_db",
            API_KEY_SECRET="test_secret_key_for_testing_only_fallback_1234567890abcdef",
            # --- MODIFIED: Added default for testing ---
            EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS=1,
            # --- END MODIFIED ---
            # --- ADDED: Placeholder email settings for tests ---
            MAIL_SERVER="smtp.example.com",
            MAIL_USERNAME="test@example.com",
            MAIL_FROM="test@example.com",
            # --- END ADDED ---
            BASE_URL="http://testserver"
        )
        logger_config.warning("Using test settings for DATABASE_URL, API_KEY_SECRET, BASE_URL and placeholder EMAIL settings.")
    else:
        logger_config.critical("CRITICAL: Failed to load application settings from environment or .env file.")
        raise e

# --- Configure Logging ---
log_level_int = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(level=log_level_int, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', force=True)
logger = logging.getLogger(__name__)
logger.info(f"Logging configured with level: {settings.LOG_LEVEL}")
