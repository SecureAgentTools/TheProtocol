"""Configuration management for TEG Core Service"""
import json
from functools import lru_cache
from typing import Optional, List, Dict, Any

from pydantic_settings import BaseSettings, SettingsConfigDict


# Auditor Rule Codes
class AuditorRuleCodes:
    EPA_V1 = "EXTREME_PRICE_ANOMALY_V1"
    BCD_PSYNC_V1 = "BASIC_COLLUSION_PRICE_SYNC_V1"


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Database
    database_url: str = "sqlite:///./teg_database.db"
    
    # Security
    # §MONEY-M3a (R26, 2026-09-03): NO default credential. Unset ⇒ "" ⇒
    # core.internal_auth.admin_key_ok() refuses every bearer. mTLS-SPIFFE is the
    # authenticator; the shared key is a gated fallback that only a REAL configured value
    # (≥32 chars, no placeholder word) can satisfy.
    admin_api_key: str = ""
    teg_token_signing_key: str = ""
    enable_admin_impersonation: bool = False  # Admin can act as agents (DEV ONLY)
    
    # Application
    app_name: str = "TEG Core Service"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"
    cors_allowed_origins: list = ["*"]
    
    # API
    api_v1_prefix: str = "/api/v1"
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "text"  # "json" or "text"
    
    # Token Economy Settings
    default_transfer_fee: str = "0.0"
    min_transfer_amount: str = "0.01"
    max_transfer_amount: Optional[str] = None

    # Event Store Integration
    event_store_url: str = "http://localhost:8200"
    event_store_api_key: str = ""
    
    # Reputation Calculation Weights
    w1_stake_weight: float = 0.1  # Low initial weight for stake
    w2_attestation_weight: float = 2.0  # Each valid attestation gives 2 points
    w3_successful_txn_weight: float = 1.0  # Placeholder for AVTP txns
    w4_failed_txn_weight: float = 2.0  # Placeholder for AVTP txns
    w5_critical_flag_penalty: float = 50.0  # Heavy penalty for critical flags
    w6_negative_ddr_penalty: float = 100.0  # Heavier penalty for DDR rulings
    max_stake_effective_for_rep: float = 1000.0  # Max stake considered for reputation
    min_reputation_score: int = 0  # Minimum reputation score
    
    # Reward Settings
    attestation_submission_reward: float = 0.1  # AVT reward for valid attestation
    teg_system_treasury_did: str = "did:theprotocol:teg_system_treasury"  # System account for rewards
    
    # AVTP Integration Settings
    avtp_system_api_key: str = ""
    
    # Registry Integration Settings
    # §MONEY-M3a (R26): no default credential. Read by nothing today (the three
    # verify_registry_service_token twins authenticate by mTLS, then the admin key).
    registry_service_token: str = ""
    
    # ZKP Attestation Weights
    w7_successful_zkp_attestation_bonus: float = 10.0  # Significant bonus for valid ZKP
    w8_failed_zkp_attestation_penalty: float = 25.0  # Significant penalty for invalid ZKP
    
    # Auditor Rule Parameters
    # Extreme Price Anomaly Detection (EPA_V1)
    extreme_price_anomaly_threshold_factor: float = 10.0  # 10x deviation
    extreme_price_anomaly_min_tx_count_for_baseline: int = 5
    extreme_price_anomaly_lookback_days: int = 30
    
    # Basic Collusion Detection - Price Sync (BCD_PSYNC_V1) - for future package
    price_sync_threshold_percentage: float = 0.01  # Prices within 0.01%
    price_sync_min_agents_involved: int = 3
    price_sync_min_transactions_per_agent: int = 5
    price_sync_lookback_hours: int = 24
    
    # Circuit Registry Path
    circuit_registry_path: str = "../agentvault_circuit_registry"  # Relative to TEG MVP root
    
    # Reputation Tier Thresholds
    rep_tier_bronze_min_score: int = 0
    rep_tier_silver_min_score: int = 300
    rep_tier_gold_min_score: int = 700
    
    # Additional weights for new ZKP attestation types and collusion
    w9_successful_resource_zkp: float = 5.0  # Bonus for successful resource usage ZKP
    w10_failed_resource_zkp: float = 15.0  # Penalty for failed resource usage ZKP
    w11_collusion_flag_penalty: float = 75.0  # Heavy penalty for potential collusion
    
    # OAuth Federation Settings
    oauth_federation_enabled: bool = False
    trusted_registries: str = "[]"  # JSON array of trusted registry configurations
    
    # Minting Authority — only this TEG ID is allowed to mint tokens
    # All other TEGs reject /admin/token/issue with 403
    minting_authority: str = "teg-layer-a"

    # Cross-TEG Settings
    cross_teg_enabled: bool = False
    teg_id: str = "teg-layer-a"  # Unique identifier for this TEG
    partner_tegs: str = "[]"  # JSON array of partner TEG configurations
    cross_teg_transfer_timeout: int = 300  # 5 minutes timeout for transfers
    cross_teg_max_amount: float = 10000.0  # Maximum cross-TEG transfer amount
    
    @property
    def parsed_trusted_registries(self) -> List[Dict[str, Any]]:
        """Parse trusted registries JSON configuration"""
        try:
            return json.loads(self.trusted_registries)
        except json.JSONDecodeError:
            return []
    
    @property
    def parsed_partner_tegs(self) -> List[Dict[str, Any]]:
        """Parse partner TEGs JSON configuration"""
        try:
            return json.loads(self.partner_tegs)
        except json.JSONDecodeError:
            return []


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
