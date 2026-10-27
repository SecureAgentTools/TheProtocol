"""Admin broadcast mutation contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/admin/broadcast-templates", auth="developer", category="admin_broadcasts", idempotent=False)
class CreateBroadcastTemplate:
    """Save a broadcast template."""
    def body(self, ctx):
        return {
            "name": "AAA+ test template",
            "subject": "Auto-created",
            "body_html": "<p>Auto</p>",
            "body_text": "Auto",
        }
    expected_status = [200, 201, 409]


@Endpoint(method="DELETE", path="/admin/broadcast-templates/{template_id}", auth="developer", category="admin_broadcasts", idempotent=True)
class DeleteBroadcastTemplate:
    """Delete a broadcast template."""
    expected_status = [200, 204, 404]


@Endpoint(method="POST", path="/admin/broadcasts/{broadcast_id}/reinstate", auth="developer", category="admin_broadcasts", idempotent=False)
class ReinstateBroadcast:
    """Reinstate a retracted broadcast."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(method="PUT", path="/admin/broadcasts/{broadcast_id}", auth="developer", category="admin_broadcasts", idempotent=False)
class UpdateBroadcast:
    """Update an existing broadcast."""
    def body(self, ctx):
        return {"title": "Updated", "body": "Updated body"}
    expected_status = [200, 404]


@Endpoint(method="GET", path="/admin/broadcasts/{broadcast_id}/stats", auth="developer", category="admin_broadcasts", idempotent=True)
class BroadcastStats:
    """Delivery stats for a broadcast."""
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/bundles/{bundle_id}/hide", auth="developer", category="admin_bundles_moderation", idempotent=False)
class HideBundle:
    """Admin hide a bundle from marketplace."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test"}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/bundles/{bundle_id}/unhide", auth="developer", category="admin_bundles_moderation", idempotent=False)
class UnhideBundle:
    """Admin unhide a bundle."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/bundles/reports/{report_id}/dismiss", auth="developer", category="admin_bundles_moderation", idempotent=False)
class DismissBundleReport:
    """Admin dismiss a bundle abuse report."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
