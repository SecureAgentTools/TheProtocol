"""TEG contracts (AAA+ Phase II-B, 2026-05-21).

Token transfers + balances + treasury + cross-registry + admin.
Note: most TEG mutations require fixtures (primary + counterparty agents,
funded). Phase II initial wave: balance + simple transfer + admin reads.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/teg/balance", auth="agent", category="teg_integration", idempotent=True)
class TegBalance:
    """Caller's liquid + staked balance."""
    expected_status = 200


@Endpoint(method="POST", path="/teg/transfer", auth="agent", category="teg_integration", idempotent=False)
class TegTransfer:
    """Intra-registry transfer. 0.5% fee to sender's TEG fee_collector.

    Emits: TokensTransferred + TransactionFeeCollected.
    """
    def body(self, ctx):
        return {
            "receiver_agent_id": "did:theprotocol:placeholder-receiver",
            "amount": "1",
            "currency": "AVT",
        }
    expected_status = 200
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "self" in r.detail_lower(),
            reason="Self-transfer protection",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "insufficient" in r.detail_lower(),
            reason="Insufficient liquid balance",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404 and "agent" in r.detail_lower(),
            reason="Receiver agent placeholder DID does not exist",
        ),
    ]


@Endpoint(
    method="POST",
    path="/teg/transactions/batch",
    auth="agent",
    category="teg_transactions",
    idempotent=False,
)
class TegBatch:
    """Batch transactions — intentionally not implemented (returns 501)."""
    def body(self, ctx):
        return {"transactions": []}
    failures = [FailureMode.not_implemented()]
    expected_status = [501]
