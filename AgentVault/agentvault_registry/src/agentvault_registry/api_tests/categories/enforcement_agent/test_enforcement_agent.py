"""Enforcement Agent Category Tests — TITANIUM VAULT D2 §4.10

4 endpoints covering agent self-service enforcement views:
  GET  /enforcement/my-status          — agent reads own enforcement state
  GET  /fees/current-rate              — public fee rate (developer auth)
  POST /agents/reputation-bond/deposit — lock AVT as reputation bond
  GET  /agents/reputation-bond/status  — maturity progress (prereq: deposit)

Ordering:
  - status + fees (reads) first, then deposit + bond status.
  - deposit must run before bond status so the bond row exists.
  - deposit is idempotent: if bond already exists, returns existing record.

Auth:
  - my-status, deposit, bond/status: agent JWT
  - fees/current-rate: developer JWT (uses get_current_developer)
"""
import logging
from typing import Optional

from ...base import APITestBase

logger = logging.getLogger(__name__)


class TestEnforcementAgent(APITestBase):
    CATEGORY_NAME = "enforcement_agent"
    PRIORITY_ENDPOINTS = [
        "/enforcement/my-status",
        "/fees/current-rate",
    ]
    RATE_LIMIT = 60
    TIMEOUT = 15.0

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
