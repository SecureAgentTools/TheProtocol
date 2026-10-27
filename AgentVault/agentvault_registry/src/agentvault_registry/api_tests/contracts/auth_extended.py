"""Authentication extended contracts (AAA+ Phase IV-A round 2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE


@Endpoint(method="POST", path="/auth/logout", auth="developer", category="auth", idempotent=True)
class AuthLogout:
    """Developer logout — invalidates session."""
    def body(self, ctx):
        return {}
    expected_status = [200, 204]


@Endpoint(method="POST", path="/auth/register", auth="none", category="auth", idempotent=False)
class AuthRegister:
    """Developer registration."""
    def body(self, ctx):
        import time
        return {
            "name": "AAA+ Contract Test Dev",
            "email": f"aaa-contract-{int(time.time()*1000)}@theprotocol.cloud",
            "password": "TestPass123!",
            "organization": "AAA+ Test Org",
        }
    expected_status = [200, 201, 409, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Duplicate email (rare race)",
        ),
    ]


@Endpoint(method="GET", path="/auth/profile", auth="developer", category="auth", idempotent=True)
class AuthProfile:
    """Caller's profile (current dev info)."""
    expected_status = 200


@Endpoint(method="POST", path="/auth/set-new-password", auth="developer", category="auth", idempotent=False)
class SetNewPassword:
    """Change caller's password."""
    def body(self, ctx):
        return {"current_password": SANDBOX_ADMIN_PASSWORD, "new_password": "NewPass123!"}
    expected_status = [200, 400, 401]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 401),
            reason="Current password mismatch or not authenticated",
        ),
    ]


@Endpoint(method="POST", path="/auth/api-keys", auth="developer", category="auth", idempotent=False)
class GenerateApiKey:
    """Generate a long-lived API key."""
    def body(self, ctx):
        return {"description": "AAA+ contract test key"}
    expected_status = [200, 201, 422]


@Endpoint(method="GET", path="/auth/api-keys", auth="developer", category="auth", idempotent=True)
class ListApiKeys:
    """List caller's API keys."""
    expected_status = 200


@Endpoint(method="DELETE", path="/auth/api-keys/{key_id}", auth="developer", category="auth", idempotent=True)
class DeleteApiKey:
    """Revoke an API key."""
    expected_status = [200, 204, 404]


# ── /authentication category (OpenAPI tag) ─────────────────────────────
@Endpoint(method="GET", path="/auth/2fa/status", auth="developer", category="two_factor_authentication", idempotent=True)
class TwoFAStatus:
    """Caller's 2FA enrollment status."""
    expected_status = 200


@Endpoint(method="POST", path="/auth/2fa/enable", auth="developer", category="two_factor_authentication", idempotent=False)
class TwoFAEnable:
    """Enable 2FA after setup."""
    def body(self, ctx):
        return {"totp_code": "000000"}
    expected_status = [200, 400, 401]
    failures = [
        FailureMode.totp_required(),
    ]


@Endpoint(method="GET", path="/auth/2fa/backup-codes", auth="developer", category="two_factor_authentication", idempotent=True)
class TwoFABackupCodes:
    """List backup codes (if 2FA enabled)."""
    expected_status = [200, 403, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (403, 404),
            reason="2FA not enabled on caller account",
        ),
    ]
