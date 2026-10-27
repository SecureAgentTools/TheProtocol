"""ANP discovery + Command Center contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/anp/discover", auth="none", category="anp_discovery", idempotent=True)
class ANPDiscover:
    """ANP discovery protocol — public listing."""
    expected_status = 200


@Endpoint(method="POST", path="/anp/discover", auth="none", category="anp_discovery", idempotent=False)
class ANPDiscoverQuery:
    """ANP discovery query."""
    def body(self, ctx):
        return {"query": "test", "limit": 10}
    expected_status = [200, 422]


@Endpoint(method="GET", path="/admin/diagnostics/config/{target_id}", auth="developer", category="command_center", idempotent=True, slow_timeout_sec=60.0)
class DiagnosticsConfig:
    """Command Center: target config snapshot."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/admin/diagnostics/actions", auth="developer", category="command_center", idempotent=True, slow_timeout_sec=60.0)
class DiagnosticsActions:
    """Recent Command Center actions."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/diagnostics/actions/{action_id}", auth="developer", category="command_center", idempotent=True, slow_timeout_sec=60.0)
class DiagnosticsActionDetail:
    """A single Command Center action detail."""
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/diagnostics/run-all", auth="developer", category="command_center", idempotent=True, slow_timeout_sec=60.0)
class DiagnosticsRunAll:
    """Run all applicable checks against one target. §SUITES1018 batch 7: the route takes {"target", "force"}
    (services/diagnostics/schemas.RunAllRequest); the contract sent {"target_id": ...} and passed on the 422. The
    catalog's body names this registry's own target; force stays off, so a check cached within its window answers."""
    def body(self, ctx):
        from ..request_bodies import RequestBodies
        return {**(RequestBodies().get_body("/admin/diagnostics/run-all") or {"target": "registry"}), "force": False}
    expected_status = [200]
