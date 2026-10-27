"""OAuth Federation Category Tests - RFC 8693/7662 Cross-Registry Auth"""
import logging
from typing import Optional
from ...base import APITestBase

logger = logging.getLogger(__name__)

class TestOauthFederation(APITestBase):
    CATEGORY_NAME = "oauth_federation"
    PRIORITY_ENDPOINTS = ['/oauth/.well-known/jwks.json', '/oauth/federation/status']
    RATE_LIMIT = 60
    TIMEOUT = 60.0

    async def setup(self):
        await super().setup_category(self.CATEGORY_NAME)

    async def teardown(self):
        pass

    async def test_all(self, developer_token: Optional[str] = None, agent_token: Optional[str] = None):
        return await self.test_category_endpoints(self.CATEGORY_NAME, developer_token, agent_token, priority_only=False)

    async def test_priority(self, developer_token: Optional[str] = None, agent_token: Optional[str] = None):
        return await self.test_category_endpoints(self.CATEGORY_NAME, developer_token, agent_token, priority_only=True)
