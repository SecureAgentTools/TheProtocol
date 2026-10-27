"""
Dynamic APY Engine — Phase 4 Early-Pull (Decision D5)

Replaces fixed APY tiers with a logistical decay curve that protects
the treasury at high TVL ratios and incentivizes staking at low TVL.

Formula:
    APY = R_max / (1 + e^(k × (TVL_pct - TVL_target))) + L_premium(lock_days)
    L_premium(lock_days) = base_rate × ln(1 + lock_days / 30)

Reference: Economic_Engine_Implementation_Specification.md §7.1
Commander directive: "Protect the treasury at all costs."
"""
import math
import logging
from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)


@dataclass
class APYConfig:
    """
    Dynamic APY curve parameters.
    
    Eventually sourced from RegistryEnforcementPolicy JSON.
    For now, hardcoded with spec defaults.
    """
    r_max: float = 15.0           # Maximum base APY (%)
    k: float = 0.05               # Decay steepness
    tvl_target: float = 40.0      # Healthy staking ratio (%)
    lock_base_rate: float = 2.0   # Lock premium base rate (%)
    total_supply: int = 10_000_000 # Total AVT supply (matches TEG genesis seed)
    circuit_breaker_pct: float = 75.0  # Emergency threshold (%)
    min_apy: float = 1.0          # Floor APY (%)
    
    # Standard lock period presets for the tier display
    lock_presets: List[int] = field(default_factory=lambda: [0, 30, 90, 180, 365])


class DynamicAPYEngine:
    """
    Computes APY dynamically from a logistical decay curve.
    
    Replaces the empty StakingApyTier database table approach.
    This is a pure-computation service — no DB writes, only reads
    for TVL calculation.
    """
    
    def __init__(self, config: Optional[APYConfig] = None):
        self.config = config or APYConfig()

    @classmethod
    def from_policy(cls, policy_json: dict) -> "DynamicAPYEngine":
        """
        Instantiate a DynamicAPYEngine from a policy JSON blob.

        Reads staking_rewards sub-section; falls back to APYConfig defaults
        for any missing key. This is the policy-driven constructor — preferred
        over the singleton get_dynamic_apy_engine() when a DB policy is available.
        """
        sr = policy_json.get("staking_rewards", {})
        config = APYConfig(
            r_max=float(sr.get("max_apy_percent", 15.0)),
            k=float(sr.get("decay_steepness_k", 0.05)),
            tvl_target=float(sr.get("tvl_target_percent", 40.0)),
            lock_base_rate=float(sr.get("lock_premium_base_rate_percent", 2.0)),
            circuit_breaker_pct=float(sr.get("circuit_breaker_tvl_percent", 75.0)),
            min_apy=float(sr.get("min_apy_percent", 1.0)),
        )
        return cls(config=config)
    
    def _base_apy(self, tvl_pct: float) -> float:
        """
        Compute base APY from logistic decay.
        
        At low TVL: approaches R_max (incentivize staking).
        At TVL_target: inflection point (~R_max/2).
        At high TVL: decays toward min_apy (protect treasury).
        """
        exponent = self.config.k * (tvl_pct - self.config.tvl_target)
        # Clamp exponent to avoid overflow
        exponent = max(-500, min(500, exponent))
        base = self.config.r_max / (1.0 + math.exp(exponent))
        return max(base, self.config.min_apy)
    
    def _lock_premium(self, lock_days: int) -> float:
        """
        Compute lock duration premium.
        
        L_premium = base_rate × ln(1 + lock_days / 30)
        
        Examples (base_rate=2.0%):
          Flexible (0 days): +0.0%
          30 days:           +1.39%
          90 days:           +2.37%
          180 days:          +3.58%
          365 days:          +5.17%
        """
        if lock_days <= 0:
            return 0.0
        return self.config.lock_base_rate * math.log(1.0 + lock_days / 30.0)
    
    def calculate_apy(self, lock_days: int, tvl_pct: float) -> float:
        """
        Compute total APY for a given lock period and TVL ratio.
        
        Args:
            lock_days: Lock period in days (0 = flexible)
            tvl_pct: Current TVL as percentage of total supply (0-100)
            
        Returns:
            Total APY as percentage (e.g. 12.5 means 12.5%)
        """
        base = self._base_apy(tvl_pct)
        premium = self._lock_premium(lock_days)
        total = base + premium
        # Round to 1 decimal place for display
        return round(total, 1)
    
    def check_circuit_breaker(self, tvl_pct: float) -> bool:
        """Returns True if TVL exceeds emergency threshold."""
        return tvl_pct >= self.config.circuit_breaker_pct
    
    def get_tier_display(self, tvl_pct: float) -> List[Dict[str, Any]]:
        """
        Generate tier display data for the frontend.
        
        Returns a list of preset lock periods with computed APY values,
        formatted to match the frontend's expected schema.
        """
        tiers = []
        base_apy = self._base_apy(tvl_pct)
        
        for lock_days in self.config.lock_presets:
            premium = self._lock_premium(lock_days)
            total_apy = round(base_apy + premium, 1)
            
            tier = {
                "lockPeriod": lock_days,
                "apy": total_apy,
                "baseApy": round(base_apy, 1),
                "lockPremium": round(premium, 1),
                "minAmount": "10",   # Minimum stake from config
                "label": self._get_period_label(lock_days),
                "description": self._get_tier_description(lock_days, premium),
            }
            tiers.append(tier)
        
        return tiers
    
    def get_curve_data(self, lock_days: int = 0) -> List[Dict[str, float]]:
        """
        Generate APY curve data for chart visualization.
        
        Returns APY at different TVL percentages for a given lock period.
        """
        points = []
        for tvl in range(0, 101, 2):  # 0%, 2%, 4%, ..., 100%
            apy = self.calculate_apy(lock_days, float(tvl))
            points.append({
                "tvl_pct": float(tvl),
                "apy": apy
            })
        return points
    
    async def get_current_tvl_pct(self, db: AsyncSession) -> float:
        """
        Calculate current TVL ratio from database.

        TVL% = (total active staked) / real_total_supply × 100
        Uses real supply from TEG treasury endpoint, falls back to config.
        """
        from ..models import Stake

        result = await db.execute(
            select(func.coalesce(func.sum(Stake.amount), 0)).where(
                Stake.is_active == True
            )
        )
        total_staked = float(result.scalar() or 0)

        # Get real total supply from TEG treasury endpoint (fast, no replay)
        real_supply = self.config.total_supply
        try:
            import httpx
            import os
            teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
            teg_key = os.getenv("TEG_ADMIN_API_KEY", "")
            async with httpx.AsyncClient(timeout=3.0, verify=get_httpx_verify()) as client:
                res = await client.get(
                    f"{teg_url}/api/v1/treasury/balance",
                    headers={"X-Service-Token": teg_key}
                )
                if res.status_code == 200:
                    data = res.json()
                    # Total supply = treasury + all agent balances
                    # Use total_supply from the additional_info if available
                    additional = data.get("additional_info", {})
                    supply_val = float(additional.get("total_supply", 0))
                    if supply_val > 0:
                        real_supply = supply_val
        except Exception as e:
            logger.debug(f"TVL: Could not fetch real supply from TEG ({e}), using config default")

        if real_supply <= 0:
            return 0.0

        tvl_pct = (total_staked / real_supply) * 100.0
        logger.debug(
            f"TVL calculation: staked={total_staked}, "
            f"supply={real_supply}, tvl_pct={tvl_pct:.1f}%"
        )
        return tvl_pct
    
    async def calculate_current_apy(
        self, db: AsyncSession, lock_days: int
    ) -> float:
        """Convenience: compute APY using live TVL from DB."""
        tvl_pct = await self.get_current_tvl_pct(db)
        return self.calculate_apy(lock_days, tvl_pct)
    
    async def get_current_tiers(
        self, db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """Convenience: generate tier display using live TVL from DB."""
        tvl_pct = await self.get_current_tvl_pct(db)
        tiers = self.get_tier_display(tvl_pct)
        
        # Add metadata
        return {
            "tiers": tiers,
            "metadata": {
                "tvl_pct": round(tvl_pct, 1),
                "total_supply": self.config.total_supply,
                "r_max": self.config.r_max,
                "circuit_breaker": self.check_circuit_breaker(tvl_pct),
                "engine": "dynamic_logistic_decay_v1",
            }
        }
    
    @staticmethod
    def _get_period_label(days: int) -> str:
        if days == 0:
            return "Flexible"
        if days == 365:
            return "1 Year"
        return f"{days} Days"
    
    @staticmethod
    def _get_tier_description(days: int, premium: float) -> str:
        if days == 0:
            return "Unlock anytime"
        return f"+{premium:.1f}% lock addition"


# ── Module-level singleton ──────────────────────────────────────────
_engine: Optional[DynamicAPYEngine] = None

def get_dynamic_apy_engine() -> DynamicAPYEngine:
    """Get or create the singleton DynamicAPYEngine instance."""
    global _engine
    if _engine is None:
        _engine = DynamicAPYEngine()
    return _engine


async def policy_apy_engine(db: AsyncSession) -> DynamicAPYEngine:
    """§DOCSFIX CB-124: the engine built from this registry's resolved policy document, the one the daily distribution
    pays with (services/staking_rewards_service), so the published tiers and the rate of a new lock are the rate paid.
    The code-default singleton only when the document cannot be read."""
    try:
        from .frame_policy import load as _load_policy
        return DynamicAPYEngine.from_policy((await _load_policy(db)).doc)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[DynamicAPY] policy unavailable ({e}); publishing the code defaults")
        return get_dynamic_apy_engine()
