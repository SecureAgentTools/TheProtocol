"""MCP Health Category Tests

2 no-auth health check endpoints:
  GET /mcp/health       — public MCP server health
  GET /mcp/admin/health — public admin MCP server health

Both return 200 with status/version/tool-count payload.
No authentication required on either endpoint.
These hit the PRODUCTION registry (port 8000), not the sandbox —
the test-endpoint proxy transparently routes to API_TEST_TARGET_URL
for /api/v1/* paths, but /mcp/* endpoints are served by registry-a
directly and are always available regardless of sandbox state.
"""
import logging
from typing import Optional

from ...base import APITestBase

logger = logging.getLogger(__name__)


class TestMcpHealth(APITestBase):
    CATEGORY_NAME = "mcp_health"
    PRIORITY_ENDPOINTS = ["/mcp/health", "/mcp/admin/health"]
    RATE_LIMIT = 60
    TIMEOUT = 60.0

    async def setup(self):
        await super().setup_category(self.CATEGORY_NAME)

    async def teardown(self):
        pass

    async def test_all(self, developer_token: Optional[str] = None, agent_token: Optional[str] = None):
        return await self.test_category_endpoints(
            self.CATEGORY_NAME, developer_token, agent_token, priority_only=False
        )

    async def test_priority(self, developer_token: Optional[str] = None, agent_token: Optional[str] = None):
        return await self.test_category_endpoints(
            self.CATEGORY_NAME, developer_token, agent_token, priority_only=True
        )
