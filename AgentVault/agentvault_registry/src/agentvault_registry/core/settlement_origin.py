"""The address a cross-registry settlement names as its origin (§MCPTEST30 V0639, agentvault2-aa, 2026-10-24).

A dispute ruled here against a defendant homed on another frame becomes a CrossRegistrySettlement and a slash request to
that frame (crud_disputes._process_cross_registry_compensation, retried by tasks/settlement_reconciliation). The
defendant's home takes the request only when its callback lies under an ACTIVE peer's base_url
(routers/federation_disputes.receive_slash_request), and its peers know this registry by the federation address its
signed card publishes (identity.federation_base_url: BILATERAL_PEER_URL where a stranger could dial it). The origin
named itself by FEDERATION_BASE_URL, the stack's INTERNAL federation proxy (http://sbx-beta-nginx-federation:8443), so
every peer refused every request with 400 "Callback URL must belong to a registered peer registry": no cross-frame
settlement was ever delivered (cross_registry_settlements empty on EU, ASIA and the sandbox; dispute 50 on sbx-beta,
2026-10-24 17:36Z, refused by all three of its peers).

CROSS_REGISTRY_SETTLEMENT_DELIVERY=on names the card's address. Off, the default, keeps the internal one exactly as
before. Turned on, a ruling here against a foreign defendant slashes on that frame (automatically below its own
auto-slash threshold, held for its administrator above it) and mints here: a money path that has never run, so it is
turned on frame by frame.
"""
from __future__ import annotations

import json
import os

from agentvault_registry.config import settings

FLAG = "CROSS_REGISTRY_SETTLEMENT_DELIVERY"


def delivery_on() -> bool:
    return os.getenv(FLAG, "off").strip().lower() == "on"


def internal_url() -> str:
    """The address the origin named before: the stack's own federation proxy, else BASE_URL."""
    return (settings.FEDERATION_BASE_URL or str(settings.BASE_URL)).rstrip("/")


def origin_url() -> str:
    """The address a new settlement names as its origin, and under which its callback lies."""
    if not delivery_on():
        return internal_url()
    from agentvault_registry.services.registry_card_builder import federation_base_url
    return (federation_base_url() or internal_url()).rstrip("/")


def peer_answer(peer: str, status: int, text: str = "") -> str:
    """One peer's answer to a slash request, for the settlement's error_message: its name, its status and its refusal
    sentence (a home's 400 names hosts only, never a token), so the reason a settlement waits outlives the log lines
    and a recreate (§MCPTEST30 V0640: two sandbox settlements kept only "retry_count=3" after their registry was
    recreated, agentvault2-66's read)."""
    detail = text or ""
    try:
        body = json.loads(text) if text else None
        if isinstance(body, dict):
            detail = str(body.get("detail") or body.get("title") or text)
    except ValueError:
        pass
    detail = " ".join(detail.split())[:160]
    return f"{peer} {status}" + (f": {detail}" if detail else "")


def answers_note(answers: list) -> str:
    """The peers' answers joined, bounded."""
    return "; ".join(answers)[:600]
