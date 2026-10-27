"""
Federation Sync Category Tests

Tests for federation_sync endpoints in the AgentVault Registry API.
These endpoints require mTLS authentication which is configured in the docker-compose.
"""

import logging
from typing import List, Optional, Dict, Any

from ...enhanced_base import EnhancedAPITestBase

logger = logging.getLogger(__name__)


class TestFederationSync(EnhancedAPITestBase):
    """
    Tests for federation_sync endpoints
    
    These endpoints require mTLS authentication. Since mTLS is working via
    docker-compose configuration with API key exchange, we'll use service
    token auth as an alternative for testing.
    """
    
    CATEGORY_NAME = "federation_sync"
    
    # Priority endpoints that should be tested first
    PRIORITY_ENDPOINTS = ['/federation/peers', '/federation/sync-status']
    
    # Rate limit for this category (requests per minute)
    RATE_LIMIT = 100
    
    # Timeout for slow endpoints
    TIMEOUT = 60.0
    
    async def setup(self):
        """Category-specific setup"""
        await super().setup_category(self.CATEGORY_NAME)
        logger.info(f"Setting up {self.CATEGORY_NAME} tests with mTLS support")
    
    async def teardown(self):
        """Category-specific cleanup"""
        logger.info(f"Cleaning up {self.CATEGORY_NAME} tests")
    
    async def test_endpoint(
        self,
        method: str,
        path: str,
        auth_type: str = "none",
        body: Optional[Dict[str, Any]] = None,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        is_form_data: bool = False,
        test_path_override: Optional[str] = None,
        timeout: float = 10.0
    ) -> Dict[str, Any]:
        """
        Override test_endpoint for federation sync mTLS endpoints.
        
        OWL32 Phase 8.17: auth_manager.py now sends X-Federation-Secret +
        X-Federation-SPIFFE-ID headers for auth_type="mtls", which mirrors
        production's federation_auth.py Mode 2 (internal secret). No auth
        override needed — the endpoint's registered auth_type="mtls" flows
        straight through auth_manager and gets accepted by federation_auth.
        """
        mtls_endpoints = [
            "/federation/peers",
            "/federation/agent-cards",
            "/federation/sync-status",
            "/federation/sync-request"
        ]
        
        if path in mtls_endpoints:
            logger.info(f"Testing mTLS endpoint {path} with federation internal-secret auth")
            # Keep auth_type as "mtls" — auth_manager.py now handles it properly
        
        return await super().test_endpoint(
            method=method,
            path=path,
            auth_type=auth_type,
            body=body,
            developer_token=developer_token,
            agent_token=agent_token,
            is_form_data=is_form_data,
            test_path_override=test_path_override,
            timeout=timeout
        )
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test all endpoints in this category"""
        logger.info("Testing federation sync endpoints with mTLS/service auth")
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
