"""Admin email studio contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/admin/email/preview/{template}", auth="developer", category="admin_email_studio", idempotent=True)
class EmailPreviewHtml:
    """Render an email template HTML preview."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Template placeholder doesn't exist",
        ),
    ]


@Endpoint(method="GET", path="/admin/email/preview/{template}/text", auth="developer", category="admin_email_studio", idempotent=True)
class EmailPreviewText:
    """Render plaintext preview."""
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/email/preview/{template}", auth="developer", category="admin_email_studio", idempotent=False)
class EmailSendTestPreview:
    """Send a test preview email with custom context."""
    def body(self, ctx):
        return {"recipient": "test@theprotocol.cloud", "context": {}}
    expected_status = [200, 404]
