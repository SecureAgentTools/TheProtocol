"""A 401 MUST NOT BECOME A PASS BECAUSE A LIFECYCLE SAID SO.

§RUNNERCRED 2026-09-07. Lifecycle and setup outcomes take precedence over the
per-tool contract sweep — three separate sites — and each trusts the recorded
outcome whole, `healthy` included. MEASURED on the flagship run of that morning:

    93 rows healthy with a recorded 401/403
    54 of them contracted to expect a 4xx refusal   ← real measurements, untouched
    31 whose contract expects SUCCESS               ← passes for calls that never authenticated
     8 with no contract entry

Control on the same image with a fresh credential: `getMyDeletionStatus` and
`getMyMcpAuditLog` both answer 200 with real data — so those 31 are the sweep's
own token dying mid-run (the 401 cascade documented at length in that file) being
reported as endpoint health.

The guard turns those into a loud skip rather than a pass or a failure: blaming
the tool would be the false NEGATIVE the retry exists to prevent, and passing it
is the false POSITIVE, which is worse because nobody goes looking.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    _credential_laundering_guard, classify_tool_skip,
)


def _outcome(status: int, healthy: bool = True) -> dict:
    return {"tool_name": "t", "contract_tier": "3", "healthy": healthy,
            "status_code": status, "elapsed_ms": 1, "skip_reason": None,
            "fail_reason": None}


def test_a_healthy_401_on_a_success_contract_is_refused() -> None:
    """And the reason must CARRY THE BODY rather than assert a cause: a census by
    body showed 25 of 40 were a dead token and the rest were deliberate refusal
    probes, so the row has to let the reader see which it is."""
    # getMyDeletionStatus expects success and was one of the measured 31.
    r = _credential_laundering_guard(
        {**_outcome(401), "result_excerpt": {"_text": "Error: HTTP 401: Could not validate credentials"}},
        "theprotocol_getMyDeletionStatus")
    assert r and "lifecycle recorded a 401 as healthy" in r, r
    assert "Could not validate credentials" in r, (
        "the reason must quote the response body — naming a cause instead is how "
        "the first version of this guard mislabelled the refusal probes")
    assert classify_tool_skip(r) == "lifecycle_4xx_sold_as_pass", classify_tool_skip(r)


def test_a_contracted_refusal_is_left_alone() -> None:
    """The 54 rows that MEAN to see a 4xx are measurements, not laundering."""
    r = _credential_laundering_guard(_outcome(401), "theprotocol_federationVetoProposal")
    assert r is None, (
        "a contract that expects error_4xx was rewritten as a credential skip — the "
        "guard cannot tell a pinned refusal from a dead token, which would erase 54 "
        "real measurements")


def test_a_real_pass_and_a_real_failure_are_untouched() -> None:
    assert _credential_laundering_guard(_outcome(200), "theprotocol_getMyDeletionStatus") is None
    assert _credential_laundering_guard(_outcome(401, healthy=False),
                                        "theprotocol_getMyDeletionStatus") is None, (
        "an outcome already marked unhealthy needs no rewriting — the guard exists "
        "for the ones sold as healthy")


def test_the_guard_never_breaks_the_sweep() -> None:
    """It runs inside a hot loop over ~750 tools; a raise there loses the whole run."""
    assert _credential_laundering_guard({}, "theprotocol_unknownToolThatHasNoContract") is None
    assert _credential_laundering_guard({"healthy": True, "status_code": "not-an-int"},
                                        "theprotocol_getMyDeletionStatus") is None
