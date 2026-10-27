"""PB-3 fiat provider abstraction layer.

Per Webhook_Fiat_Layer_Strategy.md v2 (2026-05-12) §3.1, this package defines:

  - FiatProvider Protocol — single contract every PSP integration implements
  - ProviderEvent — normalized webhook envelope (provider.parse_event returns this)
  - ProviderSession — normalized create_checkout result

W0 (zero behavior change): StripeProvider implements the protocol by delegating to
the existing services.stripe_checkout module. No handler in routers.fiat_onramp
calls this abstraction yet; that happens in W2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Protocol, runtime_checkable

# ─── Normalized event taxonomy ─────────────────────────────────────────
ProviderEventKind = Literal[
    "checkout_completed",      # PSP confirms payment captured
    "checkout_expired",        # PSP confirms session expired without capture
    "charge_refunded",         # PSP confirms refund (full or partial)
    "charge_disputed",         # PSP signals chargeback / dispute opened
    "subscription_payment",    # Recurring rail (Mollie SEPA, GoCardless) — v1.1+ out of v1.0 scope
    "unknown",                 # PSP sent an event we don't model
]


@dataclass(frozen=True)
class ProviderEvent:
    """Normalized webhook envelope. Each FiatProvider.parse_event returns this.

    Strategy reference: §3.1.
    """
    provider: str                               # 'stripe', 'mollie', ...
    provider_event_id: str                      # PSP's unique event ID — the L1 idempotency anchor
    provider_session_id: str                    # PSP's unique session/order/intent ID
    provider_payment_id: Optional[str]          # PSP's payment-id (Stripe: payment_intent; Mollie: payment.id)
    kind: ProviderEventKind                     # normalized type
    metadata: Dict[str, Any] = field(default_factory=dict)  # echoed metadata
    customer_email: Optional[str] = None        # buyer email if PSP exposes it on this event
    refund_reason: Optional[str] = None         # only for charge_refunded
    refund_amount_eur: Optional[Decimal] = None  # only for charge_refunded; equals amount_eur for full refund
    raw: Dict[str, Any] = field(default_factory=dict)  # original PSP envelope for forensics


@dataclass(frozen=True)
class ProviderSession:
    """Normalized create_checkout result. Each FiatProvider.create_checkout returns this.

    Strategy reference: §3.1.
    """
    provider_session_id: str                    # PSP-side session/order id
    redirect_url: str                           # buyer-facing checkout URL
    provider_payment_id: Optional[str] = None   # may be None until webhook arrives
    expires_at: Optional[int] = None            # unix-ts of session expiry, if PSP provides
    raw: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class FiatProvider(Protocol):
    """The contract every PSP integration implements.

    Strategy reference: §3.1. The first implementer is StripeProvider (W0); Mollie
    follows in W3. Adyen / GoCardless / Wise / Bank-SEPA-manual defer to v1.1/v1.2.
    """

    name: str                                   # 'stripe' | 'mollie' | ...
    signature_header_name: str                  # 'Stripe-Signature' | 'X-Mollie-Signature' | ...
    supports_anonymous_flow: bool               # True if PSP exposes customer_email on webhook
    supports_routed_storefront: bool            # True if operator-storefront routing is feasible

    async def verify_webhook(self, raw_body: bytes, headers: Dict[str, str]) -> ProviderEvent:
        """Verify signature + parse + return normalized event.

        Raises ValueError on signature mismatch (mapped to 401 by dispatcher).
        Raises ValueError on parse failure (mapped to 422 by dispatcher).
        """
        ...

    async def create_checkout(
        self,
        *,
        eur_amount: Decimal,
        avt_amount: Decimal,
        success_url: str,
        cancel_url: str,
        customer_email: Optional[str],
        metadata: Dict[str, Any],
        tier_label: str,
        tier_display_name: str,
        locale: str = "en",
        operator_branding: Optional[Dict[str, Any]] = None,
    ) -> ProviderSession:
        """Open a checkout session with the PSP."""
        ...

    async def retrieve_session(self, provider_session_id: str) -> Dict[str, Any]:
        """Pull current state for admin drill-down. Returns provider-shaped dict.

        Admin UI takes care of rendering; this is intentionally not normalized.
        """
        ...

    async def refund(
        self,
        provider_payment_id: str,
        *,
        amount_eur: Optional[Decimal] = None,   # None = full refund
        reason: str = "requested_by_customer",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Issue refund. Returns PSP's refund-id for audit. Raises on failure."""
        ...


__all__ = [
    "FiatProvider",
    "ProviderEvent",
    "ProviderSession",
    "ProviderEventKind",
]
