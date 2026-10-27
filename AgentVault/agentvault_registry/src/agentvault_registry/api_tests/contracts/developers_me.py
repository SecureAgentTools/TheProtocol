"""Developer-self contracts (AAA+ Phase II-B, 2026-05-21).

The /developers/me/* surface — caller's own developer record + signing keys
+ notification preferences.
"""
from __future__ import annotations

from ..core.contract import Endpoint


@Endpoint(method="GET", path="/developers/me/notification-prefs", auth="developer", category="developers", idempotent=True)
class NotificationPrefs:
    """Caller's notification preferences."""
    expected_status = 200


@Endpoint(method="GET", path="/developers/me/signing-keys", auth="developer", category="developer_signing_keys", idempotent=True)
class MySigningKeys:
    """Caller's signing key history."""
    expected_status = 200


@Endpoint(
    method="POST",
    path="/developers/me/signing-key/rotate",
    auth="developer",
    category="developer_signing_keys",
    idempotent=False,
)
class RotateMySigningKey:
    """Rotate caller's signing key. Private PEM shown ONCE."""
    def body(self, ctx):
        return {}
    expected_status = 200


@Endpoint(method="GET", path="/account/deletion-status", auth="developer", category="account_deletion", idempotent=True)
class AccountDeletionStatus:
    """Caller's account deletion status."""
    expected_status = 200
