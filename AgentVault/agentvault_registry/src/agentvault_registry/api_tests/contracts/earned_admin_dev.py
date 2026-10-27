"""§MCPTEST30 (V0636): the admin and developer tools that passed on a refusal alone, earning their success path
(agentvault2-aa; sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md, step 2).

Lifecycles only, on the subjects and row helpers of earned_fixtures. mcp_lifecycles.py extends its LIFECYCLES with
this module's at its end; this module never imports mcp_lifecycles at module level (earned_fixtures.lc())."""
from __future__ import annotations

from typing import Any, Dict, List

from agentvault_registry.api_tests.contracts import (
    earned_ad_agents, earned_ad_developers, earned_ad_devtools, earned_ad_federation, earned_ad_platform,
)

LIFECYCLES: List[Dict[str, Any]] = [
    *earned_ad_agents.LIFECYCLES,      # the admin agent tools on the run's own agents
    *earned_ad_developers.LIFECYCLES,  # the admin developer tools, and the flare tools on the run's own agents
    *earned_ad_platform.LIFECYCLES,    # broadcasts, a bundle report, an emission policy, the API tester, a canary
    *earned_ad_federation.LIFECYCLES,  # fixture peers, an invitation and the compliance mode of the run's own
    *earned_ad_devtools.LIFECYCLES,    # CI/CD, organization invitations, a support review and agent tools
]
