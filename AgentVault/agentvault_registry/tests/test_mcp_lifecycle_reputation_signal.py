"""§MCPSWEEP 2026-09-28 — applyReputationSignal's success leg: the sentinel signals +1 on its own seed transfer.

agentvault2-a4's §FINDINGS-A4 fix (e74def71) gated the route on `teg.transfer`, which the sentinel holds, and the TEG lets a
transfer's SENDER signal it once. So the EigenTrust lifecycle signals +1 on the first seed transfer of the run. Outcomes
are keyed by tool and that lifecycle runs LAST, so the leg must never overwrite the refusal probe's row: a refusal that
regressed into an acceptance would be masked by a later success. These tests drive the REAL `_exec_step` through the
helper with a fake RPC layer; every control is built so the wrong behaviour would fail it.
"""
from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.contracts import mcp_lifecycles as ml  # noqa: E402
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    _parse_rpc_result,
)

TOOL = "theprotocol_applyReputationSignal"
TX = "7f1c2d3e-0000-4000-8000-00000000abcd"
LIFECYCLES = Path(ml.__file__)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    # asyncio.run() leaves the thread with no current loop; put one back for the next file.
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _ok_envelope():
    return {"jsonrpc": "2.0", "id": 1, "result": {
        "content": [{"type": "text", "text": json.dumps({"transaction_id": TX, "signal_value": 1, "status": "applied"})}],
        "isError": False}}


def _refused_envelope():
    return {"jsonrpc": "2.0", "id": 1, "result": {
        "content": [{"type": "text", "text": "Error: applyReputationSignal returned HTTP 403: only the sender may signal"}],
        "isError": True}}


def _run(outcomes, tx, envelope, calls):
    async def rpc(tool, args, jwt="", timeout=15):
        calls.append((tool, dict(args)))
        return True, envelope, "200"
    return asyncio.run(ml._signal_own_seed_transfer(rpc, _parse_rpc_result, "sentinel-jwt", "dev-jwt", outcomes, tx))


def _refusal_row(healthy=True, fail_reason=None):
    return {"tool": TOOL, "healthy": healthy, "fail_reason": fail_reason, "marker": "the refusal probe's row"}


def test_no_transaction_makes_no_call():
    calls, outcomes = [], {}
    assert _run(outcomes, "", _ok_envelope(), calls) is None
    assert calls == [] and outcomes == {}


def test_the_leg_signals_plus_one_on_the_given_transaction_as_the_sentinel():
    calls = []
    _run({}, TX, _ok_envelope(), calls)
    (tool, args), = calls
    assert tool == TOOL and args["transaction_id"] == TX and args["signal_value"] == 1
    assert args["agent_jwt"] == "sentinel-jwt"


def test_with_no_row_yet_the_leg_records_its_own_healthy_row():
    outcomes = {}
    assert _run(outcomes, TX, _ok_envelope(), []) is True
    assert outcomes[TOOL]["healthy"] is True


def test_a_success_never_overwrites_the_refusal_row():
    row = _refusal_row()
    outcomes = {TOOL: row}
    assert _run(outcomes, TX, _ok_envelope(), []) is True
    assert outcomes[TOOL] is row and row["healthy"] is True and row["marker"] == "the refusal probe's row"


def test_a_failed_success_leg_fails_the_existing_row_and_names_why():
    row = _refusal_row()
    outcomes = {TOOL: row}
    assert _run(outcomes, TX, _refused_envelope(), []) is False
    assert outcomes[TOOL] is row and row["healthy"] is False
    assert "success leg failed" in row["fail_reason"] and TX in row["fail_reason"] and "only the sender" in row["fail_reason"]


def test_control_a_regressed_refusal_is_not_masked_by_a_later_success():
    row = _refusal_row(healthy=False, fail_reason="expected a 4xx refusal, the route ACCEPTED an unknown transaction")
    outcomes = {TOOL: row}
    assert _run(outcomes, TX, _ok_envelope(), []) is True
    assert row["healthy"] is False and "ACCEPTED an unknown transaction" in row["fail_reason"]


# ── the lifecycle wires it: the seed's own transaction id, the helper, one place ──────────────────────────────────────

def _tree():
    return ast.parse(LIFECYCLES.read_text(encoding="utf-8"))


def test_the_eigentrust_lifecycle_signals_its_own_first_seed():
    fn = next(n for n in ast.walk(_tree()) if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "lifecycle_reputation_eigentrust_setup")
    src = ast.unparse(fn)
    assert "seed_tx = str(_inner_seed.get('transaction_id') or '')" in src
    assert "await _signal_own_seed_transfer(rpc, parse, sentinel_jwt, dev_jwt, outcomes, seed_tx)" in src


def test_the_tool_constant_is_used_only_by_the_success_leg():
    # a call site naming the tool through the constant would escape the refusal-probe pins, which match literal names
    users = set()
    for fn in ast.walk(_tree()):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(isinstance(n, ast.Name) and n.id == "REPUTATION_SIGNAL_TOOL" for n in ast.walk(fn)):
                users.add(fn.name)
    assert users == {"_signal_own_seed_transfer"}, users
