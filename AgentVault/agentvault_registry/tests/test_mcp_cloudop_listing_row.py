"""§MCPTEST30 (V0641): the operator bootstrap's own createAgoraListing call is the tool's row.

The operator sweep makes its AGORA fixture listing through createAgoraListing (an organization of the run's, the
sentinel funding it) and recorded nothing, so the tool's row was its contract's refusal on a made-up organization
alone: refusal only on both operators in V0640's previews (2026-10-24/25), while every run's census showed the listing
made and delisted. Pinned: a 2xx with a listing id is a measured success, anything else a red row saying what came
back; the sweep files it among the lifecycle rows before the lifecycles run, and the tool's contract does not pin a
refusal, so the sweep takes this row for the tool.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts.mcp_contracts import get_contract
from agentvault_registry.routers import mcp_tester as mt


def test_a_created_listing_is_the_tools_measured_success():
    row = F.cloudop_listing_row("201", {"id": "lst-1", "symbol": "CO1A2B", "treasury_agent_did": "did:theprotocol:t"},
                                42)
    assert row["tool_name"] == "theprotocol_createAgoraListing" and row["healthy"] is True
    assert row["status_code"] == 201 and not row.get("skip_reason")
    as_router_reads = {"tool": row["tool_name"], "tier": "3", "healthy": True, "status": 201, "skip_reason": None,
                       "switched_off": None}
    probe = {"tool": "theprotocol_createAgoraListing", "tier": "3", "healthy": True, "status": 404,
             "skip_reason": None, "switched_off": None}
    assert mt._refusal_only([as_router_reads, probe]) == [], "with the success in the run, no refusal-only row is left"


def test_a_create_that_did_not_make_a_listing_is_red_and_says_what_came_back():
    for code, body in (("400", {"error": "ipo_price must be positive"}), ("200", {}), ("", None)):
        row = F.cloudop_listing_row(code, body, 5)
        assert row["healthy"] is False and "with no listing id" in (row.get("fail_reason") or ""), (code, body)


def test_the_sweep_files_it_before_the_lifecycles_and_the_contract_does_not_pin_a_refusal():
    tree = ast.parse(textwrap.dedent(inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "cloudop_listing_row"]
    assert len(calls) == 1
    merged = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "update" and ast.unparse(n.func.value) == "lifecycle_outcomes"
              and ast.unparse(n.args[0]) == "_cloudop_setup_rows"]
    assert len(merged) == 1
    assert not get_contract("theprotocol_createAgoraListing").override_coverage_fan
