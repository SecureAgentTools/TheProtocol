"""Fiat admin contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/admin/fiat/stats", auth="developer", category="fiat_on_ramp_admin", idempotent=True)
class FiatStats:
    """Admin aggregate stats (volume, conversion, etc.)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/fiat/purchases", auth="developer", category="fiat_on_ramp_admin", idempotent=True)
class AdminFiatPurchases:
    """All fiat purchases (paginated)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/fiat/pricing", auth="developer", category="fiat_on_ramp_admin", idempotent=True)
class AdminFiatPricing:
    """Tier pricing config snapshot."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/fiat/purchases/{purchase_id}",
    auth="developer",
    category="fiat_on_ramp_admin",
)
class AdminFiatPurchaseDetail:
    """A single purchase detail."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Purchase ID placeholder",
        ),
    ]


@Endpoint(method="GET", path="/admin/fiat/flares", auth="developer", category="fiat_on_ramp_admin", idempotent=True)
class AdminFiatFlares:
    """Flare bonuses earned via fiat purchase tiers."""
    expected_status = 200


# ── Flare endpoints ──────────────────────────────────────────────────────
@Endpoint(method="GET", path="/fiat/flare/status", auth="developer", category="fiat_on_ramp", idempotent=True)
class FlareStatus:
    """Caller's flare bonus tier status."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/fiat/flare/agent/{agent_did}",
    auth="developer",
    category="fiat_on_ramp",
)
class FlareForAgent:
    """Flare bonuses earned by a specific agent."""
    expected_status = [200, 404]


@Endpoint(
    method="GET",
    path="/fiat/flare/developer/{developer_id}",
    auth="developer",
    category="fiat_on_ramp",
)
class FlareForDeveloper:
    """Flare bonuses earned by a developer."""
    expected_status = [200, 404]
