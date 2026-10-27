"""TEG extended contracts (AAA+ Phase IV-A round 2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/teg/transactions/recent", auth="developer", category="teg_integration", idempotent=True)
class TegRecentTxs:
    """Recent transactions across all agents."""
    expected_status = 200


@Endpoint(method="GET", path="/teg/system-policies", auth="developer", category="teg_integration", idempotent=True)
class TegSystemPolicies:
    """List system-level TEG policies."""
    expected_status = 200


@Endpoint(method="GET", path="/teg/transactions/{transaction_id}", auth="developer", category="teg_transactions", idempotent=True)
class TegTxDetail:
    """Get transaction detail."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/teg/transactions/{transaction_id}/audit", auth="developer", category="teg_transactions", idempotent=True)
class TegTxAudit:
    """Get audit trail for a transaction."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/teg/disputes/{dispute_log_id}", auth="developer", category="teg_integration", idempotent=True)
class TegDisputeDetail:
    """Get TEG dispute detail."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/teg/agents/{agent_id}/reputation", auth="developer", category="teg_integration", idempotent=True)
class TegAgentReputation:
    """Get TEG-side reputation for an agent."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/teg/profile", auth="agent", category="teg_integration", idempotent=True)
class TegProfile:
    """Caller agent's TEG profile."""
    expected_status = [200, 401, 404]


# ── Staking specific (mTLS/SVID/OAuth) ──────────────────────────────────
@Endpoint(method="GET", path="/teg/integration/jwt-svid/status", auth="developer", category="teg_integration_jwt_svid", idempotent=True)
class TegJwtSvidStatus:
    """JWT-SVID integration status."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/teg/integration/mtls/status", auth="developer", category="teg_integration_mtls", idempotent=True)
class TegMtlsStatus:
    """mTLS integration status."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/teg/integration/oauth/status", auth="developer", category="teg_integration_oauth", idempotent=True)
class TegOAuthStatus:
    """OAuth integration status."""
    expected_status = [200, 404]


# ── Reputation signal endpoints ─────────────────────────────────────────
@Endpoint(method="POST", path="/token/{transaction_id}/reputation-signal", auth="agent", category="reputation_signal", idempotent=False)
class ReputationSignal:
    """Attach reputation signal to a token transaction (legacy path)."""
    def body(self, ctx):
        return {"signal_value": 1, "reason": "AAA+ contract test signal"}
    expected_status = [200, 404]


@Endpoint(method="GET", path="/reputation/{agent_did}/trust-score", auth="developer", category="reputation", idempotent=True)
class TrustScore:
    """EigenTrust trust score for an agent."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="No EigenTrust global trust vector yet for this DID",
        ),
    ]


@Endpoint(method="GET", path="/reputation/leaderboard", auth="developer", category="reputation", idempotent=True)
class ReputationLeaderboard:
    """Network-wide reputation leaderboard."""
    expected_status = 200
