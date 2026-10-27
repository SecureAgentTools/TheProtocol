"""
Batch Implementation Category Tests

Tests for batch_implementation endpoints in the AgentVault Registry API.
"""

import logging
from typing import List, Optional

from ...base import APITestBase

logger = logging.getLogger(__name__)


class TestBatchImplementation(APITestBase):
    """Tests for batch_implementation endpoints"""
    
    CATEGORY_NAME = "batch_implementation"
    
    # Priority endpoints that should be tested first
    PRIORITY_ENDPOINTS = ['/agents/by-did/{did}', '/developers/webhooks']
    
    # Rate limit for this category (requests per minute)
    RATE_LIMIT = 100
    
    # Timeout for slow endpoints
    TIMEOUT = 60.0
    
    async def setup(self):
        """Category-specific setup"""
        await super().setup_category(self.CATEGORY_NAME)
        logger.info(f"Setting up {self.CATEGORY_NAME} tests")
    
    async def teardown(self):
        """Category-specific cleanup"""
        logger.info(f"Cleaning up {self.CATEGORY_NAME} tests")
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test all endpoints in this category"""
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
        """Test only priority endpoints in this category"""
        if not self.PRIORITY_ENDPOINTS:
            logger.warning(f"No priority endpoints defined for {self.CATEGORY_NAME}")
            return await self.test_all(developer_token, agent_token)
        
        return await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=True
        )
