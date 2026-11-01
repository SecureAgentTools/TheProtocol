"""§MCPTEST30 (V0652, agentvault2-d3, 2026-11-01): composeBroadcast's emission is the direct notice the run sends.

Since V0645 every broadcast the MCP tester composes is a direct notice to the run's own developer, and the route audits a
developer-targeted notice as AdminDirectNoticeSent (routers/admin_broadcast.DIRECT_NOTICE_EVENT), never AdminBroadcastSent.
routers/mcp_tester._EMIT_MAP still named AdminBroadcastSent, so the row's event_emission axis read "REAL MISS" on every
run (V0650's and V0651's pair proofs: "AdminBroadcastSent still absent from the EventStore 25s after the sweep"). RED
before: the first test reads ['AdminBroadcastSent'].
"""
from __future__ import annotations

import inspect

from agentvault_registry.api_tests.contracts import earned_ad_platform, mcp_admin_lifecycles
from agentvault_registry.routers import admin_broadcast as ab
from agentvault_registry.routers import mcp_tester as mt


def test_compose_broadcast_expects_the_direct_notice():
    assert mt._EMIT_MAP["composeBroadcast"] == [ab.DIRECT_NOTICE_EVENT]


def test_every_broadcast_the_run_composes_names_its_addressee():
    # the expectation holds only while each composeBroadcast the tester sends is addressed to one developer
    sweep = inspect.getsource(mcp_admin_lifecycles)
    i = sweep.index('("theprotocol_composeBroadcast", {')
    assert '"target_developer_id": own_dev' in sweep[i:i + 300]
    assert '"target_developer_id": own' in inspect.getsource(earned_ad_platform._broadcast)
