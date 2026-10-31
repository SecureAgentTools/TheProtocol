"""§MCPTEST30 (V0650, tester batch 1 item 2, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6): a federation
pass on nothing becomes a verdict against the census that earned its ceiling (api_tests/federation_suite/
nothing_ceiling.py): beyond the V0649 pair proof's census a pass on nothing is red, at or under it allowed; gated only
on the pairs, where the census was taken. RED on V0649's code: nothing_ceiling does not exist and the suite's success
ignores a pass on nothing.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from agentvault_registry.api_tests import probe_meter as pm
from agentvault_registry.api_tests.federation_suite import decorator as dec
from agentvault_registry.api_tests.federation_suite import nothing_ceiling as nc
from agentvault_registry.api_tests.federation_suite import reporter
from agentvault_registry.api_tests.federation_suite import rig as rig_mod
from agentvault_registry.api_tests.federation_suite import runner as runner_mod


def _execute(state, passed=True, name="t"):
    async def run(rig):
        pm.record_probe()
        return rig_mod.AssertionResult(passed=passed, description="the thing under test", budget_sec=1.0,
                                       elapsed_sec=0.0, polling_attempts=1, last_state=state,
                                       failure_detail=None if passed else "budget exhausted")
    spec = dec.FederationTestSpec(name=name, category="c", budget_sec=1.0, severity="low", requires=[], tags=[],
                                  runner=run)
    return asyncio.run(dec.execute_test(spec, rig_mod.FederationTestRig()))


@pytest.fixture
def census(monkeypatch):
    monkeypatch.setattr(nc, "CEILING", {"known": frozenset({"silent"}), "fixed_since": frozenset({"no_agents"})})


def test_on_a_pair_a_pass_beyond_the_census_is_a_complaint(census, monkeypatch):
    monkeypatch.setenv(nc.EPHEMERAL_ENV, "true")
    ok, complaints, offenders, cleared = nc.nothing_verdict(
        [{"name": "known", "flags": ["silent"]}, {"name": "new", "flags": ["no_did"]}],
        ["known", "new", "fixed_since"])
    assert not ok and offenders == ["new"] and "holds no such pass" in complaints[0]
    assert cleared == ["fixed_since"], "a census test that measured something this time is named, never a complaint"
    ok, complaints, offenders, _c = nc.nothing_verdict([{"name": "known", "flags": ["silent", "no_agents"]}], ["known"])
    assert not ok and offenders == ["known"] and "beyond the V0649" in complaints[0] and "no_agents" in complaints[0]


def test_at_or_under_the_census_is_allowed(census, monkeypatch):
    monkeypatch.setenv(nc.EPHEMERAL_ENV, "true")
    assert nc.nothing_verdict([{"name": "known", "flags": ["silent"]}], ["known"])[:3] == (True, [], [])
    assert nc.nothing_verdict([], ["known"])[:3] == (True, [], [])


def test_a_standing_frame_reports_and_never_fails(census, monkeypatch):
    monkeypatch.delenv(nc.EPHEMERAL_ENV, raising=False)
    ok, complaints, offenders, _c = nc.nothing_verdict([{"name": "new", "flags": ["silent"]}], ["new"])
    assert ok and complaints and offenders == ["new"]


def test_the_summary_carries_the_verdict(census, monkeypatch):
    monkeypatch.setenv(nc.EPHEMERAL_ENV, "true")
    outs = [_execute({"silent": True}, name="known"), _execute({"no_did": True}, name="new"),
            _execute({"agent_did": "did:x"}, name="fixed_since")]
    s = reporter.aggregate(outs)
    assert s["nothing_gated"] is True and s["nothing_ok"] is False
    assert s["nothing_offenders"] == ["new"] and s["nothing_cleared"] == ["fixed_since"]
    assert s["passed"] == 3, "the counts stay what ran; the verdict is beside them"


def test_the_runner_reddens_the_offenders_row_and_its_success():
    src = inspect.getsource(runner_mod)
    assert 'summary.get("skips_ok", True) and summary.get("nothing_ok", True)' in src
    assert '"healthy": o.state == "passed" and o.spec.name not in _over' in src
    assert 'or _over.get(o.spec.name)' in src


def test_the_census_names_registered_tests_and_known_flags():
    runner_mod._discover_tests()
    names = {s.name for s in dec.REGISTRY}
    assert len(names) > 100, "the suite's tests were not discovered"
    for name, flags in nc.CEILING.items():
        assert name in names, f"the census names no registered test: {name}"
        assert flags and all(dec._NOTHING_FLAG.match(f) for f in flags), (name, flags)
