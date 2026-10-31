"""§MCPTEST30 (V0650, tester batch 1 item 2, agentvault2-d3, 2026-10-31, Guild order gwo_2015b757c94ce69138500df6): a
pass on nothing becomes a verdict, against the census that earned its ceiling.

V0649 (decorator.measured_nothing, reporter.aggregate) REPORTS a passed check whose own state says it measured nothing
(`passed_on_nothing_tests`: the test and the flags it rode). His reading of such a pass, 2026-10-19: "completly
cheated". As U1's vacuity and V0549's silent legs did, the first runs' census earns the ceiling before it gates: the
V0649 pair proof's census is CEILING below, test by test.

The verdict (nothing_verdict): a test that passed on nothing and is not in the census, or rode a flag the census did not
see it ride, is a complaint: its row is red and the suite does not succeed. A test of the census that measured something
this time is never a complaint (the suite reaching further than it did is the point), and the summary names those
(`nothing_cleared`) so the census can shrink.

Where it gates: only where the census was taken, a target torn down after its run (MCP_TESTER_EPHEMERAL_TARGET: the
nightly and proof pairs). A standing frame holds other data, so its passes on nothing are its own population: there the
verdict stays REPORTED (`nothing_gated: false`) until its own census earns a ceiling.
"""
from __future__ import annotations

import os
from typing import Any, Dict, FrozenSet, Iterable, List, Tuple

EPHEMERAL_ENV = "MCP_TESTER_EPHEMERAL_TARGET"

# The V0649 pair proof's census: test name -> the flags its pass rode there (pair nt261031x2, federation run
# 046a5d6d964c4c11, 2026-10-31 07:52Z: 10 of 588 rows, read from each passed row's own last_state). A test leaves the census
# when it learns to measure something (or to say NOT MEASURED); one that joins it is a finding first.
CEILING: Dict[str, FrozenSet[str]] = {
    "bridge_async_settle_rate_above_floor": frozenset({'no_traffic'}),
    "bridge_latency_p95_within_slo": frozenset({'no_traffic'}),
    "cloud_operator_health_envelope": frozenset({'no_ops'}),
    "cloud_operator_logs_envelope": frozenset({'no_ops'}),
    "different_users_different_sub": frozenset({'missing_sub'}),
    "federation_compliance_per_peer_lookup": frozenset({'no_drifts'}),
    "public_operator_applications_listing": frozenset({'silent'}),
    "relay_status_envelope": frozenset({'silent'}),
    "simulation_funding_preview_reachable": frozenset({'silent'}),
    "trust_score_for_picked_agent": frozenset({'silent'}),
}
CENSUS = "the V0649 pair proof's census"


def gated() -> bool:
    """True where the census was taken: a target torn down after its run."""
    return str(os.environ.get(EPHEMERAL_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def nothing_verdict(passed_on_nothing: List[Dict[str, Any]], passed: Iterable[str] = ()
                    ) -> Tuple[bool, List[str], List[str], List[str]]:
    """(ok, complaints, the names of the offending tests, the census tests that passed and measured something).

    `passed_on_nothing` is reporter.aggregate's list ({name, category, flags}), `passed` every passed test's name. ok
    is True where nothing exceeds the census, and always where the verdict is not gated (the complaints are still
    returned, to be reported)."""
    complaints: List[str] = []
    offenders: List[str] = []
    seen = set()
    for t in passed_on_nothing or []:
        name = str(t.get("name") or "")
        flags = set(str(f) for f in (t.get("flags") or []))
        seen.add(name)
        allowed = CEILING.get(name)
        if allowed is None:
            complaints.append(f"{name} passed on nothing ({', '.join(sorted(flags))}); {CENSUS} holds no such pass for it")
            offenders.append(name)
        elif flags - allowed:
            complaints.append(f"{name} passed on nothing ({', '.join(sorted(flags - allowed))}), beyond {CENSUS} "
                              f"({', '.join(sorted(allowed))})")
            offenders.append(name)
    cleared = sorted(n for n in set(passed) if n in CEILING and n not in seen)
    return (not complaints or not gated()), complaints, offenders, cleared
