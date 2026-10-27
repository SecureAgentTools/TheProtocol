"""PB-3 FiatProvider registry.

Per Webhook_Fiat_Layer_Strategy.md v2 (2026-05-12) §3.2.

Hybrid registry pattern: first-party PSPs (Stripe, Mollie) are code-backed;
DB-backed operator-storefront providers layer on top in v1.1+.

Each PSP gates its own boot via FIAT_PROVIDER_<NAME>_ENABLED env (default false).
Stripe gets a one-time prod legacy exception: if FIAT_ONRAMP_ENABLED=true and
FIAT_PROVIDER_STRIPE_ENABLED is unset, Stripe defaults true (backwards compatibility
for current prod where only the master switch is set).
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from . import FiatProvider

logger = logging.getLogger(__name__)


_PROVIDERS: Dict[str, FiatProvider] = {}
_INIT_DONE = False


def _master_fiat_enabled() -> bool:
    """The master kill switch — FIAT_ONRAMP_ENABLED."""
    return os.getenv("FIAT_ONRAMP_ENABLED", "false").lower() == "true"


def _stripe_legacy_or_explicit_enabled() -> bool:
    """Backward-compat: if master switch is on and FIAT_PROVIDER_STRIPE_ENABLED is
    unset, Stripe defaults to enabled. This preserves prod behavior where the
    pre-PB-3 deployment only set FIAT_ONRAMP_ENABLED=true.
    """
    if not _master_fiat_enabled():
        return False
    explicit = os.getenv("FIAT_PROVIDER_STRIPE_ENABLED")
    if explicit is None or explicit == "":
        return True  # legacy implicit
    return explicit.lower() == "true"


def _provider_enabled(name: str) -> bool:
    """FIAT_PROVIDER_<NAME>_ENABLED=true|false (default false).
    Stripe inherits the legacy implicit rule above.
    """
    if name == "stripe":
        return _stripe_legacy_or_explicit_enabled()
    if not _master_fiat_enabled():
        return False
    flag = f"FIAT_PROVIDER_{name.upper()}_ENABLED"
    return os.getenv(flag, "false").lower() == "true"


def _build_registry() -> None:
    """Build the in-process provider registry from env config.

    Called once at module import. Re-callable for tests via reset().
    """
    global _PROVIDERS, _INIT_DONE
    _PROVIDERS = {}

    # Stripe — first implementer (W0). Delegates to existing services.stripe_checkout.
    if _provider_enabled("stripe"):
        try:
            from .stripe_provider import StripeProvider
            _PROVIDERS["stripe"] = StripeProvider()
            logger.info("[fiat_providers] stripe enabled")
        except Exception as exc:
            logger.error("[fiat_providers] stripe disabled — boot failure: %s", exc)

    # Mollie — second provider (W3). Gated on FIAT_PROVIDER_MOLLIE_ENABLED=true
    # AND MOLLIE_API_KEY + MOLLIE_WEBHOOK_SIGNING_SECRET env vars set.
    # See Webhook_Fiat_Layer_Strategy.md §A.11 F2: Mollie Dashboard must enable
    # Next-gen Webhooks for our HMAC verifier to accept signatures.
    if _provider_enabled("mollie"):
        # Sanity-check required env vars (boot warns; runtime fails with clear error)
        if not os.getenv("MOLLIE_API_KEY"):
            logger.warning(
                "[fiat_providers] mollie enabled by flag but MOLLIE_API_KEY unset — runtime calls will fail"
            )
        if not os.getenv("MOLLIE_WEBHOOK_SIGNING_SECRET"):
            logger.warning(
                "[fiat_providers] mollie enabled by flag but MOLLIE_WEBHOOK_SIGNING_SECRET unset — webhooks will 401"
            )
        try:
            from .mollie_provider import MollieProvider
            _PROVIDERS["mollie"] = MollieProvider()
            logger.info("[fiat_providers] mollie enabled")
        except Exception as exc:
            logger.error("[fiat_providers] mollie disabled — boot failure: %s", exc)

    # Future v1.1+: Adyen / GoCardless / Wise / Bank-SEPA-manual
    # See PRODUCTION_DOCS/ROADMAP/Webhook_Fiat_Layer_Strategy.md §1.3.

    _INIT_DONE = True
    logger.info("[fiat_providers] registry built — enabled=%s", sorted(_PROVIDERS.keys()))


def get_provider(name: str) -> Optional[FiatProvider]:
    """Return the FiatProvider implementation for `name`, or None if disabled."""
    if not _INIT_DONE:
        _build_registry()
    return _PROVIDERS.get(name.lower())


def enabled_providers() -> List[str]:
    """Return sorted list of enabled provider names."""
    if not _INIT_DONE:
        _build_registry()
    return sorted(_PROVIDERS.keys())


def reset() -> None:
    """Force re-init. For tests only."""
    global _INIT_DONE
    _INIT_DONE = False
    _build_registry()


# Initial build at import time
_build_registry()


__all__ = ["get_provider", "enabled_providers", "reset"]
