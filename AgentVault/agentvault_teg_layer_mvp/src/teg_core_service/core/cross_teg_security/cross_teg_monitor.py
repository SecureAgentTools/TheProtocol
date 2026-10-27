"""
Cross-TEG Transfer Security Module.

Provides security monitoring and anomaly detection for cross-TEG transfers.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
import asyncio
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from ...database.models import CrossTEGTransfer, CrossTEGTransferStatus, AgentTEGProfile

logger = logging.getLogger(__name__)


class TransferPattern:
    """Represents a transfer pattern for anomaly detection."""
    def __init__(self, window_size: int = 100):
        self.amounts = deque(maxlen=window_size)
        self.timestamps = deque(maxlen=window_size)
        self.targets = deque(maxlen=window_size)
        
    def add_transfer(self, amount: Decimal, timestamp: datetime, target: str):
        """Add a transfer to the pattern history."""
        self.amounts.append(amount)
        self.timestamps.append(timestamp)
        self.targets.append(target)
    
    def get_velocity(self) -> float:
        """Calculate transfer velocity (transfers per minute)."""
        if len(self.timestamps) < 2:
            return 0.0
        
        time_diff = (self.timestamps[-1] - self.timestamps[0]).total_seconds() / 60.0
        if time_diff == 0:
            return 0.0
        
        return len(self.timestamps) / time_diff
    
    def get_average_amount(self) -> Decimal:
        """Get average transfer amount."""
        if not self.amounts:
            return Decimal('0')
        return sum(self.amounts) / len(self.amounts)
    
    def get_unique_targets(self) -> int:
        """Get number of unique targets."""
        return len(set(self.targets))


class CrossTEGSecurityMonitor:
    """
    Monitors cross-TEG transfers for security anomalies.
    
    Features:
    - Transfer velocity monitoring
    - Amount anomaly detection
    - Pattern-based fraud detection
    - Real-time alerting
    """
    
    def __init__(self, teg_id: str):
        self.teg_id = teg_id
        
        # Transfer patterns by agent
        self.agent_patterns: Dict[str, TransferPattern] = defaultdict(
            lambda: TransferPattern(window_size=100)
        )
        
        # Anomaly thresholds
        self.thresholds = {
            "max_velocity": 10.0,  # Max transfers per minute
            "max_single_amount": Decimal('10000'),  # Max single transfer
            "max_daily_amount": Decimal('50000'),  # Max daily total
            "suspicious_target_count": 20,  # Max unique targets in window
            "rapid_fire_window": 60,  # Seconds for rapid fire detection
            "rapid_fire_count": 5  # Max transfers in rapid fire window
        }
        
        # Alert callbacks
        self.alert_callbacks: List[callable] = []
        
        # Statistics
        self.stats = {
            "total_transfers_monitored": 0,
            "anomalies_detected": 0,
            "alerts_triggered": 0
        }
    
    async def monitor_transfer(
        self,
        db: AsyncSession,
        transfer_id: str,
        source_agent: str,
        target_agent: str,
        amount: Decimal,
        source_teg: str,
        target_teg: str
    ) -> Dict[str, Any]:
        """
        Monitor a cross-TEG transfer for anomalies.
        
        Returns:
            Dict containing monitoring results and any detected anomalies
        """
        monitoring_result = {
            "transfer_id": transfer_id,
            "monitored": True,
            "anomalies": [],
            "risk_score": 0.0,
            "recommendations": []
        }
        
        # Update statistics
        self.stats["total_transfers_monitored"] += 1
        
        # Update agent pattern
        pattern = self.agent_patterns[source_agent]
        pattern.add_transfer(amount, datetime.now(timezone.utc), target_agent)
        
        # Check for anomalies
        anomalies = []
        
        # 1. Amount anomaly
        if amount > self.thresholds["max_single_amount"]:
            anomalies.append({
                "type": "excessive_amount",
                "severity": "high",
                "details": f"Amount {amount} exceeds threshold {self.thresholds['max_single_amount']}"
            })
        
        # 2. Velocity anomaly
        velocity = pattern.get_velocity()
        if velocity > self.thresholds["max_velocity"]:
            anomalies.append({
                "type": "high_velocity",
                "severity": "medium",
                "details": f"Transfer velocity {velocity:.2f}/min exceeds threshold"
            })
        
        # 3. Target diversity anomaly
        unique_targets = pattern.get_unique_targets()
        if unique_targets > self.thresholds["suspicious_target_count"]:
            anomalies.append({
                "type": "suspicious_target_diversity",
                "severity": "high",
                "details": f"Agent has transferred to {unique_targets} unique targets"
            })
        
        # 4. Check daily limit
        daily_total = await self._get_daily_total(db, source_agent)
        if daily_total + amount > self.thresholds["max_daily_amount"]:
            anomalies.append({
                "type": "daily_limit_exceeded",
                "severity": "high",
                "details": f"Daily total {daily_total + amount} exceeds limit"
            })
        
        # 5. Rapid fire detection
        rapid_fire_count = await self._check_rapid_fire(db, source_agent)
        if rapid_fire_count >= self.thresholds["rapid_fire_count"]:
            anomalies.append({
                "type": "rapid_fire_transfers",
                "severity": "critical",
                "details": f"{rapid_fire_count} transfers in {self.thresholds['rapid_fire_window']}s"
            })
        
        # Calculate risk score
        risk_score = self._calculate_risk_score(anomalies)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(anomalies, risk_score)
        
        # Update result
        monitoring_result["anomalies"] = anomalies
        monitoring_result["risk_score"] = risk_score
        monitoring_result["recommendations"] = recommendations
        
        # Trigger alerts if needed
        if anomalies:
            self.stats["anomalies_detected"] += len(anomalies)
            await self._trigger_alerts(monitoring_result)
        
        # Log high-risk transfers
        if risk_score > 0.7:
            logger.warning(
                f"HIGH RISK TRANSFER DETECTED: {transfer_id} "
                f"from {source_agent} to {target_agent} "
                f"amount: {amount}, risk_score: {risk_score}"
            )
        
        return monitoring_result
    
    async def _get_daily_total(
        self,
        db: AsyncSession,
        agent_id: str
    ) -> Decimal:
        """Get total transfer amount for an agent in the last 24 hours."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        
        result = await db.execute(
            select(func.sum(CrossTEGTransfer.amount))
            .where(
                and_(
                    CrossTEGTransfer.source_agent_id == agent_id,
                    CrossTEGTransfer.initiated_at >= since,
                    CrossTEGTransfer.status.in_([
                        CrossTEGTransferStatus.COMPLETED,
                        CrossTEGTransferStatus.COMMITTED
                    ])
                )
            )
        )
        
        total = result.scalar() or Decimal('0')
        return total
    
    async def _check_rapid_fire(
        self,
        db: AsyncSession,
        agent_id: str
    ) -> int:
        """Check for rapid fire transfer pattern."""
        since = datetime.now(timezone.utc) - timedelta(seconds=self.thresholds["rapid_fire_window"])
        
        result = await db.execute(
            select(func.count(CrossTEGTransfer.transfer_id))
            .where(
                and_(
                    CrossTEGTransfer.source_agent_id == agent_id,
                    CrossTEGTransfer.initiated_at >= since
                )
            )
        )
        
        count = result.scalar() or 0
        return count
    
    def _calculate_risk_score(self, anomalies: List[Dict[str, Any]]) -> float:
        """
        Calculate risk score based on detected anomalies.
        
        Returns:
            Risk score between 0.0 (no risk) and 1.0 (maximum risk)
        """
        if not anomalies:
            return 0.0
        
        severity_weights = {
            "low": 0.2,
            "medium": 0.4,
            "high": 0.7,
            "critical": 1.0
        }
        
        total_weight = sum(
            severity_weights.get(anomaly.get("severity", "low"), 0.2)
            for anomaly in anomalies
        )
        
        # Normalize to 0-1 range
        return min(total_weight, 1.0)
    
    def _generate_recommendations(
        self,
        anomalies: List[Dict[str, Any]],
        risk_score: float
    ) -> List[str]:
        """Generate security recommendations based on anomalies."""
        recommendations = []
        
        if risk_score > 0.8:
            recommendations.append("IMMEDIATE: Block further transfers pending review")
        elif risk_score > 0.6:
            recommendations.append("HIGH PRIORITY: Flag account for manual review")
        
        # Specific recommendations
        anomaly_types = {a["type"] for a in anomalies}
        
        if "excessive_amount" in anomaly_types:
            recommendations.append("Review large transfer justification")
        
        if "high_velocity" in anomaly_types:
            recommendations.append("Implement transfer rate limiting")
        
        if "suspicious_target_diversity" in anomaly_types:
            recommendations.append("Investigate potential account compromise")
        
        if "rapid_fire_transfers" in anomaly_types:
            recommendations.append("Possible automation attack - enforce CAPTCHA")
        
        return recommendations
    
    async def _trigger_alerts(self, monitoring_result: Dict[str, Any]):
        """Trigger registered alert callbacks."""
        self.stats["alerts_triggered"] += 1
        
        for callback in self.alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(monitoring_result)
                else:
                    callback(monitoring_result)
            except Exception as e:
                logger.error(f"Alert callback failed: {str(e)}")
    
    def register_alert_callback(self, callback: callable):
        """Register a callback for security alerts."""
        self.alert_callbacks.append(callback)
    
    async def get_agent_risk_profile(
        self,
        db: AsyncSession,
        agent_id: str
    ) -> Dict[str, Any]:
        """
        Get comprehensive risk profile for an agent.
        
        Returns:
            Dict containing risk metrics and history
        """
        pattern = self.agent_patterns.get(agent_id)
        
        if not pattern or not pattern.amounts:
            return {
                "agent_id": agent_id,
                "risk_level": "unknown",
                "transfer_count": 0,
                "average_amount": "0",
                "velocity": 0.0,
                "unique_targets": 0
            }
        
        # Get recent anomalies
        recent_anomalies = await self._get_recent_anomalies(db, agent_id)
        
        # Calculate risk level
        risk_level = "low"
        if len(recent_anomalies) > 5:
            risk_level = "critical"
        elif len(recent_anomalies) > 2:
            risk_level = "high"
        elif len(recent_anomalies) > 0:
            risk_level = "medium"
        
        return {
            "agent_id": agent_id,
            "risk_level": risk_level,
            "transfer_count": len(pattern.amounts),
            "average_amount": str(pattern.get_average_amount()),
            "velocity": pattern.get_velocity(),
            "unique_targets": pattern.get_unique_targets(),
            "recent_anomalies": recent_anomalies,
            "monitoring_stats": {
                "window_size": pattern.amounts.maxlen,
                "oldest_transfer": pattern.timestamps[0].isoformat() if pattern.timestamps else None,
                "newest_transfer": pattern.timestamps[-1].isoformat() if pattern.timestamps else None
            }
        }
    
    async def _get_recent_anomalies(
        self,
        db: AsyncSession,
        agent_id: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Get recent anomalies for an agent."""
        # In production, this would query an anomaly log table
        # For now, return empty list
        return []
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        return {
            **self.stats,
            "monitored_agents": len(self.agent_patterns),
            "thresholds": self.thresholds
        }
    
    def update_threshold(self, threshold_name: str, value: Any):
        """Update an anomaly detection threshold."""
        if threshold_name in self.thresholds:
            old_value = self.thresholds[threshold_name]
            self.thresholds[threshold_name] = value
            logger.info(
                f"Updated threshold {threshold_name} from {old_value} to {value}"
            )
        else:
            logger.warning(f"Unknown threshold: {threshold_name}")


# Global monitor instance (initialized per TEG)
cross_teg_security_monitor: Optional[CrossTEGSecurityMonitor] = None


def initialize_security_monitor(teg_id: str) -> CrossTEGSecurityMonitor:
    """Initialize the security monitor for this TEG."""
    global cross_teg_security_monitor
    cross_teg_security_monitor = CrossTEGSecurityMonitor(teg_id)
    return cross_teg_security_monitor


async def default_alert_handler(alert: Dict[str, Any]):
    """Default alert handler that logs to security logger."""
    logger.critical(
        f"SECURITY ALERT: Transfer {alert['transfer_id']} "
        f"detected {len(alert['anomalies'])} anomalies, "
        f"risk score: {alert['risk_score']}"
    )
    
    for anomaly in alert['anomalies']:
        logger.warning(
            f"  - {anomaly['type']} ({anomaly['severity']}): {anomaly['details']}"
        )
