"""§MCPTEST30 V0638 (agentvault2-aa, 2026-10-24): the canary row expects the events its transfer's rail writes.

Since V0636 (d700c111) lifecycle_cross_registry_canary_recipient sends its 0.01 to this frame's own operator's canary
receiver: a cross-registry transfer on one ledger, by the TEG-direct cross-teg path, which writes TokensTransferred,
CrossRegistryTransferCompleted and TransactionFeeCollected (read on sbx-alpha's ledger, transfer 5b6acf43). The row still
expected CrossFrameTransferInitiated, the frame-to-frame rail's event, and read a correct transfer as a silent no-op
(EU's History run 6166c97bca144270: a hard fail and a bug find). The first test fails on V0636's lifecycle (the
control); the second keeps the row's events among the ones the rail writes, and the third keeps the frame-to-frame
event out of that rail.
"""
from __future__ import annotations

import ast
import inspect

from agentvault_registry.api_tests.contracts import mcp_lifecycles
from agentvault_registry.routers import teg_integration

TOOL = "theprotocol_tegCrossRegistryTransferDirect"


def _expected_on_success():
    """expect_events of every _exec_step in the lifecycle that calls the tool and expects a success."""
    tree = ast.parse(inspect.getsource(mcp_lifecycles.lifecycle_cross_registry_canary_recipient))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_exec_step"):
            continue
        consts = [a.value for a in node.args if isinstance(a, ast.Constant)]
        kw = {k.arg: k.value for k in node.keywords}
        status = kw.get("expect_status")
        if TOOL in consts and isinstance(status, ast.Constant) and status.value == "success":
            found.append(ast.literal_eval(kw["expect_events"]))
    return found


def _event_types_written(fn):
    """The literal event_type values a helper passes to the emitter."""
    tree = ast.parse(inspect.getsource(fn))
    return {k.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
            for k in node.keywords if k.arg == "event_type" and isinstance(k.value, ast.Constant)}


def test_the_operator_receiver_row_expects_the_same_ledger_rail_events():
    assert _expected_on_success() == [["TokensTransferred", "CrossRegistryTransferCompleted"]]


def test_the_same_ledger_rail_writes_every_event_the_row_expects():
    written = _event_types_written(teg_integration._emit_cross_registry_events)
    for expected in _expected_on_success():
        assert set(expected) <= written, (expected, written)


def test_the_frame_to_frame_event_is_not_the_same_ledger_rails():
    assert "CrossFrameTransferInitiated" not in _event_types_written(teg_integration._emit_cross_registry_events)
    assert "CrossFrameTransferInitiated" in _event_types_written(
        teg_integration._emit_cross_frame_async_initiated_events)
