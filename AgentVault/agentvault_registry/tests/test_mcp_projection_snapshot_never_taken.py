"""§MCPTEST30 V0638 (agentvault2-aa, 2026-10-24; agentvault2-d6's call): a tester run never takes a projection snapshot.

The admin sweep's phase-6 list called triggerProjectionSnapshot with no argument, so on a frame with
ENABLE_PROJECTION_SNAPSHOTS on it took a real one: a snapshot re-baselines the frame's ledger projection whenever its
event fits the store's bus, and on sbx-alpha (10,254 active agents, 1,074,935 bytes) the bus refused it while the route
answered "snapshot_taken" and the outbox retried it for twelve hours, one per run (EU's History run 6166c97bca144270,
D6-818). Now: with the switch on the tool is never called and its row is NOT MEASURED by design; with it off the route's
403 is measured on a refusal row. The first test fails on V0637's sweep (the control: the probe sits in its list).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
from typing import Any, Dict, Tuple

import pytest

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as adm
from agentvault_registry.routers import admin_health

SNAP = "theprotocol_triggerProjectionSnapshot"
REFUSAL_ROW = "refusal: triggerProjectionSnapshot with its switch off"


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else {}


class _Rpc:
    """A bridge that answers from a script: tool -> (ok, result, http code), and keeps every call."""

    def __init__(self, answers: Dict[str, Tuple[bool, Dict[str, Any], str]]):
        self.answers, self.calls = answers, []

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append(tool)
        ok, result, code = self.answers.get(tool, (False, {"_text": "Error: no such tool here"}, "404"))
        return ok, {"result": result}, code


def _step(rpc, outcomes):
    asyncio.run(adm._projection_snapshot_step(rpc, _parse, "admin-jwt", outcomes))
    return outcomes


def test_the_sweep_lists_no_projection_snapshot_probe():
    src = inspect.getsource(adm.lifecycle_admin_destructive_safe)
    listed = [node.elts[0].value for node in ast.walk(ast.parse(src))
              if isinstance(node, ast.Tuple) and node.elts and isinstance(node.elts[0], ast.Constant)
              and isinstance(node.elts[0].value, str)]
    assert "theprotocol_acceptComplianceBaseline" in listed          # the list is the one read
    assert SNAP not in listed
    assert "_projection_snapshot_step(" in src


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE"])
def test_with_the_switch_on_the_tool_is_never_called(monkeypatch, value):
    monkeypatch.setenv("ENABLE_PROJECTION_SNAPSHOTS", value)
    rpc = _Rpc({SNAP: (True, {"status": "snapshot_taken"}, "200")})
    out = _step(rpc, {})
    assert rpc.calls == []
    assert list(out) == [SNAP] and "NOT MEASURED by design" in out[SNAP]["skip_reason"]


@pytest.mark.parametrize("value", [None, "", "false", "0", "off"])
def test_with_the_switch_off_the_403_is_measured(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ENABLE_PROJECTION_SNAPSHOTS", raising=False)
    else:
        monkeypatch.setenv("ENABLE_PROJECTION_SNAPSHOTS", value)
    rpc = _Rpc({SNAP: (False, {"_text": "Error: Projection snapshots disabled. Set ENABLE_PROJECTION_SNAPSHOTS=true "
                                        "to enable."}, "403")})
    out = _step(rpc, {})
    assert rpc.calls == [SNAP]
    assert out[REFUSAL_ROW]["healthy"] is True
    assert out[SNAP]["skip_reason"].startswith("NOT MEASURED: ENABLE_PROJECTION_SNAPSHOTS is off here")


def test_a_snapshot_taken_with_the_switch_off_fails_its_refusal_row(monkeypatch):
    monkeypatch.delenv("ENABLE_PROJECTION_SNAPSHOTS", raising=False)
    rpc = _Rpc({SNAP: (True, {"status": "snapshot_taken"}, "200")})
    out = _step(rpc, {})
    assert out[REFUSAL_ROW]["healthy"] is False


def test_a_row_measured_for_real_is_kept():
    kept = {SNAP: {"tool_name": SNAP, "healthy": True, "skip_reason": None}}
    rpc = _Rpc({})
    assert _step(rpc, dict(kept)) == kept and rpc.calls == []


def test_the_switch_is_read_by_the_routes_own_rule():
    rule = 'os.getenv("ENABLE_PROJECTION_SNAPSHOTS", "").lower() in ("true", "1", "yes")'
    assert rule in inspect.getsource(admin_health.take_projection_snapshot)
    assert rule in inspect.getsource(adm._projection_snapshots_on)
