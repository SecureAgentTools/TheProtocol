"""Admin platform slow endpoints (AAA+ Phase IV-A, 2026-05-21).

These endpoints occasionally timeout under load — EF stamp them when status is None or 504.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


_SLOW_ADMIN_REASON = "Aggregation endpoint occasionally exceeds 10s budget under prod load"


@Endpoint(method="GET", path="/admin/combined-health", auth="developer", category="admin_platform", idempotent=True, slow_timeout_sec=60.0)
class CombinedHealth:
    """Multi-service health probe (slow under load).

    `routers/admin_health.py:get_combined_health` calls `get_docker_stats()`
    internally which iterates 46+ containers serially via Docker daemon. Wall-clock
    is ~90s in worst case. Until parallelized (Batch 2), transport ReadTimeout
    bubbles up here as `status=None` after the slow_timeout_sec gate.
    """
    expected_status = [200, 504]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (504, 503),
            reason=_SLOW_ADMIN_REASON,
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status is None,
            reason=_SLOW_ADMIN_REASON + " (transport ReadTimeout at slow_timeout_sec=60s)",
        ),
    ]


@Endpoint(method="GET", path="/admin/docker-stats", auth="developer", category="admin_platform", idempotent=True, slow_timeout_sec=60.0)
class DockerStats:
    """Container stats (slow + flaky).

    `routers/admin_health.py:_collect_docker_stats_sync` iterates ~46 agentvault
    containers serially calling `container.stats(stream=False)` (~2s each via
    Docker daemon) → 90s wall-clock. Will be parallelized in Batch 2; until
    then, transport ReadTimeout is the expected failure mode.
    """
    expected_status = [200, 500, 503, 504]
    failures = [
        FailureMode.known_bug(
            condition=lambda r: r.status in (500, 504),
            reason="Docker daemon occasionally hangs on stats query",
            bug_id="DOCKER-DAEMON-FLAKE",
        ),
        FailureMode.known_bug(
            condition=lambda r: r.status is None,
            reason="Docker daemon serial loop exceeds slow_timeout_sec=60s (parallelization queued)",
            bug_id="DOCKER-DAEMON-FLAKE",
        ),
    ]
