"""Fiat on-ramp contracts (AAA+ Phase II-B — §pass50 endpoints, 2026-05-21).

Stripe Checkout EUR → AVT. Mainframe-only via FIAT_GENESIS_REGISTRY env gate.
The webhook endpoint is impossible to call from the harness (needs Stripe signature).
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/fiat/tiers", auth="none", category="fiat_onramp", idempotent=True)
class FiatTiers:
    """Tier breakpoints + min/max EUR. Public."""
    expected_status = 200


@Endpoint(method="POST", path="/fiat/quote", auth="none", category="fiat_onramp", idempotent=True)
class FiatQuote:
    """Live AVT preview for a given EUR amount."""
    def body(self, ctx):
        return {"eur_amount": "10.00"}
    expected_status = 200


@Endpoint(method="POST", path="/fiat/checkout-session", auth="developer", category="fiat_onramp", idempotent=False)
class FiatCheckoutSession:
    """Create Stripe Checkout session. Returns hosted URL + session_id.

    Schema (`fiat_onramp.py:CheckoutRequest`) requires:
      - eur_amount: "1.00"-"500.00" string
      - tos_accepted: must be True
      - tos_version: must match CURRENT_TOS_VERSION (currently "1.4")
      - either agent_did (logged-in flow) OR customer_email (anonymous flow)
    Gate at `fiat_onramp.py:697-708` returns 400 if TOS missing/mismatched.
    """
    def body(self, ctx):
        return {
            "eur_amount": "20.00",
            "customer_email": "test-checkout@theprotocol.cloud",
            "tos_accepted": True,
            "tos_version": "1.4",
        }
    expected_status = [200, 400, 422, 503]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and ("tos" in r.detail_lower() or "terms" in r.detail_lower()),
            reason="TOS version drifted past 1.4 — bump in contract body when CURRENT_TOS_VERSION changes",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422) and ("stripe" in r.detail_lower() or "agent" in r.detail_lower()),
            reason="Stripe SDK unavailable, test-mode unset, or agent_did required",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 503,
            reason="FIAT_ONRAMP_ENABLED off or Stripe API unreachable",
        ),
    ]


@Endpoint(method="POST", path="/fiat/stripe-webhook", auth="none", category="fiat_onramp", idempotent=False)
class FiatStripeWebhook:
    """Stripe webhook receiver — requires Stripe signature, untestable from harness."""
    expected_status = [200, 400, 401, 403, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 401, 403, 422),
            reason="Stripe webhook requires X-Stripe-Signature header; harness can't sign as Stripe",
        ),
    ]


@Endpoint(method="GET", path="/fiat/my-purchases", auth="developer", category="fiat_onramp", idempotent=True)
class FiatMyPurchases:
    """Caller's fiat purchase history."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/fiat/purchase/{session_id}",
    auth="none",
    category="fiat_onramp",
)
class FiatPurchaseStatus:
    """Public-by-session-id polling endpoint for success page."""
    expected_status = [200, 404]  # 404 expected for placeholder session_id
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Templated session_id placeholder — no real purchase to poll",
        ),
    ]
