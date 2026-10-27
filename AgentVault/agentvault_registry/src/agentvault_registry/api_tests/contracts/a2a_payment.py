"""A2A payment contracts (AAA+ Phase IV-A — f045 A2A v1.0, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/a2a-payment/authorize", auth="agent", category="a2a_payment", idempotent=False)
class A2AAuthorize:
    """Caller agent authorizes a payment token (apt_...). Returns token once.

    Schema (`a2a_payment.py:AuthorizeRequest`): target_agent_did (DID of payee)
    + amount (str, AVT) + optional contract_id + ttl_seconds. The sentinel
    bootstrap agent has 0 AVT balance by default → 402 Payment Required is
    the canonical fail mode without a prior funding step.
    """
    def body(self, ctx):
        return {
            "target_agent_did": "did:theprotocol:placeholder-service",
            "amount": "1",
            "ttl_seconds": 900,
        }
    expected_status = [200, 400, 401, 402, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 402,
            reason="Insufficient balance for authorization (sentinel agent unfunded)",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Target agent placeholder DID doesn't resolve",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 401,
            reason="Agent JWT missing or rejected",
        ),
    ]


@Endpoint(method="POST", path="/a2a-payment/verify", auth="none", category="a2a_payment", idempotent=True)
class A2AVerify:
    """Verify an apt_ token. No auth needed (tokens are self-authenticating).

    Schema (`a2a_payment.py:VerifyRequest`): token (the apt_... value) + optional
    target_agent_did. Placeholder token → 404 "Token not found".
    """
    def body(self, ctx):
        return {"token": "apt_placeholder0000000000000000000000000000000000000000000000000000"}
    expected_status = [200, 400, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404, 422),
            reason="Placeholder token won't be found",
        ),
    ]


@Endpoint(method="POST", path="/a2a-payment/settle", auth="agent", category="a2a_payment", idempotent=False)
class A2ASettle:
    """Service agent settles an apt_ token (moves funds).

    Schema (`a2a_payment.py:SettleRequest`): token (apt_...) + optional task_id
    + optional success (default True). Placeholder token → 404.
    """
    def body(self, ctx):
        return {"token": "apt_placeholder0000000000000000000000000000000000000000000000000000", "success": True}
    expected_status = [200, 400, 401, 403, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404),
            reason="Placeholder token not found / not in AUTHORIZED state",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 403),
            reason="Agent JWT missing or settlement caller doesn't match target",
        ),
    ]


@Endpoint(method="POST", path="/a2a-payment/release", auth="agent", category="a2a_payment", idempotent=False)
class A2ARelease:
    """Caller agent releases (cancels) an apt_ token.

    Schema (`a2a_payment.py:SettleRequest`) — release REUSES SettleRequest
    (token + optional task_id + success). Placeholder token → 404.
    """
    def body(self, ctx):
        return {"token": "apt_placeholder0000000000000000000000000000000000000000000000000000"}
    expected_status = [200, 400, 401, 403, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404),
            reason="Placeholder token not found / not in AUTHORIZED state",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 403),
            reason="Agent JWT missing or only-the-caller check fired",
        ),
    ]


@Endpoint(method="GET", path="/a2a-payment/my-tokens", auth="agent", category="teg_integration", idempotent=True)
class A2AMyTokens:
    """List caller's outstanding apt_ tokens."""
    expected_status = 200
