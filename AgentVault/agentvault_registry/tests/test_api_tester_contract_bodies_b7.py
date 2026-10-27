"""§SUITES1018 batch 7 (2026-10-19): the V0625 sweep's 33 rows that slipped from PASS to "runner gap", read.

In the V0624 sweep these rows read PASS on a 422 their own AAA+ contract earned: a body of the wrong shape, or a read
with no query string (a contract's runner builds the path alone). Batch 6 stopped passing the refusals a contract
accepts, so V0625 read them NOT MEASURED "runner gap". Read against their handlers:
- six contracts now send the route's own shape: the internal home-frame lookups (`dids`), diagnostics run-all
  (`target`, `force`), agent-builder generate (`agent_builder_type`), the root webhook store (`events`) and contract
  creation (the caller as client, one unit: escrow is taken only at accept);
- four reads (discover, the two attestation admin previews, the slash preview: a dry run) run no contract and take the
  router's query defaults;
- the rest are no call a sweep makes (credentials, money, a person's account or queue, the frame's licence, a peer
  registration, provisioning): NOT MEASURED before any contract, with what they would do. OAuth introspect and revoke
  stay runner gaps: a client of the sweep's own would make them measurable.
Two more from the same sweep: a failure now carries the route's own sentence (the rows said "HTTP 403" alone, and the
two delegation refusals were gone with the log's rotation before anyone read them), and the agent-triggered eval run's
refusal is the registry's switch (EVALS_AGENT_TRIGGER_ENABLED), a capability gate.

RED on bf45b16f (batch 7 part 5): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio

from agentvault_registry.api_tests import base as B


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


SWEEP_AGENT = "did:theprotocol:sandbox-a.theprotocol.cloud:5b2c0c3e-0000-4000-8000-00000000000a"


def _body(monkeypatch, method, path):
    from agentvault_registry.api_tests.contracts import load_all
    from agentvault_registry.api_tests.core.contract import get_contract
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did=SWEEP_AGENT))
    load_all()
    c = get_contract(method, path)
    assert c is not None and c.body_factory is not None, (method, path)
    return asyncio.run(c.body_factory())


def test_red_the_internal_lookups_send_the_routes_own_shape(monkeypatch):
    from agentvault_registry.routers.internal_agents import HomeFramesRequest
    for path in ("/internal/agents/home-frames", "/internal/agents/home-trust-domains"):
        req = HomeFramesRequest(**_body(monkeypatch, "POST", path))
        assert req.dids == [SWEEP_AGENT], path


def test_red_diagnostics_run_all_names_a_target_and_reads_the_cache(monkeypatch):
    from agentvault_registry.services.diagnostics.schemas import RunAllRequest
    req = RunAllRequest(**_body(monkeypatch, "POST", "/admin/diagnostics/run-all"))
    assert req.target and req.force is False


def test_red_agent_builder_generate_sends_the_builder_type(monkeypatch):
    from agentvault_registry import schemas
    schemas.AgentBuildConfig(**_body(monkeypatch, "POST", "/agent-builder/generate"))


def test_red_the_root_webhook_store_takes_events(monkeypatch):
    from agentvault_registry.routers.webhooks import WebhookCreate
    req = WebhookCreate(**_body(monkeypatch, "POST", "/webhooks"))
    assert "example.com" in str(req.url)


def test_red_contract_creation_names_the_caller_as_client_for_one_unit(monkeypatch):
    from agentvault_registry.routers.contracts import ContractCreate
    req = ContractCreate(**_body(monkeypatch, "POST", "/contracts/"))
    assert req.client_agent_did == SWEEP_AGENT and float(req.payment_amount) == 1.0


READS = {
    "/discover": "query=test&limit=5",
    "/attestations/admin/governance/preview-voting-power": "agent_did=" + SWEEP_AGENT,
    "/attestations/admin/mcp-passthrough/get-agent-profile": "agent_did=" + SWEEP_AGENT,
    "/admin/enforcement/agents/{agent_did}/slash-preview": "amount=1",
}


def test_red_the_query_reads_run_no_contract_and_take_the_routers_query(monkeypatch):
    from agentvault_registry.api_tests.contracts import load_all
    from agentvault_registry.api_tests.core.contract import get_contract
    from agentvault_registry.routers import admin_api_test as R
    load_all()
    dv = _SharedValues(agent_did=SWEEP_AGENT)
    for path, query in READS.items():
        assert get_contract("GET", path) is not None, path       # the contract exists; the router skips it
        assert R._contract_for("GET", path) is None, path
        q = R._REQUIRED_QUERY_DEFAULTS[path]
        assert (q(dv) if callable(q) else q) == query, path


def test_control_a_read_with_no_query_default_keeps_its_contract():
    from agentvault_registry.api_tests.contracts import load_all
    from agentvault_registry.routers import admin_api_test as R
    load_all()
    assert R._contract_for("GET", "/federation/registries") is not None


NOT_FOR_A_SWEEP = {
    ("POST", "/account/request-deletion"): "for_a_person", ("POST", "/admin/agents/bulk/suspend"): "for_a_person",
    ("POST", "/admin/agents/bulk/reinstate"): "for_a_person", ("POST", "/auth/login"): "credential",
    ("POST", "/auth/agent/token"): "credential", ("POST", "/auth/api-keys"): "credential",
    ("GET", "/docker-registry/token"): "credential", ("POST", "/bridge/transfer"): "moves_money",
    ("POST", "/fiat/proxy/checkout-session"): "moves_money", ("POST", "/onboard/create_agent"): "moves_money",
    ("POST", "/fiat/stripe-webhook"): "for_a_person", ("POST", "/bundles"): "for_a_person",
    ("POST", "/bundles/restore-from-upload"): "for_a_person", ("POST", "/bundles/{bundle_id}/rating"): "for_a_person",
    ("POST", "/bundles/{bundle_id}/report"): "for_a_person", ("POST", "/federation/cli-audit"): "for_a_person",
    ("POST", "/federation/license/rotate-self"): "frame_control", ("POST", "/federation/peers/"): "peer_standing",
    ("POST", "/operator-applications"): "for_a_person", ("POST", "/operators/self-provision"): "suite_launch",
    ("POST", "/support/tickets"): "for_a_person",
}


def test_red_the_rows_no_sweep_makes_say_what_they_would_do():
    for (m, p), kind in NOT_FOR_A_SWEEP.items():
        got, why = B._classify_frame_control(m, p)
        assert got == kind and "not a call a sweep makes" in why, (m, p, got)


def test_control_oauth_introspection_stays_a_runner_gap_and_the_reads_beside_are_measured():
    for m, p in (("POST", "/oauth/introspect"), ("POST", "/oauth/revoke"), ("GET", "/federation/peers/"),
                 ("POST", "/onboard/bootstrap/request-token"), ("GET", "/support/tickets"), ("GET", "/bundles")):
        assert B._classify_frame_control(m, p) == ("", ""), (m, p)


def test_red_a_failure_carries_the_routes_own_sentence():
    from agentvault_registry.routers import admin_api_test as R
    out = R._runner_gap_is_not_measured({"healthy": False, "expected_failure": False, "statusCode": 403,
                                         "error": "HTTP 403", "responseData": {"detail": "A developer delegates only "
                                                                               "to an agent that developer created"}})
    assert out["error"] == "HTTP 403: A developer delegates only to an agent that developer created", out


def test_control_an_error_that_already_says_more_and_a_pass_are_left_alone():
    from agentvault_registry.routers import admin_api_test as R
    said = R._runner_gap_is_not_measured({"healthy": False, "statusCode": 502, "error": "Timeout (30s)",
                                          "responseData": {"detail": "x"}})
    assert said["error"] == "Timeout (30s)"
    ok = R._runner_gap_is_not_measured({"healthy": True, "statusCode": 200, "error": None, "responseData": {}})
    assert ok["error"] is None


def test_red_the_agent_triggered_eval_switch_is_a_capability_gate(monkeypatch):
    monkeypatch.delenv("EVALS_AGENT_TRIGGER_ENABLED", raising=False)
    monkeypatch.setenv("API_TEST_TARGET_URL", "http://localhost:8000")
    reason, bucket = B._classify_capability_gate("/forge/evals/run", 403)
    assert "EVALS_AGENT_TRIGGER_ENABLED" in reason and bucket == "capability_absent"


def test_control_with_the_switch_on_the_refusal_is_a_failure(monkeypatch):
    monkeypatch.setenv("EVALS_AGENT_TRIGGER_ENABLED", "true")
    monkeypatch.setenv("API_TEST_TARGET_URL", "http://localhost:8000")
    assert B._classify_capability_gate("/forge/evals/run", 403) == ("", "")
