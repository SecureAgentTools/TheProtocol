"""Enhanced Tokenomics test category for API testing framework"""

import logging
from typing import List, Optional, Dict, Any

from agentvault_registry.api_tests.base import APITestBase

logger = logging.getLogger(__name__)


class TestEnhancedTokenomics(APITestBase):
    """Test category for enhanced tokenomics endpoints"""
    CATEGORY_NAME = "enhanced_tokenomics"
    PRIORITY_ENDPOINTS = ['/tokenomics/treasury']
    RATE_LIMIT = 60
    TIMEOUT = 15.0
    
    async def setup(self):
        """Setup for enhanced tokenomics testing - OWL32 FIX"""
        await self.setup_category(self.CATEGORY_NAME)
        logger.info("Enhanced tokenomics test setup complete")
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test all endpoints - OWL32 FIX: return standard format with 'summary' key"""
        return await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False
        )
    
    async def test_priority(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test only priority endpoints"""
        return await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=True
        )
    
    def get_endpoints(self) -> List[Dict[str, Any]]:
        """Define all enhanced tokenomics endpoints"""
        return [
            {
                "method": "GET",
                "path": "/tokenomics/rewards/{agent_did}",
                "description": "Get pending rewards",
                "auth": "agent",
                "category": "enhanced_tokenomics"
            },
            {
                "method": "GET",
                "path": "/tokenomics/transactions/{agent_did}",
                "description": "Get transaction history",
                "auth": "agent",
                "category": "enhanced_tokenomics"
            },
            {
                "method": "GET",
                "path": "/tokenomics/treasury",
                "description": "Get treasury information",
                "auth": "agent",
                "category": "enhanced_tokenomics"
            }
        ]
    
    async def setup_prerequisites(self, developer_token: str = None, agent_token: str = None) -> Dict[str, Any]:
        """Setup any prerequisites for enhanced tokenomics tests"""
        prerequisites = {}
        
        # Get current agent DID for personalized endpoints
        if agent_token:
            try:
                result = await self.test_endpoint(
                    method="GET",
                    path="/agents/me",
                    auth_type="agent",
                    agent_token=agent_token
                )
                
                if result.get("healthy") and result.get("responseData"):
                    agent_info = result["responseData"]
                    prerequisites["agent_did"] = agent_info.get("did")
                    self.logger.info(f"Got agent DID for tokenomics tests: {prerequisites['agent_did']}")
            except Exception as e:
                self.logger.error(f"Failed to get agent DID: {e}")
        
        return prerequisites
    
    async def test_get_pending_rewards(self, agent_token: str = None, agent_did: str = None) -> Dict[str, Any]:
        """Test getting pending rewards for an agent"""
        if not agent_did:
            agent_did = "test-agent-123"  # Fallback
        
        path = f"/tokenomics/rewards/{agent_did}"
        
        result = await self.test_endpoint(
            method="GET",
            path=path,
            auth_type="agent",
            agent_token=agent_token
        )
        
        # Additional validation
        if result.get("healthy") and result.get("responseData"):
            data = result["responseData"]
            
            # Validate response structure
            if "pending_rewards" in data:
                self.logger.info(f"Pending rewards: {data['pending_rewards']} AVT")
                
                # Check reward sources
                sources = data.get("reward_sources", [])
                if sources:
                    self.logger.info(f"Found {len(sources)} reward sources")
                    for source in sources[:3]:
                        self.logger.info(f"  - {source.get('type')}: {source.get('amount')} AVT")
            else:
                result["healthy"] = False
                result["error"] = "Missing pending_rewards field"
        
        return result
    
    async def test_get_transaction_history(self, agent_token: str = None, agent_did: str = None) -> Dict[str, Any]:
        """Test getting transaction history for an agent"""
        if not agent_did:
            agent_did = "test-agent-123"  # Fallback
        
        path = f"/tokenomics/transactions/{agent_did}"
        
        result = await self.test_endpoint(
            method="GET",
            path=path,
            auth_type="agent",
            agent_token=agent_token,
            params={"limit": 10}  # Add query parameter
        )
        
        # Additional validation
        if result.get("healthy") and result.get("responseData"):
            data = result["responseData"]
            
            # Validate response structure
            if "transactions" in data and isinstance(data["transactions"], list):
                tx_count = len(data["transactions"])
                self.logger.info(f"Found {tx_count} transactions in history")
                
                if tx_count > 0:
                    # Log first transaction as example
                    tx = data["transactions"][0]
                    self.logger.info(f"Latest transaction: {tx.get('transaction_type')} of {tx.get('amount')} AVT")
            else:
                result["healthy"] = False
                result["error"] = "Missing or invalid transactions field"
        
        return result
    
    async def test_get_treasury_info(self, agent_token: str = None) -> Dict[str, Any]:
        """Test getting treasury information"""
        result = await self.test_endpoint(
            method="GET",
            path="/tokenomics/treasury",
            auth_type="agent",
            agent_token=agent_token
        )
        
        # Additional validation
        if result.get("healthy") and result.get("responseData"):
            data = result["responseData"]
            
            # Validate all required fields are present
            required_fields = [
                "total_supply", "circulating_supply", "treasury_balance",
                "locked_supply", "burned_supply", "reward_pool"
            ]
            
            missing_fields = [f for f in required_fields if f not in data]
            
            if missing_fields:
                result["healthy"] = False
                result["error"] = f"Missing treasury fields: {missing_fields}"
            else:
                self.logger.info(f"Treasury - Total supply: {data['total_supply']} AVT")
                self.logger.info(f"Treasury - Circulating: {data['circulating_supply']} AVT")
                self.logger.info(f"Treasury - Locked: {data['locked_supply']} AVT")
        
        return result
    
    async def run_all_tests(self, developer_token: str = None, agent_token: str = None) -> Dict[str, Any]:
        """Run all enhanced tokenomics tests"""
        # Setup prerequisites
        prerequisites = await self.setup_prerequisites(developer_token, agent_token)
        agent_did = prerequisites.get("agent_did")
        
        # Run individual tests
        results = []
        
        # Test pending rewards
        result = await self.test_get_pending_rewards(agent_token, agent_did)
        results.append(result)
        
        # Test transaction history
        result = await self.test_get_transaction_history(agent_token, agent_did)
        results.append(result)
        
        # Test treasury info
        result = await self.test_get_treasury_info(agent_token)
        results.append(result)
        
        # Calculate summary
        total = len(results)
        healthy = sum(1 for r in results if r.get("healthy", False))
        
        return {
            "category": self.CATEGORY_NAME,
            "description": "Enhanced tokenomics endpoints",
            "total_endpoints": total,
            "healthy_endpoints": healthy,
            "success_rate": (healthy / total * 100) if total > 0 else 0,
            "results": results,
            "prerequisites": prerequisites
        }
