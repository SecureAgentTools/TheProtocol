"""§MCPSWEEP 2026-09-28: a federation test during which the transport lost an answer is NOT MEASURED, and capped.

An exec that comes back rc 0 with no HTTP status marker lost its answer in transit (curl prints its -w marker even
when it cannot connect). On V0481 one such loss turned a correct contract row red; a loose refusal check would have
turned it green just as easily, and 546 sites in the suite catch Exception broadly, so no per-test rule can say which.
The rig counts each loss per test, the decorator makes that test's row NOT MEASURED (skip_code transport_lost, what it
reported kept), and the skip census caps how many a run may have. agentvault2-05's proposal.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.api_tests import probe_meter as pm
from agentvault_registry.api_tests.federation_suite import decorator as dec
from agentvault_registry.api_tests.federation_suite import rig as rig_mod
from agentvault_registry.api_tests.federation_suite import skip_codes as sc


def _spec(runner):
    return dec.FederationTestSpec(name="t", category="c", budget_sec=1.0, severity="low", requires=[], tags=[],
                                  runner=runner)


def _result(passed, detail=None):
    return rig_mod.AssertionResult(passed=passed, description="the thing under test", budget_sec=1.0,
                                   elapsed_sec=0.0, polling_attempts=1, failure_detail=detail)


def _execute(runner):
    return asyncio.run(dec.execute_test(_spec(runner), rig_mod.FederationTestRig()))


def _probe_and_lose():
    pm.record_probe()
    pm.record_transport_lost()


def test_a_failed_test_that_lost_an_answer_is_not_measured():
    async def runner(rig):
        _probe_and_lose()
        return _result(False, "the refusal did not name the v2 rail")
    o = _execute(runner)
    assert o.state == "skipped" and o.skip_code == "transport_lost"
    assert "1 probe answer(s) were lost in transit" in o.skip_reason and "failed verdict" in o.skip_reason
    assert "the refusal did not name the v2 rail" in o.skip_reason


def test_a_passed_test_that_lost_an_answer_is_not_measured_either():
    async def runner(rig):
        _probe_and_lose()
        return _result(True)
    o = _execute(runner)
    assert o.state == "skipped" and o.skip_code == "transport_lost" and "passed verdict" in o.skip_reason


def test_an_uncaught_lost_answer_is_not_measured():
    async def runner(rig):
        _probe_and_lose()
        raise rig_mod.MCPError("sandbox-A", "theprotocol_getAgentToken", "none", "no HTTP status captured")
    o = _execute(runner)
    assert o.state == "skipped" and o.skip_code == "transport_lost" and "errored verdict" in o.skip_reason


def test_control_without_a_loss_a_failure_stays_red():
    async def runner(rig):
        pm.record_probe()
        return _result(False, "a real failure")
    o = _execute(runner)
    assert o.state == "failed" and o.skip_code is None


def test_control_without_a_loss_an_mcp_error_stays_errored():
    async def runner(rig):
        pm.record_probe()
        raise rig_mod.MCPError("sandbox-A", "theprotocol_getAgentToken", "500", "boom")
    assert _execute(runner).state == "errored"


def test_a_loss_belongs_to_its_own_test_only():
    async def lossy(rig):
        _probe_and_lose()
        return _result(True)

    async def clean(rig):
        pm.record_probe()
        return _result(False, "a real failure")

    async def both():
        a = await dec.execute_test(_spec(lossy), rig_mod.FederationTestRig())
        b = await dec.execute_test(_spec(clean), rig_mod.FederationTestRig())
        return a, b
    a, b = asyncio.run(both())
    assert a.state == "skipped" and b.state == "failed"


def test_a_loss_recorded_in_a_worker_thread_is_seen_by_the_test():
    async def run():
        pm.reset_probes()
        await asyncio.to_thread(pm.record_transport_lost)
        return pm.transport_lost_count()
    assert asyncio.run(run()) == 1


def test_the_census_classifies_and_caps_it():
    reason = _execute(lambda rig: _lossy_failed()).skip_reason
    assert sc.classify_skip(reason) == "transport_lost"
    ok3, _ = sc.skip_verdict({"transport_lost": 3})
    ok4, complaints = sc.skip_verdict({"transport_lost": 4})
    assert ok3 and not ok4 and any("transport_lost" in c for c in complaints)


async def _lossy_failed():
    _probe_and_lose()
    return _result(False, "x")


def test_the_rig_counts_an_exec_that_captured_no_answer(monkeypatch):
    client = rig_mod.MCPClient(rig_mod.SANDBOX_REGISTRIES["sandbox-A-admin"])

    async def _jwt():
        return "test-jwt"
    monkeypatch.setattr(client, "_ensure_jwt", _jwt)
    monkeypatch.setattr(rig_mod, "exec_in_container", lambda name, args, timeout=30: (0, ""))

    async def run():
        pm.reset_probes()
        with pytest.raises(rig_mod.MCPError):
            await client.call("getNetworkStats", {})
        return pm.transport_lost_count()
    assert asyncio.run(run()) == 1


def test_a_lost_answer_keeps_the_state_the_test_captured():
    """§MCPTEST30 (2026-09-30): round 2 from EU's console lost one answer during the A->B transfer test, and the row
    said only "budget 120.0s exhausted after 9 attempts" while the money had moved and the event was in the store.
    The verdict stays NOT MEASURED; what the predicate last saw stays on the row, as it does on a red one."""
    seen = {"receiver_gain": 11.416893, "sender_debit": 12.0, "delta_B_end": 0.51}

    async def runner(rig):
        _probe_and_lose()
        return rig_mod.AssertionResult(passed=False, description="12.0 crosses A->B", budget_sec=120.0,
                                       elapsed_sec=120.0, polling_attempts=9, last_state=seen,
                                       failure_detail="budget 120.0s exhausted after 9 attempts")
    o = _execute(runner)
    assert o.state == "skipped" and o.skip_code == "transport_lost"
    assert "budget 120.0s exhausted after 9 attempts" in o.skip_reason
    assert o.last_state == seen and o.polling_attempts == 9
    d = o.to_dict()
    assert d["last_state"] == seen and d["polling_attempts"] == 9 and d["state"] == "skipped"


def test_control_an_ordinary_skip_still_carries_no_state():
    async def runner(rig):
        pm.record_probe()
        raise rig_mod.PreconditionUnmet("no fixture on this tier")
    o = _execute(runner)
    assert o.state == "skipped" and o.skip_code != "transport_lost" and o.to_dict()["last_state"] is None


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
