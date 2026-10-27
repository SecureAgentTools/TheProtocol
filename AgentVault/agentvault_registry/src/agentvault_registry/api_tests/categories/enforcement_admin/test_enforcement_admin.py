"""Enforcement Admin Category Tests — TITANIUM VAULT D2 §4.9

14 endpoints covering the full admin enforcement lifecycle:
  policy reads → policy update → agent status → rewards pause/resume
  → record offense → pending list/reject/approve
  → slash preview (dry-run) → slash execute
  → suspend → reinstate

Ordering is intentional:
  - Reads first (safe), destructive writes last.
  - Suspend is immediately followed by Reinstate so the sandbox agent
    is always restored before the session ends.
  - Slash amount kept minimal (10 AVT) to preserve sandbox agent stake.

Auth: developer (sandbox admin@test.sandbox — is_admin=True).

Note on pending/{action_id}/approve+reject:
  These depend on a pending enforcement action existing in the DB.
  record-offense creates an action, but the enforcement engine may
  auto-execute it (status → executed) rather than leave it pending.
  If no pending action exists, these two endpoints will 404 — that is
  correct behaviour, not a test framework failure.
"""
import logging
from typing import Optional

from ...base import APITestBase

logger = logging.getLogger(__name__)


class TestEnforcementAdmin(APITestBase):
    CATEGORY_NAME = "enforcement_admin"
    PRIORITY_ENDPOINTS = [
        "/admin/enforcement/policy/defaults",
        "/admin/enforcement/policy",
        "/admin/enforcement/agents/{agent_did}/status",
    ]
    RATE_LIMIT = 60
    TIMEOUT = 20.0

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
