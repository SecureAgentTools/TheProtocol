"""System + utility + websocket contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/health/deep", auth="none", category="system", idempotent=True, slow_timeout_sec=30.0)
class HealthDeep:
    """Deep health probe."""
    expected_status = 200


@Endpoint(method="GET", path="/system/info", auth="none", category="system", idempotent=True)
class SystemInfo:
    """Public system info (version, build, etc.)."""
    expected_status = 200


@Endpoint(method="GET", path="/system/version", auth="none", category="system", idempotent=True)
class SystemVersion:
    """Registry version + build hash."""
    expected_status = 200


@Endpoint(method="GET", path="/utils/timestamp", auth="none", category="utilities", idempotent=True)
class UtilsTimestamp:
    """Server time."""
    expected_status = 200


# Websocket endpoints — connections require WS upgrade, GET on them 404/426
@Endpoint(method="GET", path="/ws/events", auth="none", category="websocket", idempotent=True)
class WsEvents:
    """Public EventStore WS — requires WS upgrade, GET returns 426 or 404."""
    expected_status = [200, 404, 405, 426]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 405, 426),
            reason="WebSocket endpoint — requires WS Upgrade header",
        ),
    ]


@Endpoint(method="GET", path="/ws/agent", auth="agent", category="websocket", idempotent=True)
class WsAgent:
    """Agent WS — same WS upgrade story."""
    expected_status = [200, 404, 405, 426]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 405, 426),
            reason="WebSocket endpoint",
        ),
    ]


@Endpoint(method="GET", path="/ws/developer", auth="developer", category="websocket", idempotent=True)
class WsDeveloper:
    """Developer WS."""
    expected_status = [200, 404, 405, 426]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 405, 426),
            reason="WebSocket endpoint",
        ),
    ]
