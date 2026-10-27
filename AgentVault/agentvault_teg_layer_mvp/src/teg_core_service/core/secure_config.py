"""
Production-grade configuration management for TEG Core Service

This module provides centralized configuration with:
- Environment variable support with validation
- Type safety and constraints
- Secure defaults (no secrets have defaults)
- Clear documentation for each setting
"""
import os
import json
from decimal import Decimal
from functools import lru_cache
from typing import Optional, Literal, List, Dict, Any

from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuditorRuleCodes:
    """Auditor rule code constants"""
    EPA_V1 = "EXTREME_PRICE_ANOMALY_V1"
    BCD_PSYNC_V1 = "BASIC_COLLUSION_PRICE_SYNC_V1"


class Settings(BaseSettings):
    """
    TEG Core Service configuration with strict validation and type safety.
    
    All sensitive settings require explicit configuration - no production defaults.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Validate all fields even if not set
        validate_default=True,
        # Allow extra fields for Event Store integration
        extra="allow"
    )
    
    # ===== Database Configuration =====
    database_url: str = Field(
        default="sqlite:///./teg_database.db",
        description="Database connection URL. Use PostgreSQL in production.",
        examples=["postgresql+psycopg://user:pass@localhost/teg_db"]
    )
    
    # ===== Security Configuration =====
    admin_api_key: SecretStr = Field(
        # §2026-06-17 Phase 4: RETIRED as the internal authenticator (mTLS-SPIFFE is primary).
        # Made OPTIONAL with a non-secret placeholder so removing TEG_ADMIN_API_KEY/ADMIN_API_KEY
        # from the environment does NOT raise a boot-time ValidationError. Under
        # TEG_MTLS_REQUIRED=true nothing reads it; while shadow, a real env value still overrides.
        # (No min_length — strength is irrelevant for a deprecated, non-authoritative value.)
        default=SecretStr("deprecated-shared-admin-key-retired-by-mtls-phase4"),
        description="DEPRECATED (Phase 4): legacy shared admin key, superseded by mTLS-SPIFFE.",
    )
    
    avtp_system_api_key: SecretStr = Field(
        ...,  # Required - no default
        description="API key for AVTP system integration. Must be strong and unique.",
        min_length=32
    )
    
    # JWT Bearer Grant Configuration
    teg_token_signing_key: SecretStr = Field(
        ...,  # Required - no default
        description="Signing key for TEG access tokens. Must be strong and unique.",
        min_length=32
    )
    
    # P0-002: Registry JWT validation key
    # Used to verify the registry_jwt in POST /auth/token requests.
    # Must match the Registry's API_KEY_SECRET environment variable.
    registry_jwt_secret: Optional[SecretStr] = Field(
        default=None,
        description="Secret key from the parent Registry used to sign agent JWTs. "
                    "When set, the /auth/token endpoint will validate registry_jwt signatures. "
                    "When None, validation is skipped (MVP mode — NOT for production).",
    )
    
    # ===== Application Configuration =====
    app_name: str = Field(
        default="TEG Core Service",
        description="Application name for identification"
    )
    
    app_version: str = Field(
        default="1.0.0",
        description="Application version"
    )
    
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment"
    )
    
    debug: bool = Field(
        default=False,
        description="Enable debug mode. MUST be False in production."
    )
    
    # ===== API Configuration =====
    api_v1_prefix: str = Field(
        default="/api/v1",
        description="API v1 URL prefix",
        pattern="^/[a-zA-Z0-9/_-]+$"
    )
    
    cors_allowed_origins: list[str] = Field(
        default=["*"],
        description="CORS allowed origins. Must be explicitly configured in production.",
        examples=[["https://app.agentvault.com", "https://admin.agentvault.com"]]
    )
    
    # ===== Logging Configuration =====
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level"
    )
    
    log_format: Literal["json", "text"] = Field(
        default="json",
        description="Log output format. Use 'json' for production."
    )
    
    # ===== Token Economy Configuration =====
    teg_system_treasury_did: str = Field(
        default="did:theprotocol:teg_system_treasury",
        description="System treasury DID for rewards and fees",
        pattern="^did:(theprotocol|agentvault):[a-zA-Z0-9_-]+$"
    )
    
    # Transfer limits and fees
    min_transfer_amount: Decimal = Field(
        default=Decimal("0.01"),
        description="Minimum allowed transfer amount",
        ge=Decimal("0.001")
    )
    
    max_transfer_amount: Optional[Decimal] = Field(
        default=None,
        description="Maximum allowed transfer amount. None = no limit",
        ge=Decimal("0")
    )
    
    default_transfer_fee: Decimal = Field(
        default=Decimal("0.0"),
        description="Default transfer fee amount",
        ge=Decimal("0")
    )
    
    fee_collection_address: Optional[str] = Field(
        default=None,
        description="Address where fees are collected. None = treasury",
        pattern="^(did:(theprotocol|agentvault):[a-zA-Z0-9_-]+)?$"
    )
    
    # ===== Reward Configuration =====
    attestation_submission_reward: Decimal = Field(
        default=Decimal("0.1"),
        description="AVT reward for valid attestation submission",
        ge=Decimal("0")
    )
    
    # ===== Reputation Weight Configuration =====
    # Basic reputation weights
    w1_stake_weight: float = Field(
        default=0.1,
        description="Weight for stake in reputation calculation",
        ge=0.0, le=100.0
    )
    
    w2_attestation_weight: float = Field(
        default=2.0,
        description="Points per valid attestation",
        ge=0.0, le=100.0
    )
    
    w3_successful_txn_weight: float = Field(
        default=1.0,
        description="Weight for successful AVTP transactions",
        ge=0.0, le=100.0
    )
    
    w4_failed_txn_weight: float = Field(
        default=2.0,
        description="Penalty weight for failed AVTP transactions",
        ge=0.0, le=100.0
    )
    
    w5_critical_flag_penalty: float = Field(
        default=50.0,
        description="Penalty for critical auditor flags",
        ge=0.0, le=1000.0
    )
    
    w6_negative_ddr_penalty: float = Field(
        default=100.0,
        description="Penalty for negative DDR rulings",
        ge=0.0, le=1000.0
    )
    
    # ZKP attestation weights
    w7_successful_zkp_attestation_bonus: float = Field(
        default=10.0,
        description="Bonus for successful ZKP attestation",
        ge=0.0, le=100.0
    )
    
    w8_failed_zkp_attestation_penalty: float = Field(
        default=25.0,
        description="Penalty for failed ZKP attestation",
        ge=0.0, le=100.0
    )
    
    w9_successful_resource_zkp: float = Field(
        default=5.0,
        description="Bonus for successful resource usage ZKP",
        ge=0.0, le=100.0
    )
    
    w10_failed_resource_zkp: float = Field(
        default=15.0,
        description="Penalty for failed resource usage ZKP",
        ge=0.0, le=100.0
    )
    
    w11_collusion_flag_penalty: float = Field(
        default=75.0,
        description="Penalty for potential collusion",
        ge=0.0, le=1000.0
    )
    
    # Reputation constraints
    max_stake_effective_for_rep: Decimal = Field(
        default=Decimal("1000.0"),
        description="Maximum stake considered for reputation",
        ge=Decimal("0")
    )
    
    min_reputation_score: int = Field(
        default=0,
        description="Minimum allowed reputation score",
        ge=0
    )
    
    # Reputation tier thresholds
    rep_tier_bronze_min_score: int = Field(
        default=0,
        description="Minimum score for Bronze tier",
        ge=0
    )
    
    rep_tier_silver_min_score: int = Field(
        default=300,
        description="Minimum score for Silver tier",
        ge=0
    )
    
    rep_tier_gold_min_score: int = Field(
        default=700,
        description="Minimum score for Gold tier",
        ge=0
    )
    
    # ===== Auditor Rule Parameters =====
    # Extreme Price Anomaly Detection (EPA_V1)
    extreme_price_anomaly_threshold_factor: float = Field(
        default=10.0,
        description="Price deviation factor to trigger anomaly (e.g., 10x)",
        ge=1.0, le=1000.0
    )
    
    extreme_price_anomaly_min_tx_count_for_baseline: int = Field(
        default=5,
        description="Minimum transactions needed to establish baseline",
        ge=1, le=1000
    )
    
    extreme_price_anomaly_lookback_days: int = Field(
        default=30,
        description="Days to look back for baseline calculation",
        ge=1, le=365
    )
    
    # Basic Collusion Detection - Price Sync (BCD_PSYNC_V1)
    price_sync_threshold_percentage: float = Field(
        default=0.01,
        description="Price similarity threshold (0.01 = 0.01%)",
        ge=0.0, le=100.0
    )
    
    price_sync_min_agents_involved: int = Field(
        default=3,
        description="Minimum agents for collusion detection",
        ge=2, le=100
    )
    
    price_sync_min_transactions_per_agent: int = Field(
        default=5,
        description="Minimum transactions per agent for collusion",
        ge=1, le=100
    )
    
    price_sync_lookback_hours: int = Field(
        default=24,
        description="Hours to look back for collusion detection",
        ge=1, le=168
    )
    
    # ===== External Service Configuration =====
    circuit_registry_path: str = Field(
        default="../agentvault_circuit_registry",
        description="Path to circuit registry (relative or absolute)"
    )
    
    # ===== OAuth Federation Configuration =====
    oauth_federation_enabled: bool = Field(
        default=False,
        description="Enable multi-issuer OAuth federation for cross-registry support"
    )
    
    trusted_registries: str = Field(
        default="[]",
        description="JSON array of trusted registry configurations. Each must include: name, issuer, jwks_uri, allowed_audiences",
        examples=['[{"name": "Registry A", "issuer": "https://registry-a.example.com", "jwks_uri": "https://registry-a.example.com/oauth/.well-known/jwks.json", "allowed_audiences": ["teg", "cross-registry"]}]']
    )
    
    @property
    def parsed_trusted_registries(self) -> List[Dict[str, Any]]:
        """Parse trusted registries JSON configuration"""
        try:
            return json.loads(self.trusted_registries)
        except json.JSONDecodeError:
            return []
    
    # ===== Cross-TEG Configuration =====
    cross_teg_enabled: bool = Field(
        default=False,
        description="Enable cross-TEG transfer functionality"
    )
    
    teg_id: str = Field(
        default="teg-layer-a",
        description="Unique identifier for this TEG instance",
        pattern="^[a-zA-Z0-9-_]+$"
    )

    minting_authority: str = Field(
        default="teg-layer-a",
        description="Only this TEG ID is allowed to mint (issue) new tokens. All other TEGs reject /admin/token/issue with 403."
    )
    
    partner_tegs: str = Field(
        default="[]",
        description="JSON array of partner TEG configurations. Each must include: teg_id, url, registry_id",
        examples=['[{"teg_id": "teg-layer-b", "url": "http://teg-layer-b:8080", "registry_id": "registry-b"}]']
    )
    
    cross_teg_transfer_timeout: int = Field(
        default=300,
        description="Timeout for cross-TEG transfers in seconds",
        ge=30, le=3600
    )
    
    cross_teg_max_amount: Decimal = Field(
        default=Decimal("10000.0"),
        description="Maximum amount allowed for cross-TEG transfers",
        ge=Decimal("0")
    )
    
    @property
    def parsed_partner_tegs(self) -> List[Dict[str, Any]]:
        """Parse partner TEGs JSON configuration"""
        try:
            return json.loads(self.partner_tegs)
        except json.JSONDecodeError:
            return []
    
    # ===== Performance Configuration =====
    max_request_size: int = Field(
        default=1048576,  # 1MB
        description="Maximum request body size in bytes",
        ge=1024, le=104857600  # 1KB to 100MB
    )
    
    request_timeout: int = Field(
        default=30,
        description="Request timeout in seconds",
        ge=1, le=300
    )
    
    # ===== Validation Methods =====
    @field_validator('max_transfer_amount')
    def validate_max_transfer_amount(cls, v, info):
        """Ensure max transfer amount is greater than min if set"""
        if v is not None and 'min_transfer_amount' in info.data:
            min_amount = info.data['min_transfer_amount']
            if v < min_amount:
                raise ValueError(f"max_transfer_amount ({v}) must be >= min_transfer_amount ({min_amount})")
        return v
    
    @field_validator('rep_tier_silver_min_score')
    def validate_silver_tier(cls, v, info):
        """Ensure silver tier is higher than bronze"""
        if 'rep_tier_bronze_min_score' in info.data:
            bronze = info.data['rep_tier_bronze_min_score']
            if v <= bronze:
                raise ValueError(f"Silver tier score ({v}) must be > bronze tier score ({bronze})")
        return v
    
    @field_validator('rep_tier_gold_min_score')
    def validate_gold_tier(cls, v, info):
        """Ensure gold tier is higher than silver"""
        if 'rep_tier_silver_min_score' in info.data:
            silver = info.data['rep_tier_silver_min_score']
            if v <= silver:
                raise ValueError(f"Gold tier score ({v}) must be > silver tier score ({silver})")
        return v
    
    @field_validator('environment')
    def validate_debug_in_production(cls, v, info):
        """Ensure debug is disabled in production"""
        if v == 'production' and info.data.get('debug', False):
            raise ValueError("Debug mode cannot be enabled in production environment")
        return v
    
    def get_fee_collection_address(self) -> str:
        """Get the effective fee collection address (treasury if not set)"""
        return self.fee_collection_address or self.teg_system_treasury_did
    
    def validate_production_config(self) -> None:
        """Validate configuration for production environment"""
        if self.environment != "production":
            return
        
        errors = []
        
        # Check for SQLite in production
        if "sqlite" in self.database_url.lower():
            errors.append("SQLite database not allowed in production. Use PostgreSQL.")
        
        # Check for wildcard CORS in production
        if "*" in self.cors_allowed_origins:
            errors.append("Wildcard CORS origins not allowed in production.")
        
        # Check debug mode
        if self.debug:
            errors.append("Debug mode must be disabled in production.")
        
        # Check log format
        if self.log_format != "json":
            errors.append("JSON log format required in production.")
        
        # Check for test/example values in secrets
        for field_name in ["admin_api_key", "avtp_system_api_key", "teg_token_signing_key"]:
            value = getattr(self, field_name).get_secret_value()
            if any(test_word in value.lower() for test_word in ["test", "example", "demo", "sample"]):
                errors.append(f"{field_name} appears to contain a test value.")
        
        if errors:
            raise ValueError(f"Production configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance with production validation"""
    settings = Settings()
    # Validate production configuration
    settings.validate_production_config()
    return settings


# Export for backward compatibility
settings = get_settings()
