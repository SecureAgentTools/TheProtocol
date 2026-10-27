"""PB-2 — HMAC sign/verify for mainframe → operator routed-settle callbacks.

When the Stripe webhook lands on mainframe and the routed-fiat flow
successfully moves AVT to the operator's treasury, mainframe POSTs a
signed callback to the operator's `/internal/fiat/routed-settle-callback`
endpoint. The signature is in Stripe-compatible format:

    X-Mainframe-Signature: t=<unix-ts>,v1=<hex>

`v1` is HMAC-SHA256 of `f"{ts}.{json.dumps(body, sort_keys=True)}"` using a
secret shared between mainframe and the operator. The secret is sourced
(in priority order):

  1. `peer_registries.callback_secret` on mainframe (set per-operator at
     activation time; rotatable by admin).
  2. Fallback: `FEDERATION_INTERNAL_SECRET` env var (sandbox shortcut so
     all sandbox operators can validate without a per-operator migration).

Mirrors the Stripe webhook signing pattern (see services/stripe_checkout.py
verify_webhook_signature) for operational familiarity.

Replay window: timestamps older than `MAX_AGE_SEC` (default 300s = 5min)
are rejected. The receiver also enforces idempotency on
`mainframe_fiat_purchase_id` UNIQUE so a replay within the window has no
side effect anyway.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


MAX_AGE_SEC = int(os.getenv("ROUTED_FIAT_CALLBACK_MAX_AGE_SEC", "300"))


def _resolve_callback_secret(peer_callback_secret: Optional[str]) -> str:
    """Pick the active secret. Per-peer column wins; falls back to env."""
    if peer_callback_secret:
        return peer_callback_secret
    fallback = os.getenv("FEDERATION_INTERNAL_SECRET", "")
    if not fallback:
        raise RuntimeError(
            "No callback secret available — peer_registries.callback_secret is "
            "NULL and FEDERATION_INTERNAL_SECRET is unset."
        )
    return fallback


def sign_callback(body: dict, peer_callback_secret: Optional[str] = None) -> Tuple[str, str]:
    """Return (header_value, payload_signed).

    The caller should send `header_value` as `X-Mainframe-Signature` and
    `payload_signed` as the request body (it's the canonical JSON we signed,
    NOT the body dict — sorted-keys + UTF-8). The receiver MUST verify on
    `payload_signed` exactly to avoid sort-order discrepancies.
    """
    secret = _resolve_callback_secret(peer_callback_secret)
    ts = str(int(time.time()))
    payload_signed = json.dumps(body, sort_keys=True, separators=(",", ":"))
    signed_target = f"{ts}.{payload_signed}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signed_target, hashlib.sha256).hexdigest()
    header_value = f"t={ts},v1={sig}"
    return header_value, payload_signed


def verify_callback(
    raw_body: bytes,
    signature_header: str,
    peer_callback_secret: Optional[str] = None,
    *,
    max_age_sec: int = MAX_AGE_SEC,
) -> dict:
    """Validate signature + freshness, return the parsed body dict on success.

    Raises ValueError on any failure (caller maps to HTTPException 401).
    """
    if not signature_header:
        raise ValueError("missing X-Mainframe-Signature header")

    # Parse 't=...,v1=...' — Stripe-compatible format
    parts = {}
    for chunk in signature_header.split(","):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip()] = v.strip()
    ts = parts.get("t")
    sig_hex = parts.get("v1")
    if not ts or not sig_hex:
        raise ValueError("malformed signature header")

    # Freshness window
    try:
        ts_int = int(ts)
    except ValueError:
        raise ValueError("non-integer timestamp")
    age = abs(int(time.time()) - ts_int)
    if age > max_age_sec:
        raise ValueError(f"signature too old: {age}s > {max_age_sec}s")

    # Recompute signature on the raw body bytes — DO NOT re-encode, callers
    # send the canonical sorted-keys-separators JSON we signed (see
    # sign_callback's payload_signed).
    secret = _resolve_callback_secret(peer_callback_secret)
    signed_target = (ts + ".").encode("utf-8") + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_target, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig_hex):
        raise ValueError("signature mismatch")

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"body is not valid JSON: {exc}")


__all__ = ["sign_callback", "verify_callback", "MAX_AGE_SEC"]
