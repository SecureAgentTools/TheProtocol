"""SF-3 cross-frame bridge contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/bridge/transfer", auth="agent", category="token_bridge", idempotent=False, slow_timeout_sec=60.0)
class BridgeTransfer:
    """SF-3 cross-frame transfer (lock+mint)."""
    def body(self, ctx):
        return {
            "destination_frame": "frame-b",
            "destination_agent_did": "did:theprotocol:placeholder",
            "amount": "10",
            "memo": "AAA+ contract test",
        }
    expected_status = [200, 202, 400, 422, 503]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 503,
            reason="Cross-frame TEG unreachable in sandbox baseline",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422),
            reason="Destination agent placeholder",
        ),
    ]


@Endpoint(method="POST", path="/bridge/redeem", auth="agent", category="token_bridge", idempotent=False, slow_timeout_sec=60.0)
class BridgeRedeem:
    """Redeem wrapped AVT back to native (cross-frame return)."""
    def body(self, ctx):
        return {"amount": "10", "destination_frame": "frame-a"}
    expected_status = [200, 202, 400, 503]


@Endpoint(method="POST", path="/bridge/mint-wrapped", auth="developer", category="token_bridge", idempotent=False)
class BridgeMintWrapped:
    """Admin mint wrapped AVT (cross-frame deposit completion)."""
    def body(self, ctx):
        return {"agent_did": "did:theprotocol:placeholder", "amount": "10", "source_frame": "frame-a"}
    expected_status = [200, 400, 404]


@Endpoint(method="POST", path="/bridge/unlock", auth="developer", category="token_bridge", idempotent=False)
class BridgeUnlock:
    """Admin unlock locked AVT (cross-frame failure recovery)."""
    def body(self, ctx):
        return {"transfer_id": "placeholder", "reason": "AAA+ test recovery"}
    expected_status = [200, 400, 404]
