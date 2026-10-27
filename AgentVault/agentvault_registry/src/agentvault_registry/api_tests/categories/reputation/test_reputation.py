"""EigenTrust++ Reputation Category Tests — Phase 2

5 endpoints covering the trust computation pipeline:
  POST /reputation/admin/trigger-computation — force immediate epoch (admin)
  GET  /reputation/computation-status        — last epoch metadata
  GET  /reputation/{did}/trust-score         — GlobalTrustVector for agent
  GET  /reputation/{did}/trust-graph         — LocalTrustScore relationships
  GET  /reputation/{did}/volume-profile      — transaction volume stats

Prerequisite ordering:
  1. trigger-computation runs FIRST to seed GlobalTrustVector rows.
     Without this, trust-score returns 404 for fresh sandbox agents.
     The trigger is async (background task) — computation-status is
     polled immediately after, but may show epoch=null on first call
     if the worker hasn't completed yet. That is acceptable (200+null).
  2. trust-score requires a GlobalTrustVector row. If the epoch hasn't
     completed when the test runs, this may 404. Subsequent runs will pass
     once the background task finishes. Marked as acceptable transient fail.
  3. trust-graph and volume-profile return empty lists/zeros for fresh
     agents — both return 200, never 404.

Auth: developer JWT for all GETs. Admin JWT (is_admin check) for trigger.
     sandbox admin@test.sandbox satisfies both.
"""
import logging
from typing import Optional

from ...base import APITestBase

logger = logging.getLogger(__name__)


class TestReputation(APITestBase):
    CATEGORY_NAME = "reputation"
    PRIORITY_ENDPOINTS = [
        "/reputation/admin/trigger-computation",
        "/reputation/computation-status",
    ]
    RATE_LIMIT = 30
    TIMEOUT = 30.0  # trigger-computation spawns a background task — allow extra time

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
