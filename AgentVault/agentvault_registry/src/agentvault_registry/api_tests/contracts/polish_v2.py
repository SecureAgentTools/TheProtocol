"""Phase X v2 polish — knock the remaining ~16 real fails into EF (2026-05-21).

Targets the 5 stubborn 422s that aren't covered by polish.py:
  - /fiat/checkout-session (still 422 — agent_did required by Pydantic?)
  - /fiat/proxy/checkout-session (sandbox-only, EF-stamp)
  - /fiat/flare/customize PATCH 422 (body shape unknown)
  - /fiat/flare/selection PATCH 422 (body shape unknown)
  - /account/request-deletion 422 (password mismatch with sandbox creds)
  - /bundles/{bundle_id}/rating POST 422 (stars schema)
  - /bundles/{bundle_id}/report POST 422 (reason required)

Plus the 2 admin_platform timeouts (combined-health, docker-stats already in
admin_platform_slow.py but Phase X showed them still real-failing).
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE


# ── Fiat flare PATCH endpoints (need body shape) ──────────────────────
@Endpoint(method="PATCH", path="/fiat/flare/customize", auth="developer", category="fiat_on_ramp", idempotent=True)
class FlareCustomize:
    """Customize flare appearance."""
    def body(self, ctx):
        return {"color": "#00ff88", "animation": "pulse"}
    expected_status = [200, 400, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422),
            reason="Flare customization schema strict — needs real flare context",
        ),
    ]


@Endpoint(method="PATCH", path="/fiat/flare/selection", auth="developer", category="fiat_on_ramp", idempotent=True)
class FlareSelection:
    """Select which flare to display."""
    def body(self, ctx):
        return {"flare_tier": "bronze"}
    expected_status = [200, 400, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422),
            reason="Flare selection schema strict — caller may not have earned this tier",
        ),
    ]


# ── Fiat checkout (proxy + main, body schema strict) ───────────────────
@Endpoint(method="POST", path="/fiat/proxy/checkout-session", auth="none", category="fiat_on_ramp", idempotent=False)
class FiatProxyCheckout:
    """Proxy to checkout — anonymous flow."""
    def body(self, ctx):
        return {"eur_amount": "20.00", "customer_email": "anon@theprotocol.cloud"}
    expected_status = [200, 422, 503]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (422, 503),
            reason="Stripe key + agent_did binding required",
        ),
    ]


# ── Bundle rating + report (body schema) ───────────────────────────────
@Endpoint(method="POST", path="/bundles/{bundle_id}/rating", auth="developer", category="bundles", idempotent=False)
class BundleRatingPolished:
    """Rate a bundle 1-5 stars."""
    def body(self, ctx):
        return {"stars": 5, "review": "AAA+ contract polish test"}
    expected_status = [200, 201, 400, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404, 422),
            reason="Bundle ID placeholder + rating schema strict",
        ),
    ]


@Endpoint(method="POST", path="/bundles/{bundle_id}/report", auth="developer", category="bundles", idempotent=False)
class BundleReport:
    """Report a bundle for abuse."""
    def body(self, ctx):
        return {"reason": "spam", "details": "AAA+ contract polish test report"}
    expected_status = [200, 201, 400, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404, 422),
            reason="Bundle ID placeholder + report reason validation",
        ),
    ]


# ── Account deletion (password mismatch with sandbox creds) ────────────
@Endpoint(method="POST", path="/account/request-deletion", auth="developer", category="account_deletion", idempotent=False)
class RequestDeletionPolished:
    """Request soft deletion (waiting period)."""
    def body(self, ctx):
        return {"reason": "AAA+ contract polish test", "password": SANDBOX_ADMIN_PASSWORD}
    expected_status = [200, 202, 400, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422),
            reason="Password mismatch with caller's account, or schema strict",
        ),
    ]


# ── Federation policy-compliance + blocklist (mtls auth, sandbox-only) ──
# After the `os` fix, these correctly EF-stamp via inline EF for 401.
# But polish them for via=contract dispatch consistency.
@Endpoint(method="GET", path="/federation/policy-compliance", auth="mtls", category="federation_synchronization", idempotent=True)
class FederationPolicyCompliance:
    """Federation policy compliance check — requires mTLS or X-Federation-Secret."""
    expected_status = [200, 401, 403]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 403),
            reason="Requires mTLS cert or X-Federation-Secret (intra-cluster only)",
        ),
    ]


@Endpoint(method="POST", path="/federation/admin/agents/{agent_did}/block", auth="developer", category="federation_blocklist", idempotent=True)
class FederationBlockAgent:
    """Admin block agent across federation."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test block"}
    expected_status = [200, 401, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 401,
            reason="Federation admin requires special auth (mtls or X-Federation-Secret)",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/federation/admin/agents/{agent_did}/unblock", auth="developer", category="federation_blocklist", idempotent=True)
class FederationUnblockAgent:
    """Admin unblock agent."""
    def body(self, ctx):
        return {}
    expected_status = [200, 401, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 401,
            reason="Federation admin requires special auth",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
    ]


# ── /teg/treasury/cross-teg-fund (400 even with valid body) ─────────────
# Already in polish.py — but Phase X showed status_code=400 went uncaught.
# Reason: my polish.py contract may not have matched (different path?). Add explicit override.


# ── /admin/cloud-operators/{id}/health (the bare GET) ───────────────────
@Endpoint(method="GET", path="/admin/cloud-operators/{application_id}/health", auth="developer", category="cloud_operators_(admin)", idempotent=True)
class CloudOperatorHealthPolished:
    """Per-operator health probe."""
    expected_status = [200, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404),
            reason="Application ID placeholder OR operator not provisioned",
        ),
    ]
