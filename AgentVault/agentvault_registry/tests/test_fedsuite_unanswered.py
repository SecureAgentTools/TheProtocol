"""§MCPTEST30 (V0549): a federation row whose every leg answered an error or nothing is NOT MEASURED, not a pass.

116 test files carry a copy of `_is_silent_or_error` (an error text, or an empty answer) and mark such a leg
{"silent": True}; their predicates accept a silent leg as readily as an answer. So a row whose every leg answered an
error read green: cloud_op_self_logs_per_cloudop passed every night on two 503s "This feature runs on sovereign
mainframes only" (the tool it called cannot succeed anywhere). The decorator judges the state map once: every leg
silent is NOT MEASURED (skip_code `unanswered`, the legs kept as evidence), some legs silent is a pass that names
them, and skip_codes holds the census to a ceiling that may only shrink.
"""
from __future__ import annotations

import asyncio

from agentvault_registry.api_tests import probe_meter as pm
from agentvault_registry.api_tests.federation_suite import decorator as dec
from agentvault_registry.api_tests.federation_suite import rig as rig_mod
from agentvault_registry.api_tests.federation_suite import skip_codes as sc


def _execute(state, passed=True):
    async def runner(rig):
        pm.record_probe()
        return rig_mod.AssertionResult(passed=passed, description="the thing under test", budget_sec=1.0,
                                       elapsed_sec=0.0, polling_attempts=1, last_state=state,
                                       failure_detail=None if passed else "budget exhausted")
    spec = dec.FederationTestSpec(name="t", category="c", budget_sec=1.0, severity="low", requires=[], tags=[],
                                  runner=runner)
    return asyncio.run(dec.execute_test(spec, rig_mod.FederationTestRig()))


def test_a_pass_whose_every_leg_was_silent_measured_nothing():
    o = _execute({"sandboxalpha-admin": {"silent": True}, "sandboxdelta-admin": {"silent": True}})
    assert o.state == "skipped" and o.skip_code == "unanswered"
    assert o.skip_reason.startswith("unanswered: every leg answered an error or nothing (sandboxalpha-admin, "
                                    "sandboxdelta-admin)")
    row = o.to_dict()
    assert row["last_state"] == {"sandboxalpha-admin": {"silent": True}, "sandboxdelta-admin": {"silent": True}}
    assert sc.classify_skip(o.skip_reason) == "unanswered"


def test_a_pass_with_one_answered_leg_stays_a_pass_and_names_the_silent_one():
    o = _execute({"sandbox-A": {"keys": ["agents"]}, "sandbox-B": {"silent": True}})
    assert o.state == "passed" and o.skip_code is None
    assert o.to_dict()["last_state"] == {"silent_legs": ["sandbox-B"]}


def test_a_leg_kept_as_the_keys_of_an_admin_error_envelope_is_silent_too():
    """The copy-pasted helper reads the admin dispatcher's error envelope as an answer and the test keeps its keys:
    cloud_op_self_logs_per_cloudop passed that way on two 503s (sbx-alpha, 2026-10-02)."""
    env = {"keys": ["detail", "path", "status_code", "upstream_error"]}
    o = _execute({"sandboxalpha-admin": env, "sandboxdelta-admin": dict(env)})
    assert o.state == "skipped" and o.skip_code == "unanswered"
    # control: an answer's keys that are not an error envelope are an answer
    o = _execute({"sandboxalpha-admin": {"keys": ["agents", "total"]}, "sandboxdelta-admin": env})
    assert o.state == "passed" and o.to_dict()["last_state"] == {"silent_legs": ["sandboxdelta-admin"]}


def test_controls_a_pass_without_silent_legs_and_a_failure_are_unchanged():
    o = _execute({"sandbox-A": {"keys": ["agents"]}})
    assert o.state == "passed" and o.to_dict()["last_state"] is None
    # a leg map (§TWOAGENT) is kept exactly as before
    o = _execute({"legs": {"a": True, "b": 1}, "not_run": []})
    assert o.state == "passed" and o.to_dict()["last_state"] == {"legs": {"a": True, "b": True}, "not_run": []}
    # a failed row with silent legs stays red: only a PASS can be one on silence
    o = _execute({"sandbox-A": {"silent": True}}, passed=False)
    assert o.state == "failed" and o.skip_code is None
    # a leg that is not a dict (an exception's text) is not silent
    o = _execute({"sandbox-A": "error: boom", "sandbox-B": {"silent": True}})
    assert o.state == "passed"


def test_the_census_has_a_ceiling_and_only_growth_complains():
    cap = sc.BASELINE_SKIPS["unanswered"]
    assert cap == 2, "measured on sbx-alpha 2026-10-02: two rows; a ceiling moves only with a new measurement"
    assert sc.skip_verdict({"unanswered": cap})[0]
    assert sc.skip_verdict({"unanswered": max(0, cap - 3)})[0]
    ok, complaints = sc.skip_verdict({"unanswered": cap + 1})
    assert not ok and any("unanswered" in c for c in complaints)
