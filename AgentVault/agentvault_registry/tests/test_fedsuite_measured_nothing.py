"""§MCPTEST30 (V0649, agentvault2-d3): a federation check that passed on nothing says so on its row and in the summary.

The census of 2026-10-31: 269 branches in 92 of the 167 test files set a TOP-LEVEL flag and return True when the check's
read answered an error or nothing (`state["silent"] = True`, 225) or found nothing to check (`no_agents`, `no_did`,
`empty_list`, 44). V0549's judge reads only the per-leg form ({"<label>": {"silent": True}}), and a passed row kept no
state, so how often a pass rode such a branch could be read nowhere. REPORTED, not a verdict yet (the census earns a
ceiling first): the row's last_state names the flags (`measured_nothing`), the summary counts them (`passed_on_nothing`).
RED on V0648: decorator.measured_nothing does not exist.
"""
from __future__ import annotations

import asyncio
import pathlib
import re

from agentvault_registry.api_tests import probe_meter as pm
from agentvault_registry.api_tests.federation_suite import decorator as dec
from agentvault_registry.api_tests.federation_suite import reporter
from agentvault_registry.api_tests.federation_suite import rig as rig_mod


def _execute(state, passed=True, name="t"):
    async def runner(rig):
        pm.record_probe()
        return rig_mod.AssertionResult(passed=passed, description="the thing under test", budget_sec=1.0,
                                       elapsed_sec=0.0, polling_attempts=1, last_state=state,
                                       failure_detail=None if passed else "budget exhausted")
    spec = dec.FederationTestSpec(name=name, category="c", budget_sec=1.0, severity="low", requires=[], tags=[],
                                  runner=runner)
    return asyncio.run(dec.execute_test(spec, rig_mod.FederationTestRig()))


def test_a_pass_on_a_silent_read_stays_a_pass_and_says_so():
    o = _execute({"agent_did": "did:theprotocol:x", "silent": True})
    assert o.state == "passed"
    assert o.to_dict()["last_state"] == {"measured_nothing": ["silent"]}


def test_a_pass_on_an_empty_population_says_so():
    o = _execute({"no_agents": True})
    assert o.state == "passed" and o.to_dict()["last_state"] == {"measured_nothing": ["no_agents"]}
    assert dec.measured_nothing({"empty_list": True, "missing_did": True, "no_did": True}) == \
        ["empty_list", "missing_did", "no_did"]


def test_a_flag_that_is_not_true_and_an_unrelated_key_are_not_a_finding():
    assert dec.measured_nothing({"silent": False, "no_agents": 0, "agent_did": "did:x", "keys": ["agents"],
                                 "nothing": True, "noisy": True}) == []
    assert dec.measured_nothing(None) == [] and dec.measured_nothing(["silent"]) == []


def test_the_per_leg_form_stays_v0549s_judgment():
    # every leg silent: NOT MEASURED (unanswered), unchanged; a top-level flag beside it adds nothing to that verdict
    o = _execute({"sandbox-A": {"silent": True}, "sandbox-B": {"silent": True}})
    assert o.state == "skipped" and o.skip_code == "unanswered"
    o = _execute({"sandbox-A": {"keys": ["agents"]}, "sandbox-B": {"silent": True}, "no_dids": True})
    assert o.state == "passed"
    assert o.to_dict()["last_state"] == {"silent_legs": ["sandbox-B"], "measured_nothing": ["no_dids"]}


def test_controls_an_ordinary_pass_and_a_failure_are_unchanged():
    o = _execute({"sandbox-A": {"keys": ["agents"]}, "agent_did": "did:x"})
    assert o.state == "passed" and o.to_dict()["last_state"] is None
    o = _execute({"silent": True}, passed=False)
    assert o.state == "failed" and o.to_dict()["last_state"] == {"silent": True}


def test_the_summary_counts_the_passes_on_nothing():
    outs = [_execute({"silent": True}, name="a"), _execute({"no_agents": True}, name="b"),
            _execute({"agent_did": "did:x"}, name="c"), _execute({"silent": True}, passed=False, name="d")]
    s = reporter.aggregate(outs)
    assert s["passed_on_nothing"] == 2
    assert [(t["name"], t["flags"]) for t in s["passed_on_nothing_tests"]] == [("a", ["silent"]), ("b", ["no_agents"])]
    assert s["passed"] == 3 and s["failed"] == 1, "a report, never a verdict"


def test_the_census_the_docstring_cites_still_reads_true():
    """The branch shape the report exists for: a top-level flag set True, then `return True`. Fewer is progress (a
    check that learned to say NOT MEASURED); none at all would mean the report has nothing left to find."""
    tests = pathlib.Path(dec.__file__).parent / "tests"
    flag = re.compile(r"\[[\"'](silent|no_\w+|empty\w*|missing_\w+)[\"']\]\s*=\s*True")
    n = 0
    for f in tests.glob("test_*.py"):
        lines = f.read_text().splitlines()
        for i, ln in enumerate(lines):
            if flag.search(ln) and " ".join(x.strip() for x in lines[i + 1:i + 3]).startswith("return True"):
                n += 1
    assert 0 < n <= 269, n
