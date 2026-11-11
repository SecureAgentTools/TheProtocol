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

CROSS_REGISTRY_SETTLEMENT_DELIVERY=on names the card's address. Turned on, a ruling here against a foreign defendant
slashes on that frame (automatically below its own auto-slash threshold, held for its administrator above it), and
when that frame confirms, the complainant is paid here from this registry's payout funding (the fee collector, then
the treasury): a transfer, never an issuance. A money path that has never run, so it is turned on frame by frame.

V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf (session-lead's option B): both settings say what they do. Off, the
default, no slash request goes out: the settlement records the internal address and ends at once as NOT_DELIVERED,
and the ruling's compensation says delivery is off here and nothing moved (before, the request went out under the
internal address, every peer refused it, it was retried three times and expired after 24 h: sbx-beta 24ca7222). On
with no address a stranger can dial ends the same way, naming that. A request every peer refuses (an HTTP 4xx, 404
included, 408, 425 and 429 left out) ends at once as REFUSED with each peer's answer; a transport error, a 5xx or one
of those three is retried as before. No request goes to an https peer without this registry's mTLS client certificate:
the settlement waits for the reconciliation instead. An administrator closes a settlement no peer holds (CLOSED,
routers/federation_disputes.close_settlement), after the event store shows no slash for one a request may have reached.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from agentvault_registry.config import settings

FLAG = "CROSS_REGISTRY_SETTLEMENT_DELIVERY"

# The end states V0660 (k) adds. None of them moved anything, none is retried, the confirmation's claim refuses them
# (routers/federation_disputes.UNCLAIMABLE) and the saga sweep leaves them alone (services/settlement_saga).
NOT_DELIVERED = "NOT_DELIVERED"   # no request went out: delivery is off here, or no address a peer can dial
REFUSED = "REFUSED"               # every peer refused the request (a 4xx); no peer holds it
CLOSED = "CLOSED"                 # an administrator closed it (a settlement no peer holds)
ENDED = (NOT_DELIVERED, REFUSED, CLOSED)
NOTHING_MOVED = "Nothing moved, and the complainant is not paid through this settlement."


def delivery_on() -> bool:
    return os.getenv(FLAG, "off").strip().lower() == "on"


def internal_url() -> str:
    """The address the origin named before: the stack's own federation proxy, else BASE_URL."""
    return (settings.FEDERATION_BASE_URL or str(settings.BASE_URL)).rstrip("/")


def public_url() -> str:
    """The address the card publishes (identity.federation_base_url), where a stranger can dial it; else empty."""
    from agentvault_registry.services.registry_card_builder import federation_base_url
    return (federation_base_url() or "").rstrip("/")


def origin_url() -> str:
    """The address a new settlement names as its origin, and under which its callback lies. Where no request can go
    out (why_not_delivered), it is only recorded: the internal address, as before."""
    if not delivery_on():
        return internal_url()
    return public_url() or internal_url()


def why_not_delivered() -> Optional[str]:
    """Why no slash request can go out from this registry now (a clause: "<why>, so no slash request was sent");
    None when one can."""
    if not delivery_on():
        return f"{FLAG} is off on this registry"
    if not public_url():
        return ("this registry publishes no federation address a peer can dial (BILATERAL_PEER_URL or "
                "FEDERATION_BASE_URL)")
    return None


# A 4xx that is not a final answer: the peer timed the request out (408), asks for it later (425) or is limiting its
# callers (429). Sending again may pass, so the settlement is retried, as after a 5xx or a transport error.
RETRYABLE_4XX = (408, 425, 429)

# Why a slash request is not sent to an https peer (V0660 (k) review): without this registry's own client certificate
# the peer cannot know who asks, so nothing goes out and the settlement waits for the reconciliation.
NO_CLIENT_CERT = "this registry's mTLS client certificate (its SVID) is not available"


def is_definite_refusal(status: int) -> bool:
    """A peer's answer that sending again cannot change: an HTTP 4xx (404: it does not hold the defendant), except
    408, 425 and 429. A 5xx or a transport error may pass, so the settlement is retried."""
    return 400 <= int(status) < 500 and int(status) not in RETRYABLE_4XX


def needs_client_cert(urls) -> bool:
    """Whether a slash request to these peers needs this registry's mTLS client certificate (any of them is https)."""
    return any((u or "").strip().lower().startswith("https://") for u in urls)


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
