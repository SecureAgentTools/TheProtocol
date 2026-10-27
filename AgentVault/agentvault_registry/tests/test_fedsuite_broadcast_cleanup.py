"""§MCPTEST30 (V0558): the federation suite takes back what it says.

Each run composed four broadcasts per frame and retracted one; 733 of the 736 active broadcasts on Sandbox Alpha were
the tester's, and the newest scrolled across every sandbox console's header. Pinned: the helper reads every envelope the
compose has used, retracts with the id it read, records the outcome on the verdict and never raises; and every suite
test that composes a broadcast retracts it.
"""
import ast
import pathlib
import types

import pytest

from agentvault_registry.api_tests.federation_suite import broadcast_cleanup as bc

SUITE = pathlib.Path(bc.__file__).parent / "tests"


@pytest.mark.parametrize("resp, want", [
    ({"id": 5}, 5), ({"broadcast": {"id": "7"}}, 7), ({"data": {"broadcast_id": 9}}, 9),
    ({"result": {"id": 11}}, 11), ({"id": "x"}, None), ([], None), (None, None), ({}, None),
])
def test_composed_id_reads_every_envelope(resp, want):
    assert bc.composed_id(resp) == want


class _Mcp:
    def __init__(self, calls, fail):
        self.calls, self.fail = calls, fail

    async def call(self, tool, args):
        self.calls.append((tool, args))
        if self.fail:
            raise RuntimeError("peer down")
        return {}


class _Rig:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def mcp(self, name):
        self.calls.append(("as", name))
        return _Mcp(self.calls, self.fail)


def _result(state=None):
    return types.SimpleNamespace(passed=True, last_state=state)


@pytest.mark.asyncio
async def test_retracts_with_the_id_and_records_it():
    rig, res = _Rig(), _result({"title_marker": "m"})
    out = await bc.retract_own(rig, "sandbox-A-admin", 41, res)
    assert out is res and res.passed
    assert ("retractBroadcast", {"broadcast_id": 41}) in rig.calls and ("as", "sandbox-A-admin") in rig.calls
    assert res.last_state == {"title_marker": "m", "cleanup": "retracted #41 on sandbox-A-admin"}


@pytest.mark.asyncio
async def test_a_failed_retraction_is_recorded_never_raised():
    res = _result(None)
    await bc.retract_own(_Rig(fail=True), "sandbox-B-admin", 7, res)
    assert res.passed and res.last_state["cleanup"].startswith("not retracted: RuntimeError")


@pytest.mark.asyncio
async def test_no_id_no_call():
    rig, res = _Rig(), _result({})
    await bc.retract_own(rig, "sandbox-A-admin", None, res)
    assert rig.calls == [] and "no id" in res.last_state["cleanup"]


def test_every_suite_test_that_composes_a_broadcast_takes_it_back():
    composers = []
    for f in sorted(SUITE.glob("test_*.py")):
        for fn in ast.walk(ast.parse(f.read_text())):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            consts = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            if "composeBroadcast" in consts:
                composers.append(f"{f.name}::{fn.name}")
                assert "retract_own" in names, f"{f.name}::{fn.name} composes a broadcast and never takes it back"
    assert len(composers) >= 3, composers
