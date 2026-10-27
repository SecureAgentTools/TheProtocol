"""
Exchange (AGORA) Category Tests — §V0064, 2026-06-12.

Covers the `exchange` OpenAPI tag (auto-cataloged by the api-tester):
public market-data reads (listings/book/trades/candles/top-traders),
agent-JWT order/portfolio/IPO surfaces, and developer-JWT listing admin.

NB: on registries where the venue ships dark (EXCHANGE_ENABLED unset),
these endpoints 404/503 by design — the runner's expected-failure
classification handles that, same as other env-gated categories.
"""

import logging
from typing import Optional

from ...enhanced_base import EnhancedAPITestBase

logger = logging.getLogger(__name__)


class TestExchange(EnhancedAPITestBase):
    """Tests for AGORA exchange endpoints"""

    CATEGORY_NAME = "exchange"

    # Public market-data reads first — they prove the venue is up before
    # any order-path endpoint is attempted.
    # §AGORAWORDS Phase 5 (2026-09-22): the documented names (the schema lists /agora since V0419; /exchange is hidden)
    PRIORITY_ENDPOINTS = [
        '/agora/listings',
        '/agora/top-traders',
        '/agora/orders/mine',
        '/agora/portfolio',
    ]

    # Order placement runs the CLOB matcher under an advisory lock —
    # keep the category gentle.
    RATE_LIMIT = 60

    # Candle aggregation + settlement-adjacent reads can be slow under load.
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
