"""Webhook contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/developers/webhooks", auth="developer", category="developers", idempotent=False)
class CreateWebhook:
    """Register a webhook for the caller."""
    def body(self, ctx):
        return {
            "url": "https://webhook-test.example.com/hook",
            "events": ["agent.created", "agent.updated"],
        }
    expected_status = [200, 201, 422]


@Endpoint(method="GET", path="/developers/webhooks", auth="developer", category="developers", idempotent=True)
class ListWebhooks:
    """List caller's webhooks."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/webhooks/{webhook_id}/disable", auth="developer", category="admin_platform", idempotent=False)
class DisableWebhook:
    """Admin disable a webhook."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/webhooks/{webhook_id}/enable", auth="developer", category="admin_platform", idempotent=False)
class EnableWebhook:
    """Admin enable a webhook."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/webhooks/{webhook_id}/test", auth="developer", category="admin_platform", idempotent=False)
class TestWebhook:
    """Admin fire a test webhook."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
