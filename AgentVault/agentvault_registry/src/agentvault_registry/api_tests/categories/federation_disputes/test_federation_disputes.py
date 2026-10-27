"""Federation Disputes Category Tests - OWL25 Cross-Registry Settlement"""
import logging
from typing import Optional
from ...base import APITestBase

logger = logging.getLogger(__name__)

class TestFederationDisputes(APITestBase):
    CATEGORY_NAME = "federation_disputes"
    PRIORITY_ENDPOINTS = ['/federation/disputes/settlements', '/federation/disputes/peer-slash-config']
    RATE_LIMIT = 60
    TIMEOUT = 15.0

    async def setup(self):
        await super().setup_category(self.CATEGORY_NAME)

    async def teardown(self):
        pass

    async def test_all(self, developer_token: Optional[str] = None, agent_token: Optional[str] = None):
        return await self.test_category_endpoints(self.CATEGORY_NAME, developer_token, agent_token, priority_only=False)

    async def test_priority(self, developer_token: Optional[str] = None, agent_token: Optional[str] = None):
        return await self.test_category_endpoints(self.CATEGORY_NAME, developer_token, agent_token, priority_only=True)
