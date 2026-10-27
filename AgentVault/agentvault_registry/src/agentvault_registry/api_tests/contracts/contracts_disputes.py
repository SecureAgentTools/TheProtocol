"""Contracts + disputes contracts (AAA+ Phase II-B, 2026-05-21).

P2P service contracts + dispute filing + admin rulings.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Contracts ────────────────────────────────────────────────────────────
@Endpoint(method="POST", path="/contracts/", auth="agent", category="contracts", idempotent=False)
class CreateContract:
    """Create a contract for a service. Caller is the client agent. §SUITES1018 batch 7: the route takes the legacy RUC
    shape (client_agent_did, which must be the caller, the scope, the repository, the acceptance criteria and the
    payment); the contract sent another shape and passed on the 422. Creating records the offer only: escrow is taken at
    accept (routers/contracts._do_accept). The sweep's own agent is the client; one unit."""
    def body(self, ctx):
        from agentvault_registry.routers.admin_api_test import DYNAMIC_VALUES
        from ..request_bodies import RequestBodies
        body = dict(RequestBodies().get_body("/contracts/") or {})
        body["client_agent_did"] = DYNAMIC_VALUES.get("agent_did") or body.get("client_agent_did")
        body["payment_amount"] = 1
        return body
    expected_status = [200, 201]


@Endpoint(
    method="POST",
    path="/contracts/{contract_id}/accept",
    auth="agent",
    category="contracts",
    idempotent=False,
)
class AcceptContract:
    """Upgrader agent accepts the contract. B1: client cannot self-accept."""
    def body(self, ctx):
        return {"upgrader_agent_did": "did:theprotocol:placeholder-upgrader"}
    expected_status = [200, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and ("self" in r.detail_lower() or "client" in r.detail_lower()),
            reason="B1 IDOR: client cannot accept their own contract",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Contract ID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/contracts/malpractice", auth="agent", category="contracts", idempotent=False)
class FileContractMalpractice:
    """File contract malpractice claim."""
    def body(self, ctx):
        return {"contract_id": "placeholder-id", "reason": "Service not delivered"}
    expected_status = [200, 201, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Contract ID placeholder",
        ),
    ]


# ── Disputes ─────────────────────────────────────────────────────────────
@Endpoint(method="POST", path="/disputes/", auth="agent", category="disputes", idempotent=False)
class FileDispute:
    """File a dispute against another agent."""
    def body(self, ctx):
        return {
            "defendant_did": "did:theprotocol:placeholder-defendant",
            "dispute_type": "SERVICE",
            "description": "AAA+ contract test dispute",
        }
    expected_status = [200, 201, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "self" in r.detail_lower(),
            reason="Self-dispute protection",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Defendant DID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/disputes/enhanced/log", auth="agent", category="disputes_enhanced", idempotent=False)
class LogEnhancedDispute:
    """Log a TITANIUM VAULT D2 enhanced dispute."""
    def body(self, ctx):
        return {
            "defendant_agent_id": "did:theprotocol:placeholder-defendant",
            "reason_code": "SERVICE_FAILURE",
            "brief_description": "AAA+ contract test",
        }
    expected_status = [200, 201, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Defendant DID placeholder",
        ),
    ]


@Endpoint(
    method="PUT",
    path="/admin/disputes/{dispute_id}/ruling",
    auth="developer",
    category="admin",
    idempotent=False,
)
class RuleDispute:
    """Admin rules on a dispute."""
    def body(self, ctx):
        return {
            "ruling": "IN_FAVOR_OF_COMPLAINANT",
            "notes": "AAA+ contract test ruling",
        }
    expected_status = [200, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "closed" in r.detail_lower(),
            reason="Dispute already ruled (state-dep, idempotent healthy)",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Dispute ID placeholder",
        ),
    ]
