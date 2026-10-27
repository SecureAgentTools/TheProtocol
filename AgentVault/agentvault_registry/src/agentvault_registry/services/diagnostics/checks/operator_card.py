"""One of this frame's operators, as its signed registry card says (§MCPTEST30 V0562).

The card the federation fan-out fetched and verified (peer_registries.cached_registry_card, card_signature_verified:
the JWS against the operator's own keys AND the 3-way SPIFFE match): a card that no longer verifies is a finding; a
release other than this registry's is said (an operator a release behind its frame runs code the frame has moved past),
never failed. No Docker socket and no new dial.
"""

import re
import time

from ..schemas import CheckResult

CHECK_ID = "operator-card"
TITLE = "Operator's signed card"
DESCRIPTION = "This frame's operator publishes a card that verifies, and runs this registry's release."
CATEGORY = "config"
COST_MS = 20

_VERSION = re.compile(r"V(\d{3,6})$")


def applies(target: dict) -> bool:
    return target.get("role") == "operator" and bool(target.get("peer_registry_id"))


def _version(tag) -> str:
    m = _VERSION.search(str(tag or ""))
    return f"V{m.group(1)}" if m else ""


async def run(target: dict, probe) -> CheckResult:
    from agentvault_registry.core.registry_identity import BUNDLED_IMAGE_TAG
    from .operator_federation_reach import load_peer
    started = time.monotonic()

    def result(status, summary, **kw):
        return CheckResult(check_id=CHECK_ID, target=target["operator_id"], status=status,
                           latency_ms=int((time.monotonic() - started) * 1000), summary=summary, **kw)

    try:
        peer = await load_peer(int(target["peer_registry_id"]))
    except Exception as e:  # noqa: BLE001
        return result("unknown", f"not measured: the peer row could not be read ({type(e).__name__})")
    if peer is None:
        return result("unknown", "not measured: the peer row is gone")
    card = peer.cached_registry_card if isinstance(peer.cached_registry_card, dict) else None
    if not card:
        return result("unknown", "not measured: no card fetched from this operator yet")
    ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    theirs, ours = _version(ident.get("software_version")), _version(BUNDLED_IMAGE_TAG)
    pulled = peer.card_last_pulled_at.isoformat() if getattr(peer, "card_last_pulled_at", None) else None
    details = {"software_version": ident.get("software_version"), "this_registry": BUNDLED_IMAGE_TAG,
               "signature_verified": bool(peer.card_signature_verified), "kid": peer.card_signature_kid,
               "card_last_pulled_at": pulled}
    if not peer.card_signature_verified:
        return result("fail", "its card does not verify (signature or SPIFFE match): this frame cannot trust what it "
                              "publishes", details=details)
    if theirs and ours and theirs != ours:
        return result("warn", f"runs {theirs}, this registry {ours}", details=details)
    return result("ok", f"card verified{f', runs {theirs}' if theirs else ''}", details=details)
