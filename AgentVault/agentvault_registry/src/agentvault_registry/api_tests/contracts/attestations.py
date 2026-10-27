"""ZKP attestation contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/attestations/submit", auth="agent", category="attestations", idempotent=False)
class AttestationSubmit:
    """Submit a ZKP attestation."""
    def body(self, ctx):
        return {
            "circuit_id": "test-circuit",
            "proof_data": {"proof": "test-proof", "public_inputs": {"input1": "v1"}},
            "public_inputs": {"input1": "v1"},
        }
    expected_status = [200, 201, 400, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422),
            reason="Invalid proof / unknown circuit",
        ),
    ]


@Endpoint(method="GET", path="/attestations/circuits", auth="developer", category="attestations", idempotent=True)
class AttestationCircuits:
    """List registered ZKP circuits."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/attestations/{attestation_id}",
    auth="developer",
    category="attestations",
    idempotent=True,
)
class AttestationDetail:
    """Get attestation by ID."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Attestation ID placeholder",
        ),
    ]


@Endpoint(
    method="GET",
    path="/attestations/{attestation_id}/bundle",
    auth="developer",
    category="attestations",
)
class AttestationBundle:
    """Signed attestation bundle."""
    expected_status = [200, 404]


@Endpoint(
    method="GET",
    path="/attestations/{attestation_id}/verify",
    auth="developer",
    category="attestations",
)
class AttestationVerify:
    """Verify attestation signature."""
    expected_status = [200, 404]


@Endpoint(
    method="POST",
    path="/attestations/{attestation_id}/revoke",
    auth="developer",
    category="attestations",
    idempotent=False,
)
class AttestationRevoke:
    """Revoke an attestation."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test"}
    expected_status = [200, 404]


@Endpoint(method="GET", path="/attestations/schedules", auth="developer", category="attestations", idempotent=True)
class AttestationSchedules:
    """List recurring attestation schedules."""
    expected_status = 200


@Endpoint(method="POST", path="/attestations/schedules", auth="developer", category="attestations", idempotent=False)
class CreateAttestationSchedule:
    """Create a recurring attestation schedule."""
    def body(self, ctx):
        return {
            "circuit_id": "test-circuit",
            "interval_hours": 24,
            "agent_did": "did:theprotocol:placeholder",
        }
    expected_status = [200, 201, 400, 404]


@Endpoint(
    method="DELETE",
    path="/attestations/schedules/{schedule_id}",
    auth="developer",
    category="attestations",
)
class DeleteAttestationSchedule:
    """Delete a schedule."""
    expected_status = [200, 204, 404]


# ── Admin attestation endpoints ──────────────────────────────────────────
@Endpoint(method="POST", path="/attestations/admin/run-expiry-sweep", auth="developer", category="attestations", idempotent=True)
class RunExpirySweep:
    """Force expiry sweep across all attestations."""
    def body(self, ctx):
        return {}
    expected_status = [200, 403]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 403,
            reason="Cron auth required (admin needs special token)",
        ),
    ]


@Endpoint(method="POST", path="/attestations/admin/run-schedule-cron", auth="developer", category="attestations", idempotent=True)
class RunScheduleCron:
    """Force the schedule cron to fire."""
    def body(self, ctx):
        return {}
    expected_status = [200, 403]
