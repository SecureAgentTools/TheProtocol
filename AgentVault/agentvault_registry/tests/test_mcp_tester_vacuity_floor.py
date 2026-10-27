"""§FEDSUITECRED (2026-09-23): a sweep that judged nothing must not be stored as a clean night.

§EVTYPES gave the MCP tester a vacuity floor keyed on `tool_count <= 0` — a sweep that listed nothing at all. The
nightly federation run of 2026-09-23 03:11Z found the other half: it LISTED 572 tools and JUDGED none of them
(passed 0, failed 0, skipped 572), because a rotated operator password had been left behind in one of its carriers.
`tool_count` counts the roster, not the work, so the floor stayed silent and the run was stored
`status: completed, error: null` — a refusal filed as a clean night, indistinguishable from a healthy one.

The second half of the same defect: the suite's result already CARRIED the explanation (`credential preflight failed
for 1 of 8 registry/ies … password_env=API_TEST_FED_ALPHA_PASSWORD`), and the caller overwrote `error` with None. The
only surviving copy was a log line in the TARGET registry, because the sweep is dispatched to the target and its
python runs there — which is why the console that launched it had zero `[FederationSuite]` lines to show.

The numbers below are the two REAL runs, not invented ones:
  03:11Z ea4c71b8b9ff4a21 — passed 0, failed 0, skipped 572, tool_count 572   (the refusal)
  07:43Z b5841b29f255425b — passed 571, failed 1, skipped 0, tool_count 572   (the healthy run, after the fix)
"""
import pytest

from agentvault_registry.routers.mcp_tester import vacuity_verdict

TARGET = "http://sbx-alpha-registry:8000"
REFUSAL = {"tool_count": 572, "passed": 0, "failed": 0, "skipped": 572, "pass_pct": 0.0}
HEALTHY = {"tool_count": 572, "passed": 571, "failed": 1, "skipped": 0, "pass_pct": 99.83}
PREFLIGHT_ERROR = ("credential preflight failed for 1 of 8 registry/ies -- suite NOT run. sandboxalpha -> "
                   "container=cloud-op-sbxalphaop-registry email=admin@cloud-op-sbxalphaop.dev "
                   "password_env=API_TEST_FED_ALPHA_PASSWORD")


def test_a_sweep_that_listed_tools_but_judged_none_is_vacuous():
    v = vacuity_verdict(REFUSAL, None, TARGET)
    assert v and "VACUOUS RUN" in v
    assert "572 tool(s) were listed and NONE was judged" in v
    assert TARGET in v


def test_the_flows_own_reason_is_carried_into_the_verdict():
    v = vacuity_verdict(REFUSAL, PREFLIGHT_ERROR, TARGET)
    assert "password_env=API_TEST_FED_ALPHA_PASSWORD" in v, "the reason must not stay in another container's log"
    assert "cloud-op-sbxalphaop-registry" in v


def test_with_no_reason_the_verdict_says_where_to_look_instead_of_inventing_one():
    v = vacuity_verdict(REFUSAL, None, TARGET)
    assert "TARGET registry's log" in v and "not in the console that launched" in v


def test_the_real_healthy_run_is_not_vacuous():
    assert vacuity_verdict(HEALTHY, None, TARGET) is None


@pytest.mark.parametrize("summary", [
    {"tool_count": 572, "passed": 0, "failed": 572, "skipped": 0},   # everything failed: it MEASURED
    {"tool_count": 1, "passed": 1, "failed": 0, "skipped": 0},       # one pass is a measurement
])
def test_a_sweep_that_measured_is_never_called_vacuous(summary):
    assert vacuity_verdict(summary, None, TARGET) is None


def test_an_empty_roster_still_fires_the_original_floor():
    v = vacuity_verdict({"tool_count": 0, "passed": 0, "failed": 0, "skipped": 0}, None, TARGET)
    assert v and "measured 0 tools" in v


def test_a_missing_summary_is_treated_as_having_measured_nothing():
    assert "VACUOUS RUN" in (vacuity_verdict({}, None, TARGET) or "")
    assert "VACUOUS RUN" in (vacuity_verdict(None, None, TARGET) or "")
