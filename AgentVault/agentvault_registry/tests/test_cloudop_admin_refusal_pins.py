"""§MCPTEST30 (V0551): the operator admin sweep judges a refusal pin; only a success contract with no shape is a gap.

V0550 pinned 81 admin tools to the refusal of their own deliberately-invalid probe (expect_status error_4xx/error plus
the phrase, override_coverage_fan). override_coverage_fan drops the tool's fan row on an operator, and the sweep's gap
rule then read "no expect_keys" as "nothing to judge by": sandboxalpha went 93 -> 166 skipped in round 17
(ecb25f93d121425c, "cloud-op admin contract_gap"), 73 of them tools that had passed in round 16. A refusal contract
has no expect_keys by design; _evaluate_contract judges it by status class and phrase, and still refuses a bare one.
"""
from __future__ import annotations

import ast
import inspect

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS, McpContract, McpFixtureBag

_BAG = McpFixtureBag(sentinel_did="did:theprotocol:test", sentinel_jwt="x")
PIN = "theprotocol_recordAgentOffense"


def _wrapped(text: str) -> dict:
    return {"result": {"content": [{"type": "text", "text": text}]}}


def test_every_refusal_pin_without_a_shape_is_judged_not_a_gap():
    pins = [t for t, c in MCP_CONTRACTS.items()
            if c.expect_status in F._REFUSAL_STATUSES and not c.expect_keys and not c.skip_reason]
    assert len(pins) >= 81, f"the V0550 pins are the population this rule exists for ({len(pins)})"
    assert PIN in pins
    assert [t for t in pins if F._cloudop_admin_contract_gap(MCP_CONTRACTS[t])] == []
    # control: a success contract with nothing to hold the answer to is still a gap, one with a shape is not
    assert F._cloudop_admin_contract_gap(McpContract(tier="admin", expect_status="success"))
    assert F._cloudop_admin_contract_gap(McpContract(tier="admin", expect_status="any"))
    assert not F._cloudop_admin_contract_gap(McpContract(tier="admin", expect_status="success", expect_keys=["ok"]))


def test_a_judged_pin_passes_on_its_phrase_and_fails_on_another():
    c = MCP_CONTRACTS[PIN]
    ok, fail = F._evaluate_contract({"name": PIN}, c, False, "404",
                                    _wrapped("Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
                                    _BAG)
    assert ok is True and fail is None, fail
    # another refusal is a failure: the row would measure something else
    ok, fail = F._evaluate_contract({"name": PIN}, c, False, "403", _wrapped("Error: HTTP 403: Not authorized"), _BAG)
    assert ok is False and "expected error message" in fail
    # a 2xx where the pin expects the refusal is a failure, never a pass
    ok, fail = F._evaluate_contract({"name": PIN}, c, True, "200", _wrapped('{"status": "recorded"}'), _BAG)
    assert ok is False and "expected error_4xx" in fail
    # lifting the gap does not wave a BARE refusal through: the evaluator refuses the banned pattern
    ok, fail = F._evaluate_contract({"name": PIN}, McpContract(tier="admin", expect_status="error_4xx"), False, "404",
                                    _wrapped("Error: HTTP 404: anything"), _BAG)
    assert ok is False and fail.startswith("banned pattern")
    assert not F._cloudop_admin_contract_gap(McpContract(tier="admin", expect_status="error_4xx"))


def test_the_operator_sweep_asks_the_rule():
    tree = ast.parse(inspect.getsource(F))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_cloudop_admin_contract_gap"]
    assert len(calls) == 1, "the operator admin sweep's gap rule is this predicate, asked once"
    # the old question is gone from the sweep: no `if not admin_default.expect_keys:` decides a skip any more
    gap_tests = [n for n in ast.walk(tree) if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp)
                 and isinstance(n.test.op, ast.Not) and isinstance(n.test.operand, ast.Attribute)
                 and n.test.operand.attr == "expect_keys" and isinstance(n.test.operand.value, ast.Name)
                 and n.test.operand.value.id == "admin_default"
                 and any(isinstance(s, ast.Return) for s in n.body)]
    assert gap_tests == []
