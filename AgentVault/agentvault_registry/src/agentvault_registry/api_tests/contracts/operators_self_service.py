"""Operator self-service contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/operator/license/status", auth="developer", category="federation_license_(self_serve)", idempotent=True)
class LicenseStatus:
    """Caller's operator federation license status."""
    expected_status = [200, 404]


@Endpoint(method="POST", path="/operator/license/request", auth="developer", category="federation_license_(self_serve)", idempotent=False)
class LicenseRequest:
    """Request a federation license."""
    def body(self, ctx):
        return {"operator_name": "aaa-test-op", "contact_email": "aaa@theprotocol.cloud"}
    expected_status = [200, 201, 409]


@Endpoint(method="GET", path="/operator/license/audit", auth="developer", category="federation_cli_audit", idempotent=True)
class LicenseAudit:
    """tp-operator CLI audit endpoint."""
    expected_status = 200


@Endpoint(method="GET", path="/operator/portal", auth="developer", category="operator_self_service", idempotent=True)
class OperatorPortal:
    """Operator self-service portal data."""
    expected_status = 200


@Endpoint(method="POST", path="/operator/portal/heartbeat", auth="developer", category="operator_self_service", idempotent=True)
class OperatorHeartbeat:
    """Operator reports liveness."""
    def body(self, ctx):
        return {"status": "active"}
    expected_status = 200
