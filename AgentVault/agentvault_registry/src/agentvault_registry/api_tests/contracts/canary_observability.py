"""Canary worker observability contracts (AAA+ Phase II-B, 2026-05-21).

Status + events endpoints for the canary subsystem reactors:
  - canary_judge: 30s judge sweep
  - canary_rebalancer: agent refuel
  - canary_ironhand: mTLS canary
  - canary core: results + path config
"""
from __future__ import annotations

from ..core.contract import Endpoint


# ── Core canary status ───────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/canary/status", auth="developer", category="admin_canary", idempotent=True)
class CanaryStatus:
    """Live canary path scoreboard."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/canary/results", auth="developer", category="admin_canary", idempotent=True)
class CanaryResults:
    """Recent canary test_result rows."""
    expected_status = 200


# ── Worker observability ─────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/canary-judge/status", auth="developer", category="admin_canary_judge", idempotent=True)
class CanaryJudgeStatus:
    """Judge worker snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/canary-judge/events", auth="developer", category="admin_canary_judge", idempotent=True)
class CanaryJudgeEvents:
    """Judge action audit log."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/canary-rebalancer/status", auth="developer", category="admin_canary_rebalancer", idempotent=True)
class CanaryRebalancerStatus:
    """Rebalancer worker snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/canary-rebalancer/events", auth="developer", category="admin_canary_rebalancer", idempotent=True)
class CanaryRebalancerEvents:
    """Rebalancer action audit log."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/canary-ironhand/status", auth="developer", category="admin_canary_ironhand", idempotent=True)
class CanaryIronhandStatus:
    """IRONHAND canary status."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/canary-ironhand/events", auth="developer", category="admin_canary_ironhand", idempotent=True)
class CanaryIronhandEvents:
    """IRONHAND canary audit log."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/canary-ironhand/svids", auth="developer", category="admin_canary_ironhand", idempotent=True)
class CanaryIronhandSVIDs:
    """SVID inventory for IRONHAND canary agents."""
    expected_status = 200


# ── Other worker observability ───────────────────────────────────────────
@Endpoint(method="GET", path="/admin/cross-teg-sweeper/status", auth="developer", category="admin_cross_teg_sweeper", idempotent=True)
class CrossTegSweeperStatus:
    """Cross-TEG sweeper worker snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/cross-teg-sweeper/events", auth="developer", category="admin_cross_teg_sweeper", idempotent=True)
class CrossTegSweeperEvents:
    """Cross-TEG sweeper compensation audit."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/collusion/status", auth="developer", category="admin_collusion_detector", idempotent=True)
class CollusionStatus:
    """Collusion detector worker snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/collusion/rings", auth="developer", category="admin_collusion_detector", idempotent=True)
class CollusionRings:
    """Detected collusion rings."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/saga-timeout/status", auth="developer", category="admin_saga_timeout", idempotent=True)
class SagaTimeoutStatus:
    """Saga timeout checker status."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/saga-timeout/events", auth="developer", category="admin_saga_timeout", idempotent=True)
class SagaTimeoutEvents:
    """Saga timeout audit."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/supply-auditor/status", auth="developer", category="admin_supply_auditor", idempotent=True)
class SupplyAuditorStatus:
    """Supply auditor worker status."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/supply-auditor/events", auth="developer", category="admin_supply_auditor", idempotent=True)
class SupplyAuditorEvents:
    """Supply auditor breach audit log."""
    expected_status = 200
