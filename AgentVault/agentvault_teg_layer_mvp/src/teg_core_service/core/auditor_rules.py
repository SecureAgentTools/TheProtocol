"""Algorithmic Auditor Rules Module

This module implements automated rule checking for the TEG Layer MVP.
It analyzes AVTP transaction logs and other data to detect anomalies and violations.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..database.models import AVTPTransactionSummaryLog, AuditorFlagLog
from ..api.v1.schemas import AuditorFlagLogCreateSchema
from .config import get_settings, AuditorRuleCodes

logger = logging.getLogger(__name__)


class AuditorRules:
    """Implements automated auditing rules"""
    
    def __init__(self):
        self.settings = get_settings()
    
    def check_extreme_price_anomaly(self, db_session: Session) -> List[AuditorFlagLogCreateSchema]:
        """Check for extreme price anomalies in AVTP transactions
        
        This rule detects when an agent's latest price for a service deviates
        significantly from their historical average.
        
        Args:
            db_session: Database session
            
        Returns:
            List of potential flags to be saved
        """
        flags = []
        
        try:
            # Calculate lookback timestamp
            lookback_timestamp = datetime.now(timezone.utc) - timedelta(
                days=self.settings.extreme_price_anomaly_lookback_days
            )
            
            # Get all unique agent/service combinations with sufficient history
            agent_service_pairs = db_session.query(
                AVTPTransactionSummaryLog.agent_did,
                AVTPTransactionSummaryLog.service_identifier
            ).filter(
                AVTPTransactionSummaryLog.timestamp >= lookback_timestamp
            ).group_by(
                AVTPTransactionSummaryLog.agent_did,
                AVTPTransactionSummaryLog.service_identifier
            ).having(
                func.count(AVTPTransactionSummaryLog.avtp_transaction_id) >= 
                self.settings.extreme_price_anomaly_min_tx_count_for_baseline
            ).all()
            
            # Check each agent/service pair
            for agent_did, service_identifier in agent_service_pairs:
                # Get historical transactions for this pair
                historical_txns = db_session.query(AVTPTransactionSummaryLog).filter(
                    and_(
                        AVTPTransactionSummaryLog.agent_did == agent_did,
                        AVTPTransactionSummaryLog.service_identifier == service_identifier,
                        AVTPTransactionSummaryLog.timestamp >= lookback_timestamp
                    )
                ).order_by(AVTPTransactionSummaryLog.timestamp.desc()).all()
                
                if not historical_txns:
                    continue
                
                # Get latest transaction
                latest_txn = historical_txns[0]
                latest_price = float(latest_txn.price_avt)
                
                # Calculate historical average (excluding the latest)
                if len(historical_txns) > 1:
                    historical_prices = [float(t.price_avt) for t in historical_txns[1:]]
                    avg_price = sum(historical_prices) / len(historical_prices)
                    
                    # Check for anomaly
                    if latest_price > (avg_price * self.settings.extreme_price_anomaly_threshold_factor):
                        # Check if we already have an active flag for this
                        existing_flag = db_session.query(AuditorFlagLog).filter(
                            and_(
                                AuditorFlagLog.flagged_agent_did == agent_did,
                                AuditorFlagLog.rule_violated_code == AuditorRuleCodes.EPA_V1,
                                AuditorFlagLog.related_avtp_transaction_id == latest_txn.avtp_transaction_id,
                                AuditorFlagLog.status.in_([
                                    "auto_flagged_manual_review",
                                    "manual_review_confirmed",
                                    "resolved_action_taken_critical_flag"
                                ])
                            )
                        ).first()
                        
                        if not existing_flag:
                            flag = AuditorFlagLogCreateSchema(
                                flagged_agent_did=agent_did,
                                rule_violated_code=AuditorRuleCodes.EPA_V1,
                                related_avtp_transaction_id=latest_txn.avtp_transaction_id,
                                related_attestation_id=None,
                                flag_reason=(
                                    f"Extreme price anomaly detected. Latest price ({latest_price:.2f} AVT) "
                                    f"is {latest_price/avg_price:.1f}x higher than historical average "
                                    f"({avg_price:.2f} AVT) for service '{service_identifier}'"
                                ),
                                flag_type="PriceAnomaly",  # Add the missing flag_type
                                severity="high",
                                status="auto_flagged_manual_review",
                                flagged_by="AUDITOR_AUTOMATED_EPA_V1"
                            )
                            flags.append(flag)
                            
                            logger.warning(
                                f"EPA_V1 flag generated for agent {agent_did}: "
                                f"price {latest_price} vs avg {avg_price}"
                            )
            
            logger.info(f"Extreme price anomaly check completed. Generated {len(flags)} flags.")
            return flags
            
        except Exception as e:
            logger.error(f"Error in extreme price anomaly check: {e}")
            return []
    
    def check_basic_price_sync_collusion(self, db_session: Session) -> List[AuditorFlagLogCreateSchema]:
        """Check for basic price synchronization that might indicate collusion
        
        This rule detects when multiple agents have suspiciously similar prices
        for the same service within a time window.
        
        Args:
            db_session: Database session
            
        Returns:
            List of potential flags to be saved
        """
        flags = []
        
        try:
            # Calculate lookback timestamp
            lookback_timestamp = datetime.now(timezone.utc) - timedelta(
                hours=self.settings.price_sync_lookback_hours
            )
            
            # Get all recent transactions grouped by service
            recent_txns = db_session.query(AVTPTransactionSummaryLog).filter(
                AVTPTransactionSummaryLog.timestamp >= lookback_timestamp
            ).all()
            
            logger.info(f"Found {len(recent_txns)} recent transactions since {lookback_timestamp}")
            
            # Group by service_identifier
            service_groups = defaultdict(list)
            for txn in recent_txns:
                service_groups[txn.service_identifier].append(txn)
            
            # Check each service for price synchronization
            for service_id, txns in service_groups.items():
                # Group by agent and get their latest prices
                agent_prices = {}
                agent_tx_counts = defaultdict(int)
                
                for txn in txns:
                    agent_tx_counts[txn.agent_did] += 1
                    # Keep the latest price for each agent
                    if txn.agent_did not in agent_prices or txn.timestamp > agent_prices[txn.agent_did]['timestamp']:
                        agent_prices[txn.agent_did] = {
                            'price': float(txn.price_avt),
                            'timestamp': txn.timestamp,
                            'tx_id': txn.avtp_transaction_id
                        }
                
                # Filter agents with sufficient transactions
                qualified_agents = [
                    agent_did for agent_did, count in agent_tx_counts.items()
                    if count >= self.settings.price_sync_min_transactions_per_agent
                ]
                
                logger.info(f"Service {service_id}: {len(qualified_agents)} qualified agents from {len(agent_tx_counts)} total agents")
                logger.info(f"Agent transaction counts: {dict(agent_tx_counts)}")
                
                # Need at least the minimum number of agents
                if len(qualified_agents) < self.settings.price_sync_min_agents_involved:
                    continue
                
                # Check for price synchronization among qualified agents
                # Use a graph-based approach to find connected components of similar prices
                
                # Build adjacency list of agents with similar prices
                price_connections = defaultdict(set)
                
                # Log the prices for debugging
                logger.info(f"Agent prices: {[(agent, agent_prices[agent]['price']) for agent in qualified_agents]}")
                logger.info(f"Price sync threshold: {self.settings.price_sync_threshold_percentage}%")
                
                # Build connections between agents with similar prices
                for i, agent1 in enumerate(qualified_agents):
                    price1 = agent_prices[agent1]['price']
                    for j, agent2 in enumerate(qualified_agents):
                        if i >= j:  # Skip self and already processed pairs
                            continue
                        price2 = agent_prices[agent2]['price']
                        
                        # Calculate percentage difference
                        if price1 > 0:
                            diff_pct = abs(price2 - price1) / price1 * 100
                            if diff_pct <= self.settings.price_sync_threshold_percentage:
                                price_connections[agent1].add(agent2)
                                price_connections[agent2].add(agent1)
                                logger.debug(f"Connected {agent1} and {agent2} (diff={diff_pct:.4f}%)")
                
                # Find connected components using DFS
                visited = set()
                price_groups = []
                
                def dfs(agent, component):
                    visited.add(agent)
                    component.append(agent)
                    for neighbor in price_connections[agent]:
                        if neighbor not in visited:
                            dfs(neighbor, component)
                
                for agent in qualified_agents:
                    if agent not in visited:
                        component = []
                        dfs(agent, component)
                        
                        # Only keep groups with enough agents
                        logger.info(f"Price cluster found: {len(component)} agents - {component}")
                        if len(component) >= self.settings.price_sync_min_agents_involved:
                            avg_price = sum(agent_prices[a]['price'] for a in component) / len(component)
                            price_groups.append((avg_price, component))
                
                # Check if any price group has enough agents
                logger.info(f"Price groups for {service_id}: {[(price, len(agents)) for price, agents in price_groups]}")
                
                for group_price, group_agents in price_groups:
                        # Generate a flag for potential collusion
                        implicated_agents = ", ".join(group_agents[:5])  # List first 5
                        if len(group_agents) > 5:
                            implicated_agents += f" and {len(group_agents) - 5} others"
                        
                        flag_reason = (
                            f"Potential price synchronization detected for service '{service_id}'. "
                            f"{len(group_agents)} agents have prices within "
                            f"{self.settings.price_sync_threshold_percentage}% of {group_price:.2f} AVT. "
                            f"Implicated agents: {implicated_agents}"
                        )
                        
                        # Create a flag for each implicated agent
                        for agent_did in group_agents:
                            # Check if we already have an active flag for this agent/rule/service
                            existing_flag = db_session.query(AuditorFlagLog).filter(
                                and_(
                                    AuditorFlagLog.flagged_agent_did == agent_did,
                                    AuditorFlagLog.rule_violated_code == AuditorRuleCodes.BCD_PSYNC_V1,
                                    AuditorFlagLog.flag_reason.contains(service_id),
                                    AuditorFlagLog.status.in_([
                                        "auto_flagged_manual_review",
                                        "manual_review_confirmed",
                                        "resolved_action_taken_critical_flag"
                                    ])
                                )
                            ).first()
                            
                            if not existing_flag:
                                flag = AuditorFlagLogCreateSchema(
                                    flagged_agent_did=agent_did,
                                    rule_violated_code=AuditorRuleCodes.BCD_PSYNC_V1,
                                    related_avtp_transaction_id=agent_prices[agent_did]['tx_id'],
                                    related_attestation_id=None,
                                    flag_reason=flag_reason,
                                    flag_type="PriceCollusion",  # Add the missing flag_type
                                    severity="high",
                                    status="auto_flagged_manual_review",
                                    flagged_by="AUDITOR_AUTOMATED_BCD_PSYNC_V1"
                                )
                                flags.append(flag)
                        
                        logger.warning(
                            f"BCD_PSYNC_V1 flag generated for {len(group_agents)} agents "
                            f"with synchronized prices around {group_price:.2f} AVT for service '{service_id}'"
                        )
            
            logger.info(f"Basic price sync collusion check completed. Generated {len(flags)} flags.")
            return flags
            
        except Exception as e:
            logger.error(f"Error in basic price sync collusion check: {e}")
            return []
    
    def run_all_rules(self, db_session: Session) -> Dict[str, List[AuditorFlagLogCreateSchema]]:
        """Run all automated auditor rules
        
        Args:
            db_session: Database session
            
        Returns:
            Dictionary mapping rule codes to lists of generated flags
        """
        results = {}
        
        # Run extreme price anomaly check
        epa_flags = self.check_extreme_price_anomaly(db_session)
        if epa_flags:
            results[AuditorRuleCodes.EPA_V1] = epa_flags
        
        # Run basic collusion check (placeholder for now)
        collusion_flags = self.check_basic_price_sync_collusion(db_session)
        if collusion_flags:
            results[AuditorRuleCodes.BCD_PSYNC_V1] = collusion_flags
        
        return results


# Singleton instance
_auditor_rules: Optional[AuditorRules] = None


def get_auditor_rules() -> AuditorRules:
    """Get singleton auditor rules instance"""
    global _auditor_rules
    if _auditor_rules is None:
        _auditor_rules = AuditorRules()
    return _auditor_rules
