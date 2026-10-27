"""PB-3 W6 — Prometheus metrics for fiat providers.

Per Webhook_Fiat_Layer_Strategy.md v2 §11.1. Counters + histograms for
inbound webhook health, per-PSP success/failure rates, and fulfilment
latency. Wired into:

  - _process_provider_webhook → _WEBHOOK_RECEIVED_TOTAL, _SIGNATURE_FAILED_TOTAL,
    _PARSE_FAILED_TOTAL, _IDEMPOTENT_REPLAY_TOTAL
  - _handle_checkout_completed → _PURCHASE_COMPLETED_TOTAL, _FULFILMENT_DURATION
  - _handle_charge_refunded    → _PURCHASE_REFUNDED_TOTAL
  - _handle_charge_disputed    → _PURCHASE_DISPUTED_TOTAL
  - _handle_checkout_expired   → _PURCHASE_FAILED_TOTAL (label: reason=expired)

Try-import pattern with None fallbacks — preserves the runtime when
prometheus_client isn't installed (per existing routers/a2a_payment.py
precedent).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


try:
    from prometheus_client import Counter, Histogram

    _PROM_AVAILABLE = True

    FIAT_PROVIDER_WEBHOOK_RECEIVED_TOTAL = Counter(
        "fiat_provider_webhook_received_total",
        "Inbound fiat-provider webhooks received (after dispatch routing)",
        labelnames=["provider", "event_kind"],
    )
    FIAT_PROVIDER_SIGNATURE_FAILED_TOTAL = Counter(
        "fiat_provider_signature_failed_total",
        "Webhook signature verification failures (potential attack OR key rotation drift)",
        labelnames=["provider"],
    )
    FIAT_PROVIDER_PARSE_FAILED_TOTAL = Counter(
        "fiat_provider_parse_failed_total",
        "Webhook body parse failures (malformed payload from PSP)",
        labelnames=["provider"],
    )
    FIAT_PROVIDER_IDEMPOTENT_REPLAY_TOTAL = Counter(
        "fiat_provider_idempotent_replay_total",
        "Webhook L1 idempotency replays (PSP retries that we already processed)",
        labelnames=["provider"],
    )

    FIAT_PROVIDER_PURCHASE_COMPLETED_TOTAL = Counter(
        "fiat_provider_purchase_completed_total",
        "Successful AVT-credit completions",
        labelnames=["provider", "anonymous", "routed"],
    )
    FIAT_PROVIDER_PURCHASE_FAILED_TOTAL = Counter(
        "fiat_provider_purchase_failed_total",
        "Failed purchases (PSP rejected, expired, fund waterfall failed)",
        labelnames=["provider", "reason"],
    )
    FIAT_PROVIDER_PURCHASE_REFUNDED_TOTAL = Counter(
        "fiat_provider_purchase_refunded_total",
        "Refunds flagged (AVT NOT auto-clawed per Commander doctrine)",
        labelnames=["provider"],
    )
    FIAT_PROVIDER_PURCHASE_DISPUTED_TOTAL = Counter(
        "fiat_provider_purchase_disputed_total",
        "Chargebacks / disputes flagged (no auto-enforcement)",
        labelnames=["provider"],
    )

    FIAT_PROVIDER_FULFILMENT_DURATION_SECONDS = Histogram(
        "fiat_provider_fulfilment_duration_seconds",
        "End-to-end fulfilment latency: webhook arrival → AVT credited",
        labelnames=["provider"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
    )

except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False
    FIAT_PROVIDER_WEBHOOK_RECEIVED_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_SIGNATURE_FAILED_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_PARSE_FAILED_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_IDEMPOTENT_REPLAY_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_PURCHASE_COMPLETED_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_PURCHASE_FAILED_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_PURCHASE_REFUNDED_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_PURCHASE_DISPUTED_TOTAL = None  # type: ignore[assignment]
    FIAT_PROVIDER_FULFILMENT_DURATION_SECONDS = None  # type: ignore[assignment]


# ── Safe increment helpers (no-op when prometheus_client unavailable) ────


def inc_webhook_received(provider: str, event_kind: str) -> None:
    if FIAT_PROVIDER_WEBHOOK_RECEIVED_TOTAL is not None:
        try:
            FIAT_PROVIDER_WEBHOOK_RECEIVED_TOTAL.labels(provider=provider, event_kind=event_kind).inc()
        except Exception:
            pass


def inc_signature_failed(provider: str) -> None:
    if FIAT_PROVIDER_SIGNATURE_FAILED_TOTAL is not None:
        try:
            FIAT_PROVIDER_SIGNATURE_FAILED_TOTAL.labels(provider=provider).inc()
        except Exception:
            pass


def inc_parse_failed(provider: str) -> None:
    if FIAT_PROVIDER_PARSE_FAILED_TOTAL is not None:
        try:
            FIAT_PROVIDER_PARSE_FAILED_TOTAL.labels(provider=provider).inc()
        except Exception:
            pass


def inc_idempotent_replay(provider: str) -> None:
    if FIAT_PROVIDER_IDEMPOTENT_REPLAY_TOTAL is not None:
        try:
            FIAT_PROVIDER_IDEMPOTENT_REPLAY_TOTAL.labels(provider=provider).inc()
        except Exception:
            pass


def inc_purchase_completed(provider: str, *, anonymous: bool, routed: bool) -> None:
    if FIAT_PROVIDER_PURCHASE_COMPLETED_TOTAL is not None:
        try:
            FIAT_PROVIDER_PURCHASE_COMPLETED_TOTAL.labels(
                provider=provider,
                anonymous="true" if anonymous else "false",
                routed="true" if routed else "false",
            ).inc()
        except Exception:
            pass


def inc_purchase_failed(provider: str, *, reason: str) -> None:
    if FIAT_PROVIDER_PURCHASE_FAILED_TOTAL is not None:
        try:
            FIAT_PROVIDER_PURCHASE_FAILED_TOTAL.labels(provider=provider, reason=reason).inc()
        except Exception:
            pass


def inc_purchase_refunded(provider: str) -> None:
    if FIAT_PROVIDER_PURCHASE_REFUNDED_TOTAL is not None:
        try:
            FIAT_PROVIDER_PURCHASE_REFUNDED_TOTAL.labels(provider=provider).inc()
        except Exception:
            pass


def inc_purchase_disputed(provider: str) -> None:
    if FIAT_PROVIDER_PURCHASE_DISPUTED_TOTAL is not None:
        try:
            FIAT_PROVIDER_PURCHASE_DISPUTED_TOTAL.labels(provider=provider).inc()
        except Exception:
            pass


def observe_fulfilment_duration(provider: str, duration_seconds: float) -> None:
    if FIAT_PROVIDER_FULFILMENT_DURATION_SECONDS is not None:
        try:
            FIAT_PROVIDER_FULFILMENT_DURATION_SECONDS.labels(provider=provider).observe(duration_seconds)
        except Exception:
            pass


__all__ = [
    "_PROM_AVAILABLE",
    "inc_webhook_received",
    "inc_signature_failed",
    "inc_parse_failed",
    "inc_idempotent_replay",
    "inc_purchase_completed",
    "inc_purchase_failed",
    "inc_purchase_refunded",
    "inc_purchase_disputed",
    "observe_fulfilment_duration",
]
