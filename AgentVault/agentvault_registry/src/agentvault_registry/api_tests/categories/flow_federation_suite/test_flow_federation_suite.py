"""Flow wrapper that invokes the federation_suite runner.

Registered as flow_federation_suite_complete (and per-category variants) in
routers/admin_api_test.py:flow_map. Sandbox-only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.federation_suite.runner import (
    run_federation_suite,
)


class TestFlowFederationSuite(APITestBase):
    CATEGORY_NAME = "flow_federation_suite"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_all(self, developer_token=None, agent_token=None):
        std = await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False,
        )
        std["flow_tests"] = await self.test_federation_suite_flow(developer_token)
        return std

    async def test_federation_suite_flow(self, developer_token: str = None) -> Dict[str, Any]:
        """Run ALL registered federation tests."""
        result = await run_federation_suite()
        self.flow_values = result.get("flow_values", {})
        return result

    async def test_federation_suite_smoke_flow(self, developer_token: str = None) -> Dict[str, Any]:
        """Run smoke category only — verifies rig + substrate before deep tests."""
        result = await run_federation_suite(category_filter=["smoke"])
        self.flow_values = result.get("flow_values", {})
        return result

    async def test_federation_suite_critical_flow(self, developer_token: str = None) -> Dict[str, Any]:
        """Run critical-severity tests only."""
        result = await run_federation_suite(severity_filter=["critical"])
        self.flow_values = result.get("flow_values", {})
        return result
