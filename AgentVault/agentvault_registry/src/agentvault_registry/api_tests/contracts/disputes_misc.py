"""Dispute / evidence contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(
    method="POST",
    path="/disputes/{dispute_id}/evidence",
    auth="agent",
    category="disputes",
    idempotent=False,
)
class SubmitEvidence:
    """Submit evidence to a dispute."""
    def body(self, ctx):
        return {
            "submitter_did": "did:theprotocol:placeholder",
            "evidence_data": {"type": "text", "content": "AAA+ test evidence"},
        }
    expected_status = [200, 201, 404]


@Endpoint(method="POST", path="/teg/disputes/log", auth="agent", category="teg_integration", idempotent=False)
class TegLogDispute:
    """Log a dispute against another agent on the TEG layer."""
    def body(self, ctx):
        return {
            "defendant_agent_did": "did:theprotocol:placeholder",
            "reason_code": "SERVICE_FAILURE",
            "brief_description": "AAA+ contract test",
        }
    expected_status = [200, 201, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "self" in r.detail_lower(),
            reason="Self-dispute protection",
        ),
    ]


@Endpoint(method="POST", path="/teg/attestations/submit", auth="agent", category="teg_integration", idempotent=False)
class TegSubmitAttestation:
    """Submit an attestation against another agent on the TEG layer."""
    def body(self, ctx):
        return {
            "target_agent_did": "did:theprotocol:placeholder",
            "attestation_type": "identity_verification",
            "attestation_data": {"verification_level": "basic"},
        }
    expected_status = [200, 201, 400, 404]


@Endpoint(method="POST", path="/teg/policies", auth="developer", category="teg_integration", idempotent=False)
class TegCreatePolicy:
    """Create a TEG policy."""
    def body(self, ctx):
        return {
            "policy_code": "AAA_TEST_POLICY",
            "policy_name": "AAA+ Test Policy",
            "policy_type": "governance",
            "policy_data": {"quorum_percentage": 51},
        }
    expected_status = [200, 201, 409]
