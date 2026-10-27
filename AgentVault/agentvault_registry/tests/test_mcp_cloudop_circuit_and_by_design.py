"""§MCPTEST30 (V0640): an operator run picks an active circuit, and says a mainframe-only refusal by design on its row.

V0640's tester on V0638's operators (2026-10-24 23:11-23:19Z) read 89 refusal-only rows per operator. Two causes in the
operator sweep itself:
* the operator bootstrap never read a circuit (the frame's reads one in phase 4), so lifecycle_attestation_schedule
  returned before its first step and createAttestationSchedule / disableMyAttestationSchedule passed on a made-up id
  alone, on operators that serve the catalog with ZKP_PHASE_5_ENABLED on by default;
* about 45 mainframe-only admin tools the operator refuses by construction were passes on a refusal alone, which the
  tester router gives its generic refusal-only sentence (V0636), so they read like the real gaps beside them.
Pinned: the pick takes the first ACTIVE circuit (a retired one is refused 400), names an operator that lists none, and
learns nothing from a read with no list; the sweep publishes it; a by-construction row is NOT MEASURED by design with
the operator's words, which the router leaves as it is, while a bare refusal pass is still refusal-only (control).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.routers import mcp_tester as mt


def _answer(obj, ok=True, code="200"):
    return ok, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                       "structuredContent": obj}}, code


def _pick(answer):
    seen = []

    async def call(target, tool, args, jwt="", timeout=30):
        seen.append((tool, dict(args), jwt))
        return answer
    return asyncio.run(F.cloudop_pick_circuit(call, "op-target", "dev-jwt")), seen


def test_the_first_active_circuit_is_picked_never_a_retired_one():
    (cid, why), seen = _pick(_answer({"circuits": [
        {"circuit_id": "fairMarkupPolicy/v1.0.0", "status": "retired", "superseded_by": "fairMarkupPolicy/v2.0.0"},
        {"circuit_id": "fairMarkupPolicy/v2.0.0", "status": "active"},
        {"circuit_id": "proofOfStake/v2.0.0", "status": "active"}]}))
    assert (cid, why) == ("fairMarkupPolicy/v2.0.0", None)
    assert seen == [("theprotocol_getCircuits", {}, "dev-jwt")]


def test_an_operator_listing_no_active_circuit_is_named():
    (cid, why), _ = _pick(_answer({"circuits": [{"circuit_id": "x/v1.0.0", "status": "retired"}]}))
    assert cid is None and why == F._CLOUDOP_NO_CIRCUIT


@pytest.mark.parametrize("answer", [
    _answer({"error": "circuits answered HTTP 503"}),
    (False, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "boom"}}, "500"),
])
def test_a_read_with_no_list_learns_nothing(answer):
    assert _pick(answer)[0] == (None, None)


def _sweep_tree():
    return ast.parse(textwrap.dedent(inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)))


def test_the_sweep_publishes_the_circuit():
    tree = _sweep_tree()
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "cloudop_pick_circuit"]
    assert len(calls) == 1
    stores = {n.slice.value for n in ast.walk(tree) if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store)
              and isinstance(getattr(n, "slice", None), ast.Constant)}
    assert "circuit_id" in stores


def test_a_by_construction_refusal_is_said_by_design_in_the_operators_words():
    s = F.cloudop_by_construction_reason("mainframe_only:", 404)
    assert s.startswith("NOT MEASURED on a cloud operator, by design: a mainframe-only tool")
    assert "'mainframe_only:'" in s and "HTTP 404" in s


def test_the_sweep_files_it_not_measured():
    """The `_phrase` branch assigns (cloudop_by_construction_reason(...), False): read off the sweep's AST."""
    found = []
    for n in ast.walk(_sweep_tree()):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple) and len(n.value.elts) == 2
                and isinstance(n.value.elts[0], ast.Call)
                and getattr(n.value.elts[0].func, "id", "") == "cloudop_by_construction_reason"):
            found.append(n.value.elts[1])
    assert len(found) == 1 and isinstance(found[0], ast.Constant) and found[0].value is False


def test_the_router_leaves_the_by_design_row_and_still_catches_a_bare_refusal_pass():
    by_design = {"tool": "theprotocol_revokeFrame", "tier": "admin-bridge", "healthy": False, "status": 404,
                 "skip_reason": F.cloudop_by_construction_reason("mainframe_only:", 404), "switched_off": None}
    bare = {"tool": "theprotocol_blacklistRegistry", "tier": "admin-bridge", "healthy": True, "status": 404,
            "skip_reason": None, "switched_off": None}
    assert mt._refusal_only([by_design, bare]) == [1], "only the bare refusal pass is refusal-only"
    rows, summary, skipped = [dict(by_design), dict(bare)], {"passed": 1, "skipped": 1, "tool_count": 2}, []
    assert mt._apply_refusal_only(rows, summary, skipped) == 1
    assert rows[0]["skip_reason"].startswith("NOT MEASURED on a cloud operator, by design"), "its own reason stays"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
