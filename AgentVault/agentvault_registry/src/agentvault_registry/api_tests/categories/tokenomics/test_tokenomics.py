"""
Tokenomics Category Tests - OWL32

Tests for tokenomics proxy endpoints (rewards, transactions, treasury).
These endpoints proxy through to the TEG Layer.
"""

import logging
from typing import Optional, Dict, Any

from agentvault_registry.api_tests.base import APITestBase

logger = logging.getLogger(__name__)


class TestTokenomics(APITestBase):
    """
    Test suite for tokenomics proxy endpoints.
    
    Endpoints:
    - GET /tokenomics/rewards/{agent_did} - Get pending rewards
    - GET /tokenomics/transactions/{agent_did} - Get transaction history
    - GET /tokenomics/treasury - Get treasury information
    """
    
    CATEGORY_NAME = "tokenomics"
    
    PRIORITY_ENDPOINTS = [
        "/tokenomics/treasury",
    ]
    
    async def setup(self):
        """Setup for tokenomics testing"""
        await self.setup_category(self.CATEGORY_NAME)
        logger.info("Tokenomics test setup complete")
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test all endpoints - returns standard format with 'summary' key"""
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
