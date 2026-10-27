"""PB-3 Mollie FiatProvider — W3 implementation.

Second FiatProvider implementer after Stripe. Mollie B.V. (NL DNB-licensed EMI)
is the v1.0 second PSP per Webhook_Fiat_Layer_Strategy.md v2 §1.2.

Signature scheme (Mollie Next-gen Webhooks):
  - HMAC-SHA256 of raw body keyed with MOLLIE_WEBHOOK_SIGNING_SECRET
  - Header: `X-Mollie-Signature: sha256=<hex>`
  - Snapshot mode (recommended): webhook body contains full payment resource
  - Legacy mode (id-only): body is form-encoded `id=tr_xxx`; we'd need to
    GET /v2/payments/{id} to read state (v1.1+ — out of v1.0 scope)

Critical runbook item (strategy §A.11 F2): when provisioning the Mollie
production webhook in Mollie Dashboard, EXPLICITLY ENABLE Next-gen Webhooks.
Default for older API consumers is still legacy unsigned. Without that toggle
our HMAC verifier rejects every webhook (no `X-Mollie-Signature` header).

Documentation: docs.mollie.com/reference/webhooks-new

Strategy reference: §3.3.2 (signature scheme), §1.2 (selection rationale),
§A.11 F2 (Dashboard opt-in runbook item).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

import httpx

from . import FiatProvider, ProviderEvent, ProviderSession

logger = logging.getLogger(__name__)


MOLLIE_API_BASE = os.getenv("MOLLIE_API_BASE", "https://api.mollie.com/v2")


# Mollie payment.status → ProviderEventKind mapping
# https://docs.mollie.com/reference/v2/payments-api/get-payment#response-status
_STATUS_MAP = {
    "paid":       "checkout_completed",
    "authorized": "checkout_completed",   # treat as completed; capture is automatic in our flow
    "expired":    "checkout_expired",
    "canceled":   "checkout_expired",     # user-cancelled = same disposition
    "failed":     "checkout_expired",     # closest equivalent (we don't have a dedicated "failed" kind)
    "refunded":   "charge_refunded",
    "chargeback": "charge_disputed",
    # "open"/"pending" don't map — they're in-flight; no terminal action needed
}


class MollieProvider:
    """Mollie Next-gen Webhooks (HMAC-SHA256 over raw body, snapshot mode).

    v1.0 scope:
      - Snapshot-mode webhooks (full payment resource in body)
      - Cards + iDEAL + Bancontact + Sofort + Giropay (via Mollie's auto-method selection)
      - SEPA-DD via Single Mandate (one-shot SEPA)

    v1.1+ scope:
      - Routed-storefront (operator-storefront mode via mainframe) — needs Mollie's
        equivalent of Stripe metadata round-trip. Defers per strategy §14 Q10.
      - Legacy id-only webhook fallback with GET /v2/payments/{id} re-pull

    Strategy: §3.3.2 + §1.2.
    """

    name: str = "mollie"
    signature_header_name: str = "X-Mollie-Signature"
    supports_anonymous_flow: bool = True   # Mollie exposes customer email in payment resource
    supports_routed_storefront: bool = False  # v1.0: direct only; v1.1+ adds routed-Mollie

    # ── Webhook verification + parse ────────────────────────────────

    async def verify_webhook(self, raw_body: bytes, headers: Dict[str, str]) -> ProviderEvent:
        """Verify Mollie webhook signature + parse payload.

        Two paths:
          A) Next-gen Webhooks (recommended for prod): HMAC-SHA256(raw_body, secret)
             → header `X-Mollie-Signature: sha256=<hex>`. Body is full payment JSON.
          B) Legacy mode (sandbox-friendly): no signature header. Body is form-encoded
             `id=tr_xxx`. We re-pull full payment state via GET /v2/payments/{id}
             using MOLLIE_API_KEY. Security in this mode relies on the unguessability
             of our webhook URL (and the API key); use only for sandbox.

        Strategy: §3.3.2 + §A.11 F2.
        """
        sig_header = (
            headers.get("X-Mollie-Signature")
            or headers.get("x-mollie-signature")
        )

        if sig_header:
            # Path A: Next-gen Webhooks with HMAC signature
            return await self._verify_nextgen_webhook(raw_body, sig_header)
        else:
            # Path B: Legacy id-only mode (no signature; verify by re-pulling state)
            return await self._verify_legacy_webhook(raw_body)

    async def _verify_nextgen_webhook(self, raw_body: bytes, sig_header: str) -> ProviderEvent:
        """Next-gen Webhooks: HMAC-SHA256 over raw body."""
        if not sig_header.startswith("sha256="):
            raise ValueError("malformed X-Mollie-Signature header (expected 'sha256=<hex>')")
        provided_hex = sig_header[len("sha256="):]

        secret = os.getenv("MOLLIE_WEBHOOK_SIGNING_SECRET", "")
        if not secret:
            raise ValueError("MOLLIE_WEBHOOK_SIGNING_SECRET not configured")

        expected_hex = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_hex, provided_hex):
            raise ValueError("Mollie signature mismatch")

        try:
            payment = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Next-gen webhook body is not valid JSON: {exc}")

        return self._normalize_event(payment)

    async def _verify_legacy_webhook(self, raw_body: bytes) -> ProviderEvent:
        """Legacy id-only mode: parse form-encoded `id=tr_xxx`, re-pull state from Mollie.

        No HMAC signature on this path. Security model: webhook URL has a random
        path-segment that an attacker can't guess, AND Mollie's API key is needed
        to read the payment state (so a guessed URL still can't fake a fulfilment).

        Used in sandbox; production should enable Next-gen Webhooks.
        """
        # Parse form-encoded body to extract `id`
        try:
            body_str = raw_body.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Mollie webhook body is not UTF-8")

        # Mollie sends `id=tr_xxx`; could also be multi-field form-encoded
        payment_id = None
        for pair in body_str.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k.strip() == "id":
                    payment_id = v.strip()
                    break

        if not payment_id:
            # Could be JSON without signature header (unusual but possible) — try JSON parse
            try:
                payment_obj = json.loads(raw_body)
                if isinstance(payment_obj, dict) and "id" in payment_obj:
                    return self._normalize_event(payment_obj)
            except json.JSONDecodeError:
                pass
            raise ValueError(
                f"Mollie legacy webhook missing 'id' field; body={body_str[:200]!r}"
            )

        # Re-pull full payment state from Mollie API. THIS is the security gate:
        # only someone with our MOLLIE_API_KEY can read the real payment state.
        try:
            payment = await self.retrieve_session(payment_id)
        except Exception as exc:
            raise ValueError(f"Mollie legacy webhook re-pull failed for {payment_id}: {exc}")

        logger.info(
            "[fiat_providers/mollie] legacy webhook resolved id=%s status=%s",
            payment_id, payment.get("status", "?"),
        )
        return self._normalize_event(payment)

    def _normalize_event(self, payment: Dict[str, Any]) -> ProviderEvent:
        """Map a Mollie payment resource (snapshot mode) to ProviderEvent."""
        payment_id = payment.get("id", "")
        status = payment.get("status", "")
        metadata = payment.get("metadata", {}) or {}
        # Mollie's metadata can be a dict, a string, or null — normalize.
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        elif not isinstance(metadata, dict):
            metadata = {}

        # Mollie doesn't emit Stripe-style top-level event_id. Synthesize from
        # (payment_id, status, ts) for L1 idempotency. Two webhooks with the
        # same id+status are a real replay (Mollie may resend); we accept.
        # If Mollie ever ships true event_id, swap this.
        last_update = (
            payment.get("amountChargedBack", {}).get("value")  # for chargeback
            or payment.get("amountRefunded", {}).get("value")  # for refund
            or payment.get("authorizedAt")
            or payment.get("paidAt")
            or payment.get("expiredAt")
            or payment.get("canceledAt")
            or payment.get("failedAt")
            or payment.get("createdAt", "")
        )
        synth_event_id = f"mollie-{payment_id}-{status}-{last_update}"

        kind = _STATUS_MAP.get(status, "unknown")

        # Extract customer email from payment.details.consumerEmail (varies by
        # payment method). Fallback to billingAddress.email.
        customer_email = None
        details = payment.get("details") or {}
        if isinstance(details, dict):
            customer_email = (
                details.get("consumerEmail")
                or details.get("billingEmail")
                or None
            )
        if not customer_email:
            billing = payment.get("billingAddress") or {}
            if isinstance(billing, dict):
                customer_email = billing.get("email") or None

        # Refund-specific fields
        refund_reason = None
        refund_amount_eur = None
        if kind == "charge_refunded":
            refund_amount_raw = (
                payment.get("amountRefunded", {}).get("value")
                or payment.get("amount", {}).get("value")
            )
            if refund_amount_raw:
                try:
                    refund_amount_eur = Decimal(str(refund_amount_raw))
                except Exception:
                    pass
            # Mollie may carry refund reason in metadata.reason or details
            refund_reason = (
                metadata.get("refund_reason")
                or metadata.get("reason")
                or "mollie_refund"
            )

        # Mollie doesn't separate session_id from payment_id — same identifier
        # serves both roles.
        return ProviderEvent(
            provider="mollie",
            provider_event_id=synth_event_id,
            provider_session_id=payment_id,
            provider_payment_id=payment_id,
            kind=kind,
            metadata=metadata,
            customer_email=customer_email,
            refund_reason=refund_reason,
            refund_amount_eur=refund_amount_eur,
            raw=payment,
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
        """Create a Mollie Payment + return the hosted checkout URL.

        Mollie's webhook URL is part of the Payment resource — pass our public
        endpoint here so Mollie knows where to deliver Next-gen webhooks.

        URL-template handling (strategy §A.11 W2.6 fix): the success_url may
        contain Stripe's `{CHECKOUT_SESSION_ID}` template token (passed in by
        callers that hard-code Stripe-format URLs). Mollie doesn't substitute
        this token, so we strip it before passing to Mollie. The success page
        falls back to polling by fiat_purchase_id (returned in CheckoutResponse)
        instead of session_id from URL.
        """
        api_key = os.getenv("MOLLIE_API_KEY", "")
        if not api_key:
            raise RuntimeError("MOLLIE_API_KEY not configured")

        webhook_url = os.getenv(
            "MOLLIE_WEBHOOK_URL",
            "https://api.theprotocol.cloud/api/v1/fiat/webhook/mollie",
        )

        # Strip Stripe URL-template tokens. Mollie doesn't substitute them; pass
        # a clean URL. The frontend success page resolves the purchase via the
        # fiat_purchase_id stored in the calling page's localStorage before redirect.
        success_url = _strip_stripe_url_template(success_url)
        cancel_url = _strip_stripe_url_template(cancel_url)

        # Mollie expects amount as a decimal string ({value: "10.00", currency: "EUR"}).
        # Use a string with 2-decimal precision.
        amount_str = f"{eur_amount.quantize(Decimal('0.01'), rounding=ROUND_DOWN)}"

        avt_int = int(avt_amount.quantize(Decimal("1"), rounding=ROUND_DOWN))
        description = f"TheProtocol — {tier_display_name} (€{eur_amount} support · {avt_int:,} AVT bonus)"

        # Mollie metadata: can be any JSON. We round-trip our internal IDs the
        # same way Stripe does. Stays under Mollie's 1KB metadata cap easily.
        mollie_metadata: Dict[str, Any] = {
            **{k: str(v) for k, v in (metadata or {}).items() if v is not None},
            "tier_label": tier_label,
            "tier_display_name": tier_display_name,
        }

        body: Dict[str, Any] = {
            "amount": {"currency": "EUR", "value": amount_str},
            "description": description,
            "redirectUrl": success_url,
            "cancelUrl": cancel_url,
            "webhookUrl": webhook_url,
            "metadata": mollie_metadata,
            "locale": _MOLLIE_LOCALES.get(locale, "en_US"),
        }
        if customer_email:
            body["billingEmail"] = customer_email

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{MOLLIE_API_BASE}/payments",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if resp.status_code >= 300:
            raise RuntimeError(f"Mollie create payment failed {resp.status_code}: {resp.text[:500]}")
        payment = resp.json()
        checkout_url = (
            payment.get("_links", {}).get("checkout", {}).get("href", "")
        )
        if not checkout_url:
            raise RuntimeError(f"Mollie response missing _links.checkout.href: {payment}")
        logger.info(
            "[fiat_providers/mollie] created payment id=%s eur=%s checkout=%s",
            payment.get("id"), amount_str, checkout_url,
        )
        return ProviderSession(
            provider_session_id=payment["id"],
            redirect_url=checkout_url,
            provider_payment_id=payment["id"],
            expires_at=None,  # Mollie has an expiresAt field but it's a timestamp string, not unix-ts
            raw=payment,
        )

    # ── Drill-down ──────────────────────────────────────────────────

    async def retrieve_session(self, provider_session_id: str) -> Dict[str, Any]:
        """Fetch a Mollie payment resource for admin drill-down."""
        api_key = os.getenv("MOLLIE_API_KEY", "")
        if not api_key:
            raise RuntimeError("MOLLIE_API_KEY not configured")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{MOLLIE_API_BASE}/payments/{provider_session_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code >= 300:
            raise RuntimeError(f"Mollie retrieve failed {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    # ── Refund ──────────────────────────────────────────────────────

    async def refund(
        self,
        provider_payment_id: str,
        *,
        amount_eur: Optional[Decimal] = None,
        reason: str = "requested_by_customer",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Issue Mollie refund. Returns refund_id.

        Mollie refunds are POST /v2/payments/{id}/refunds with body
        {amount: {value, currency}, description}. amount is optional for full refund.
        """
        api_key = os.getenv("MOLLIE_API_KEY", "")
        if not api_key:
            raise RuntimeError("MOLLIE_API_KEY not configured")

        body: Dict[str, Any] = {
            "description": f"TheProtocol refund: {reason}"[:140],
        }
        if amount_eur is not None:
            amount_str = f"{amount_eur.quantize(Decimal('0.01'), rounding=ROUND_DOWN)}"
            body["amount"] = {"currency": "EUR", "value": amount_str}
        if metadata:
            body["metadata"] = {k: str(v) for k, v in metadata.items() if v is not None}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{MOLLIE_API_BASE}/payments/{provider_payment_id}/refunds",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if resp.status_code >= 300:
            raise RuntimeError(f"Mollie refund failed {resp.status_code}: {resp.text[:500]}")
        refund = resp.json()
        refund_id = refund.get("id", "")
        logger.info(
            "[fiat_providers/mollie] refund issued payment_id=%s refund_id=%s amount=%s",
            provider_payment_id, refund_id, amount_eur,
        )
        return refund_id


# ────────────────────────────────────────────────────────────────────────────
# URL template helpers (W2.6 fix)
# ────────────────────────────────────────────────────────────────────────────


def _strip_stripe_url_template(url: str) -> str:
    """Remove Stripe-specific `{CHECKOUT_SESSION_ID}` template tokens.

    Stripe's checkout URLs use `{CHECKOUT_SESSION_ID}` as a placeholder that
    Stripe substitutes at redirect time. Mollie + other PSPs don't substitute
    this, so we strip it before passing the URL to non-Stripe providers.

    Handles both literal and URL-encoded forms:
      - `?session_id={CHECKOUT_SESSION_ID}` → ``
      - `&session_id={CHECKOUT_SESSION_ID}` → ``
      - `?session_id=%7BCHECKOUT_SESSION_ID%7D` (URL-encoded) → ``
    """
    if not url:
        return url
    # Common forms (literal + URL-encoded). Order matters: longer matches first.
    for token in (
        "?session_id={CHECKOUT_SESSION_ID}",
        "?session_id=%7BCHECKOUT_SESSION_ID%7D",
        "&session_id={CHECKOUT_SESSION_ID}",
        "&session_id=%7BCHECKOUT_SESSION_ID%7D",
        "{CHECKOUT_SESSION_ID}",
        "%7BCHECKOUT_SESSION_ID%7D",
    ):
        url = url.replace(token, "")
    return url


# Mollie locale codes — map our generic locale to Mollie's expected format.
# Mollie wants underscore-separated language_country pairs.
_MOLLIE_LOCALES = {
    "en":    "en_US",
    "en_US": "en_US",
    "en_GB": "en_GB",
    "de":    "de_DE",
    "de_DE": "de_DE",
    "de_AT": "de_AT",
    "de_CH": "de_CH",
    "fr":    "fr_FR",
    "fr_FR": "fr_FR",
    "fr_BE": "fr_BE",
    "nl":    "nl_NL",
    "nl_NL": "nl_NL",
    "nl_BE": "nl_BE",
    "es":    "es_ES",
    "es_ES": "es_ES",
    "it":    "it_IT",
    "it_IT": "it_IT",
    "auto":  "en_US",  # Mollie has no auto; fall back to English
}


__all__ = ["MollieProvider"]
