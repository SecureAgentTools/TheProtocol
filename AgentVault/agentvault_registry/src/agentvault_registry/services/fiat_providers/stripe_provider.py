"""PB-3 Stripe FiatProvider — W0 implementation.

This is the first implementer of the FiatProvider protocol. It delegates to the
existing services.stripe_checkout module to keep Stripe path byte-identical
during the W0 zero-behavior-change refactor.

W2 will refactor routers.fiat_onramp handlers to call this abstraction.

Strategy reference: §3.3.1 + §A.4 W0.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional

from . import FiatProvider, ProviderEvent, ProviderSession

logger = logging.getLogger(__name__)


class StripeProvider:
    """Stripe Checkout (cards + SEPA + Klarna + iDEAL + Bancontact + Sofort + Giropay).

    Webhook signature: HMAC-SHA256 of `{ts}.{body}` via STRIPE_WEBHOOK_SECRET.
    Header: Stripe-Signature: t=<unix-ts>,v1=<hex>.
    SDK does verify + parse atomically via stripe.Webhook.construct_event().

    Strategy: §3.3.1.
    """

    name: str = "stripe"
    signature_header_name: str = "Stripe-Signature"
    supports_anonymous_flow: bool = True
    supports_routed_storefront: bool = True

    # ── Webhook verification + parse ────────────────────────────────

    async def verify_webhook(self, raw_body: bytes, headers: Dict[str, str]) -> ProviderEvent:
        """Verify Stripe webhook signature + parse the event envelope into ProviderEvent.

        Raises ValueError on signature failure (mapped to 401 by dispatcher).
        """
        # Resolve signature header case-insensitively
        sig = (
            headers.get("Stripe-Signature")
            or headers.get("stripe-signature")
            or headers.get("STRIPE_SIGNATURE")
        )
        if not sig:
            raise ValueError("missing Stripe-Signature header")

        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        if not secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET not configured")

        # Delegate to existing services.stripe_checkout.verify_webhook_signature
        # (raises stripe.SignatureVerificationError on mismatch — caller maps to ValueError). It returns a PLAIN dict
        # (§DEPS stripe15: stripe-python 15's StripeObject has no .get(), which _normalize_event reads throughout).
        try:
            from ..stripe_checkout import verify_webhook_signature
            event = verify_webhook_signature(
                payload=raw_body,
                signature_header=sig,
                webhook_secret=secret,
            )
        except Exception as exc:
            # Stripe SDK raises SignatureVerificationError + ValueError + others;
            # normalize to ValueError per FiatProvider contract.
            raise ValueError(f"Stripe signature verification failed: {exc}") from exc

        return self._normalize_event(event)

    def _normalize_event(self, event: Dict[str, Any]) -> ProviderEvent:
        """Map a Stripe envelope to a normalized ProviderEvent.

        Stripe's `event.type` strings get mapped to our ProviderEventKind enum.
        """
        event_type = event.get("type", "")
        event_id = event.get("id", "")
        data_object = event.get("data", {}).get("object", {}) or {}

        # Map Stripe event types to our enum
        if event_type == "checkout.session.completed":
            kind = "checkout_completed"
            session_id = data_object.get("id", "")
            payment_id = data_object.get("payment_intent")
            metadata = data_object.get("metadata", {}) or {}
            customer_email = (
                data_object.get("customer_email")
                or data_object.get("customer_details", {}).get("email", "")
                or None
            )
            return ProviderEvent(
                provider="stripe",
                provider_event_id=event_id,
                provider_session_id=session_id,
                provider_payment_id=payment_id,
                kind="checkout_completed",
                metadata=metadata,
                customer_email=customer_email,
                raw=event,
            )

        if event_type == "checkout.session.expired":
            session_id = data_object.get("id", "")
            payment_id = data_object.get("payment_intent")
            metadata = data_object.get("metadata", {}) or {}
            return ProviderEvent(
                provider="stripe",
                provider_event_id=event_id,
                provider_session_id=session_id,
                provider_payment_id=payment_id,
                kind="checkout_expired",
                metadata=metadata,
                customer_email=None,
                raw=event,
            )

        if event_type in ("charge.refunded", "charge.refund.updated"):
            # Stripe charge envelope is different shape from checkout session.
            payment_id = data_object.get("payment_intent", "")
            # Try to extract refund reason from charge.refunds.data[0].reason if present.
            refund_reason = None
            refunds = data_object.get("refunds", {})
            if isinstance(refunds, dict):
                refund_list = refunds.get("data") or []
                if refund_list and isinstance(refund_list[0], dict):
                    refund_reason = refund_list[0].get("reason")
            amount_refunded = data_object.get("amount_refunded")
            refund_amount_eur: Optional[Decimal] = None
            if isinstance(amount_refunded, (int, float)):
                refund_amount_eur = Decimal(amount_refunded) / Decimal("100")
            metadata = data_object.get("metadata", {}) or {}
            return ProviderEvent(
                provider="stripe",
                provider_event_id=event_id,
                provider_session_id="",  # charge events don't carry session id directly
                provider_payment_id=payment_id,
                kind="charge_refunded",
                metadata=metadata,
                customer_email=None,
                refund_reason=refund_reason,
                refund_amount_eur=refund_amount_eur,
                raw=event,
            )

        if event_type in ("charge.dispute.created", "charge.dispute.updated"):
            payment_id = data_object.get("payment_intent", "")
            metadata = data_object.get("metadata", {}) or {}
            reason = data_object.get("reason")
            return ProviderEvent(
                provider="stripe",
                provider_event_id=event_id,
                provider_session_id="",
                provider_payment_id=payment_id,
                kind="charge_disputed",
                metadata={**metadata, "stripe_dispute_reason": reason} if reason else metadata,
                customer_email=None,
                raw=event,
            )

        # Unknown event type — caller logs + 200s for Stripe queue health.
        return ProviderEvent(
            provider="stripe",
            provider_event_id=event_id,
            provider_session_id=data_object.get("id", ""),
            provider_payment_id=None,
            kind="unknown",
            metadata=data_object.get("metadata", {}) or {},
            customer_email=None,
            raw=event,
        )

    # ── Checkout creation ────────────────────────────────────────────

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
        """Open a Stripe Checkout Session — delegates to existing helper.

        operator_branding is currently consumed inside metadata + product_data by
        the existing helper (see services.stripe_checkout for the session_kwargs
        composition). Strategy: §3.4 operator-storefront stays Stripe-only in v1.0.
        """
        api_key = os.getenv("STRIPE_API_KEY", "")
        if not api_key:
            raise RuntimeError("STRIPE_API_KEY not configured")

        # Stripe metadata values must be strings; coerce
        meta = {
            **{k: str(v) for k, v in (metadata or {}).items() if v is not None},
            "tier_label": tier_label,
            "tier_display_name": tier_display_name,
        }

        from ..stripe_checkout import create_checkout_session
        session = create_checkout_session(
            api_key=api_key,
            eur_amount=eur_amount,
            avt_amount=avt_amount,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata=meta,
            locale=locale if locale else "auto",
        )

        # a plain dict (§DEPS stripe15): stripe-python 15's StripeObject raises on dict(obj), and hasattr(obj,
        # "__iter__") is True there, so the old guard would have raised instead of falling back
        return ProviderSession(
            provider_session_id=session["id"],
            redirect_url=session["url"],
            provider_payment_id=session.get("payment_intent"),
            expires_at=session.get("expires_at"),
            raw=dict(session),
        )

    # ── Drill-down ──────────────────────────────────────────────────

    async def retrieve_session(self, provider_session_id: str) -> Dict[str, Any]:
        """Fetch the Stripe checkout session — used by admin drill-down."""
        api_key = os.getenv("STRIPE_API_KEY", "")
        if not api_key:
            raise RuntimeError("STRIPE_API_KEY not configured")
        from ..stripe_checkout import retrieve_session as _retrieve
        # already a plain dict (§DEPS stripe15: services.stripe_checkout.retrieve_session calls .to_dict())
        return dict(_retrieve(api_key=api_key, session_id=provider_session_id))

    # ── Refund ──────────────────────────────────────────────────────

    async def refund(
        self,
        provider_payment_id: str,
        *,
        amount_eur: Optional[Decimal] = None,
        reason: str = "requested_by_customer",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Issue Stripe refund. Returns refund_id."""
        api_key = os.getenv("STRIPE_API_KEY", "")
        if not api_key:
            raise RuntimeError("STRIPE_API_KEY not configured")

        try:
            import stripe  # type: ignore
        except ImportError as exc:
            raise RuntimeError("stripe SDK not installed") from exc

        stripe.api_key = api_key

        refund_kwargs: Dict[str, Any] = {
            "payment_intent": provider_payment_id,
            "reason": reason,
        }
        if amount_eur is not None:
            refund_kwargs["amount"] = int((amount_eur * Decimal("100")).quantize(Decimal("1")))
        if metadata:
            refund_kwargs["metadata"] = {k: str(v) for k, v in metadata.items() if v is not None}

        # a plain dict, like every other SDK result the fiat code reads (§DEPS stripe15)
        refund = stripe.Refund.create(**refund_kwargs).to_dict()
        refund_id = refund.get("id", "")
        logger.info(
            "[fiat_providers/stripe] refund issued payment_intent=%s refund_id=%s amount_eur=%s reason=%s",
            provider_payment_id, refund_id, amount_eur, reason,
        )
        return refund_id


__all__ = ["StripeProvider"]
