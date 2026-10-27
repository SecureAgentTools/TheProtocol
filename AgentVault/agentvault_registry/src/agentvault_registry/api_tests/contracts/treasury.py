"""TEG treasury contracts (AAA+ Phase II-B, 2026-05-21).

Treasury fund-agent, mint, cross-TEG, system-transfer.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/teg/treasury/fund-agent", auth="developer", category="teg_integration", idempotent=False)
class FundAgent:
    """Treasury → agent transfer. Emits TokensTransferred."""
    def body(self, ctx):
        return {
            "agent_did": "did:theprotocol:placeholder",
            "amount": "10",
            "memo": "AAA+ contract test",
        }
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/teg/treasury/mint", auth="developer", category="teg_integration", idempotent=False)
class TreasuryMint:
    """Mint new AVT into treasury. Emits TokensIssued + TokensTransferred.

    Schema (`teg_integration.py:TreasuryMintRequest`): amount (str) + reason (str, max 256).
    target_agent_did defaults to system treasury, so omitting it is fine.
    """
    def body(self, ctx):
        return {"amount": "1000", "reason": "AAA+ contract mint"}
    expected_status = 200


@Endpoint(method="POST", path="/teg/system-transfer", auth="agent", category="teg_integration", idempotent=False)
class SystemTransfer:
    """Agent-to-system transfer (closing balance to system treasury).

    Schema (`teg_integration.py:TEGSystemTransferRequest`): amount (str) + optional purpose (str).
    Requires AGENT JWT — not developer. Endpoint is on the agent's own balance.
    """
    def body(self, ctx):
        return {
            "amount": "1",
            "purpose": "AAA+ contract test system transfer",
        }
    expected_status = [200, 400, 401, 403]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 403),
            reason="Agent JWT missing or agent has 0 balance",
        ),
    ]


@Endpoint(method="POST", path="/teg/cross-registry-transfer", auth="agent", category="teg_integration", idempotent=False)
class CrossRegistryTransfer:
    """Cross-registry AVT transfer. 0.5% fee to receiver's TEG fee_collector."""
    def body(self, ctx):
        return {
            "receiver_agent_id": "did:theprotocol:placeholder",
            "receiver_registry": "registry-test-b",
            "amount": "10",
            "currency": "AVT",
        }
    expected_status = [200, 400, 404]


@Endpoint(method="POST", path="/teg/treasury/cross-teg-fund", auth="developer", category="teg_integration", idempotent=False)
class CrossTegFund:
    """Fund a peer TEG's treasury from origin TEG (treasury-to-treasury, NOT per-agent).

    Schema (`teg_integration.py:CrossTEGTreasuryFundRequest`): target_registry (name as in
    TRUSTED_REGISTRIES) + amount (str) + reason (str) + optional correlation_id.
    Sandbox-A → Sandbox-B is the canonical test pair (both have CROSS_TEG_ENABLED).
    Endpoint is restricted to Registry-A / Sandbox-A by allowlist (origin-only).
    """
    def body(self, ctx):
        return {
            "target_registry": "Sandbox Beta",
            "amount": "10",
            "reason": "cross_teg_fund",
        }
    expected_status = [200, 400, 403, 404, 503]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404),
            reason="Target peer TEG unreachable in test env",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 503,
            reason="Cross-TEG disabled or partner-TEG unreachable",
        ),
    ]


@Endpoint(method="POST", path="/teg/treasury/receive", auth="developer", category="teg_integration", idempotent=True)
class TreasuryReceive:
    """Treasury receive handler (server-to-server)."""
    def body(self, ctx):
        return {
            "from_did": "did:theprotocol:placeholder",
            "amount": "1",
            "memo": "AAA+ contract test",
        }
    expected_status = [200, 400, 401]
