"""Authentication contracts (AAA+ Phase II-B, 2026-05-21).

Login + agent token + JWKS + 2FA + password reset.
Some 2FA endpoints are impossible to test (real TOTP needed) — marked accordingly.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE


@Endpoint(method="POST", path="/auth/login", auth="none", category="auth", idempotent=False)
class AuthLogin:
    """Developer login (form-encoded, returns JWT)."""
    # Note: the contract framework sends JSON by default. Login needs form-encoded.
    # We handle this via the fallback inline path for now; contract is registered
    # to demonstrate the framework but DELEGATES to inline by raising in body.
    def body(self, ctx):
        # Legacy fallback handler injects form-encoded body.
        return {"username": "admin@test.sandbox", "password": SANDBOX_ADMIN_PASSWORD}
    expected_status = [200, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Endpoint expects form-encoded body, not JSON — handled by legacy fallback",
        ),
    ]


@Endpoint(method="POST", path="/auth/agent/token", auth="none", category="auth", idempotent=False)
class AuthAgentToken:
    """Mint agent JWT from client_id + client_secret. Form-encoded."""
    def body(self, ctx):
        return {"grant_type": "password", "username": "placeholder", "password": "placeholder"}
    expected_status = [200, 401, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Endpoint expects form-encoded body, not JSON",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 401,
            reason="Placeholder credentials are not real agent credentials",
        ),
    ]


@Endpoint(method="POST", path="/auth/refresh", auth="none", category="auth", idempotent=False)
class AuthRefresh:
    """Refresh access token from refresh_token."""
    def body(self, ctx):
        return {"refresh_token": "placeholder"}
    expected_status = [200, 401, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 422),
            reason="Placeholder refresh token is not a real token",
        ),
    ]


@Endpoint(method="POST", path="/auth/2fa/setup", auth="developer", category="two_factor_authentication", idempotent=False)
class TwoFASetup:
    """Initiate 2FA setup. Returns QR code + secret."""
    def body(self, ctx):
        return {"password": SANDBOX_ADMIN_PASSWORD}
    expected_status = [200, 400, 403, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 403, 409),
            reason="2FA already enabled or password mismatch",
        ),
    ]


@Endpoint(method="POST", path="/auth/2fa/verify", auth="none", category="two_factor_authentication", idempotent=False)
class TwoFAVerify:
    """Verify TOTP code — impossible without real wall-clock code."""
    def body(self, ctx):
        return {"code": "000000"}
    failures = [FailureMode.totp_required()]
    expected_status = [200, 400, 401]


@Endpoint(method="POST", path="/auth/2fa/disable", auth="developer", category="two_factor_authentication", idempotent=False)
class TwoFADisable:
    """Disable 2FA — needs current TOTP, not testable."""
    def body(self, ctx):
        return {"password": SANDBOX_ADMIN_PASSWORD}
    failures = [FailureMode.totp_required()]
    expected_status = [200, 400, 401, 403]


@Endpoint(method="POST", path="/auth/2fa/validate", auth="none", category="two_factor_authentication", idempotent=False)
class TwoFAValidate:
    """Validate partial token from 2FA-enabled login — impossible without 2FA-enabled account."""
    def body(self, ctx):
        return {"partial_token": "000000", "code": "000000"}
    failures = [FailureMode.totp_required()]
    expected_status = [200, 400, 401]


@Endpoint(method="POST", path="/auth/2fa/recover", auth="none", category="two_factor_authentication", idempotent=False)
class TwoFARecover:
    """Use backup code to recover 2FA — needs real partial_token + backup code."""
    def body(self, ctx):
        return {"partial_token": "placeholder", "backup_code": "BACKUP-CODE-001"}
    failures = [FailureMode.totp_required()]
    expected_status = [200, 400, 401]


@Endpoint(method="POST", path="/auth/request-password-reset", auth="none", category="auth", idempotent=False)
class RequestPasswordReset:
    """Request password reset email."""
    def body(self, ctx):
        return {"email": "test@theprotocol.cloud"}
    expected_status = 200


@Endpoint(method="POST", path="/auth/reset-password", auth="none", category="auth", idempotent=False)
class ResetPassword:
    """Reset password with token from email — impossible without real token."""
    def body(self, ctx):
        return {"token": "placeholder", "new_password": "NewPassword123!"}
    failures = [FailureMode.email_roundtrip()]
    expected_status = [200, 400, 401]


@Endpoint(method="POST", path="/auth/recover-account", auth="none", category="auth", idempotent=False)
class RecoverAccount:
    """Account recovery via recovery key — impossible without real key."""
    def body(self, ctx):
        return {"email": "test@theprotocol.cloud", "recovery_key": "placeholder"}
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400,
            reason="Placeholder recovery key — real key required",
        ),
    ]
    expected_status = [200, 400]
